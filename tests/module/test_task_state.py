import unittest
import tempfile
from pathlib import Path

from module.app import DownloadStatus, TaskNode


class TaskStateStoreTestCase(unittest.TestCase):
    def test_create_update_file_and_complete_keeps_task_visible(self):
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        store = TaskStateStore(recent_limit=5)

        task = store.create_task(
            task_id=42,
            source="bot",
            task_type="package",
            chat_id=-1001,
            title="sample package",
            status=TaskStatus.CREATED,
        )
        self.assertEqual(task.task_id, "42")

        store.update_task(
            task.task_id,
            status=TaskStatus.QUEUED,
            total_count=2,
        )
        store.upsert_file(
            task.task_id,
            101,
            status=FileStatus.DOWNLOADING,
            filename="/data/tg/movie.mp4",
            total_size=100,
            downloaded_size=40,
            download_speed=10,
        )
        store.upsert_file(task.task_id, 101, status=FileStatus.UPLOADED)
        store.upsert_file(task.task_id, 102, status=FileStatus.SKIPPED)
        completed = store.complete_task(task.task_id)

        self.assertEqual(completed.status, TaskStatus.COMPLETED)
        self.assertEqual(completed.success_count, 1)
        self.assertEqual(completed.skipped_count, 1)
        self.assertEqual(completed.failed_count, 0)
        self.assertEqual(completed.upload_success_count, 1)

        payload = store.dashboard()
        self.assertEqual(payload["active_task_count"], 0)
        self.assertEqual(payload["completed_task_count"], 1)
        self.assertEqual(payload["tasks"][0]["task_id"], "42")
        self.assertEqual(payload["tasks"][0]["status"], TaskStatus.COMPLETED)

    def test_snapshot_node_uses_task_counts_and_status(self):
        from module.task_state import TaskStatus, snapshot_node

        node = TaskNode(chat_id=-1002, task_id=7)
        node.total_download_task = 3
        node.success_download_task = 1
        node.failed_download_task = 1
        node.skip_download_task = 1
        node.upload_success_count = 1
        node.download_status = {
            11: DownloadStatus.SuccessDownload,
            12: DownloadStatus.FailedDownload,
            13: DownloadStatus.SkipDownload,
        }

        snapshot = snapshot_node(
            node, source="bot", task_type="comment", title="comments"
        )

        self.assertEqual(snapshot.task_id, "7")
        self.assertEqual(snapshot.chat_id, -1002)
        self.assertEqual(snapshot.status, TaskStatus.COMPLETED_WITH_ERRORS)
        self.assertEqual(snapshot.total_count, 3)
        self.assertEqual(snapshot.success_count, 1)
        self.assertEqual(snapshot.failed_count, 1)
        self.assertEqual(snapshot.skipped_count, 1)
        self.assertEqual(snapshot.upload_success_count, 1)

    def test_upload_failed_file_is_not_regressed_by_download_snapshot(self):
        import module.task_state as task_state_module

        from module.task_state import FileStatus, TaskStateStore, TaskStatus, snapshot_node

        original_store = task_state_module._TASK_STORE
        task_state_module._TASK_STORE = TaskStateStore()
        try:
            task = task_state_module.get_task_store().create_task(
                "upload-failed",
                status=TaskStatus.COMPLETED_WITH_ERRORS,
            )
            task_state_module.get_task_store().upsert_file(
                task.task_id,
                101,
                status=FileStatus.UPLOAD_FAILED,
                save_path="/data/retained.mp4",
            )
            node = TaskNode(chat_id=-1002, task_id="upload-failed")
            node.download_status[101] = DownloadStatus.SuccessDownload

            snapshot_node(node)

            stored = task_state_module.get_task_store().get_task(task.task_id)
            self.assertEqual(stored.files["101"].status, FileStatus.UPLOAD_FAILED)
        finally:
            task_state_module._TASK_STORE = original_store

    def test_update_reactivates_a_terminal_task_for_upload_retry(self):
        from module.task_state import TaskStateStore, TaskStatus

        store = TaskStateStore()
        task = store.create_task("retry-upload", status=TaskStatus.COMPLETED_WITH_ERRORS)

        updated = store.update_task(task.task_id, status=TaskStatus.UPLOADING)

        self.assertEqual(updated.status, TaskStatus.UPLOADING)
        dashboard = store.dashboard()
        self.assertEqual(dashboard["active_task_count"], 1)
        self.assertEqual(dashboard["completed_task_count"], 0)

    def test_mask_display_name_preserves_extension(self):
        from module.task_state import mask_display_name

        self.assertEqual(mask_display_name("/data/private/movie.mp4", True), "****.mp4")
        self.assertEqual(
            mask_display_name("/data/private/movie.mp4", False), "movie.mp4"
        )
        self.assertEqual(mask_display_name("", True), "")

    def test_add_active_task_node_registers_task_snapshot(self):
        from module.download_stat import add_active_task_node, remove_active_task_node
        from module.task_state import TaskStatus, get_task_store

        store = get_task_store()
        store.clear()
        node = TaskNode(chat_id=-1003, task_id=88)
        node.total_download_task = 1

        add_active_task_node(node)

        snapshot = store.get_task("88")
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.status, TaskStatus.QUEUED)
        self.assertEqual(snapshot.total_count, 1)

        remove_active_task_node(88)

    def test_progress_callback_updates_task_and_file_snapshot(self):
        import asyncio

        from module.download_stat import add_active_task_node, update_download_status
        from module.task_state import FileStatus, TaskStatus, get_task_store

        class FakeClient:
            def stop_transmission(self):
                raise AssertionError("should not stop")

        store = get_task_store()
        store.clear()
        node = TaskNode(chat_id=-1004, task_id=89)
        add_active_task_node(node)

        asyncio.run(
            update_download_status(
                50,
                100,
                501,
                "/data/tg/demo.mp4",
                1.0,
                node,
                FakeClient(),
            )
        )

        snapshot = store.get_task("89")
        self.assertEqual(snapshot.status, TaskStatus.DOWNLOADING)
        self.assertEqual(snapshot.current_file.status, FileStatus.DOWNLOADING)
        self.assertEqual(snapshot.current_file.download_progress, 50.0)

    def test_sqlite_store_persists_task_and_files(self):
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            store = TaskStateStore(storage_path=db_path)
            task = store.create_task(
                task_id="persist-1",
                source="web",
                task_type="package",
                title="Persisted",
                status=TaskStatus.WAITING_CONFIRMATION,
                total_count=2,
            )
            store.upsert_file(task.task_id, 101, status=FileStatus.QUEUED)
            store.upsert_file(task.task_id, 102, status=FileStatus.FAILED)

            reloaded = TaskStateStore(storage_path=db_path)
            snapshot = reloaded.get_task("persist-1")

            self.assertIsNotNone(snapshot)
            self.assertEqual(snapshot.status, TaskStatus.WAITING_CONFIRMATION)
            self.assertEqual(snapshot.task_type, "package")
            self.assertEqual(len(snapshot.files), 2)

    def test_ensure_task_is_idempotent_and_does_not_regress_existing_state(self):
        from module.task_state import TaskStateStore, TaskStatus

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            store = TaskStateStore(storage_path=db_path)

            created = store.ensure_task(
                "channel-batch-fixed",
                source="web",
                task_type="channel_library",
                chat_id=-1001,
                title="Original batch",
                status=TaskStatus.QUEUED,
                total_count=2,
            )
            store.update_task(created.task_id, status=TaskStatus.DOWNLOADING)

            replayed = TaskStateStore(storage_path=db_path).ensure_task(
                "channel-batch-fixed",
                source="web",
                task_type="channel_library",
                chat_id=-1001,
                title="Original batch",
                status=TaskStatus.QUEUED,
                total_count=2,
            )

            self.assertEqual(replayed.task_id, created.task_id)
            self.assertEqual(replayed.status, TaskStatus.DOWNLOADING)
            self.assertEqual(len(TaskStateStore(storage_path=db_path).tasks()), 1)

    def test_ensure_task_preserves_matching_terminal_identity(self):
        from module.task_state import TaskStateStore, TaskStatus

        store = TaskStateStore()
        created = store.ensure_task(
            "channel-batch-terminal",
            source="web",
            task_type="channel_library",
            chat_id=-1001,
            title="Immutable batch",
            status=TaskStatus.QUEUED,
            total_count=4,
        )
        store.update_task(created.task_id, status=TaskStatus.COMPLETED)

        replayed = store.ensure_task(
            created.task_id,
            source="web",
            task_type="channel_library",
            chat_id=-1001,
            title="Immutable batch",
            status=TaskStatus.QUEUED,
            total_count=4,
        )

        self.assertIs(replayed, created)
        self.assertEqual(replayed.status, TaskStatus.COMPLETED)

    def test_ensure_task_rejects_deterministic_identity_mismatch(self):
        from module.task_state import (
            TaskIdentityConflictError,
            TaskStateStore,
            TaskStatus,
        )

        store = TaskStateStore()
        store.ensure_task(
            "channel-batch-conflict",
            source="web",
            task_type="channel_library",
            chat_id=-1001,
            title="Immutable batch",
            status=TaskStatus.QUEUED,
            total_count=4,
        )

        with self.assertRaises(TaskIdentityConflictError):
            store.ensure_task(
                "channel-batch-conflict",
                source="web",
                task_type="channel_library",
                chat_id=-1001,
                title="Corrupt replacement",
                status=TaskStatus.QUEUED,
                total_count=99,
            )

        existing = store.get_task("channel-batch-conflict")
        self.assertEqual(existing.title, "Immutable batch")
        self.assertEqual(existing.total_count, 4)

    def test_paginate_files_bounds_page_size(self):
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        store = TaskStateStore()
        store.create_task("page-1", status=TaskStatus.QUEUED)
        for message_id in range(1, 121):
            store.upsert_file("page-1", message_id, status=FileStatus.QUEUED)

        page = store.paginate_files("page-1", page=2, page_size=50, max_page_size=100)
        oversized = store.paginate_files(
            "page-1", page=1, page_size=1000, max_page_size=100
        )

        self.assertEqual(page["page"], 2)
        self.assertEqual(page["page_size"], 50)
        self.assertEqual(page["total"], 120)
        self.assertEqual(page["items"][0]["message_id"], "51")
        self.assertEqual(len(oversized["items"]), 100)

    def test_dashboard_limits_task_rows(self):
        from module.task_state import TaskStateStore, TaskStatus

        store = TaskStateStore()
        for index in range(5):
            store.create_task(
                f"task-{index}",
                status=TaskStatus.QUEUED,
                title=f"Task {index}",
            )

        payload = store.dashboard(limit=2)

        self.assertEqual(payload["active_task_count"], 5)
        self.assertEqual(len(payload["tasks"]), 2)


if __name__ == "__main__":
    unittest.main()

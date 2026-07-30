import os
import subprocess
import sys
import threading
import unittest
import tempfile
import sqlite3
from pathlib import Path
from unittest import mock

from module.app import DownloadStatus, TaskNode


class TaskStateStoreTestCase(unittest.TestCase):
    def test_import_does_not_create_task_database(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "web_tasks.sqlite3"
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
            environment["TMD_TASK_DB_PATH"] = str(db_path)

            subprocess.run(
                [sys.executable, "-c", "import module.task_state"],
                cwd=tmp_dir,
                env=environment,
                check=True,
            )

            self.assertFalse(db_path.exists())

    def test_get_task_store_requires_explicit_initialization(self):
        from module.task_state import (
            get_task_store,
            initialize_task_store,
            reset_task_store_for_tests,
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            previous_store = reset_task_store_for_tests()
            try:
                with self.assertRaisesRegex(RuntimeError, "not initialized"):
                    get_task_store()
                initialized = initialize_task_store(
                    Path(tmp_dir) / "tasks.sqlite3",
                    recover_interrupted=False,
                )
                self.assertIs(get_task_store(), initialized)
            finally:
                reset_task_store_for_tests(previous_store)

    def test_reader_snapshots_cannot_mutate_store_state(self):
        from module.task_state import (
            FileStatus,
            TaskStateStore,
            WorkflowSnapshot,
        )

        store = TaskStateStore()
        store.create_task(
            "immutable-read",
            workflow=WorkflowSnapshot(selected_count=1),
        )
        store.upsert_file(
            "immutable-read",
            101,
            status=FileStatus.DOWNLOADING,
            downloaded_size=10,
        )

        task = store.get_task("immutable-read")
        task.workflow.selected_count = 99
        task.files["101"].downloaded_size = 999
        task.files["extra"] = task.files["101"]
        store.tasks()[0].status = "caller-mutated"

        persisted = store.get_task("immutable-read")
        self.assertEqual(persisted.workflow.selected_count, 1)
        self.assertEqual(persisted.files["101"].downloaded_size, 10)
        self.assertNotIn("extra", persisted.files)
        self.assertNotEqual(persisted.status, "caller-mutated")

    def test_serialization_uses_stable_snapshot_during_concurrent_file_update(self):
        from module.task_state import TaskSnapshot, TaskStateStore

        store = TaskStateStore()
        store.create_task("serialize-concurrent")
        store.upsert_file("serialize-concurrent", 1, filename="one.bin")
        entered_serializer = threading.Event()
        release_serializer = threading.Event()
        errors = []
        serialized = []
        original_to_dict = TaskSnapshot.to_dict

        def blocking_to_dict(task_snapshot, *args, **kwargs):
            entered_serializer.set()
            release_serializer.wait(timeout=2)
            return original_to_dict(task_snapshot, *args, **kwargs)

        def serialize():
            try:
                serialized.extend(store.serialize_tasks(include_files=True))
            except Exception as error:  # pragma: no cover - asserted below
                errors.append(error)

        with mock.patch.object(TaskSnapshot, "to_dict", blocking_to_dict):
            reader = threading.Thread(target=serialize)
            reader.start()
            self.assertTrue(entered_serializer.wait(timeout=1))
            store.upsert_file("serialize-concurrent", 2, filename="two.bin")
            release_serializer.set()
            reader.join(timeout=2)

        self.assertFalse(reader.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(serialized[0]["files"]), 1)

    def test_transition_file_updates_task_and_file_together(self):
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        store = TaskStateStore()
        store.create_task("transition-1", status=TaskStatus.QUEUED)

        task, file_snapshot = store.transition_file(
            "transition-1",
            101,
            task_updates={"status": TaskStatus.DOWNLOADING, "total_count": 1},
            file_updates={
                "status": FileStatus.DOWNLOADING,
                "filename": "sample.bin",
                "total_size": 100,
                "downloaded_size": 40,
            },
        )

        self.assertEqual(task.status, TaskStatus.DOWNLOADING)
        self.assertEqual(task.total_count, 1)
        self.assertEqual(file_snapshot.status, FileStatus.DOWNLOADING)
        self.assertEqual(task.files["101"].downloaded_size, 40)

    def test_transition_file_rolls_back_memory_and_sqlite_on_file_write_failure(self):
        from module.task_state import TaskStateStore, TaskStatus

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            store = TaskStateStore(storage_path=db_path)
            store.create_task("transition-fail", status=TaskStatus.QUEUED)
            with sqlite3.connect(db_path) as connection:
                connection.executescript(
                    """
                    CREATE TRIGGER reject_transition_file
                    BEFORE INSERT ON task_files
                    BEGIN
                        SELECT RAISE(ABORT, 'file write rejected');
                    END;
                    """
                )

            with self.assertRaises(sqlite3.IntegrityError):
                store.transition_file(
                    "transition-fail",
                    101,
                    task_updates={"status": TaskStatus.DOWNLOADING},
                    file_updates={"status": "downloading"},
                )

            in_memory = store.get_task("transition-fail")
            reloaded = TaskStateStore(storage_path=db_path).get_task("transition-fail")
            self.assertEqual(in_memory.status, TaskStatus.QUEUED)
            self.assertEqual(in_memory.files, {})
            self.assertEqual(reloaded.status, TaskStatus.QUEUED)
            self.assertEqual(reloaded.files, {})

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

    def test_upload_state_is_not_regressed_by_download_snapshot(self):
        import module.task_state as task_state_module

        from module.task_state import (
            FileStatus,
            TaskStateStore,
            TaskStatus,
            snapshot_node,
        )

        for upload_status in (
            FileStatus.UPLOADING,
            FileStatus.UPLOADED,
            FileStatus.UPLOAD_FAILED,
        ):
            with self.subTest(upload_status=upload_status):
                original_store = task_state_module._TASK_STORE
                task_state_module._TASK_STORE = TaskStateStore()
                try:
                    task = task_state_module.get_task_store().create_task(
                        f"preserve-{upload_status}",
                        status=TaskStatus.COMPLETED_WITH_ERRORS,
                    )
                    task_state_module.get_task_store().upsert_file(
                        task.task_id,
                        101,
                        status=upload_status,
                        save_path="/data/retained.mp4",
                    )
                    node = TaskNode(chat_id=-1002, task_id=task.task_id)
                    node.download_status[101] = DownloadStatus.SuccessDownload

                    snapshot_node(node)

                    stored = task_state_module.get_task_store().get_task(task.task_id)
                    self.assertEqual(stored.files["101"].status, upload_status)
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

    def test_active_task_registry_returns_a_container_snapshot(self):
        from module.download_stat import (
            add_active_task_node,
            get_active_task_nodes,
            remove_active_task_node,
        )
        from module.task_state import get_task_store

        store = get_task_store()
        store.clear()
        node = TaskNode(chat_id=-1003, task_id="registry-snapshot")
        add_active_task_node(node)

        try:
            caller_snapshot = get_active_task_nodes()
            caller_snapshot.pop(node.task_id)

            self.assertIn(node.task_id, get_active_task_nodes())
        finally:
            remove_active_task_node(node.task_id)
            store.clear()

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

    @unittest.skipUnless(os.name == "posix", "POSIX file modes are required")
    def test_sqlite_store_uses_owner_only_mode_wal_and_busy_timeout(self):
        from module.task_state import TaskStateStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            with sqlite3.connect(db_path):
                pass
            os.chmod(db_path, 0o644)

            store = TaskStateStore(storage_path=db_path)

            self.assertEqual(db_path.stat().st_mode & 0o777, 0o600)
            with store._connect() as connection:
                self.assertEqual(
                    connection.execute("PRAGMA journal_mode").fetchone()[0],
                    "wal",
                )
                self.assertEqual(
                    connection.execute("PRAGMA busy_timeout").fetchone()[0],
                    5000,
                )

    def test_sqlite_migration_persists_upload_progress_and_sets_schema_version(self):
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            with sqlite3.connect(db_path) as connection:
                connection.executescript(
                    """
                    CREATE TABLE tasks (
                        task_id TEXT PRIMARY KEY, source TEXT, task_type TEXT,
                        chat_id INTEGER, title TEXT, status TEXT,
                        created_at REAL, updated_at REAL, total_count INTEGER,
                        success_count INTEGER, failed_count INTEGER,
                        skipped_count INTEGER, upload_success_count INTEGER,
                        workflow_type TEXT, workflow_status TEXT,
                        workflow_scan_count INTEGER, workflow_media_count INTEGER,
                        workflow_selected_count INTEGER, workflow_summary TEXT,
                        workflow_error TEXT, error TEXT, needs_confirmation INTEGER
                    );
                    CREATE TABLE task_files (
                        task_id TEXT, message_id TEXT, status TEXT, filename TEXT,
                        total_size INTEGER, downloaded_size INTEGER,
                        download_speed INTEGER, save_path TEXT, error TEXT,
                        updated_at REAL, PRIMARY KEY (task_id, message_id)
                    );
                    INSERT INTO tasks (
                        task_id, status, created_at, updated_at, needs_confirmation
                    ) VALUES ('legacy-completed', 'completed', 1, 1, 0);
                    INSERT INTO task_files (
                        task_id, message_id, status, filename, total_size,
                        downloaded_size, download_speed, save_path, error, updated_at
                    ) VALUES (
                        'legacy-completed', '9', 'downloaded', 'legacy.mp4',
                        100, 100, 0, '/tmp/legacy.mp4', '', 1
                    );
                    """
                )

            store = TaskStateStore(storage_path=db_path)
            task = store.create_task("upload-persist", status=TaskStatus.UPLOADING)
            store.upsert_file(
                task.task_id,
                1,
                status=FileStatus.UPLOADING,
                total_size=100,
                uploaded_size=75,
                upload_speed=12,
            )

            reloaded = TaskStateStore(storage_path=db_path)
            file_snapshot = reloaded.get_task(task.task_id).files["1"]
            with sqlite3.connect(db_path) as connection:
                columns = {
                    row[1] for row in connection.execute("PRAGMA table_info(task_files)")
                }
                schema_version = connection.execute("PRAGMA user_version").fetchone()[0]

            self.assertEqual(schema_version, 1)
            self.assertIn("uploaded_size", columns)
            self.assertIn("upload_speed", columns)
            self.assertEqual(file_snapshot.uploaded_size, 75)
            self.assertEqual(file_snapshot.upload_speed, 12)
            self.assertEqual(
                reloaded.get_task("legacy-completed").files["9"].filename,
                "legacy.mp4",
            )

    def test_persistent_recent_limit_prunes_old_tasks_and_files(self):
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            store = TaskStateStore(recent_limit=2, storage_path=db_path)
            for index in range(3):
                task = store.create_task(
                    f"completed-{index}", status=TaskStatus.QUEUED
                )
                store.upsert_file(
                    task.task_id, index, status=FileStatus.DOWNLOADED
                )
                store.complete_task(task.task_id)

            reloaded = TaskStateStore(recent_limit=2, storage_path=db_path)
            with sqlite3.connect(db_path) as connection:
                task_ids = {
                    row[0] for row in connection.execute("SELECT task_id FROM tasks")
                }
                file_task_ids = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT task_id FROM task_files"
                    )
                }

            self.assertEqual(len(reloaded.tasks()), 2)
            self.assertEqual(task_ids, {"completed-1", "completed-2"})
            self.assertEqual(file_task_ids, task_ids)

    def test_restart_recovery_fails_non_resumable_active_task(self):
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            store = TaskStateStore(storage_path=db_path)
            task = store.create_task(
                "interrupted-package",
                source="web",
                task_type="package",
                status=TaskStatus.DOWNLOADING,
            )
            store.upsert_file(
                task.task_id, 1, status=FileStatus.DOWNLOADING, error=""
            )

            recovered = TaskStateStore(
                storage_path=db_path, recover_interrupted=True
            ).get_task("interrupted-package")

            self.assertEqual(recovered.status, TaskStatus.FAILED)
            self.assertEqual(recovered.error, "restart_interrupted")
            self.assertEqual(recovered.files["1"].status, FileStatus.FAILED)
            self.assertEqual(recovered.files["1"].error, "restart_interrupted")

    def test_restart_recovery_preserves_channel_task_for_batch_reconciliation(self):
        from module.task_state import TaskStateStore, TaskStatus

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            store = TaskStateStore(storage_path=db_path)
            store.create_task(
                "channel-resumable",
                source="web",
                task_type="channel_library",
                status=TaskStatus.DOWNLOADING,
            )

            recovered = TaskStateStore(
                storage_path=db_path, recover_interrupted=True
            ).get_task("channel-resumable")

            self.assertEqual(recovered.status, TaskStatus.DOWNLOADING)
            self.assertEqual(recovered.error, "")

    def test_sqlite_store_rejects_newer_schema_version(self):
        from module.task_state import TaskStateStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "tasks.sqlite3"
            TaskStateStore(storage_path=db_path)
            with sqlite3.connect(db_path) as connection:
                connection.execute("PRAGMA user_version = 2")

            with self.assertRaisesRegex(RuntimeError, "newer task database schema"):
                TaskStateStore(storage_path=db_path)

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

    def test_task_payload_exposes_processed_download_and_upload_stage_counts(self):
        from module.task_state import FileStatus, TaskStateStore, TaskStatus

        store = TaskStateStore()
        task = store.create_task(
            "stage-counts",
            status=TaskStatus.UPLOADING,
            total_count=5,
        )
        store.upsert_file(task.task_id, 1, status=FileStatus.UPLOADED)
        store.upsert_file(task.task_id, 2, status=FileStatus.UPLOAD_FAILED)
        store.upsert_file(task.task_id, 3, status=FileStatus.UPLOADING)
        store.upsert_file(task.task_id, 4, status=FileStatus.FAILED)
        store.upsert_file(task.task_id, 5, status=FileStatus.SKIPPED)

        payload = store.get_task(task.task_id).to_dict()

        self.assertEqual(payload["processed_count"], 4)
        self.assertEqual(payload["download_completed_count"], 4)
        self.assertEqual(payload["upload_attempt_count"], 3)
        self.assertEqual(payload["upload_completed_count"], 2)

    def test_task_payload_preserves_aggregate_progress_without_file_rows(self):
        from module.task_state import TaskStateStore

        store = TaskStateStore()
        task = store.create_task(
            "aggregate-counts",
            total_count=8,
            success_count=3,
            failed_count=1,
            skipped_count=2,
            upload_success_count=2,
        )

        payload = task.to_dict()

        self.assertEqual(payload["processed_count"], 6)
        self.assertEqual(payload["download_completed_count"], 6)
        self.assertEqual(payload["upload_attempt_count"], 2)
        self.assertEqual(payload["upload_completed_count"], 2)

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

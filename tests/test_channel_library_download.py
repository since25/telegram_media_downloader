"""Download outbox and immutable channel-package lifecycle tests."""

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from module.channel_library_service import ChannelLibraryService
from module.channel_library_store import (
    ChannelLibraryConfig,
    ChannelLibraryStore,
    PackageFilter,
)
from module.task_state import TaskStateStore, TaskStatus


def make_download_service(tmp_path, *, task_store=None, client=None):
    store = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    store.initialize()
    library, _ = store.create_or_get_library(
        -1001, "channel", "demo", "Demo Channel", "https://t.me/demo"
    )
    with store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
        for ordinal, (package_id, start_id, title) in enumerate(
            ((10, 101, "Original A"), (20, 201, "Original B")), start=1
        ):
            connection.execute(
                """
                INSERT INTO channel_packages (
                    id, library_id, start_message_id, end_message_id, title,
                    boundary_status, media_count, known_total_size,
                    unknown_size_count, index_revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'stable', 2, 200, 0, 7, 1, 1)
                """,
                (package_id, library["id"], start_id, start_id + 1, title),
            )
            connection.execute(
                """
                INSERT INTO channel_package_selections (
                    library_id, package_id, package_revision, selected,
                    created_at, updated_at
                ) VALUES (?, ?, 7, 1, 1, 1)
                """,
                (library["id"], package_id),
            )
            for item_ordinal, message_id in enumerate((start_id, start_id + 1), start=1):
                connection.execute(
                    """
                    INSERT INTO channel_media_messages (
                        library_id, message_id, message_date, media_type,
                        caption, file_name, file_size, raw_fingerprint,
                        first_seen_at, updated_at
                    ) VALUES (?, ?, '2026-07-16T00:00:00+00:00', 'video',
                              ?, ?, 100, ?, 1, 1)
                    """,
                    (
                        library["id"],
                        message_id,
                        f"caption-{message_id}",
                        f"{message_id}.mp4",
                        f"fingerprint-{message_id}",
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO channel_package_items (
                        library_id, package_id, message_id, ordinal, media_type,
                        caption_for_naming, original_caption, inherited_caption
                    ) VALUES (?, ?, ?, ?, 'video', ?, ?, 0)
                    """,
                    (
                        library["id"],
                        package_id,
                        message_id,
                        item_ordinal,
                        f"saved-{message_id}",
                        f"caption-{message_id}",
                    ),
                )
    library = store.get_library(library["id"])
    loop = asyncio.new_event_loop()
    service = ChannelLibraryService(
        SimpleNamespace(loop=loop),
        client or SimpleNamespace(),
        store,
        ChannelLibraryConfig(),
        task_store=task_store
        or TaskStateStore(storage_path=tmp_path / "web-tasks.sqlite3"),
    )
    return service, library, loop


def test_create_download_batch_is_idempotent_and_snapshots_selected_revision(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        first = service.create_download_batch(
            library["id"], "request-1", redownload=False
        )
        replay = service.create_download_batch(
            library["id"], "request-1", redownload=False
        )

        with service.store.connect() as connection:
            connection.execute(
                """
                UPDATE channel_packages
                SET title = 'Changed later', index_revision = 8
                WHERE library_id = ? AND id = 10
                """,
                (library["id"],),
            )
            connection.execute(
                """
                UPDATE channel_package_items
                SET caption_for_naming = 'changed later'
                WHERE library_id = ? AND package_id = 10
                """,
                (library["id"],),
            )

        snapshot = service.store.get_download_batch(first["id"])
        assert replay["id"] == first["id"]
        assert replay["task_id"] == first["task_id"]
        assert first["task_id"].startswith("channel-batch-")
        assert snapshot["dispatch_status"] == "dispatched"
        assert [package["package_revision"] for package in snapshot["packages"]] == [7, 7]
        assert [package["title"] for package in snapshot["packages"]] == [
            "Original A",
            "Original B",
        ]
        assert snapshot["packages"][0]["items"][0]["caption_for_naming"] == "saved-101"
        assert len(service.task_store.tasks()) == 1
        assert service.task_store.get_task(first["task_id"]).status == TaskStatus.QUEUED
    finally:
        loop.close()


def test_create_download_batch_rejects_package_in_an_active_batch(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        first = service.create_download_batch(library["id"], "active-request")

        replay = service.create_download_batch(library["id"], "active-request")
        assert replay["id"] == first["id"]
        with pytest.raises(ValueError, match="active download batch"):
            service.create_download_batch(library["id"], "different-request")

        assert len(service.store.list_download_batches(library["id"])) == 1
    finally:
        loop.close()


def test_active_attempt_survives_index_summary_revision_and_blocks_new_key(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        with service.store.connect() as connection:
            connection.execute(
                """
                UPDATE channel_packages
                SET current_download_status = 'completed',
                    has_successful_attempt = 1, completed_revision = 7
                WHERE library_id = ?
                """,
                (library["id"],),
            )
        first = service.create_download_batch(
            library["id"], "redownload-a", redownload=True
        )

        with service.store.connect() as connection:
            connection.execute(
                """
                UPDATE channel_packages
                SET current_download_status = 'outdated', index_revision = 8
                WHERE library_id = ? AND id = 10
                """,
                (library["id"],),
            )
            connection.execute(
                """
                UPDATE channel_package_selections
                SET selected = CASE WHEN package_id = 10 THEN 1 ELSE 0 END,
                    package_revision = CASE WHEN package_id = 10 THEN 8 ELSE package_revision END
                WHERE library_id = ?
                """,
                (library["id"],),
            )

        with pytest.raises(ValueError, match="active download batch"):
            service.create_download_batch(
                library["id"], "redownload-b", redownload=True
            )

        assert [batch["id"] for batch in service.store.list_download_batches()] == [
            first["id"]
        ]
    finally:
        loop.close()


def test_channel_transaction_failure_does_not_create_web_task(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        with service.store.connect() as connection:
            connection.execute(
                """
                CREATE TRIGGER abort_download_batch
                BEFORE INSERT ON channel_download_batches
                BEGIN
                    SELECT RAISE(ABORT, 'channel commit blocked');
                END
                """
            )

        with pytest.raises(sqlite3.IntegrityError, match="channel commit blocked"):
            service.create_download_batch(library["id"], "request-before-commit")

        assert service.store.list_download_batches(library["id"]) == []
        assert service.task_store.tasks() == []
    finally:
        loop.close()


def test_restart_replays_crash_after_channel_commit_before_web_task(tmp_path):
    class FailOnceTaskStore(TaskStateStore):
        def __init__(self, path):
            super().__init__(storage_path=path)
            self.failed = False

        def ensure_task(self, *args, **kwargs):
            if not self.failed:
                self.failed = True
                raise RuntimeError("crash before web task")
            return super().ensure_task(*args, **kwargs)

    task_path = tmp_path / "web-tasks.sqlite3"
    service, library, loop = make_download_service(
        tmp_path, task_store=FailOnceTaskStore(task_path)
    )
    try:
        with pytest.raises(RuntimeError, match="crash before web task"):
            service.create_download_batch(library["id"], "request-after-channel")

        pending = service.store.list_pending_download_batches()
        assert len(pending) == 1
        assert service.task_store.tasks() == []

        restarted = ChannelLibraryService(
            SimpleNamespace(loop=loop),
            SimpleNamespace(),
            ChannelLibraryStore(service.store.path),
            ChannelLibraryConfig(),
            task_store=TaskStateStore(storage_path=task_path),
        )
        dispatched = restarted.dispatch_pending_batches()

        assert [batch["id"] for batch in dispatched] == [pending[0]["id"]]
        assert restarted.store.get_download_batch(pending[0]["id"])[
            "dispatch_status"
        ] == "dispatched"
        assert len(restarted.task_store.tasks()) == 1
    finally:
        loop.close()


def test_restart_replays_crash_after_web_task_before_dispatched_mark(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        with service.store.connect() as connection:
            connection.execute(
                """
                CREATE TRIGGER abort_dispatch_mark
                BEFORE UPDATE OF dispatch_status ON channel_download_batches
                WHEN NEW.dispatch_status = 'dispatched'
                BEGIN
                    SELECT RAISE(ABORT, 'dispatch mark blocked');
                END
                """
            )

        with pytest.raises(sqlite3.IntegrityError, match="dispatch mark blocked"):
            service.create_download_batch(library["id"], "request-after-web")

        pending = service.store.list_pending_download_batches()
        task_id = pending[0]["task_id"]
        task = service.task_store.get_task(task_id)
        assert task.title == "Demo Channel / 2 packages"

        with service.store.connect() as connection:
            connection.execute(
                "UPDATE channel_libraries SET title = 'Renamed Channel' WHERE id = ?",
                (library["id"],),
            )

        with service.store.connect() as connection:
            connection.execute("DROP TRIGGER abort_dispatch_mark")
        dispatched = service.dispatch_pending_batches()

        assert [batch["id"] for batch in dispatched] == [pending[0]["id"]]
        assert service.store.get_download_batch(pending[0]["id"])[
            "dispatch_status"
        ] == "dispatched"
        assert [task.task_id for task in service.task_store.tasks()] == [task_id]
        assert service.task_store.get_task(task_id).title == "Demo Channel / 2 packages"
    finally:
        loop.close()


def test_pending_dispatch_rejects_corrupt_deterministic_task_identity(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        pending = service.store.create_download_batch(
            library["id"],
            "corrupt-task",
            "channel-batch-corrupt-task",
        )
        service.task_store.create_task(
            pending["task_id"],
            source="web",
            task_type="channel_library",
            chat_id=-1001,
            title="Corrupt identity",
            status=TaskStatus.COMPLETED,
            total_count=99,
        )

        assert service.dispatch_pending_batches() == []

        stored = service.store.get_download_batch(pending["id"])
        assert stored["dispatch_status"] == "pending_dispatch"
        assert stored["last_error"] == "task_identity_conflict"
        corrupt = service.task_store.get_task(pending["task_id"])
        assert corrupt.title == "Corrupt identity"
        assert corrupt.status == TaskStatus.COMPLETED
    finally:
        loop.close()


def test_pending_dispatch_preserves_matching_terminal_task(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        pending = service.store.create_download_batch(
            library["id"],
            "terminal-task",
            "channel-batch-terminal-task",
        )
        terminal = service.task_store.create_task(
            pending["task_id"],
            source="web",
            task_type="channel_library",
            chat_id=-1001,
            title="Demo Channel / 2 packages",
            status=TaskStatus.COMPLETED,
            total_count=4,
        )

        dispatched = service.dispatch_pending_batches()

        assert [batch["id"] for batch in dispatched] == [pending["id"]]
        assert service.store.get_download_batch(pending["id"])[
            "dispatch_status"
        ] == "dispatched"
        assert service.task_store.get_task(pending["task_id"]) is terminal
        assert terminal.status == TaskStatus.COMPLETED
    finally:
        loop.close()


def test_failed_redownload_preserves_historical_success_duplicate_protection(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        with service.store.connect() as connection:
            connection.execute(
                """
                UPDATE channel_packages
                SET current_download_status = 'completed',
                    has_successful_attempt = 1, completed_revision = 7,
                    last_successful_at = 10
                WHERE library_id = ?
                """,
                (library["id"],),
            )

        batch = service.create_download_batch(
            library["id"], "explicit-redownload", redownload=True
        )
        service.store.finish_download_batch_package(
            batch["id"], 10, "failed", last_error="network"
        )

        package = service.store.list_packages(
            library["id"], PackageFilter(), limit=10
        ).items[0]
        assert package["has_successful_attempt"] == 1
        with pytest.raises(ValueError, match="redownload"):
            service.create_download_batch(
                library["id"], "retry-without-confirmation", redownload=False
            )
    finally:
        loop.close()


def test_create_download_batch_rejects_nonterminal_library_and_stale_selection(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        with service.store.connect() as connection:
            connection.execute(
                "UPDATE channel_libraries SET status = 'indexing' WHERE id = ?",
                (library["id"],),
            )
        with pytest.raises(ValueError, match="not ready"):
            service.create_download_batch(library["id"], "not-ready")

        with service.store.connect() as connection:
            connection.execute(
                "UPDATE channel_libraries SET status = 'partial' WHERE id = ?",
                (library["id"],),
            )
            connection.execute(
                """
                UPDATE channel_package_selections
                SET package_revision = 6 WHERE library_id = ? AND package_id = 10
                """,
                (library["id"],),
            )
        with pytest.raises(ValueError, match="revision changed"):
            service.create_download_batch(library["id"], "stale-selection")
    finally:
        loop.close()


def test_run_download_batch_refetches_exact_snapshot_and_writes_package_results(
    tmp_path,
):
    class SnapshotClient:
        def __init__(self):
            self.requests = []

        async def get_messages(self, chat_id, message_ids):
            self.requests.append((chat_id, list(message_ids)))
            return [
                SimpleNamespace(
                    id=message_id,
                    empty=False,
                    caption=f"live-{message_id}",
                    media="video",
                    media_group_id=None,
                    video=SimpleNamespace(
                        file_name=f"live-{message_id}.mp4",
                        file_size=100,
                        mime_type="video/mp4",
                    ),
                )
                for message_id in message_ids
                if message_id != 102
            ]

    client = SnapshotClient()
    service, library, loop = make_download_service(tmp_path, client=client)
    try:
        batch = service.create_download_batch(library["id"], "run-exact-snapshot")
        with service.store.connect() as connection:
            connection.execute(
                "UPDATE channel_libraries SET title = 'Renamed Channel' WHERE id = ?",
                (library["id"],),
            )
        captured = []

        async def fake_download_prescan_packages(
            packages,
            channel,
            parent_node,
            selected_package_ids,
            on_package_started=None,
            on_package_finished=None,
            manage_parent_lifecycle=True,
        ):
            from media_downloader import PackageDownloadResult, PackageMessageResult

            assert channel == "Demo Channel"
            assert selected_package_ids == {10, 20}
            results = []
            for package in packages:
                captured.append(
                    (
                        package.package_id,
                        package.package_revision,
                        package.title,
                        package.start_message_id,
                        package.end_message_id,
                        [item.caption_for_naming for item in package.items],
                        list(package.failed_message_ids),
                    )
                )
                await on_package_started(package.attempt_id, package)
                message_results = {
                    item.message.id: PackageMessageResult(
                        item.message.id,
                        "completed",
                    )
                    for item in package.items
                }
                for message_id in package.failed_message_ids:
                    message_results[message_id] = PackageMessageResult(
                        message_id,
                        "not_found",
                    )
                await on_package_finished(package.attempt_id, message_results)
                package_status = (
                    "not_found"
                    if package.failed_message_ids
                    else "completed"
                )
                results.append(
                    PackageDownloadResult(
                        package.attempt_id,
                        package.package_id,
                        package_status,
                        tuple(message_results),
                        message_results,
                    )
                )
            return results

        with patch(
            "media_downloader.download_prescan_packages",
            new=fake_download_prescan_packages,
        ):
            results = loop.run_until_complete(service.run_download_batch(batch["id"]))

        assert client.requests == [
            (-1001, [101, 102]),
            (-1001, [201, 202]),
        ]
        assert captured == [
            (10, 7, "Original A", 101, 102, ["saved-101"], [102]),
            (20, 7, "Original B", 201, 202, ["saved-201", "saved-202"], []),
        ]
        assert [result.status for result in results] == ["not_found", "completed"]
        stored = service.store.get_download_batch(batch["id"])
        assert [package["status"] for package in stored["packages"]] == [
            "not_found",
            "completed",
        ]
        assert stored["status"] == "failed"
        assert stored["channel_title"] == "Demo Channel"
    finally:
        loop.close()


def test_reconcile_download_batches_uses_file_evidence_and_cancel_status(tmp_path):
    from module.task_state import FileStatus

    service, library, loop = make_download_service(tmp_path)
    try:
        completed = service.create_download_batch(library["id"], "reconcile-completed")
        for package in completed["packages"]:
            for item in package["items"]:
                service.task_store.upsert_file(
                    completed["task_id"],
                    item["message_id"],
                    status=FileStatus.DOWNLOADED,
                )
        service.task_store.complete_task(completed["task_id"])

        reconciled = service.reconcile_download_batches()

        assert [batch["id"] for batch in reconciled] == [completed["id"]]
        completed_stored = service.store.get_download_batch(completed["id"])
        assert completed_stored["status"] == "completed"
        assert all(
            package["status"] == "completed"
            for package in completed_stored["packages"]
        )

        with service.store.connect() as connection:
            connection.execute(
                """
                UPDATE channel_package_selections
                SET selected = 1, package_revision = 7, invalidation_reason = NULL
                WHERE library_id = ?
                """,
                (library["id"],),
            )
        cancelled = service.create_download_batch(
            library["id"], "reconcile-cancelled", redownload=True
        )
        service.task_store.update_task(
            cancelled["task_id"], status=TaskStatus.CANCELLED
        )

        service.reconcile_download_batches()

        cancelled_stored = service.store.get_download_batch(cancelled["id"])
        assert cancelled_stored["status"] == "cancelled"
        assert all(
            package["status"] == "cancelled"
            for package in cancelled_stored["packages"]
        )
    finally:
        loop.close()


def test_reconcile_completed_with_errors_uses_per_package_file_evidence(tmp_path):
    from module.task_state import FileStatus

    service, library, loop = make_download_service(tmp_path)
    try:
        batch = service.create_download_batch(library["id"], "mixed-reconcile")
        for item in batch["packages"][0]["items"]:
            service.task_store.upsert_file(
                batch["task_id"], item["message_id"], status=FileStatus.DOWNLOADED
            )
        service.task_store.upsert_file(
            batch["task_id"], 201, status=FileStatus.FAILED
        )
        service.task_store.upsert_file(
            batch["task_id"], 202, status=FileStatus.DOWNLOADED
        )
        service.task_store.update_task(
            batch["task_id"], status=TaskStatus.COMPLETED_WITH_ERRORS
        )

        service.reconcile_download_batches()

        stored = service.store.get_download_batch(batch["id"])
        assert [package["status"] for package in stored["packages"]] == [
            "completed",
            "failed",
        ]
    finally:
        loop.close()


def test_run_download_batch_contains_refetch_error_to_affected_package(tmp_path):
    secret = "SECRET_REFETCH_DETAIL_8472"

    class FailingFirstClient:
        def __init__(self):
            self.calls = 0

        async def get_messages(self, _chat_id, message_ids):
            self.calls += 1
            if self.calls == 1:
                raise OSError(secret)
            return [
                SimpleNamespace(
                    id=message_id,
                    empty=False,
                    caption=f"live-{message_id}",
                    media="video",
                    media_group_id=None,
                    video=SimpleNamespace(
                        file_name=f"{message_id}.mp4",
                        file_size=100,
                        mime_type="video/mp4",
                    ),
                )
                for message_id in message_ids
            ]

    service, library, loop = make_download_service(
        tmp_path, client=FailingFirstClient()
    )
    try:
        batch = service.create_download_batch(library["id"], "refetch-error")

        async def fake_download_prescan_packages(
            packages,
            channel=None,
            parent_node=None,
            selected_package_ids=None,
            on_package_started=None,
            on_package_finished=None,
            **_kwargs,
        ):
            from media_downloader import PackageDownloadResult, PackageMessageResult

            results = []
            for package in packages:
                await on_package_started(package.attempt_id, package)
                status = "failed" if package.fetch_error else "completed"
                message_results = {
                    message_id: PackageMessageResult(
                        message_id,
                        status,
                        package.fetch_error or "",
                    )
                    for message_id in (
                        [item.message.id for item in package.items]
                        + list(package.failed_message_ids)
                    )
                }
                await on_package_finished(package.attempt_id, message_results)
                results.append(
                    PackageDownloadResult(
                        package.attempt_id,
                        package.package_id,
                        status,
                        tuple(message_results),
                        message_results,
                    )
                )
            return results

        with patch(
            "media_downloader.download_prescan_packages",
            new=fake_download_prescan_packages,
        ):
            results = loop.run_until_complete(service.run_download_batch(batch["id"]))

        assert [result.status for result in results] == ["failed", "completed"]
        stored = service.store.get_download_batch(batch["id"])
        assert [package["status"] for package in stored["packages"]] == [
            "failed",
            "completed",
        ]
        assert stored["packages"][0]["last_error"] == "telegram_refetch_failed"
        for path in (service.store.path, service.task_store.storage_path):
            with sqlite3.connect(path) as connection:
                assert secret not in "\n".join(connection.iterdump())
    finally:
        loop.close()


def test_callback_exception_persists_only_safe_error_codes(tmp_path):
    from media_downloader import PackageCallbackError

    secret = "SECRET_CALLBACK_DETAIL_9127"
    service, library, loop = make_download_service(tmp_path, client=SimpleNamespace())
    try:
        batch = service.create_download_batch(library["id"], "callback-error")

        class CompleteClient:
            async def get_messages(self, _chat_id, message_ids):
                return [
                    SimpleNamespace(
                        id=message_id,
                        empty=False,
                        caption=f"live-{message_id}",
                        media="video",
                        media_group_id=None,
                        video=SimpleNamespace(
                            file_name=f"{message_id}.mp4",
                            file_size=100,
                            mime_type="video/mp4",
                        ),
                    )
                    for message_id in message_ids
                ]

        service.client = CompleteClient()
        with patch.object(
            service.store,
            "mark_download_batch_package_started",
            side_effect=RuntimeError(secret),
        ), patch(
            "module.pyrogram_extension.report_bot_status",
            new=lambda *_args, **_kwargs: asyncio.sleep(0),
        ), pytest.raises(PackageCallbackError):
            loop.run_until_complete(service.run_download_batch(batch["id"]))

        stored = service.store.get_download_batch(batch["id"])
        assert {package["last_error"] for package in stored["packages"]} == {
            "callback_failed"
        }
        task = service.task_store.get_task(batch["task_id"])
        assert task.status == TaskStatus.FAILED
        assert task.error == "callback_failed"
        for path in (service.store.path, service.task_store.storage_path):
            with sqlite3.connect(path) as connection:
                assert secret not in "\n".join(connection.iterdump())
    finally:
        loop.close()


def test_run_download_batch_marks_unfinished_packages_cancelled(tmp_path):
    class CompleteClient:
        async def get_messages(self, _chat_id, message_ids):
            return [
                SimpleNamespace(
                    id=message_id,
                    empty=False,
                    caption=f"live-{message_id}",
                    media="video",
                    media_group_id=None,
                    video=SimpleNamespace(
                        file_name=f"{message_id}.mp4",
                        file_size=100,
                        mime_type="video/mp4",
                    ),
                )
                for message_id in message_ids
            ]

    service, library, loop = make_download_service(tmp_path, client=CompleteClient())
    try:
        batch = service.create_download_batch(library["id"], "cancel-runner")

        async def cancelling_download(
            packages,
            channel=None,
            parent_node=None,
            selected_package_ids=None,
            on_package_started=None,
            **_kwargs,
        ):
            await on_package_started(packages[0].attempt_id, packages[0])
            raise asyncio.CancelledError

        with patch(
            "media_downloader.download_prescan_packages", new=cancelling_download
        ), pytest.raises(asyncio.CancelledError):
            loop.run_until_complete(service.run_download_batch(batch["id"]))

        stored = service.store.get_download_batch(batch["id"])
        assert stored["status"] == "cancelled"
        assert all(
            package["status"] == "cancelled" for package in stored["packages"]
        )
    finally:
        loop.close()


def test_cancel_while_waiting_for_refetch_gate_cancels_batch_without_leaks(tmp_path):
    from module.download_stat import get_active_task_nodes
    from module.telegram_activity import TelegramActivityGate

    service, library, loop = make_download_service(tmp_path, client=SimpleNamespace())
    service.gate = TelegramActivityGate()
    try:
        batch = service.create_download_batch(library["id"], "cancel-gate-wait")

        async def scenario():
            scan = await service.gate.acquire_scan()
            task = asyncio.create_task(service.run_download_batch(batch["id"]))
            while service.gate._waiting_downloads == 0:
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            scan.release()
            await asyncio.sleep(0)
            await service.gate.wait_until_downloads_idle()

        loop.run_until_complete(scenario())

        stored = service.store.get_download_batch(batch["id"])
        assert stored["status"] == "cancelled"
        assert all(
            package["status"] == "cancelled" for package in stored["packages"]
        )
        assert service.task_store.get_task(batch["task_id"]).status == TaskStatus.CANCELLED
        assert batch["task_id"] not in get_active_task_nodes()
        assert service._running_download_batch_ids == set()
    finally:
        loop.close()


def test_cancel_during_blocking_refetch_cancels_batch_and_releases_permit(tmp_path):
    from module.download_stat import get_active_task_nodes
    from module.telegram_activity import TelegramActivityGate

    class BlockingClient:
        def __init__(self):
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def get_messages(self, _chat_id, _message_ids):
            self.entered.set()
            await self.release.wait()

    client = BlockingClient()
    service, library, loop = make_download_service(tmp_path, client=client)
    service.gate = TelegramActivityGate()
    try:
        batch = service.create_download_batch(library["id"], "cancel-refetch")

        async def scenario():
            task = asyncio.create_task(service.run_download_batch(batch["id"]))
            await client.entered.wait()
            assert await service.gate.has_download_activity() is True
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await service.gate.wait_until_downloads_idle()

        loop.run_until_complete(scenario())

        stored = service.store.get_download_batch(batch["id"])
        assert stored["status"] == "cancelled"
        assert all(
            package["status"] == "cancelled" for package in stored["packages"]
        )
        assert service.task_store.get_task(batch["task_id"]).status == TaskStatus.CANCELLED
        assert batch["task_id"] not in get_active_task_nodes()
        assert service._running_download_batch_ids == set()
    finally:
        loop.close()


def test_same_batch_concurrent_runner_is_rejected_before_second_refetch(tmp_path):
    class FirstCallBlockingClient:
        def __init__(self):
            self.calls = 0
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def get_messages(self, _chat_id, message_ids):
            self.calls += 1
            if self.calls == 1:
                self.entered.set()
                await self.release.wait()
            return [
                SimpleNamespace(id=message_id, empty=False) for message_id in message_ids
            ]

    client = FirstCallBlockingClient()
    service, library, loop = make_download_service(tmp_path, client=client)
    try:
        batch = service.create_download_batch(library["id"], "single-runner")
        competing = ChannelLibraryService(
            SimpleNamespace(loop=loop),
            client,
            ChannelLibraryStore(service.store.path),
            ChannelLibraryConfig(),
            task_store=TaskStateStore(storage_path=service.task_store.storage_path),
        )

        async def no_download(**_kwargs):
            return []

        async def scenario():
            first = asyncio.create_task(service.run_download_batch(batch["id"]))
            await client.entered.wait()
            try:
                with pytest.raises(RuntimeError, match="already running"):
                    await competing.run_download_batch(batch["id"])
            finally:
                first.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await first

        with patch(
            "media_downloader.download_prescan_packages", new=no_download
        ):
            loop.run_until_complete(scenario())

        assert client.calls == 1
        assert service._running_download_batch_ids == set()
        assert competing._running_download_batch_ids == set()
        stored = service.store.get_download_batch(batch["id"])
        assert stored["status"] == "cancelled"
    finally:
        loop.close()


def test_mark_package_started_rejects_nonqueued_attempt_state(tmp_path):
    service, library, loop = make_download_service(tmp_path)
    try:
        batch = service.create_download_batch(library["id"], "started-conflict")
        service.store.mark_download_batch_package_started(batch["id"], 10)

        with pytest.raises(ValueError, match="not queued"):
            service.store.mark_download_batch_package_started(batch["id"], 10)
    finally:
        loop.close()


def test_restart_normalizes_stale_downloading_attempt_before_resume(tmp_path):
    class CompleteClient:
        async def get_messages(self, _chat_id, message_ids):
            return [
                SimpleNamespace(
                    id=message_id,
                    empty=False,
                    caption=f"live-{message_id}",
                    media="video",
                    media_group_id=None,
                    video=SimpleNamespace(
                        file_name=f"{message_id}.mp4",
                        file_size=100,
                        mime_type="video/mp4",
                    ),
                )
                for message_id in message_ids
            ]

    service, library, loop = make_download_service(tmp_path, client=CompleteClient())
    try:
        batch = service.create_download_batch(library["id"], "restart-resume")
        service.store.mark_download_batch_package_started(batch["id"], 10)
        restarted = ChannelLibraryService(
            SimpleNamespace(loop=loop),
            CompleteClient(),
            ChannelLibraryStore(service.store.path),
            ChannelLibraryConfig(),
            task_store=TaskStateStore(storage_path=service.task_store.storage_path),
        )
        statuses_before_callbacks = []

        async def complete_download(
            packages,
            on_package_started=None,
            on_package_finished=None,
            **_kwargs,
        ):
            from media_downloader import PackageDownloadResult, PackageMessageResult

            statuses_before_callbacks.extend(
                package["status"]
                for package in restarted.store.get_download_batch(batch["id"])[
                    "packages"
                ]
            )
            results = []
            for package in packages:
                await on_package_started(package.attempt_id, package)
                message_results = {
                    message_id: PackageMessageResult(message_id, "completed")
                    for message_id in package.expected_message_ids
                }
                await on_package_finished(package.attempt_id, message_results)
                results.append(
                    PackageDownloadResult(
                        package.attempt_id,
                        package.package_id,
                        "completed",
                        tuple(message_results),
                        message_results,
                    )
                )
            return results

        with patch(
            "media_downloader.download_prescan_packages", new=complete_download
        ):
            loop.run_until_complete(restarted.run_download_batch(batch["id"]))

        assert statuses_before_callbacks == ["queued", "queued"]
        stored = restarted.store.get_download_batch(batch["id"])
        assert stored["status"] == "completed"
        assert all(
            package["status"] == "completed" for package in stored["packages"]
        )
    finally:
        loop.close()


def test_normal_return_after_user_stop_forces_parent_and_unstarted_cancelled(tmp_path):
    class CompleteClient:
        async def get_messages(self, _chat_id, message_ids):
            return [
                SimpleNamespace(
                    id=message_id,
                    empty=False,
                    caption=f"live-{message_id}",
                    media="video",
                    media_group_id=None,
                    video=SimpleNamespace(
                        file_name=f"{message_id}.mp4",
                        file_size=100,
                        mime_type="video/mp4",
                    ),
                )
                for message_id in message_ids
            ]

    service, library, loop = make_download_service(tmp_path, client=CompleteClient())
    try:
        batch = service.create_download_batch(library["id"], "normal-stop")

        async def stopped_downloader(packages, parent_node=None, **_kwargs):
            service.task_store.update_task(
                parent_node.task_id, status=TaskStatus.COMPLETED
            )
            parent_node.stop_transmission()
            return []

        with patch(
            "media_downloader.download_prescan_packages", new=stopped_downloader
        ):
            results = loop.run_until_complete(service.run_download_batch(batch["id"]))

        assert results == []
        assert service.task_store.get_task(batch["task_id"]).status == TaskStatus.CANCELLED
        stored = service.store.get_download_batch(batch["id"])
        assert stored["status"] == "cancelled"
        assert all(
            package["status"] == "cancelled" for package in stored["packages"]
        )
    finally:
        loop.close()


def test_inherited_caption_snapshot_reconstructs_text_zero_and_one(tmp_path):
    class CompleteClient:
        async def get_messages(self, _chat_id, message_ids):
            return [
                SimpleNamespace(
                    id=message_id,
                    empty=False,
                    caption=f"live-{message_id}",
                    media="video",
                    media_group_id=None,
                    video=SimpleNamespace(
                        file_name=f"{message_id}.mp4",
                        file_size=100,
                        mime_type="video/mp4",
                    ),
                )
                for message_id in message_ids
            ]

    service, library, loop = make_download_service(tmp_path, client=CompleteClient())
    try:
        with service.store.connect() as connection:
            connection.execute(
                """
                UPDATE channel_package_items
                SET inherited_caption = CASE message_id WHEN 101 THEN '0' ELSE '1' END
                WHERE library_id = ? AND package_id = 10
                """,
                (library["id"],),
            )
        batch = service.create_download_batch(library["id"], "caption-bool")
        captured = []

        async def capture_packages(packages, **_kwargs):
            captured.extend(
                [item.inherited_caption for item in packages[0].items]
            )
            return []

        with patch(
            "media_downloader.download_prescan_packages", new=capture_packages
        ):
            loop.run_until_complete(service.run_download_batch(batch["id"]))

        assert captured == [False, True]
    finally:
        loop.close()

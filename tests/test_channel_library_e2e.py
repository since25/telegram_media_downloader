"""End-to-end acceptance coverage for the persistent channel library."""

import asyncio
import datetime
from collections import Counter
from itertools import chain
from types import SimpleNamespace

import pytest

from module.app import DownloadStatus
from module.channel_library_service import ChannelLibraryService
from module.channel_library_store import (
    ChannelLibraryConfig,
    ChannelLibraryStore,
    PackageFilter,
)
from module.telegram_activity import TelegramActivityGate
from module.task_state import FileStatus, TaskStateStore, TaskStatus


UTC = datetime.timezone.utc


class SimulatedProcessExit(BaseException):
    """Stop the in-process scan without running its graceful recovery path."""


class NoWait:
    """Record configured delays without sleeping."""

    def __init__(self, crash_after_calls=None):
        self.calls = []
        self.crash_after_calls = crash_after_calls

    async def __call__(self, delay):
        self.calls.append(delay)
        if len(self.calls) == self.crash_after_calls:
            raise SimulatedProcessExit


class FifteenThousandIdClient:
    """Return one package boundary from each requested 50-ID window."""

    def __init__(self):
        self.batch_call_count = 0
        self.requested_ids = []
        self.refetch_requests = []
        self.scanning = True

    async def get_messages(self, chat_id, message_ids):
        assert chat_id == -10015000
        if not self.scanning:
            self.refetch_requests.append(list(message_ids))
            messages = [
                self._video_message(message_id, f"live-{message_id}")
                for message_id in message_ids
            ]
            return messages[0] if len(messages) == 1 else messages

        assert len(message_ids) == 50
        self.batch_call_count += 1
        self.requested_ids.append(list(message_ids))
        batch_number = self.batch_call_count
        prefix = "featured" if batch_number % 60 == 0 else "regular"
        message_id = message_ids[0]
        return self._video_message(
            message_id, f"{prefix}-{package_label(batch_number)}"
        )

    @staticmethod
    def _video_message(message_id, caption):
        video = SimpleNamespace(
            file_name=f"{message_id}.mp4",
            file_size=1000 + message_id,
            mime_type="video/mp4",
            duration=10,
            width=1280,
            height=720,
        )
        return SimpleNamespace(
            id=message_id,
            empty=False,
            caption=caption,
            media="video",
            media_group_id=None,
            date=datetime.datetime(2026, 7, 16, tzinfo=UTC),
            audio=None,
            document=None,
            photo=None,
            video=video,
            voice=None,
            video_note=None,
        )


class FakeDownloadBridge(TaskStateStore):
    """Use real task persistence while recording idempotent dispatch calls."""

    def __init__(self, path):
        super().__init__(storage_path=path)
        self.ensure_calls = []

    def ensure_task(self, task_id, **snapshot):
        self.ensure_calls.append((task_id, snapshot))
        return super().ensure_task(task_id, **snapshot)


class RandomUniformSpy:
    """Record every configured random range and return its lower bound."""

    def __init__(self):
        self.calls = []

    def __call__(self, low, high):
        self.calls.append((low, high))
        return low


def package_label(number):
    """Return a fixed-width alphabetic label that cannot look like a sequence."""

    characters = []
    value = number
    for _ in range(4):
        value, remainder = divmod(value, 26)
        characters.append(chr(ord("a") + remainder))
    return "".join(reversed(characters))


def make_service(store, client, task_store, sleep, random_uniform):
    service = ChannelLibraryService(
        SimpleNamespace(loop=asyncio.get_running_loop()),
        client,
        store,
        ChannelLibraryConfig(),
        sleep=sleep,
        random_uniform=random_uniform,
        task_store=task_store,
    )
    service.gate = TelegramActivityGate()
    return service


def unique_package_keys(store, library_id):
    with store.connect() as connection:
        package_keys = [
            (row["library_id"], row["start_message_id"])
            for row in connection.execute(
                """
                SELECT library_id, start_message_id
                FROM channel_packages
                WHERE library_id = ? AND boundary_status != 'superseded'
                """,
                (library_id,),
            )
        ]
        item_keys = [
            (row["library_id"], row["package_id"], row["message_id"])
            for row in connection.execute(
                """
                SELECT library_id, package_id, message_id
                FROM channel_package_items
                WHERE library_id = ?
                """,
                (library_id,),
            )
        ]
    return (
        len(package_keys) == len(set(package_keys))
        and len(item_keys) == len(set(item_keys))
    )


def one_task_per_batch(store, task_store):
    batches = store.list_download_batches()
    task_ids = {task.task_id for task in task_store.tasks()}
    return len(task_ids) == len(batches) and task_ids == {
        batch["task_id"] for batch in batches
    }


def test_full_channel_library_recovers_and_downloads_filtered_selection(
    tmp_path, monkeypatch
):
    async def scenario():
        import media_downloader
        import module.task_state as task_state_module

        from module.download_stat import get_active_task_nodes

        database_path = tmp_path / "channel-library.sqlite3"
        initial_store = ChannelLibraryStore(database_path)
        initial_store.initialize()
        library, job, created = initial_store.create_or_get_library_with_full_job(
            -10015000,
            "channel",
            "large_demo",
            "Large Demo",
            "https://t.me/large_demo/1",
            15000,
        )
        assert created is True

        fake_client = FifteenThousandIdClient()
        fake_download_bridge = FakeDownloadBridge(tmp_path / "web-tasks.sqlite3")
        random_uniform = RandomUniformSpy()
        interrupted_sleep = NoWait(crash_after_calls=120)
        initial_service = make_service(
            initial_store,
            fake_client,
            fake_download_bridge,
            interrupted_sleep,
            random_uniform,
        )

        with pytest.raises(SimulatedProcessExit):
            await initial_service._run_job(job)

        committed = initial_store.get_job(job["id"])
        assert committed["status"] == "running"
        assert committed["fetched_through_message_id"] == 6000
        assert committed["indexed_through_message_id"] == 6000
        assert committed["next_message_id"] == 6001

        resumed_store = ChannelLibraryStore(database_path)
        resumed_store.initialize()
        assert resumed_store.recover_interrupted_jobs() == 1
        resumed_job = resumed_store.get_job(job["id"])
        assert resumed_job["status"] == "queued"
        assert resumed_job["next_message_id"] == 6001

        resumed_sleep = NoWait()
        resumed_service = make_service(
            resumed_store,
            fake_client,
            fake_download_bridge,
            resumed_sleep,
            random_uniform,
        )
        await resumed_service._run_job(resumed_job)
        fake_client.scanning = False

        assert fake_client.batch_call_count == 300
        assert list(chain.from_iterable(fake_client.requested_ids)) == list(
            range(1, 15001)
        )
        assert len(interrupted_sleep.calls) + len(resumed_sleep.calls) == 299
        assert random_uniform.calls == [(4.0, 6.0)] * 299
        assert interrupted_sleep.calls + resumed_sleep.calls == [4.0] * 299
        assert resumed_store.get_job(job["id"])["status"] == "completed"
        assert resumed_store.get_library(library["id"])[
            "fetched_through_message_id"
        ] == 15000
        overview = resumed_store.get_library_overview(library["id"])
        assert overview["counts"]["package_count"] == 300
        assert overview["counts"]["stable_package_count"] == 300
        assert overview["counts"]["media_count"] == 300
        assert unique_package_keys(resumed_store, library["id"])

        package_filter = PackageFilter(
            q="featured",
            media_count_min=1,
            media_count_max=1,
            download_status="never",
        )
        filtered_packages = []
        cursor = None
        library_revision = None
        while True:
            page = resumed_store.list_packages(
                library["id"], package_filter, cursor=cursor, limit=2
            )
            filtered_packages.extend(page.items)
            library_revision = library_revision or page.library_revision
            assert page.library_revision == library_revision
            if page.next_cursor is None:
                break
            cursor = page.next_cursor

        assert len(filtered_packages) == 5
        assert len({package["id"] for package in filtered_packages}) == 5
        assert all(package["selectable"] for package in filtered_packages)
        assert resumed_store.select_filtered(
            library["id"], package_filter
        ) == {"selected_count": 5, "skipped_count": 0}

        reopened_store = ChannelLibraryStore(database_path)
        reopened_store.initialize()
        assert reopened_store.selection_summary(library["id"])[
            "selected_count"
        ] == 5

        batch = resumed_service.create_download_batch(
            library["id"], "e2e-filtered-download"
        )
        replay = resumed_service.create_download_batch(
            library["id"], "e2e-filtered-download"
        )

        assert replay["id"] == batch["id"]
        assert batch["dispatch_status"] == "dispatched"
        assert len(batch["packages"]) == 5
        assert [package["start_message_id"] for package in batch["packages"]] == [
            package["start_message_id"]
            for package in reversed(filtered_packages)
        ]
        assert one_task_per_batch(reopened_store, fake_download_bridge)
        assert [call[0] for call in fake_download_bridge.ensure_calls] == [
            batch["task_id"],
            batch["task_id"],
        ]
        task_snapshot = fake_download_bridge.get_task(batch["task_id"])
        assert task_snapshot.source == "web"
        assert task_snapshot.task_type == "channel_library"
        assert task_snapshot.total_count == 5

        execution = {
            "active": 0,
            "max_active": 0,
            "ranges": [],
            "counts": Counter(),
        }

        async def fake_download_media(message, node):
            start_message_id = node.package_naming_context.start_message_id
            item_ids = [item.message.id for item in node.package_plan.items]
            package_range = (start_message_id, max(item_ids))
            execution["active"] += 1
            execution["max_active"] = max(
                execution["max_active"], execution["active"]
            )
            execution["ranges"].append(package_range)
            execution["counts"][package_range] += 1
            try:
                await asyncio.sleep(0)
                node.total_task += 1
                node.total_download_task += 1
                node.download_status[message.id] = DownloadStatus.SuccessDownload
                node.stat(
                    DownloadStatus.SuccessDownload,
                    node.chat_id,
                    message.id,
                    f"/fake/{message.id}.mp4",
                )
                fake_download_bridge.upsert_file(
                    node.task_id,
                    message.id,
                    status=FileStatus.DOWNLOADED,
                    filename=f"/fake/{message.id}.mp4",
                )
                return True
            finally:
                execution["active"] -= 1

        async def fake_report_bot_status(*_args, **_kwargs):
            return None

        monkeypatch.setattr(
            media_downloader, "add_download_task", fake_download_media
        )
        monkeypatch.setattr(
            "module.pyrogram_extension.report_bot_status",
            fake_report_bot_status,
        )
        old_task_store = task_state_module._TASK_STORE
        task_state_module._TASK_STORE = fake_download_bridge
        resumed_service.owner_loop = asyncio.get_running_loop()
        try:
            assert resumed_service.schedule_pending_download_batches() == [
                batch["id"]
            ]
            download_task = resumed_service._download_batch_tasks[batch["id"]]
            assert resumed_service.schedule_pending_download_batches() == []
            results = await download_task
        finally:
            task_state_module._TASK_STORE = old_task_store
            get_active_task_nodes().pop(batch["task_id"], None)

        expected_ranges = [
            (package["start_message_id"], package["end_message_id"])
            for package in batch["packages"]
        ]
        assert execution["ranges"] == expected_ranges
        assert execution["counts"] == Counter(
            {package_range: 1 for package_range in expected_ranges}
        )
        assert execution["active"] == 0
        assert execution["max_active"] == 1
        assert fake_client.refetch_requests == [
            [package["start_message_id"]] for package in batch["packages"]
        ]
        assert fake_client.batch_call_count == 300
        assert [result.status for result in results] == ["completed"] * 5

        stored_batch = resumed_store.get_download_batch(batch["id"])
        assert stored_batch["status"] == "completed"
        assert [package["status"] for package in stored_batch["packages"]] == [
            "completed"
        ] * 5
        assert resumed_service.schedule_pending_download_batches() == []
        assert len(fake_download_bridge.tasks()) == 1
        completed_task = fake_download_bridge.get_task(batch["task_id"])
        assert completed_task.status == TaskStatus.COMPLETED
        with resumed_store.connect() as connection:
            package_states = [
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT current_download_status, has_successful_attempt
                    FROM channel_packages
                    WHERE id IN ({})
                    ORDER BY start_message_id
                    """.format(",".join("?" for _ in batch["packages"])),
                    [package["package_id"] for package in batch["packages"]],
                )
            ]
        assert package_states == [("completed", 1)] * 5

    asyncio.run(scenario())

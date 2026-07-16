"""End-to-end acceptance coverage for the persistent channel library."""

import asyncio
import datetime
from itertools import chain
from types import SimpleNamespace

import pytest

from module.channel_library_service import ChannelLibraryService
from module.channel_library_store import (
    ChannelLibraryConfig,
    ChannelLibraryStore,
    PackageFilter,
)
from module.telegram_activity import TelegramActivityGate


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

    async def get_messages(self, chat_id, message_ids):
        assert chat_id == -10015000
        assert len(message_ids) == 50
        self.batch_call_count += 1
        self.requested_ids.append(list(message_ids))
        batch_number = self.batch_call_count
        prefix = "featured" if batch_number % 60 == 0 else "regular"
        message_id = message_ids[0]
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
            caption=f"{prefix}-{package_label(batch_number)}",
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


class FakeDownloadBridge:
    """Idempotently record Web task dispatches without downloading media."""

    def __init__(self):
        self.calls = []
        self.tasks = {}

    def ensure_task(self, task_id, **snapshot):
        self.calls.append((task_id, snapshot))
        self.tasks.setdefault(task_id, snapshot)
        return self.tasks[task_id]


def package_label(number):
    """Return a fixed-width alphabetic label that cannot look like a sequence."""

    characters = []
    value = number
    for _ in range(4):
        value, remainder = divmod(value, 26)
        characters.append(chr(ord("a") + remainder))
    return "".join(reversed(characters))


def make_service(store, client, task_store, sleep):
    service = ChannelLibraryService(
        SimpleNamespace(loop=asyncio.get_running_loop()),
        client,
        store,
        ChannelLibraryConfig(),
        sleep=sleep,
        random_uniform=lambda low, _high: low,
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
    return len(task_store.tasks) == len(batches) and set(task_store.tasks) == {
        batch["task_id"] for batch in batches
    }


def test_full_channel_library_recovers_and_dispatches_filtered_selection(tmp_path):
    async def scenario():
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
        fake_download_bridge = FakeDownloadBridge()
        interrupted_sleep = NoWait(crash_after_calls=120)
        initial_service = make_service(
            initial_store,
            fake_client,
            fake_download_bridge,
            interrupted_sleep,
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
        )
        await resumed_service._run_job(resumed_job)

        assert fake_client.batch_call_count == 300
        assert list(chain.from_iterable(fake_client.requested_ids)) == list(
            range(1, 15001)
        )
        assert len(interrupted_sleep.calls) + len(resumed_sleep.calls) == 299
        assert all(4.0 <= delay <= 6.0 for delay in interrupted_sleep.calls)
        assert all(4.0 <= delay <= 6.0 for delay in resumed_sleep.calls)
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
        task_snapshot = fake_download_bridge.tasks[batch["task_id"]]
        assert task_snapshot["source"] == "web"
        assert task_snapshot["task_type"] == "channel_library"
        assert task_snapshot["total_count"] == 5

    asyncio.run(scenario())

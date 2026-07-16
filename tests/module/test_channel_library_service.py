"""Tests for the recoverable channel-library scan scheduler."""

import asyncio
import datetime
import sqlite3
import threading
import time
from functools import wraps
from types import SimpleNamespace
from typing import Callable, Optional

import pytest
from pyrogram import errors

from module.channel_library_service import ChannelLibraryService
from module.channel_library_store import ChannelLibraryConfig, ChannelLibraryStore
from module.channel_library_workflow import extract_media_row
from module.telegram_activity import TelegramActivityGate


UTC = datetime.timezone.utc


def async_test(test):
    """Run async tests without depending on pytest-asyncio."""

    @wraps(test)
    def run_test(*args, **kwargs):
        return asyncio.run(test(*args, **kwargs))

    return run_test


class SleepRecorder:
    def __init__(self):
        self.delays = []

    async def __call__(self, delay):
        self.delays.append(delay)


class InterruptingSleep(SleepRecorder):
    async def __call__(self, delay):
        await super().__call__(delay)
        raise asyncio.CancelledError


def fake_media(message_id, caption=None):
    video = SimpleNamespace(
        file_name=f"lesson-{message_id}.mp4",
        file_size=message_id * 100,
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


class FakeClient:
    def __init__(self):
        self.latest_message_id = 0
        self.requested_ids = []
        self.requested_chats = []
        self.failures = []
        self.on_request: Optional[Callable[[], None]] = None
        self.call_loops = []
        self.chat = SimpleNamespace(
            id=-1001,
            type="channel",
            username="demo",
            title="Demo",
        )

    async def get_chat(self, source_chat):
        self.call_loops.append(asyncio.get_running_loop())
        return self.chat

    async def get_chat_history(self, chat_id, limit=1):
        assert limit == 1
        self.call_loops.append(asyncio.get_running_loop())
        if self.latest_message_id:
            yield SimpleNamespace(id=self.latest_message_id)

    async def get_messages(self, chat_id, message_ids):
        self.call_loops.append(asyncio.get_running_loop())
        self.requested_chats.append(chat_id)
        self.requested_ids.append(list(message_ids))
        if self.on_request is not None:
            self.on_request()
        if self.failures:
            failure = self.failures.pop(0)
            if failure is not None:
                raise failure
        messages = [fake_media(message_id) for message_id in message_ids]
        return messages[0] if len(messages) == 1 else messages


class BlockingClient(FakeClient):
    def __init__(self):
        super().__init__()
        self.request_started = asyncio.Event()
        self.release_request = asyncio.Event()
        self.was_cancelled = False

    async def get_messages(self, chat_id, message_ids):
        self.requested_chats.append(chat_id)
        self.requested_ids.append(list(message_ids))
        self.request_started.set()
        try:
            await self.release_request.wait()
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise
        return [fake_media(message_id) for message_id in message_ids]


def make_service(tmp_path, *, client=None, config=None, sleep=None, random_value=None):
    store = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    store.initialize()
    library, _ = store.create_or_get_library(
        -1001, "channel", "demo", "Demo", "https://t.me/demo/1"
    )
    loop = asyncio.get_running_loop()
    app = SimpleNamespace(loop=loop)
    recorder = sleep or SleepRecorder()
    service = ChannelLibraryService(
        app,
        client or FakeClient(),
        store,
        config or ChannelLibraryConfig(
            full_scan_batch_size=50,
            full_scan_delay_min_sec=5.0,
            full_scan_delay_max_sec=5.0,
            transient_retry_delays_sec=(5.0, 15.0, 45.0),
        ),
        recorder,
        (
            (lambda low, _high: low)
            if random_value is None
            else (lambda _low, _high: random_value)
        ),
    )
    service.gate = TelegramActivityGate()
    return service, library, recorder


def finish_full_scan(service, library, snapshot_max=40, messages=()):
    job = service.store.create_scan_job(
        library["id"], "full", 1, snapshot_max
    )
    job = service.store.transition_job(job["id"], "running")
    rows = [extract_media_row(message) for message in messages]
    service.store.commit_fetched_batch(job["id"], rows, end_id=snapshot_max)
    service.indexer.index_through(
        service.store, service.store.get_job(job["id"]), snapshot_max
    )
    return service.store.transition_job(job["id"], "completed")


def finish_partial_scan(service, library, failures, snapshot_max=40, messages=()):
    job = service.store.create_scan_job(
        library["id"], "full", 1, snapshot_max
    )
    job = service.store.transition_job(job["id"], "running")
    rows = [extract_media_row(message) for message in messages]
    service.store.commit_fetched_batch(job["id"], rows, end_id=snapshot_max)
    recorded = []
    for start, end, anchor, uncertain_through in failures:
        recorded.append(
            service.store.record_failed_range(
                job["id"],
                start,
                end,
                "unreadable range",
                reindex_anchor_start=anchor,
                uncertain_through_message_id=uncertain_through,
            )
        )
    service.indexer.index_through(
        service.store, service.store.get_job(job["id"]), snapshot_max
    )
    service.store.transition_job(job["id"], "partial")
    return service.store.get_job(job["id"]), recorded


@async_test
async def test_full_scan_uses_50_id_batches_and_persists_progress(tmp_path):
    service, library, sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 150)

    await service._run_job(job)

    assert service.client.requested_ids == [
        list(range(1, 51)),
        list(range(51, 101)),
        list(range(101, 151)),
    ]
    current = service.store.get_job(job["id"])
    assert current["status"] == "completed"
    assert current["fetched_through_message_id"] == 150
    assert current["indexed_through_message_id"] == 150
    assert service.store.get_library(library["id"])[
        "fetched_through_message_id"
    ] == 150
    assert sleep.delays == [pytest.approx(5.0), pytest.approx(5.0)]


@async_test
async def test_full_scan_uses_immutable_snapshot_and_normalizes_singleton(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    service.client.latest_message_id = 999
    job = service.store.create_scan_job(library["id"], "full", 1, 51)

    await service._run_job(job)

    assert service.client.requested_ids == [list(range(1, 51)), [51]]
    assert service.store.get_job(job["id"])["snapshot_max_message_id"] == 51
    assert service.store.get_media(library["id"], 51)["message_id"] == 51


@async_test
async def test_queue_incremental_snapshots_new_tail_and_uses_low_rate_batches(
    tmp_path,
):
    service, library, sleep = make_service(tmp_path)
    finish_full_scan(service, library, snapshot_max=60)
    service.owner_loop = asyncio.get_running_loop()
    service.client.latest_message_id = 161

    incremental = await service.queue_incremental(library["id"])
    service.client.latest_message_id = 999
    await service._run_job(incremental)

    assert incremental["kind"] == "incremental"
    assert incremental["start_message_id"] == 61
    assert incremental["next_message_id"] == 61
    assert incremental["snapshot_max_message_id"] == 161
    assert service.client.requested_ids == [
        list(range(61, 111)),
        list(range(111, 161)),
        [161],
    ]
    assert sleep.delays == [pytest.approx(1.0), pytest.approx(1.0)]
    assert service.store.get_job(incremental["id"])["status"] == "completed"


@async_test
async def test_queue_incremental_rejects_incomplete_initial_full_before_snapshot(
    tmp_path,
):
    service, library, _sleep = make_service(tmp_path)
    service.store.create_scan_job(library["id"], "full", 1, 40)
    service.owner_loop = asyncio.get_running_loop()
    service.client.latest_message_id = 80

    with pytest.raises(ValueError, match="finished full scan"):
        await service.queue_incremental(library["id"])

    assert service.client.call_loops == []


@async_test
async def test_repair_defaults_to_all_failures_and_resolves_complete_closures(
    tmp_path,
):
    service, library, sleep = make_service(tmp_path)
    _full, failures = finish_partial_scan(
        service,
        library,
        [(5, 6, 1, 20), (15, 16, 11, 40)],
        messages=(
            fake_media(1, "Alpha"),
            fake_media(11, "Bravo"),
            fake_media(21, "Charlie"),
        ),
    )

    repair = service.queue_repair(library["id"])
    await service._run_job(repair)

    assert service.client.requested_ids == [[5, 6], [15, 16]]
    assert sleep.delays == []
    targets = service.store.list_repair_targets(repair["id"])
    assert [target["failure_id"] for target in targets] == [
        failures[0]["id"],
        failures[1]["id"],
    ]
    assert [target["status"] for target in targets] == ["completed", "completed"]
    assert [target["failure_status"] for target in targets] == [
        "resolved",
        "resolved",
    ]
    assert service.store.get_job(repair["id"])["status"] == "completed"
    assert service.store.get_library(library["id"])["status"] == "ready"


@async_test
async def test_selected_repair_resolves_only_successful_target(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    _full, failures = finish_partial_scan(
        service,
        library,
        [(5, 6, 1, 20), (25, 26, 21, 40)],
        messages=(fake_media(1, "Alpha"), fake_media(21, "Bravo")),
    )

    repair = service.queue_repair(library["id"], [failures[1]["id"]])
    await service._run_job(repair)

    assert service.client.requested_ids == [[25, 26]]
    assert service.store.get_job(repair["id"])["status"] == "partial"
    with service.store.connect() as connection:
        statuses = {
            row["id"]: row["status"]
            for row in connection.execute(
                "SELECT id, status FROM channel_scan_failures ORDER BY id"
            )
        }
    assert statuses == {
        failures[0]["id"]: "open",
        failures[1]["id"]: "resolved",
    }


@async_test
async def test_repair_resumes_each_target_from_its_persisted_cursor(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    _full, failures = finish_partial_scan(
        service,
        library,
        [(1, 100, 1, 120)],
        snapshot_max=120,
    )
    repair = service.queue_repair(library["id"], [failures[0]["id"]])
    interrupted = InterruptingSleep()
    service.sleep = interrupted

    with pytest.raises(asyncio.CancelledError):
        await service._run_job(repair)

    target = service.store.list_repair_targets(repair["id"])[0]
    assert target["next_message_id"] == 51
    assert service.store.get_job(repair["id"])["status"] == "queued"

    service.sleep = SleepRecorder()
    await service._run_job(service.store.get_job(repair["id"]))

    assert service.client.requested_ids == [
        list(range(1, 51)),
        list(range(51, 101)),
    ]
    assert service.store.list_repair_targets(repair["id"])[0][
        "status"
    ] == "completed"


def test_retry_failed_job_preserves_kind_snapshot_and_checkpoint(tmp_path):
    async def scenario():
        service, library, _sleep = make_service(tmp_path)
        finish_full_scan(service, library, snapshot_max=10)
        failed = service.store.create_scan_job(
            library["id"], "incremental", 11, 20
        )
        service.store.transition_job(failed["id"], "running")
        service.store.commit_fetched_batch(failed["id"], [], end_id=15)
        service.store.commit_indexed_revision(failed["id"], 15)
        service.store.transition_job(failed["id"], "failed", last_error="offline")

        retried = service.retry_failed_job(library["id"], failed["id"])

        assert retried["id"] != failed["id"]
        assert retried["kind"] == "incremental"
        assert retried["start_message_id"] == 11
        assert retried["next_message_id"] == 16
        assert retried["snapshot_max_message_id"] == 20

    asyncio.run(scenario())


@async_test
async def test_full_incremental_and_repair_use_one_range_runner(
    tmp_path, monkeypatch
):
    calls = []

    async def capture_range(job, start_id, end_id, delay_range):
        calls.append(
            (
                job["kind"],
                job.get("repair_failure_id"),
                start_id,
                end_id,
                delay_range,
            )
        )
        raise asyncio.CancelledError

    full_service, full_library, _sleep = make_service(tmp_path / "full")
    full = full_service.store.create_scan_job(full_library["id"], "full", 1, 10)
    monkeypatch.setattr(full_service, "_scan_range", capture_range)
    with pytest.raises(asyncio.CancelledError):
        await full_service._run_job(full)

    incremental_service, incremental_library, _sleep = make_service(
        tmp_path / "incremental"
    )
    finish_full_scan(incremental_service, incremental_library, snapshot_max=10)
    incremental_service.owner_loop = asyncio.get_running_loop()
    incremental_service.client.latest_message_id = 15
    incremental = await incremental_service.queue_incremental(
        incremental_library["id"]
    )
    monkeypatch.setattr(incremental_service, "_scan_range", capture_range)
    with pytest.raises(asyncio.CancelledError):
        await incremental_service._run_job(incremental)

    repair_service, repair_library, _sleep = make_service(tmp_path / "repair")
    _full, failures = finish_partial_scan(
        repair_service,
        repair_library,
        [(5, 6, 1, 10)],
        snapshot_max=10,
    )
    repair = repair_service.queue_repair(repair_library["id"])
    monkeypatch.setattr(repair_service, "_scan_range", capture_range)
    with pytest.raises(asyncio.CancelledError):
        await repair_service._run_job(repair)

    assert calls == [
        ("full", None, 1, 10, (5.0, 5.0)),
        ("incremental", None, 11, 15, (1.0, 2.0)),
        ("repair", failures[0]["id"], 5, 6, (1.0, 2.0)),
    ]


@async_test
async def test_runner_retries_only_index_after_downloading_revision_clears(
    tmp_path, monkeypatch
):
    service, library, _sleep = make_service(tmp_path)
    finish_full_scan(
        service,
        library,
        snapshot_max=2,
        messages=(fake_media(1, "Alpha"), fake_media(2)),
    )
    with service.store.connect() as connection:
        package_id = connection.execute(
            "SELECT id FROM channel_packages WHERE library_id = ?",
            (library["id"],),
        ).fetchone()[0]

    def begin_download():
        with service.store.connect() as connection:
            connection.execute(
                """
                UPDATE channel_packages
                SET current_download_status = 'downloading'
                WHERE id = ?
                """,
                (package_id,),
            )

    waits = []

    async def finish_download():
        waits.append(True)
        with service.store.connect() as connection:
            connection.execute(
                """
                UPDATE channel_packages
                SET current_download_status = 'cancelled'
                WHERE id = ?
                """,
                (package_id,),
            )

    service.client.on_request = begin_download
    monkeypatch.setattr(service.gate, "wait_until_downloads_idle", finish_download)
    service.owner_loop = asyncio.get_running_loop()
    service.client.latest_message_id = 3
    incremental = await service.queue_incremental(library["id"])

    await service._run_job(incremental)

    with service.store.connect() as connection:
        package = dict(
            connection.execute(
                "SELECT * FROM channel_packages WHERE id = ?", (package_id,)
            ).fetchone()
        )
    assert service.client.requested_ids == [[3]]
    assert waits == [True]
    assert package["end_message_id"] == 3
    assert package["current_download_status"] == "cancelled"
    assert service.store.get_job(incremental["id"])["status"] == "completed"


@async_test
async def test_full_scan_resumes_from_persisted_next_message_id(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 100)
    running = service.store.transition_job(job["id"], "running")
    service.store.commit_fetched_batch(running["id"], [], end_id=50)
    service.store.commit_indexed_revision(running["id"], 50)
    service.store.transition_job(running["id"], "queued")

    await service._run_job(service.store.get_job(job["id"]))

    assert service.client.requested_ids == [list(range(51, 101))]
    assert service.store.get_job(job["id"])["status"] == "completed"


@async_test
async def test_resume_reindexes_fetched_checkpoint_without_refetching(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 50)
    running = service.store.transition_job(job["id"], "running")
    service.store.commit_fetched_batch(
        running["id"], [extract_media_row(fake_media(1, "Alpha"))], end_id=50
    )
    service.store.transition_job(running["id"], "queued")

    await service._run_job(service.store.get_job(job["id"]))

    current = service.store.get_job(job["id"])
    assert service.client.requested_ids == []
    assert current["fetched_through_message_id"] == 50
    assert current["indexed_through_message_id"] == 50
    assert current["status"] == "completed"


@pytest.mark.parametrize(
    ("command", "expected_status"),
    [("pause", "paused_user"), ("stop_job", "stopped")],
)
@async_test
async def test_control_request_applies_after_successful_batch_boundary(
    tmp_path, command, expected_status
):
    service, library, _sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 100)
    service.client.on_request = lambda: getattr(service, command)(job["id"])

    await service._run_job(job)

    current = service.store.get_job(job["id"])
    assert service.client.requested_ids == [list(range(1, 51))]
    assert current["fetched_through_message_id"] == 50
    assert current["indexed_through_message_id"] == 50
    assert current["status"] == expected_status
    assert current["control_requested"] is None


@async_test
async def test_download_activity_auto_pauses_requeues_and_sends_no_batch(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 50)
    download = await service.gate.acquire_download()

    scan = asyncio.create_task(service._run_job(job))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert service.store.get_job(job["id"])["status"] == "auto_paused_download"
    assert service.client.requested_ids == []

    await download.release_and_wait()
    await asyncio.wait_for(scan, 1)

    assert service.store.get_job(job["id"])["status"] == "queued"
    assert service.client.requested_ids == []


@async_test
async def test_transient_errors_retry_with_configured_delays(tmp_path):
    service, library, sleep = make_service(tmp_path)
    service.client.failures = [
        errors.InternalServerError(),
        errors.InternalServerError(),
        errors.InternalServerError(),
    ]
    job = service.store.create_scan_job(library["id"], "full", 1, 50)

    await service._run_job(job)

    assert service.client.requested_ids == [list(range(1, 51))] * 4
    assert sleep.delays == [5.0, 15.0, 45.0]
    current = service.store.get_job(job["id"])
    assert current["retry_count"] == 0
    assert current["status"] == "completed"


@async_test
async def test_retry_resume_uses_only_remaining_persisted_delays(tmp_path):
    service, library, sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 50)
    service.store.transition_job(job["id"], "running")
    service.store.record_job_retry(job["id"], "interrupted first retry")
    service.store.transition_job(job["id"], "queued")
    service.client.failures = [
        errors.InternalServerError(),
        errors.InternalServerError(),
    ]

    await service._run_job(service.store.get_job(job["id"]))

    assert service.client.requested_ids == [list(range(1, 51))] * 3
    assert sleep.delays == [15.0, 45.0]
    current = service.store.get_job(job["id"])
    assert current["retry_count"] == 0
    assert current["status"] == "completed"


@async_test
async def test_repeated_restarts_cannot_exceed_batch_retry_budget(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 50)
    service.client.failures = [errors.InternalServerError()] * 4

    for expected_count, expected_delay in [(1, 5.0), (2, 15.0), (3, 45.0)]:
        interrupted_sleep = InterruptingSleep()
        service.sleep = interrupted_sleep
        with pytest.raises(asyncio.CancelledError):
            await service._run_job(service.store.get_job(job["id"]))
        current = service.store.get_job(job["id"])
        assert current["status"] == "queued"
        assert current["retry_count"] == expected_count
        assert interrupted_sleep.delays == [expected_delay]

    service.sleep = SleepRecorder()
    await service._run_job(service.store.get_job(job["id"]))

    current = service.store.get_job(job["id"])
    assert len(service.client.requested_ids) == 4
    assert current["status"] == "partial"
    assert current["retry_count"] == 0


@async_test
async def test_success_resets_retry_budget_before_next_batch(tmp_path):
    config = ChannelLibraryConfig(
        full_scan_batch_size=50,
        full_scan_delay_min_sec=7.0,
        full_scan_delay_max_sec=7.0,
        transient_retry_delays_sec=(5.0, 15.0, 45.0),
    )
    service, library, sleep = make_service(tmp_path, config=config)
    service.client.failures = [
        errors.InternalServerError(),
        None,
        errors.InternalServerError(),
    ]
    job = service.store.create_scan_job(library["id"], "full", 1, 100)

    await service._run_job(job)

    assert service.client.requested_ids == [
        list(range(1, 51)),
        list(range(1, 51)),
        list(range(51, 101)),
        list(range(51, 101)),
    ]
    assert sleep.delays == [5.0, 7.0, 5.0]
    current = service.store.get_job(job["id"])
    assert current["retry_count"] == 0
    assert current["status"] == "completed"


@async_test
async def test_final_transient_batch_failure_is_recorded_and_scan_continues(tmp_path):
    service, library, sleep = make_service(tmp_path)
    service.client.failures = [errors.InternalServerError()] * 4
    job = service.store.create_scan_job(library["id"], "full", 1, 100)

    await service._run_job(job)

    current = service.store.get_job(job["id"])
    assert service.client.requested_ids[-1] == list(range(51, 101))
    assert current["status"] == "partial"
    assert current["fetched_through_message_id"] == 100
    assert current["indexed_through_message_id"] == 100
    assert sleep.delays == [5.0, 15.0, 45.0]


@async_test
async def test_flood_wait_persists_absolute_deadline_without_retry(tmp_path):
    service, library, sleep = make_service(tmp_path, random_value=2.0)
    service.client.failures = [errors.FloodWait(20)]
    job = service.store.create_scan_job(library["id"], "full", 1, 50)
    before = time.time()

    await service._run_job(job)

    current = service.store.get_job(job["id"])
    assert current["status"] == "waiting_rate_limit"
    assert before + 22 <= current["wait_until"] <= time.time() + 22
    assert current["wait_reason"] == "FloodWait"
    assert current["fetched_through_message_id"] == 0
    assert current["retry_count"] == 0
    assert sleep.delays == []


@async_test
async def test_permanent_permission_error_fails_without_advancing(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    service.client.failures = [errors.ChannelPrivate()]
    job = service.store.create_scan_job(library["id"], "full", 1, 50)

    await service._run_job(job)

    current = service.store.get_job(job["id"])
    assert current["status"] == "failed"
    assert current["fetched_through_message_id"] == 0
    assert "CHANNEL_PRIVATE" in current["last_error"]


@async_test
async def test_sqlite_failure_never_advances_checkpoint(tmp_path, monkeypatch):
    service, library, _sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 50)

    def fail_commit(*_args, **_kwargs):
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(service.store, "commit_fetched_batch", fail_commit)

    await service._run_job(job)

    current = service.store.get_job(job["id"])
    assert current["status"] == "failed"
    assert current["fetched_through_message_id"] == 0
    assert current["next_message_id"] == 1


@async_test
async def test_sqlite_failure_while_recording_failed_range_stops_job(
    tmp_path, monkeypatch
):
    service, library, _sleep = make_service(tmp_path)
    service.client.failures = [errors.InternalServerError()] * 4
    job = service.store.create_scan_job(library["id"], "full", 1, 50)

    def fail_record(*_args, **_kwargs):
        raise sqlite3.OperationalError("failure table unavailable")

    monkeypatch.setattr(service.store, "record_failed_range", fail_record)

    await service._run_job(job)

    current = service.store.get_job(job["id"])
    assert current["status"] == "failed"
    assert current["fetched_through_message_id"] == 0
    assert current["next_message_id"] == 1


@async_test
async def test_start_stop_are_idempotent_and_recover_interrupted_job(tmp_path):
    service, library, _sleep = make_service(tmp_path)
    job = service.store.create_scan_job(library["id"], "full", 1, 50)
    service.store.transition_job(job["id"], "running")
    service.pause(job["id"])

    await service.start()
    scheduler = service.scheduler_task
    await service.start()

    assert service.owner_loop is asyncio.get_running_loop()
    assert service.scheduler_task is scheduler
    assert service.store.get_job(job["id"])["status"] == "paused_user"

    await service.stop()
    await service.stop()
    assert scheduler.done()


@async_test
async def test_second_service_cannot_recover_store_owned_by_live_service(
    tmp_path, monkeypatch
):
    first, library, _sleep = make_service(tmp_path)
    await first.start()
    job = first.store.create_scan_job(library["id"], "full", 1, 50)
    first.store.transition_job(job["id"], "running")
    before = first.store.get_job(job["id"])

    second, _library, _sleep = make_service(tmp_path)
    original_recover = second.store.recover_interrupted_jobs
    recovery_calls = []

    def tracked_recover(*args, **kwargs):
        recovery_calls.append(True)
        return original_recover(*args, **kwargs)

    monkeypatch.setattr(second.store, "recover_interrupted_jobs", tracked_recover)

    with pytest.raises(RuntimeError, match="already owned"):
        await second.start()

    assert recovery_calls == []
    assert second.store.get_job(job["id"]) == before

    await first.stop()
    await second.start()
    assert recovery_calls == [True]
    assert second.store.get_job(job["id"])["status"] == "queued"
    await second.stop()


@async_test
async def test_stop_waits_for_active_request_and_checkpoint_boundary(tmp_path):
    client = BlockingClient()
    service, library, _sleep = make_service(tmp_path, client=client)
    job = service.store.create_scan_job(library["id"], "full", 1, 50)
    await service.start()
    await asyncio.wait_for(client.request_started.wait(), 1)

    stopping = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    assert not stopping.done()
    assert client.was_cancelled is False

    client.release_request.set()
    await asyncio.wait_for(stopping, 1)

    current = service.store.get_job(job["id"])
    assert client.was_cancelled is False
    assert current["fetched_through_message_id"] == 50
    assert current["indexed_through_message_id"] == 50
    assert current["status"] == "queued"


@async_test
async def test_cancelled_stop_retains_ownership_until_internal_cleanup_finishes(
    tmp_path
):
    client = BlockingClient()
    service, library, _sleep = make_service(tmp_path, client=client)
    job = service.store.create_scan_job(library["id"], "full", 1, 50)
    await service.start()
    await asyncio.wait_for(client.request_started.wait(), 1)

    stopping = asyncio.create_task(service.stop())
    await asyncio.sleep(0)
    cleanup = service._shutdown_task
    assert cleanup is not None and not cleanup.done()

    stopping.cancel()
    with pytest.raises(asyncio.CancelledError):
        await stopping

    successor, _library, _sleep = make_service(tmp_path)
    with pytest.raises(RuntimeError, match="already owned"):
        await successor.start()
    assert client.was_cancelled is False
    assert service.scheduler_task is not None and not service.scheduler_task.done()
    assert cleanup.cancelled() is False

    client.release_request.set()
    await service.stop()

    current = service.store.get_job(job["id"])
    assert service._shutdown_task is cleanup
    assert cleanup.done() and not cleanup.cancelled()
    assert service.scheduler_task.done()
    assert client.was_cancelled is False
    assert current["fetched_through_message_id"] == 50
    assert current["indexed_through_message_id"] == 50
    assert current["status"] == "queued"

    service.store.transition_job(job["id"], "running")
    await successor.start()
    assert successor.store.get_job(job["id"])["status"] == "queued"
    await successor.stop()


@async_test
async def test_scheduler_runs_multiple_libraries_strictly_serially(tmp_path):
    service, first, _sleep = make_service(tmp_path)
    second, _ = service.store.create_or_get_library(
        -1002, "channel", "two", "Two", "https://t.me/two/1"
    )
    first_job = service.store.create_scan_job(first["id"], "full", 1, 1)
    second_job = service.store.create_scan_job(second["id"], "full", 1, 1)

    await service.start()
    deadline = asyncio.get_running_loop().time() + 1
    while (
        service.store.get_job(second_job["id"])["status"] != "completed"
        and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0)
    await service.stop()

    assert service.store.get_job(first_job["id"])["status"] == "completed"
    assert service.store.get_job(second_job["id"])["status"] == "completed"
    assert service.client.requested_chats == [-1001, -1002]


@async_test
async def test_resolve_creates_snapshot_once_and_duplicate_returns_existing(tmp_path):
    client = FakeClient()
    client.latest_message_id = 87
    service, _library, _sleep = make_service(tmp_path, client=client)
    with service.store.connect() as connection:
        connection.execute("DELETE FROM channel_scan_jobs")
        connection.execute("DELETE FROM channel_libraries")
    await service.start()

    created = await service.resolve_and_create_library("https://t.me/demo/20")
    duplicate = await service.resolve_and_create_library("https://t.me/demo/21")

    assert created.created is True
    assert created.job["snapshot_max_message_id"] == 87
    assert duplicate.created is False
    assert duplicate.library["id"] == created.library["id"]
    assert duplicate.job["id"] == created.job["id"]
    assert client.call_loops and set(client.call_loops) == {service.owner_loop}
    await service.stop()


@async_test
async def test_threadsafe_submit_runs_resolution_on_owner_loop(tmp_path):
    client = FakeClient()
    client.latest_message_id = 3
    service, _library, _sleep = make_service(tmp_path, client=client)
    with service.store.connect() as connection:
        connection.execute("DELETE FROM channel_scan_jobs")
        connection.execute("DELETE FROM channel_libraries")
    await service.start()

    submitted = await asyncio.to_thread(
        service.submit_library_link_threadsafe, "https://t.me/demo/1"
    )
    result = await asyncio.wrap_future(submitted)

    assert result.created is True
    assert client.call_loops and set(client.call_loops) == {service.owner_loop}
    assert threading.current_thread() is threading.main_thread()
    await service.stop()


@async_test
async def test_resolve_rejects_non_channel_chat(tmp_path):
    client = FakeClient()
    client.chat.type = "private"
    service, _library, _sleep = make_service(tmp_path, client=client)
    await service.start()

    with pytest.raises(ValueError, match="channel or supergroup"):
        await service.resolve_and_create_library("https://t.me/demo/1")

    await service.stop()

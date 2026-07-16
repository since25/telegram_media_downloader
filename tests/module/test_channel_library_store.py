"""Tests for the persistent channel library store."""

import sqlite3

import pytest

from module.channel_library_store import (
    ALLOWED_SCAN_TRANSITIONS,
    ChannelLibraryStore,
)


REQUIRED_TABLES = {
    "schema_meta",
    "channel_libraries",
    "channel_scan_jobs",
    "channel_media_messages",
    "channel_packages",
    "channel_package_items",
    "channel_scan_failures",
    "channel_scan_repair_targets",
    "channel_package_selections",
    "channel_download_batches",
    "channel_download_batch_packages",
    "channel_download_batch_items",
}


@pytest.fixture
def store(tmp_path):
    result = ChannelLibraryStore(tmp_path / "channel_library.sqlite3")
    result.initialize()
    return result


def make_library(store, chat_id=-1001):
    library, _ = store.create_or_get_library(
        chat_id,
        "channel",
        "demo",
        "Demo",
        "https://t.me/demo",
    )
    return library


def make_full_job(store, snapshot_max_id=100, chat_id=-1001):
    library = make_library(store, chat_id=chat_id)
    return store.create_scan_job(library["id"], "full", 1, snapshot_max_id)


def make_job(store, status="queued", wait_until=None, chat_id=-1001):
    job = make_full_job(store, chat_id=chat_id)
    with store.connect() as connection:
        connection.execute(
            """
            UPDATE channel_scan_jobs
            SET status = ?, wait_until = ?
            WHERE id = ?
            """,
            (status, wait_until, job["id"]),
        )
    return store.get_job(job["id"])


def media_row(message_id, media_type="video"):
    return {
        "message_id": message_id,
        "message_date": "2026-07-16T00:00:00+00:00",
        "media_type": media_type,
        "media_group_id": None,
        "caption": "Lesson",
        "file_name": f"lesson-{message_id}.mp4",
        "file_size": 100,
        "mime_type": "video/mp4",
        "duration": 10,
        "width": 1280,
        "height": 720,
        "raw_fingerprint": f"fingerprint-{message_id}",
    }


def make_partial_job_with_failures(store):
    job = make_full_job(store, snapshot_max_id=40)
    store.transition_job(job["id"], "running", now=1.0)
    first = store.record_failed_range(
        job["id"],
        1,
        10,
        "first failure",
        reindex_anchor_start=1,
        uncertain_through_message_id=15,
        now=2.0,
    )
    second = store.record_failed_range(
        job["id"],
        30,
        40,
        "second failure",
        reindex_anchor_start=25,
        uncertain_through_message_id=40,
        now=3.0,
    )
    store.commit_fetched_batch(job["id"], [], end_id=40, now=4.0)
    store.commit_indexed_revision(job["id"], 40, now=5.0)
    store.transition_job(job["id"], "partial", now=6.0)
    return store.get_job(job["id"]), first, second


def test_store_initializes_secure_wal_schema(tmp_path):
    store = ChannelLibraryStore(tmp_path / "channel_library.sqlite3")
    store.initialize()
    assert (store.path.stat().st_mode & 0o777) == 0o600
    with store.connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert REQUIRED_TABLES <= tables


def test_library_is_unique_by_chat_id(tmp_path):
    store = ChannelLibraryStore(tmp_path / "library.sqlite3")
    store.initialize()
    first, created = store.create_or_get_library(
        -1001, "channel", "demo", "Demo", "https://t.me/demo/1"
    )
    second, created_again = store.create_or_get_library(
        -1001, "channel", "demo", "Renamed", "https://t.me/demo/9"
    )
    assert created is True and created_again is False
    assert second["id"] == first["id"] and second["title"] == "Renamed"


def test_repair_target_enforces_library_ownership(tmp_path):
    store = ChannelLibraryStore(tmp_path / "library.sqlite3")
    store.initialize()
    library_a, _ = store.create_or_get_library(
        -1001, "channel", "one", "One", "https://t.me/one"
    )
    library_b, _ = store.create_or_get_library(
        -1002, "channel", "two", "Two", "https://t.me/two"
    )

    with store.connect() as connection:
        job_a = connection.execute(
            """
            INSERT INTO channel_scan_jobs (
                library_id, kind, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (library_a["id"], "full", "completed", 1.0, 1.0),
        ).lastrowid
        job_b = connection.execute(
            """
            INSERT INTO channel_scan_jobs (
                library_id, kind, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (library_b["id"], "full", "completed", 1.0, 1.0),
        ).lastrowid
        failure_a = connection.execute(
            """
            INSERT INTO channel_scan_failures (
                job_id, library_id, start_message_id, end_message_id,
                last_error, reindex_anchor_start,
                uncertain_through_message_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_a, library_a["id"], 1, 50, "failure-a", 1, 50, 1.0, 1.0),
        ).lastrowid
        failure_b = connection.execute(
            """
            INSERT INTO channel_scan_failures (
                job_id, library_id, start_message_id, end_message_id,
                last_error, reindex_anchor_start,
                uncertain_through_message_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (job_b, library_b["id"], 51, 100, "failure-b", 51, 100, 1.0, 1.0),
        ).lastrowid

        connection.execute(
            """
            INSERT INTO channel_scan_repair_targets (
                job_id, failure_id, library_id, next_message_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (job_a, failure_a, library_a["id"], 1, 1.0, 1.0),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO channel_scan_repair_targets (
                    job_id, failure_id, library_id, next_message_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (job_a, failure_b, library_a["id"], 51, 1.0, 1.0),
            )

        target_count = connection.execute(
            "SELECT COUNT(*) FROM channel_scan_repair_targets"
        ).fetchone()[0]
    assert target_count == 1


def test_scan_transition_table_is_exact():
    assert ALLOWED_SCAN_TRANSITIONS == {
        "queued": {"running", "paused_user", "stopped", "failed"},
        "running": {
            "queued",
            "paused_user",
            "auto_paused_download",
            "waiting_rate_limit",
            "stopped",
            "completed",
            "partial",
            "failed",
        },
        "auto_paused_download": {"queued", "paused_user", "stopped", "failed"},
        "waiting_rate_limit": {"queued", "paused_user", "stopped", "failed"},
        "paused_user": {"queued", "stopped"},
        "stopped": {"queued"},
        "completed": set(),
        "partial": set(),
        "failed": set(),
    }


def test_create_and_claim_oldest_queued_job(store):
    first = make_full_job(store, chat_id=-1001)
    second = make_full_job(store, chat_id=-1002)

    claimed = store.claim_next_job(now=10.0)

    assert claimed["id"] == first["id"]
    assert claimed["status"] == "running"
    assert claimed["started_at"] == 10.0
    assert store.get_job(second["id"])["status"] == "queued"


def test_illegal_scan_transition_is_rejected(store):
    job = make_full_job(store)

    with pytest.raises(ValueError, match="Illegal scan transition"):
        store.transition_job(job["id"], "completed", now=1.0)

    assert store.get_job(job["id"])["status"] == "queued"


def test_waiting_job_cannot_queue_before_deadline(store):
    job = make_job(store, status="waiting_rate_limit", wait_until=200.0)

    with pytest.raises(ValueError, match="rate-limit deadline"):
        store.transition_job(job["id"], "queued", now=100.0)

    assert store.get_job(job["id"])["status"] == "waiting_rate_limit"


def test_stopped_job_must_be_resumed_instead_of_replaced(store):
    job = make_full_job(store)
    store.transition_job(job["id"], "stopped", now=1.0)

    with pytest.raises(ValueError, match="recoverable scan job"):
        store.create_scan_job(job["library_id"], "full", 1, 100)

    resumed = store.transition_job(job["id"], "queued", now=2.0)
    assert resumed["id"] == job["id"]
    assert resumed["status"] == "queued"


def test_incremental_job_requires_finished_full_scan(store):
    library = make_library(store)

    with pytest.raises(ValueError, match="finished full scan"):
        store.create_scan_job(library["id"], "incremental", 1, 100)


def test_fetched_batch_and_checkpoint_commit_together(store):
    job = make_full_job(store, snapshot_max_id=100)

    store.commit_fetched_batch(job["id"], [media_row(50)], end_id=50)

    current = store.get_job(job["id"])
    assert current["fetched_through_message_id"] == 50
    assert current["indexed_through_message_id"] == 0
    assert current["next_message_id"] == 51
    assert store.get_media(job["library_id"], 50) is not None


def test_fetched_batch_rolls_back_media_when_checkpoint_fails(store):
    job = make_full_job(store, snapshot_max_id=100)
    invalid = media_row(51, media_type=None)

    with pytest.raises(sqlite3.IntegrityError):
        store.commit_fetched_batch(
            job["id"], [media_row(50), invalid], end_id=51
        )

    assert store.get_job(job["id"])["fetched_through_message_id"] == 0
    assert store.get_media(job["library_id"], 50) is None


def test_fetch_and_index_watermarks_advance_independently(store):
    job = make_full_job(store, snapshot_max_id=100)
    store.commit_fetched_batch(job["id"], [media_row(50)], end_id=50)

    indexed = store.commit_indexed_revision(job["id"], 25, now=10.0)

    assert indexed["fetched_through_message_id"] == 50
    assert indexed["indexed_through_message_id"] == 25
    assert indexed["index_revision"] == 1
    library = store.get_library(job["library_id"])
    assert library["fetched_through_message_id"] == 50
    assert library["indexed_through_message_id"] == 25


def test_index_checkpoint_cannot_advance_past_fetched_data(store):
    job = make_full_job(store, snapshot_max_id=100)

    with pytest.raises(ValueError, match="fetched watermark"):
        store.commit_indexed_revision(job["id"], 1)

    current = store.get_job(job["id"])
    assert current["indexed_through_message_id"] == 0
    assert current["index_revision"] == 0


@pytest.mark.parametrize("final_status,library_status", [("completed", "ready"), ("partial", "partial")])
def test_terminal_status_requires_both_watermarks(
    store, final_status, library_status
):
    job = make_full_job(store, snapshot_max_id=10)
    store.transition_job(job["id"], "running", now=1.0)
    store.commit_fetched_batch(job["id"], [], end_id=10, now=2.0)

    with pytest.raises(ValueError, match="watermarks"):
        store.transition_job(job["id"], final_status, now=3.0)

    store.commit_indexed_revision(job["id"], 10, now=4.0)
    finished = store.transition_job(job["id"], final_status, now=5.0)
    assert finished["status"] == final_status
    assert store.get_library(job["library_id"])["status"] == library_status


def test_adjacent_failed_ranges_merge_but_separate_ranges_do_not(store):
    job = make_full_job(store, snapshot_max_id=100)
    first = store.record_failed_range(
        job["id"],
        1,
        10,
        "first",
        reindex_anchor_start=1,
        uncertain_through_message_id=15,
        now=1.0,
    )
    merged = store.record_failed_range(
        job["id"],
        11,
        20,
        "second",
        reindex_anchor_start=5,
        uncertain_through_message_id=25,
        now=2.0,
    )
    separate = store.record_failed_range(
        job["id"],
        30,
        40,
        "third",
        reindex_anchor_start=30,
        uncertain_through_message_id=45,
        now=3.0,
    )

    assert merged["id"] == first["id"]
    assert (merged["start_message_id"], merged["end_message_id"]) == (1, 20)
    assert merged["reindex_anchor_start"] == 1
    assert merged["uncertain_through_message_id"] == 25
    assert separate["id"] != merged["id"]
    with store.connect() as connection:
        open_count = connection.execute(
            """
            SELECT COUNT(*) FROM channel_scan_failures
            WHERE library_id = ? AND status = ?
            """,
            (job["library_id"], "open"),
        ).fetchone()[0]
    assert open_count == 2


def test_repair_job_persists_independent_target_cursors(store):
    original, first, second = make_partial_job_with_failures(store)

    repair = store.create_repair_job(original["library_id"], now=10.0)
    targets = store.list_repair_targets(repair["id"])

    assert [target["failure_id"] for target in targets] == [
        first["id"],
        second["id"],
    ]
    assert [target["next_message_id"] for target in targets] == [1, 30]

    store.resolve_repair_target(
        repair["id"], first["id"], next_message_id=6, now=11.0
    )
    store.resolve_repair_target(
        repair["id"], second["id"], next_message_id=41, now=12.0
    )
    updated = store.list_repair_targets(repair["id"])
    assert updated[0]["next_message_id"] == 6
    assert updated[0]["status"] == "running"
    assert updated[0]["failure_status"] == "repairing"
    assert updated[1]["status"] == "completed"
    assert updated[1]["failure_status"] == "resolved"


def test_recovery_respects_rate_limit_deadline(store):
    job = make_job(store, status="waiting_rate_limit", wait_until=200.0)

    store.recover_interrupted_jobs(now=100.0)
    waiting = store.get_job(job["id"])
    assert waiting["status"] == "waiting_rate_limit"
    assert waiting["wait_until"] == 200.0

    store.recover_interrupted_jobs(now=201.0)
    assert store.get_job(job["id"])["status"] == "queued"


@pytest.mark.parametrize("interrupted", ["running", "auto_paused_download"])
def test_recovery_requeues_only_interrupted_jobs(store, interrupted):
    job = make_job(store, status=interrupted)

    recovered = store.recover_interrupted_jobs(now=100.0)

    assert recovered == 1
    assert store.get_job(job["id"])["status"] == "queued"


@pytest.mark.parametrize(
    "preserved", ["queued", "paused_user", "stopped", "completed", "partial", "failed"]
)
def test_recovery_preserves_non_interrupted_states(store, preserved):
    job = make_job(store, status=preserved)

    recovered = store.recover_interrupted_jobs(now=100.0)

    assert recovered == 0
    assert store.get_job(job["id"])["status"] == preserved

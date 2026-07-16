"""Tests for persisted channel messages and revisioned package indexing."""

import datetime
import sqlite3
from types import SimpleNamespace

import pytest

from module.channel_library_store import ChannelLibraryStore
from module.channel_library_workflow import (
    ChannelPackageIndexer,
    MediaDTO,
    PersistedMessageAdapter,
    extract_media_row,
)
from module.comment_workflow import plan_message_package_sequence


UTC = datetime.timezone.utc


def fake_media(
    message_id,
    caption,
    *,
    media_type="video",
    size=100,
    media_group_id=None,
    date=None,
):
    extension = "jpg" if media_type == "photo" else "mp4"
    mime_type = "image/jpeg" if media_type == "photo" else "video/mp4"
    media = SimpleNamespace(
        file_name=f"media-{message_id}.{extension}",
        file_size=size,
        mime_type=mime_type,
        duration=message_id,
        width=1280,
        height=720,
    )
    values = {
        "id": message_id,
        "empty": False,
        "caption": caption,
        "media": media_type,
        "media_group_id": media_group_id,
        "date": date or datetime.datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
        "audio": None,
        "document": None,
        "photo": None,
        "video": None,
        "voice": None,
        "video_note": None,
    }
    values[media_type] = media
    return SimpleNamespace(**values)


def summarize_sequence(sequence):
    return [
        {
            "title": package.package_title,
            "ids": [item.message.id for item in package.items],
            "captions": [item.caption_for_naming for item in package.items],
            "original": [item.original_caption for item in package.items],
            "inherited": [item.inherited_caption for item in package.items],
            "known_size": package.size_summary.known_total_size,
            "unknown_size": package.size_summary.unknown_size_count,
            "next": (
                package.next_package_message.id
                if package.next_package_message is not None
                else None
            ),
            "warning": package.scan_warning,
        }
        for package in sequence.all_packages
    ]


@pytest.fixture
def store(tmp_path):
    result = ChannelLibraryStore(tmp_path / "channel_library.sqlite3")
    result.initialize()
    return result


def make_running_job(store, snapshot_max_id=100):
    library, _ = store.create_or_get_library(
        -1001,
        "channel",
        "demo",
        "Demo",
        "https://t.me/demo",
    )
    job = store.create_scan_job(
        library["id"], "full", 1, snapshot_max_id, now=2.0
    )
    return store.transition_job(job["id"], "running", now=3.0)


def persist_messages(store, job, messages, end_id, now=10.0):
    rows = [extract_media_row(message) for message in messages]
    store.commit_fetched_batch(job["id"], rows, end_id=end_id, now=now)
    return store.get_job(job["id"])


def start_incremental_job(store, full_job, snapshot_max_id):
    store.transition_job(full_job["id"], "completed", now=16.0)
    incremental = store.create_scan_job(
        full_job["library_id"],
        "incremental",
        int(full_job["snapshot_max_message_id"]) + 1,
        snapshot_max_id,
        now=17.0,
    )
    return store.transition_job(incremental["id"], "running", now=18.0)


def package_rows(store, library_id):
    with store.connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM channel_packages
            WHERE library_id = ?
            ORDER BY start_message_id, id
            """,
            (library_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def active_package_rows(store, library_id):
    return [
        row
        for row in package_rows(store, library_id)
        if row["boundary_status"] != "superseded"
    ]


def package_item_ids(store, library_id, package_id):
    with store.connect() as connection:
        return [
            row[0]
            for row in connection.execute(
                """
                SELECT message_id FROM channel_package_items
                WHERE library_id = ? AND package_id = ?
                ORDER BY ordinal
                """,
                (library_id, package_id),
            )
        ]


def test_extract_media_row_and_adapter_preserve_planner_fields():
    local_tz = datetime.timezone(datetime.timedelta(hours=8))
    message = fake_media(
        7,
        "Course 07",
        size=987,
        media_group_id="album-7",
        date=datetime.datetime(2026, 7, 16, 16, 30, tzinfo=local_tz),
    )

    row = extract_media_row(message)
    repeated = extract_media_row(message)
    adapted = PersistedMessageAdapter.from_row(row)

    assert row == repeated
    assert row["message_date"] == "2026-07-16T08:30:00+00:00"
    assert len(row["raw_fingerprint"]) == 64
    assert adapted.id == 7
    assert adapted.empty is False
    assert adapted.caption == "Course 07"
    assert adapted.media_group_id == "album-7"
    assert adapted.date == datetime.datetime(2026, 7, 16, 8, 30, tzinfo=UTC)
    assert adapted.media == "video"
    assert adapted.video == MediaDTO(
        file_name="media-7.mp4",
        file_size=987,
        mime_type="video/mp4",
        duration=7,
        width=1280,
        height=720,
    )
    assert adapted.photo is None

    non_media = SimpleNamespace(id=8, empty=False, media=None, text="hello")
    assert extract_media_row(non_media) is None


@pytest.mark.parametrize(
    "real",
    [
        [
            fake_media(1, "Course 01", size=10),
            fake_media(2, None, size=20),
            fake_media(3, "Course 02", size=30),
        ],
        [
            fake_media(10, None, media_type="photo", media_group_id="album-1"),
            fake_media(
                11,
                "Album EP01",
                media_type="photo",
                media_group_id="album-1",
            ),
            fake_media(12, None, media_type="photo", media_group_id="album-1"),
            fake_media(20, "Album EP02", media_type="photo"),
        ],
    ],
    ids=["caption-boundary", "album-caption"],
)
def test_persisted_adapter_matches_real_message_plan(real):
    adapted = [
        PersistedMessageAdapter.from_row(extract_media_row(item)) for item in real
    ]
    expected = plan_message_package_sequence(
        real, real[0].id, following_package_count=2, max_scan_count=len(real) + 1
    )
    actual = plan_message_package_sequence(
        adapted,
        adapted[0].id,
        following_package_count=2,
        max_scan_count=len(adapted) + 1,
    )

    assert summarize_sequence(actual) == summarize_sequence(expected)


def test_indexer_keeps_tail_provisional_until_cross_batch_boundary(store):
    job = make_running_job(store, snapshot_max_id=100)
    first_batch = [fake_media(1, "Alpha Series")]
    first_batch.extend(fake_media(message_id, None) for message_id in range(2, 51))
    job = persist_messages(store, job, first_batch, end_id=50)

    first = ChannelPackageIndexer().index_through(store, job, 50)

    packages = active_package_rows(store, job["library_id"])
    assert first.stable_package_count == 0
    assert [(row["start_message_id"], row["end_message_id"], row["boundary_status"]) for row in packages] == [
        (1, 50, "provisional")
    ]

    job = persist_messages(store, job, [fake_media(51, "Bravo Series")], end_id=51)
    ChannelPackageIndexer().index_through(store, job, 51)

    packages = active_package_rows(store, job["library_id"])
    assert [
        (row["start_message_id"], row["end_message_id"], row["boundary_status"])
        for row in packages
    ] == [(1, 50, "stable"), (51, 51, "provisional")]


def test_indexer_does_not_turn_500_window_into_false_boundary(store):
    job = make_running_job(store, snapshot_max_id=600)
    same_package = [
        fake_media(message_id, "Long Course") for message_id in range(1, 502)
    ]
    job = persist_messages(store, job, same_package, end_id=501)

    ChannelPackageIndexer().index_through(store, job, 501)

    packages = active_package_rows(store, job["library_id"])
    assert len(packages) == 1
    assert (packages[0]["start_message_id"], packages[0]["end_message_id"]) == (
        1,
        501,
    )
    assert packages[0]["boundary_status"] == "provisional"
    assert package_item_ids(store, job["library_id"], packages[0]["id"]) == list(
        range(1, 502)
    )

    job = persist_messages(store, job, [fake_media(502, "Next Course")], end_id=502)
    ChannelPackageIndexer().index_through(store, job, 502)
    packages = active_package_rows(store, job["library_id"])
    assert [row["boundary_status"] for row in packages] == [
        "stable",
        "provisional",
    ]
    assert packages[0]["end_message_id"] == 501


def test_indexer_stabilizes_nonempty_tail_only_at_snapshot_end(store):
    job = make_running_job(store, snapshot_max_id=3)
    job = persist_messages(
        store,
        job,
        [fake_media(1, "Course"), fake_media(2, None)],
        end_id=2,
    )

    ChannelPackageIndexer().index_through(store, job, 2)
    assert active_package_rows(store, job["library_id"])[0][
        "boundary_status"
    ] == "provisional"

    job = persist_messages(store, job, [fake_media(3, None)], end_id=3)
    result = ChannelPackageIndexer().index_through(store, job, 3)
    package = active_package_rows(store, job["library_id"])[0]
    assert package["boundary_status"] == "stable"
    assert package["end_message_id"] == 3
    assert result.indexed_through_message_id == 3
    assert result.stable_package_count == 1


def test_unresolved_failure_closure_never_shrinks_at_a_proven_boundary(store):
    job = make_running_job(store, snapshot_max_id=40)
    messages = [
        fake_media(1, "Alpha"),
        fake_media(11, "Bravo"),
        fake_media(21, "Charlie"),
    ]
    job = persist_messages(store, job, messages, end_id=21)
    failure = store.record_failed_range(
        job["id"],
        5,
        10,
        "unreadable range",
        reindex_anchor_start=1,
        uncertain_through_message_id=21,
        now=11.0,
    )

    ChannelPackageIndexer().index_through(store, job, 21)

    packages = active_package_rows(store, job["library_id"])
    assert [
        (row["start_message_id"], row["boundary_status"]) for row in packages
    ] == [(1, "uncertain"), (11, "uncertain"), (21, "uncertain")]
    with store.connect() as connection:
        uncertain_through = connection.execute(
            "SELECT uncertain_through_message_id FROM channel_scan_failures WHERE id = ?",
            (failure["id"],),
        ).fetchone()[0]
    assert uncertain_through == 21


def test_split_and_merge_supersede_removed_start_identities(store):
    job = make_running_job(store, snapshot_max_id=3)
    original = [
        fake_media(1, "Alpha"),
        fake_media(2, None),
        fake_media(3, "Bravo"),
    ]
    job = persist_messages(store, job, original, end_id=3)
    ChannelPackageIndexer().index_through(store, job, 3)
    first = {row["start_message_id"]: row for row in active_package_rows(store, job["library_id"])}
    assert set(first) == {1, 3}
    store.record_failed_range(
        job["id"],
        2,
        2,
        "repaired metadata",
        reindex_anchor_start=1,
        uncertain_through_message_id=3,
        now=15.0,
    )

    job = persist_messages(store, job, [fake_media(2, "Bravo")], end_id=3, now=20.0)
    ChannelPackageIndexer().index_through(store, job, 3)
    split = {row["start_message_id"]: row for row in package_rows(store, job["library_id"])}
    assert split[1]["id"] == first[1]["id"]
    assert split[3]["boundary_status"] == "superseded"
    assert split[3]["superseded_by_package_id"] == split[2]["id"]

    job = persist_messages(store, job, [fake_media(2, None)], end_id=3, now=30.0)
    ChannelPackageIndexer().index_through(store, job, 3)
    merged = {row["start_message_id"]: row for row in package_rows(store, job["library_id"])}
    assert merged[2]["boundary_status"] == "superseded"
    assert merged[2]["superseded_by_package_id"] == merged[1]["id"]
    assert merged[3]["id"] == first[3]["id"]
    assert merged[3]["boundary_status"] == "uncertain"
    assert merged[3]["superseded_by_package_id"] is None


def test_changed_package_invalidates_existing_selection(store):
    job = make_running_job(store, snapshot_max_id=2)
    job = persist_messages(
        store,
        job,
        [fake_media(1, "Alpha"), fake_media(2, None)],
        end_id=2,
    )
    ChannelPackageIndexer().index_through(store, job, 2)
    package = active_package_rows(store, job["library_id"])[0]
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO channel_package_selections (
                library_id, package_id, package_revision, selected,
                created_at, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?)
            """,
            (
                job["library_id"],
                package["id"],
                package["index_revision"],
                15.0,
                15.0,
            ),
        )

    job = start_incremental_job(store, job, snapshot_max_id=3)
    job = persist_messages(store, job, [fake_media(3, None)], end_id=3, now=20.0)
    ChannelPackageIndexer().index_through(store, job, 3)

    with store.connect() as connection:
        selection = connection.execute(
            """
            SELECT * FROM channel_package_selections
            WHERE library_id = ? AND package_id = ?
            """,
            (job["library_id"], package["id"]),
        ).fetchone()
    assert selection["selected"] == 0
    assert selection["invalidation_reason"] == "package_revision_changed"


def test_successful_changed_revision_becomes_outdated_without_losing_history(store):
    job = make_running_job(store, snapshot_max_id=2)
    job = persist_messages(
        store,
        job,
        [fake_media(1, "Alpha"), fake_media(2, None)],
        end_id=2,
    )
    ChannelPackageIndexer().index_through(store, job, 2)
    package = active_package_rows(store, job["library_id"])[0]
    with store.connect() as connection:
        connection.execute(
            """
            UPDATE channel_packages
            SET current_download_status = 'completed',
                has_successful_attempt = 1,
                completed_revision = ?, last_successful_at = ?
            WHERE id = ?
            """,
            (package["index_revision"], 15.0, package["id"]),
        )

    job = start_incremental_job(store, job, snapshot_max_id=3)
    job = persist_messages(store, job, [fake_media(3, None)], end_id=3, now=20.0)
    ChannelPackageIndexer().index_through(store, job, 3)

    changed = {row["id"]: row for row in package_rows(store, job["library_id"])}[
        package["id"]
    ]
    assert changed["index_revision"] > package["index_revision"]
    assert changed["current_download_status"] == "outdated"
    assert changed["has_successful_attempt"] == 1
    assert changed["completed_revision"] == package["index_revision"]
    assert changed["last_successful_at"] == 15.0


def test_incremental_caption_boundary_creates_new_package_without_revising_old(store):
    job = make_running_job(store, snapshot_max_id=2)
    job = persist_messages(
        store,
        job,
        [fake_media(1, "Alpha"), fake_media(2, None)],
        end_id=2,
    )
    ChannelPackageIndexer().index_through(store, job, 2)
    original = active_package_rows(store, job["library_id"])[0]

    job = start_incremental_job(store, job, snapshot_max_id=3)
    job = persist_messages(store, job, [fake_media(3, "Bravo")], end_id=3)
    ChannelPackageIndexer().index_through(store, job, 3)

    packages = active_package_rows(store, job["library_id"])
    assert [(row["start_message_id"], row["end_message_id"]) for row in packages] == [
        (1, 2),
        (3, 3),
    ]
    assert packages[0]["id"] == original["id"]
    assert packages[0]["index_revision"] == original["index_revision"]
    assert packages[1]["index_revision"] > original["index_revision"]


def test_changed_revision_waits_while_overlapping_package_is_downloading(store):
    job = make_running_job(store, snapshot_max_id=2)
    job = persist_messages(
        store,
        job,
        [fake_media(1, "Alpha"), fake_media(2, None)],
        end_id=2,
    )
    ChannelPackageIndexer().index_through(store, job, 2)
    original = active_package_rows(store, job["library_id"])[0]
    with store.connect() as connection:
        connection.execute(
            "UPDATE channel_packages SET current_download_status = 'downloading' WHERE id = ?",
            (original["id"],),
        )

    job = start_incremental_job(store, job, snapshot_max_id=3)
    job = persist_messages(store, job, [fake_media(3, None)], end_id=3)
    deferred = ChannelPackageIndexer().index_through(store, job, 3)

    unchanged = active_package_rows(store, job["library_id"])[0]
    assert deferred.publication_deferred is True
    assert unchanged["end_message_id"] == 2
    assert unchanged["index_revision"] == original["index_revision"]
    assert unchanged["current_download_status"] == "downloading"
    assert store.get_job(job["id"])["indexed_through_message_id"] == 2

    with store.connect() as connection:
        connection.execute(
            "UPDATE channel_packages SET current_download_status = 'cancelled' WHERE id = ?",
            (original["id"],),
        )
    published = ChannelPackageIndexer().index_through(store, job, 3)

    changed = active_package_rows(store, job["library_id"])[0]
    assert published.publication_deferred is False
    assert changed["end_message_id"] == 3
    assert changed["index_revision"] > original["index_revision"]
    assert store.get_job(job["id"])["indexed_through_message_id"] == 3


def test_repair_media_and_target_cursor_commit_atomically(store):
    job = make_running_job(store, snapshot_max_id=20)
    job = persist_messages(store, job, [fake_media(1, "Alpha")], end_id=20)
    failure = store.record_failed_range(
        job["id"],
        5,
        6,
        "unreadable range",
        reindex_anchor_start=1,
        uncertain_through_message_id=20,
    )
    ChannelPackageIndexer().index_through(store, job, 20)
    store.transition_job(job["id"], "partial")
    repair = store.create_repair_job(job["library_id"], [failure["id"]])
    repair = store.transition_job(repair["id"], "running")
    with store.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER abort_repair_target_cursor
            BEFORE UPDATE OF next_message_id ON channel_scan_repair_targets
            BEGIN
                SELECT RAISE(ABORT, 'repair cursor blocked');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="repair cursor blocked"):
        store.commit_fetched_batch(
            repair["id"],
            [extract_media_row(fake_media(5, None))],
            end_id=5,
            repair_failure_id=failure["id"],
        )

    assert store.get_media(job["library_id"], 5) is None
    target = store.list_repair_targets(repair["id"])[0]
    assert target["next_message_id"] == 5
    assert target["status"] == "queued"


def test_repair_closure_publication_and_resolution_commit_atomically(store):
    job = make_running_job(store, snapshot_max_id=21)
    job = persist_messages(
        store,
        job,
        [
            fake_media(1, "Alpha"),
            fake_media(11, "Bravo"),
            fake_media(21, "Charlie"),
        ],
        end_id=21,
    )
    failure = store.record_failed_range(
        job["id"],
        5,
        6,
        "unreadable range",
        reindex_anchor_start=1,
        uncertain_through_message_id=20,
    )
    ChannelPackageIndexer().index_through(store, job, 21)
    store.transition_job(job["id"], "partial")
    repair = store.create_repair_job(job["library_id"], [failure["id"]])
    repair = store.transition_job(repair["id"], "running")
    store.commit_fetched_batch(
        repair["id"],
        [extract_media_row(fake_media(5, None))],
        end_id=6,
        repair_failure_id=failure["id"],
    )
    before_job = store.get_job(repair["id"])
    before_library = store.get_library(job["library_id"])
    before_packages = package_rows(store, job["library_id"])
    with store.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER abort_repair_failure_resolution
            BEFORE UPDATE OF status ON channel_scan_failures
            WHEN NEW.status = 'resolved'
            BEGIN
                SELECT RAISE(ABORT, 'repair resolution blocked');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="repair resolution blocked"):
        ChannelPackageIndexer().index_through(
            store,
            store.get_job(repair["id"]),
            20,
            resolve_failure_id=failure["id"],
        )

    target = store.list_repair_targets(repair["id"])[0]
    assert target["status"] == "running"
    assert target["failure_status"] == "repairing"
    assert store.get_job(repair["id"])["index_revision"] == before_job[
        "index_revision"
    ]
    assert store.get_job(repair["id"])["indexed_through_message_id"] == before_job[
        "indexed_through_message_id"
    ]
    assert store.get_library(job["library_id"])[
        "indexed_through_message_id"
    ] == before_library["indexed_through_message_id"]
    assert package_rows(store, job["library_id"]) == before_packages

    with store.connect() as connection:
        connection.execute("DROP TRIGGER abort_repair_failure_resolution")
    ChannelPackageIndexer().index_through(
        store,
        store.get_job(repair["id"]),
        20,
        resolve_failure_id=failure["id"],
    )

    target = store.list_repair_targets(repair["id"])[0]
    assert target["status"] == "completed"
    assert target["failure_status"] == "resolved"
    assert all(
        package["boundary_status"] != "uncertain"
        for package in active_package_rows(store, job["library_id"])
        if package["start_message_id"] <= 20
    )


def test_package_publication_rolls_back_with_index_watermark(store):
    job = make_running_job(store, snapshot_max_id=1)
    job = persist_messages(store, job, [fake_media(1, "Alpha")], end_id=1)
    with store.connect() as connection:
        connection.execute(
            """
            CREATE TRIGGER abort_package_index_checkpoint
            BEFORE UPDATE OF indexed_through_message_id ON channel_scan_jobs
            WHEN NEW.indexed_through_message_id > OLD.indexed_through_message_id
            BEGIN
                SELECT RAISE(ABORT, 'index checkpoint blocked');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="index checkpoint blocked"):
        ChannelPackageIndexer().index_through(store, job, 1)

    assert package_rows(store, job["library_id"]) == []
    assert store.get_job(job["id"])["indexed_through_message_id"] == 0
    assert store.get_job(job["id"])["index_revision"] == 0
    assert store.get_library(job["library_id"])["index_revision"] == 0

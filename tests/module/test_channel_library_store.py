"""Tests for the persistent channel library store."""

import sqlite3

import pytest

from module.channel_library_store import ChannelLibraryStore


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

"""Tests for the persistent channel library store."""

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

"""Persistent storage foundation for the Web channel library."""

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence, Union


SCHEMA_VERSION = 1

LIBRARY_STATUSES = frozenset(
    {"new", "indexing", "ready", "partial", "paused", "stopped", "failed"}
)
SCAN_JOB_KINDS = frozenset({"full", "incremental", "repair"})
SCAN_JOB_STATUSES = frozenset(
    {
        "queued",
        "running",
        "paused_user",
        "auto_paused_download",
        "waiting_rate_limit",
        "stopped",
        "completed",
        "partial",
        "failed",
    }
)
PACKAGE_BOUNDARY_STATUSES = frozenset(
    {"stable", "provisional", "uncertain", "superseded"}
)
PACKAGE_DOWNLOAD_STATUSES = frozenset(
    {
        "never",
        "queued",
        "downloading",
        "completed",
        "outdated",
        "failed",
        "cancelled",
    }
)
SCAN_FAILURE_STATUSES = frozenset({"open", "repairing", "resolved"})
DOWNLOAD_DISPATCH_STATUSES = frozenset({"pending_dispatch", "dispatched"})


@dataclass(frozen=True)
class ChannelLibraryConfig:
    """Validated, immutable channel-library runtime configuration."""

    full_scan_batch_size: int = 50
    full_scan_delay_min_sec: float = 4.0
    full_scan_delay_max_sec: float = 6.0
    incremental_scan_batch_size: int = 50
    incremental_scan_delay_min_sec: float = 1.0
    incremental_scan_delay_max_sec: float = 2.0
    transient_retry_delays_sec: Sequence[float] = (5.0, 15.0, 45.0)

    @classmethod
    def from_mapping(cls, raw: Optional[dict]) -> "ChannelLibraryConfig":
        raw = raw or {}
        full_min = max(float(raw.get("full_scan_delay_min_sec", 4)), 2.0)
        inc_min = max(float(raw.get("incremental_scan_delay_min_sec", 1)), 0.5)
        return cls(
            full_scan_batch_size=min(
                max(int(raw.get("full_scan_batch_size", 50)), 1), 100
            ),
            full_scan_delay_min_sec=full_min,
            full_scan_delay_max_sec=max(
                float(raw.get("full_scan_delay_max_sec", 6)), full_min
            ),
            incremental_scan_batch_size=min(
                max(int(raw.get("incremental_scan_batch_size", 50)), 1), 100
            ),
            incremental_scan_delay_min_sec=inc_min,
            incremental_scan_delay_max_sec=max(
                float(raw.get("incremental_scan_delay_max_sec", 2)), inc_min
            ),
            transient_retry_delays_sec=tuple(
                float(value)
                for value in raw.get("transient_retry_delays_sec", (5, 15, 45))
            ),
        )


class ChannelLibraryStore:
    """SQLite storage for channel-library state."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta (
                    version INTEGER PRIMARY KEY,
                    applied_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS channel_libraries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER NOT NULL UNIQUE,
                    chat_type TEXT NOT NULL
                        CHECK (chat_type IN ('channel', 'supergroup')),
                    username TEXT,
                    title TEXT NOT NULL,
                    source_link TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new'
                        CHECK (status IN (
                            'new', 'indexing', 'ready', 'partial', 'paused',
                            'stopped', 'failed'
                        )),
                    fetched_through_message_id INTEGER NOT NULL DEFAULT 0,
                    indexed_through_message_id INTEGER NOT NULL DEFAULT 0,
                    index_revision INTEGER NOT NULL DEFAULT 0,
                    last_full_scan_at REAL,
                    last_incremental_scan_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS channel_scan_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_id INTEGER NOT NULL,
                    kind TEXT NOT NULL
                        CHECK (kind IN ('full', 'incremental', 'repair')),
                    status TEXT NOT NULL DEFAULT 'queued'
                        CHECK (status IN (
                            'queued', 'running', 'paused_user',
                            'auto_paused_download', 'waiting_rate_limit',
                            'stopped', 'completed', 'partial', 'failed'
                        )),
                    snapshot_max_message_id INTEGER NOT NULL DEFAULT 0,
                    start_message_id INTEGER NOT NULL DEFAULT 1,
                    next_message_id INTEGER NOT NULL DEFAULT 1,
                    fetched_through_message_id INTEGER NOT NULL DEFAULT 0,
                    indexed_through_message_id INTEGER NOT NULL DEFAULT 0,
                    index_revision INTEGER NOT NULL DEFAULT 0,
                    scanned_id_count INTEGER NOT NULL DEFAULT 0,
                    visible_message_count INTEGER NOT NULL DEFAULT 0,
                    media_count INTEGER NOT NULL DEFAULT 0,
                    stable_package_count INTEGER NOT NULL DEFAULT 0,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    wait_until REAL,
                    wait_reason TEXT,
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    UNIQUE (id, library_id),
                    FOREIGN KEY (library_id) REFERENCES channel_libraries(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS channel_media_messages (
                    library_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    message_date TEXT,
                    media_type TEXT NOT NULL,
                    media_group_id TEXT,
                    caption TEXT,
                    file_name TEXT,
                    file_size INTEGER,
                    mime_type TEXT,
                    duration INTEGER,
                    width INTEGER,
                    height INTEGER,
                    raw_fingerprint TEXT NOT NULL,
                    first_seen_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (library_id, message_id),
                    FOREIGN KEY (library_id) REFERENCES channel_libraries(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS channel_packages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_id INTEGER NOT NULL,
                    start_message_id INTEGER NOT NULL,
                    end_message_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    published_at TEXT,
                    boundary_status TEXT NOT NULL DEFAULT 'provisional'
                        CHECK (boundary_status IN (
                            'stable', 'provisional', 'uncertain', 'superseded'
                        )),
                    media_count INTEGER NOT NULL DEFAULT 0,
                    known_total_size INTEGER NOT NULL DEFAULT 0,
                    unknown_size_count INTEGER NOT NULL DEFAULT 0,
                    current_download_status TEXT NOT NULL DEFAULT 'never'
                        CHECK (current_download_status IN (
                            'never', 'queued', 'downloading', 'completed',
                            'outdated', 'failed', 'cancelled'
                        )),
                    has_successful_attempt INTEGER NOT NULL DEFAULT 0
                        CHECK (has_successful_attempt IN (0, 1)),
                    completed_revision INTEGER,
                    last_successful_at REAL,
                    last_download_task_id TEXT,
                    last_downloaded_at REAL,
                    download_attempt_count INTEGER NOT NULL DEFAULT 0,
                    superseded_by_package_id INTEGER,
                    index_revision INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE (library_id, start_message_id),
                    UNIQUE (library_id, id),
                    FOREIGN KEY (library_id) REFERENCES channel_libraries(id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (library_id, superseded_by_package_id)
                        REFERENCES channel_packages(library_id, id)
                );

                CREATE TABLE IF NOT EXISTS channel_package_items (
                    library_id INTEGER NOT NULL,
                    package_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    caption_for_naming TEXT,
                    original_caption TEXT,
                    inherited_caption TEXT,
                    PRIMARY KEY (library_id, package_id, message_id),
                    UNIQUE (library_id, package_id, ordinal),
                    FOREIGN KEY (library_id, package_id)
                        REFERENCES channel_packages(library_id, id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (library_id, message_id)
                        REFERENCES channel_media_messages(library_id, message_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS channel_scan_failures (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    library_id INTEGER NOT NULL,
                    start_message_id INTEGER NOT NULL,
                    end_message_id INTEGER NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    last_error TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'repairing', 'resolved')),
                    reindex_anchor_start INTEGER NOT NULL,
                    uncertain_through_message_id INTEGER NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    resolved_at REAL,
                    UNIQUE (id, library_id),
                    FOREIGN KEY (job_id, library_id)
                        REFERENCES channel_scan_jobs(id, library_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (library_id) REFERENCES channel_libraries(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS channel_scan_repair_targets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL,
                    failure_id INTEGER NOT NULL,
                    library_id INTEGER NOT NULL,
                    next_message_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    UNIQUE (job_id, failure_id),
                    FOREIGN KEY (job_id, library_id)
                        REFERENCES channel_scan_jobs(id, library_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (failure_id, library_id)
                        REFERENCES channel_scan_failures(id, library_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS channel_package_selections (
                    library_id INTEGER NOT NULL,
                    package_id INTEGER NOT NULL,
                    package_revision INTEGER NOT NULL,
                    selected INTEGER NOT NULL DEFAULT 1
                        CHECK (selected IN (0, 1)),
                    invalidation_reason TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (library_id, package_id),
                    FOREIGN KEY (library_id, package_id)
                        REFERENCES channel_packages(library_id, id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS channel_download_batches (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_id INTEGER NOT NULL,
                    task_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL,
                    dispatch_status TEXT NOT NULL DEFAULT 'pending_dispatch'
                        CHECK (dispatch_status IN (
                            'pending_dispatch', 'dispatched'
                        )),
                    status TEXT NOT NULL DEFAULT 'queued',
                    allow_redownload INTEGER NOT NULL DEFAULT 0
                        CHECK (allow_redownload IN (0, 1)),
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    dispatched_at REAL,
                    completed_at REAL,
                    UNIQUE (library_id, idempotency_key),
                    UNIQUE (library_id, id),
                    FOREIGN KEY (library_id) REFERENCES channel_libraries(id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS channel_download_batch_packages (
                    batch_id INTEGER NOT NULL,
                    library_id INTEGER NOT NULL,
                    package_id INTEGER NOT NULL,
                    package_revision INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    start_message_id INTEGER NOT NULL,
                    end_message_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    last_error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    PRIMARY KEY (batch_id, package_id),
                    UNIQUE (batch_id, ordinal),
                    UNIQUE (batch_id, package_id, library_id),
                    FOREIGN KEY (library_id, batch_id)
                        REFERENCES channel_download_batches(library_id, id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (library_id, package_id)
                        REFERENCES channel_packages(library_id, id)
                );

                CREATE TABLE IF NOT EXISTS channel_download_batch_items (
                    batch_id INTEGER NOT NULL,
                    package_id INTEGER NOT NULL,
                    library_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    ordinal INTEGER NOT NULL,
                    media_type TEXT NOT NULL,
                    caption_for_naming TEXT,
                    original_caption TEXT,
                    inherited_caption TEXT,
                    PRIMARY KEY (batch_id, package_id, message_id),
                    UNIQUE (batch_id, package_id, ordinal),
                    FOREIGN KEY (batch_id, package_id, library_id)
                        REFERENCES channel_download_batch_packages(
                            batch_id, package_id, library_id
                        ) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_channel_libraries_status_updated
                    ON channel_libraries(status, updated_at);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_channel_scan_jobs_active_library
                    ON channel_scan_jobs(library_id)
                    WHERE status IN (
                        'queued', 'running', 'paused_user',
                        'auto_paused_download', 'waiting_rate_limit', 'stopped'
                    );
                CREATE INDEX IF NOT EXISTS idx_channel_scan_jobs_status_created
                    ON channel_scan_jobs(status, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_channel_media_messages_group
                    ON channel_media_messages(library_id, media_group_id);
                CREATE INDEX IF NOT EXISTS idx_channel_packages_listing
                    ON channel_packages(
                        library_id, boundary_status, start_message_id, id
                    );
                CREATE INDEX IF NOT EXISTS idx_channel_packages_download_status
                    ON channel_packages(library_id, current_download_status);
                CREATE INDEX IF NOT EXISTS idx_channel_package_items_message
                    ON channel_package_items(library_id, message_id);
                CREATE INDEX IF NOT EXISTS idx_channel_scan_failures_open_range
                    ON channel_scan_failures(
                        library_id, status, start_message_id, end_message_id
                    );
                CREATE INDEX IF NOT EXISTS idx_channel_scan_repair_targets_status
                    ON channel_scan_repair_targets(job_id, status, id);
                CREATE INDEX IF NOT EXISTS idx_channel_package_selections_selected
                    ON channel_package_selections(library_id, selected, package_id);
                CREATE INDEX IF NOT EXISTS idx_channel_download_batches_dispatch
                    ON channel_download_batches(dispatch_status, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_channel_download_batches_status
                    ON channel_download_batches(library_id, status, created_at);
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_meta (version, applied_at) VALUES (?, ?)",
                (SCHEMA_VERSION, time.time()),
            )
        os.chmod(self.path, 0o600)

    def create_or_get_library(
        self,
        chat_id: int,
        chat_type: str,
        username: Optional[str],
        title: str,
        source_link: str,
    ) -> tuple[dict, bool]:
        now = time.time()
        with self.connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO channel_libraries (
                    chat_id, chat_type, username, title, source_link,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(chat_id) DO NOTHING
                """,
                (chat_id, chat_type, username, title, source_link, now, now),
            )
            created = cursor.rowcount == 1
            if not created:
                connection.execute(
                    """
                    UPDATE channel_libraries
                    SET chat_type = ?, username = ?, title = ?, source_link = ?,
                        updated_at = ?
                    WHERE chat_id = ?
                    """,
                    (chat_type, username, title, source_link, now, chat_id),
                )
            row = connection.execute(
                "SELECT * FROM channel_libraries WHERE chat_id = ?", (chat_id,)
            ).fetchone()
        return dict(row), created

    def get_library(self, library_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM channel_libraries WHERE id = ?", (library_id,)
            ).fetchone()
        return dict(row) if row is not None else None

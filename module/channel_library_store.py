"""Persistent storage foundation for the Web channel library."""

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence, Union


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

ALLOWED_SCAN_TRANSITIONS = {
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

    @staticmethod
    def _insert_scan_job(
        connection: sqlite3.Connection,
        library: sqlite3.Row,
        kind: str,
        start_message_id: int,
        snapshot_max_message_id: int,
        now: float,
    ) -> int:
        fetched = int(library["fetched_through_message_id"])
        indexed = int(library["indexed_through_message_id"])
        cursor = max(start_message_id, fetched + 1)
        return connection.execute(
            """
            INSERT INTO channel_scan_jobs (
                library_id, kind, snapshot_max_message_id, start_message_id,
                next_message_id, fetched_through_message_id,
                indexed_through_message_id, index_revision,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                library["id"],
                kind,
                snapshot_max_message_id,
                start_message_id,
                cursor,
                fetched,
                indexed,
                library["index_revision"],
                now,
                now,
            ),
        ).lastrowid

    def create_scan_job(
        self,
        library_id: int,
        kind: str,
        start_message_id: int,
        snapshot_max_message_id: int,
        now: Optional[float] = None,
    ) -> dict:
        if kind not in SCAN_JOB_KINDS:
            raise ValueError(f"Unsupported scan job kind: {kind}")
        if start_message_id < 1 or snapshot_max_message_id < start_message_id - 1:
            raise ValueError("Invalid scan message range")
        now = time.time() if now is None else now
        with self.connect() as connection:
            library = connection.execute(
                "SELECT * FROM channel_libraries WHERE id = ?", (library_id,)
            ).fetchone()
            if library is None:
                raise KeyError(f"Channel library {library_id} does not exist")
            active = connection.execute(
                """
                SELECT id FROM channel_scan_jobs
                WHERE library_id = ? AND status IN (
                    'queued', 'running', 'paused_user',
                    'auto_paused_download', 'waiting_rate_limit', 'stopped'
                )
                LIMIT 1
                """,
                (library_id,),
            ).fetchone()
            if active is not None:
                raise ValueError(
                    f"Library {library_id} already has a recoverable scan job"
                )
            if kind == "incremental":
                finished_full = connection.execute(
                    """
                    SELECT id FROM channel_scan_jobs
                    WHERE library_id = ? AND kind = 'full'
                      AND status IN ('completed', 'partial')
                    LIMIT 1
                    """,
                    (library_id,),
                ).fetchone()
                if finished_full is None:
                    raise ValueError("Incremental scan requires a finished full scan")
            job_id = self._insert_scan_job(
                connection,
                library,
                kind,
                start_message_id,
                snapshot_max_message_id,
                now,
            )
            connection.execute(
                """
                UPDATE channel_libraries
                SET status = 'indexing', updated_at = ?
                WHERE id = ?
                """,
                (now, library_id),
            )
            row = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(row)

    def get_job(self, job_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    def claim_next_job(self, now: Optional[float] = None) -> Optional[dict]:
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            running = connection.execute(
                """
                SELECT id FROM channel_scan_jobs
                WHERE status = 'running'
                LIMIT 1
                """
            ).fetchone()
            if running is not None:
                return None
            row = connection.execute(
                """
                SELECT * FROM channel_scan_jobs
                WHERE status = 'queued'
                ORDER BY created_at, id
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            connection.execute(
                """
                UPDATE channel_scan_jobs
                SET status = 'running', started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, row["id"]),
            )
            connection.execute(
                """
                UPDATE channel_libraries
                SET status = 'indexing', updated_at = ?
                WHERE id = ?
                """,
                (now, row["library_id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (row["id"],)
            ).fetchone()
        return dict(claimed)

    def transition_job(
        self,
        job_id: int,
        new_status: str,
        *,
        now: Optional[float] = None,
        wait_until: Optional[float] = None,
        wait_reason: Optional[str] = None,
        last_error: Optional[str] = None,
    ) -> dict:
        if new_status not in SCAN_JOB_STATUSES:
            raise ValueError(f"Unsupported scan job status: {new_status}")
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            current_status = job["status"]
            if new_status not in ALLOWED_SCAN_TRANSITIONS[current_status]:
                raise ValueError(
                    f"Illegal scan transition: {current_status} -> {new_status}"
                )
            if new_status == "running":
                other_runner = connection.execute(
                    """
                    SELECT id FROM channel_scan_jobs
                    WHERE status = 'running' AND id != ?
                    LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
                if other_runner is not None:
                    raise ValueError("Another scan job is already running")
            deadline = job["wait_until"]
            if (
                new_status in {"queued", "running"}
                and deadline is not None
                and now < deadline
            ):
                raise ValueError("Cannot resume before the rate-limit deadline")
            if new_status == "waiting_rate_limit" and wait_until is None:
                raise ValueError("Rate-limited jobs require an absolute wait_until")
            if new_status in {"completed", "partial"} and (
                job["fetched_through_message_id"]
                < job["snapshot_max_message_id"]
                or job["indexed_through_message_id"]
                < job["snapshot_max_message_id"]
            ):
                raise ValueError(
                    "Cannot finish scan before fetch and index watermarks reach snapshot"
                )
            if new_status in {"completed", "partial"} and job["kind"] == "repair":
                incomplete_target = connection.execute(
                    """
                    SELECT id FROM channel_scan_repair_targets
                    WHERE job_id = ? AND status != 'completed'
                    LIMIT 1
                    """,
                    (job_id,),
                ).fetchone()
                if incomplete_target is not None:
                    raise ValueError(
                        "Cannot finish repair before all repair targets complete"
                    )
            if new_status == "completed":
                unresolved_failure = connection.execute(
                    """
                    SELECT id FROM channel_scan_failures
                    WHERE library_id = ? AND status != 'resolved'
                    LIMIT 1
                    """,
                    (job["library_id"],),
                ).fetchone()
                if unresolved_failure is not None:
                    raise ValueError(
                        "Cannot complete library while unresolved failures remain"
                    )

            next_wait_until = job["wait_until"]
            next_wait_reason = job["wait_reason"]
            if new_status == "waiting_rate_limit":
                next_wait_until = wait_until
                next_wait_reason = wait_reason
            elif new_status == "queued":
                next_wait_until = None
                next_wait_reason = None
            started_at = job["started_at"]
            if new_status == "running" and started_at is None:
                started_at = now
            completed_at = (
                now if new_status in {"completed", "partial", "failed"} else None
            )
            connection.execute(
                """
                UPDATE channel_scan_jobs
                SET status = ?, started_at = ?, updated_at = ?,
                    completed_at = ?, wait_until = ?, wait_reason = ?,
                    last_error = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    started_at,
                    now,
                    completed_at,
                    next_wait_until,
                    next_wait_reason,
                    job["last_error"] if last_error is None else last_error,
                    job_id,
                ),
            )
            library_status = {
                "paused_user": "paused",
                "stopped": "stopped",
                "completed": "ready",
                "partial": "partial",
                "failed": "failed",
            }.get(new_status, "indexing")
            connection.execute(
                """
                UPDATE channel_libraries
                SET status = ?,
                    last_full_scan_at = CASE
                        WHEN ? = 'full' AND ? IN ('completed', 'partial')
                        THEN ? ELSE last_full_scan_at END,
                    last_incremental_scan_at = CASE
                        WHEN ? = 'incremental' AND ? IN ('completed', 'partial')
                        THEN ? ELSE last_incremental_scan_at END,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    library_status,
                    job["kind"],
                    new_status,
                    now,
                    job["kind"],
                    new_status,
                    now,
                    now,
                    job["library_id"],
                ),
            )
            updated = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(updated)

    def commit_fetched_batch(
        self,
        job_id: int,
        media_rows: Sequence[Mapping[str, object]],
        end_id: int,
        now: Optional[float] = None,
    ) -> dict:
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            if job["status"] != "running":
                raise ValueError("Checkpoint writes require a running scan job")
            if end_id < job["start_message_id"] - 1:
                raise ValueError("Fetch checkpoint precedes the scan range")
            if end_id > job["snapshot_max_message_id"]:
                raise ValueError("Fetch checkpoint exceeds the scan snapshot")
            for media in media_rows:
                connection.execute(
                    """
                    INSERT INTO channel_media_messages (
                        library_id, message_id, message_date, media_type,
                        media_group_id, caption, file_name, file_size, mime_type,
                        duration, width, height, raw_fingerprint,
                        first_seen_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(library_id, message_id) DO UPDATE SET
                        message_date = excluded.message_date,
                        media_type = excluded.media_type,
                        media_group_id = excluded.media_group_id,
                        caption = excluded.caption,
                        file_name = excluded.file_name,
                        file_size = excluded.file_size,
                        mime_type = excluded.mime_type,
                        duration = excluded.duration,
                        width = excluded.width,
                        height = excluded.height,
                        raw_fingerprint = excluded.raw_fingerprint,
                        updated_at = excluded.updated_at
                    """,
                    (
                        job["library_id"],
                        media["message_id"],
                        media.get("message_date"),
                        media["media_type"],
                        media.get("media_group_id"),
                        media.get("caption"),
                        media.get("file_name"),
                        media.get("file_size"),
                        media.get("mime_type"),
                        media.get("duration"),
                        media.get("width"),
                        media.get("height"),
                        media["raw_fingerprint"],
                        media.get("first_seen_at", now),
                        now,
                    ),
                )
            fetched = max(job["fetched_through_message_id"], end_id)
            scanned_delta = max(0, end_id - job["fetched_through_message_id"])
            media_count = connection.execute(
                """
                SELECT COUNT(*) FROM channel_media_messages
                WHERE library_id = ?
                """,
                (job["library_id"],),
            ).fetchone()[0]
            connection.execute(
                """
                UPDATE channel_scan_jobs
                SET next_message_id = MAX(next_message_id, ?),
                    fetched_through_message_id = ?,
                    scanned_id_count = scanned_id_count + ?,
                    visible_message_count = MAX(visible_message_count, ?),
                    media_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    end_id + 1,
                    fetched,
                    scanned_delta,
                    media_count,
                    media_count,
                    now,
                    job_id,
                ),
            )
            connection.execute(
                """
                UPDATE channel_libraries
                SET fetched_through_message_id = MAX(
                        fetched_through_message_id, ?
                    ),
                    updated_at = ?
                WHERE id = ?
                """,
                (fetched, now, job["library_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(updated)

    def get_media(self, library_id: int, message_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM channel_media_messages
                WHERE library_id = ? AND message_id = ?
                """,
                (library_id, message_id),
            ).fetchone()
        return dict(row) if row is not None else None

    def load_package_index_context(
        self,
        job_id: int,
        library_id: int,
        through_message_id: int,
    ) -> dict:
        """Load the persisted tail and unresolved failures for one index pass."""

        with self.connect() as connection:
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            if job["library_id"] != library_id:
                raise ValueError("Scan job does not belong to the requested library")
            if job["status"] != "running":
                raise ValueError("Package indexing requires a running scan job")
            if through_message_id > job["fetched_through_message_id"]:
                raise ValueError("Index checkpoint exceeds the fetched watermark")
            if through_message_id > job["snapshot_max_message_id"]:
                raise ValueError("Index checkpoint exceeds the scan snapshot")

            tail = connection.execute(
                """
                SELECT start_message_id FROM channel_packages
                WHERE library_id = ? AND boundary_status != 'superseded'
                  AND start_message_id <= ?
                ORDER BY start_message_id DESC, id DESC
                LIMIT 1
                """,
                (library_id, through_message_id),
            ).fetchone()
            failures = connection.execute(
                """
                SELECT * FROM channel_scan_failures
                WHERE library_id = ? AND status != 'resolved'
                  AND reindex_anchor_start <= ?
                ORDER BY reindex_anchor_start, id
                """,
                (library_id, through_message_id),
            ).fetchall()
            repair_anchors = connection.execute(
                """
                SELECT f.reindex_anchor_start
                FROM channel_scan_repair_targets AS t
                JOIN channel_scan_failures AS f
                  ON f.id = t.failure_id AND f.library_id = t.library_id
                WHERE t.job_id = ? AND t.library_id = ?
                  AND f.reindex_anchor_start <= ?
                ORDER BY f.reindex_anchor_start
                """,
                (job_id, library_id, through_message_id),
            ).fetchall()

            anchors = []
            if tail is not None:
                anchors.append(int(tail["start_message_id"]))
            anchors.extend(int(row["reindex_anchor_start"]) for row in failures)
            anchors.extend(
                int(row["reindex_anchor_start"]) for row in repair_anchors
            )
            if anchors:
                reindex_anchor_start = min(anchors)
            else:
                first_media = connection.execute(
                    """
                    SELECT MIN(message_id) FROM channel_media_messages
                    WHERE library_id = ? AND message_id <= ?
                    """,
                    (library_id, through_message_id),
                ).fetchone()[0]
                reindex_anchor_start = (
                    int(first_media)
                    if first_media is not None
                    else max(1, int(job["start_message_id"]))
                )

            media_rows = connection.execute(
                """
                SELECT * FROM channel_media_messages
                WHERE library_id = ? AND message_id BETWEEN ? AND ?
                ORDER BY message_id
                """,
                (library_id, reindex_anchor_start, through_message_id),
            ).fetchall()
        return {
            "job": dict(job),
            "reindex_anchor_start": reindex_anchor_start,
            "media_rows": [dict(row) for row in media_rows],
            "failures": [dict(row) for row in failures],
        }

    def publish_indexed_packages(
        self,
        job_id: int,
        through_message_id: int,
        reindex_anchor_start: int,
        packages: Sequence[Mapping[str, object]],
        failure_updates: Sequence[Mapping[str, object]] = (),
        now: Optional[float] = None,
    ) -> dict:
        """Atomically publish derived packages, items, revision, and watermark."""

        now = time.time() if now is None else now
        desired_packages = [dict(package) for package in packages]
        desired_starts = [int(package["start_message_id"]) for package in desired_packages]
        if len(desired_starts) != len(set(desired_starts)):
            raise ValueError("Package start message IDs must be unique")
        if any(
            start < reindex_anchor_start or start > through_message_id
            for start in desired_starts
        ):
            raise ValueError("Package starts outside the reindex range")

        def normalize_inherited(value: object) -> bool:
            if isinstance(value, str):
                return value not in {"", "0", "false", "False"}
            return bool(value)

        def item_signature(item: Mapping[str, object]) -> tuple:
            return (
                int(item["message_id"]),
                int(item["ordinal"]),
                str(item["media_type"]),
                item["caption_for_naming"],
                item["original_caption"],
                normalize_inherited(item["inherited_caption"]),
            )

        def package_content_signature(
            package: Mapping[str, object], package_items: Sequence[Mapping[str, object]]
        ) -> tuple:
            return (
                int(package["end_message_id"]),
                str(package["title"]),
                package["published_at"],
                int(package["media_count"]),
                int(package["known_total_size"]),
                int(package["unknown_size_count"]),
                tuple(item_signature(item) for item in package_items),
            )

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            if job["status"] != "running":
                raise ValueError("Package indexing requires a running scan job")
            if through_message_id > job["fetched_through_message_id"]:
                raise ValueError("Index checkpoint exceeds the fetched watermark")
            if through_message_id > job["snapshot_max_message_id"]:
                raise ValueError("Index checkpoint exceeds the scan snapshot")
            library_id = int(job["library_id"])
            library = connection.execute(
                "SELECT * FROM channel_libraries WHERE id = ?", (library_id,)
            ).fetchone()

            existing_rows = connection.execute(
                """
                SELECT * FROM channel_packages
                WHERE library_id = ? AND start_message_id BETWEEN ? AND ?
                ORDER BY start_message_id, id
                """,
                (library_id, reindex_anchor_start, through_message_id),
            ).fetchall()
            existing_by_start = {
                int(row["start_message_id"]): row for row in existing_rows
            }
            existing_items = {}
            for row in existing_rows:
                item_rows = connection.execute(
                    """
                    SELECT * FROM channel_package_items
                    WHERE library_id = ? AND package_id = ?
                    ORDER BY ordinal
                    """,
                    (library_id, row["id"]),
                ).fetchall()
                existing_items[int(row["id"])] = item_rows

            desired_by_start = {
                int(package["start_message_id"]): package
                for package in desired_packages
            }
            changed_desired = {}
            content_changed = {}
            for start, package in desired_by_start.items():
                items = list(package.get("items") or ())
                if not items:
                    raise ValueError("Cannot publish an empty package")
                item_ids = [int(item["message_id"]) for item in items]
                if len(item_ids) != len(set(item_ids)):
                    raise ValueError("Package item message IDs must be unique")
                existing = existing_by_start.get(start)
                if existing is None:
                    content_changed[start] = True
                    changed_desired[start] = True
                    continue
                old_content = package_content_signature(
                    existing, existing_items[int(existing["id"])]
                )
                new_content = package_content_signature(package, items)
                content_changed[start] = old_content != new_content
                changed_desired[start] = content_changed[start] or (
                    existing["boundary_status"] != package["boundary_status"]
                    or existing["superseded_by_package_id"] is not None
                )

            removed_rows = [
                row
                for row in existing_rows
                if row["boundary_status"] != "superseded"
                and int(row["start_message_id"]) not in desired_by_start
            ]
            changed_count = sum(changed_desired.values()) + len(removed_rows)
            old_revision = max(
                int(job["index_revision"]), int(library["index_revision"])
            )
            index_revision = old_revision + 1 if changed_count else old_revision
            invalidated_selection_count = 0
            desired_ids = {}

            for start in sorted(desired_by_start):
                if not changed_desired[start]:
                    desired_ids[start] = int(existing_by_start[start]["id"])
                    continue
                package = desired_by_start[start]
                changed_content = content_changed[start]
                connection.execute(
                    """
                    INSERT INTO channel_packages (
                        library_id, start_message_id, end_message_id, title,
                        published_at, boundary_status, media_count,
                        known_total_size, unknown_size_count, index_revision,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(library_id, start_message_id) DO UPDATE SET
                        end_message_id = excluded.end_message_id,
                        title = excluded.title,
                        published_at = excluded.published_at,
                        boundary_status = excluded.boundary_status,
                        media_count = excluded.media_count,
                        known_total_size = excluded.known_total_size,
                        unknown_size_count = excluded.unknown_size_count,
                        current_download_status = CASE
                            WHEN channel_packages.has_successful_attempt = 1
                                 AND ? = 1
                            THEN 'outdated'
                            ELSE channel_packages.current_download_status
                        END,
                        superseded_by_package_id = NULL,
                        index_revision = excluded.index_revision,
                        updated_at = excluded.updated_at
                    """,
                    (
                        library_id,
                        start,
                        int(package["end_message_id"]),
                        str(package["title"]),
                        package.get("published_at"),
                        str(package["boundary_status"]),
                        int(package["media_count"]),
                        int(package["known_total_size"]),
                        int(package["unknown_size_count"]),
                        index_revision,
                        now,
                        now,
                        int(changed_content),
                    ),
                )
                package_id = connection.execute(
                    """
                    SELECT id FROM channel_packages
                    WHERE library_id = ? AND start_message_id = ?
                    """,
                    (library_id, start),
                ).fetchone()[0]
                desired_ids[start] = int(package_id)
                connection.execute(
                    """
                    DELETE FROM channel_package_items
                    WHERE library_id = ? AND package_id = ?
                    """,
                    (library_id, package_id),
                )
                for item in package.get("items") or ():
                    connection.execute(
                        """
                        INSERT INTO channel_package_items (
                            library_id, package_id, message_id, ordinal,
                            media_type, caption_for_naming, original_caption,
                            inherited_caption
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            library_id,
                            package_id,
                            int(item["message_id"]),
                            int(item["ordinal"]),
                            str(item["media_type"]),
                            item.get("caption_for_naming"),
                            item.get("original_caption"),
                            int(
                                normalize_inherited(
                                    item.get("inherited_caption", False)
                                )
                            ),
                        ),
                    )
                selection = connection.execute(
                    """
                    UPDATE channel_package_selections
                    SET selected = 0,
                        invalidation_reason = 'package_revision_changed',
                        updated_at = ?
                    WHERE library_id = ? AND package_id = ? AND selected = 1
                    """,
                    (now, library_id, package_id),
                )
                invalidated_selection_count += selection.rowcount

            desired_ranges = [
                (
                    int(package["start_message_id"]),
                    int(package["end_message_id"]),
                    desired_ids[int(package["start_message_id"])],
                )
                for package in desired_packages
            ]
            for removed in removed_rows:
                removed_start = int(removed["start_message_id"])
                superseded_by = next(
                    (
                        package_id
                        for start, end, package_id in desired_ranges
                        if start <= removed_start <= end
                    ),
                    None,
                )
                if superseded_by is None and desired_ranges:
                    earlier = [
                        row for row in desired_ranges if row[0] <= removed_start
                    ]
                    superseded_by = (earlier[-1] if earlier else desired_ranges[0])[2]
                connection.execute(
                    """
                    UPDATE channel_packages
                    SET boundary_status = 'superseded',
                        superseded_by_package_id = ?, index_revision = ?,
                        updated_at = ?
                    WHERE id = ? AND library_id = ?
                    """,
                    (
                        superseded_by,
                        index_revision,
                        now,
                        removed["id"],
                        library_id,
                    ),
                )
                selection = connection.execute(
                    """
                    UPDATE channel_package_selections
                    SET selected = 0,
                        invalidation_reason = 'package_revision_changed',
                        updated_at = ?
                    WHERE library_id = ? AND package_id = ? AND selected = 1
                    """,
                    (now, library_id, removed["id"]),
                )
                invalidated_selection_count += selection.rowcount

            for failure_update in failure_updates:
                cursor = connection.execute(
                    """
                    UPDATE channel_scan_failures
                    SET uncertain_through_message_id = ?, updated_at = ?
                    WHERE id = ? AND library_id = ? AND status != 'resolved'
                    """,
                    (
                        int(failure_update["uncertain_through_message_id"]),
                        now,
                        int(failure_update["failure_id"]),
                        library_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Failure does not belong to the indexing library")

            stable_package_count = connection.execute(
                """
                SELECT COUNT(*) FROM channel_packages
                WHERE library_id = ? AND boundary_status = 'stable'
                """,
                (library_id,),
            ).fetchone()[0]
            indexed = max(
                int(job["indexed_through_message_id"]), int(through_message_id)
            )
            connection.execute(
                """
                UPDATE channel_scan_jobs
                SET indexed_through_message_id = ?, index_revision = ?,
                    stable_package_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    indexed,
                    index_revision,
                    stable_package_count,
                    now,
                    job_id,
                ),
            )
            connection.execute(
                """
                UPDATE channel_libraries
                SET indexed_through_message_id = MAX(
                        indexed_through_message_id, ?
                    ),
                    index_revision = ?, updated_at = ?
                WHERE id = ?
                """,
                (indexed, index_revision, now, library_id),
            )
            updated_job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        result = dict(updated_job)
        result.update(
            {
                "changed_package_count": changed_count,
                "superseded_package_count": len(removed_rows),
                "invalidated_selection_count": invalidated_selection_count,
            }
        )
        return result

    def commit_indexed_revision(
        self,
        job_id: int,
        through_message_id: int,
        index_revision: Optional[int] = None,
        stable_package_count: Optional[int] = None,
        now: Optional[float] = None,
    ) -> dict:
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            if job["status"] != "running":
                raise ValueError("Checkpoint writes require a running scan job")
            if through_message_id > job["fetched_through_message_id"]:
                raise ValueError("Index checkpoint exceeds the fetched watermark")
            if through_message_id > job["snapshot_max_message_id"]:
                raise ValueError("Index checkpoint exceeds the scan snapshot")
            revision = (
                job["index_revision"] + 1
                if index_revision is None
                else index_revision
            )
            if revision < job["index_revision"]:
                raise ValueError("Index revision cannot move backwards")
            indexed = max(job["indexed_through_message_id"], through_message_id)
            packages = (
                job["stable_package_count"]
                if stable_package_count is None
                else stable_package_count
            )
            connection.execute(
                """
                UPDATE channel_scan_jobs
                SET indexed_through_message_id = ?, index_revision = ?,
                    stable_package_count = ?, updated_at = ?
                WHERE id = ?
                """,
                (indexed, revision, packages, now, job_id),
            )
            connection.execute(
                """
                UPDATE channel_libraries
                SET indexed_through_message_id = MAX(
                        indexed_through_message_id, ?
                    ),
                    index_revision = MAX(index_revision, ?), updated_at = ?
                WHERE id = ?
                """,
                (indexed, revision, now, job["library_id"]),
            )
            updated = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(updated)

    def record_failed_range(
        self,
        job_id: int,
        start_message_id: int,
        end_message_id: int,
        last_error: str,
        *,
        reindex_anchor_start: int,
        uncertain_through_message_id: int,
        now: Optional[float] = None,
    ) -> dict:
        if start_message_id < 1 or end_message_id < start_message_id:
            raise ValueError("Invalid failed message range")
        now = time.time() if now is None else now
        with self.connect() as connection:
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            adjacent = connection.execute(
                """
                SELECT * FROM channel_scan_failures
                WHERE job_id = ? AND status = 'open'
                  AND start_message_id <= ? AND end_message_id >= ?
                ORDER BY id
                """,
                (job_id, end_message_id + 1, start_message_id - 1),
            ).fetchall()
            if adjacent:
                keeper = adjacent[0]
                merged_start = min(
                    start_message_id,
                    *(row["start_message_id"] for row in adjacent),
                )
                merged_end = max(
                    end_message_id,
                    *(row["end_message_id"] for row in adjacent),
                )
                merged_anchor = min(
                    reindex_anchor_start,
                    *(row["reindex_anchor_start"] for row in adjacent),
                )
                merged_uncertain = max(
                    uncertain_through_message_id,
                    *(row["uncertain_through_message_id"] for row in adjacent),
                )
                attempts = 1 + sum(row["attempt_count"] for row in adjacent)
                connection.execute(
                    """
                    UPDATE channel_scan_failures
                    SET start_message_id = ?, end_message_id = ?,
                        attempt_count = ?, last_error = ?,
                        reindex_anchor_start = ?,
                        uncertain_through_message_id = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        merged_start,
                        merged_end,
                        attempts,
                        last_error,
                        merged_anchor,
                        merged_uncertain,
                        now,
                        keeper["id"],
                    ),
                )
                for redundant in adjacent[1:]:
                    connection.execute(
                        "DELETE FROM channel_scan_failures WHERE id = ?",
                        (redundant["id"],),
                    )
                failure_id = keeper["id"]
            else:
                failure_id = connection.execute(
                    """
                    INSERT INTO channel_scan_failures (
                        job_id, library_id, start_message_id, end_message_id,
                        last_error, reindex_anchor_start,
                        uncertain_through_message_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        job["library_id"],
                        start_message_id,
                        end_message_id,
                        last_error,
                        reindex_anchor_start,
                        uncertain_through_message_id,
                        now,
                        now,
                    ),
                ).lastrowid
            failure = connection.execute(
                "SELECT * FROM channel_scan_failures WHERE id = ?", (failure_id,)
            ).fetchone()
        return dict(failure)

    def create_repair_job(
        self,
        library_id: int,
        failure_ids: Optional[Sequence[int]] = None,
        now: Optional[float] = None,
    ) -> dict:
        now = time.time() if now is None else now
        with self.connect() as connection:
            library = connection.execute(
                "SELECT * FROM channel_libraries WHERE id = ?", (library_id,)
            ).fetchone()
            if library is None:
                raise KeyError(f"Channel library {library_id} does not exist")
            if library["status"] != "partial":
                raise ValueError("Repair scans require a partial library")
            active = connection.execute(
                """
                SELECT id FROM channel_scan_jobs
                WHERE library_id = ? AND status IN (
                    'queued', 'running', 'paused_user',
                    'auto_paused_download', 'waiting_rate_limit', 'stopped'
                )
                LIMIT 1
                """,
                (library_id,),
            ).fetchone()
            if active is not None:
                raise ValueError(
                    f"Library {library_id} already has a recoverable scan job"
                )

            failures = []
            if failure_ids is None:
                failures = connection.execute(
                    """
                    SELECT * FROM channel_scan_failures
                    WHERE library_id = ? AND status = 'open'
                    ORDER BY start_message_id, id
                    """,
                    (library_id,),
                ).fetchall()
            else:
                for failure_id in dict.fromkeys(failure_ids):
                    failure = connection.execute(
                        """
                        SELECT * FROM channel_scan_failures
                        WHERE id = ? AND library_id = ? AND status = 'open'
                        """,
                        (failure_id, library_id),
                    ).fetchone()
                    if failure is None:
                        raise ValueError(
                            f"Failure {failure_id} is not open for this library"
                        )
                    failures.append(failure)
                failures.sort(key=lambda row: (row["start_message_id"], row["id"]))
            if not failures:
                raise ValueError("Repair scans require at least one open failure")

            start_message_id = min(row["start_message_id"] for row in failures)
            snapshot_max_message_id = max(
                row["uncertain_through_message_id"] for row in failures
            )
            job_id = self._insert_scan_job(
                connection,
                library,
                "repair",
                start_message_id,
                snapshot_max_message_id,
                now,
            )
            for failure in failures:
                connection.execute(
                    """
                    UPDATE channel_scan_failures
                    SET status = 'repairing', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, failure["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO channel_scan_repair_targets (
                        job_id, failure_id, library_id, next_message_id,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        job_id,
                        failure["id"],
                        library_id,
                        failure["start_message_id"],
                        now,
                        now,
                    ),
                )
            connection.execute(
                """
                UPDATE channel_libraries
                SET status = 'indexing', updated_at = ?
                WHERE id = ?
                """,
                (now, library_id),
            )
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(job)

    def list_repair_targets(self, job_id: int) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT t.*, f.start_message_id, f.end_message_id,
                       f.reindex_anchor_start,
                       f.uncertain_through_message_id,
                       f.status AS failure_status
                FROM channel_scan_repair_targets AS t
                JOIN channel_scan_failures AS f
                  ON f.id = t.failure_id AND f.library_id = t.library_id
                WHERE t.job_id = ?
                ORDER BY f.start_message_id, t.id
                """,
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_repair_target(
        self,
        job_id: int,
        failure_id: int,
        next_message_id: Optional[int] = None,
        now: Optional[float] = None,
    ) -> dict:
        now = time.time() if now is None else now
        with self.connect() as connection:
            target = connection.execute(
                """
                SELECT t.*, f.start_message_id, f.end_message_id
                FROM channel_scan_repair_targets AS t
                JOIN channel_scan_failures AS f
                  ON f.id = t.failure_id AND f.library_id = t.library_id
                WHERE t.job_id = ? AND t.failure_id = ?
                """,
                (job_id, failure_id),
            ).fetchone()
            if target is None:
                raise KeyError(
                    f"Repair target {job_id}/{failure_id} does not exist"
                )
            cursor = (
                target["end_message_id"] + 1
                if next_message_id is None
                else next_message_id
            )
            if cursor < target["next_message_id"]:
                raise ValueError("Repair target cursor cannot move backwards")
            completed = cursor > target["end_message_id"]
            status = "completed" if completed else "running"
            connection.execute(
                """
                UPDATE channel_scan_repair_targets
                SET next_message_id = ?, status = ?, updated_at = ?,
                    completed_at = ?
                WHERE job_id = ? AND failure_id = ?
                """,
                (
                    cursor,
                    status,
                    now,
                    now if completed else None,
                    job_id,
                    failure_id,
                ),
            )
            if completed:
                connection.execute(
                    """
                    UPDATE channel_scan_failures
                    SET status = 'resolved', updated_at = ?, resolved_at = ?
                    WHERE id = ?
                    """,
                    (now, now, failure_id),
                )
            updated = connection.execute(
                """
                SELECT * FROM channel_scan_repair_targets
                WHERE job_id = ? AND failure_id = ?
                """,
                (job_id, failure_id),
            ).fetchone()
        return dict(updated)

    def recover_interrupted_jobs(self, now: Optional[float] = None) -> int:
        now = time.time() if now is None else now
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE channel_scan_jobs
                SET status = 'queued',
                    wait_until = CASE
                        WHEN status = 'waiting_rate_limit' THEN NULL
                        ELSE wait_until END,
                    wait_reason = CASE
                        WHEN status = 'waiting_rate_limit' THEN NULL
                        ELSE wait_reason END,
                    updated_at = ?
                WHERE status IN ('running', 'auto_paused_download')
                   OR (status = 'waiting_rate_limit'
                       AND (wait_until IS NULL OR wait_until <= ?))
                """,
                (now, now),
            )
            recovered = cursor.rowcount
            connection.execute(
                """
                UPDATE channel_libraries
                SET status = 'indexing', updated_at = ?
                WHERE id IN (
                    SELECT library_id FROM channel_scan_jobs
                    WHERE status = 'queued'
                )
                """,
                (now,),
            )
        return recovered

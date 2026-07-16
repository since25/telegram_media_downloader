"""Persistent storage foundation for the Web channel library."""

import base64
import binascii
import datetime
import json
import os
import sqlite3
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union


SCHEMA_VERSION = 3

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
DOWNLOAD_ATTEMPT_TERMINAL_STATUSES = frozenset(
    {"completed", "failed", "upload_failed", "cancelled", "not_found"}
)
DOWNLOAD_ERROR_CODES = frozenset(
    {
        "telegram_refetch_failed",
        "download_failed",
        "callback_failed",
        "task_identity_conflict",
        "cancelled",
        "upload_failed",
        "not_found",
    }
)
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
SQLITE_MAX_INTEGER = 2**63 - 1

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
class PackageFilter:
    """Typed, allow-listed package query fields."""

    q: Optional[str] = None
    date_from: Optional[Union[str, datetime.date, datetime.datetime]] = None
    date_to: Optional[Union[str, datetime.date, datetime.datetime]] = None
    message_id_min: Optional[int] = None
    message_id_max: Optional[int] = None
    media_count_min: Optional[int] = None
    media_count_max: Optional[int] = None
    size_min: Optional[int] = None
    size_max: Optional[int] = None
    include_unknown_size: bool = False
    download_status: Optional[str] = None


@dataclass(frozen=True)
class QueryPage:
    """One keyset page and the revision of its read snapshot."""

    items: list[dict]
    next_cursor: Optional[str]
    library_revision: Optional[int] = None


def _normalize_title(value: object) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).casefold()


def _safe_download_error_code(
    value: Optional[str], status: Optional[str] = None
) -> Optional[str]:
    if value is None:
        return None
    code = str(value)
    if code in DOWNLOAD_ERROR_CODES:
        return code
    if status == "cancelled":
        return "cancelled"
    if status == "upload_failed":
        return "upload_failed"
    if status == "not_found":
        return "not_found"
    return "download_failed"


def _normalize_utc_boundary(
    value: Union[str, datetime.date, datetime.datetime], field_name: str
) -> str:
    if isinstance(value, datetime.datetime):
        parsed = value
    elif isinstance(value, datetime.date):
        parsed = datetime.datetime.combine(value, datetime.time.min)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field_name} must not be empty")
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError as error:
            raise ValueError(f"{field_name} must be an ISO datetime") from error
    else:
        raise ValueError(f"{field_name} must be an ISO datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return parsed.astimezone(datetime.timezone.utc).isoformat()


def _encode_cursor(payload: Mapping[str, int]) -> str:
    encoded = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, required_keys: frozenset[str]) -> dict[str, int]:
    if not isinstance(cursor, str) or not cursor or len(cursor) > 512:
        raise ValueError("Invalid cursor")
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.b64decode(
            f"{cursor}{padding}", altchars=b"-_", validate=True
        ).decode("utf-8")

        def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("Invalid cursor")
                result[key] = value
            return result

        payload = json.loads(decoded, object_pairs_hook=reject_duplicate_keys)
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("Invalid cursor") from error
    if not isinstance(payload, dict) or frozenset(payload) != required_keys:
        raise ValueError("Invalid cursor")
    if any(
        type(payload[key]) is not int
        or payload[key] < 0
        or payload[key] > SQLITE_MAX_INTEGER
        for key in required_keys
    ):
        raise ValueError("Invalid cursor")
    return payload


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
        connection.create_function(
            "unicode_nfkc_casefold", 1, _normalize_title, deterministic=True
        )
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
                    control_requested TEXT
                        CHECK (control_requested IN ('pause', 'stop')),
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
                    channel_title TEXT NOT NULL,
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
            scan_job_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(channel_scan_jobs)")
            }
            if "control_requested" not in scan_job_columns:
                connection.execute(
                    """
                    ALTER TABLE channel_scan_jobs
                    ADD COLUMN control_requested TEXT
                        CHECK (control_requested IN ('pause', 'stop'))
                    """
                )
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta (version, applied_at) VALUES (2, ?)",
                    (time.time(),),
                )
            download_batch_columns = {
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(channel_download_batches)"
                )
            }
            if "channel_title" not in download_batch_columns:
                connection.execute(
                    "ALTER TABLE channel_download_batches ADD COLUMN channel_title TEXT"
                )
                connection.execute(
                    """
                    UPDATE channel_download_batches
                    SET channel_title = (
                        SELECT title FROM channel_libraries
                        WHERE channel_libraries.id = channel_download_batches.library_id
                    )
                    WHERE channel_title IS NULL
                    """
                )
                connection.execute(
                    "INSERT OR IGNORE INTO schema_meta (version, applied_at) VALUES (3, ?)",
                    (time.time(),),
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

    def create_or_get_library_with_full_job(
        self,
        chat_id: int,
        chat_type: str,
        username: Optional[str],
        title: str,
        source_link: str,
        snapshot_max_message_id: int,
        now: Optional[float] = None,
    ) -> tuple[dict, dict, bool]:
        """Atomically create/deduplicate a library and its initial full job."""

        if snapshot_max_message_id < 0:
            raise ValueError("Invalid scan message range")
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
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
            library = connection.execute(
                "SELECT * FROM channel_libraries WHERE chat_id = ?", (chat_id,)
            ).fetchone()
            job = connection.execute(
                """
                SELECT * FROM channel_scan_jobs
                WHERE library_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (library["id"],),
            ).fetchone()
            if job is None:
                if not created and library["status"] != "new":
                    raise ValueError(
                        f"Library {library['id']} has no initial scan job"
                    )
                job_id = self._insert_scan_job(
                    connection,
                    library,
                    "full",
                    1,
                    snapshot_max_message_id,
                    now,
                )
                connection.execute(
                    """
                    UPDATE channel_libraries
                    SET status = 'indexing', updated_at = ?
                    WHERE id = ?
                    """,
                    (now, library["id"]),
                )
                library = connection.execute(
                    "SELECT * FROM channel_libraries WHERE id = ?",
                    (library["id"],),
                ).fetchone()
                job = connection.execute(
                    "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
                ).fetchone()
        return dict(library), dict(job), created

    def get_library(self, library_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM channel_libraries WHERE id = ?", (library_id,)
            ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _page_size(limit: int) -> int:
        if type(limit) is not int or limit < 1:
            raise ValueError("Page size must be a positive integer")
        return min(limit, MAX_PAGE_SIZE)

    @staticmethod
    def _package_predicate(
        library_id: int, package_filter: PackageFilter
    ) -> tuple[str, list[object]]:
        if not isinstance(package_filter, PackageFilter):
            raise TypeError("package_filter must be a PackageFilter")
        if package_filter.q is not None and not isinstance(package_filter.q, str):
            raise ValueError("q must be a string")
        if type(package_filter.include_unknown_size) is not bool:
            raise ValueError("include_unknown_size must be a boolean")

        numeric_fields = (
            "message_id_min",
            "message_id_max",
            "media_count_min",
            "media_count_max",
            "size_min",
            "size_max",
        )
        numeric_values = {}
        for field_name in numeric_fields:
            value = getattr(package_filter, field_name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{field_name} must be a non-negative integer")
            numeric_values[field_name] = value
        for lower_name, upper_name in (
            ("message_id_min", "message_id_max"),
            ("media_count_min", "media_count_max"),
            ("size_min", "size_max"),
        ):
            lower = numeric_values[lower_name]
            upper = numeric_values[upper_name]
            if lower is not None and upper is not None and lower > upper:
                raise ValueError(f"{lower_name} must not exceed {upper_name}")

        if (
            package_filter.download_status is not None
            and package_filter.download_status not in PACKAGE_DOWNLOAD_STATUSES
        ):
            raise ValueError("Unsupported package download status")
        date_from = (
            _normalize_utc_boundary(package_filter.date_from, "date_from")
            if package_filter.date_from is not None
            else None
        )
        date_to = (
            _normalize_utc_boundary(package_filter.date_to, "date_to")
            if package_filter.date_to is not None
            else None
        )
        if date_from is not None and date_to is not None and date_from >= date_to:
            raise ValueError("date_from must be before date_to")

        predicates = [
            "p.library_id = ?",
            "p.boundary_status != 'superseded'",
        ]
        parameters: list[object] = [library_id]
        if package_filter.q is not None:
            normalized_query = _normalize_title(package_filter.q)
            if normalized_query:
                predicates.append(
                    "instr(unicode_nfkc_casefold(p.title), ?) > 0"
                )
                parameters.append(normalized_query)
        if date_from is not None:
            predicates.append("p.published_at >= ?")
            parameters.append(date_from)
        if date_to is not None:
            predicates.append("p.published_at < ?")
            parameters.append(date_to)
        if package_filter.message_id_min is not None:
            predicates.append("p.end_message_id >= ?")
            parameters.append(package_filter.message_id_min)
        if package_filter.message_id_max is not None:
            predicates.append("p.start_message_id <= ?")
            parameters.append(package_filter.message_id_max)
        if package_filter.media_count_min is not None:
            predicates.append("p.media_count >= ?")
            parameters.append(package_filter.media_count_min)
        if package_filter.media_count_max is not None:
            predicates.append("p.media_count <= ?")
            parameters.append(package_filter.media_count_max)
        size_filter_active = (
            package_filter.size_min is not None or package_filter.size_max is not None
        )
        if package_filter.size_min is not None:
            predicates.append("p.known_total_size >= ?")
            parameters.append(package_filter.size_min)
        if package_filter.size_max is not None:
            predicates.append("p.known_total_size <= ?")
            parameters.append(package_filter.size_max)
        if size_filter_active and not package_filter.include_unknown_size:
            predicates.append("p.unknown_size_count = 0")
        if package_filter.download_status is not None:
            predicates.append("p.current_download_status = ?")
            parameters.append(package_filter.download_status)
        return " AND ".join(predicates), parameters

    def list_libraries(
        self,
        cursor: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> QueryPage:
        """List libraries in stable descending-ID order without offsets."""

        page_size = self._page_size(limit)
        parameters: list[object] = []
        cursor_sql = ""
        if cursor is not None:
            decoded = _decode_cursor(cursor, frozenset({"id"}))
            cursor_sql = "WHERE id < ?"
            parameters.append(decoded["id"])
        parameters.append(page_size + 1)
        with self.connect() as connection:
            connection.execute("BEGIN")
            rows = connection.execute(
                f"""
                SELECT * FROM channel_libraries
                {cursor_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        has_more = len(rows) > page_size
        page_rows = rows[:page_size]
        next_cursor = (
            _encode_cursor({"id": int(page_rows[-1]["id"])})
            if has_more
            else None
        )
        return QueryPage([dict(row) for row in page_rows], next_cursor)

    def list_packages(
        self,
        library_id: int,
        package_filter: PackageFilter,
        cursor: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> QueryPage:
        """List filtered packages using a descending composite keyset."""

        page_size = self._page_size(limit)
        predicate, parameters = self._package_predicate(library_id, package_filter)
        if cursor is not None:
            decoded = _decode_cursor(
                cursor, frozenset({"start_message_id", "id"})
            )
            predicate = (
                f"{predicate} AND "
                "(p.start_message_id < ? OR "
                "(p.start_message_id = ? AND p.id < ?))"
            )
            parameters.extend(
                [
                    decoded["start_message_id"],
                    decoded["start_message_id"],
                    decoded["id"],
                ]
            )
        parameters.append(page_size + 1)
        with self.connect() as connection:
            connection.execute("BEGIN")
            library = connection.execute(
                "SELECT index_revision FROM channel_libraries WHERE id = ?",
                (library_id,),
            ).fetchone()
            if library is None:
                raise KeyError(f"Channel library {library_id} does not exist")
            rows = connection.execute(
                f"""
                SELECT p.*,
                       s.package_revision AS selection_revision,
                       s.selected AS stored_selected,
                       s.invalidation_reason AS stored_invalidation_reason
                FROM channel_packages AS p
                LEFT JOIN channel_package_selections AS s
                  ON s.library_id = p.library_id AND s.package_id = p.id
                WHERE {predicate}
                ORDER BY p.start_message_id DESC, p.id DESC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        has_more = len(rows) > page_size
        page_rows = rows[:page_size]
        items = []
        for row in page_rows:
            item = dict(row)
            selected = (
                item["stored_selected"] == 1
                and item["selection_revision"] == item["index_revision"]
                and item["boundary_status"] == "stable"
            )
            invalidation_reason = item.pop("stored_invalidation_reason")
            if invalidation_reason is None and item["stored_selected"] == 1:
                if item["selection_revision"] != item["index_revision"]:
                    invalidation_reason = "package_revision_changed"
                elif item["boundary_status"] != "stable":
                    invalidation_reason = "package_not_stable"
            item.pop("stored_selected")
            item["selected"] = selected
            item["selection_invalidation_reason"] = invalidation_reason
            item["selectable"] = item["boundary_status"] == "stable"
            item["unselectable_reason"] = (
                None if item["selectable"] else "package_not_stable"
            )
            item["size_is_exact"] = item["unknown_size_count"] == 0
            items.append(item)
        next_cursor = (
            _encode_cursor(
                {
                    "start_message_id": int(page_rows[-1]["start_message_id"]),
                    "id": int(page_rows[-1]["id"]),
                }
            )
            if has_more
            else None
        )
        return QueryPage(items, next_cursor, int(library["index_revision"]))

    def list_package_items(
        self,
        library_id: int,
        package_id: int,
        cursor: Optional[str] = None,
        limit: int = DEFAULT_PAGE_SIZE,
    ) -> QueryPage:
        """List one package's media details using an ascending item keyset."""

        page_size = self._page_size(limit)
        cursor_sql = ""
        parameters: list[object] = [library_id, package_id]
        if cursor is not None:
            decoded = _decode_cursor(
                cursor, frozenset({"ordinal", "message_id"})
            )
            cursor_sql = (
                "AND (i.ordinal > ? OR "
                "(i.ordinal = ? AND i.message_id > ?))"
            )
            parameters.extend(
                [decoded["ordinal"], decoded["ordinal"], decoded["message_id"]]
            )
        parameters.append(page_size + 1)
        with self.connect() as connection:
            connection.execute("BEGIN")
            library = connection.execute(
                "SELECT index_revision FROM channel_libraries WHERE id = ?",
                (library_id,),
            ).fetchone()
            if library is None:
                raise KeyError(f"Channel library {library_id} does not exist")
            package = connection.execute(
                """
                SELECT id FROM channel_packages
                WHERE library_id = ? AND id = ?
                """,
                (library_id, package_id),
            ).fetchone()
            if package is None:
                raise KeyError(f"Channel package {package_id} does not exist")
            rows = connection.execute(
                f"""
                SELECT i.*, m.message_date, m.media_group_id, m.caption,
                       m.file_name, m.file_size, m.mime_type, m.duration,
                       m.width, m.height
                FROM channel_package_items AS i
                JOIN channel_media_messages AS m
                  ON m.library_id = i.library_id AND m.message_id = i.message_id
                WHERE i.library_id = ? AND i.package_id = ?
                  {cursor_sql}
                ORDER BY i.ordinal, i.message_id
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        has_more = len(rows) > page_size
        page_rows = rows[:page_size]
        next_cursor = (
            _encode_cursor(
                {
                    "ordinal": int(page_rows[-1]["ordinal"]),
                    "message_id": int(page_rows[-1]["message_id"]),
                }
            )
            if has_more
            else None
        )
        return QueryPage(
            [dict(row) for row in page_rows],
            next_cursor,
            int(library["index_revision"]),
        )

    def set_package_selected(
        self,
        library_id: int,
        package_id: int,
        selected: bool,
        now: Optional[float] = None,
    ) -> dict:
        """Persist one package selection bound to its current revision."""

        if type(selected) is not bool:
            raise ValueError("selected must be a boolean")
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            package = connection.execute(
                """
                SELECT * FROM channel_packages
                WHERE library_id = ? AND id = ?
                """,
                (library_id, package_id),
            ).fetchone()
            if package is None:
                library = connection.execute(
                    "SELECT id FROM channel_libraries WHERE id = ?", (library_id,)
                ).fetchone()
                if library is None:
                    raise KeyError(f"Channel library {library_id} does not exist")
                raise KeyError(f"Channel package {package_id} does not exist")
            if selected and package["boundary_status"] != "stable":
                raise ValueError("Package is not stable and cannot be selected")
            if selected:
                connection.execute(
                    """
                    INSERT INTO channel_package_selections (
                        library_id, package_id, package_revision, selected,
                        invalidation_reason, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, NULL, ?, ?)
                    ON CONFLICT(library_id, package_id) DO UPDATE SET
                        package_revision = excluded.package_revision,
                        selected = 1, invalidation_reason = NULL,
                        updated_at = excluded.updated_at
                    """,
                    (
                        library_id,
                        package_id,
                        package["index_revision"],
                        now,
                        now,
                    ),
                )
            else:
                connection.execute(
                    """
                    DELETE FROM channel_package_selections
                    WHERE library_id = ? AND package_id = ?
                    """,
                    (library_id, package_id),
                )
        return {
            "library_id": library_id,
            "package_id": package_id,
            "package_revision": int(package["index_revision"]),
            "selected": selected,
            "invalidation_reason": None,
        }

    def select_filtered(
        self,
        library_id: int,
        package_filter: PackageFilter,
        now: Optional[float] = None,
    ) -> dict[str, int]:
        """Select every matching stable package with one INSERT-SELECT."""

        predicate, parameters = self._package_predicate(library_id, package_filter)
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            library = connection.execute(
                "SELECT id FROM channel_libraries WHERE id = ?", (library_id,)
            ).fetchone()
            if library is None:
                raise KeyError(f"Channel library {library_id} does not exist")
            counts = connection.execute(
                f"""
                SELECT COUNT(*) AS matching_count,
                       COALESCE(SUM(
                           CASE WHEN p.boundary_status = 'stable' THEN 1 ELSE 0 END
                       ), 0) AS stable_count
                FROM channel_packages AS p
                WHERE {predicate}
                """,
                parameters,
            ).fetchone()
            connection.execute(
                f"""
                INSERT INTO channel_package_selections (
                    library_id, package_id, package_revision, selected,
                    invalidation_reason, created_at, updated_at
                )
                SELECT p.library_id, p.id, p.index_revision, 1, NULL, ?, ?
                FROM channel_packages AS p
                WHERE {predicate} AND p.boundary_status = 'stable'
                ON CONFLICT(library_id, package_id) DO UPDATE SET
                    package_revision = excluded.package_revision,
                    selected = 1, invalidation_reason = NULL,
                    updated_at = excluded.updated_at
                """,
                [now, now, *parameters],
            )
        selected_count = int(counts["stable_count"])
        return {
            "selected_count": selected_count,
            "skipped_count": int(counts["matching_count"]) - selected_count,
        }

    def clear_selection(self, library_id: int) -> int:
        """Remove all valid and invalidated selection records for a library."""

        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            library = connection.execute(
                "SELECT id FROM channel_libraries WHERE id = ?", (library_id,)
            ).fetchone()
            if library is None:
                raise KeyError(f"Channel library {library_id} does not exist")
            cursor = connection.execute(
                "DELETE FROM channel_package_selections WHERE library_id = ?",
                (library_id,),
            )
        return cursor.rowcount

    def selection_summary(self, library_id: int) -> dict:
        """Summarize valid selections separately from invalidated records."""

        with self.connect() as connection:
            connection.execute("BEGIN")
            library = connection.execute(
                "SELECT id FROM channel_libraries WHERE id = ?", (library_id,)
            ).fetchone()
            if library is None:
                raise KeyError(f"Channel library {library_id} does not exist")
            totals = connection.execute(
                """
                SELECT
                    COALESCE(SUM(CASE
                        WHEN s.selected = 1
                         AND s.package_revision = p.index_revision
                         AND p.boundary_status = 'stable'
                        THEN 1 ELSE 0 END), 0) AS selected_count,
                    COALESCE(SUM(CASE
                        WHEN s.selected = 1
                         AND s.package_revision = p.index_revision
                         AND p.boundary_status = 'stable'
                        THEN p.media_count ELSE 0 END), 0) AS media_count,
                    COALESCE(SUM(CASE
                        WHEN s.selected = 1
                         AND s.package_revision = p.index_revision
                         AND p.boundary_status = 'stable'
                        THEN p.known_total_size ELSE 0 END), 0) AS known_total_size,
                    COALESCE(SUM(CASE
                        WHEN s.selected = 1
                         AND s.package_revision = p.index_revision
                         AND p.boundary_status = 'stable'
                        THEN p.unknown_size_count ELSE 0 END), 0)
                        AS unknown_size_count
                FROM channel_package_selections AS s
                JOIN channel_packages AS p
                  ON p.library_id = s.library_id AND p.id = s.package_id
                WHERE s.library_id = ?
                """,
                (library_id,),
            ).fetchone()
            invalidation_rows = connection.execute(
                """
                SELECT s.package_id,
                       CASE
                         WHEN s.invalidation_reason IS NOT NULL
                         THEN s.invalidation_reason
                         WHEN s.package_revision != p.index_revision
                         THEN 'package_revision_changed'
                         WHEN p.boundary_status != 'stable'
                         THEN 'package_not_stable'
                       END AS reason
                FROM channel_package_selections AS s
                JOIN channel_packages AS p
                  ON p.library_id = s.library_id AND p.id = s.package_id
                WHERE s.library_id = ?
                  AND (
                    s.invalidation_reason IS NOT NULL
                    OR (s.selected = 1 AND (
                        s.package_revision != p.index_revision
                        OR p.boundary_status != 'stable'
                    ))
                  )
                ORDER BY s.package_id
                """,
                (library_id,),
            ).fetchall()
        unknown_size_count = int(totals["unknown_size_count"])
        invalidations = [
            {"package_id": int(row["package_id"]), "reason": row["reason"]}
            for row in invalidation_rows
        ]
        return {
            "selected_count": int(totals["selected_count"]),
            "media_count": int(totals["media_count"]),
            "known_total_size": int(totals["known_total_size"]),
            "unknown_size_count": unknown_size_count,
            "size_is_exact": unknown_size_count == 0,
            "invalidated_count": len(invalidations),
            "invalidations": invalidations,
        }

    def create_download_batch(
        self,
        library_id: int,
        idempotency_key: str,
        task_id: str,
        allow_redownload: bool = False,
        now: Optional[float] = None,
    ) -> dict:
        """Atomically validate selections and persist one immutable outbox batch."""

        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("Idempotency key is required")
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT id FROM channel_download_batches
                WHERE library_id = ? AND idempotency_key = ?
                """,
                (library_id, key),
            ).fetchone()
            if existing is not None:
                batch_id = int(existing["id"])
            else:
                library = connection.execute(
                    "SELECT * FROM channel_libraries WHERE id = ?", (library_id,)
                ).fetchone()
                if library is None:
                    raise KeyError(f"Channel library {library_id} does not exist")
                if library["status"] not in {"ready", "partial"}:
                    raise ValueError("Channel library is not ready for download")

                selected = connection.execute(
                    """
                    SELECT p.*, s.package_revision AS selected_revision
                    FROM channel_package_selections AS s
                    JOIN channel_packages AS p
                      ON p.library_id = s.library_id AND p.id = s.package_id
                    WHERE s.library_id = ? AND s.selected = 1
                    ORDER BY p.start_message_id, p.id
                    """,
                    (library_id,),
                ).fetchall()
                if not selected:
                    raise ValueError("No channel packages are selected")
                for package in selected:
                    if int(package["selected_revision"]) != int(
                        package["index_revision"]
                    ):
                        raise ValueError("Selected package revision changed")
                    if package["boundary_status"] != "stable":
                        raise ValueError("Selected package is not stable")
                    active_attempt = connection.execute(
                        """
                        SELECT 1
                        FROM channel_download_batch_packages AS attempt
                        JOIN channel_download_batches AS batch
                          ON batch.id = attempt.batch_id
                         AND batch.library_id = attempt.library_id
                        WHERE attempt.library_id = ?
                          AND attempt.package_id = ?
                          AND attempt.status IN ('queued', 'downloading')
                          AND batch.status IN ('queued', 'downloading')
                        LIMIT 1
                        """,
                        (library_id, int(package["id"])),
                    ).fetchone()
                    if active_attempt is not None:
                        raise ValueError("Selected package is in an active download batch")
                    if package["current_download_status"] in {
                        "queued",
                        "downloading",
                    }:
                        raise ValueError("Selected package is in an active download batch")
                    if (
                        package["has_successful_attempt"] == 1
                        or package["current_download_status"] == "outdated"
                    ) and not allow_redownload:
                        raise ValueError("Explicit redownload confirmation is required")

                cursor = connection.execute(
                    """
                    INSERT INTO channel_download_batches (
                        library_id, task_id, idempotency_key, channel_title,
                        allow_redownload, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        library_id,
                        task_id,
                        key,
                        library["title"],
                        1 if allow_redownload else 0,
                        now,
                        now,
                    ),
                )
                batch_id = int(cursor.lastrowid)
                for package_ordinal, package in enumerate(selected, start=1):
                    package_id = int(package["id"])
                    connection.execute(
                        """
                        INSERT INTO channel_download_batch_packages (
                            batch_id, library_id, package_id, package_revision,
                            title, start_message_id, end_message_id, ordinal,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            batch_id,
                            library_id,
                            package_id,
                            int(package["index_revision"]),
                            package["title"],
                            int(package["start_message_id"]),
                            int(package["end_message_id"]),
                            package_ordinal,
                            now,
                            now,
                        ),
                    )
                    item_rows = connection.execute(
                        """
                        SELECT * FROM channel_package_items
                        WHERE library_id = ? AND package_id = ?
                        ORDER BY ordinal, message_id
                        """,
                        (library_id, package_id),
                    ).fetchall()
                    if not item_rows:
                        raise ValueError("Selected package has no media items")
                    for item in item_rows:
                        connection.execute(
                            """
                            INSERT INTO channel_download_batch_items (
                                batch_id, package_id, library_id, message_id,
                                ordinal, media_type, caption_for_naming,
                                original_caption, inherited_caption
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                batch_id,
                                package_id,
                                library_id,
                                int(item["message_id"]),
                                int(item["ordinal"]),
                                item["media_type"],
                                item["caption_for_naming"],
                                item["original_caption"],
                                item["inherited_caption"],
                            ),
                        )
                    connection.execute(
                        """
                        UPDATE channel_packages
                        SET current_download_status = 'queued',
                            last_download_task_id = ?,
                            download_attempt_count = download_attempt_count + 1,
                            updated_at = ?
                        WHERE library_id = ? AND id = ?
                        """,
                        (task_id, now, library_id, package_id),
                    )
        return self.get_download_batch(batch_id)

    def get_download_batch(self, batch_id: int) -> Optional[dict]:
        with self.connect() as connection:
            batch = connection.execute(
                "SELECT * FROM channel_download_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                return None
            package_rows = connection.execute(
                """
                SELECT * FROM channel_download_batch_packages
                WHERE batch_id = ? ORDER BY ordinal, package_id
                """,
                (batch_id,),
            ).fetchall()
            packages = []
            for package_row in package_rows:
                package = dict(package_row)
                item_rows = connection.execute(
                    """
                    SELECT * FROM channel_download_batch_items
                    WHERE batch_id = ? AND package_id = ?
                    ORDER BY ordinal, message_id
                    """,
                    (batch_id, package_row["package_id"]),
                ).fetchall()
                package["items"] = [dict(item) for item in item_rows]
                packages.append(package)
        result = dict(batch)
        result["packages"] = packages
        return result

    def list_download_batches(self, library_id: Optional[int] = None) -> list[dict]:
        predicate = "" if library_id is None else "WHERE library_id = ?"
        parameters = () if library_id is None else (library_id,)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id FROM channel_download_batches
                {predicate}
                ORDER BY created_at, id
                """,
                parameters,
            ).fetchall()
        return [self.get_download_batch(int(row["id"])) for row in rows]

    def list_pending_download_batches(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT id FROM channel_download_batches
                WHERE dispatch_status = 'pending_dispatch'
                ORDER BY created_at, id
                """
            ).fetchall()
        return [self.get_download_batch(int(row["id"])) for row in rows]

    def mark_download_batch_dispatched(
        self, batch_id: int, now: Optional[float] = None
    ) -> dict:
        now = time.time() if now is None else now
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE channel_download_batches
                SET dispatch_status = 'dispatched', dispatched_at = COALESCE(dispatched_at, ?),
                    updated_at = ?, last_error = NULL
                WHERE id = ?
                """,
                (now, now, batch_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Download batch {batch_id} does not exist")
        return self.get_download_batch(batch_id)

    def mark_download_batch_dispatch_error(
        self, batch_id: int, error_code: str, now: Optional[float] = None
    ) -> dict:
        now = time.time() if now is None else now
        safe_code = _safe_download_error_code(error_code)
        with self.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE channel_download_batches
                SET last_error = ?, updated_at = ?
                WHERE id = ? AND dispatch_status = 'pending_dispatch'
                """,
                (safe_code, now, batch_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Pending download batch {batch_id} does not exist")
        return self.get_download_batch(batch_id)

    def mark_download_batch_package_started(
        self, batch_id: int, package_id: int, now: Optional[float] = None
    ) -> dict:
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            batch = connection.execute(
                "SELECT task_id, library_id FROM channel_download_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise KeyError(f"Download batch {batch_id} does not exist")
            cursor = connection.execute(
                """
                UPDATE channel_download_batch_packages
                SET status = 'downloading', updated_at = ?
                WHERE batch_id = ? AND package_id = ? AND status = 'queued'
                """,
                (now, batch_id, package_id),
            )
            if cursor.rowcount == 0:
                attempt = connection.execute(
                    """
                    SELECT status FROM channel_download_batch_packages
                    WHERE batch_id = ? AND package_id = ?
                    """,
                    (batch_id, package_id),
                ).fetchone()
                if attempt is None:
                    raise KeyError(
                        f"Package {package_id} is not in download batch {batch_id}"
                    )
                raise ValueError(
                    f"Package download attempt is not queued: {attempt['status']}"
                )
            if cursor.rowcount != 1:
                raise RuntimeError("Unexpected package attempt update count")
            connection.execute(
                """
                UPDATE channel_packages
                SET current_download_status = 'downloading', updated_at = ?
                WHERE library_id = ? AND id = ? AND last_download_task_id = ?
                """,
                (now, batch["library_id"], package_id, batch["task_id"]),
            )
            connection.execute(
                """
                UPDATE channel_download_batches
                SET status = 'downloading', updated_at = ? WHERE id = ?
                """,
                (now, batch_id),
            )
        return self.get_download_batch(batch_id)

    def prepare_download_batch_for_run(
        self, batch_id: int, now: Optional[float] = None
    ) -> dict:
        """Normalize stale single-process work before a fresh runner claims it."""

        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            batch = connection.execute(
                "SELECT * FROM channel_download_batches WHERE id = ?", (batch_id,)
            ).fetchone()
            if batch is None:
                raise KeyError(f"Download batch {batch_id} does not exist")
            if batch["status"] not in {"queued", "downloading"}:
                raise ValueError(
                    f"Download batch is not resumable: {batch['status']}"
                )
            connection.execute(
                """
                UPDATE channel_packages
                SET current_download_status = 'queued', updated_at = ?
                WHERE library_id = ? AND last_download_task_id = ?
                  AND id IN (
                      SELECT package_id FROM channel_download_batch_packages
                      WHERE batch_id = ? AND status = 'downloading'
                  )
                """,
                (now, batch["library_id"], batch["task_id"], batch_id),
            )
            connection.execute(
                """
                UPDATE channel_download_batch_packages
                SET status = 'queued', updated_at = ?
                WHERE batch_id = ? AND status = 'downloading'
                """,
                (now, batch_id),
            )
            connection.execute(
                """
                UPDATE channel_download_batches
                SET status = 'queued', updated_at = ?
                WHERE id = ? AND status = 'downloading'
                """,
                (now, batch_id),
            )
        return self.get_download_batch(batch_id)

    def finish_download_batch_package(
        self,
        batch_id: int,
        package_id: int,
        status: str,
        last_error: Optional[str] = None,
        now: Optional[float] = None,
    ) -> dict:
        if status not in DOWNLOAD_ATTEMPT_TERMINAL_STATUSES:
            raise ValueError(f"Invalid package download status: {status}")
        last_error = _safe_download_error_code(last_error, status)
        now = time.time() if now is None else now
        summary_status = (
            "completed"
            if status == "completed"
            else "cancelled" if status == "cancelled" else "failed"
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            batch = connection.execute(
                "SELECT task_id, library_id FROM channel_download_batches WHERE id = ?",
                (batch_id,),
            ).fetchone()
            if batch is None:
                raise KeyError(f"Download batch {batch_id} does not exist")
            cursor = connection.execute(
                """
                UPDATE channel_download_batch_packages
                SET status = ?, last_error = ?, updated_at = ?, completed_at = ?
                WHERE batch_id = ? AND package_id = ?
                """,
                (status, last_error, now, now, batch_id, package_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(
                    f"Package {package_id} is not in download batch {batch_id}"
                )
            connection.execute(
                """
                UPDATE channel_packages
                SET current_download_status = ?,
                    has_successful_attempt = CASE
                        WHEN ? = 'completed' THEN 1 ELSE has_successful_attempt END,
                    completed_revision = CASE
                        WHEN ? = 'completed' THEN (
                            SELECT package_revision
                            FROM channel_download_batch_packages
                            WHERE batch_id = ? AND package_id = ?
                        ) ELSE completed_revision END,
                    last_successful_at = CASE
                        WHEN ? = 'completed' THEN ? ELSE last_successful_at END,
                    last_downloaded_at = ?, updated_at = ?
                WHERE library_id = ? AND id = ? AND last_download_task_id = ?
                """,
                (
                    summary_status,
                    status,
                    status,
                    batch_id,
                    package_id,
                    status,
                    now,
                    now,
                    now,
                    batch["library_id"],
                    package_id,
                    batch["task_id"],
                ),
            )
            unfinished = connection.execute(
                """
                SELECT COUNT(*) FROM channel_download_batch_packages
                WHERE batch_id = ? AND status IN ('queued', 'downloading')
                """,
                (batch_id,),
            ).fetchone()[0]
            if unfinished == 0:
                statuses = {
                    row[0]
                    for row in connection.execute(
                        "SELECT status FROM channel_download_batch_packages WHERE batch_id = ?",
                        (batch_id,),
                    )
                }
                batch_status = (
                    "completed"
                    if statuses == {"completed"}
                    else "cancelled"
                    if statuses <= {"completed", "cancelled"}
                    else "failed"
                )
                connection.execute(
                    """
                    UPDATE channel_download_batches
                    SET status = ?, updated_at = ?, completed_at = ? WHERE id = ?
                    """,
                    (batch_status, now, now, batch_id),
                )
        return self.get_download_batch(batch_id)

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

    def request_job_control(
        self,
        job_id: int,
        action: str,
        now: Optional[float] = None,
    ) -> dict:
        """Persist pause/stop intent without interrupting a running batch."""

        if action not in {"pause", "stop"}:
            raise ValueError(f"Unsupported scan control action: {action}")
        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            if job["status"] != "running":
                raise ValueError("Boundary control requests require a running scan job")
            requested = (
                "stop" if action == "stop" or job["control_requested"] == "stop"
                else "pause"
            )
            connection.execute(
                """
                UPDATE channel_scan_jobs
                SET control_requested = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (requested, now, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(updated)

    def consume_job_control(
        self, job_id: int, now: Optional[float] = None
    ) -> Optional[dict]:
        """Atomically apply a pending control request at a batch boundary."""

        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            action = job["control_requested"]
            if action is None:
                return None
            if job["status"] != "running":
                raise ValueError("Boundary control can only be consumed while running")
            new_status = "paused_user" if action == "pause" else "stopped"
            connection.execute(
                """
                UPDATE channel_scan_jobs
                SET status = ?, control_requested = NULL, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (new_status, now, job_id),
            )
            connection.execute(
                """
                UPDATE channel_libraries
                SET status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    "paused" if new_status == "paused_user" else "stopped",
                    now,
                    job["library_id"],
                ),
            )
            updated = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(updated)

    def next_rate_limit_deadline(self) -> Optional[float]:
        """Return the earliest persisted rate-limit deadline."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT MIN(wait_until) FROM channel_scan_jobs
                WHERE status = 'waiting_rate_limit' AND wait_until IS NOT NULL
                """
            ).fetchone()
        return float(row[0]) if row[0] is not None else None

    def has_open_failures(self, library_id: int) -> bool:
        """Return whether a library still has an unresolved scan range."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT 1 FROM channel_scan_failures
                WHERE library_id = ? AND status != 'resolved'
                LIMIT 1
                """,
                (library_id,),
            ).fetchone()
        return row is not None

    def has_finished_full_scan(self, library_id: int) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT id FROM channel_scan_jobs
                WHERE library_id = ? AND kind = 'full'
                  AND status IN ('completed', 'partial')
                LIMIT 1
                """,
                (library_id,),
            ).fetchone()
        return row is not None

    def reindex_anchor_for_message(self, library_id: int, message_id: int) -> int:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT start_message_id FROM channel_packages
                WHERE library_id = ? AND boundary_status != 'superseded'
                  AND start_message_id <= ?
                ORDER BY start_message_id DESC, id DESC
                LIMIT 1
                """,
                (library_id, message_id),
            ).fetchone()
        return int(row["start_message_id"]) if row is not None else 1

    def record_job_retry(
        self,
        job_id: int,
        last_error: str,
        now: Optional[float] = None,
    ) -> dict:
        """Persist one ordinary retry without advancing scan checkpoints."""

        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if job is None:
                raise KeyError(f"Scan job {job_id} does not exist")
            if job["status"] != "running":
                raise ValueError("Retry updates require a running scan job")
            connection.execute(
                """
                UPDATE channel_scan_jobs
                SET retry_count = retry_count + 1,
                    last_error = ?, updated_at = ?
                WHERE id = ? AND status = 'running'
                """,
                (last_error, now, job_id),
            )
            updated = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(updated)

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
                    last_error = ?,
                    control_requested = CASE
                        WHEN ? = 'running' THEN control_requested ELSE NULL END
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
                    new_status,
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
        repair_failure_id: Optional[int] = None,
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
            repair_target = None
            if repair_failure_id is not None:
                if job["kind"] != "repair":
                    raise ValueError("Only repair jobs have repair target cursors")
                repair_target = connection.execute(
                    """
                    SELECT t.*, f.end_message_id
                    FROM channel_scan_repair_targets AS t
                    JOIN channel_scan_failures AS f
                      ON f.id = t.failure_id AND f.library_id = t.library_id
                    WHERE t.job_id = ? AND t.failure_id = ?
                    """,
                    (job_id, repair_failure_id),
                ).fetchone()
                if repair_target is None:
                    raise KeyError(
                        f"Repair target {job_id}/{repair_failure_id} does not exist"
                    )
                if end_id < repair_target["next_message_id"]:
                    raise ValueError("Repair target cursor cannot move backwards")
                if end_id > repair_target["end_message_id"]:
                    raise ValueError("Repair fetch checkpoint exceeds its target")
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
                    media_count = ?, retry_count = 0, updated_at = ?
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
            if repair_target is not None:
                connection.execute(
                    """
                    UPDATE channel_scan_repair_targets
                    SET next_message_id = ?, status = 'running',
                        updated_at = ?, completed_at = NULL
                    WHERE job_id = ? AND failure_id = ?
                    """,
                    (end_id + 1, now, job_id, repair_failure_id),
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
        resolved_failure_ids: Sequence[int] = (),
        repair_failure_id: Optional[int] = None,
        now: Optional[float] = None,
    ) -> dict:
        """Atomically publish derived packages, items, revision, and watermark."""

        now = time.time() if now is None else now
        desired_packages = [dict(package) for package in packages]
        resolved_ids = list(dict.fromkeys(int(value) for value in resolved_failure_ids))
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
            if job["kind"] == "repair" and (failure_updates or resolved_ids):
                target_failure_ids = {
                    int(row["failure_id"])
                    for row in connection.execute(
                        """
                        SELECT failure_id FROM channel_scan_repair_targets
                        WHERE job_id = ?
                        """,
                        (job_id,),
                    ).fetchall()
                }
                if (
                    repair_failure_id not in target_failure_ids
                    or any(
                        int(update["failure_id"]) != repair_failure_id
                        for update in failure_updates
                    )
                    or any(failure_id != repair_failure_id for failure_id in resolved_ids)
                ):
                    raise ValueError(
                        "Repair index updates must be scoped to the active target"
                    )
            for failure_id in resolved_ids:
                target = connection.execute(
                    """
                    SELECT t.next_message_id, t.status AS target_status,
                           f.end_message_id, f.status AS failure_status
                    FROM channel_scan_repair_targets AS t
                    JOIN channel_scan_failures AS f
                      ON f.id = t.failure_id AND f.library_id = t.library_id
                    WHERE t.job_id = ? AND t.failure_id = ?
                    """,
                    (job_id, failure_id),
                ).fetchone()
                if target is None:
                    raise ValueError("Resolved failure is not a target of this repair")
                if target["next_message_id"] <= target["end_message_id"]:
                    raise ValueError("Cannot resolve an incompletely fetched repair target")
                if (
                    target["target_status"] == "completed"
                    or target["failure_status"] == "resolved"
                ):
                    raise ValueError("Repair target is already resolved")

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
            changed_existing_ids = {
                int(existing_by_start[start]["id"])
                for start, changed in changed_desired.items()
                if changed and start in existing_by_start
            }
            changed_existing_ids.update(int(row["id"]) for row in removed_rows)
            if any(
                int(row["id"]) in changed_existing_ids
                and row["current_download_status"] == "downloading"
                for row in existing_rows
            ):
                result = dict(job)
                result.update(
                    {
                        "changed_package_count": changed_count,
                        "superseded_package_count": len(removed_rows),
                        "invalidated_selection_count": 0,
                        "publication_deferred": True,
                    }
                )
                return result
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
                    SET uncertain_through_message_id = MAX(
                            uncertain_through_message_id, ?
                        ),
                        updated_at = ?
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

            for failure_id in resolved_ids:
                connection.execute(
                    """
                    UPDATE channel_scan_repair_targets
                    SET status = 'completed', updated_at = ?, completed_at = ?
                    WHERE job_id = ? AND failure_id = ?
                    """,
                    (now, now, job_id, failure_id),
                )
                connection.execute(
                    """
                    UPDATE channel_scan_failures
                    SET status = 'resolved', updated_at = ?, resolved_at = ?
                    WHERE id = ? AND library_id = ?
                    """,
                    (now, now, failure_id, library_id),
                )

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
                "publication_deferred": False,
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

    def retry_failed_repair_job(
        self, failed_job_id: int, now: Optional[float] = None
    ) -> dict:
        """Clone unfinished targets from a failed repair without losing cursors."""

        now = time.time() if now is None else now
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            failed = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (failed_job_id,)
            ).fetchone()
            if failed is None:
                raise KeyError(f"Scan job {failed_job_id} does not exist")
            if failed["kind"] != "repair" or failed["status"] != "failed":
                raise ValueError("Only failed repair jobs can be retried here")
            active = connection.execute(
                """
                SELECT id FROM channel_scan_jobs
                WHERE library_id = ? AND status IN (
                    'queued', 'running', 'paused_user',
                    'auto_paused_download', 'waiting_rate_limit', 'stopped'
                )
                LIMIT 1
                """,
                (failed["library_id"],),
            ).fetchone()
            if active is not None:
                raise ValueError(
                    f"Library {failed['library_id']} already has a recoverable scan job"
                )
            targets = connection.execute(
                """
                SELECT t.* FROM channel_scan_repair_targets AS t
                JOIN channel_scan_failures AS f
                  ON f.id = t.failure_id AND f.library_id = t.library_id
                WHERE t.job_id = ? AND t.status != 'completed'
                  AND f.status != 'resolved'
                ORDER BY t.id
                """,
                (failed_job_id,),
            ).fetchall()
            if not targets:
                raise ValueError("Failed repair has no unfinished targets")
            library = connection.execute(
                "SELECT * FROM channel_libraries WHERE id = ?",
                (failed["library_id"],),
            ).fetchone()
            job_id = self._insert_scan_job(
                connection,
                library,
                "repair",
                int(failed["start_message_id"]),
                int(failed["snapshot_max_message_id"]),
                now,
            )
            for target in targets:
                connection.execute(
                    """
                    INSERT INTO channel_scan_repair_targets (
                        job_id, failure_id, library_id, next_message_id,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'queued', ?, ?)
                    """,
                    (
                        job_id,
                        target["failure_id"],
                        target["library_id"],
                        target["next_message_id"],
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
                (now, failed["library_id"]),
            )
            job = connection.execute(
                "SELECT * FROM channel_scan_jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return dict(job)

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
                SET status = CASE control_requested
                        WHEN 'pause' THEN 'paused_user'
                        WHEN 'stop' THEN 'stopped'
                        ELSE 'queued' END,
                    control_requested = NULL,
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
            connection.execute(
                """
                UPDATE channel_libraries
                SET status = 'paused', updated_at = ?
                WHERE id IN (
                    SELECT library_id FROM channel_scan_jobs
                    WHERE status = 'paused_user'
                )
                """,
                (now,),
            )
            connection.execute(
                """
                UPDATE channel_libraries
                SET status = 'stopped', updated_at = ?
                WHERE id IN (
                    SELECT library_id FROM channel_scan_jobs
                    WHERE status = 'stopped'
                )
                """,
                (now,),
            )
        return recovered

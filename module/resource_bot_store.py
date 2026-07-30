"""Persistent access, channel binding, and delivery state for the resource Bot."""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Optional, Union


RESOURCE_BOT_SCHEMA_VERSION = 2
ACTIVATION_STATUSES = frozenset({"available", "redeemed", "revoked"})
USER_STATUSES = frozenset({"active", "revoked"})
BINDING_STATUSES = frozenset({"active", "permission_lost", "unbound"})
JOB_STATUSES = frozenset(
    {"queued", "downloading", "uploading", "completed", "failed", "cancelled"}
)
ACTIVE_JOB_STATUSES = frozenset({"downloading", "uploading"})
TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _now() -> float:
    return time.time()


def _key_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row_dict(row: Optional[sqlite3.Row]) -> Optional[dict]:
    return dict(row) if row is not None else None


class ResourceBotStore:
    """Own the resource Bot's independent SQLite state."""

    def __init__(self, path: Union[str, Path]):
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def initialize(self) -> None:
        """Create or migrate storage and reject unsupported future schemas."""

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            schema_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if schema_version > RESOURCE_BOT_SCHEMA_VERSION:
                raise RuntimeError(
                    "newer resource Bot database schema is not supported: "
                    f"{schema_version} > {RESOURCE_BOT_SCHEMA_VERSION}"
                )
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS resource_activation_keys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key_hash TEXT NOT NULL UNIQUE,
                    key_prefix TEXT NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN ('available', 'redeemed', 'revoked')),
                    created_by INTEGER NOT NULL,
                    redeemed_by INTEGER,
                    created_at REAL NOT NULL,
                    redeemed_at REAL,
                    revoked_at REAL
                );

                CREATE TABLE IF NOT EXISTS resource_users (
                    telegram_user_id INTEGER PRIMARY KEY,
                    status TEXT NOT NULL
                        CHECK (status IN ('active', 'revoked')),
                    activation_key_id INTEGER NOT NULL,
                    activated_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    revoked_at REAL,
                    FOREIGN KEY (activation_key_id)
                        REFERENCES resource_activation_keys(id)
                );

                CREATE TABLE IF NOT EXISTS resource_channel_bindings (
                    telegram_user_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    username TEXT,
                    status TEXT NOT NULL
                        CHECK (status IN (
                            'active', 'permission_lost', 'unbound'
                        )),
                    bound_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    last_verified_at REAL NOT NULL,
                    FOREIGN KEY (telegram_user_id)
                        REFERENCES resource_users(telegram_user_id)
                );

                CREATE TABLE IF NOT EXISTS resource_delivery_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    public_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    telegram_user_id INTEGER NOT NULL,
                    package_id INTEGER NOT NULL,
                    package_revision INTEGER NOT NULL,
                    target_chat_id INTEGER NOT NULL,
                    status TEXT NOT NULL
                        CHECK (status IN (
                            'queued', 'downloading', 'uploading',
                            'completed', 'failed', 'cancelled'
                        )),
                    total_items INTEGER NOT NULL,
                    downloaded_items INTEGER NOT NULL DEFAULT 0,
                    uploaded_items INTEGER NOT NULL DEFAULT 0,
                    download_speed INTEGER NOT NULL DEFAULT 0,
                    upload_speed INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT,
                    error_summary TEXT,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    updated_at REAL NOT NULL,
                    finished_at REAL,
                    FOREIGN KEY (telegram_user_id)
                        REFERENCES resource_users(telegram_user_id)
                );

                CREATE INDEX IF NOT EXISTS idx_resource_keys_status_created
                    ON resource_activation_keys(status, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_resource_bindings_chat_status
                    ON resource_channel_bindings(chat_id, status);
                CREATE INDEX IF NOT EXISTS idx_resource_jobs_queue
                    ON resource_delivery_jobs(status, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_resource_jobs_user_created
                    ON resource_delivery_jobs(
                        telegram_user_id, created_at DESC, id DESC
                    );
                """
            )
            job_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(resource_delivery_jobs)"
                ).fetchall()
            }
            if "download_speed" not in job_columns:
                connection.execute(
                    """
                    ALTER TABLE resource_delivery_jobs
                    ADD COLUMN download_speed INTEGER NOT NULL DEFAULT 0
                    """
                )
            if "upload_speed" not in job_columns:
                connection.execute(
                    """
                    ALTER TABLE resource_delivery_jobs
                    ADD COLUMN upload_speed INTEGER NOT NULL DEFAULT 0
                    """
                )
            connection.execute(
                f"PRAGMA user_version = {RESOURCE_BOT_SCHEMA_VERSION}"
            )
        if os.name != "nt":
            os.chmod(self.path, 0o600)

    def create_activation_key(self, created_by: int, now: float = None) -> str:
        """Create one high-entropy activation key and persist only its digest."""

        created_at = _now() if now is None else float(now)
        while True:
            key = secrets.token_urlsafe(24)
            try:
                with self.connect() as connection:
                    connection.execute(
                        """
                        INSERT INTO resource_activation_keys (
                            key_hash, key_prefix, status, created_by, created_at
                        ) VALUES (?, ?, 'available', ?, ?)
                        """,
                        (_key_hash(key), key[:8], int(created_by), created_at),
                    )
                return key
            except sqlite3.IntegrityError:
                continue

    def redeem_activation_key(
        self, key: str, user_id: int, now: float = None
    ) -> bool:
        """Atomically redeem one unused key and activate the Telegram user."""

        value = str(key or "").strip()
        if not value:
            return False
        redeemed_at = _now() if now is None else float(now)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id FROM resource_activation_keys
                WHERE key_hash = ? AND status = 'available'
                """,
                (_key_hash(value),),
            ).fetchone()
            if row is None:
                return False
            key_id = int(row["id"])
            updated = connection.execute(
                """
                UPDATE resource_activation_keys
                SET status = 'redeemed', redeemed_by = ?, redeemed_at = ?
                WHERE id = ? AND status = 'available'
                """,
                (int(user_id), redeemed_at, key_id),
            )
            if updated.rowcount != 1:
                return False
            connection.execute(
                """
                INSERT INTO resource_users (
                    telegram_user_id, status, activation_key_id,
                    activated_at, updated_at, revoked_at
                ) VALUES (?, 'active', ?, ?, ?, NULL)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    status = 'active',
                    activation_key_id = excluded.activation_key_id,
                    activated_at = excluded.activated_at,
                    updated_at = excluded.updated_at,
                    revoked_at = NULL
                """,
                (int(user_id), key_id, redeemed_at, redeemed_at),
            )
        return True

    def get_user(self, user_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM resource_users WHERE telegram_user_id = ?
                """,
                (int(user_id),),
            ).fetchone()
        return _row_dict(row)

    def is_user_active(self, user_id: int) -> bool:
        user = self.get_user(user_id)
        return bool(user and user["status"] == "active")

    def revoke_user(self, user_id: int, now: float = None) -> bool:
        """Revoke one user, unbind their channel, and cancel queued work."""

        revoked_at = _now() if now is None else float(now)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            updated = connection.execute(
                """
                UPDATE resource_users
                SET status = 'revoked', updated_at = ?, revoked_at = ?
                WHERE telegram_user_id = ?
                """,
                (revoked_at, revoked_at, int(user_id)),
            )
            if updated.rowcount == 0:
                return False
            connection.execute(
                """
                UPDATE resource_channel_bindings
                SET status = 'unbound', updated_at = ?, last_verified_at = ?
                WHERE telegram_user_id = ?
                """,
                (revoked_at, revoked_at, int(user_id)),
            )
            connection.execute(
                """
                UPDATE resource_delivery_jobs
                SET status = 'cancelled', error_code = 'activation_revoked',
                    error_summary = 'Resource Bot activation was revoked',
                    updated_at = ?, finished_at = ?
                WHERE telegram_user_id = ? AND status = 'queued'
                """,
                (revoked_at, revoked_at, int(user_id)),
            )
        return True

    def bind_channel(
        self,
        user_id: int,
        chat_id: int,
        title: str,
        username: Optional[str],
        now: float = None,
    ) -> dict:
        """Bind one verified channel to one active user."""

        bound_at = _now() if now is None else float(now)
        normalized_title = str(title or "").strip() or str(chat_id)
        normalized_username = str(username).strip() if username else None
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = connection.execute(
                """
                SELECT status FROM resource_users WHERE telegram_user_id = ?
                """,
                (int(user_id),),
            ).fetchone()
            if user is None or user["status"] != "active":
                raise ValueError("activation_required")
            existing = connection.execute(
                """
                SELECT telegram_user_id, status
                FROM resource_channel_bindings WHERE chat_id = ?
                """,
                (int(chat_id),),
            ).fetchone()
            if (
                existing is not None
                and int(existing["telegram_user_id"]) != int(user_id)
                and existing["status"] != "unbound"
            ):
                raise ValueError("channel_already_bound")
            if existing is not None and int(existing["telegram_user_id"]) != int(
                user_id
            ):
                connection.execute(
                    """
                    DELETE FROM resource_channel_bindings
                    WHERE telegram_user_id = ?
                    """,
                    (int(existing["telegram_user_id"]),),
                )
            connection.execute(
                """
                INSERT INTO resource_channel_bindings (
                    telegram_user_id, chat_id, title, username, status,
                    bound_at, updated_at, last_verified_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?)
                ON CONFLICT(telegram_user_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    title = excluded.title,
                    username = excluded.username,
                    status = 'active',
                    bound_at = excluded.bound_at,
                    updated_at = excluded.updated_at,
                    last_verified_at = excluded.last_verified_at
                """,
                (
                    int(user_id),
                    int(chat_id),
                    normalized_title,
                    normalized_username,
                    bound_at,
                    bound_at,
                    bound_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM resource_channel_bindings
                WHERE telegram_user_id = ?
                """,
                (int(user_id),),
            ).fetchone()
        return dict(row)

    def get_binding(self, user_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM resource_channel_bindings
                WHERE telegram_user_id = ?
                """,
                (int(user_id),),
            ).fetchone()
        return _row_dict(row)

    def get_binding_by_chat(self, chat_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM resource_channel_bindings WHERE chat_id = ?
                """,
                (int(chat_id),),
            ).fetchone()
        return _row_dict(row)

    def mark_binding_permission_lost(
        self, chat_id: int, now: float = None
    ) -> bool:
        verified_at = _now() if now is None else float(now)
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE resource_channel_bindings
                SET status = 'permission_lost', updated_at = ?,
                    last_verified_at = ?
                WHERE chat_id = ? AND status != 'unbound'
                """,
                (verified_at, verified_at, int(chat_id)),
            )
        return updated.rowcount > 0

    def mark_binding_verified(
        self, chat_id: int, now: float = None
    ) -> bool:
        verified_at = _now() if now is None else float(now)
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE resource_channel_bindings
                SET status = 'active', updated_at = ?, last_verified_at = ?
                WHERE chat_id = ? AND status != 'unbound'
                """,
                (verified_at, verified_at, int(chat_id)),
            )
        return updated.rowcount > 0

    def unbind_channel(self, user_id: int, now: float = None) -> bool:
        updated_at = _now() if now is None else float(now)
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE resource_channel_bindings
                SET status = 'unbound', updated_at = ?, last_verified_at = ?
                WHERE telegram_user_id = ? AND status != 'unbound'
                """,
                (updated_at, updated_at, int(user_id)),
            )
        return updated.rowcount > 0

    def create_delivery_job(
        self,
        *,
        idempotency_key: str,
        user_id: int,
        package_id: int,
        package_revision: int,
        target_chat_id: int,
        total_items: int,
        now: float = None,
    ) -> tuple[dict, bool]:
        """Create one queued job or return the existing idempotent result."""

        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("idempotency_key_required")
        created_at = _now() if now is None else float(now)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            user = connection.execute(
                """
                SELECT status FROM resource_users WHERE telegram_user_id = ?
                """,
                (int(user_id),),
            ).fetchone()
            if user is None or user["status"] != "active":
                raise ValueError("activation_required")
            binding = connection.execute(
                """
                SELECT chat_id, status FROM resource_channel_bindings
                WHERE telegram_user_id = ?
                """,
                (int(user_id),),
            ).fetchone()
            if (
                binding is None
                or binding["status"] != "active"
                or int(binding["chat_id"]) != int(target_chat_id)
            ):
                raise ValueError("channel_not_bound")
            existing = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs
                WHERE idempotency_key = ?
                """,
                (key,),
            ).fetchone()
            if existing is not None:
                return dict(existing), False
            public_id = secrets.token_urlsafe(12)
            cursor = connection.execute(
                """
                INSERT INTO resource_delivery_jobs (
                    public_id, idempotency_key, telegram_user_id,
                    package_id, package_revision, target_chat_id, status,
                    total_items, downloaded_items, uploaded_items,
                    download_speed, upload_speed,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, 0, 0, 0, 0, ?, ?)
                """,
                (
                    public_id,
                    key,
                    int(user_id),
                    int(package_id),
                    int(package_revision),
                    int(target_chat_id),
                    max(int(total_items), 0),
                    created_at,
                    created_at,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs WHERE id = ?
                """,
                (int(cursor.lastrowid),),
            ).fetchone()
        return dict(row), True

    def get_delivery_job(self, job_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs WHERE id = ?
                """,
                (int(job_id),),
            ).fetchone()
        return _row_dict(row)

    def get_delivery_job_by_public_id(self, public_id: str) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs WHERE public_id = ?
                """,
                (str(public_id),),
            ).fetchone()
        return _row_dict(row)

    def get_latest_delivery_job(self, user_id: int) -> Optional[dict]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs
                WHERE telegram_user_id = ?
                ORDER BY created_at DESC, id DESC LIMIT 1
                """,
                (int(user_id),),
            ).fetchone()
        return _row_dict(row)

    def list_delivery_jobs(
        self, *, limit: int = 100, offset: int = 0
    ) -> tuple[list[dict], int]:
        """Return newest delivery jobs with target metadata and queue position."""

        bounded_limit = min(max(int(limit), 1), 200)
        bounded_offset = max(int(offset), 0)
        with self.connect() as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM resource_delivery_jobs"
                ).fetchone()[0]
            )
            rows = connection.execute(
                """
                SELECT
                    jobs.*,
                    bindings.title AS binding_title,
                    bindings.username AS binding_username,
                    CASE
                        WHEN jobs.status = 'queued' THEN (
                            SELECT COUNT(*) + 1
                            FROM resource_delivery_jobs AS queued
                            WHERE queued.status = 'queued'
                              AND (
                                  queued.created_at < jobs.created_at
                                  OR (
                                      queued.created_at = jobs.created_at
                                      AND queued.id < jobs.id
                                  )
                              )
                        )
                        ELSE NULL
                    END AS queue_position
                FROM resource_delivery_jobs AS jobs
                LEFT JOIN resource_channel_bindings AS bindings
                  ON bindings.chat_id = jobs.target_chat_id
                ORDER BY jobs.created_at DESC, jobs.id DESC
                LIMIT ? OFFSET ?
                """,
                (bounded_limit, bounded_offset),
            ).fetchall()
        return [dict(row) for row in rows], total

    def delivery_job_summary(self) -> dict:
        """Return status counts and active transfer speeds for the Web page."""

        summary = {
            "queued": 0,
            "active": 0,
            "completed": 0,
            "failed": 0,
            "cancelled": 0,
            "download_speed": 0,
            "upload_speed": 0,
        }
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM resource_delivery_jobs
                GROUP BY status
                """
            ).fetchall()
            speeds = connection.execute(
                """
                SELECT
                    COALESCE(SUM(download_speed), 0) AS download_speed,
                    COALESCE(SUM(upload_speed), 0) AS upload_speed
                FROM resource_delivery_jobs
                WHERE status IN ('downloading', 'uploading')
                """
            ).fetchone()
        for row in rows:
            status = str(row["status"])
            count = int(row["count"])
            if status in ACTIVE_JOB_STATUSES:
                summary["active"] += count
            elif status in summary:
                summary[status] = count
        summary["download_speed"] = int(speeds["download_speed"])
        summary["upload_speed"] = int(speeds["upload_speed"])
        return summary

    def claim_next_delivery_job(self, now: float = None) -> Optional[dict]:
        """Atomically move the oldest queued job into downloading."""

        started_at = _now() if now is None else float(now)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id FROM resource_delivery_jobs
                WHERE status = 'queued'
                ORDER BY created_at, id LIMIT 1
                """
            ).fetchone()
            if row is None:
                return None
            job_id = int(row["id"])
            updated = connection.execute(
                """
                UPDATE resource_delivery_jobs
                SET status = 'downloading', started_at = COALESCE(started_at, ?),
                    updated_at = ?, error_code = NULL, error_summary = NULL,
                    download_speed = 0, upload_speed = 0
                WHERE id = ? AND status = 'queued'
                """,
                (started_at, started_at, job_id),
            )
            if updated.rowcount != 1:
                return None
            claimed = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
        return dict(claimed)

    def update_job_progress(
        self,
        job_id: int,
        *,
        status: Optional[str] = None,
        downloaded_items: Optional[int] = None,
        uploaded_items: Optional[int] = None,
        download_speed: Optional[int] = None,
        upload_speed: Optional[int] = None,
        now: float = None,
    ) -> dict:
        """Update bounded non-terminal progress for one active job."""

        if status is not None and status not in ACTIVE_JOB_STATUSES:
            raise ValueError("invalid_active_job_status")
        updated_at = _now() if now is None else float(now)
        assignments = ["updated_at = ?"]
        parameters: list[object] = [updated_at]
        if status is not None:
            assignments.append("status = ?")
            parameters.append(status)
        if downloaded_items is not None:
            assignments.append("downloaded_items = ?")
            parameters.append(max(int(downloaded_items), 0))
        if uploaded_items is not None:
            assignments.append("uploaded_items = ?")
            parameters.append(max(int(uploaded_items), 0))
        if download_speed is not None:
            assignments.append("download_speed = ?")
            parameters.append(max(int(download_speed), 0))
        if upload_speed is not None:
            assignments.append("upload_speed = ?")
            parameters.append(max(int(upload_speed), 0))
        parameters.append(int(job_id))
        with self.connect() as connection:
            updated = connection.execute(
                f"""
                UPDATE resource_delivery_jobs
                SET {", ".join(assignments)}
                WHERE id = ? AND status IN ('downloading', 'uploading')
                """,
                parameters,
            )
            if updated.rowcount != 1:
                raise ValueError("delivery_job_not_active")
            row = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs WHERE id = ?
                """,
                (int(job_id),),
            ).fetchone()
        return dict(row)

    def finish_delivery_job(
        self,
        job_id: int,
        status: str,
        error_code: Optional[str] = None,
        error_summary: Optional[str] = None,
        now: float = None,
    ) -> dict:
        """Move one queued or active job to a terminal state."""

        if status not in TERMINAL_JOB_STATUSES:
            raise ValueError("invalid_terminal_job_status")
        finished_at = _now() if now is None else float(now)
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE resource_delivery_jobs
                SET status = ?, error_code = ?, error_summary = ?,
                    download_speed = 0, upload_speed = 0,
                    updated_at = ?, finished_at = ?
                WHERE id = ? AND status NOT IN ('completed', 'failed', 'cancelled')
                """,
                (
                    status,
                    error_code,
                    error_summary,
                    finished_at,
                    finished_at,
                    int(job_id),
                ),
            )
            if updated.rowcount != 1:
                row = connection.execute(
                    """
                    SELECT * FROM resource_delivery_jobs WHERE id = ?
                    """,
                    (int(job_id),),
                ).fetchone()
                if row is None:
                    raise KeyError(f"Delivery job {job_id} does not exist")
                return dict(row)
            row = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs WHERE id = ?
                """,
                (int(job_id),),
            ).fetchone()
        return dict(row)

    def recover_interrupted_jobs(self, now: float = None) -> int:
        """Fail non-resumable active work while retaining queued jobs."""

        recovered_at = _now() if now is None else float(now)
        with self.connect() as connection:
            updated = connection.execute(
                """
                UPDATE resource_delivery_jobs
                SET status = 'failed', error_code = 'restart_interrupted',
                    error_summary = 'Resource delivery was interrupted by restart',
                    download_speed = 0, upload_speed = 0,
                    updated_at = ?, finished_at = ?
                WHERE status IN ('downloading', 'uploading')
                """,
                (recovered_at, recovered_at),
            )
        return updated.rowcount

    def list_queued_delivery_jobs(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs
                WHERE status = 'queued' ORDER BY created_at, id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def cancel_queued_delivery_job(
        self, public_id: str, now: float = None
    ) -> dict:
        """Cancel one queued job without interrupting active or partial uploads."""

        cancelled_at = _now() if now is None else float(now)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT id, status FROM resource_delivery_jobs
                WHERE public_id = ?
                """,
                (str(public_id),),
            ).fetchone()
            if row is None:
                raise KeyError(public_id)
            if row["status"] != "queued":
                raise ValueError("delivery_job_not_queued")
            connection.execute(
                """
                UPDATE resource_delivery_jobs
                SET status = 'cancelled',
                    error_code = 'cancelled_by_admin',
                    error_summary = 'Resource delivery was cancelled before start',
                    download_speed = 0, upload_speed = 0,
                    updated_at = ?, finished_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (cancelled_at, cancelled_at, int(row["id"])),
            )
            cancelled = connection.execute(
                """
                SELECT * FROM resource_delivery_jobs WHERE id = ?
                """,
                (int(row["id"]),),
            ).fetchone()
        return dict(cancelled)

    def clear_terminal_delivery_job(self, public_id: str) -> bool:
        """Delete one terminal delivery job from Web history."""

        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT status FROM resource_delivery_jobs WHERE public_id = ?
                """,
                (str(public_id),),
            ).fetchone()
            if row is None:
                raise KeyError(public_id)
            if row["status"] not in TERMINAL_JOB_STATUSES:
                raise ValueError("delivery_job_not_terminal")
            deleted = connection.execute(
                """
                DELETE FROM resource_delivery_jobs WHERE public_id = ?
                """,
                (str(public_id),),
            )
        return deleted.rowcount == 1

    def clear_terminal_delivery_jobs(self) -> int:
        """Delete all terminal delivery jobs while preserving active and queued work."""

        with self.connect() as connection:
            deleted = connection.execute(
                """
                DELETE FROM resource_delivery_jobs
                WHERE status IN ('completed', 'failed', 'cancelled')
                """
            )
        return deleted.rowcount

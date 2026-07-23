"""In-memory Web task state snapshots."""

import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from module.app import DownloadStatus
from utils.format import format_byte


class TaskStatus:
    """Task status values exposed to the Web UI."""

    CREATED = "created"
    SCANNING = "scanning"
    WAITING_CONFIRMATION = "waiting_confirmation"
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    CANCELLED = "cancelled"
    FAILED = "failed"


class FileStatus:
    """File status values exposed to the Web UI."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    UPLOAD_FAILED = "upload_failed"
    SKIPPED = "skipped"
    FAILED = "failed"


TERMINAL_TASK_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.COMPLETED_WITH_ERRORS,
    TaskStatus.CANCELLED,
    TaskStatus.FAILED,
}


class TaskIdentityConflictError(ValueError):
    """A deterministic task ID already belongs to different immutable data."""

    code = "task_identity_conflict"

    def __init__(self, task_id: Any):
        super().__init__(self.code)
        self.task_id = str(task_id)

SUCCESS_FILE_STATUSES = {FileStatus.DOWNLOADED, FileStatus.UPLOADED}
FAILED_FILE_STATUSES = {FileStatus.FAILED, FileStatus.UPLOAD_FAILED}
SKIPPED_FILE_STATUSES = {FileStatus.SKIPPED}


def _now() -> float:
    return time.time()


def mask_display_name(name: str, hide: bool) -> str:
    """Return a safe display name, respecting hidden filename config."""

    if not name:
        return ""
    basename = os.path.basename(str(name))
    if not hide:
        return basename
    _, extension = os.path.splitext(basename)
    return f"****{extension}"


@dataclass
class FileSnapshot:
    """Web-safe status for one media file/message."""

    message_id: str
    status: str = FileStatus.QUEUED
    filename: str = ""
    total_size: int = 0
    downloaded_size: int = 0
    download_speed: int = 0
    save_path: str = ""
    error: str = ""
    updated_at: float = field(default_factory=_now)
    uploaded_size: int = 0
    upload_speed: int = 0

    @property
    def download_progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return round(min(self.downloaded_size / self.total_size * 100, 100.0), 1)

    @property
    def upload_progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return round(min(self.uploaded_size / self.total_size * 100, 100.0), 1)

    def to_dict(self, hide_file_name: bool = False) -> dict:
        return {
            "message_id": self.message_id,
            "status": self.status,
            "filename": mask_display_name(self.filename, hide_file_name),
            "total_size": format_byte(self.total_size),
            "total_size_bytes": self.total_size,
            "downloaded_size": format_byte(self.downloaded_size),
            "downloaded_size_bytes": self.downloaded_size,
            "download_progress": self.download_progress,
            "download_speed": format_byte(int(self.download_speed)) + "/s",
            "download_speed_bytes": int(self.download_speed),
            "save_path": "" if hide_file_name else self.save_path.replace("\\", "/"),
            "error": self.error,
            "updated_at": self.updated_at,
            "uploaded_size_bytes": self.uploaded_size,
            "upload_progress": self.upload_progress,
            "upload_speed": format_byte(int(self.upload_speed)) + "/s",
            "upload_speed_bytes": int(self.upload_speed),
        }


@dataclass
class WorkflowSnapshot:
    """Web-safe scan/workflow summary."""

    workflow_type: str = ""
    status: str = ""
    scan_count: int = 0
    media_count: int = 0
    selected_count: int = 0
    summary: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "workflow_type": self.workflow_type,
            "status": self.status,
            "scan_count": self.scan_count,
            "media_count": self.media_count,
            "selected_count": self.selected_count,
            "summary": self.summary,
            "error": self.error,
        }


@dataclass
class TaskSnapshot:
    """Web-safe status for one user-visible task."""

    task_id: str
    source: str = "bot"
    task_type: str = "unknown"
    chat_id: Optional[int] = None
    title: str = ""
    status: str = TaskStatus.CREATED
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    total_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    upload_success_count: int = 0
    current_file: Optional[FileSnapshot] = None
    workflow: Optional[WorkflowSnapshot] = None
    error: str = ""
    needs_confirmation: bool = False
    files: dict[str, FileSnapshot] = field(default_factory=dict)

    def refresh_counts_from_files(self) -> None:
        if self.files:
            self.total_count = max(self.total_count, len(self.files))
            self.success_count = sum(
                1
                for item in self.files.values()
                if item.status in SUCCESS_FILE_STATUSES
            )
            self.failed_count = sum(
                1 for item in self.files.values() if item.status in FAILED_FILE_STATUSES
            )
            self.skipped_count = sum(
                1
                for item in self.files.values()
                if item.status in SKIPPED_FILE_STATUSES
            )
            self.upload_success_count = max(
                self.upload_success_count,
                sum(
                    1
                    for item in self.files.values()
                    if item.status == FileStatus.UPLOADED
                ),
            )

    def to_dict(
        self, hide_file_name: bool = False, include_files: bool = False
    ) -> dict:
        self.refresh_counts_from_files()
        current_file = self.current_file
        if not current_file and self.files:
            current_file = sorted(
                self.files.values(), key=lambda item: item.updated_at, reverse=True
            )[0]
        payload = {
            "task_id": self.task_id,
            "source": self.source,
            "task_type": self.task_type,
            "chat_id": self.chat_id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "total_count": self.total_count,
            "success_count": self.success_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
            "upload_success_count": self.upload_success_count,
            "current_file": (
                current_file.to_dict(hide_file_name) if current_file else None
            ),
            "workflow": self.workflow.to_dict() if self.workflow else None,
            "error": self.error,
            "needs_confirmation": self.needs_confirmation,
            "upload_progress": self._upload_progress(),
            "upload_speed": format_byte(self._upload_speed_bytes()) + "/s",
        }
        if include_files:
            payload["files"] = [
                item.to_dict(hide_file_name)
                for item in sorted(
                    self.files.values(), key=lambda file: file.message_id
                )
            ]
        return payload

    def _upload_progress(self) -> float:
        uploading = [
            f
            for f in self.files.values()
            if f.status in (FileStatus.UPLOADING, FileStatus.UPLOADED)
        ]
        if not uploading:
            return 0.0
        done = sum(1 for f in uploading if f.status == FileStatus.UPLOADED)
        active = [
            f.upload_progress for f in uploading if f.status == FileStatus.UPLOADING
        ]
        partial = sum(active) / 100.0
        return round((done + partial) / len(uploading) * 100, 1)

    def _upload_speed_bytes(self) -> int:
        return int(
            sum(
                f.upload_speed
                for f in self.files.values()
                if f.status == FileStatus.UPLOADING
            )
        )


class TaskStateStore:
    """Process-local store for task snapshots."""

    def __init__(self, recent_limit: int = 200, storage_path: Optional[Path] = None):
        self.recent_limit = recent_limit
        self._lock = threading.RLock()
        self._active: dict[str, TaskSnapshot] = {}
        self._completed: dict[str, TaskSnapshot] = {}
        self.storage_path = Path(storage_path) if storage_path else None
        if self.storage_path:
            self._init_storage()
            self._load_storage()

    def clear(self) -> None:
        with self._lock:
            self._active.clear()
            self._completed.clear()
            if self.storage_path:
                with self._connect() as connection:
                    connection.execute("DELETE FROM task_files")
                    connection.execute("DELETE FROM tasks")

    def create_task(
        self,
        task_id: Any,
        source: str = "bot",
        task_type: str = "unknown",
        chat_id: Optional[int] = None,
        title: str = "",
        status: str = TaskStatus.CREATED,
        **updates,
    ) -> TaskSnapshot:
        task_key = str(task_id)
        with self._lock:
            task = self._active.get(task_key) or self._completed.pop(task_key, None)
            if not task:
                task = TaskSnapshot(
                    task_id=task_key,
                    source=source,
                    task_type=task_type,
                    chat_id=chat_id,
                    title=title,
                    status=status,
                )
            self._apply_updates(
                task,
                source=source,
                task_type=task_type,
                chat_id=chat_id,
                title=title,
                status=status,
                **updates,
            )
            self._active[task_key] = task
            self._persist_task(task)
            return task

    def ensure_task(
        self,
        task_id: Any,
        source: str = "bot",
        task_type: str = "unknown",
        chat_id: Optional[int] = None,
        title: str = "",
        status: str = TaskStatus.CREATED,
        **updates,
    ) -> TaskSnapshot:
        """Create a deterministic task once without resetting an existing task."""

        task_key = str(task_id)
        with self._lock:
            existing = self._active.get(task_key) or self._completed.get(task_key)
            if existing is not None:
                expected_identity = {
                    "source": source,
                    "task_type": str(task_type),
                    "chat_id": chat_id,
                    "title": title,
                }
                for count_field in (
                    "total_count",
                    "success_count",
                    "failed_count",
                    "skipped_count",
                    "upload_success_count",
                ):
                    if count_field in updates:
                        expected_identity[count_field] = int(updates[count_field])
                if any(
                    getattr(existing, field_name) != expected_value
                    for field_name, expected_value in expected_identity.items()
                ):
                    raise TaskIdentityConflictError(task_key)
                return existing
            return self.create_task(
                task_key,
                source=source,
                task_type=task_type,
                chat_id=chat_id,
                title=title,
                status=status,
                **updates,
            )

    def update_task(self, task_id: Any, **updates) -> Optional[TaskSnapshot]:
        task_key = str(task_id)
        with self._lock:
            task = self._active.get(task_key) or self._completed.get(task_key)
            if not task:
                return None
            self._apply_updates(task, **updates)
            if task.status in TERMINAL_TASK_STATUSES:
                self._move_completed(task_key, task)
            else:
                self._completed.pop(task_key, None)
                self._active[task_key] = task
                self._persist_task(task)
            return task

    def upsert_file(self, task_id: Any, message_id: Any, **updates) -> FileSnapshot:
        task_key = str(task_id)
        message_key = str(message_id)
        with self._lock:
            task = (
                self._active.get(task_key)
                or self._completed.get(task_key)
                or self.create_task(task_key)
            )
            file_snapshot = task.files.get(message_key)
            if not file_snapshot:
                file_snapshot = FileSnapshot(message_id=message_key)
                task.files[message_key] = file_snapshot
            for key, value in updates.items():
                if hasattr(file_snapshot, key) and value is not None:
                    setattr(file_snapshot, key, value)
            file_snapshot.updated_at = _now()
            task.current_file = file_snapshot
            task.updated_at = file_snapshot.updated_at
            task.refresh_counts_from_files()
            self._persist_task(task)
            self._persist_file(task_key, file_snapshot)
            return file_snapshot

    def complete_task(self, task_id: Any) -> Optional[TaskSnapshot]:
        task_key = str(task_id)
        with self._lock:
            task = self._active.get(task_key) or self._completed.get(task_key)
            if not task:
                return None
            task.refresh_counts_from_files()
            if task.failed_count:
                task.status = TaskStatus.COMPLETED_WITH_ERRORS
            elif task.status not in {TaskStatus.FAILED, TaskStatus.CANCELLED}:
                task.status = TaskStatus.COMPLETED
            task.updated_at = _now()
            self._move_completed(task_key, task)
            return task

    def get_task(self, task_id: Any) -> Optional[TaskSnapshot]:
        task_key = str(task_id)
        with self._lock:
            return self._active.get(task_key) or self._completed.get(task_key)

    def remove_task(self, task_id: Any) -> bool:
        task_key = str(task_id)
        with self._lock:
            removed = self._active.pop(task_key, None) or self._completed.pop(
                task_key, None
            )
            if self.storage_path:
                with self._connect() as connection:
                    connection.execute("DELETE FROM task_files WHERE task_id = ?", (task_key,))
                    connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_key,))
            return removed is not None

    def clear_completed(self) -> int:
        with self._lock:
            count = len(self._completed)
            completed_keys = list(self._completed)
            self._completed.clear()
            if self.storage_path and completed_keys:
                with self._connect() as connection:
                    connection.executemany(
                        "DELETE FROM task_files WHERE task_id = ?",
                        [(task_id,) for task_id in completed_keys],
                    )
                    connection.executemany(
                        "DELETE FROM tasks WHERE task_id = ?",
                        [(task_id,) for task_id in completed_keys],
                    )
            return count

    def tasks(self) -> list[TaskSnapshot]:
        with self._lock:
            return list(self._active.values()) + list(self._completed.values())

    def serialize_tasks(
        self,
        hide_file_name: bool = False,
        include_files: bool = False,
        limit: Optional[int] = None,
    ) -> list[dict]:
        tasks = sorted(self.tasks(), key=lambda item: item.updated_at, reverse=True)
        if limit is not None:
            tasks = tasks[: max(int(limit), 0)]
        return [
            task.to_dict(hide_file_name=hide_file_name, include_files=include_files)
            for task in tasks
        ]

    def paginate_files(
        self,
        task_id: Any,
        page: int = 1,
        page_size: int = 50,
        max_page_size: int = 200,
        hide_file_name: bool = False,
    ) -> dict:
        task = self.get_task(task_id)
        safe_page = max(int(page or 1), 1)
        safe_page_size = min(max(int(page_size or 50), 1), max_page_size)
        if not task:
            return {
                "task_id": str(task_id),
                "page": safe_page,
                "page_size": safe_page_size,
                "total": 0,
                "items": [],
            }
        files = sorted(task.files.values(), key=lambda file: _sort_message_key(file.message_id))
        total = len(files)
        start = (safe_page - 1) * safe_page_size
        end = start + safe_page_size
        return {
            "task_id": task.task_id,
            "page": safe_page,
            "page_size": safe_page_size,
            "total": total,
            "items": [
                item.to_dict(hide_file_name=hide_file_name) for item in files[start:end]
            ],
        }

    def dashboard(self, hide_file_name: bool = False, limit: int = 100) -> dict:
        with self._lock:
            tasks = self.serialize_tasks(hide_file_name=hide_file_name, limit=limit)
            return {
                "active_task_count": len(self._active),
                "completed_task_count": len(self._completed),
                "tasks": tasks,
            }

    def _move_completed(self, task_key: str, task: TaskSnapshot) -> None:
        self._active.pop(task_key, None)
        self._completed[task_key] = task
        while len(self._completed) > self.recent_limit:
            oldest_key = sorted(
                self._completed,
                key=lambda key: self._completed[key].updated_at,
            )[0]
            self._completed.pop(oldest_key, None)
        self._persist_task(task)

    @staticmethod
    def _apply_updates(task: TaskSnapshot, **updates) -> None:
        for key, value in updates.items():
            if value is None:
                continue
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = _now()

    def _connect(self):
        connection = sqlite3.connect(self.storage_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_storage(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    source TEXT,
                    task_type TEXT,
                    chat_id INTEGER,
                    title TEXT,
                    status TEXT,
                    created_at REAL,
                    updated_at REAL,
                    total_count INTEGER,
                    success_count INTEGER,
                    failed_count INTEGER,
                    skipped_count INTEGER,
                    upload_success_count INTEGER,
                    workflow_type TEXT,
                    workflow_status TEXT,
                    workflow_scan_count INTEGER,
                    workflow_media_count INTEGER,
                    workflow_selected_count INTEGER,
                    workflow_summary TEXT,
                    workflow_error TEXT,
                    error TEXT,
                    needs_confirmation INTEGER
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS task_files (
                    task_id TEXT,
                    message_id TEXT,
                    status TEXT,
                    filename TEXT,
                    total_size INTEGER,
                    downloaded_size INTEGER,
                    download_speed INTEGER,
                    save_path TEXT,
                    error TEXT,
                    updated_at REAL,
                    PRIMARY KEY (task_id, message_id)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_tasks_updated_at ON tasks(updated_at)"
            )

    def _load_storage(self) -> None:
        with self._connect() as connection:
            task_rows = connection.execute("SELECT * FROM tasks").fetchall()
            file_rows = connection.execute("SELECT * FROM task_files").fetchall()

        files_by_task: dict[str, dict[str, FileSnapshot]] = {}
        for row in file_rows:
            task_files = files_by_task.setdefault(row["task_id"], {})
            task_files[row["message_id"]] = FileSnapshot(
                message_id=row["message_id"],
                status=row["status"],
                filename=row["filename"] or "",
                total_size=int(row["total_size"] or 0),
                downloaded_size=int(row["downloaded_size"] or 0),
                download_speed=int(row["download_speed"] or 0),
                save_path=row["save_path"] or "",
                error=row["error"] or "",
                updated_at=float(row["updated_at"] or _now()),
            )

        for row in task_rows:
            workflow = None
            if row["workflow_type"] or row["workflow_status"]:
                workflow = WorkflowSnapshot(
                    workflow_type=row["workflow_type"] or "",
                    status=row["workflow_status"] or "",
                    scan_count=int(row["workflow_scan_count"] or 0),
                    media_count=int(row["workflow_media_count"] or 0),
                    selected_count=int(row["workflow_selected_count"] or 0),
                    summary=row["workflow_summary"] or "",
                    error=row["workflow_error"] or "",
                )
            task = TaskSnapshot(
                task_id=row["task_id"],
                source=row["source"] or "bot",
                task_type=row["task_type"] or "unknown",
                chat_id=row["chat_id"],
                title=row["title"] or "",
                status=row["status"] or TaskStatus.CREATED,
                created_at=float(row["created_at"] or _now()),
                updated_at=float(row["updated_at"] or _now()),
                total_count=int(row["total_count"] or 0),
                success_count=int(row["success_count"] or 0),
                failed_count=int(row["failed_count"] or 0),
                skipped_count=int(row["skipped_count"] or 0),
                upload_success_count=int(row["upload_success_count"] or 0),
                workflow=workflow,
                error=row["error"] or "",
                needs_confirmation=bool(row["needs_confirmation"]),
                files=files_by_task.get(row["task_id"], {}),
            )
            if task.files:
                task.current_file = sorted(
                    task.files.values(), key=lambda item: item.updated_at, reverse=True
                )[0]
            if task.status in TERMINAL_TASK_STATUSES:
                self._completed[task.task_id] = task
            else:
                self._active[task.task_id] = task

    def _persist_task(self, task: TaskSnapshot) -> None:
        if not self.storage_path:
            return
        workflow = task.workflow or WorkflowSnapshot()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO tasks (
                    task_id, source, task_type, chat_id, title, status,
                    created_at, updated_at, total_count, success_count,
                    failed_count, skipped_count, upload_success_count,
                    workflow_type, workflow_status, workflow_scan_count,
                    workflow_media_count, workflow_selected_count,
                    workflow_summary, workflow_error, error, needs_confirmation
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    source=excluded.source,
                    task_type=excluded.task_type,
                    chat_id=excluded.chat_id,
                    title=excluded.title,
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    total_count=excluded.total_count,
                    success_count=excluded.success_count,
                    failed_count=excluded.failed_count,
                    skipped_count=excluded.skipped_count,
                    upload_success_count=excluded.upload_success_count,
                    workflow_type=excluded.workflow_type,
                    workflow_status=excluded.workflow_status,
                    workflow_scan_count=excluded.workflow_scan_count,
                    workflow_media_count=excluded.workflow_media_count,
                    workflow_selected_count=excluded.workflow_selected_count,
                    workflow_summary=excluded.workflow_summary,
                    workflow_error=excluded.workflow_error,
                    error=excluded.error,
                    needs_confirmation=excluded.needs_confirmation
                """,
                (
                    task.task_id,
                    task.source,
                    str(task.task_type),
                    task.chat_id,
                    task.title,
                    task.status,
                    task.created_at,
                    task.updated_at,
                    task.total_count,
                    task.success_count,
                    task.failed_count,
                    task.skipped_count,
                    task.upload_success_count,
                    workflow.workflow_type,
                    workflow.status,
                    workflow.scan_count,
                    workflow.media_count,
                    workflow.selected_count,
                    workflow.summary,
                    workflow.error,
                    task.error,
                    1 if task.needs_confirmation else 0,
                ),
            )

    def _persist_file(self, task_id: str, file_snapshot: FileSnapshot) -> None:
        if not self.storage_path:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO task_files (
                    task_id, message_id, status, filename, total_size,
                    downloaded_size, download_speed, save_path, error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id, message_id) DO UPDATE SET
                    status=excluded.status,
                    filename=excluded.filename,
                    total_size=excluded.total_size,
                    downloaded_size=excluded.downloaded_size,
                    download_speed=excluded.download_speed,
                    save_path=excluded.save_path,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    task_id,
                    file_snapshot.message_id,
                    file_snapshot.status,
                    file_snapshot.filename,
                    file_snapshot.total_size,
                    file_snapshot.downloaded_size,
                    file_snapshot.download_speed,
                    file_snapshot.save_path,
                    file_snapshot.error,
                    file_snapshot.updated_at,
                ),
            )


def _default_storage_path() -> Optional[Path]:
    configured = os.environ.get("TMD_TASK_DB_PATH")
    if configured:
        return Path(configured)
    return Path(os.path.abspath(".")) / "web_tasks.sqlite3"


_TASK_STORE = TaskStateStore(storage_path=_default_storage_path())


def _sort_message_key(message_id: str):
    try:
        return (0, int(message_id))
    except (TypeError, ValueError):
        return (1, str(message_id))


def get_task_store() -> TaskStateStore:
    return _TASK_STORE


def _status_from_node(node) -> str:
    failed = int(getattr(node, "failed_download_task", 0) or 0)
    total = int(
        getattr(node, "total_download_task", 0)
        or getattr(node, "total_task", 0)
        or len(getattr(node, "download_status", {}) or {})
    )
    success = int(getattr(node, "success_download_task", 0) or 0)
    skipped = int(getattr(node, "skip_download_task", 0) or 0)
    if total and success + failed + skipped >= total:
        return TaskStatus.COMPLETED_WITH_ERRORS if failed else TaskStatus.COMPLETED
    if getattr(node, "is_stop_transmission", False):
        return TaskStatus.CANCELLED
    if getattr(node, "is_running", False):
        return TaskStatus.DOWNLOADING
    return TaskStatus.QUEUED


def snapshot_node(
    node,
    source: Optional[str] = None,
    task_type: Optional[str] = None,
    title: Optional[str] = None,
) -> TaskSnapshot:
    task_id = getattr(node, "task_id", None) or f"{getattr(node, 'chat_id', 'unknown')}"
    existing = get_task_store().get_task(task_id)
    preserve_identity = bool(
        existing is not None and getattr(node, "preserve_task_identity", False)
    )
    resolved_source = (
        (existing.source if preserve_identity else None)
        or source
        or getattr(node, "task_source", None)
        or (existing.source if existing else None)
        or "bot"
    )
    resolved_type = (
        (existing.task_type if preserve_identity else None)
        or task_type
        or getattr(node, "task_display_type", None)
        or (existing.task_type if existing else None)
        or "unknown"
    )
    resolved_total_count = int(
        getattr(node, "total_download_task", 0)
        or getattr(node, "total_task", 0)
        or len(getattr(node, "download_status", {}) or {})
    )
    task = get_task_store().create_task(
        task_id=task_id,
        source=resolved_source,
        task_type=resolved_type,
        chat_id=(existing.chat_id if preserve_identity else getattr(node, "chat_id", None)),
        title=(
            existing.title
            if preserve_identity
            else title
            or getattr(node, "replay_message", "")
            or getattr(node, "file_name_tag", "")
        ),
        status=_status_from_node(node),
        total_count=(existing.total_count if preserve_identity else resolved_total_count),
        success_count=int(getattr(node, "success_download_task", 0) or 0),
        failed_count=int(getattr(node, "failed_download_task", 0) or 0),
        skipped_count=int(getattr(node, "skip_download_task", 0) or 0),
        upload_success_count=int(getattr(node, "upload_success_count", 0) or 0),
    )
    for message_id, status in (getattr(node, "download_status", {}) or {}).items():
        existing_file = task.files.get(str(message_id))
        mapped_status = _file_status_from_download_status(status)
        if (
            existing_file is not None
            and existing_file.status == FileStatus.UPLOAD_FAILED
            and mapped_status == FileStatus.DOWNLOADED
        ):
            continue
        get_task_store().upsert_file(
            task.task_id,
            message_id,
            status=mapped_status,
        )
    if task.status in TERMINAL_TASK_STATUSES:
        get_task_store().complete_task(task.task_id)
    return task


def _file_status_from_download_status(status) -> str:
    if status is DownloadStatus.SuccessDownload:
        return FileStatus.DOWNLOADED
    if status is DownloadStatus.FailedDownload:
        return FileStatus.FAILED
    if status is DownloadStatus.SkipDownload:
        return FileStatus.SKIPPED
    if (
        getattr(DownloadStatus, "Downloading", None) is not None
        and status is DownloadStatus.Downloading
    ):
        return FileStatus.DOWNLOADING
    return FileStatus.QUEUED

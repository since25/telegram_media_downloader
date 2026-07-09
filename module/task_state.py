"""In-memory Web task state snapshots."""

import os
import threading
import time
from dataclasses import dataclass, field
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

    @property
    def download_progress(self) -> float:
        if self.total_size <= 0:
            return 0.0
        return round(min(self.downloaded_size / self.total_size * 100, 100.0), 1)

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
        }
        if include_files:
            payload["files"] = [
                item.to_dict(hide_file_name)
                for item in sorted(
                    self.files.values(), key=lambda file: file.message_id
                )
            ]
        return payload


class TaskStateStore:
    """Process-local store for task snapshots."""

    def __init__(self, recent_limit: int = 200):
        self.recent_limit = recent_limit
        self._lock = threading.RLock()
        self._active: dict[str, TaskSnapshot] = {}
        self._completed: dict[str, TaskSnapshot] = {}

    def clear(self) -> None:
        with self._lock:
            self._active.clear()
            self._completed.clear()

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
            return task

    def update_task(self, task_id: Any, **updates) -> Optional[TaskSnapshot]:
        task_key = str(task_id)
        with self._lock:
            task = self._active.get(task_key) or self._completed.get(task_key)
            if not task:
                return None
            self._apply_updates(task, **updates)
            if task.status in TERMINAL_TASK_STATUSES:
                self._move_completed(task_key, task)
            return task

    def upsert_file(self, task_id: Any, message_id: Any, **updates) -> FileSnapshot:
        task_key = str(task_id)
        message_key = str(message_id)
        with self._lock:
            task = self._active.get(task_key) or self.create_task(task_key)
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

    def tasks(self) -> list[TaskSnapshot]:
        with self._lock:
            return list(self._active.values()) + list(self._completed.values())

    def serialize_tasks(
        self, hide_file_name: bool = False, include_files: bool = False
    ) -> list[dict]:
        return [
            task.to_dict(hide_file_name=hide_file_name, include_files=include_files)
            for task in sorted(
                self.tasks(), key=lambda item: item.updated_at, reverse=True
            )
        ]

    def dashboard(self, hide_file_name: bool = False) -> dict:
        with self._lock:
            tasks = self.serialize_tasks(hide_file_name=hide_file_name)
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

    @staticmethod
    def _apply_updates(task: TaskSnapshot, **updates) -> None:
        for key, value in updates.items():
            if value is None:
                continue
            if hasattr(task, key):
                setattr(task, key, value)
        task.updated_at = _now()


_TASK_STORE = TaskStateStore()


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
    task = get_task_store().create_task(
        task_id=task_id,
        source=source or getattr(node, "task_source", "bot"),
        task_type=task_type
        or getattr(node, "task_display_type", None)
        or getattr(node, "task_type", "unknown"),
        chat_id=getattr(node, "chat_id", None),
        title=title
        or getattr(node, "replay_message", "")
        or getattr(node, "file_name_tag", ""),
        status=_status_from_node(node),
        total_count=int(
            getattr(node, "total_download_task", 0)
            or getattr(node, "total_task", 0)
            or len(getattr(node, "download_status", {}) or {})
        ),
        success_count=int(getattr(node, "success_download_task", 0) or 0),
        failed_count=int(getattr(node, "failed_download_task", 0) or 0),
        skipped_count=int(getattr(node, "skip_download_task", 0) or 0),
        upload_success_count=int(getattr(node, "upload_success_count", 0) or 0),
    )
    for message_id, status in (getattr(node, "download_status", {}) or {}).items():
        get_task_store().upsert_file(
            task.task_id,
            message_id,
            status=_file_status_from_download_status(status),
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

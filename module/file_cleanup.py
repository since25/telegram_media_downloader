"""Startup reconciliation for downloader-owned local files."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from module.task_state import FileStatus


_STORAGE_METRICS_LOCK = threading.Lock()
_STORAGE_METRICS_CACHE: tuple[float, tuple[str, str], dict[str, int]] | None = None
STORAGE_METRICS_CACHE_SECONDS = 15.0


@dataclass(frozen=True)
class FileCleanupReport:
    """Counts emitted by one startup reconciliation pass."""

    temp_files_removed: int = 0
    temp_dirs_removed: int = 0
    uploaded_files_removed: int = 0
    cleanup_failures: int = 0


def _directory_metrics(root: Path) -> tuple[int, int, int]:
    """Return bytes, regular-file count, and filesystem scan failures."""

    total_bytes = 0
    file_count = 0
    failures = 0
    if not root.exists():
        return 0, 0, 0
    for current, _directories, files in os.walk(root, followlinks=False):
        for name in files:
            path = Path(current) / name
            try:
                if path.is_symlink() or not path.is_file():
                    continue
                total_bytes += path.stat().st_size
                file_count += 1
            except OSError:
                failures += 1
    return total_bytes, file_count, failures


def collect_storage_metrics(app: Any) -> dict[str, int]:
    """Return bounded disk-usage details for the Web/MCP system cards."""

    temp_root = Path(getattr(app, "temp_save_path", "temp")).expanduser().resolve()
    save_root = Path(getattr(app, "save_path", "downloads")).expanduser().resolve()
    cache_key = (str(temp_root), str(save_root))
    now = time.monotonic()
    global _STORAGE_METRICS_CACHE
    with _STORAGE_METRICS_LOCK:
        if (
            _STORAGE_METRICS_CACHE is not None
            and _STORAGE_METRICS_CACHE[1] == cache_key
            and now - _STORAGE_METRICS_CACHE[0] < STORAGE_METRICS_CACHE_SECONDS
        ):
            return dict(_STORAGE_METRICS_CACHE[2])
        temp_bytes, temp_files, temp_failures = _directory_metrics(temp_root)
        save_bytes, save_files, save_failures = _directory_metrics(save_root)
        metrics = {
            "temp_bytes": temp_bytes,
            "temp_files": temp_files,
            "save_path_bytes": save_bytes,
            "save_path_files": save_files,
            "storage_scan_failures": temp_failures + save_failures,
        }
        _STORAGE_METRICS_CACHE = (now, cache_key, metrics)
        return dict(metrics)


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root), str(candidate))) == str(root)
    except ValueError:
        return False


def _remove_temp_root(root: Path, logger: Any) -> tuple[int, int, int]:
    """Remove files left in the idle temp root and then empty directories."""

    if not root.exists():
        return 0, 0, 0
    files_removed = 0
    dirs_removed = 0
    failures = 0
    for current, directories, files in os.walk(root, topdown=False, followlinks=False):
        for name in files:
            path = Path(current) / name
            try:
                # A symlink is removed as a directory entry; its target is never
                # traversed or deleted.
                if path.is_file() or path.is_symlink():
                    path.unlink()
                    files_removed += 1
            except OSError as error:
                failures += 1
                logger.warning(f"启动清理临时文件失败: {path} ({error})")
        for name in directories:
            path = Path(current) / name
            try:
                if path.is_symlink():
                    path.unlink()
                else:
                    path.rmdir()
                dirs_removed += 1
            except OSError:
                # Non-empty directories can be left by an active external
                # process; the next startup will retry them.
                continue
    return files_removed, dirs_removed, failures


def _remove_uploaded_sources(
    save_root: Path,
    task_store: Any,
    logger: Any,
) -> tuple[int, int]:
    """Remove only persisted files already marked as uploaded."""

    removed = 0
    failures = 0
    if not save_root.exists():
        return removed, failures
    for task in task_store.tasks():
        for file_snapshot in task.files.values():
            if file_snapshot.status != FileStatus.UPLOADED:
                continue
            raw_path = str(file_snapshot.save_path or "")
            if not raw_path:
                continue
            candidate = Path(raw_path).expanduser().resolve(strict=False)
            if not _is_within(save_root, candidate) or candidate == save_root:
                failures += 1
                logger.warning(
                    f"跳过 save_path 外的已上传文件: task={task.task_id} "
                    f"path={raw_path}"
                )
                continue
            try:
                if candidate.is_file() or candidate.is_symlink():
                    candidate.unlink()
                    removed += 1
            except OSError as error:
                failures += 1
                logger.warning(
                    f"启动清理已上传文件失败: task={task.task_id} "
                    f"path={candidate} ({error})"
                )
    return removed, failures


def remove_uploaded_source(save_root: Path, raw_path: str, logger: Any) -> bool:
    """Delete one uploaded source only when it is inside the configured root."""

    root = Path(save_root).expanduser().resolve()
    candidate = Path(str(raw_path or "")).expanduser().resolve(strict=False)
    if not raw_path or candidate == root or not _is_within(root, candidate):
        logger.warning(f"跳过 save_path 外的上传源文件: {raw_path}")
        return False
    try:
        if candidate.is_file() or candidate.is_symlink():
            candidate.unlink()
        return True
    except OSError as error:
        logger.warning(f"删除已上传文件失败: {candidate} ({error})")
        return False


def reconcile_download_files(
    app: Any, task_store: Any, logger: Any
) -> FileCleanupReport:
    """Reconcile temp files and confirmed uploaded sources at process startup.

    Startup runs before download workers are created, so the temp root is idle
    and can be emptied safely. Final files are removed only when their durable
    task row says ``uploaded`` and the active upload configuration requests
    deletion. Unknown or failed files are retained for inspection or retry.
    """

    temp_root = Path(getattr(app, "temp_save_path", "temp")).expanduser().resolve()
    save_root = Path(getattr(app, "save_path", "downloads")).expanduser().resolve()
    if temp_root == save_root:
        logger.warning("跳过启动文件清理：temp_save_path 与 save_path 相同")
        return FileCleanupReport(cleanup_failures=1)

    temp_files, temp_dirs, failures = _remove_temp_root(temp_root, logger)
    cloud_config = getattr(app, "cloud_drive_config", None)
    should_remove_uploaded = bool(
        cloud_config
        and getattr(cloud_config, "enable_upload_file", False)
        and getattr(cloud_config, "after_upload_file_delete", False)
    )
    uploaded_files = 0
    if should_remove_uploaded:
        uploaded_files, uploaded_failures = _remove_uploaded_sources(
            save_root, task_store, logger
        )
        failures += uploaded_failures

    report = FileCleanupReport(
        temp_files_removed=temp_files,
        temp_dirs_removed=temp_dirs,
        uploaded_files_removed=uploaded_files,
        cleanup_failures=failures,
    )
    logger.info(
        "启动文件对账完成: "
        f"temp_files={report.temp_files_removed}, "
        f"temp_dirs={report.temp_dirs_removed}, "
        f"uploaded_files={report.uploaded_files_removed}, "
        f"failures={report.cleanup_failures}"
    )
    return report

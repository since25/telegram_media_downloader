"""Injected scan and download operations shared by process adapters."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Callable

DownloadOperation = Callable[..., Any]


@dataclass(frozen=True)
class DownloadOperations:
    """Business operations required by Web, Bot, and channel adapters."""

    scan_comment_range: DownloadOperation
    scan_post_comments: DownloadOperation
    scan_message_package: DownloadOperation
    scan_prescan_packages: DownloadOperation
    download_comments: DownloadOperation
    download_prescan_packages: DownloadOperation
    download_prepared_messages: DownloadOperation
    download_prepared_comments: DownloadOperation


_compatibility_lock = threading.RLock()
_compatibility_operations: DownloadOperations | None = None


def configure_compatibility_operations(operations: DownloadOperations) -> None:
    """Install the facade adapter used only by legacy direct module callers."""

    global _compatibility_operations
    with _compatibility_lock:
        _compatibility_operations = operations


def get_compatibility_operations() -> DownloadOperations:
    """Return configured legacy operations or fail before doing work."""

    with _compatibility_lock:
        if _compatibility_operations is None:
            raise RuntimeError("download operations have not been configured")
        return _compatibility_operations

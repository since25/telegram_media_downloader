"""Stable contracts shared by package download producers and consumers."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PackageMessageResult:
    """Terminal result for one message in one package."""

    message_id: int
    status: str
    error: str = ""


@dataclass(frozen=True)
class PackageDownloadResult:
    """Package-scoped result independent of parent task counters."""

    attempt_id: Any
    package_id: int
    status: str
    expected_message_ids: tuple[int, ...]
    message_results: dict[int, PackageMessageResult]


PackageStartedCallback = Callable[[Any, Any], Any]
PackageFinishedCallback = Callable[[Any, dict[int, PackageMessageResult]], Any]
PreparePackageCallback = Callable[[Any], Any]


class PackageCallbackError(RuntimeError):
    """A package lifecycle callback failed; raw details remain in server logs."""

    def __init__(self):
        super().__init__("callback_failed")

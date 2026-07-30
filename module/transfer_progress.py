"""Process-local progress state shared by transfer callbacks and watchdogs."""

import time
from collections.abc import Callable
from typing import Any, Optional

TransferKey = tuple[str, str, str]


def transfer_key(node: Any, message_id: Any) -> TransferKey:
    """Return the process-unique identity used for one active transfer."""

    return (
        str(getattr(node, "task_id", "") or ""),
        str(getattr(node, "chat_id", "") or ""),
        str(message_id),
    )


class TransferProgressTracker:
    """Track byte progress and watchdog cancellation for active transfers."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._last_progress_at: dict[TransferKey, float] = {}
        self._downloaded_size: dict[TransferKey, int] = {}
        self._stalled: set[TransferKey] = set()

    def start(self, key: TransferKey) -> None:
        self._last_progress_at[key] = self._clock()
        self._downloaded_size[key] = 0
        self._stalled.discard(key)

    def observe(self, key: TransferKey, downloaded_size: int) -> None:
        previous_size = self._downloaded_size.get(key, -1)
        if downloaded_size > previous_size:
            self._downloaded_size[key] = downloaded_size
            self._last_progress_at[key] = self._clock()

    def downloaded_size(self, key: TransferKey) -> int:
        return self._downloaded_size.get(key, 0)

    def last_progress_at(self, key: TransferKey) -> Optional[float]:
        return self._last_progress_at.get(key)

    def mark_stalled(self, key: TransferKey) -> None:
        self._stalled.add(key)

    def consume_stalled(self, key: TransferKey) -> bool:
        if key not in self._stalled:
            return False
        self._stalled.remove(key)
        return True

    def clear(self, key: TransferKey) -> None:
        self._last_progress_at.pop(key, None)
        self._downloaded_size.pop(key, None)
        self._stalled.discard(key)

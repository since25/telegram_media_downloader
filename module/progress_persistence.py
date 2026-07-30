"""Sample high-frequency download progress before persisting it."""

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Callable

from module.task_state import FileStatus, TaskStatus


@dataclass(frozen=True)
class _ProgressSample:
    persisted_at: float
    downloaded_size: int


class ProgressPersistence:
    """Bounded progress writer that keeps SQLite work off the event loop."""

    def __init__(
        self,
        *,
        min_interval_seconds: float = 1.0,
        min_byte_delta: int = 1024 * 1024,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.min_interval_seconds = max(float(min_interval_seconds), 0.0)
        self.min_byte_delta = max(int(min_byte_delta), 0)
        self.clock = clock
        self._samples: dict[tuple[str, str], _ProgressSample] = {}
        self._inflight: dict[tuple[str, str], threading.Event] = {}
        self._lock = threading.RLock()

    async def persist_download(
        self,
        store,
        task_id,
        message_id,
        *,
        total_count: int,
        filename: str,
        total_size: int,
        downloaded_size: int,
        download_speed: int,
        force: bool = False,
    ) -> bool:
        """Persist one useful progress sample and suppress redundant callbacks."""

        key = (str(task_id), str(message_id))
        while True:
            with self._lock:
                inflight = self._inflight.get(key)
                if inflight is None:
                    now = self.clock()
                    previous = self._samples.get(key)
                    should_persist = (
                        force
                        or previous is None
                        or now - previous.persisted_at >= self.min_interval_seconds
                        or abs(int(downloaded_size) - previous.downloaded_size)
                        >= self.min_byte_delta
                    )
                    if not should_persist:
                        return False
                    completion = threading.Event()
                    self._inflight[key] = completion
                    break
            if not force:
                return False
            await asyncio.to_thread(inflight.wait)

        try:
            await asyncio.to_thread(
                store.transition_file,
                task_id,
                message_id,
                task_updates={
                    "status": TaskStatus.DOWNLOADING,
                    "total_count": int(total_count),
                },
                file_updates={
                    "status": FileStatus.DOWNLOADING,
                    "filename": filename,
                    "save_path": filename,
                    "total_size": int(total_size),
                    "downloaded_size": int(downloaded_size),
                    "download_speed": max(int(download_speed), 0),
                },
            )
            with self._lock:
                self._samples[key] = _ProgressSample(
                    persisted_at=now,
                    downloaded_size=int(downloaded_size),
                )
        finally:
            with self._lock:
                if self._inflight.get(key) is completion:
                    self._inflight.pop(key, None)
                completion.set()
        return True

    def clear(self, task_id, message_id) -> None:
        """Forget one file after its terminal transition is persisted."""

        with self._lock:
            self._samples.pop((str(task_id), str(message_id)), None)


download_progress_persistence = ProgressPersistence()

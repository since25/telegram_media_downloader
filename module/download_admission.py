"""FIFO disk-space admission for resource-package download lifecycles."""

from __future__ import annotations

import asyncio
import shutil
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional


GIB = 1024**3
DEFAULT_MIN_FREE_DISK_BYTES = 3 * GIB


@dataclass(frozen=True)
class DiskReservationSnapshot:
    """Current state suitable for task or system-status reporting."""

    free_bytes: int
    reserved_bytes: int
    minimum_free_bytes: int
    waiting_count: int


class DiskReservation:
    """One acquired package reservation that must be released exactly once."""

    def __init__(
        self, admission: "DiskSpaceAdmission", reservation_id: str, size_bytes: int
    ) -> None:
        self._admission = admission
        self.reservation_id = reservation_id
        self.size_bytes = size_bytes
        self._released = False

    async def release(self) -> None:
        """Release this package's reserved space after its lifecycle ends."""

        if self._released:
            return
        self._released = True
        await self._admission.release(self.reservation_id)


class DiskSpaceAdmission:
    """Admit package lifecycles in FIFO order while preserving free space.

    A package reserves its full known download size before any file is queued.
    The reservation remains held until every download and upload in that package
    settles. A later package cannot bypass an earlier package waiting for disk.
    """

    def __init__(
        self,
        path: Path | str,
        minimum_free_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES,
        disk_free_bytes: Optional[Callable[[Path], int]] = None,
        poll_interval_sec: float = 1.0,
    ) -> None:
        self.path = Path(path)
        self.minimum_free_bytes = max(int(minimum_free_bytes), 0)
        self._disk_free_bytes = disk_free_bytes or self._default_disk_free_bytes
        self._poll_interval_sec = max(float(poll_interval_sec), 0.05)
        self._condition = asyncio.Condition()
        self._waiting: Deque[str] = deque()
        self._requested_bytes: dict[str, int] = {}
        self._reserved_bytes: dict[str, int] = {}

    @staticmethod
    def _default_disk_free_bytes(path: Path) -> int:
        return int(shutil.disk_usage(path).free)

    def _can_admit(self, required_bytes: int) -> bool:
        free_bytes = max(int(self._disk_free_bytes(self.path)), 0)
        reserved_bytes = sum(self._reserved_bytes.values())
        return free_bytes - reserved_bytes - required_bytes >= self.minimum_free_bytes

    async def acquire(self, reservation_id: str, size_bytes: int) -> DiskReservation:
        """Wait for this package's FIFO turn and reserve its full size."""

        key = str(reservation_id)
        required_bytes = int(size_bytes)
        if required_bytes < 0:
            raise ValueError("Reservation size cannot be negative")

        async with self._condition:
            if key in self._requested_bytes or key in self._reserved_bytes:
                raise ValueError(f"Duplicate disk reservation: {key}")
            self._waiting.append(key)
            self._requested_bytes[key] = required_bytes
            try:
                while self._waiting[0] != key or not self._can_admit(required_bytes):
                    try:
                        await asyncio.wait_for(
                            self._condition.wait(), timeout=self._poll_interval_sec
                        )
                    except asyncio.TimeoutError:
                        continue
                self._waiting.popleft()
                self._requested_bytes.pop(key, None)
                self._reserved_bytes[key] = required_bytes
                self._condition.notify_all()
            except BaseException:
                self._requested_bytes.pop(key, None)
                try:
                    self._waiting.remove(key)
                except ValueError:
                    pass
                self._condition.notify_all()
                raise
        return DiskReservation(self, key, required_bytes)

    async def release(self, reservation_id: str) -> None:
        """Release a previous reservation and wake the next FIFO waiter."""

        async with self._condition:
            self._reserved_bytes.pop(str(reservation_id), None)
            self._condition.notify_all()

    async def notify_space_changed(self) -> None:
        """Wake waiters after an external cleanup operation."""

        async with self._condition:
            self._condition.notify_all()

    async def snapshot(self) -> DiskReservationSnapshot:
        """Return a coherent admission snapshot."""

        async with self._condition:
            return DiskReservationSnapshot(
                free_bytes=max(int(self._disk_free_bytes(self.path)), 0),
                reserved_bytes=sum(self._reserved_bytes.values()),
                minimum_free_bytes=self.minimum_free_bytes,
                waiting_count=len(self._waiting),
            )

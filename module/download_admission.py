"""FIFO disk-space admission for resource-package download lifecycles."""

from __future__ import annotations

import asyncio
import shutil
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Deque, Optional


GIB = 1024**3
DEFAULT_MIN_FREE_DISK_BYTES = 3 * GIB
# 一个请求连续这么久都超出磁盘容量上限，就判定它等不到了。
# 空间可能被外部清理释放，所以不能一发现放不下就立刻判死；但也不能无限等，
# 否则队首会把整条流水线拖死（线上出现过两次，每次静默 6 小时）。
DEFAULT_CAPACITY_TIMEOUT_SEC = 600.0


class DiskCapacityExceededError(RuntimeError):
    """请求的空间在这块磁盘上永远不可能满足，等下去也没有意义。

    与「暂时排不上队」区分开：前者必须立刻失败让队列继续走，
    后者才应该继续等待其他预留释放。
    """

    def __init__(
        self, reservation_id: str, required_bytes: int, capacity_bytes: int
    ) -> None:
        super().__init__(
            f"disk capacity exceeded: {reservation_id} needs {required_bytes} bytes, "
            f"capacity is {capacity_bytes} bytes"
        )
        self.reservation_id = reservation_id
        self.required_bytes = required_bytes
        self.capacity_bytes = capacity_bytes


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
    settles.

    队列以先来后到为主，但有三条保命规则，否则整条下载流水线会被队首拖死：

    1. 队首暂时排不上时，后面放得下的包可以先走。严格 FIFO 下队首若一直放不下，
       后面的包也永远动不了，而磁盘空间只有靠下载完成才会释放 —— 没有人能下载，
       空间就永远不会出现，这是个自锁的死循环。并发等待者数量由批次调度的信号量
       限制（默认 4 个），所以队首不会被长期插队饿死。
    2. 请求量持续超过「所有预留都释放后的空间上限」达到宽限期后，抛出
       :class:`DiskCapacityExceededError`，不再无限等待一个永远不会到来的额度。
       给宽限期是因为空间可能被外部清理释放，不能一发现放不下就判死。
    3. 等待期间不持有任何锁。等待必须能被正常取消 —— 早期实现用
       ``wait_for(Condition.wait())`` 轮询，取消会卡在 ``Condition.wait()``
       重新抢锁的循环里，导致等待者既拿不到空间也杀不掉。
    """

    def __init__(
        self,
        path: Path | str,
        minimum_free_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES,
        disk_free_bytes: Optional[Callable[[Path], int]] = None,
        poll_interval_sec: float = 1.0,
        capacity_timeout_sec: float = DEFAULT_CAPACITY_TIMEOUT_SEC,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.path = Path(path)
        self.minimum_free_bytes = max(int(minimum_free_bytes), 0)
        self._disk_free_bytes = disk_free_bytes or self._default_disk_free_bytes
        self._poll_interval_sec = max(float(poll_interval_sec), 0.05)
        self._capacity_timeout_sec = max(float(capacity_timeout_sec), 0.0)
        self._clock = clock
        self._lock = asyncio.Lock()
        self._wakeup_waiters: list[asyncio.Future] = []
        self._waiting: Deque[str] = deque()
        self._requested_bytes: dict[str, int] = {}
        self._reserved_bytes: dict[str, int] = {}

    @staticmethod
    def _default_disk_free_bytes(path: Path) -> int:
        return int(shutil.disk_usage(path).free)

    def _free_bytes_now(self) -> int:
        return max(int(self._disk_free_bytes(self.path)), 0)

    def _reserved_total(self) -> int:
        return sum(self._reserved_bytes.values())

    def _can_admit(self, required_bytes: int, free_bytes: Optional[int] = None) -> bool:
        """当前额度是否放得下这个请求。"""

        if free_bytes is None:
            free_bytes = self._free_bytes_now()
        return (
            free_bytes - self._reserved_total() - required_bytes
            >= self.minimum_free_bytes
        )

    def _capacity_bytes(self, free_bytes: int) -> int:
        """所有在手预留都释放之后，这块磁盘能给出的空间上限。"""

        return free_bytes + self._reserved_total()

    def _may_admit(self, key: str, required_bytes: int, free_bytes: int) -> bool:
        """放行条件：自己放得下，且（是队首 或 队首此刻放不下）。"""

        if not self._can_admit(required_bytes, free_bytes):
            return False
        head = self._waiting[0]
        if head == key:
            return True
        return not self._can_admit(self._requested_bytes.get(head, 0), free_bytes)

    def _notify_all(self) -> None:
        """唤醒所有等待者重新评估。同步方法，调用点之间没有 await。"""

        waiters, self._wakeup_waiters = self._wakeup_waiters, []
        for waiter in waiters:
            if not waiter.done():
                waiter.set_result(None)

    def _discard(self, key: str) -> None:
        """把一个请求从账上彻底抹掉。同步且不含 await，因此是原子的。"""

        self._requested_bytes.pop(key, None)
        self._reserved_bytes.pop(key, None)
        try:
            self._waiting.remove(key)
        except ValueError:
            pass

    @staticmethod
    def _resolve_waiter(waiter: asyncio.Future) -> None:
        if not waiter.done():
            waiter.set_result(None)

    async def _wait_for_change(self) -> None:
        """等待空间变化，最多等一个轮询周期。

        两条都是踩过坑的硬约束：

        - 不持锁等待。持锁会让取消无法生效，也会把 release() 挡在门外。
        - 不用 ``asyncio.wait_for`` 做超时。超时到期时它会把外部传进来的取消
          转成 ``TimeoutError``，调用方一旦吞掉这个超时，取消就永远丢了 ——
          等待者既拿不到空间也杀不掉。这里改用定时器直接兑现 future。
        """

        loop = asyncio.get_running_loop()
        waiter = loop.create_future()
        self._wakeup_waiters.append(waiter)
        timer = loop.call_later(
            self._poll_interval_sec, self._resolve_waiter, waiter
        )
        try:
            await waiter
        finally:
            timer.cancel()
            try:
                self._wakeup_waiters.remove(waiter)
            except ValueError:
                pass

    async def acquire(self, reservation_id: str, size_bytes: int) -> DiskReservation:
        """Wait for this package's FIFO turn and reserve its full size."""

        key = str(reservation_id)
        required_bytes = int(size_bytes)
        if required_bytes < 0:
            raise ValueError("Reservation size cannot be negative")

        async with self._lock:
            if key in self._requested_bytes or key in self._reserved_bytes:
                raise ValueError(f"Duplicate disk reservation: {key}")
            self._waiting.append(key)
            self._requested_bytes[key] = required_bytes

        over_capacity_since: Optional[float] = None
        try:
            while True:
                async with self._lock:
                    free_bytes = self._free_bytes_now()
                    capacity_bytes = self._capacity_bytes(free_bytes)
                    if required_bytes + self.minimum_free_bytes > capacity_bytes:
                        # 即使把在手的预留全部释放也放不下。空间有可能被外部
                        # 清理释放，所以先给一段宽限期；一直没等到就判定等不到，
                        # 直接失败让后面的包继续走，而不是无限期堵住队列。
                        now = self._clock()
                        if over_capacity_since is None:
                            over_capacity_since = now
                        elif now - over_capacity_since >= self._capacity_timeout_sec:
                            raise DiskCapacityExceededError(
                                key, required_bytes, capacity_bytes
                            )
                    else:
                        over_capacity_since = None
                        if self._may_admit(key, required_bytes, free_bytes):
                            self._waiting.remove(key)
                            self._requested_bytes.pop(key, None)
                            self._reserved_bytes[key] = required_bytes
                            self._notify_all()
                            break
                await self._wait_for_change()
        except BaseException:
            # acquire 要么返回一个 DiskReservation，要么什么都不留下。
            # 少退这一步，被取消的预留就会一直占着额度直到进程重启。
            # 这里不再去抢锁：取消进行中抢锁可能又被取消，而这段清理没有
            # await，在单线程事件循环里本来就是原子的。
            self._discard(key)
            self._notify_all()
            raise
        return DiskReservation(self, key, required_bytes)

    async def release(self, reservation_id: str) -> None:
        """Release a previous reservation and wake the next FIFO waiter."""

        async with self._lock:
            self._reserved_bytes.pop(str(reservation_id), None)
            self._notify_all()

    async def notify_space_changed(self) -> None:
        """Wake waiters after an external cleanup operation."""

        async with self._lock:
            self._notify_all()

    async def snapshot(self) -> DiskReservationSnapshot:
        """Return a coherent admission snapshot."""

        async with self._lock:
            return DiskReservationSnapshot(
                free_bytes=self._free_bytes_now(),
                reserved_bytes=self._reserved_total(),
                minimum_free_bytes=self.minimum_free_bytes,
                waiting_count=len(self._waiting),
            )

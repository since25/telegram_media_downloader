import asyncio

import pytest

from module.download_admission import (
    DiskCapacityExceededError,
    DiskSpaceAdmission,
    GIB,
)


def test_reservations_are_admitted_in_fifo_order(tmp_path):
    async def scenario():
        free_bytes = 14 * GIB
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: free_bytes,
            poll_interval_sec=0.01,
        )
        order = []
        first = await admission.acquire("first", 10 * GIB)

        async def wait_for_second():
            reservation = await admission.acquire("second", 10 * GIB)
            order.append("second")
            return reservation

        async def wait_for_third():
            reservation = await admission.acquire("third", 2 * GIB)
            order.append("third")
            return reservation

        second_task = asyncio.create_task(wait_for_second())
        third_task = asyncio.create_task(wait_for_third())
        await asyncio.sleep(0)
        assert order == []

        await first.release()
        second = await asyncio.wait_for(second_task, timeout=1)
        assert order == ["second"]
        assert not third_task.done()

        await second.release()
        third = await asyncio.wait_for(third_task, timeout=1)
        await third.release()
        assert order == ["second", "third"]

    asyncio.run(scenario())


def test_waiter_starts_after_external_space_cleanup(tmp_path):
    async def scenario():
        free_bytes = 12 * GIB
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: free_bytes,
            poll_interval_sec=60,
        )
        waiting = asyncio.create_task(admission.acquire("package", 10 * GIB))
        await asyncio.sleep(0)
        assert not waiting.done()

        free_bytes = 13 * GIB
        await admission.notify_space_changed()
        reservation = await asyncio.wait_for(waiting, timeout=1)
        snapshot = await admission.snapshot()
        assert snapshot.reserved_bytes == 10 * GIB
        await reservation.release()

    asyncio.run(scenario())


def test_a_blocked_head_does_not_stall_smaller_packages(tmp_path):
    """队首放不下时，后面放得下的包必须能先走。

    线上就是栽在这里：队首等的空间只有靠别人下载完成才会出现，
    而后面的人全被它挡住 —— 谁都动不了，空间永远不会出现。
    """

    async def scenario():
        now = [0.0]
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: 4 * GIB,
            poll_interval_sec=0.01,
            capacity_timeout_sec=60,
            clock=lambda: now[0],
        )
        blocked_head = asyncio.create_task(admission.acquire("head", 2 * GIB))
        try:
            await asyncio.sleep(0.05)
            assert not blocked_head.done()

            small = await asyncio.wait_for(
                admission.acquire("small", 512 * 1024 * 1024), timeout=1
            )
            assert not blocked_head.done()
            await small.release()
        finally:
            # 推进时钟让还卡着的等待者走容量超时退出，
            # 避免用例失败时把整个测试进程挂死
            now[0] = 1e9
            await asyncio.gather(blocked_head, return_exceptions=True)

    asyncio.run(scenario())


def test_head_still_wins_when_it_fits(tmp_path):
    """队首放得下时不允许被插队，先来后到的语义必须保住。"""

    async def scenario():
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: 10 * GIB,
            poll_interval_sec=0.01,
        )
        holder = await admission.acquire("holder", 6 * GIB)

        order = []

        async def queue_up(name, size):
            reservation = await admission.acquire(name, size)
            order.append(name)
            return reservation

        head = asyncio.create_task(queue_up("head", 3 * GIB))
        await asyncio.sleep(0)
        later = asyncio.create_task(queue_up("later", 5 * GIB))
        await asyncio.sleep(0.05)
        assert order == []

        # 释放后额度只够队首，队首必须先拿到
        await holder.release()
        first = await asyncio.wait_for(head, timeout=1)
        await asyncio.sleep(0.05)
        assert order == ["head"]
        assert not later.done()

        await first.release()
        second = await asyncio.wait_for(later, timeout=1)
        await second.release()
        assert order == ["head", "later"]

    asyncio.run(scenario())


def test_request_beyond_disk_capacity_fails_after_grace_period(tmp_path):
    """超出磁盘容量上限的请求要在宽限期后失败，而不是无限等待。"""

    async def scenario():
        now = [0.0]
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: 5 * GIB,
            poll_interval_sec=0.01,
            capacity_timeout_sec=60,
            clock=lambda: now[0],
        )
        waiting = asyncio.create_task(admission.acquire("oversized", 10 * GIB))
        await asyncio.sleep(0.05)
        assert not waiting.done(), "宽限期内不应该立刻失败"

        now[0] = 61.0
        with pytest.raises(DiskCapacityExceededError):
            await asyncio.wait_for(waiting, timeout=1)

        snapshot = await admission.snapshot()
        assert snapshot.reserved_bytes == 0
        assert snapshot.waiting_count == 0

    asyncio.run(scenario())


def test_capacity_grace_period_resets_when_space_appears(tmp_path):
    """宽限期内空间被外部清理释放出来，就该正常放行而不是判死。"""

    async def scenario():
        now = [0.0]
        free_bytes = 5 * GIB
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: free_bytes,
            poll_interval_sec=0.01,
            capacity_timeout_sec=60,
            clock=lambda: now[0],
        )
        waiting = asyncio.create_task(admission.acquire("oversized", 10 * GIB))
        await asyncio.sleep(0.05)

        now[0] = 59.0
        free_bytes = 20 * GIB
        reservation = await asyncio.wait_for(waiting, timeout=1)
        assert reservation.size_bytes == 10 * GIB
        await reservation.release()

    asyncio.run(scenario())


def test_cancelled_acquire_leaves_no_reservation_behind(tmp_path):
    """acquire 要么返回预留，要么什么都不留下。

    少退这一步，被取消的预留就会一直占着额度直到进程重启，
    让后续每个包都更难排上队。
    """

    async def scenario():
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: 4 * GIB,
            poll_interval_sec=0.01,
        )
        waiting = asyncio.create_task(admission.acquire("cancelled", 3 * GIB))
        await asyncio.sleep(0.05)
        waiting.cancel()
        await asyncio.gather(waiting, return_exceptions=True)

        snapshot = await admission.snapshot()
        assert snapshot.reserved_bytes == 0
        assert snapshot.waiting_count == 0

    asyncio.run(scenario())


def test_failure_after_registration_releases_the_reservation(tmp_path):
    """预留登记之后才出错，也不能把这笔预留留在账上。"""

    async def scenario():
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: 100 * GIB,
            poll_interval_sec=0.01,
        )
        real_notify = admission._notify_all
        armed = [True]

        def exploding_notify():
            if armed[0]:
                armed[0] = False
                raise RuntimeError("wakeup failed right after registration")
            return real_notify()

        admission._notify_all = exploding_notify
        with pytest.raises(RuntimeError):
            await admission.acquire("doomed", 5 * GIB)
        admission._notify_all = real_notify

        snapshot = await admission.snapshot()
        assert snapshot.reserved_bytes == 0
        assert snapshot.waiting_count == 0

    asyncio.run(scenario())


def test_a_waiting_acquire_can_actually_be_cancelled(tmp_path):
    """等待中的请求必须能被取消掉。

    线上就是死在这一点：批次 6 小时超时发出的取消根本杀不掉等待者。
    早期实现用 ``wait_for(Condition.wait())`` 轮询，超时会把取消吞掉，
    等待者既拿不到空间也退不出来，整个进程只能靠重启恢复。
    """

    async def scenario():
        now = [0.0]
        admission = DiskSpaceAdmission(
            tmp_path,
            minimum_free_bytes=3 * GIB,
            disk_free_bytes=lambda _path: 4 * GIB,
            poll_interval_sec=0.01,
            capacity_timeout_sec=60,
            clock=lambda: now[0],
        )
        waiting = asyncio.create_task(admission.acquire("stuck", 3 * GIB))
        try:
            await asyncio.sleep(0.1)
            assert not waiting.done()

            waiting.cancel()
            done, pending = await asyncio.wait({waiting}, timeout=2)
            assert done and not pending, "取消没有生效：等待者杀不掉"
            assert waiting.cancelled()
        finally:
            now[0] = 1e9
            await asyncio.gather(waiting, return_exceptions=True)

    asyncio.run(scenario())

import asyncio

from module.download_admission import DiskSpaceAdmission, GIB


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

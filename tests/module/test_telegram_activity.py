"""Tests for Telegram download-priority activity coordination."""

import asyncio
from functools import wraps

import pytest

from module.telegram_activity import TelegramActivityGate


def async_test(test):
    """Run an async test without requiring a pytest event-loop plugin."""

    @wraps(test)
    def run_test():
        asyncio.run(test())

    return run_test


@async_test
async def test_waiting_download_blocks_next_scan_batch():
    gate = TelegramActivityGate()
    first_scan = await gate.acquire_scan()
    waiting_download = asyncio.create_task(gate.acquire_download())
    await asyncio.sleep(0)
    second_scan = asyncio.create_task(gate.acquire_scan())

    first_scan.release()
    download = await asyncio.wait_for(waiting_download, 1)
    assert not second_scan.done()

    download.release()
    scan = await asyncio.wait_for(second_scan, 1)
    scan.release()
    await gate.wait_until_idle()


@async_test
async def test_multiple_downloads_coexist_while_scans_are_exclusive():
    gate = TelegramActivityGate()
    first_download, second_download = await asyncio.gather(
        gate.acquire_download(), gate.acquire_download()
    )
    waiting_scan = asyncio.create_task(gate.acquire_scan())
    await asyncio.sleep(0)

    assert not waiting_scan.done()
    first_download.release()
    await asyncio.sleep(0)
    assert not waiting_scan.done()

    second_download.release()
    first_scan = await asyncio.wait_for(waiting_scan, 1)
    second_scan = asyncio.create_task(gate.acquire_scan())
    await asyncio.sleep(0)
    assert not second_scan.done()

    first_scan.release()
    next_scan = await asyncio.wait_for(second_scan, 1)
    next_scan.release()
    await gate.wait_until_idle()


@async_test
async def test_cancelled_waiting_download_releases_its_priority_intent():
    gate = TelegramActivityGate()
    scan = await gate.acquire_scan()
    waiting_download = asyncio.create_task(gate.acquire_download())
    await asyncio.sleep(0)

    waiting_download.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting_download

    scan.release()
    next_scan = await asyncio.wait_for(gate.acquire_scan(), 1)
    next_scan.release()
    await gate.wait_until_idle()


@async_test
async def test_registered_download_cancelled_before_worker_does_not_block_scan():
    gate = TelegramActivityGate()
    intent = await gate.register_download_intent()

    intent.cancel()

    scan = await asyncio.wait_for(gate.acquire_scan(), 1)
    scan.release()
    await gate.wait_until_idle()


@async_test
async def test_download_context_releases_after_body_cancellation():
    gate = TelegramActivityGate()
    entered = asyncio.Event()

    async def use_download_permit():
        async with gate.download_permit():
            entered.set()
            await asyncio.Future()

    task = asyncio.create_task(use_download_permit())
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    scan = await asyncio.wait_for(gate.acquire_scan(), 1)
    scan.release()
    await gate.wait_until_idle()


@async_test
async def test_release_and_wait_finishes_counter_transition_once():
    gate = TelegramActivityGate()
    download = await gate.acquire_download()
    acquisition_order = []

    async def acquire_waiting_scan():
        permit = await gate.acquire_scan()
        acquisition_order.append("scan")
        return permit

    waiting_scan = asyncio.create_task(acquire_waiting_scan())
    await asyncio.sleep(0)

    download.release()
    await download.release_and_wait()
    acquisition_order.append("release-complete")
    await download.release_and_wait()

    assert acquisition_order == ["scan", "release-complete"]
    scan = await asyncio.wait_for(waiting_scan, 1)
    scan.release()
    await gate.wait_until_idle()


@async_test
async def test_download_only_observation_and_wait_ignore_scan_state():
    gate = TelegramActivityGate()
    scan = await gate.acquire_scan()

    assert await gate.has_download_activity() is False
    await asyncio.wait_for(gate.wait_until_downloads_idle(), 1)

    waiting_download = asyncio.create_task(gate.acquire_download())
    await asyncio.sleep(0)
    assert await gate.has_download_activity() is True
    waiting_for_downloads = asyncio.create_task(gate.wait_until_downloads_idle())
    await asyncio.sleep(0)
    assert not waiting_for_downloads.done()

    scan.release()
    download = await asyncio.wait_for(waiting_download, 1)
    await download.release_and_wait()
    await asyncio.wait_for(waiting_for_downloads, 1)
    await gate.wait_until_idle()


def test_gate_rejects_acquisition_from_a_second_event_loop():
    gate = TelegramActivityGate()

    async def use_first_loop():
        permit = await gate.acquire_scan()
        permit.release()
        await gate.wait_until_idle()

    asyncio.run(use_first_loop())

    with pytest.raises(RuntimeError, match="event loop"):
        asyncio.run(gate.acquire_scan())

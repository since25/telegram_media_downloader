import asyncio
import threading

import pytest


def _running_loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    return loop, thread


def _stop_loop(loop, thread):
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    try:
        if asyncio.get_event_loop() is loop:
            asyncio.set_event_loop(None)
    except RuntimeError:
        pass
    loop.close()


def test_submit_runs_coroutine_on_owner_loop_thread():
    from module.web_commands import submit_web_coroutine

    loop, thread = _running_loop()
    caller_thread = threading.get_ident()

    async def owner_thread_id():
        return threading.get_ident()

    try:
        future = submit_web_coroutine(loop, owner_thread_id())
        result_thread = future.result(timeout=1)
    finally:
        _stop_loop(loop, thread)

    assert result_thread != caller_thread


def test_unavailable_loop_closes_coroutine():
    from module.web_commands import submit_web_coroutine

    loop = asyncio.new_event_loop()
    loop.close()

    async def never_started():
        return None

    coroutine = never_started()
    with pytest.raises(RuntimeError, match="not available"):
        submit_web_coroutine(loop, coroutine)

    assert coroutine.cr_frame is None


def test_bounded_wait_times_out_without_cancelling_owner_work():
    from module.web_commands import WebCommandTimeout, wait_for_web_command

    loop, thread = _running_loop()
    release = threading.Event()

    async def blocked():
        await asyncio.to_thread(release.wait)
        return "done"

    try:
        future = asyncio.run_coroutine_threadsafe(blocked(), loop)
        with pytest.raises(WebCommandTimeout):
            wait_for_web_command(future, timeout=0.01)
        assert future.cancelled() is False
        release.set()
        assert wait_for_web_command(future, timeout=1) == "done"
    finally:
        release.set()
        _stop_loop(loop, thread)


def test_owner_exception_is_propagated():
    from module.web_commands import wait_for_web_command

    loop, thread = _running_loop()

    async def fail():
        raise ValueError("owner failed")

    try:
        future = asyncio.run_coroutine_threadsafe(fail(), loop)
        with pytest.raises(ValueError, match="owner failed"):
            wait_for_web_command(future, timeout=1)
    finally:
        _stop_loop(loop, thread)

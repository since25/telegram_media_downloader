"""Thread-safe command submission from Flask into the application loop."""

import asyncio
import concurrent.futures


class WebCommandTimeout(RuntimeError):
    """An accepted owner-loop command did not finish within the HTTP wait bound."""


def submit_web_coroutine(loop, coroutine) -> concurrent.futures.Future:
    """Submit one coroutine to the running application loop."""

    if (
        loop is None
        or getattr(loop, "is_closed", lambda: False)()
        or not loop.is_running()
    ):
        coroutine.close()
        raise RuntimeError("application loop is not available")
    try:
        return asyncio.run_coroutine_threadsafe(coroutine, loop)
    except Exception:
        coroutine.close()
        raise


def wait_for_web_command(future, *, timeout: float):
    """Wait without cancelling accepted owner-loop work on HTTP timeout."""

    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as error:
        raise WebCommandTimeout("owner-loop command timed out") from error

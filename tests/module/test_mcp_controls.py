"""Pause, resume, and cancel over MCP are explicit and owner-loop bound."""

import asyncio
import threading

import pytest

from tests.module.test_mcp_packages import auth, env  # noqa: F401

from module.download_stat import DownloadState, get_download_state, set_download_state


@pytest.fixture(autouse=True)
def running_owner_loop(env):
    loop = env.app.loop
    started = threading.Event()

    def run_loop():
        asyncio.set_event_loop(loop)
        started.set()
        loop.run_forever()

    thread = threading.Thread(target=run_loop)
    thread.start()
    assert started.wait(timeout=1)
    try:
        yield
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)


def test_pause_is_idempotent_and_does_not_toggle(env):
    set_download_state(DownloadState.Downloading)

    first = env.client.post("/api/mcp/downloads/pause", headers=auth())
    second = env.client.post("/api/mcp/downloads/pause", headers=auth())

    assert first.get_json()["download_state"] == DownloadState.StopDownload.name
    assert second.get_json()["download_state"] == DownloadState.StopDownload.name
    assert get_download_state() is DownloadState.StopDownload


def test_resume_returns_the_resulting_state(env):
    set_download_state(DownloadState.StopDownload)

    response = env.client.post("/api/mcp/downloads/resume", headers=auth())

    assert response.get_json()["download_state"] == DownloadState.Downloading.name


def test_cancel_unknown_task_returns_not_found(env):
    response = env.client.post("/api/mcp/tasks/missing/cancel", headers=auth())

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "not_found"

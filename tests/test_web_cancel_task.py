"""Cancel must never leave a task permanently stuck.

Guardrails covered:
- an orphaned `waiting_confirmation` task (no matching preview/prescan entry,
  e.g. because a service restart wiped the in-memory dicts) is discarded
  entirely rather than 404ing forever.
- an actively downloading task with a live node is stopped and kept visible
  as cancelled.
- cancelling an unknown task id still 404s.
"""
import asyncio
import threading
from types import SimpleNamespace
from unittest import mock

import pytest

import module.web as web
from module.task_state import TaskStatus, get_task_store


def _complete_web_command(_loop, coroutine):
    future = asyncio.run(coroutine)
    completed = mock.Mock()
    completed.result.return_value = future
    return completed


@pytest.fixture
def client():
    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = True
    try:
        with app.test_client() as test_client:
            token = test_client.get("/api/csrf-token").get_json()["csrf_token"]
            test_client.environ_base["HTTP_X_CSRF_TOKEN"] = token
            yield test_client
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled
        web._pending_web_task_previews.clear()
        web._pending_web_prescans.clear()
        web._scanning_web_task_nodes.clear()
        get_task_store().clear()


def test_cancel_orphaned_waiting_confirmation_task_removes_it(client):
    task_id = "web-orphan-1"
    get_task_store().create_task(
        task_id,
        source="web",
        task_type="package",
        status=TaskStatus.WAITING_CONFIRMATION,
        needs_confirmation=True,
    )
    # No entry in _pending_web_task_previews / _pending_web_prescans: simulates
    # a service restart wiping the in-memory dicts while the task persisted.

    response = client.post(f"/api/tasks/{task_id}/cancel")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body.get("removed") is True
    assert get_task_store().get_task(task_id) is None


def test_cancel_downloading_task_with_active_node_stays_cancelled(monkeypatch, client):
    task_id = "web-dl-1"
    node = mock.Mock()
    get_task_store().create_task(
        task_id,
        source="web",
        task_type="package",
        status=TaskStatus.DOWNLOADING,
    )
    monkeypatch.setattr(web, "get_active_task_nodes", lambda: {task_id: node})
    monkeypatch.setattr(web, "submit_web_coroutine", _complete_web_command)
    monkeypatch.setattr(
        web,
        "_current_app",
        SimpleNamespace(loop=object(), channel_library_service=None),
    )

    response = client.post(f"/api/tasks/{task_id}/cancel")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["status"] == TaskStatus.CANCELLED
    node.stop_transmission.assert_called_once()
    task = get_task_store().get_task(task_id)
    assert task is not None
    assert task.status == TaskStatus.CANCELLED


def test_cancel_active_web_task_mutates_node_on_owner_loop(monkeypatch, client):
    task_id = "web-owned-cancel"
    loop = asyncio.new_event_loop()
    loop_started = threading.Event()

    def run_loop():
        asyncio.set_event_loop(loop)
        loop_started.set()
        loop.run_forever()

    owner_thread = threading.Thread(target=run_loop)
    owner_thread.start()
    loop_started.wait(timeout=1)

    class ThreadTrackingNode:
        def __init__(self):
            self.cancel_thread_id = None

        def stop_transmission(self):
            self.cancel_thread_id = threading.get_ident()

    node = ThreadTrackingNode()
    get_task_store().create_task(
        task_id,
        source="web",
        task_type="package",
        status=TaskStatus.DOWNLOADING,
    )
    monkeypatch.setattr(
        web,
        "_current_app",
        SimpleNamespace(loop=loop, channel_library_service=None),
    )
    monkeypatch.setattr(web, "get_active_task_nodes", lambda: {task_id: node})

    try:
        response = client.post(f"/api/tasks/{task_id}/cancel")
    finally:
        loop.call_soon_threadsafe(loop.stop)
        owner_thread.join(timeout=2)
        loop.close()

    assert response.status_code == 200
    assert node.cancel_thread_id == owner_thread.ident


def test_cancel_unknown_task_returns_404(client):
    response = client.post("/api/tasks/does-not-exist/cancel")

    assert response.status_code == 404
    body = response.get_json()
    assert body["ok"] is False


def test_cancel_active_task_without_runtime_handle_reports_conflict(client):
    task_id = "web-missing-runtime-handle"
    get_task_store().create_task(
        task_id,
        source="web",
        task_type="package",
        status=TaskStatus.DOWNLOADING,
    )

    response = client.post(f"/api/tasks/{task_id}/cancel")

    assert response.status_code == 409
    assert response.get_json() == {
        "ok": False,
        "error": "runtime handle is unavailable",
        "error_code": "runtime_handle_missing",
    }
    task = get_task_store().get_task(task_id)
    assert task is not None
    assert task.status == TaskStatus.DOWNLOADING


def test_confirm_orphaned_waiting_task_is_closed_as_restart_interrupted(client):
    task_id = "web-orphan-confirm"
    get_task_store().create_task(
        task_id,
        source="web",
        task_type="package",
        status=TaskStatus.WAITING_CONFIRMATION,
        needs_confirmation=True,
    )

    response = client.post(f"/api/tasks/{task_id}/confirm")

    assert response.status_code == 409
    body = response.get_json()
    assert body["ok"] is False
    assert body["error"] == "restart_interrupted"
    task = get_task_store().get_task(task_id)
    assert task.status == TaskStatus.FAILED
    assert task.error == "restart_interrupted"
    assert task.needs_confirmation is False

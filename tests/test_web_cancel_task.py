"""Cancel must never leave a task permanently stuck.

Guardrails covered:
- an orphaned `waiting_confirmation` task (no matching preview/prescan entry,
  e.g. because a service restart wiped the in-memory dicts) is discarded
  entirely rather than 404ing forever.
- an actively downloading task with a live node is stopped and kept visible
  as cancelled.
- cancelling an unknown task id still 404s.
"""
from unittest import mock

import pytest

import module.web as web
from module.task_state import TaskStatus, get_task_store


@pytest.fixture
def client():
    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = True
    try:
        with app.test_client() as test_client:
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

    response = client.post(f"/api/tasks/{task_id}/cancel")

    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["status"] == TaskStatus.CANCELLED
    node.stop_transmission.assert_called_once()
    task = get_task_store().get_task(task_id)
    assert task is not None
    assert task.status == TaskStatus.CANCELLED


def test_cancel_unknown_task_returns_404(client):
    response = client.post("/api/tasks/does-not-exist/cancel")

    assert response.status_code == 404
    body = response.get_json()
    assert body["ok"] is False

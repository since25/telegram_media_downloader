"""Prescan package state must survive confirm so the download detail stays populated.

Guardrails covered:
- confirm keeps the prescan entry (packages endpoint stays 200 during download).
- confirm with no packages selected still returns 400 and leaves the prescan pending.
- a RuntimeError during confirm still rolls back to a not-confirmed, cancellable state.
- cancel still pops the prescan entirely.
- clear (single + clear-completed) still drops any retained prescan entry.
"""
import json
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
        web._pending_web_prescans.clear()
        get_task_store().clear()


def _make_prescan(selected_ids=None):
    pkg = mock.Mock(
        package_id=1, title="pkg", start_message_id=1, end_message_id=9, media_count=3
    )
    pkg.size_summary = mock.Mock(known_total_size=1000)
    return {
        "packages": [pkg],
        "selected_package_ids": set(selected_ids or ()),
        "node": mock.Mock(),
        "task_type": "prescan",
    }


def test_packages_available_after_confirm(monkeypatch, client):
    task_id = "prescan-1"
    web._pending_web_prescans[task_id] = _make_prescan({1})
    get_task_store().create_task(task_id, status=TaskStatus.WAITING_CONFIRMATION)
    monkeypatch.setattr(web, "_active_app", lambda: mock.Mock(hide_file_name=False))
    monkeypatch.setattr(web, "_schedule_web_coroutine", lambda app, coro: coro.close())
    monkeypatch.setattr(
        web,
        "_run_confirmed_prescan_download",
        lambda prescan: mock.Mock(close=lambda: None),
    )

    confirm = client.post(f"/api/tasks/{task_id}/confirm")
    packages = client.get(f"/api/prescans/{task_id}/packages")

    assert confirm.status_code == 200
    assert packages.status_code == 200, "packages must remain after confirm"
    body = json.loads(packages.data)
    assert body["total"] == 1
    assert body["items"][0]["selected"] is True
    assert task_id in web._pending_web_prescans
    assert web._pending_web_prescans[task_id].get("confirmed") is True


def test_confirm_without_selection_returns_400_and_keeps_prescan_pending(
    monkeypatch, client
):
    task_id = "prescan-2"
    web._pending_web_prescans[task_id] = _make_prescan()
    get_task_store().create_task(task_id, status=TaskStatus.WAITING_CONFIRMATION)
    monkeypatch.setattr(web, "_active_app", lambda: mock.Mock(hide_file_name=False))

    confirm = client.post(f"/api/tasks/{task_id}/confirm")
    packages = client.get(f"/api/prescans/{task_id}/packages")

    assert confirm.status_code == 400
    assert "select at least one package" in confirm.get_json()["error"]
    assert packages.status_code == 200
    assert web._pending_web_prescans[task_id].get("confirmed") is not True


def test_confirm_rollback_on_runtime_error_keeps_prescan_cancellable(
    monkeypatch, client
):
    task_id = "prescan-3"
    web._pending_web_prescans[task_id] = _make_prescan({1})
    get_task_store().create_task(task_id, status=TaskStatus.WAITING_CONFIRMATION)
    monkeypatch.setattr(web, "_active_app", lambda: mock.Mock(hide_file_name=False))

    def _boom(prescan):
        raise RuntimeError("application loop is not available")

    monkeypatch.setattr(web, "_run_confirmed_prescan_download", _boom)

    confirm = client.post(f"/api/tasks/{task_id}/confirm")
    assert confirm.status_code == 503
    assert web._pending_web_prescans[task_id].get("confirmed") is not True

    cancel = client.post(f"/api/tasks/{task_id}/cancel")
    assert cancel.status_code == 200
    assert task_id not in web._pending_web_prescans


def test_cancel_removes_pending_prescan(client):
    task_id = "prescan-4"
    web._pending_web_prescans[task_id] = _make_prescan()

    cancel = client.post(f"/api/tasks/{task_id}/cancel")
    packages = client.get(f"/api/prescans/{task_id}/packages")

    assert cancel.status_code == 200
    assert task_id not in web._pending_web_prescans
    assert packages.status_code == 404


def test_clear_terminal_task_removes_confirmed_prescan(monkeypatch, client):
    task_id = "prescan-5"
    web._pending_web_prescans[task_id] = _make_prescan({1})
    monkeypatch.setattr(web, "_active_app", lambda: mock.Mock(hide_file_name=False))
    monkeypatch.setattr(web, "_schedule_web_coroutine", lambda app, coro: coro.close())
    monkeypatch.setattr(
        web,
        "_run_confirmed_prescan_download",
        lambda prescan: mock.Mock(close=lambda: None),
    )
    client.post(f"/api/tasks/{task_id}/confirm")
    get_task_store().create_task(task_id, status=TaskStatus.COMPLETED)
    get_task_store().update_task(task_id, status=TaskStatus.COMPLETED)

    clear = client.post(f"/api/tasks/{task_id}/clear")
    packages = client.get(f"/api/prescans/{task_id}/packages")

    assert clear.status_code == 200
    assert task_id not in web._pending_web_prescans
    assert packages.status_code == 404


def test_clear_completed_removes_confirmed_prescan(monkeypatch, client):
    task_id = "prescan-6"
    web._pending_web_prescans[task_id] = _make_prescan({1})
    monkeypatch.setattr(web, "_active_app", lambda: mock.Mock(hide_file_name=False))
    monkeypatch.setattr(web, "_schedule_web_coroutine", lambda app, coro: coro.close())
    monkeypatch.setattr(
        web,
        "_run_confirmed_prescan_download",
        lambda prescan: mock.Mock(close=lambda: None),
    )
    client.post(f"/api/tasks/{task_id}/confirm")
    get_task_store().create_task(task_id, status=TaskStatus.COMPLETED)
    get_task_store().update_task(task_id, status=TaskStatus.COMPLETED)

    clear_completed = client.post("/api/tasks/clear-completed")
    packages = client.get(f"/api/prescans/{task_id}/packages")

    assert clear_completed.status_code == 200
    assert task_id not in web._pending_web_prescans
    assert packages.status_code == 404


def test_prune_orphaned_prescans_drops_entries_whose_task_is_gone(client):
    """A retained prescan entry must not outlive its task in the store.

    The task store LRU-evicts old completed tasks once `_completed` exceeds
    `recent_limit`. If a confirmed prescan's task is evicted that way before
    the user clears it, `_pending_web_prescans[task_id]` would otherwise
    orphan forever (unbounded memory growth). `_prune_orphaned_prescans`
    reconciles the dict against the store: entries whose task still exists
    (active or completed) survive; entries whose task is gone are dropped.
    """
    live_task_id = "prescan-live"
    orphaned_task_id = "prescan-orphaned"
    web._pending_web_prescans[live_task_id] = _make_prescan({1})
    web._pending_web_prescans[orphaned_task_id] = _make_prescan({1})
    get_task_store().create_task(live_task_id, status=TaskStatus.COMPLETED)
    get_task_store().update_task(live_task_id, status=TaskStatus.COMPLETED)
    # orphaned_task_id has no matching task in the store: simulates eviction.

    web._prune_orphaned_prescans()

    assert live_task_id in web._pending_web_prescans
    assert orphaned_task_id not in web._pending_web_prescans


def test_confirm_prunes_orphaned_prescans_from_other_tasks(monkeypatch, client):
    """confirm_task reconciles the whole dict, not just the task being confirmed."""
    orphaned_task_id = "prescan-orphaned-2"
    web._pending_web_prescans[orphaned_task_id] = _make_prescan({1})

    task_id = "prescan-7"
    web._pending_web_prescans[task_id] = _make_prescan({1})
    monkeypatch.setattr(web, "_active_app", lambda: mock.Mock(hide_file_name=False))
    monkeypatch.setattr(web, "_schedule_web_coroutine", lambda app, coro: coro.close())
    monkeypatch.setattr(
        web,
        "_run_confirmed_prescan_download",
        lambda prescan: mock.Mock(close=lambda: None),
    )
    get_task_store().create_task(task_id, status=TaskStatus.WAITING_CONFIRMATION)

    confirm = client.post(f"/api/tasks/{task_id}/confirm")

    assert confirm.status_code == 200
    assert orphaned_task_id not in web._pending_web_prescans
    assert task_id in web._pending_web_prescans

"""Tests for clearing completed entries from the Files page download cache.

Guardrails covered:
- POST /clear_download_list removes only fully-downloaded entries from
  module.download_stat's _download_result (the store backing
  GET /get_download_list?already_down=true on the Files page).
- in-progress entries (down_byte < total_size) are preserved.
- the JSON response reports the correct cleared count.
"""
from types import SimpleNamespace

import pytest

import module.web as web
from module.download_stat import (
    get_download_result,
    record_download_result,
    reset_download_runtime_state_for_tests,
)


@pytest.fixture
def client():
    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = True
    reset_download_runtime_state_for_tests()
    try:
        with app.test_client() as test_client:
            token = test_client.get("/api/csrf-token").get_json()["csrf_token"]
            test_client.environ_base["HTTP_X_CSRF_TOKEN"] = token
            yield test_client
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled
        reset_download_runtime_state_for_tests()


def _record(task_id, chat_id, message_id, down_byte, total_size, file_name):
    node = SimpleNamespace(task_id=task_id, chat_id=chat_id)
    record_download_result(
        node,
        message_id,
        downloaded_size=down_byte,
        total_size=total_size,
        file_name=file_name,
        start_time=0.0,
    )


def test_clear_download_list_removes_only_completed(client):
    _record("task-1", 100, 1, 1000, 1000, "done.mp4")
    _record("task-1", 100, 2, 500, 1000, "in_progress.mp4")

    response = client.post("/clear_download_list")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "cleared": 1}
    download_result = get_download_result()
    assert ("task-1", "100", "1") not in download_result
    assert download_result[("task-1", "100", "2")]["down_byte"] == 500


def test_clear_download_list_drops_empty_chat_bucket(client):
    _record("task-2", 200, 1, 2000, 2000, "solo.mp4")

    response = client.post("/clear_download_list")

    assert response.get_json() == {"ok": True, "cleared": 1}
    assert get_download_result() == {}

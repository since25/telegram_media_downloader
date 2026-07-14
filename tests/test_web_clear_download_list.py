"""Tests for clearing completed entries from the Files page download cache.

Guardrails covered:
- POST /clear_download_list removes only fully-downloaded entries from
  module.download_stat's _download_result (the store backing
  GET /get_download_list?already_down=true on the Files page).
- in-progress entries (down_byte < total_size) are preserved.
- the JSON response reports the correct cleared count.
"""
import pytest

import module.web as web
from module.download_stat import get_download_result


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
        get_download_result().clear()


def _entry(down_byte, total_size, file_name):
    return {
        "down_byte": down_byte,
        "total_size": total_size,
        "file_name": file_name,
        "start_time": 0.0,
        "end_time": 0.0,
        "download_speed": 0,
        "each_second_total_download": 0,
        "task_id": None,
    }


def test_clear_download_list_removes_only_completed(client):
    download_result = get_download_result()
    download_result[100] = {
        1: _entry(1000, 1000, "done.mp4"),
        2: _entry(500, 1000, "in_progress.mp4"),
    }

    response = client.post("/clear_download_list")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "cleared": 1}
    assert 1 not in download_result[100]
    assert 2 in download_result[100]
    assert download_result[100][2]["down_byte"] == 500


def test_clear_download_list_drops_empty_chat_bucket(client):
    download_result = get_download_result()
    download_result[200] = {1: _entry(2000, 2000, "solo.mp4")}

    response = client.post("/clear_download_list")

    assert response.get_json() == {"ok": True, "cleared": 1}
    assert 200 not in download_result

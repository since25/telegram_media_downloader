"""Tests for GET /api/system metrics endpoint."""
import json
from types import SimpleNamespace

import module.web as web


def test_system_metrics_shape(monkeypatch):
    fake_app = SimpleNamespace(save_path="/tmp")
    monkeypatch.setattr(web, "_current_app", fake_app, raising=False)
    monkeypatch.setattr(web, "get_total_download_speed", lambda: 7215000)
    monkeypatch.setattr(web, "get_total_upload_speed", lambda: 1024)

    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = True
    try:
        with app.test_client() as client:
            resp = client.get("/api/system")
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled

    assert resp.status_code == 200
    body = json.loads(resp.data)
    for key in (
        "cpu_percent",
        "mem_used",
        "mem_total",
        "disk_used",
        "disk_total",
        "disk_free",
        "download_speed",
        "upload_speed",
    ):
        assert key in body, f"missing {key}"
    assert isinstance(body["disk_total"], int) and body["disk_total"] > 0
    assert body["download_speed"].endswith("/s")
    assert body["upload_speed"].endswith("/s")

"""Tests for GET /api/system metrics endpoint."""

import json
from types import SimpleNamespace

import module.web as web
from module.runtime_health import RuntimeHealth


def test_healthz_is_public_and_reflects_process_readiness(monkeypatch):
    health = RuntimeHealth()
    monkeypatch.setattr(
        web,
        "_current_app",
        SimpleNamespace(runtime_health=health),
        raising=False,
    )
    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = False
    try:
        with app.test_client() as client:
            starting = client.get("/healthz")
            health.mark_ready()
            ready = client.get("/healthz")
            health.mark_stopping()
            stopping = client.get("/healthz")
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled

    assert starting.status_code == 503
    assert starting.get_json() == {"status": "not_ready"}
    assert ready.status_code == 200
    assert ready.get_json() == {"status": "ok"}
    assert stopping.status_code == 503
    assert stopping.get_json() == {"status": "not_ready"}


def test_system_metrics_remain_login_protected():
    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = False
    try:
        with app.test_client() as client:
            resp = client.get("/api/system")
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled

    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


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

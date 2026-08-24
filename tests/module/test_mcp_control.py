"""Bearer authentication contract for the MCP control blueprint."""

from types import SimpleNamespace

import pytest
from flask import Flask

from module import mcp_control


@pytest.fixture
def mcp_env(tmp_path, monkeypatch):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    app = SimpleNamespace(
        mcp_enabled=True,
        config_file=str(tmp_path / "config.yaml"),
    )
    monkeypatch.setenv("TMD_MCP_API_KEY", "test-key")
    monkeypatch.setattr(mcp_control, "_current_app", app, raising=False)
    mcp_control.reset_mcp_limiter_for_tests()
    assert mcp_control.register_mcp_blueprint(flask_app, app) is True
    with flask_app.test_client() as client:
        yield SimpleNamespace(client=client, app=app)


def test_valid_key_is_accepted(mcp_env):
    response = mcp_env.client.get(
        "/api/mcp/ping", headers={"Authorization": "Bearer test-key"}
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_missing_key_returns_json_401_not_a_login_redirect(mcp_env):
    response = mcp_env.client.get("/api/mcp/ping")

    assert response.status_code == 401
    assert response.get_json()["error_code"] == "unauthorized"
    assert "Location" not in response.headers


def test_session_cookie_is_not_accepted_as_credential(mcp_env):
    mcp_env.client.set_cookie("localhost", "session", "forged")

    response = mcp_env.client.get("/api/mcp/ping")

    assert response.status_code == 401


def test_repeated_failures_are_rate_limited(mcp_env):
    for _ in range(5):
        mcp_env.client.get(
            "/api/mcp/ping", headers={"Authorization": "Bearer wrong"}
        )

    response = mcp_env.client.get(
        "/api/mcp/ping", headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code == 429
    assert response.get_json()["retry_after"] >= 1


def test_blueprint_is_not_registered_when_disabled(tmp_path):
    flask_app = Flask(__name__)
    app = SimpleNamespace(mcp_enabled=False, config_file=str(tmp_path / "config.yaml"))

    assert mcp_control.register_mcp_blueprint(flask_app, app) is False

    with flask_app.test_client() as client:
        assert client.get("/api/mcp/ping").status_code == 404


def test_error_responses_never_echo_key_material(mcp_env):
    response = mcp_env.client.get(
        "/api/mcp/ping", headers={"Authorization": "Bearer super-secret-value"}
    )

    assert "super-secret-value" not in response.get_data(as_text=True)

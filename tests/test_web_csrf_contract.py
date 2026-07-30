"""Every authenticated Web mutation must require one session-bound CSRF token."""

import re
from pathlib import Path

from module import web


MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def test_every_authenticated_mutating_route_is_csrf_protected():
    app = web.get_flask_app()
    missing = []

    for rule in app.url_map.iter_rules():
        methods = MUTATING_METHODS.intersection(rule.methods or ())
        if not methods or rule.endpoint == "login":
            continue
        view = app.view_functions[rule.endpoint]
        if not getattr(view, "_csrf_protected", False):
            missing.append(f"{','.join(sorted(methods))} {rule.rule}")

    assert missing == []


def test_login_remains_the_only_mutation_without_csrf(monkeypatch):
    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = False
    monkeypatch.setitem(web.web_login_users, "root", "secret")
    try:
        with app.test_client() as client:
            response = client.post("/login", data={"password": "secret"})
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled

    assert response.status_code == 200
    assert response.get_json()["code"] == "1"


def test_logout_requires_the_authenticated_session_token(monkeypatch):
    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = False
    monkeypatch.setitem(web.web_login_users, "root", "secret")
    try:
        client = app.test_client()
        assert client.post("/login", data={"password": "secret"}).status_code == 200
        missing = client.post("/logout")
        token = client.get("/api/csrf-token").get_json()["csrf_token"]
        valid = client.post("/logout", headers={"X-CSRF-Token": token})
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled

    assert missing.status_code == 403
    assert valid.status_code == 200


def test_legacy_mutation_rejects_missing_and_cross_session_tokens():
    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = True
    try:
        first = app.test_client()
        second = app.test_client()
        token = first.get("/api/csrf-token").get_json()["csrf_token"]

        missing = first.post("/clear_download_list")
        cross_session = second.post(
            "/clear_download_list",
            headers={"X-CSRF-Token": token},
        )
        valid = first.post(
            "/clear_download_list",
            headers={"X-CSRF-Token": token},
        )
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled

    assert missing.status_code == 403
    assert cross_session.status_code == 403
    assert valid.status_code == 200


def test_frontend_mutations_use_the_csrf_aware_fetch_helper():
    html = Path(web.__file__).with_name("templates").joinpath("index.html").read_text()

    direct_mutations = re.findall(
        r"fetch\([^;]+method\s*:\s*['\"](?:POST|PUT|PATCH|DELETE)['\"][^;]*",
        html,
        flags=re.DOTALL,
    )

    assert direct_mutations == []
    assert "async function mutationFetch(" in html

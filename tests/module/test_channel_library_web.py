"""Authenticated HTTP contracts and lifecycle wiring for channel libraries."""

import asyncio
import concurrent.futures
import os
from pathlib import Path
import re
import threading
from types import SimpleNamespace

import pytest

import media_downloader
from module.app import Application
from module.channel_library_service import ChannelLibraryService, SubmitLibraryResult
from module.channel_library_store import ChannelLibraryConfig, ChannelLibraryStore
from module.task_state import TaskStateStore


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_TEMPLATE = PROJECT_ROOT / "module/templates/index.html"
INDEX_CSS = PROJECT_ROOT / "module/static/css/index.css"


class ImmediateFuture:
    """Small completed-future double for the external owner-loop boundary."""

    def __init__(self, *, value=None, error=None):
        self.value = value
        self.error = error
        self.cancelled = False
        self.timeouts = []

    def result(self, timeout=None):
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return self.value

    def cancel(self):
        self.cancelled = True


def build_app(tmp_path):
    app = Application(
        str(tmp_path / "config.yaml"),
        str(tmp_path / "app-data.yaml"),
    )
    app.config = {
        "api_id": "1",
        "api_hash": "hash",
        "bot_token": "",
        "media_types": ["photo", "video", "document"],
        "file_formats": {"video": ["all"], "document": ["all"]},
        "save_path": str(tmp_path / "downloads"),
    }
    app.assign_config(app.config)
    return app


def insert_package(
    store,
    library_id,
    start_message_id,
    *,
    title=None,
    boundary_status="stable",
    media_count=1,
    known_total_size=100,
):
    title = title or f"Package {start_message_id}"
    with store.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        revision = connection.execute(
            "SELECT index_revision + 1 FROM channel_libraries WHERE id = ?",
            (library_id,),
        ).fetchone()[0]
        package_id = connection.execute(
            """
            INSERT INTO channel_packages (
                library_id, start_message_id, end_message_id, title,
                published_at, boundary_status, media_count,
                known_total_size, unknown_size_count,
                current_download_status, index_revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, 'never', ?, ?, ?)
            """,
            (
                library_id,
                start_message_id,
                start_message_id,
                title,
                "2026-07-16T00:00:00+00:00",
                boundary_status,
                media_count,
                known_total_size,
                revision,
                float(revision),
                float(revision),
            ),
        ).lastrowid
        connection.execute(
            """
            UPDATE channel_libraries
            SET index_revision = ?, updated_at = ? WHERE id = ?
            """,
            (revision, float(revision), library_id),
        )
    return int(package_id)


def insert_package_item(store, library_id, package_id, message_id, ordinal=0):
    with store.connect() as connection:
        connection.execute(
            """
            INSERT INTO channel_media_messages (
                library_id, message_id, message_date, media_type, caption,
                file_name, file_size, raw_fingerprint, first_seen_at, updated_at
            ) VALUES (?, ?, ?, 'video', ?, ?, ?, ?, 1, 1)
            """,
            (
                library_id,
                message_id,
                "2026-07-16T00:00:00+00:00",
                f"Caption {message_id}",
                f"video-{message_id}.mp4",
                message_id * 10,
                f"fingerprint-{message_id}",
            ),
        )
        connection.execute(
            """
            INSERT INTO channel_package_items (
                library_id, package_id, message_id, ordinal, media_type,
                caption_for_naming, original_caption, inherited_caption
            ) VALUES (?, ?, ?, ?, 'video', ?, ?, 0)
            """,
            (
                library_id,
                package_id,
                message_id,
                ordinal,
                f"Name {message_id}",
                f"Caption {message_id}",
            ),
        )


@pytest.fixture
def web_env(tmp_path):
    from module import web

    app = build_app(tmp_path)
    store = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    store.initialize()
    task_store = TaskStateStore(storage_path=tmp_path / "web-tasks.sqlite3")
    service = ChannelLibraryService(
        app,
        SimpleNamespace(),
        store,
        ChannelLibraryConfig(),
        task_store=task_store,
    )
    old_current_app = web._current_app
    old_login_disabled = web._flask_app.config.get("LOGIN_DISABLED")
    web._current_app = app
    app.channel_library_service = service
    web._flask_app.config.update(TESTING=True, LOGIN_DISABLED=True)
    try:
        with web.get_flask_app().test_client() as client:
            yield SimpleNamespace(
                app=app,
                client=client,
                service=service,
                store=store,
                task_store=task_store,
                web=web,
            )
    finally:
        app.channel_library_service = None
        web._current_app = old_current_app
        web._flask_app.config["LOGIN_DISABLED"] = old_login_disabled
        app.loop.close()


def csrf_headers(env):
    response = env.client.get("/api/csrf-token")
    assert response.status_code == 200
    return {"X-CSRF-Token": response.get_json()["csrf_token"]}


def session_cookie(env, client=None):
    client = client or env.client
    name = env.web._flask_app.config.get("SESSION_COOKIE_NAME", "session")
    for cookie in client.cookie_jar:
        if cookie.name == name:
            return cookie.value
    return None


def create_library(env, chat_id=-1001, title="Demo"):
    library, job, _ = env.store.create_or_get_library_with_full_job(
        chat_id,
        "channel",
        "demo",
        title,
        "https://t.me/demo/1",
        10,
    )
    return library, job


def strict_route_context(env):
    library, job = create_library(env)
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    detail = env.client.get(f"/api/channel-libraries/{library['id']}").get_json()
    return library, job, package_id, detail["library_version"]


def test_all_channel_routes_require_existing_login(web_env):
    env = web_env
    env.web._flask_app.config["LOGIN_DISABLED"] = False
    routes = [
        ("GET", "/api/csrf-token"),
        ("GET", "/api/channel-libraries"),
        ("POST", "/api/channel-libraries"),
        ("GET", "/api/channel-libraries/1"),
        ("DELETE", "/api/channel-libraries/1"),
        ("POST", "/api/channel-libraries/1/scans"),
        ("POST", "/api/channel-scans/1/pause"),
        ("POST", "/api/channel-scans/1/resume"),
        ("POST", "/api/channel-scans/1/stop"),
        ("GET", "/api/channel-libraries/1/packages"),
        ("GET", "/api/channel-libraries/1/packages/1/items"),
        ("PUT", "/api/channel-libraries/1/selection/packages/1"),
        ("POST", "/api/channel-libraries/1/selection/select-filtered"),
        ("POST", "/api/channel-libraries/1/selection/clear"),
        ("GET", "/api/channel-libraries/1/selection"),
        ("POST", "/api/channel-libraries/1/download-batches"),
    ]

    for method, route in routes:
        response = env.client.open(route, method=method, json={})
        assert response.status_code in {302, 401}, (method, route, response.status_code)


def test_mutating_routes_require_session_bound_csrf(web_env):
    env = web_env
    routes = [
        ("POST", "/api/channel-libraries"),
        ("DELETE", "/api/channel-libraries/1"),
        ("POST", "/api/channel-libraries/1/scans"),
        ("POST", "/api/channel-scans/1/pause"),
        ("POST", "/api/channel-scans/1/resume"),
        ("POST", "/api/channel-scans/1/stop"),
        ("PUT", "/api/channel-libraries/1/selection/packages/1"),
        ("POST", "/api/channel-libraries/1/selection/select-filtered"),
        ("POST", "/api/channel-libraries/1/selection/clear"),
        ("POST", "/api/channel-libraries/1/download-batches"),
    ]

    for method, route in routes:
        missing = env.client.open(route, method=method, json={})
        wrong = env.client.open(
            route,
            method=method,
            json={},
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert missing.status_code == 403, (method, route)
        assert wrong.status_code == 403, (method, route)
        assert missing.get_json()["error_code"] == "csrf_failed"


@pytest.mark.parametrize("supplied", [None, "wrong-token"])
def test_csrf_failure_without_token_does_not_create_session_cookie(web_env, supplied):
    env = web_env
    headers = {} if supplied is None else {"X-CSRF-Token": supplied}

    response = env.client.post(
        "/api/channel-libraries/1/selection/clear", headers=headers
    )

    assert response.status_code == 403
    assert response.get_json()["error_code"] == "csrf_failed"
    assert response.headers.getlist("Set-Cookie") == []
    assert session_cookie(env) is None


def test_wrong_csrf_does_not_rotate_existing_token_or_cookie(web_env):
    env = web_env
    token = env.client.get("/api/csrf-token").get_json()["csrf_token"]
    cookie = session_cookie(env)

    response = env.client.post(
        "/api/channel-libraries/1/selection/clear",
        headers={"X-CSRF-Token": "wrong-token"},
    )

    assert response.status_code == 403
    assert response.headers.getlist("Set-Cookie") == []
    assert session_cookie(env) == cookie
    assert env.client.get("/api/csrf-token").get_json()["csrf_token"] == token


def test_csrf_token_is_bound_to_one_session(web_env):
    env = web_env
    first_token = env.client.get("/api/csrf-token").get_json()["csrf_token"]
    with env.web.get_flask_app().test_client() as other_client:
        second_token = other_client.get("/api/csrf-token").get_json()["csrf_token"]
        second_cookie = session_cookie(env, other_client)
        response = other_client.post(
            "/api/channel-libraries",
            json={"link": "https://t.me/demo/1"},
            headers={"X-CSRF-Token": first_token},
        )

    assert first_token != second_token
    assert response.status_code == 403
    assert response.headers.getlist("Set-Cookie") == []
    assert session_cookie(env, other_client) == second_cookie


def test_channel_routes_return_safe_503_until_service_is_available(web_env):
    env = web_env
    env.app.channel_library_service = None

    read_response = env.client.get("/api/channel-libraries")
    write_response = env.client.post(
        "/api/channel-libraries",
        json={"link": "https://t.me/demo/1"},
        headers=csrf_headers(env),
    )

    assert read_response.status_code == 503
    assert write_response.status_code == 503
    assert read_response.get_json() == {
        "error_code": "service_unavailable",
        "message": "Channel library service is unavailable",
    }


def test_create_library_returns_202_then_duplicate_200(web_env):
    env = web_env

    def submit(_link):
        library, job, created = env.store.create_or_get_library_with_full_job(
            -1001,
            "channel",
            "demo",
            "Demo",
            "https://t.me/demo/1",
            10,
        )
        return ImmediateFuture(
            value=SubmitLibraryResult(library=library, created=created, job=job)
        )

    env.service.submit_library_link_threadsafe = submit
    headers = csrf_headers(env)

    created = env.client.post(
        "/api/channel-libraries",
        json={"link": "https://t.me/demo/1"},
        headers=headers,
    )
    duplicate = env.client.post(
        "/api/channel-libraries",
        json={"link": "https://t.me/demo/2"},
        headers=headers,
    )

    assert created.status_code == 202
    assert created.get_json()["created"] is True
    assert duplicate.status_code == 200
    assert duplicate.get_json()["created"] is False
    assert duplicate.get_json()["library"]["id"] == created.get_json()["library"]["id"]


@pytest.mark.parametrize(
    "payload",
    [None, [], {}, {"link": 7}, {"link": ""}],
)
def test_create_library_validates_json_and_link_type(web_env, payload):
    env = web_env
    response = env.client.post(
        "/api/channel-libraries",
        json=payload,
        headers=csrf_headers(env),
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_create_maps_domain_error_and_timeout_without_leaking_or_cancelling(web_env):
    env = web_env
    secret = "session-secret-sentinel"
    failing = ImmediateFuture(error=ValueError(secret))
    env.service.submit_library_link_threadsafe = lambda _link: failing
    headers = csrf_headers(env)

    invalid = env.client.post(
        "/api/channel-libraries",
        json={"link": "https://t.me/not-a-channel/1"},
        headers=headers,
    )
    timeout = ImmediateFuture(error=concurrent.futures.TimeoutError())
    env.service.submit_library_link_threadsafe = lambda _link: timeout
    unavailable = env.client.post(
        "/api/channel-libraries",
        json={"link": "https://t.me/demo/1"},
        headers=headers,
    )

    assert invalid.status_code == 400
    assert invalid.get_json()["error_code"] == "invalid_link"
    assert secret not in invalid.get_data(as_text=True)
    assert unavailable.status_code == 503
    assert unavailable.get_json()["error_code"] == "service_timeout"
    assert timeout.timeouts == [30]
    assert timeout.cancelled is False


def test_library_list_and_detail_include_scan_counts_and_safe_errors(web_env):
    env = web_env
    library, job = create_library(env)
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_scan_jobs SET last_error = ? WHERE id = ?",
            ("token-secret-sentinel", job["id"]),
        )

    listing = env.client.get("/api/channel-libraries?page_size=1")
    detail = env.client.get(f"/api/channel-libraries/{library['id']}")

    assert listing.status_code == 200
    assert listing.get_json()["items"][0]["scan"]["id"] == job["id"]
    body = detail.get_json()
    assert detail.status_code == 200
    assert body["counts"]["package_count"] == 1
    assert body["counts"]["media_count"] == 1
    assert body["library_version"]
    assert body["scan"]["error_code"] == "scan_failed"
    assert "token-secret-sentinel" not in detail.get_data(as_text=True)


def test_library_detail_includes_download_and_monitor_keyword_statistics(web_env):
    env = web_env
    library, _job = create_library(env)
    python_id = insert_package(
        env.store, library["id"], 10, title="Course Python Basics"
    )
    rust_id = insert_package(env.store, library["id"], 20, title="Course Rust Advanced")
    insert_package(env.store, library["id"], 30, title="Course Python Draft")
    env.store.save_keyword_monitor_group(
        "Programming",
        required_keywords=["Course"],
        match_keywords=["Python", "Rust"],
        blacklist_keywords=["Draft"],
    )
    with env.store.connect() as connection:
        connection.execute(
            """
            UPDATE channel_packages
            SET current_download_status = 'completed',
                has_successful_attempt = 1
            WHERE id = ?
            """,
            (python_id,),
        )

    body = env.client.get(f"/api/channel-libraries/{library['id']}").get_json()
    listing = env.client.get("/api/channel-libraries").get_json()

    assert body["counts"]["available_package_count"] == 3
    assert body["counts"]["downloaded_package_count"] == 1
    assert body["counts"]["pending_download_package_count"] == 2
    assert body["keyword_distribution"] == [
        {
            "group_id": 1,
            "group_name": "Programming",
            "package_count": 2,
            "keywords": [
                {"keyword": "Python", "package_count": 1},
                {"keyword": "Rust", "package_count": 1},
            ],
        }
    ]
    assert rust_id > python_id
    assert "keyword_distribution" not in listing["items"][0]


def test_library_list_strictly_validates_keyset_page_inputs(web_env):
    env = web_env

    for query in ("page_size=0", "page_size=201", "page_size=true", "cursor=bad"):
        response = env.client.get(f"/api/channel-libraries?{query}")
        assert response.status_code == 400
        assert response.get_json()["error_code"] == "invalid_request"


@pytest.mark.parametrize(
    ("method", "route_name"),
    [
        ("GET", "csrf"),
        ("GET", "libraries"),
        ("POST", "create"),
        ("GET", "detail"),
        ("DELETE", "delete"),
        ("POST", "scans"),
        ("POST", "pause"),
        ("POST", "resume"),
        ("POST", "stop"),
        ("GET", "packages"),
        ("GET", "items"),
        ("PUT", "select-one"),
        ("POST", "select-filtered"),
        ("POST", "clear-selection"),
        ("GET", "selection"),
        ("POST", "download-batch"),
    ],
)
def test_task9_route_matrix_rejects_undocumented_query_keys(
    web_env, method, route_name
):
    env = web_env
    library, job, package_id, version = strict_route_context(env)
    routes = {
        "csrf": "/api/csrf-token",
        "libraries": "/api/channel-libraries",
        "create": "/api/channel-libraries",
        "detail": f"/api/channel-libraries/{library['id']}",
        "delete": f"/api/channel-libraries/{library['id']}",
        "scans": f"/api/channel-libraries/{library['id']}/scans",
        "pause": f"/api/channel-scans/{job['id']}/pause",
        "resume": f"/api/channel-scans/{job['id']}/resume",
        "stop": f"/api/channel-scans/{job['id']}/stop",
        "packages": f"/api/channel-libraries/{library['id']}/packages",
        "items": (
            f"/api/channel-libraries/{library['id']}/packages/{package_id}/items"
        ),
        "select-one": (
            f"/api/channel-libraries/{library['id']}/selection/packages/{package_id}"
        ),
        "select-filtered": (
            f"/api/channel-libraries/{library['id']}/selection/select-filtered"
        ),
        "clear-selection": (f"/api/channel-libraries/{library['id']}/selection/clear"),
        "selection": f"/api/channel-libraries/{library['id']}/selection",
        "download-batch": (f"/api/channel-libraries/{library['id']}/download-batches"),
    }
    payloads = {
        "create": {"link": "https://t.me/demo/1"},
        "delete": {
            "confirm_library_id": library["id"],
            "library_version": version,
        },
        "scans": {"mode": "incremental"},
        "select-one": {"selected": True},
        "select-filtered": {},
        "download-batch": {"redownload": False},
    }
    headers = {}
    if method in {"POST", "PUT", "DELETE"}:
        headers.update(csrf_headers(env))
    if route_name == "download-batch":
        headers["Idempotency-Key"] = "strict-query"
    kwargs = {
        "method": method,
        "query_string": {"unexpected": "1"},
        "headers": headers,
    }
    if route_name in payloads:
        kwargs["json"] = payloads[route_name]

    response = env.client.open(routes[route_name], **kwargs)

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


@pytest.mark.parametrize(
    ("method", "route_name"),
    [
        ("GET", "csrf"),
        ("GET", "libraries"),
        ("GET", "detail"),
        ("POST", "pause"),
        ("POST", "resume"),
        ("POST", "stop"),
        ("GET", "packages"),
        ("GET", "items"),
        ("POST", "clear-selection"),
        ("GET", "selection"),
    ],
)
def test_bodyless_task9_routes_reject_unexpected_json(web_env, method, route_name):
    env = web_env
    library, job, package_id, _version = strict_route_context(env)
    routes = {
        "csrf": "/api/csrf-token",
        "libraries": "/api/channel-libraries",
        "detail": f"/api/channel-libraries/{library['id']}",
        "pause": f"/api/channel-scans/{job['id']}/pause",
        "resume": f"/api/channel-scans/{job['id']}/resume",
        "stop": f"/api/channel-scans/{job['id']}/stop",
        "packages": f"/api/channel-libraries/{library['id']}/packages",
        "items": (
            f"/api/channel-libraries/{library['id']}/packages/{package_id}/items"
        ),
        "clear-selection": (f"/api/channel-libraries/{library['id']}/selection/clear"),
        "selection": f"/api/channel-libraries/{library['id']}/selection",
    }
    headers = csrf_headers(env) if method == "POST" else {}

    response = env.client.open(
        routes[route_name],
        method=method,
        json={"unexpected": 1},
        headers=headers,
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_bodyless_commands_accept_empty_body_and_empty_json(web_env):
    env = web_env
    library, job, _package_id, _version = strict_route_context(env)
    headers = csrf_headers(env)

    paused = env.client.post(f"/api/channel-scans/{job['id']}/pause", headers=headers)
    resumed = env.client.post(
        f"/api/channel-scans/{job['id']}/resume", json={}, headers=headers
    )
    stopped = env.client.post(f"/api/channel-scans/{job['id']}/stop", headers=headers)
    cleared = env.client.post(
        f"/api/channel-libraries/{library['id']}/selection/clear",
        json={},
        headers=headers,
    )

    assert [
        response.status_code for response in (paused, resumed, stopped, cleared)
    ] == [
        200,
        200,
        200,
        200,
    ]


@pytest.mark.parametrize(
    ("method", "route_name"),
    [
        ("POST", "create"),
        ("DELETE", "delete"),
        ("POST", "scans"),
        ("PUT", "select-one"),
        ("POST", "select-filtered"),
        ("POST", "download-batch"),
    ],
)
def test_json_task9_routes_reject_undocumented_fields(web_env, method, route_name):
    env = web_env
    library, _job, package_id, version = strict_route_context(env)
    routes = {
        "create": "/api/channel-libraries",
        "delete": f"/api/channel-libraries/{library['id']}",
        "scans": f"/api/channel-libraries/{library['id']}/scans",
        "select-one": (
            f"/api/channel-libraries/{library['id']}/selection/packages/{package_id}"
        ),
        "select-filtered": (
            f"/api/channel-libraries/{library['id']}/selection/select-filtered"
        ),
        "download-batch": (f"/api/channel-libraries/{library['id']}/download-batches"),
    }
    payloads = {
        "create": {"link": "https://t.me/demo/1", "unexpected": 1},
        "delete": {
            "confirm_library_id": library["id"],
            "library_version": version,
            "unexpected": 1,
        },
        "scans": {"mode": "incremental", "unexpected": 1},
        "select-one": {"selected": True, "unexpected": 1},
        "select-filtered": {"unexpected": 1},
        "download-batch": {"redownload": False, "unexpected": 1},
    }
    headers = csrf_headers(env)
    if route_name == "download-batch":
        headers["Idempotency-Key"] = "strict-json"

    response = env.client.open(
        routes[route_name], method=method, json=payloads[route_name], headers=headers
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_versioned_delete_checks_confirmation_version_and_active_work(web_env):
    env = web_env
    library, job = create_library(env)
    headers = csrf_headers(env)
    detail = env.client.get(f"/api/channel-libraries/{library['id']}").get_json()

    active = env.client.delete(
        f"/api/channel-libraries/{library['id']}",
        json={
            "confirm_library_id": library["id"],
            "library_version": detail["library_version"],
        },
        headers=headers,
    )
    env.service.stop_job(job["id"])
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET updated_at = updated_at + 1 WHERE id = ?",
            (library["id"],),
        )
    stale = env.client.delete(
        f"/api/channel-libraries/{library['id']}",
        json={
            "confirm_library_id": library["id"],
            "library_version": detail["library_version"],
        },
        headers=headers,
    )
    current = env.client.get(f"/api/channel-libraries/{library['id']}").get_json()
    wrong_confirm = env.client.delete(
        f"/api/channel-libraries/{library['id']}",
        json={
            "confirm_library_id": library["id"] + 1,
            "library_version": current["library_version"],
        },
        headers=headers,
    )
    deleted = env.client.delete(
        f"/api/channel-libraries/{library['id']}",
        json={
            "confirm_library_id": library["id"],
            "library_version": current["library_version"],
        },
        headers=headers,
    )

    assert active.status_code == 409
    assert stale.status_code == 409
    assert wrong_confirm.status_code == 400
    assert deleted.status_code == 200
    assert env.client.get(f"/api/channel-libraries/{library['id']}").status_code == 404


def test_versioned_delete_rejects_terminal_parent_with_active_child_attempt(web_env):
    env = web_env
    library, job = create_library(env)
    env.service.stop_job(job["id"])
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    env.store.set_package_selected(library["id"], package_id, True)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
    batch = env.service.create_download_batch(library["id"], "divergent-attempt")
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_download_batches SET status = 'completed' WHERE id = ?",
            (batch["id"],),
        )
    detail = env.client.get(f"/api/channel-libraries/{library['id']}").get_json()

    response = env.client.delete(
        f"/api/channel-libraries/{library['id']}",
        json={
            "confirm_library_id": library["id"],
            "library_version": detail["library_version"],
        },
        headers=csrf_headers(env),
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "state_conflict"
    assert env.store.get_library(library["id"]) is not None
    assert (
        env.store.get_download_batch(batch["id"])["packages"][0]["status"] == "queued"
    )


def test_scan_create_and_controls_map_statuses(web_env):
    env = web_env
    library, initial_job = create_library(env)
    headers = csrf_headers(env)

    paused = env.client.post(
        f"/api/channel-scans/{initial_job['id']}/pause", headers=headers
    )
    resumed = env.client.post(
        f"/api/channel-scans/{initial_job['id']}/resume", headers=headers
    )
    stopped = env.client.post(
        f"/api/channel-scans/{initial_job['id']}/stop", headers=headers
    )
    env.service.submit_incremental_threadsafe = lambda _library_id: ImmediateFuture(
        error=ValueError("full scan is not finished")
    )
    conflict = env.client.post(
        f"/api/channel-libraries/{library['id']}/scans",
        json={"mode": "incremental"},
        headers=headers,
    )
    missing = env.client.post("/api/channel-scans/9999/pause", headers=headers)
    invalid = env.client.post(
        f"/api/channel-libraries/{library['id']}/scans",
        json={"mode": "repair", "failure_ids": [True]},
        headers=headers,
    )
    retry_invalid = env.client.post(
        f"/api/channel-libraries/{library['id']}/scans",
        json={"mode": "retry", "failed_job_id": True},
        headers=headers,
    )

    assert paused.status_code == 200
    assert paused.get_json()["scan"]["status"] == "paused_user"
    assert resumed.get_json()["scan"]["status"] == "queued"
    assert stopped.get_json()["scan"]["status"] == "stopped"
    assert conflict.status_code == 409
    assert missing.status_code == 404
    assert invalid.status_code == 400
    assert retry_invalid.status_code == 400


def test_package_and_item_queries_use_filters_keysets_and_revision(web_env):
    env = web_env
    library, _job = create_library(env)
    first_id = insert_package(env.store, library["id"], 10, title="Other")
    second_id = insert_package(env.store, library["id"], 20, title="Lesson two")
    third_id = insert_package(env.store, library["id"], 30, title="Lesson three")
    insert_package_item(env.store, library["id"], second_id, 20, ordinal=0)
    insert_package_item(env.store, library["id"], second_id, 21, ordinal=1)

    page_one = env.client.get(
        f"/api/channel-libraries/{library['id']}/packages?q=lesson&page_size=1"
    )
    body_one = page_one.get_json()
    page_two = env.client.get(
        f"/api/channel-libraries/{library['id']}/packages",
        query_string={"q": "lesson", "page_size": 1, "cursor": body_one["next_cursor"]},
    )
    items_one = env.client.get(
        f"/api/channel-libraries/{library['id']}/packages/{second_id}/items?page_size=1"
    )
    items_two = env.client.get(
        f"/api/channel-libraries/{library['id']}/packages/{second_id}/items",
        query_string={"page_size": 1, "cursor": items_one.get_json()["next_cursor"]},
    )

    assert page_one.status_code == 200
    assert [item["id"] for item in body_one["items"]] == [third_id]
    assert [item["id"] for item in page_two.get_json()["items"]] == [second_id]
    assert page_two.get_json()["library_revision"] == body_one["library_revision"]
    assert items_one.get_json()["items"][0]["message_id"] == 20
    assert items_two.get_json()["items"][0]["message_id"] == 21
    assert first_id not in {third_id, second_id}


def test_aggregate_packages_filter_select_and_download_across_channels(web_env):
    env = web_env
    first_library, first_job = create_library(env, chat_id=-1001, title="Alpha")
    second_library, second_job = create_library(env, chat_id=-1002, title="Beta")
    first_package = insert_package(
        env.store, first_library["id"], 10, title="Same Course"
    )
    second_package = insert_package(
        env.store, second_library["id"], 20, title="Same Course"
    )
    insert_package_item(env.store, first_library["id"], first_package, 10)
    insert_package_item(env.store, second_library["id"], second_package, 20)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id IN (?, ?)",
            (first_library["id"], second_library["id"]),
        )
        connection.execute(
            "UPDATE channel_scan_jobs SET status = 'completed' WHERE id IN (?, ?)",
            (first_job["id"], second_job["id"]),
        )
    headers = csrf_headers(env)

    all_packages = env.client.get("/api/packages?q=course")
    alpha_packages = env.client.get(
        "/api/packages",
        query_string={"q": "course", "library_ids": str(first_library["id"])},
    )
    first_selection = env.client.put(
        f"/api/packages/{first_package}/selection",
        json={"selected": True},
        headers=headers,
    )
    second_selection = env.client.put(
        f"/api/packages/{second_package}/selection",
        json={"selected": True},
        headers=headers,
    )
    summary = env.client.get("/api/packages/selection")
    scheduled = set()
    env.service.schedule_download_batch_threadsafe = scheduled.add
    download_headers = {**headers, "Idempotency-Key": "aggregate-request"}
    created = env.client.post(
        "/api/packages/download-batches",
        json={"redownload": False},
        headers=download_headers,
    )
    replayed = env.client.post(
        "/api/packages/download-batches",
        json={"redownload": False},
        headers=download_headers,
    )

    assert all_packages.status_code == 200
    assert {
        (item["id"], item["channel_title"]) for item in all_packages.get_json()["items"]
    } == {(first_package, "Alpha"), (second_package, "Beta")}
    assert [item["id"] for item in alpha_packages.get_json()["items"]] == [
        first_package
    ]
    assert first_selection.status_code == second_selection.status_code == 200
    assert summary.get_json()["channel_count"] == 2
    assert created.status_code == 202
    assert len(created.get_json()["batches"]) == 2
    assert replayed.status_code == 200
    assert replayed.get_json()["created"] is False
    assert {batch["id"] for batch in replayed.get_json()["batches"]} == {
        batch["id"] for batch in created.get_json()["batches"]
    }
    assert scheduled == {batch["id"] for batch in created.get_json()["batches"]}


def test_keyword_monitor_group_api_triggers_existing_index_and_returns_history(web_env):
    env = web_env
    library, job = create_library(env, title="Courses")
    package_id = insert_package(env.store, library["id"], 10, title="课程 Python 完整版")
    insert_package_item(env.store, library["id"], package_id, 10)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
        connection.execute(
            "UPDATE channel_scan_jobs SET status = 'completed' WHERE id = ?",
            (job["id"],),
        )
    headers = csrf_headers(env)

    created = env.client.post(
        "/api/keyword-monitor-groups",
        json={
            "name": "课程监控",
            "enabled": True,
            "required_keywords": ["课程"],
            "match_keywords": ["Python", " python "],
            "blacklist_keywords": ["预告"],
        },
        headers=headers,
    )
    group = created.get_json()["group"]
    listed = env.client.get("/api/keyword-monitor-groups")
    history = env.client.get(f"/api/keyword-monitor-groups/{group['id']}/history")
    updated = env.client.put(
        f"/api/keyword-monitor-groups/{group['id']}",
        json={
            "name": "课程监控",
            "enabled": False,
            "required_keywords": ["课程"],
            "match_keywords": ["Python"],
            "blacklist_keywords": ["预告"],
        },
        headers=headers,
    )

    assert created.status_code == 201
    assert group["match_keywords"] == ["Python"]
    assert listed.get_json()["items"][0]["history_count"] == 1
    assert history.get_json()["items"][0]["package_id"] == package_id
    assert history.get_json()["items"][0]["matched_keywords"] == ["Python"]
    assert history.get_json()["items"][0]["package_download_status"] == "queued"
    assert history.get_json()["items"][0]["progress"] == {
        "status": "queued",
        "total_count": 1,
        "success_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "upload_success_count": 0,
        "updated_at": history.get_json()["items"][0]["progress"]["updated_at"],
    }
    assert updated.get_json()["group"]["enabled"] is False


@pytest.mark.parametrize(
    "query",
    [
        "page_size=0",
        "page_size=201",
        "include_unknown_size=1",
        "message_id_min=-1",
        "media_count_min=true",
        "download_status=secret",
        "date_from=not-a-date",
    ],
)
def test_package_query_strictly_validates_filter_primitives(web_env, query):
    env = web_env
    library, _job = create_library(env)

    response = env.client.get(
        f"/api/channel-libraries/{library['id']}/packages?{query}"
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_selection_single_filtered_clear_and_summary(web_env):
    env = web_env
    library, _job = create_library(env)
    stable_id = insert_package(env.store, library["id"], 10, media_count=2)
    insert_package(env.store, library["id"], 20, boundary_status="uncertain")
    headers = csrf_headers(env)

    selected = env.client.put(
        f"/api/channel-libraries/{library['id']}/selection/packages/{stable_id}",
        json={"selected": True},
        headers=headers,
    )
    summary = env.client.get(f"/api/channel-libraries/{library['id']}/selection")
    invalid_bool = env.client.put(
        f"/api/channel-libraries/{library['id']}/selection/packages/{stable_id}",
        json={"selected": 1},
        headers=headers,
    )
    filtered = env.client.post(
        f"/api/channel-libraries/{library['id']}/selection/select-filtered",
        json={"media_count_min": 1},
        headers=headers,
    )
    cleared = env.client.post(
        f"/api/channel-libraries/{library['id']}/selection/clear",
        headers=headers,
    )

    assert selected.status_code == 200
    assert selected.get_json()["selection"]["selected"] is True
    assert summary.get_json()["selected_count"] == 1
    assert summary.get_json()["media_count"] == 2
    assert invalid_bool.status_code == 400
    assert filtered.get_json()["selected_count"] == 1
    assert filtered.get_json()["skipped_count"] == 1
    assert cleared.get_json()["cleared_count"] == 1


def test_create_download_batch_response_is_a_lightweight_summary(web_env):
    env = web_env
    library, job = create_library(env)
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    env.store.set_package_selected(library["id"], package_id, True)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
        connection.execute(
            "UPDATE channel_scan_jobs SET status = 'completed' WHERE id = ?",
            (job["id"],),
        )
    env.service.schedule_download_batch_threadsafe = lambda *_a, **_k: None
    headers = {**csrf_headers(env), "Idempotency-Key": "summary-key"}

    response = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={"redownload": False},
        headers=headers,
    )

    assert response.status_code == 202
    batch = response.get_json()["batch"]
    assert batch["task_id"].startswith("channel-batch-")
    assert batch["package_count"] == 1
    assert batch["item_count"] == 1
    # The response must not carry the full (potentially huge) package/item snapshot.
    assert "packages" not in batch
    assert "items" not in batch


def test_download_batch_requires_key_is_idempotent_and_schedules_once(web_env):
    env = web_env
    library, job = create_library(env)
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    env.store.set_package_selected(library["id"], package_id, True)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
        connection.execute(
            "UPDATE channel_scan_jobs SET status = 'completed' WHERE id = ?",
            (job["id"],),
        )
    scheduled = set()
    env.service.schedule_download_batch_threadsafe = scheduled.add
    headers = csrf_headers(env)

    missing_key = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={},
        headers=headers,
    )
    first = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={"redownload": False},
        headers={**headers, "Idempotency-Key": "request-1"},
    )
    duplicate = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={"redownload": False},
        headers={**headers, "Idempotency-Key": "request-1"},
    )

    assert missing_key.status_code == 400
    assert first.status_code == 202
    assert duplicate.status_code == 200
    assert first.get_json()["batch"]["id"] == duplicate.get_json()["batch"]["id"]
    assert scheduled == {first.get_json()["batch"]["id"]}


def test_download_batch_result_preserves_dict_api_and_reports_atomic_creation(web_env):
    env = web_env
    library, job = create_library(env)
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    env.store.set_package_selected(library["id"], package_id, True)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
        connection.execute(
            "UPDATE channel_scan_jobs SET status = 'completed' WHERE id = ?",
            (job["id"],),
        )

    first, first_created = env.service.create_download_batch_result(
        library["id"], "atomic-result"
    )
    replay, replay_created = env.service.create_download_batch_result(
        library["id"], "atomic-result"
    )
    legacy = env.service.create_download_batch(library["id"], "atomic-result")

    assert first_created is True
    assert replay_created is False
    assert first["id"] == replay["id"] == legacy["id"]
    assert isinstance(legacy, dict)


def test_concurrent_download_requests_return_one_creator_and_one_replay(
    web_env, monkeypatch
):
    env = web_env
    library, job = create_library(env)
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    env.store.set_package_selected(library["id"], package_id, True)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
        connection.execute(
            "UPDATE channel_scan_jobs SET status = 'completed' WHERE id = ?",
            (job["id"],),
        )
    env.service.schedule_download_batch_threadsafe = lambda _batch_id: None
    original_lookup = env.store.get_download_batch_by_idempotency_key
    lookup_barrier = threading.Barrier(2)

    def synchronized_lookup(*args):
        result = original_lookup(*args)
        lookup_barrier.wait(timeout=2)
        return result

    monkeypatch.setattr(
        env.store, "get_download_batch_by_idempotency_key", synchronized_lookup
    )
    first_client = env.web.get_flask_app().test_client()
    second_client = env.web.get_flask_app().test_client()
    first_headers = {
        **csrf_headers(SimpleNamespace(client=first_client)),
        "Idempotency-Key": "concurrent-key",
    }
    second_headers = {
        **csrf_headers(SimpleNamespace(client=second_client)),
        "Idempotency-Key": "concurrent-key",
    }

    def submit(client, headers):
        return client.post(
            f"/api/channel-libraries/{library['id']}/download-batches",
            json={"redownload": False},
            headers=headers,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda args: submit(*args),
                ((first_client, first_headers), (second_client, second_headers)),
            )
        )

    assert sorted(response.status_code for response in responses) == [200, 202]
    assert len({response.get_json()["batch"]["id"] for response in responses}) == 1
    assert len(env.store.list_download_batches(library["id"])) == 1


def test_replaying_pending_batch_repairs_dispatch_after_failure(web_env, monkeypatch):
    env = web_env
    library, job = create_library(env)
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    env.store.set_package_selected(library["id"], package_id, True)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
        connection.execute(
            "UPDATE channel_scan_jobs SET status = 'completed' WHERE id = ?",
            (job["id"],),
        )
    original_ensure = env.task_store.ensure_task
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("dispatch unavailable")
        return original_ensure(*args, **kwargs)

    monkeypatch.setattr(env.task_store, "ensure_task", fail_once)
    scheduled = []
    env.service.schedule_download_batch_threadsafe = scheduled.append
    headers = {
        **csrf_headers(env),
        "Idempotency-Key": "repair-pending",
    }

    failed = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={"redownload": False},
        headers=headers,
    )
    pending = env.store.list_pending_download_batches()[0]
    replay = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={"redownload": False},
        headers=headers,
    )

    assert failed.status_code == 503
    assert replay.status_code == 200
    assert replay.get_json()["created"] is False
    assert replay.get_json()["batch"]["id"] == pending["id"]
    assert (
        env.store.get_download_batch(pending["id"])["dispatch_status"] == "dispatched"
    )
    assert scheduled == [pending["id"]]


def test_download_batch_maps_state_conflict_and_strict_redownload_type(web_env):
    env = web_env
    library, _job = create_library(env)
    headers = {
        **csrf_headers(env),
        "Idempotency-Key": "request-2",
    }

    conflict = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={"redownload": False},
        headers=headers,
    )
    invalid = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={"redownload": 1},
        headers=headers,
    )

    assert conflict.status_code == 409
    assert conflict.get_json()["error_code"] == "state_conflict"
    assert invalid.status_code == 400


def test_download_batch_returns_specific_redownload_required_code(web_env):
    env = web_env
    library, job = create_library(env)
    package_id = insert_package(env.store, library["id"], 10)
    insert_package_item(env.store, library["id"], package_id, 10)
    env.store.set_package_selected(library["id"], package_id, True)
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
        connection.execute(
            "UPDATE channel_scan_jobs SET status = 'completed' WHERE id = ?",
            (job["id"],),
        )
        connection.execute(
            """
            UPDATE channel_packages
            SET has_successful_attempt = 1,
                current_download_status = 'completed'
            WHERE id = ?
            """,
            (package_id,),
        )

    response = env.client.post(
        f"/api/channel-libraries/{library['id']}/download-batches",
        json={"redownload": False},
        headers={
            **csrf_headers(env),
            "Idempotency-Key": "requires-redownload",
        },
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "redownload_required"


def test_scan_response_reports_kind_and_range_relative_progress(web_env):
    env = web_env
    library, job = create_library(env)
    with env.store.connect() as connection:
        connection.execute(
            """
            UPDATE channel_scan_jobs
            SET kind = 'incremental', start_message_id = 14501,
                snapshot_max_message_id = 15000,
                fetched_through_message_id = 15000,
                scanned_id_count = 500, status = 'completed'
            WHERE id = ?
            """,
            (job["id"],),
        )

    scan = env.client.get(f"/api/channel-libraries/{library['id']}").get_json()["scan"]

    assert scan["kind"] == "incremental"
    assert scan["progress_completed_id_count"] == 500
    assert scan["progress_total_id_count"] == 500

    with env.store.connect() as connection:
        connection.execute(
            """
            UPDATE channel_scan_jobs
            SET kind = 'repair', scanned_id_count = 120
            WHERE id = ?
            """,
            (job["id"],),
        )
    repair_scan = env.client.get(f"/api/channel-libraries/{library['id']}").get_json()[
        "scan"
    ]

    assert repair_scan["progress_completed_id_count"] == 120
    assert repair_scan["progress_total_id_count"] is None


def test_service_start_schedules_each_resumable_download_batch_once(tmp_path):
    loop = asyncio.new_event_loop()
    app = SimpleNamespace(loop=loop)
    store = ChannelLibraryStore(tmp_path / "channel.sqlite3")
    store.initialize()
    library, _ = store.create_or_get_library(
        -1001, "channel", "demo", "Demo", "https://t.me/demo/1"
    )
    package_id = insert_package(store, library["id"], 10)
    insert_package_item(store, library["id"], package_id, 10)
    store.set_package_selected(library["id"], package_id, True)
    with store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (library["id"],),
        )
    task_store = TaskStateStore(storage_path=tmp_path / "tasks.sqlite3")
    service = ChannelLibraryService(
        app,
        SimpleNamespace(),
        store,
        ChannelLibraryConfig(),
        task_store=task_store,
    )
    batch = service.create_download_batch(library["id"], "restart-batch")
    calls = []

    async def record_run(batch_id):
        calls.append(batch_id)
        await asyncio.sleep(0)
        return []

    service.run_download_batch = record_run
    try:
        loop.run_until_complete(service.start())
        service.schedule_pending_download_batches()
        service.schedule_pending_download_batches()
        loop.run_until_complete(asyncio.sleep(0))
        assert calls == [batch["id"]]
        loop.run_until_complete(service.stop())
    finally:
        loop.close()


def test_service_start_cleans_owner_tasks_when_pending_schedule_fails(tmp_path):
    loop = asyncio.new_event_loop()
    service = ChannelLibraryService(
        SimpleNamespace(loop=loop),
        SimpleNamespace(),
        ChannelLibraryStore(tmp_path / "channel.sqlite3"),
        ChannelLibraryConfig(),
        task_store=TaskStateStore(storage_path=tmp_path / "tasks.sqlite3"),
    )

    def fail_schedule():
        raise RuntimeError("pending schedule failed")

    service.schedule_pending_download_batches = fail_schedule
    try:
        with pytest.raises(RuntimeError, match="pending schedule failed"):
            loop.run_until_complete(service.start())
        loop.run_until_complete(asyncio.sleep(0))
        assert service.scheduler_task is None or service.scheduler_task.done()
        assert service._download_batch_tasks == {}
    finally:
        if service.scheduler_task is not None and not service.scheduler_task.done():
            service.scheduler_task.cancel()
            loop.run_until_complete(
                asyncio.gather(service.scheduler_task, return_exceptions=True)
            )
        loop.close()


def test_media_lifecycle_assigns_after_start_stops_and_survives_init_failure(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    loop = asyncio.new_event_loop()
    app = SimpleNamespace(
        loop=loop,
        channel_library_config=ChannelLibraryConfig(),
        channel_library_service=None,
    )
    try:
        started = media_downloader._start_channel_library_service(
            app, SimpleNamespace()
        )
        assert started is app.channel_library_service
        assert started.owner_loop is loop
        assert (tmp_path / "channel_library.sqlite3").exists()

        media_downloader._stop_channel_library_service(app)
        assert app.channel_library_service is None

        async def fail_start(_self):
            raise RuntimeError("secret-token-sentinel")

        monkeypatch.setattr(ChannelLibraryService, "start", fail_start)
        assert (
            media_downloader._start_channel_library_service(app, SimpleNamespace())
            is None
        )
        assert app.channel_library_service is None
    finally:
        if app.channel_library_service is not None:
            loop.run_until_complete(app.channel_library_service.stop())
        loop.close()


def test_media_shutdown_clears_service_before_await_and_precedes_client_stop():
    loop = asyncio.new_event_loop()
    events = []
    app = SimpleNamespace(loop=loop, channel_library_service=None)

    class RecordingService:
        async def stop(self):
            events.append(("service_stop", app.channel_library_service))

    class RecordingClient:
        async def stop(self):
            events.append(("client_stop", None))

    service = RecordingService()
    app.channel_library_service = service
    try:
        media_downloader._stop_channel_library_service(app)
        loop.run_until_complete(media_downloader.stop_server(RecordingClient()))
    finally:
        loop.close()

    assert events == [("service_stop", None), ("client_stop", None)]


def test_channel_library_tab_has_one_complete_spa_dom_contract():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    required_ids = {
        "tab_channel-library",
        "channel_library_link",
        "channel_library_add",
        "channel_library_rows",
        "channel_library_more",
        "channel_library_empty",
        "channel_library_workspace",
        "channel_library_status",
        "channel_library_scan_controls",
        "channel_library_notice",
        "channel_library_stats",
        "channel_stat_available",
        "channel_stat_downloaded",
        "channel_keyword_distribution",
        "channel_library_delete",
    }

    assert html.count('data-tab="channel-library"') == 1
    assert 'href="/channel' not in html
    assert (
        '<button type="button" class="app-tab" data-tab="channel-library" role="tab"'
        in html
    )
    assert html.count('role="tabpanel"') == 6
    assert 'aria-labelledby="app_tab_channel_library"' in html
    assert "['ArrowLeft','ArrowRight'].includes(e.key)" in html
    assert "next.focus(); next.click();" in html
    for element_id in required_ids:
        assert len(re.findall(rf'id="{re.escape(element_id)}"', html)) == 1
    assert 'id="channel_library_packages"' not in html
    assert 'id="channel_library_filters"' not in html


def test_aggregate_package_and_keyword_monitor_tabs_have_complete_dom_contracts():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    required_ids = {
        "tab_packages",
        "aggregate_filter_libraries",
        "aggregate_package_filters",
        "aggregate_package_rows",
        "aggregate_selection_text",
        "aggregate_select_filtered",
        "aggregate_download_selection",
        "tab_keyword-monitor",
        "keyword_group_rows",
        "keyword_group_form",
        "keyword_required",
        "keyword_match",
        "keyword_blacklist",
        "keyword_history_rows",
    }

    assert html.count('data-tab="packages"') == 1
    assert html.count('data-tab="keyword-monitor"') == 1
    assert "/api/packages" in html
    assert "/api/keyword-monitor-groups" in html
    for element_id in required_ids:
        assert len(re.findall(rf'id="{re.escape(element_id)}"', html)) == 1


def test_channel_library_script_has_security_state_and_polling_contracts():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert "async function channelApiWrite" in html
    assert "'X-CSRF-Token': state.channel.csrfToken" in html
    assert "function isChannelLibraryActive" in html
    assert "if (!isChannelLibraryActive()) return" in html
    assert "else if (tab==='channel-library')" in html
    assert "escapeHtml(library.title" in html
    assert "escapeHtml(pkg.title" in html
    assert "escapeHtml(message)" in html


def test_channel_library_controls_resume_stopped_scans():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert "scan.status === 'paused_user' || scan.status === 'stopped'" in html


def test_channel_library_script_guards_async_identity_and_all_keyset_pages():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")
    detail_source = html.split("async function loadChannelDetail", 1)[1].split(
        "async function selectChannelLibrary", 1
    )[0]

    assert "generation:0" in html
    assert html.count("generation !== state.channel.generation") >= 4
    assert "libraryNextCursor" in html
    assert "data-channel-library-more" in html
    assert "loadChannelLibraries({append:true})" in html
    assert "refreshLoaded=true" in html
    assert "pagesFetched < targetPages || !selectedFound()" in html
    assert "progress_total_id_count" in html
    assert "CHANNEL_SCAN_KIND" in html
    assert "catch (error)" in detail_source
    assert "throw error" in detail_source


def test_keyword_monitor_form_preserves_unsaved_draft_during_polling():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert "draftDirty:false" in html
    assert "state.keywordMonitor.draftDirty" in html
    assert "captureKeywordDraft()" in html
    assert "if (selected&&!state.keywordMonitor.draftDirty)" in html


@pytest.mark.parametrize(
    ("status", "label"),
    [
        ("empty", "尚未添加频道"),
        ("queued", "排队中"),
        ("running", "扫描中"),
        ("auto_paused_download", "下载让行"),
        ("paused_user", "已暂停"),
        ("partial", "部分完成"),
        ("ready", "就绪"),
        ("failed", "失败"),
        ("provisional", "待确认边界"),
        ("uncertain", "边界不确定"),
        ("outdated", "内容已更新"),
        ("superseded", "已被替代"),
    ],
)
def test_channel_library_ui_defines_required_state_labels(status, label):
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert re.search(rf"{re.escape(status)}\s*:\s*\{{[^}}]*label:'{label}'", html)


def test_channel_library_styles_define_responsive_split_workspace():
    css = INDEX_CSS.read_text(encoding="utf-8")

    assert ".channel-library-layout" in css
    assert "grid-template-columns: 248px minmax(0, 1fr)" in css
    assert ".channel-library-sidebar" in css
    assert ".channel-library-workspace" in css
    assert ".channel-library-workspace-empty[hidden]" in css
    assert ".channel-library-table-footer .btn[hidden]" in css
    assert ".channel-library-package-grid" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 560px)" in css
    assert ".app-tab-list, .app-tab, .app-nav > button" in css
    assert "flex: 0 0 auto; white-space: nowrap" in css

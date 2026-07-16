"""Authenticated HTTP contracts and lifecycle wiring for channel libraries."""

import asyncio
import concurrent.futures
import os
from types import SimpleNamespace

import pytest

import media_downloader
from module.app import Application
from module.channel_library_service import ChannelLibraryService, SubmitLibraryResult
from module.channel_library_store import ChannelLibraryConfig, ChannelLibraryStore
from module.task_state import TaskStateStore


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


def test_csrf_token_is_bound_to_one_session(web_env):
    env = web_env
    first_token = env.client.get("/api/csrf-token").get_json()["csrf_token"]
    with env.web.get_flask_app().test_client() as other_client:
        second_token = other_client.get("/api/csrf-token").get_json()["csrf_token"]
        response = other_client.post(
            "/api/channel-libraries",
            json={"link": "https://t.me/demo/1"},
            headers={"X-CSRF-Token": first_token},
        )

    assert first_token != second_token
    assert response.status_code == 403


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


def test_library_list_strictly_validates_keyset_page_inputs(web_env):
    env = web_env

    for query in ("page_size=0", "page_size=201", "page_size=true", "cursor=bad"):
        response = env.client.get(f"/api/channel-libraries?{query}")
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
    scheduled = []
    env.service.schedule_download_batch_threadsafe = scheduled.append
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
    assert scheduled == [first.get_json()["batch"]["id"]]


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
        assert media_downloader._start_channel_library_service(
            app, SimpleNamespace()
        ) is None
        assert app.channel_library_service is None
    finally:
        if app.channel_library_service is not None:
            loop.run_until_complete(app.channel_library_service.stop())
        loop.close()

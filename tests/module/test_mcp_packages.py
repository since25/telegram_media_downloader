"""Read-only MCP package queries mirror the browser queries."""

from types import SimpleNamespace

import pytest
from flask import Flask

from module import mcp_control
from module.channel_library_service import ChannelLibraryService
from module.channel_library_store import ChannelLibraryConfig, ChannelLibraryStore
from module.task_state import TaskStateStore
from tests.module.test_channel_library_web import (
    build_app,
    insert_package,
    insert_package_item,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    app = build_app(tmp_path)
    app.mcp_enabled = True
    store = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    store.initialize()
    task_store = TaskStateStore(storage_path=tmp_path / "web-tasks.sqlite3")
    app.channel_library_service = ChannelLibraryService(
        app,
        SimpleNamespace(),
        store,
        ChannelLibraryConfig(),
        task_store=task_store,
    )
    monkeypatch.setenv("TMD_MCP_API_KEY", "test-key")
    mcp_control.reset_mcp_limiter_for_tests()
    mcp_control.register_mcp_blueprint(flask_app, app)
    library, _job, _created = store.create_or_get_library_with_full_job(
        -1001, "channel", "demo", "Demo", "https://t.me/demo/1", 10
    )
    try:
        with flask_app.test_client() as client:
            yield SimpleNamespace(
                client=client, app=app, store=store, library=library
            )
    finally:
        app.loop.close()


def auth():
    return {"Authorization": "Bearer test-key"}


def test_search_returns_non_superseded_packages_with_downloadable_flag(env):
    stable_id = insert_package(env.store, env.library["id"], 10)
    provisional_id = insert_package(
        env.store, env.library["id"], 20, boundary_status="provisional"
    )

    response = env.client.get("/api/mcp/packages?page_size=50", headers=auth())

    assert response.status_code == 200
    items = {int(item["id"]): item for item in response.get_json()["items"]}
    assert set(items) == {stable_id, provisional_id}
    assert items[stable_id]["downloadable"] is True
    assert items[provisional_id]["downloadable"] is False
    assert items[provisional_id]["boundary_status"] == "provisional"


def test_search_rejects_unknown_query_parameters(env):
    response = env.client.get("/api/mcp/packages?nope=1", headers=auth())

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_package_detail_returns_metadata_and_items(env):
    package_id = insert_package(env.store, env.library["id"], 10)
    insert_package_item(env.store, env.library["id"], package_id, 10)

    response = env.client.get(f"/api/mcp/packages/{package_id}", headers=auth())

    assert response.status_code == 200
    payload = response.get_json()
    assert int(payload["package"]["id"]) == package_id
    assert len(payload["items"]) == 1


def test_missing_package_returns_not_found(env):
    response = env.client.get("/api/mcp/packages/999999", headers=auth())

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "not_found"

"""Keyword monitor management over MCP mirrors the browser contract."""

import asyncio
import threading

import pytest

from tests.module.test_mcp_packages import auth, env  # noqa: F401


@pytest.fixture(autouse=True)
def running_owner_loop(env):
    loop = env.app.loop
    env.app.channel_library_service.owner_loop = loop
    env.app.channel_library_service._accepting_commands = True
    started = threading.Event()

    def run_loop():
        asyncio.set_event_loop(loop)
        started.set()
        loop.run_forever()

    thread = threading.Thread(target=run_loop)
    thread.start()
    assert started.wait(timeout=1)
    try:
        yield
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)


def body(name="Python", match=("python",)):
    return {
        "name": name,
        "enabled": True,
        "required_keywords": [],
        "match_keywords": list(match),
        "blacklist_keywords": [],
    }


def test_create_list_and_get_round_trip(env):
    created = env.client.post("/api/mcp/keyword-monitors", headers=auth(), json=body())
    group_id = created.get_json()["group"]["id"]

    listed = env.client.get("/api/mcp/keyword-monitors", headers=auth())
    fetched = env.client.get(f"/api/mcp/keyword-monitors/{group_id}", headers=auth())

    assert created.status_code == 201
    listed_payload = listed.get_json()
    assert [item["id"] for item in listed_payload["items"]] == [group_id]
    assert listed_payload["total"] == 1
    assert listed_payload["enabled"] == 1
    assert listed_payload["disabled"] == 0
    assert listed_payload["items"][0]["summary"]["total_count"] == 0
    assert fetched.get_json()["group"]["name"] == "Python"
    assert fetched.get_json()["group"]["summary"]["processed_count"] == 0


def test_create_requires_at_least_one_match_keyword(env):
    response = env.client.post(
        "/api/mcp/keyword-monitors", headers=auth(), json=body(match=())
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_delete_removes_the_group(env):
    created = env.client.post("/api/mcp/keyword-monitors", headers=auth(), json=body())
    group_id = created.get_json()["group"]["id"]

    deleted = env.client.delete(f"/api/mcp/keyword-monitors/{group_id}", headers=auth())
    listed = env.client.get("/api/mcp/keyword-monitors", headers=auth())

    assert deleted.status_code == 200
    assert listed.get_json()["items"] == []


def test_retry_without_recoverable_failures_returns_conflict(env):
    created = env.client.post("/api/mcp/keyword-monitors", headers=auth(), json=body())
    group_id = created.get_json()["group"]["id"]

    response = env.client.post(
        f"/api/mcp/keyword-monitors/{group_id}/retry-failures", headers=auth()
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "state_conflict"

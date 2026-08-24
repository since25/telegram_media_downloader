"""System status and task reads over MCP stay bounded and secret-free."""

from tests.module.test_mcp_packages import auth, env  # noqa: F401

from module.task_state import TaskStatus, get_task_store


def test_system_status_reports_state_without_secrets(env):
    env.app.api_hash = "super-secret-hash"

    response = env.client.get("/api/mcp/system", headers=auth())

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {
        "phase",
        "download_state",
        "download_speed_bytes",
        "disk_free",
        "disk_total",
        "active_task_count",
        "completed_task_count",
    }
    assert "super-secret-hash" not in response.get_data(as_text=True)


def test_task_list_is_capped_and_filterable(env):
    store = get_task_store()
    for index in range(5):
        store.create_task(
            task_id=f"task-{index}",
            task_type="channel_batch",
            source="mcp-test",
            status=TaskStatus.QUEUED,
        )

    capped = env.client.get("/api/mcp/tasks?limit=2", headers=auth())
    filtered = env.client.get(
        f"/api/mcp/tasks?status={TaskStatus.DOWNLOADING}", headers=auth()
    )

    assert len(capped.get_json()["items"]) == 2
    assert filtered.get_json()["items"] == []


def test_task_detail_returns_not_found_for_unknown_id(env):
    response = env.client.get("/api/mcp/tasks/missing", headers=auth())

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "not_found"

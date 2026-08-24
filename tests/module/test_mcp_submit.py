"""Download submission over MCP is explicit, idempotent, and selection-free."""

from tests.module.test_mcp_packages import auth, env  # noqa: F401
from tests.module.test_channel_library_web import insert_package, insert_package_item


def prepare_stable_package(env, package_id, message_id):
    with env.store.connect() as connection:
        connection.execute(
            "UPDATE channel_libraries SET status = 'ready' WHERE id = ?",
            (env.library["id"],),
        )
    insert_package_item(env.store, env.library["id"], package_id, message_id)
    env.app.channel_library_service.schedule_download_batch_threadsafe = lambda _id: None


def test_submit_creates_one_batch_and_leaves_selection_untouched(env):
    package_id = insert_package(env.store, env.library["id"], 10)
    prepare_stable_package(env, package_id, 10)
    env.store.set_package_selected_aggregate(package_id, True)
    before = env.store.selection_summary_aggregate()

    response = env.client.post(
        "/api/mcp/downloads",
        headers=auth(),
        json={"package_ids": [package_id], "idempotency_key": "mcp-1"},
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["created"] is True
    assert payload["batches"][0]["task_id"]
    assert env.store.selection_summary_aggregate() == before


def test_repeated_submit_returns_the_same_batch_without_creating(env):
    package_id = insert_package(env.store, env.library["id"], 10)
    prepare_stable_package(env, package_id, 10)
    body = {"package_ids": [package_id], "idempotency_key": "mcp-2"}

    first = env.client.post("/api/mcp/downloads", headers=auth(), json=body)
    second = env.client.post("/api/mcp/downloads", headers=auth(), json=body)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.get_json()["created"] is False
    assert (
        first.get_json()["batches"][0]["task_id"]
        == second.get_json()["batches"][0]["task_id"]
    )


def test_submit_rejects_unstable_package_with_state_conflict(env):
    package_id = insert_package(
        env.store, env.library["id"], 20, boundary_status="provisional"
    )

    response = env.client.post(
        "/api/mcp/downloads",
        headers=auth(),
        json={"package_ids": [package_id], "idempotency_key": "mcp-3"},
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "state_conflict"


def test_submit_requires_an_idempotency_key(env):
    package_id = insert_package(env.store, env.library["id"], 30)

    response = env.client.post(
        "/api/mcp/downloads", headers=auth(), json={"package_ids": [package_id]}
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_submit_requires_explicit_redownload_flag_type(env):
    package_id = insert_package(env.store, env.library["id"], 40)

    response = env.client.post(
        "/api/mcp/downloads",
        headers=auth(),
        json={
            "package_ids": [package_id],
            "idempotency_key": "mcp-4",
            "redownload": "yes",
        },
    )

    assert response.status_code == 400

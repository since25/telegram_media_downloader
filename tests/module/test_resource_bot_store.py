"""Persistent state contracts for the activated-user resource Bot."""

import os

import pytest

from module.resource_bot_store import ResourceBotStore


@pytest.fixture
def store(tmp_path):
    resource_store = ResourceBotStore(tmp_path / "resource_bot.sqlite3")
    resource_store.initialize()
    return resource_store


def activate_user(store, user_id, created_by=1):
    key = store.create_activation_key(created_by)
    assert store.redeem_activation_key(key, user_id) is True
    return key


def create_job(store, *, key="action-1", user_id=200, package_id=12):
    return store.create_delivery_job(
        idempotency_key=key,
        user_id=user_id,
        package_id=package_id,
        package_revision=3,
        target_chat_id=-1001,
        total_items=2,
    )


def test_initialize_creates_versioned_private_database(store):
    with store.connect() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]

    assert version == 1
    assert integrity == "ok"
    if os.name != "nt":
        assert (os.stat(store.path).st_mode & 0o777) == 0o600


def test_initialize_rejects_newer_database_schema(tmp_path):
    path = tmp_path / "future.sqlite3"
    store = ResourceBotStore(path)
    with store.connect() as connection:
        connection.execute("PRAGMA user_version = 999")

    with pytest.raises(RuntimeError, match="newer resource Bot database schema"):
        store.initialize()


def test_activation_key_is_hashed_and_redeems_once(store):
    key = store.create_activation_key(100)

    with store.connect() as connection:
        row = connection.execute(
            "SELECT key_hash, key_prefix, status FROM resource_activation_keys"
        ).fetchone()

    assert key not in row["key_hash"]
    assert key.startswith(row["key_prefix"])
    assert row["status"] == "available"
    assert store.redeem_activation_key(key, 200) is True
    assert store.redeem_activation_key(key, 201) is False
    assert store.is_user_active(200) is True
    assert store.is_user_active(201) is False


def test_invalid_activation_key_does_not_create_user(store):
    assert store.redeem_activation_key("invalid", 200) is False
    assert store.get_user(200) is None


def test_redeeming_new_key_reactivates_revoked_user(store):
    activate_user(store, 200)
    assert store.revoke_user(200) is True

    second_key = store.create_activation_key(100)

    assert store.redeem_activation_key(second_key, 200) is True
    assert store.is_user_active(200) is True


def test_bind_channel_requires_active_user(store):
    with pytest.raises(ValueError, match="activation_required"):
        store.bind_channel(200, -1001, "Target", "target")


def test_bind_channel_is_one_per_user_and_one_user_per_channel(store):
    activate_user(store, 200)
    activate_user(store, 201)

    first = store.bind_channel(200, -1001, "First", "first")
    replacement = store.bind_channel(200, -1002, "Second", None)

    assert first["chat_id"] == -1001
    assert replacement["chat_id"] == -1002
    assert store.get_binding(200)["title"] == "Second"
    with pytest.raises(ValueError, match="channel_already_bound"):
        store.bind_channel(201, -1002, "Second", None)


def test_permission_loss_and_unbind_are_persisted(store):
    activate_user(store, 200)
    store.bind_channel(200, -1001, "Target", "target")

    assert store.mark_binding_permission_lost(-1001) is True
    assert store.get_binding(200)["status"] == "permission_lost"
    assert store.unbind_channel(200) is True
    assert store.get_binding(200)["status"] == "unbound"


def test_delivery_job_creation_requires_active_user_and_binding(store):
    activate_user(store, 200)
    with pytest.raises(ValueError, match="channel_not_bound"):
        create_job(store)


def test_delivery_job_creation_is_idempotent(store):
    activate_user(store, 200)
    store.bind_channel(200, -1001, "Target", "target")

    first, created = create_job(store)
    replay, replay_created = create_job(store)

    assert created is True
    assert replay_created is False
    assert replay["id"] == first["id"]
    assert replay["public_id"] == first["public_id"]


def test_claim_progress_and_finish_delivery_job(store):
    activate_user(store, 200)
    store.bind_channel(200, -1001, "Target", "target")
    created, _ = create_job(store)

    claimed = store.claim_next_delivery_job()
    downloading = store.update_job_progress(
        claimed["id"], downloaded_items=1
    )
    uploading = store.update_job_progress(
        claimed["id"], status="uploading", uploaded_items=1
    )
    completed = store.finish_delivery_job(claimed["id"], "completed")

    assert claimed["id"] == created["id"]
    assert claimed["status"] == "downloading"
    assert downloading["downloaded_items"] == 1
    assert uploading["status"] == "uploading"
    assert uploading["uploaded_items"] == 1
    assert completed["status"] == "completed"
    assert completed["finished_at"] is not None


def test_recover_marks_active_jobs_failed_and_keeps_queued(store):
    activate_user(store, 200)
    store.bind_channel(200, -1001, "Target", "target")
    first, _ = create_job(store, key="active", package_id=12)
    second, _ = create_job(store, key="queued", package_id=13)
    assert store.claim_next_delivery_job()["id"] == first["id"]

    recovered = store.recover_interrupted_jobs()

    assert recovered == 1
    assert store.get_delivery_job(first["id"])["status"] == "failed"
    assert (
        store.get_delivery_job(first["id"])["error_code"]
        == "restart_interrupted"
    )
    assert store.get_delivery_job(second["id"])["status"] == "queued"


def test_revoke_user_deactivates_binding_and_cancels_queued_jobs(store):
    activate_user(store, 200)
    store.bind_channel(200, -1001, "Target", "target")
    job, _ = create_job(store, key="queued-action")

    assert store.revoke_user(200) is True

    assert store.is_user_active(200) is False
    assert store.get_binding(200)["status"] == "unbound"
    assert store.get_delivery_job(job["id"])["status"] == "cancelled"
    assert store.get_delivery_job(job["id"])["error_code"] == "activation_revoked"

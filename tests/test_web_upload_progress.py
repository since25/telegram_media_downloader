"""Tests for upload progress in Web task/file payloads."""
from module.task_state import FileSnapshot, FileStatus, TaskSnapshot, TaskStatus


def test_file_snapshot_exposes_upload_fields():
    f = FileSnapshot(
        message_id="1",
        status=FileStatus.UPLOADING,
        total_size=1000,
        uploaded_size=740,
        upload_speed=200,
    )
    d = f.to_dict()
    assert d["upload_progress"] == 74.0
    assert d["upload_speed"].endswith("/s")
    assert d["upload_speed_bytes"] == 200


def test_task_dashboard_row_has_upload_progress():
    t = TaskSnapshot(task_id="t1", status=TaskStatus.UPLOADING)
    t.files["1"] = FileSnapshot(
        message_id="1", status=FileStatus.UPLOADING, total_size=1000, uploaded_size=500
    )
    d = t.to_dict()
    assert "upload_progress" in d
    assert d["upload_progress"] == 50.0


def test_snapshot_node_maps_upload_state():
    from module.app import UploadProgressStat, UploadStatus
    from module.task_state import FileStatus, get_task_store, snapshot_node

    class _Node:
        pass

    node = _Node()
    node.task_id = "up-1"
    node.chat_id = -100
    node.download_status = {}
    node.upload_status = {7: UploadStatus.Uploading}
    node.upload_stat_dict = {
        7: UploadProgressStat(
            file_name="wall_31.jpg",
            total_size=1000,
            upload_size=600,
            start_time=0.0,
            last_stat_time=0.0,
            upload_speed=150,
        )
    }
    node.upload_success_count = 0
    snapshot_node(node)
    f = get_task_store().get_task("up-1").files["7"]
    assert f.status == FileStatus.UPLOADING
    assert f.uploaded_size == 600 and f.upload_speed == 150


def test_get_upload_list_returns_uploading_files(monkeypatch):
    import json

    import module.web as web
    from module.app import UploadProgressStat, UploadStatus

    class _Node:
        pass

    node = _Node()
    node.chat_id = -100
    node.upload_status = {5: UploadStatus.Uploading}
    node.upload_stat_dict = {
        5: UploadProgressStat(
            file_name="/d/wall_31.jpg",
            total_size=1000,
            upload_size=740,
            start_time=0.0,
            last_stat_time=0.0,
            upload_speed=200,
        )
    }
    monkeypatch.setattr(
        web, "get_active_task_nodes", lambda: {"up-1": node}, raising=False
    )

    app = web.get_flask_app()
    app.config["TESTING"] = True
    old_login_disabled = app.config.get("LOGIN_DISABLED")
    app.config["LOGIN_DISABLED"] = True
    try:
        with app.test_client() as client:
            resp = client.get("/get_upload_list")
    finally:
        app.config["LOGIN_DISABLED"] = old_login_disabled

    assert resp.status_code == 200
    rows = json.loads(resp.data)
    assert rows and rows[0]["filename"] == "wall_31.jpg"
    assert rows[0]["upload_progress"] == 74.0

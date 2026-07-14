"""Tests for upload progress in Web task/file payloads (rclone/cloud-drive model)."""
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


def test_snapshot_node_does_not_touch_cloud_upload_state():
    """snapshot_node no longer mirrors node.cloud_drive_upload_stat_dict into
    file status - that responsibility belongs to media_downloader.py, which
    calls upsert_file(..., status=FileStatus.UPLOADING/UPLOADED/UPLOAD_FAILED)
    directly around the actual upload. The cloud_drive_upload_stat_dict is
    still read live by get_upload_list/get_total_upload_speed (see below),
    just not mirrored into the task store by snapshot_node anymore."""
    from module.app import CloudDriveUploadStat
    from module.task_state import get_task_store, snapshot_node

    class _Node:
        pass

    node = _Node()
    node.task_id = "up-1"
    node.chat_id = -100
    node.download_status = {}
    node.cloud_drive_upload_stat_dict = {
        7: CloudDriveUploadStat(
            file_name="wall_31.jpg",
            transferred="6.0 MiB",
            total="10.0 MiB",
            percentage="60",
            speed="1.5 MiB/s",
            eta="3s",
        )
    }
    node.upload_success_count = 0
    snapshot_node(node)
    task = get_task_store().get_task("up-1")
    # No file entry was created from cloud_drive_upload_stat_dict.
    assert "7" not in task.files


def test_snapshot_node_preserves_existing_task_identity():
    """A Web-submitted prescan task (source=web, task_type=prescan) must keep
    that identity even when re-snapshotted from a node context that lacks
    task_source/task_display_type - the weak "bot"/"unknown" defaults must
    not downgrade an already-known identity (see snapshot_node's resolved_source/
    resolved_type fallback chain in module/task_state.py)."""
    from module.task_state import TaskStatus, get_task_store, snapshot_node

    store = get_task_store()
    store.create_task(
        task_id="web-1",
        source="web",
        task_type="prescan",
        chat_id=-200,
        title="prescan task",
        status=TaskStatus.SCANNING,
    )

    class _Node:
        pass

    node = _Node()
    node.task_id = "web-1"
    node.chat_id = -200
    node.download_status = {}
    # Deliberately no task_source / task_display_type on this node.

    snapshot_node(node)

    task = store.get_task("web-1")
    assert task.source == "web"
    assert task.task_type == "prescan"


def test_snapshot_node_defaults_new_task_to_bot_unknown():
    """Regression guard: a brand-new task (no existing store entry) with a
    bare node still falls back to source=bot/type=unknown as before."""
    from module.task_state import get_task_store, snapshot_node

    store = get_task_store()
    assert store.get_task("bot-1") is None

    class _Node:
        pass

    node = _Node()
    node.task_id = "bot-1"
    node.chat_id = -300
    node.download_status = {}

    snapshot_node(node)

    task = store.get_task("bot-1")
    assert task.source == "bot"
    assert task.task_type == "unknown"


def _build_cloud_upload_node():
    from module.app import CloudDriveUploadStat

    class _Node:
        pass

    node = _Node()
    node.chat_id = -100
    node.cloud_drive_upload_stat_dict = {
        5: CloudDriveUploadStat(
            file_name="/d/wall_31.jpg",
            transferred="7.4 MiB",
            total="10.0 MiB",
            percentage="74.20",
            speed="2.0 MiB/s",
            eta="1s",
        )
    }
    return node


def test_get_upload_list_returns_uploading_files(monkeypatch):
    import json
    from types import SimpleNamespace

    import module.web as web

    node = _build_cloud_upload_node()
    monkeypatch.setattr(
        web, "get_active_task_nodes", lambda: {"up-1": node}, raising=False
    )
    monkeypatch.setattr(
        web, "_current_app", SimpleNamespace(hide_file_name=False), raising=False
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
    # total_size/upload_speed are rclone-formatted strings, passed through as-is.
    assert rows[0]["total_size"] == "10.0 MiB"
    assert rows[0]["upload_speed"] == "2.0 MiB/s"
    assert rows[0]["upload_progress"] == 74.2


def test_get_upload_list_masks_filename_when_hide_file_name_enabled(monkeypatch):
    import json
    from types import SimpleNamespace

    import module.web as web

    node = _build_cloud_upload_node()
    monkeypatch.setattr(
        web, "get_active_task_nodes", lambda: {"up-1": node}, raising=False
    )
    monkeypatch.setattr(
        web, "_current_app", SimpleNamespace(hide_file_name=True), raising=False
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
    assert rows and rows[0]["filename"] == "****.jpg"


def test_get_total_upload_speed_sums_parsed_cloud_speeds(monkeypatch):
    from module.app import CloudDriveUploadStat
    import module.download_stat as download_stat

    class _Node:
        pass

    node_a = _Node()
    node_a.cloud_drive_upload_stat_dict = {
        1: CloudDriveUploadStat(
            file_name="a.jpg",
            transferred="1 MiB",
            total="2 MiB",
            percentage="50",
            speed="1.5 MiB/s",
            eta="1s",
        )
    }
    node_b = _Node()
    node_b.cloud_drive_upload_stat_dict = {
        2: CloudDriveUploadStat(
            file_name="b.jpg",
            transferred="512 KiB",
            total="1 MiB",
            percentage="50",
            speed="512 KiB/s",
            eta="1s",
        )
    }

    monkeypatch.setattr(
        download_stat,
        "get_active_task_nodes",
        lambda: {"a": node_a, "b": node_b},
        raising=False,
    )

    expected = int(1.5 * 1024 * 1024) + 512 * 1024
    assert download_stat.get_total_upload_speed() == expected


def test_rclone_upload_success_pops_cloud_stat_entry(monkeypatch):
    """Part A: once rclone reports 100% success, the finished message's
    display-cache entry must be removed so it doesn't linger as "uploading"
    forever (rclone's 100% line never hits the progress_callback branch that
    would otherwise update it)."""
    import asyncio

    from module.app import CloudDriveUploadStat
    from module.cloud_drive import CloudDrive, CloudDriveConfig

    class _FakeStdout:
        def __init__(self, lines):
            self._lines = lines

        def __aiter__(self):
            return self._gen()

        async def _gen(self):
            for line in self._lines:
                yield line.encode()

    class _FakeProc:
        def __init__(self, lines):
            self.stdout = _FakeStdout(lines)

        async def wait(self):
            return 0

    async def _fake_create_subprocess_shell(*_args, **_kwargs):
        return _FakeProc(["Transferred: 1 / 1, 100%, , ETA 0s\n"])

    monkeypatch.setattr(
        asyncio, "create_subprocess_shell", _fake_create_subprocess_shell
    )
    monkeypatch.setattr(CloudDrive, "rclone_mkdir", lambda *a, **k: None)

    class _Node:
        pass

    node = _Node()
    node.cloud_drive_upload_stat_dict = {
        42: CloudDriveUploadStat(
            file_name="file.txt",
            transferred="9 MiB",
            total="10 MiB",
            percentage="90",
            speed="1 MiB/s",
            eta="1s",
        )
    }

    drive_config = CloudDriveConfig(
        after_upload_file_delete=False, before_upload_file_zip=False
    )

    result = asyncio.run(
        CloudDrive.rclone_upload_file(
            drive_config,
            "/tmp",
            "/tmp/file.txt",
            progress_callback=None,
            progress_args=(node, 42, "file.txt"),
        )
    )

    assert result is True
    assert 42 not in node.cloud_drive_upload_stat_dict

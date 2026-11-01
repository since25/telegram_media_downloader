from types import SimpleNamespace

from module.file_cleanup import reconcile_download_files
from module.task_state import FileStatus, TaskStateStore


class _Logger:
    def __init__(self):
        self.messages = []

    def info(self, message, *args):
        self.messages.append((message, args))

    def warning(self, message, *args):
        self.messages.append((message, args))


def test_startup_reconciliation_cleans_temp_and_confirmed_uploads(tmp_path):
    temp_root = tmp_path / "temp"
    save_root = tmp_path / "downloads"
    (temp_root / "old" / "nested.bin").parent.mkdir(parents=True)
    (temp_root / "old" / "nested.bin").write_bytes(b"partial")
    uploaded = save_root / "uploaded.bin"
    uploaded.parent.mkdir()
    uploaded.write_bytes(b"uploaded")
    retained = save_root / "retained.bin"
    retained.write_bytes(b"keep")

    store = TaskStateStore(storage_path=tmp_path / "tasks.sqlite3")
    store.create_task("uploaded-task")
    store.upsert_file(
        "uploaded-task", 1, status=FileStatus.UPLOADED, save_path=str(uploaded)
    )
    store.create_task("failed-task")
    store.upsert_file(
        "failed-task", 2, status=FileStatus.UPLOAD_FAILED, save_path=str(retained)
    )

    report = reconcile_download_files(
        SimpleNamespace(
            temp_save_path=str(temp_root),
            save_path=str(save_root),
            cloud_drive_config=SimpleNamespace(
                enable_upload_file=True,
                after_upload_file_delete=True,
            ),
        ),
        store,
        _Logger(),
    )

    assert report.temp_files_removed == 1
    assert report.temp_dirs_removed == 1
    assert report.uploaded_files_removed == 1
    assert not (temp_root / "old" / "nested.bin").exists()
    assert not uploaded.exists()
    assert retained.exists()


def test_startup_reconciliation_retains_uploaded_files_when_deletion_disabled(tmp_path):
    save_root = tmp_path / "downloads"
    uploaded = save_root / "uploaded.bin"
    save_root.mkdir()
    uploaded.write_bytes(b"uploaded")
    store = TaskStateStore(storage_path=tmp_path / "tasks.sqlite3")
    store.create_task("task")
    store.upsert_file("task", 1, status=FileStatus.UPLOADED, save_path=str(uploaded))

    report = reconcile_download_files(
        SimpleNamespace(
            temp_save_path=str(tmp_path / "temp"),
            save_path=str(save_root),
            cloud_drive_config=SimpleNamespace(
                enable_upload_file=True,
                after_upload_file_delete=False,
            ),
        ),
        store,
        _Logger(),
    )

    assert report.uploaded_files_removed == 0
    assert uploaded.exists()


def test_startup_reconciliation_never_deletes_outside_save_root(tmp_path):
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"keep")
    save_root = tmp_path / "downloads"
    save_root.mkdir()
    store = TaskStateStore(storage_path=tmp_path / "tasks.sqlite3")
    store.create_task("task")
    store.upsert_file("task", 1, status=FileStatus.UPLOADED, save_path=str(outside))

    report = reconcile_download_files(
        SimpleNamespace(
            temp_save_path=str(tmp_path / "temp"),
            save_path=str(save_root),
            cloud_drive_config=SimpleNamespace(
                enable_upload_file=True,
                after_upload_file_delete=True,
            ),
        ),
        store,
        _Logger(),
    )

    assert report.uploaded_files_removed == 0
    assert report.cleanup_failures == 1
    assert outside.exists()

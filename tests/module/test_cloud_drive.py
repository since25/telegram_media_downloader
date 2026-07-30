import asyncio
from pathlib import Path
from types import SimpleNamespace


class _FakeStdout:
    def __init__(self, lines):
        self._lines = tuple(lines)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for line in self._lines:
            yield line.encode()


class _FakeProcess:
    def __init__(self, lines=(), returncode=0):
        self.stdout = _FakeStdout(lines)
        self.returncode = returncode

    async def wait(self):
        return self.returncode


def test_rclone_mkdir_uses_argument_array_and_return_code(monkeypatch):
    import module.cloud_drive as cloud_drive

    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(cloud_drive.subprocess, "run", fake_run, raising=False)
    config = cloud_drive.CloudDriveConfig(rclone_path="/opt/rclone binary")

    assert cloud_drive.CloudDrive.rclone_mkdir(
        config, "remote:/folder with spaces;$(touch nope)"
    )
    assert calls[0][0] == [
        "/opt/rclone binary",
        "mkdir",
        "remote:/folder with spaces;$(touch nope)",
    ]
    assert calls[0][1]["check"] is False


def test_rclone_upload_uses_exec_and_return_code_success(monkeypatch, tmp_path):
    import module.cloud_drive as cloud_drive

    local_file = tmp_path / "odd name 'quoted';$(touch nope).txt"
    local_file.write_text("payload", encoding="utf-8")
    calls = []

    async def fake_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeProcess(["Transferred: 7 / 9, 77%, 1 MiB/s, ETA 1s\n"], 0)

    async def reject_shell(*_args, **_kwargs):
        raise AssertionError("shell execution is forbidden")

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(asyncio, "create_subprocess_shell", reject_shell)
    monkeypatch.setattr(
        cloud_drive.CloudDrive,
        "rclone_mkdir",
        lambda *_args, **_kwargs: True,
    )
    config = cloud_drive.CloudDriveConfig(
        rclone_path="/opt/rclone binary",
        remote_dir="remote:/folder with spaces",
        after_upload_file_delete=True,
    )
    progress = []

    async def record_progress(*args):
        progress.append(args)

    result = asyncio.run(
        cloud_drive.CloudDrive.rclone_upload_file(
            config,
            str(tmp_path),
            str(local_file),
            progress_callback=record_progress,
        )
    )

    assert result is True
    assert local_file.exists() is False
    assert config.total_upload_success_file_count == 1
    assert calls[0][0] == (
        "/opt/rclone binary",
        "copy",
        str(local_file),
        "remote:/folder with spaces/",
        "--create-empty-src-dirs",
        "--ignore-existing",
        "--progress",
    )
    assert progress


def test_rclone_failure_keeps_source_and_does_not_cache_directory(
    monkeypatch, tmp_path
):
    import module.cloud_drive as cloud_drive

    local_file = tmp_path / "source.bin"
    local_file.write_bytes(b"payload")
    config = cloud_drive.CloudDriveConfig(
        remote_dir="remote:/target",
        after_upload_file_delete=True,
    )
    monkeypatch.setattr(
        cloud_drive.CloudDrive,
        "rclone_mkdir",
        lambda *_args, **_kwargs: False,
    )

    result = asyncio.run(
        cloud_drive.CloudDrive.rclone_upload_file(
            config,
            str(tmp_path),
            str(local_file),
        )
    )

    assert result is False
    assert local_file.exists()
    assert config.dir_cache == {}


def test_nonzero_copy_exit_keeps_source_even_with_success_text(monkeypatch, tmp_path):
    import module.cloud_drive as cloud_drive

    local_file = tmp_path / "source.bin"
    local_file.write_bytes(b"payload")

    async def fake_exec(*_args, **_kwargs):
        return _FakeProcess(["Transferred: 1 / 1, 100%, 1 MiB/s, ETA 0s\n"], 7)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    monkeypatch.setattr(
        cloud_drive.CloudDrive,
        "rclone_mkdir",
        lambda *_args, **_kwargs: True,
    )
    config = cloud_drive.CloudDriveConfig(
        remote_dir="remote:/target",
        after_upload_file_delete=True,
    )

    result = asyncio.run(
        cloud_drive.CloudDrive.rclone_upload_file(
            config,
            str(tmp_path),
            str(local_file),
        )
    )

    assert result is False
    assert local_file.exists()
    assert config.total_upload_success_file_count == 0

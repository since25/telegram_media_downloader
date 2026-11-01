import asyncio


def test_cloud_upload_can_defer_source_deletion(monkeypatch, tmp_path):
    import module.cloud_drive as cloud_drive

    source = tmp_path / "source.bin"
    source.write_bytes(b"payload")

    async def fake_exec(*_args, **_kwargs):
        return cloud_drive_test_process()

    def cloud_drive_test_process():
        class Process:
            stdout = None
            returncode = 0

            async def wait(self):
                return 0

        return Process()

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

    with cloud_drive.defer_local_file_delete():
        result = asyncio.run(
            cloud_drive.CloudDrive.rclone_upload_file(
                config,
                str(tmp_path),
                str(source),
            )
        )

    assert result is True
    assert source.exists()

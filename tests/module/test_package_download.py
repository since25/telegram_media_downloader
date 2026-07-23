import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from pyrogram.errors import FloodWait

import module.task_state as task_state_module
from module.app import DownloadStatus
from module.download_transfer import TransferRuntime, transfer_media
from module.package_download import build_package_result
from module.task_state import FileStatus, TaskStateStore


def test_partial_package_result_is_completed_with_errors(tmp_path):
    store = TaskStateStore(storage_path=Path(tmp_path) / "tasks.sqlite3")
    store.create_task("partial-package")
    store.upsert_file("partial-package", 101, status=FileStatus.DOWNLOADED)
    store.upsert_file("partial-package", 102, status=FileStatus.FAILED)
    package = SimpleNamespace(
        attempt_id=501,
        package_id=51,
        expected_message_ids=(101, 102),
        failed_message_ids=[],
        items=[],
        not_found_message_ids=set(),
    )
    node = SimpleNamespace(
        task_id="partial-package",
        is_stop_transmission=False,
        skip_not_found_message_ids=set(),
        completed_file_skip_message_ids=set(),
    )

    previous_store = task_state_module._TASK_STORE
    task_state_module._TASK_STORE = store
    try:
        result = build_package_result(package, node)
    finally:
        task_state_module._TASK_STORE = previous_store

    assert result.status == "completed_with_errors"
    assert result.message_results[101].status == "completed"
    assert result.message_results[102].status == "failed"


def test_external_transfer_cancellation_is_not_retried(tmp_path):
    async def run_scenario():
        started = asyncio.Event()

        class BlockingClient:
            async def download_media(self, *_args, **_kwargs):
                started.set()
                await asyncio.Event().wait()

        async def fetch_message(_client, message):
            return message

        async def get_media_meta(*_args, **_kwargs):
            return (
                str(tmp_path / "final.bin"),
                str(tmp_path / "temp.bin"),
                "octet-stream",
            )

        loop = asyncio.get_running_loop()
        runtime = TransferRuntime(
            app=SimpleNamespace(loop=loop, hide_file_name=False),
            logger=Mock(),
            translate=lambda value: value,
            fetch_message=fetch_message,
            get_media_meta=get_media_meta,
            record_message_marker=lambda *_args: None,
            can_download=lambda *_args: True,
            is_file=lambda _path: False,
            check_download_finish=lambda *_args: None,
            move_to_download_path=lambda *_args: None,
            retry_timed_out=lambda *_args: False,
            update_download_status=lambda *_args: None,
            get_download_result=lambda: {},
            retry_timeout=0,
            stall_timeout=600,
            last_progress_ts={},
            last_progress_bytes={},
            stalled_message_ids=set(),
        )
        message = SimpleNamespace(
            id=99,
            empty=False,
            document=SimpleNamespace(file_size=1),
        )
        node = SimpleNamespace(chat_id=-100, skip_not_found_download_task=0)
        task = asyncio.create_task(
            transfer_media(
                BlockingClient(),
                message,
                ["document"],
                {"document": ["all"]},
                node,
                None,
                runtime,
            )
        )
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert not runtime.stalled_message_ids

    asyncio.run(run_scenario())


def test_flood_wait_uses_server_delay_then_retries(tmp_path):
    async def run_scenario():
        class FloodWaitClient:
            def __init__(self):
                self.calls = 0

            async def download_media(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise FloodWait(0)
                return str(tmp_path / "temp.bin")

        async def fetch_message(_client, message):
            return message

        async def get_media_meta(*_args, **_kwargs):
            return (
                str(tmp_path / "final.bin"),
                str(tmp_path / "temp.bin"),
                "octet-stream",
            )

        client = FloodWaitClient()
        runtime = TransferRuntime(
            app=SimpleNamespace(loop=asyncio.get_running_loop(), hide_file_name=False),
            logger=Mock(),
            translate=lambda value: value,
            fetch_message=fetch_message,
            get_media_meta=get_media_meta,
            record_message_marker=lambda *_args: None,
            can_download=lambda *_args: True,
            is_file=lambda _path: False,
            check_download_finish=lambda *_args: None,
            move_to_download_path=lambda *_args: None,
            retry_timed_out=lambda *_args: False,
            update_download_status=lambda *_args: None,
            get_download_result=lambda: {},
            retry_timeout=0,
            stall_timeout=600,
            last_progress_ts={},
            last_progress_bytes={},
            stalled_message_ids=set(),
        )
        message = SimpleNamespace(
            id=100,
            empty=False,
            document=SimpleNamespace(file_size=1),
        )
        node = SimpleNamespace(chat_id=-100, skip_not_found_download_task=0)

        status, path = await transfer_media(
            client,
            message,
            ["document"],
            {"document": ["all"]},
            node,
            None,
            runtime,
        )

        assert status is DownloadStatus.SuccessDownload
        assert path == str(tmp_path / "final.bin")
        assert client.calls == 2

    asyncio.run(run_scenario())

"""媒体会话假死后的自愈契约。

Pyrogram 的 get_file 会吞掉媒体会话里的异常并返回空文件，
会话一旦坏掉就会被一直缓存复用，进程不重启就永远下不动。
"""

import asyncio
import unittest
from unittest import mock

from module import download_transfer
from module.download_transfer import (
    EmptyDownloadError,
    check_download_finish,
    note_download_success,
    note_empty_download,
    reset_media_sessions,
)


class _Logger:
    def __init__(self):
        self.warnings = []

    def warning(self, message, *_args, **_kwargs):
        self.warnings.append(str(message))

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class _Session:
    def __init__(self):
        self.stopped = False

    async def stop(self):
        self.stopped = True


class _Client:
    def __init__(self, dc_ids=(2, 4)):
        self.media_sessions = {dc_id: _Session() for dc_id in dc_ids}


class _HangingSession(_Session):
    async def stop(self):
        await asyncio.sleep(3600)


def _reset_module_state():
    download_transfer._empty_download_streak = 0
    download_transfer._last_media_session_reset = 0.0


class EmptyDownloadDetectionTestCase(unittest.TestCase):
    def test_zero_byte_result_raises_empty_download_error(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            empty_file = Path(tmp_dir) / "empty.mp4"
            empty_file.write_bytes(b"")

            with self.assertRaises(EmptyDownloadError):
                check_download_finish(
                    1024, str(empty_file), "empty.mp4", _Logger(), lambda text: text
                )

    def test_short_but_non_empty_result_stays_a_plain_value_error(self):
        """只写了一半的文件是普通的大小不符，不该触发会话重建。"""

        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp_dir:
            partial_file = Path(tmp_dir) / "partial.mp4"
            partial_file.write_bytes(b"x" * 10)

            with self.assertRaises(ValueError) as caught:
                check_download_finish(
                    1024, str(partial_file), "partial.mp4", _Logger(), lambda text: text
                )

            self.assertNotIsInstance(caught.exception, EmptyDownloadError)


class MediaSessionResetTestCase(unittest.TestCase):
    def setUp(self):
        _reset_module_state()
        self.addCleanup(_reset_module_state)

    def test_reset_stops_and_drops_cached_sessions(self):
        client = _Client()
        sessions = list(client.media_sessions.values())

        closed = asyncio.run(reset_media_sessions(client, _Logger()))

        self.assertEqual(closed, 2)
        self.assertEqual(client.media_sessions, {})
        self.assertTrue(all(session.stopped for session in sessions))

    def test_reset_does_not_hang_on_a_wedged_session(self):
        """会话已经卡死时，停止旧会话不能把调用方一起挂住。"""

        client = _Client(dc_ids=())
        client.media_sessions[2] = _HangingSession()

        async def scenario():
            return await asyncio.wait_for(
                reset_media_sessions(client, _Logger()), timeout=30
            )

        with mock.patch.object(
            download_transfer, "MEDIA_SESSION_STOP_TIMEOUT", 0.05
        ):
            closed = asyncio.run(scenario())

        self.assertEqual(closed, 1)
        self.assertEqual(client.media_sessions, {})

    def test_reset_triggers_only_after_the_streak_threshold(self):
        client = _Client()
        logger = _Logger()

        async def scenario():
            results = []
            for _ in range(download_transfer.EMPTY_DOWNLOAD_RESET_THRESHOLD):
                results.append(await note_empty_download(client, logger))
            return results

        results = asyncio.run(scenario())

        self.assertEqual(
            results[:-1],
            [False] * (download_transfer.EMPTY_DOWNLOAD_RESET_THRESHOLD - 1),
        )
        self.assertTrue(results[-1])
        self.assertEqual(client.media_sessions, {})

    def test_a_successful_download_clears_the_streak(self):
        client = _Client()
        logger = _Logger()

        async def scenario():
            for _ in range(download_transfer.EMPTY_DOWNLOAD_RESET_THRESHOLD - 1):
                await note_empty_download(client, logger)
            note_download_success()
            return await note_empty_download(client, logger)

        triggered = asyncio.run(scenario())

        self.assertFalse(triggered)
        self.assertEqual(len(client.media_sessions), 2)

    def test_cooldown_prevents_back_to_back_resets(self):
        client = _Client()
        logger = _Logger()
        threshold = download_transfer.EMPTY_DOWNLOAD_RESET_THRESHOLD

        async def scenario():
            for _ in range(threshold):
                await note_empty_download(client, logger)
            client.media_sessions[2] = _Session()
            results = []
            for _ in range(threshold):
                results.append(await note_empty_download(client, logger))
            return results

        results = asyncio.run(scenario())

        self.assertNotIn(True, results)
        self.assertIn(2, client.media_sessions)


class TransferMediaSelfHealTestCase(unittest.TestCase):
    """端到端：下载持续返回空文件时，transfer_media 会触发媒体会话重建。"""

    def setUp(self):
        _reset_module_state()
        self.addCleanup(_reset_module_state)

    def _run_transfer(self, client, temp_dir):
        import os
        import time
        from types import SimpleNamespace

        from module.download_transfer import (
            TransferRuntime,
            can_download,
            is_file,
            move_to_download_path,
            retry_timed_out,
            transfer_media,
        )
        from module.transfer_progress import TransferProgressTracker

        temp_file_name = os.path.join(temp_dir, "temp.mp4")
        file_name = os.path.join(temp_dir, "final.mp4")
        message = SimpleNamespace(id=901, video=SimpleNamespace(file_size=2048))
        node = SimpleNamespace(chat_id=-1007, skip_not_found_download_task=0)

        async def fetch_message(_client, msg):
            return msg

        async def get_media_meta(*_args, **_kwargs):
            return file_name, temp_file_name, "mp4"

        logger = _Logger()

        async def scenario():
            runtime = TransferRuntime(
                app=SimpleNamespace(
                    hide_file_name=False,
                    loop=asyncio.get_running_loop(),
                ),
                logger=logger,
                translate=lambda text: text,
                fetch_message=fetch_message,
                get_media_meta=get_media_meta,
                record_message_marker=lambda *_args, **_kwargs: None,
                can_download=can_download,
                is_file=is_file,
                check_download_finish=lambda size, path, name: check_download_finish(
                    size, path, name, logger, lambda text: text
                ),
                move_to_download_path=move_to_download_path,
                retry_timed_out=retry_timed_out,
                update_download_status=lambda *_args, **_kwargs: None,
                remove_download_result=lambda *_args, **_kwargs: None,
                retry_timeout=0,
                stall_timeout=600,
                progress_tracker=TransferProgressTracker(),
            )
            return await transfer_media(
                client,
                message,
                ["video"],
                {"video": ["all"]},
                node,
                None,
                runtime,
            )

        real_sleep = asyncio.sleep

        async def fast_sleep(delay, *args, **kwargs):
            # 重试退避在测试里没有意义，压到接近零以保持用例快速
            return await real_sleep(min(delay, 0.001), *args, **kwargs)

        started = time.monotonic()
        with mock.patch.object(asyncio, "sleep", fast_sleep):
            status, _ = asyncio.run(scenario())
        return status, time.monotonic() - started

    def test_repeated_empty_downloads_rebuild_media_sessions(self):
        import tempfile

        from module.app import DownloadStatus

        threshold = download_transfer.EMPTY_DOWNLOAD_RESET_THRESHOLD

        class _EmptyDownloadClient(_Client):
            """模拟假死的媒体会话：始终返回一个 0 字节文件。"""

            def __init__(self, temp_path):
                super().__init__()
                self.temp_path = temp_path
                self.calls = 0

            async def download_media(self, *_args, **kwargs):
                self.calls += 1
                path = kwargs.get("file_name") or self.temp_path
                with open(path, "wb"):
                    pass
                return path

        with tempfile.TemporaryDirectory() as tmp_dir:
            client = _EmptyDownloadClient(None)
            # transfer_media 每个文件最多重试 3 次，跑够次数才能越过阈值
            statuses = []
            for _ in range((threshold // 3) + 1):
                status, _elapsed = self._run_transfer(client, tmp_dir)
                statuses.append(status)

            self.assertTrue(
                all(status is DownloadStatus.FailedDownload for status in statuses)
            )
            self.assertGreaterEqual(client.calls, threshold)
            self.assertEqual(client.media_sessions, {})


if __name__ == "__main__":
    unittest.main()

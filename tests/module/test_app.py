"""test app"""

import os
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

import module.app
from module.app import Application, ChatDownloadConfig, DownloadStatus

sys.path.append("..")  # Adds higher directory to python modules path.


def test_channel_library_config_is_clamped():
    app = Application("", "")
    app.assign_config(
        {
            "api_id": "",
            "api_hash": "",
            "media_types": [],
            "file_formats": {},
            "channel_library": {
                "full_scan_batch_size": 999,
                "full_scan_delay_min_sec": 0,
                "incremental_scan_delay_min_sec": 0,
                "incremental_scan_cron": "*/15 * * * *",
                "incremental_scan_timezone": "Asia/Shanghai",
            },
        }
    )

    assert app.channel_library_config.full_scan_batch_size == 100
    assert app.channel_library_config.full_scan_delay_min_sec == 2.0
    assert app.channel_library_config.incremental_scan_delay_min_sec == 0.5
    assert not hasattr(app.channel_library_config, "incremental_scan_cron")
    assert not hasattr(app.channel_library_config, "incremental_scan_timezone")


def test_resource_bot_token_defaults_empty():
    app = Application("", "")

    assert app.resource_bot_token == ""
    assert app.resource_staging_chat_id == 0


def test_resource_bot_token_loads_from_config():
    app = Application("", "")

    app.assign_config(
        {
            "api_id": "",
            "api_hash": "",
            "bot_token": "admin-token",
            "resource_bot_token": "resource-token",
            "resource_staging_chat_id": -1009,
            "media_types": [],
            "file_formats": {},
        }
    )

    assert app.bot_token == "admin-token"
    assert app.resource_bot_token == "resource-token"
    assert app.resource_staging_chat_id == -1009


class AppTestCase(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        config_test = os.path.join(os.path.abspath("."), "config_test.yaml")
        data_test = os.path.join(os.path.abspath("."), "data_test.yaml")
        if os.path.exists(config_test):
            os.remove(config_test)
        if os.path.exists(data_test):
            os.remove(data_test)

    def test_app(self):
        app = Application("", "")
        self.assertEqual(app.save_path, os.path.join(os.path.abspath("."), "downloads"))
        self.assertEqual(app.proxy, {})
        self.assertEqual(app.restart_program, False)

        app.chat_download_config[123] = ChatDownloadConfig()
        app.chat_download_config[123].last_read_message_id = 13
        app.chat_download_config[123].node.download_status[
            6
        ] = DownloadStatus.Downloading
        app.chat_download_config[123].ids_to_retry.append(7)
        # download success
        app.chat_download_config[123].node.download_status[
            8
        ] = DownloadStatus.SuccessDownload
        app.chat_download_config[123].finish_task += 1
        # download success
        app.chat_download_config[123].node.download_status[
            10
        ] = DownloadStatus.SuccessDownload
        app.chat_download_config[123].finish_task += 1
        # not exist message
        app.chat_download_config[123].node.download_status[
            13
        ] = DownloadStatus.SuccessDownload
        app.config["chat"] = [{"chat_id": 123, "last_read_message_id": 5}]

        app.update_config(False)

        self.assertEqual(
            app.chat_download_config[123].last_read_message_id + 1,
            app.config["chat"][0]["last_read_message_id"],
        )
        self.assertEqual(
            [6, 7],
            app.app_data["chat"][0]["ids_to_retry"],
        )

    @mock.patch("module.app.atomic_write_yaml")
    def test_update_config(self, mock_atomic_write):
        app = Application("", "")
        app.config_file = "config_test.yaml"
        app.app_data_file = "data_test.yaml"
        app.config["chat"] = [{"chat_id": 123, "last_read_message_id": 0}]
        app.update_config()
        self.assertEqual(mock_atomic_write.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in mock_atomic_write.call_args_list],
            [
                module.app.Path("config_test.yaml"),
                module.app.Path("data_test.yaml"),
            ],
        )

    @mock.patch("module.app.atomic_write_yaml")
    def test_update_config_serializes_concurrent_writes(self, mock_atomic_write):
        active_writes = 0
        max_active_writes = 0
        counter_lock = threading.Lock()

        def record_write(*_args, **_kwargs):
            nonlocal active_writes, max_active_writes
            with counter_lock:
                active_writes += 1
                max_active_writes = max(max_active_writes, active_writes)
            time.sleep(0.02)
            with counter_lock:
                active_writes -= 1

        mock_atomic_write.side_effect = record_write
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = Application(
                os.path.join(tmp_dir, "config.yaml"),
                os.path.join(tmp_dir, "data.yaml"),
            )
            app.config = {"chat": []}
            app.app_data = {}
            workers = [threading.Thread(target=app.update_config) for _ in range(2)]

            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=2)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(max_active_writes, 1)
        self.assertEqual(mock_atomic_write.call_count, 4)

"""Tests for the Flask web control surface."""

import json
import os
import tempfile
import unittest

from module.app import Application


def build_web_test_app(tmp_dir):
    """Build a minimal configured application for web endpoint tests."""

    app = Application(
        os.path.join(tmp_dir, "config.yaml"),
        os.path.join(tmp_dir, "app_data.yaml"),
    )
    app.config = {
        "api_id": "1",
        "api_hash": "hash",
        "bot_token": "",
        "chat": [{"chat_id": "me", "last_read_message_id": 7}],
        "media_types": ["audio", "photo", "video", "document"],
        "file_formats": {
            "audio": ["all"],
            "document": ["all"],
            "video": ["all"],
        },
        "file_path_prefix": ["chat_title", "media_datetime"],
        "file_name_prefix": ["message_id", "file_name"],
        "save_path": os.path.join(tmp_dir, "downloads"),
    }
    app.assign_config(app.config)
    return app


class WebTestCase(unittest.TestCase):
    def setUp(self):
        from module import web as web_module
        from module.task_state import get_task_store

        self.web_module = web_module
        self.old_auth_env = os.environ.get(web_module.WEB_AUTH_FILE_ENV)
        self.old_current_app = web_module._current_app
        self.old_login_disabled = web_module._flask_app.config.get("LOGIN_DISABLED")
        web_module._flask_app.config["TESTING"] = True
        get_task_store().clear()

    def tearDown(self):
        if self.old_auth_env is None:
            os.environ.pop(self.web_module.WEB_AUTH_FILE_ENV, None)
        else:
            os.environ[self.web_module.WEB_AUTH_FILE_ENV] = self.old_auth_env
        self.web_module._current_app = self.old_current_app
        self.web_module._flask_app.config["LOGIN_DISABLED"] = self.old_login_disabled
        from module.task_state import get_task_store

        get_task_store().clear()

    def test_web_auth_generates_local_password_and_allows_login(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            auth_file = os.path.join(tmp_dir, "web_auth.json")
            os.environ[self.web_module.WEB_AUTH_FILE_ENV] = auth_file
            app = build_web_test_app(tmp_dir)
            app.web_login_secret = ""

            self.web_module._ensure_web_auth(app)

            with open(auth_file, encoding="utf-8") as handle:
                auth_data = json.load(handle)
            self.assertEqual(auth_data["username"], "root")
            self.assertTrue(auth_data["password"])
            self.assertEqual(auth_data["password_source"], "local")

            encrypted_password = self.web_module.deAesCrypt.encrypt(
                auth_data["password"]
            ).decode("utf-8")
            client = self.web_module.get_flask_app().test_client()
            response = client.post("/login", data={"password": encrypted_password})

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["code"], "1")

    def test_web_settings_updates_download_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.post(
                "/api/settings",
                json={
                    "save_path": os.path.join(tmp_dir, "new_downloads"),
                    "media_types": ["video", "document"],
                    "file_formats": {
                        "audio": ["mp3"],
                        "document": ["pdf", "zip"],
                        "video": ["mp4"],
                    },
                    "file_path_prefix": ["chat_title"],
                    "file_name_prefix": ["message_id", "caption"],
                    "file_name_prefix_split": " - ",
                    "max_download_task": 8,
                    "max_concurrent_transmissions": 24,
                    "start_timeout": 120,
                    "date_format": "%Y_%m_%d",
                    "hide_file_name": True,
                    "drop_no_audio_video": True,
                    "enable_download_txt": True,
                    "after_upload_telegram_delete": False,
                    "upload_drive": {
                        "enable_upload_file": False,
                        "upload_adapter": "rclone",
                        "rclone_path": "/usr/bin/rclone",
                        "remote_dir": "remote:/tg",
                        "before_upload_file_zip": False,
                        "after_upload_file_delete": False,
                    },
                    "web": {
                        "enable_web": True,
                        "web_host": "0.0.0.0",
                        "web_port": 80,
                    },
                    "chats": [
                        {
                            "chat_id": "me",
                            "last_read_message_id": 9,
                            "download_filter": "media_type == 'video'",
                            "upload_telegram_chat_id": "",
                        }
                    ],
                },
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertTrue(payload["restart_required"])
            self.assertEqual(app.max_download_task, 8)
            self.assertEqual(app.cloud_drive_config.remote_dir, "remote:/tg")
            self.assertFalse(app.cloud_drive_config.after_upload_file_delete)
            self.assertEqual(
                app.chat_download_config["me"].download_filter,
                "media_type == 'video'",
            )

            with open(app.config_file, encoding="utf-8") as handle:
                saved_config = handle.read()
            self.assertIn("enable_web: true", saved_config)
            self.assertIn("web_port: 80", saved_config)
            self.assertIn("after_upload_file_delete: false", saved_config)

    def test_task_dashboard_returns_task_summary(self):
        from module.task_state import FileStatus, TaskStatus, get_task_store

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            store = get_task_store()
            task = store.create_task(
                task_id=99,
                source="bot",
                task_type="package",
                chat_id=-1001,
                title="demo",
                status=TaskStatus.DOWNLOADING,
                total_count=1,
            )
            store.upsert_file(
                task.task_id,
                501,
                status=FileStatus.DOWNLOADING,
                filename="/data/tg/demo.mp4",
                total_size=100,
                downloaded_size=50,
                download_speed=10,
            )

            client = self.web_module.get_flask_app().test_client()
            response = client.get("/api/task-dashboard")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["active_task_count"], 1)
            self.assertEqual(payload["completed_task_count"], 0)
            self.assertEqual(payload["tasks"][0]["task_id"], "99")
            self.assertEqual(
                payload["tasks"][0]["current_file"]["filename"], "demo.mp4"
            )
            self.assertEqual(
                payload["tasks"][0]["current_file"]["download_progress"], 50.0
            )

    def test_task_detail_returns_files(self):
        from module.task_state import FileStatus, TaskStatus, get_task_store

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            store = get_task_store()
            task = store.create_task(
                task_id="web-1",
                source="web",
                task_type="comment",
                status=TaskStatus.QUEUED,
            )
            store.upsert_file(task.task_id, 11, status=FileStatus.QUEUED)

            client = self.web_module.get_flask_app().test_client()
            response = client.get("/api/tasks/web-1")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["task_id"], "web-1")
            self.assertEqual(payload["files"][0]["message_id"], "11")

    def test_task_submission_rejects_invalid_link(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.post("/api/tasks", json={"link": "not-a-telegram-link"})

            self.assertEqual(response.status_code, 400)
            payload = response.get_json()
            self.assertFalse(payload["ok"])
            self.assertIn("unsupported", payload["error"])

    def test_task_submission_requires_running_telegram_client(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.post(
                "/api/tasks",
                json={"link": "https://t.me/c/12345/99"},
            )

            self.assertEqual(response.status_code, 503)
            payload = response.get_json()
            self.assertFalse(payload["ok"])
            self.assertIn("telegram client", payload["error"])

    def test_task_submission_schedules_valid_package_link(self):
        class FakeLoop:
            def __init__(self):
                self.scheduled = []

            def is_running(self):
                return False

            def create_task(self, coroutine):
                self.scheduled.append(coroutine)
                coroutine.close()

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            app.web_client = object()
            app.loop = FakeLoop()
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.post(
                "/api/tasks",
                json={"link": "https://t.me/c/12345/99"},
            )

            self.assertEqual(response.status_code, 202)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["task_type"], "package")
            self.assertEqual(payload["status"], "scanning")
            self.assertEqual(len(app.loop.scheduled), 1)

    def test_index_contains_task_dashboard_shell(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.get("/")

            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('id="task_dashboard_summary"', html)
            self.assertIn('id="web_task_link"', html)
            self.assertIn('id="submit_task_btn"', html)
            self.assertIn('id="task_list"', html)
            self.assertIn('id="task_detail_list"', html)

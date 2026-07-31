"""Tests for the Flask web control surface."""

import asyncio
import copy
import concurrent.futures
import json
import os
import tempfile
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from module.app import Application


def accepted_web_submission(scheduled):
    """Return a submission stub for route tests that do not execute owner work."""

    def submit(_loop, coroutine):
        scheduled.append(coroutine)
        coroutine.close()
        future = concurrent.futures.Future()
        future.set_result(None)
        return future

    return submit


def completed_web_command(_loop, coroutine):
    """Execute an owner command for synchronous Flask route tests."""

    result = asyncio.run(coroutine)
    future = concurrent.futures.Future()
    future.set_result(result)
    return future


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
        from module.download_stat import reset_download_runtime_state_for_tests
        from module.task_state import get_task_store

        self.web_module = web_module
        self.old_auth_env = os.environ.get(web_module.WEB_AUTH_FILE_ENV)
        self.old_web_auth_state = web_module._web_auth_state
        self.old_login_attempt_limiter = web_module._login_attempt_limiter
        self.old_current_app = web_module._current_app
        self.old_login_disabled = web_module._flask_app.config.get("LOGIN_DISABLED")
        self.old_secret_key = web_module._flask_app.secret_key
        web_module._flask_app.config["TESTING"] = True
        web_module._pending_web_task_previews.clear()
        web_module._pending_web_prescans.clear()
        web_module._scanning_web_task_nodes.clear()
        web_module._active_web_prescan_task_id = None
        reset_download_runtime_state_for_tests()
        get_task_store().clear()

    def _csrf_client(self):
        client = self.web_module.get_flask_app().test_client()
        token = client.get("/api/csrf-token").get_json()["csrf_token"]
        client.environ_base["HTTP_X_CSRF_TOKEN"] = token
        return client

    def tearDown(self):
        if self.old_auth_env is None:
            os.environ.pop(self.web_module.WEB_AUTH_FILE_ENV, None)
        else:
            os.environ[self.web_module.WEB_AUTH_FILE_ENV] = self.old_auth_env
        self.web_module._current_app = self.old_current_app
        self.web_module._flask_app.config["LOGIN_DISABLED"] = self.old_login_disabled
        self.web_module._flask_app.secret_key = self.old_secret_key
        self.web_module._web_auth_state = self.old_web_auth_state
        self.web_module._login_attempt_limiter = self.old_login_attempt_limiter
        from module.task_state import get_task_store

        self.web_module._pending_web_task_previews.clear()
        self.web_module._pending_web_prescans.clear()
        self.web_module._scanning_web_task_nodes.clear()
        self.web_module._active_web_prescan_task_id = None
        from module.download_stat import reset_download_runtime_state_for_tests

        reset_download_runtime_state_for_tests()
        get_task_store().clear()

    def test_flask_session_secret_is_not_static(self):
        self.assertNotEqual(self.web_module._flask_app.secret_key, "tdl")
        self.assertGreaterEqual(len(self.web_module._flask_app.secret_key), 32)

    def test_web_auth_generates_bootstrap_password_and_removes_it_after_login(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            auth_file = os.path.join(tmp_dir, "web_auth.json")
            os.environ[self.web_module.WEB_AUTH_FILE_ENV] = auth_file
            app = build_web_test_app(tmp_dir)
            app.web_login_secret = ""

            self.web_module._ensure_web_auth(app)

            with open(auth_file, encoding="utf-8") as handle:
                auth_data = json.load(handle)
            self.assertEqual(auth_data["username"], "root")
            self.assertTrue(auth_data["password_hash"])
            self.assertTrue(auth_data["bootstrap_password"])
            self.assertEqual(auth_data["password_source"], "local")

            client = self.web_module.get_flask_app().test_client()
            response = client.post(
                "/login",
                data={"password": auth_data["bootstrap_password"]},
            )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["code"], "1")
            with open(auth_file, encoding="utf-8") as handle:
                consumed_auth_data = json.load(handle)
            self.assertNotIn("bootstrap_password", consumed_auth_data)

    def test_login_rate_limit_session_lifetime_and_success_reset(self):
        from module.web_auth import LoginAttemptLimiter

        with tempfile.TemporaryDirectory() as tmp_dir:
            auth_file = os.path.join(tmp_dir, "web_auth.json")
            os.environ[self.web_module.WEB_AUTH_FILE_ENV] = auth_file
            app = build_web_test_app(tmp_dir)
            app.web_login_secret = "configured-secret"
            now = [100.0]
            self.web_module._login_attempt_limiter = LoginAttemptLimiter(
                max_failures=5,
                window_seconds=300,
                retry_delay_seconds=60,
                clock=lambda: now[0],
            )
            self.web_module._ensure_web_auth(app)
            client = self.web_module.get_flask_app().test_client()

            for _ in range(4):
                response = client.post("/login", data={"password": "wrong"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.get_json(), {"code": "0"})

            limited = client.post("/login", data={"password": "wrong"})
            self.assertEqual(limited.status_code, 429)
            self.assertEqual(limited.get_json(), {"code": "0"})
            self.assertEqual(limited.headers["Retry-After"], "60")

            now[0] += 61
            accepted = client.post(
                "/login",
                data={"password": "configured-secret"},
            )
            self.assertEqual(accepted.status_code, 200)
            self.assertEqual(accepted.get_json(), {"code": "1"})
            with client.session_transaction() as login_session:
                self.assertTrue(login_session.permanent)
            self.assertEqual(
                self.web_module._flask_app.permanent_session_lifetime,
                timedelta(hours=12),
            )
            self.assertFalse(
                self.web_module._flask_app.config["SESSION_REFRESH_EACH_REQUEST"]
            )
            self.assertEqual(
                self.web_module._login_attempt_limiter.record_failure(
                    "127.0.0.1"
                ),
                0,
            )

    def test_secure_cookie_is_explicitly_configured(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            auth_file = os.path.join(tmp_dir, "web_auth.json")
            os.environ[self.web_module.WEB_AUTH_FILE_ENV] = auth_file
            app = build_web_test_app(tmp_dir)
            app.web_login_secret = "configured-secret"
            app.web_secure_cookie = True

            self.web_module._ensure_web_auth(app)
            client = self.web_module.get_flask_app().test_client()
            response = client.post(
                "/login",
                data={"password": "configured-secret"},
            )

            self.assertIn("Secure", response.headers["Set-Cookie"])
            self.assertEqual(
                self.web_module._flask_app.config["MAX_CONTENT_LENGTH"],
                1024 * 1024,
            )

    def test_web_settings_updates_download_config(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            original_save_path = app.save_path
            original_max_download_task = app.max_download_task
            original_max_concurrent_transmissions = app.max_concurrent_transmissions
            original_start_timeout = app.start_timeout
            original_upload_adapter = app.cloud_drive_config.upload_adapter
            original_web_enabled = app.enable_web
            original_web_port = app.web_port
            app.channel_library_service = SimpleNamespace(
                disk_admission=SimpleNamespace(path=Path(original_save_path))
            )
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self._csrf_client()

            with patch.object(
                self.web_module,
                "submit_web_coroutine",
                side_effect=completed_web_command,
            ):
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
                            "upload_adapter": "aligo",
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
            self.assertEqual(
                payload["restart_fields"],
                [
                    "max_concurrent_transmissions",
                    "max_download_task",
                    "save_path",
                    "start_timeout",
                    "upload_drive.upload_adapter",
                    "web.enable_web",
                    "web.web_port",
                ],
            )
            self.assertEqual(app.save_path, original_save_path)
            self.assertEqual(app.max_download_task, original_max_download_task)
            self.assertEqual(
                app.max_concurrent_transmissions,
                original_max_concurrent_transmissions,
            )
            self.assertEqual(app.start_timeout, original_start_timeout)
            self.assertEqual(
                app.cloud_drive_config.upload_adapter,
                original_upload_adapter,
            )
            self.assertEqual(app.enable_web, original_web_enabled)
            self.assertEqual(app.web_port, original_web_port)
            self.assertEqual(
                app.channel_library_service.disk_admission.path,
                Path(original_save_path),
            )
            self.assertEqual(payload["active_settings"]["save_path"], original_save_path)
            self.assertEqual(
                payload["configured_settings"]["save_path"],
                os.path.join(tmp_dir, "new_downloads"),
            )
            self.assertEqual(
                payload["configured_settings"]["max_download_task"],
                8,
            )
            self.assertEqual(app.config["max_download_task"], 8)
            self.assertEqual(app.cloud_drive_config.remote_dir, "remote:/tg")
            self.assertFalse(app.cloud_drive_config.after_upload_file_delete)
            self.assertEqual(
                app.chat_download_config["me"].download_filter,
                "media_type == 'video'",
            )

            app.update_config()
            with open(app.config_file, encoding="utf-8") as handle:
                saved_config = handle.read()
            self.assertIn("enable_web: true", saved_config)
            self.assertIn("web_port: 80", saved_config)
            self.assertIn("after_upload_file_delete: false", saved_config)

    def test_web_settings_are_applied_on_owner_loop(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            loop = asyncio.new_event_loop()
            loop_started = threading.Event()
            update_thread_ids = []

            def run_loop():
                asyncio.set_event_loop(loop)
                loop_started.set()
                loop.run_forever()

            def record_update(_immediate=True):
                update_thread_ids.append(threading.get_ident())

            owner_thread = threading.Thread(target=run_loop)
            owner_thread.start()
            loop_started.wait(timeout=1)
            app.loop = loop
            app.update_config = record_update
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self._csrf_client()

            try:
                response = client.post(
                    "/api/settings",
                    json={"date_format": "%Y-%m-%d"},
                )
            finally:
                loop.call_soon_threadsafe(loop.stop)
                owner_thread.join(timeout=2)
                loop.close()

            self.assertEqual(response.status_code, 200)
            self.assertEqual(update_thread_ids, [owner_thread.ident])

    def test_invalid_web_settings_have_zero_memory_or_disk_side_effects(self):
        invalid_payloads = (
            (
                "date_format",
                {
                    "media_types": ["video"],
                    "date_format": "%Y-%m-%d%",
                },
            ),
            (
                "date_format",
                {
                    "media_types": ["video"],
                    "date_format": "%Y-%Q",
                },
            ),
            (
                "max_download_task",
                {
                    "media_types": ["video"],
                    "max_download_task": True,
                },
            ),
            (
                "media_types",
                {
                    "media_types": ["video", "unsupported"],
                },
            ),
            (
                "upload_drive",
                {
                    "media_types": ["video"],
                    "upload_drive": [],
                },
            ),
        )

        for expected_field, invalid_payload in invalid_payloads:
            with self.subTest(field=expected_field), tempfile.TemporaryDirectory() as tmp_dir:
                app = build_web_test_app(tmp_dir)
                app.update_config()
                original_config = copy.deepcopy(app.config)
                original_media_types = list(app.media_types)
                original_date_format = app.date_format
                original_cloud_config = copy.deepcopy(app.cloud_drive_config.__dict__)
                config_bytes = Path(app.config_file).read_bytes()
                app_data_bytes = Path(app.app_data_file).read_bytes()
                self.web_module._current_app = app
                self.web_module._flask_app.config["LOGIN_DISABLED"] = True
                client = self._csrf_client()

                with (
                    patch.object(app, "update_config") as update_config,
                    patch.object(
                        self.web_module,
                        "submit_web_coroutine",
                        side_effect=completed_web_command,
                    ),
                ):
                    response = client.post("/api/settings", json=invalid_payload)

                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.get_json(),
                    {
                        "ok": False,
                        "error": "invalid settings",
                        "error_code": "invalid_settings",
                        "field": expected_field,
                    },
                )
                self.assertEqual(app.config, original_config)
                self.assertEqual(app.media_types, original_media_types)
                self.assertEqual(app.date_format, original_date_format)
                self.assertEqual(
                    app.cloud_drive_config.__dict__,
                    original_cloud_config,
                )
                update_config.assert_not_called()
                self.assertEqual(Path(app.config_file).read_bytes(), config_bytes)
                self.assertEqual(Path(app.app_data_file).read_bytes(), app_data_bytes)

    def test_pause_download_mutation_runs_on_owner_loop(self):
        loop = asyncio.new_event_loop()
        loop_started = threading.Event()
        mutation_thread_ids = []

        def run_loop():
            asyncio.set_event_loop(loop)
            loop_started.set()
            loop.run_forever()

        def record_state(_state):
            mutation_thread_ids.append(threading.get_ident())

        owner_thread = threading.Thread(target=run_loop)
        owner_thread.start()
        loop_started.wait(timeout=1)
        self.web_module._current_app = SimpleNamespace(
            loop=loop,
            channel_library_service=None,
        )
        self.web_module._flask_app.config["LOGIN_DISABLED"] = True
        client = self._csrf_client()

        try:
            with patch.object(
                self.web_module,
                "get_download_state",
                return_value=self.web_module.DownloadState.Downloading,
            ), patch.object(
                self.web_module,
                "set_download_state",
                side_effect=record_state,
            ):
                response = client.post("/set_download_state?state=pause")
        finally:
            loop.call_soon_threadsafe(loop.stop)
            owner_thread.join(timeout=2)
            loop.close()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), "continue")
        self.assertEqual(mutation_thread_ids, [owner_thread.ident])

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

    def test_task_files_api_returns_paginated_files(self):
        from module.task_state import FileStatus, TaskStatus, get_task_store

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            store = get_task_store()
            task = store.create_task(
                task_id="web-files-1",
                source="web",
                task_type="package",
                status=TaskStatus.QUEUED,
            )
            for message_id in range(1, 61):
                store.upsert_file(task.task_id, message_id, status=FileStatus.QUEUED)

            client = self.web_module.get_flask_app().test_client()
            response = client.get("/api/tasks/web-files-1/files?page=2&page_size=25")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["page"], 2)
            self.assertEqual(payload["page_size"], 25)
            self.assertEqual(payload["total"], 60)
            self.assertEqual(payload["items"][0]["message_id"], "26")

    def test_download_list_uses_download_result_store(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.get("/get_download_list?already_down=false")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json(), [])

    def test_prescan_slot_allows_only_one_running_scan(self):
        self.assertTrue(self.web_module._try_acquire_prescan_slot("scan-1"))
        self.assertFalse(self.web_module._try_acquire_prescan_slot("scan-2"))

        self.web_module._release_prescan_slot("scan-1")

        self.assertTrue(self.web_module._try_acquire_prescan_slot("scan-2"))

    def test_prescan_limits_are_bounded_for_rn_server(self):
        limits = self.web_module._prescan_limits_from_payload(
            {"max_messages": 999999, "max_packages": 999999, "batch_size": 999999}
        )

        self.assertEqual(limits["max_messages"], self.web_module.WEB_PRESCAN_MAX_MESSAGES)
        self.assertEqual(limits["max_packages"], self.web_module.WEB_PRESCAN_MAX_PACKAGES)
        self.assertEqual(limits["batch_size"], self.web_module.WEB_PRESCAN_MAX_BATCH_SIZE)

    def test_prescan_progress_updates_task_workflow(self):
        from module.task_state import TaskStatus, get_task_store

        get_task_store().create_task(
            "web-prescan-progress",
            source="web",
            task_type="prescan",
            status=TaskStatus.SCANNING,
        )

        self.web_module._update_web_prescan_progress(
            "web-prescan-progress",
            {"scanned_count": 150, "package_count": 3},
        )

        task = get_task_store().get_task("web-prescan-progress")
        self.assertEqual(task.status, TaskStatus.SCANNING)
        self.assertEqual(task.workflow.scan_count, 150)
        self.assertEqual(task.workflow.media_count, 3)
        self.assertIn("150", task.workflow.summary)

    def test_web_prescan_waits_for_package_selection(self):
        from module.comment_workflow import build_message_package_workflow_request
        from module.task_state import TaskStatus, get_task_store

        class FakeClient:
            async def get_chat(self, chat_id):
                return SimpleNamespace(id=-10012345, username="demo", title="Demo")

        package = SimpleNamespace(
            package_id=1,
            title="Pack 1",
            start_message_id=100,
            end_message_id=105,
            media_count=2,
            messages=[],
            failed_message_ids=[],
        )
        scan_result = SimpleNamespace(
            prescan_plan=SimpleNamespace(
                start_message_id=99,
                scanned_count=20,
                packages=[package],
                warning=None,
            ),
            messages=[],
            failed_message_ids=[],
        )

        async def fake_scan(*_args, **_kwargs):
            return scan_result

        request = build_message_package_workflow_request("https://t.me/c/12345/99")

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            with patch("media_downloader.scan_prescan_packages", fake_scan):
                asyncio.run(
                    self.web_module._run_web_prescan_task(
                        app,
                        FakeClient(),
                        "web-prescan-1",
                        request,
                        self.web_module._prescan_limits_from_payload({}),
                    )
                )

            task = get_task_store().get_task("web-prescan-1")
            self.assertEqual(task.status, TaskStatus.WAITING_CONFIRMATION)
            self.assertTrue(task.needs_confirmation)
            self.assertEqual(task.workflow.selected_count, 0)
            self.assertIn("web-prescan-1", self.web_module._pending_web_prescans)

    def test_prescan_packages_api_and_selection(self):
        package = SimpleNamespace(
            package_id=1,
            title="Pack 1",
            start_message_id=100,
            end_message_id=105,
            media_count=2,
            messages=[],
            failed_message_ids=[],
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            self.web_module._pending_web_prescans["web-prescan-2"] = {
                "packages": [package],
                "selected_package_ids": set(),
            }
            client = self._csrf_client()

            response = client.get("/api/prescans/web-prescan-2/packages")
            select_response = client.post(
                "/api/prescans/web-prescan-2/packages/1/select",
                json={"selected": True},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["total"], 1)
            self.assertFalse(payload["items"][0]["selected"])
            self.assertEqual(select_response.status_code, 200)
            self.assertTrue(select_response.get_json()["selected"])

    def test_prescan_select_all_and_clear(self):
        def make_pkg(pid):
            return SimpleNamespace(
                package_id=pid, title="Pack %d" % pid,
                start_message_id=100 + pid, end_message_id=105 + pid,
                media_count=2, messages=[], failed_message_ids=[],
            )
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            self.web_module._pending_web_prescans["web-prescan-all"] = {
                "packages": [make_pkg(1), make_pkg(2), make_pkg(3)],
                "selected_package_ids": set(),
            }
            client = self._csrf_client()

            select_all = client.post(
                "/api/prescans/web-prescan-all/packages/select-all",
                json={"selected": True},
            )
            clear_all = client.post(
                "/api/prescans/web-prescan-all/packages/select-all",
                json={"selected": False},
            )
            missing = client.post(
                "/api/prescans/does-not-exist/packages/select-all",
                json={"selected": True},
            )

            self.assertEqual(select_all.status_code, 200)
            self.assertEqual(select_all.get_json()["selected_count"], 3)
            self.assertEqual(select_all.get_json()["total"], 3)
            self.assertEqual(clear_all.get_json()["selected_count"], 0)
            self.assertEqual(missing.status_code, 404)

    def test_confirm_prescan_schedules_selected_download(self):
        package = SimpleNamespace(package_id=1, messages=[], failed_message_ids=[])
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            scheduled = []
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            node = self.web_module._create_web_task(
                "web-prescan-3",
                "prescan",
                -10012345,
                "Demo prescan",
                "prescan",
            )
            self.web_module._pending_web_prescans["web-prescan-3"] = {
                "channel": "demo",
                "node": node,
                "packages": [package],
                "selected_package_ids": {1},
            }
            client = self._csrf_client()

            with patch.object(
                self.web_module,
                "submit_web_coroutine",
                side_effect=accepted_web_submission(scheduled),
            ):
                response = client.post("/api/tasks/web-prescan-3/confirm")

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["status"], "queued")
            self.assertEqual(len(scheduled), 1)

    def test_clear_terminal_task_removes_history(self):
        from module.task_state import TaskStatus, get_task_store

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            store = get_task_store()
            store.create_task("clear-1", status=TaskStatus.COMPLETED)
            store.update_task("clear-1", status=TaskStatus.COMPLETED)
            client = self._csrf_client()

            response = client.post("/api/tasks/clear-1/clear")

            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.get_json()["ok"])
            self.assertIsNone(store.get_task("clear-1"))

    def test_retry_without_metadata_returns_clear_error(self):
        from module.task_state import TaskStatus, get_task_store

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            get_task_store().create_task("retry-1", status=TaskStatus.FAILED)
            client = self._csrf_client()

            response = client.post("/api/tasks/retry-1/retry")

            self.assertEqual(response.status_code, 409)
            self.assertIn("metadata", response.get_json()["error"])

    def test_retry_channel_task_schedules_failed_downloads(self):
        from module.task_state import FileStatus, TaskStatus, get_task_store

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            scheduled = []
            future = concurrent.futures.Future()
            future.set_result(True)
            app.channel_library_service = SimpleNamespace(
                store=SimpleNamespace(
                    get_download_batch_by_task_id=lambda _task_id: {"id": 1}
                ),
                schedule_download_retry_threadsafe=lambda task_id: (
                    scheduled.append(task_id) or future
                ),
                schedule_upload_retry_threadsafe=lambda _task_id: (
                    self.fail("download failure must not use upload-only retry")
                ),
            )
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            store = get_task_store()
            store.create_task(
                "retry-download",
                task_type="channel_library",
                status=TaskStatus.COMPLETED_WITH_ERRORS,
            )
            store.upsert_file(
                "retry-download",
                101,
                status=FileStatus.FAILED,
                error="download_failed",
            )
            client = self._csrf_client()

            response = client.post("/api/tasks/retry-download/retry")

            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.get_json()["mode"], "download_failed")
            self.assertEqual(scheduled, ["retry-download"])

    def test_retry_channel_task_preserves_upload_only_priority(self):
        from module.task_state import FileStatus, TaskStatus, get_task_store

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            scheduled = []
            future = concurrent.futures.Future()
            future.set_result(True)
            app.channel_library_service = SimpleNamespace(
                store=SimpleNamespace(
                    get_download_batch_by_task_id=lambda _task_id: {"id": 1}
                ),
                schedule_upload_retry_threadsafe=lambda task_id: (
                    scheduled.append(task_id) or future
                ),
                schedule_download_retry_threadsafe=lambda _task_id: (
                    self.fail("retained upload failure must keep upload-only retry")
                ),
            )
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            store = get_task_store()
            store.create_task(
                "retry-upload",
                task_type="channel_library",
                status=TaskStatus.COMPLETED_WITH_ERRORS,
            )
            store.upsert_file(
                "retry-upload",
                101,
                status=FileStatus.UPLOAD_FAILED,
                error="upload_failed",
            )
            client = self._csrf_client()

            response = client.post("/api/tasks/retry-upload/retry")

            self.assertEqual(response.status_code, 202)
            self.assertEqual(response.get_json()["mode"], "upload_only")
            self.assertEqual(scheduled, ["retry-upload"])

    def test_task_submission_rejects_invalid_link(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self._csrf_client()

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
            client = self._csrf_client()

            response = client.post(
                "/api/tasks",
                json={"link": "https://t.me/c/12345/99"},
            )

            self.assertEqual(response.status_code, 503)
            payload = response.get_json()
            self.assertFalse(payload["ok"])
            self.assertIn("telegram client", payload["error"])

    def test_cancel_running_prescan_scan_sets_stop_flag(self):
        from module.app import TaskNode
        from module.task_state import TaskStatus, get_task_store

        node = TaskNode(chat_id=-1001, from_user_id="web", task_id="web-scan-9")
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            self.web_module._scanning_web_task_nodes["web-scan-9"] = node
            get_task_store().create_task(
                "web-scan-9",
                source="web",
                task_type="prescan",
                status=TaskStatus.SCANNING,
            )
            client = self._csrf_client()

            with patch.object(
                self.web_module,
                "submit_web_coroutine",
                side_effect=completed_web_command,
            ):
                response = client.post("/api/tasks/web-scan-9/cancel")

            self.assertEqual(response.status_code, 200)
            self.assertTrue(node.is_stop_transmission)
            task = get_task_store().get_task("web-scan-9")
            self.assertEqual(task.status, TaskStatus.CANCELLED)
            self.web_module._scanning_web_task_nodes.clear()

    def test_cancel_active_download_node_does_not_crash(self):
        from module.app import TaskNode
        from module.task_state import TaskStatus, get_task_store

        node = TaskNode(chat_id=-1001, from_user_id="web", task_id="web-dl-9")
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            get_task_store().create_task(
                "web-dl-9",
                source="web",
                task_type="package",
                status=TaskStatus.DOWNLOADING,
            )
            client = self._csrf_client()

            with patch.object(
                self.web_module,
                "get_active_task_nodes",
                return_value={"web-dl-9": node},
            ), patch.object(
                self.web_module,
                "submit_web_coroutine",
                side_effect=completed_web_command,
            ):
                response = client.post("/api/tasks/web-dl-9/cancel")

            self.assertEqual(response.status_code, 200)
            self.assertTrue(node.is_stop_transmission)
            task = get_task_store().get_task("web-dl-9")
            self.assertEqual(task.status, TaskStatus.CANCELLED)

    def test_web_prescan_stays_cancelled_after_scan_completes(self):
        from module.comment_workflow import build_message_package_workflow_request
        from module.task_state import TaskStatus, get_task_store

        class FakeClient:
            async def get_chat(self, chat_id):
                return SimpleNamespace(id=-10012345, username="demo", title="Demo")

        scan_result = SimpleNamespace(
            prescan_plan=SimpleNamespace(
                start_message_id=99,
                scanned_count=1,
                packages=[],
                warning=None,
            ),
            messages=[],
            failed_message_ids=[],
        )
        web_module = self.web_module

        async def fake_scan(*_args, **_kwargs):
            node = web_module._scanning_web_task_nodes.get("web-prescan-9")
            assert node is not None, "scanning node must be registered during scan"
            node.stop_transmission()
            get_task_store().update_task(
                "web-prescan-9", status=TaskStatus.CANCELLED
            )
            return scan_result

        request = build_message_package_workflow_request("https://t.me/c/12345/99")

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            with patch("media_downloader.scan_prescan_packages", fake_scan):
                asyncio.run(
                    self.web_module._run_web_prescan_task(
                        app,
                        FakeClient(),
                        "web-prescan-9",
                        request,
                        self.web_module._prescan_limits_from_payload({}),
                    )
                )

            task = get_task_store().get_task("web-prescan-9")
            self.assertEqual(task.status, TaskStatus.CANCELLED)
            self.assertFalse(task.needs_confirmation)
            self.assertNotIn("web-prescan-9", self.web_module._pending_web_prescans)
            self.assertNotIn("web-prescan-9", self.web_module._scanning_web_task_nodes)

    def test_web_package_scan_stays_cancelled_after_scan_completes(self):
        from module.comment_workflow import build_message_package_workflow_request
        from module.task_state import TaskStatus, get_task_store

        class FakeClient:
            async def get_chat(self, chat_id):
                return SimpleNamespace(id=-10012345, username="demo", title="Demo")

        message = SimpleNamespace(id=99)
        scan_result = SimpleNamespace(
            messages=[message],
            failed_message_ids=[],
            package_plan=SimpleNamespace(
                package_title="Demo package",
                summary=SimpleNamespace(scanned_count=5, media_count=1),
                items=[SimpleNamespace(message=message)],
            ),
        )
        web_module = self.web_module

        async def fake_scan(*_args, **_kwargs):
            node = web_module._scanning_web_task_nodes.get("web-preview-9")
            assert node is not None, "scanning node must be registered during scan"
            node.stop_transmission()
            get_task_store().update_task(
                "web-preview-9", status=TaskStatus.CANCELLED
            )
            return scan_result

        request = build_message_package_workflow_request("https://t.me/c/12345/99")

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            with patch("media_downloader.scan_message_package", fake_scan):
                asyncio.run(
                    self.web_module._run_web_package_task(
                        app, FakeClient(), "web-preview-9", request
                    )
                )

            task = get_task_store().get_task("web-preview-9")
            self.assertEqual(task.status, TaskStatus.CANCELLED)
            self.assertFalse(task.needs_confirmation)
            self.assertNotIn(
                "web-preview-9", self.web_module._pending_web_task_previews
            )
            self.assertNotIn("web-preview-9", self.web_module._scanning_web_task_nodes)

    def test_task_submission_schedules_valid_package_link(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            app.web_client = object()
            scheduled = []
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self._csrf_client()

            with patch.object(
                self.web_module,
                "submit_web_coroutine",
                side_effect=accepted_web_submission(scheduled),
            ):
                response = client.post(
                    "/api/tasks",
                    json={"link": "https://t.me/c/12345/99"},
                )

            self.assertEqual(response.status_code, 202)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["task_type"], "package")
            self.assertEqual(payload["status"], "scanning")
            self.assertEqual(len(scheduled), 1)

    def test_task_submission_rejects_stopped_application_loop(self):
        class StoppedLoop:
            def is_running(self):
                return False

            def is_closed(self):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            app.web_client = object()
            app.loop = StoppedLoop()
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self._csrf_client()

            response = client.post(
                "/api/tasks",
                json={"link": "https://t.me/c/12345/99"},
            )

            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.get_json()["error"],
                "application loop is not available",
            )

    def test_package_scan_waits_for_web_confirmation_before_downloading(self):
        from module.comment_workflow import build_message_package_workflow_request
        from module.task_state import TaskStatus, get_task_store

        class FakeClient:
            async def get_chat(self, chat_id):
                return SimpleNamespace(id=-10012345, username="demo", title="Demo")

        message = SimpleNamespace(id=99)
        scan_result = SimpleNamespace(
            messages=[message],
            failed_message_ids=[],
            package_plan=SimpleNamespace(
                package_title="Demo package",
                summary=SimpleNamespace(scanned_count=5, media_count=1),
                items=[SimpleNamespace(message=message)],
            ),
        )
        download_calls = []

        async def fake_scan(*_args, **_kwargs):
            return scan_result

        async def fake_download(*args, **_kwargs):
            download_calls.append(args)

        request = build_message_package_workflow_request("https://t.me/c/12345/99")

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            with patch("media_downloader.scan_message_package", fake_scan), patch(
                "media_downloader.download_prepared_messages", fake_download
            ):
                asyncio.run(
                    self.web_module._run_web_package_task(
                        app, FakeClient(), "web-preview-1", request
                    )
                )

            task = get_task_store().get_task("web-preview-1")
            self.assertEqual(task.status, TaskStatus.WAITING_CONFIRMATION)
            self.assertTrue(task.needs_confirmation)
            self.assertEqual(task.workflow.selected_count, 1)
            self.assertIn("web-preview-1", self.web_module._pending_web_task_previews)
            self.assertEqual(download_calls, [])

    def test_telegram_preview_reads_wait_for_download_permit(self):
        from module.comment_workflow import (
            build_comment_workflow_request,
            build_message_package_workflow_request,
        )
        from module.telegram_activity import TelegramActivityGate

        web_module = self.web_module

        class FakeClient:
            def __init__(self):
                self.get_chat_calls = []

            async def get_chat(self, chat_id):
                self.get_chat_calls.append(chat_id)
                return SimpleNamespace(id=-10012345, username="demo", title="Demo")

        message = SimpleNamespace(id=99)
        package_scan_result = SimpleNamespace(
            messages=[message],
            failed_message_ids=[],
            package_plan=SimpleNamespace(
                package_title="Demo package",
                summary=SimpleNamespace(scanned_count=5, media_count=1),
                items=[SimpleNamespace(message=message)],
            ),
        )
        prescan_scan_result = SimpleNamespace(
            prescan_plan=SimpleNamespace(
                start_message_id=99,
                scanned_count=1,
                packages=[],
                warning=None,
            ),
            messages=[],
            failed_message_ids=[],
        )

        async def fake_package_scan(*_args, **_kwargs):
            return package_scan_result

        async def fake_prescan_scan(*_args, **_kwargs):
            return prescan_scan_result

        async def assert_preview_waits(gate, client, coroutine):
            scan = await gate.acquire_scan()
            preview_task = asyncio.create_task(coroutine)
            await asyncio.sleep(0)
            self.assertEqual(client.get_chat_calls, [])
            scan.release()
            await asyncio.wait_for(preview_task, 1)
            await gate.wait_until_idle()

        async def scenario():
            with tempfile.TemporaryDirectory() as tmp_dir:
                app = build_web_test_app(tmp_dir)

                package_gate = TelegramActivityGate()
                package_client = FakeClient()
                package_request = build_message_package_workflow_request(
                    "https://t.me/c/12345/99"
                )
                with patch.object(
                    web_module,
                    "get_telegram_activity_gate",
                    return_value=package_gate,
                ), patch(
                    "media_downloader.scan_message_package", fake_package_scan
                ):
                    await assert_preview_waits(
                        package_gate,
                        package_client,
                        web_module._run_web_package_task(
                            app,
                            package_client,
                            "web-gated-package",
                            package_request,
                        ),
                    )

                comment_gate = TelegramActivityGate()
                comment_client = FakeClient()
                comment_request = build_comment_workflow_request(
                    "https://t.me/c/12345/99?comment=101"
                )
                with patch.object(
                    web_module,
                    "get_telegram_activity_gate",
                    return_value=comment_gate,
                ):
                    await assert_preview_waits(
                        comment_gate,
                        comment_client,
                        web_module._run_web_comment_task(
                            app,
                            comment_client,
                            "web-gated-comment",
                            comment_request,
                        ),
                    )

                prescan_gate = TelegramActivityGate()
                prescan_client = FakeClient()
                with patch.object(
                    web_module,
                    "get_telegram_activity_gate",
                    return_value=prescan_gate,
                ), patch(
                    "media_downloader.scan_prescan_packages", fake_prescan_scan
                ):
                    await assert_preview_waits(
                        prescan_gate,
                        prescan_client,
                        web_module._run_web_prescan_task(
                            app,
                            prescan_client,
                            "web-gated-prescan",
                            package_request,
                            web_module._prescan_limits_from_payload({}),
                        ),
                    )

        asyncio.run(scenario())

    def test_confirm_preview_schedules_package_download(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            scheduled = []
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            node = self.web_module._create_web_task(
                "web-preview-2",
                "package",
                -10012345,
                "Demo package",
                "message_package",
            )
            self.web_module._pending_web_task_previews["web-preview-2"] = {
                "task_type": "package",
                "node": node,
                "messages": [],
                "failed_message_ids": [],
            }
            client = self._csrf_client()

            with patch.object(
                self.web_module,
                "submit_web_coroutine",
                side_effect=accepted_web_submission(scheduled),
            ):
                response = client.post("/api/tasks/web-preview-2/confirm")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "queued")
            self.assertEqual(len(scheduled), 1)

    def test_cancel_preview_marks_task_cancelled(self):
        from module.task_state import TaskStatus, get_task_store

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            node = self.web_module._create_web_task(
                "web-preview-3",
                "package",
                -10012345,
                "Demo package",
                "message_package",
            )
            self.web_module._pending_web_task_previews["web-preview-3"] = {
                "task_type": "package",
                "node": node,
                "messages": [],
                "failed_message_ids": [],
            }
            client = self._csrf_client()

            with patch.object(
                self.web_module,
                "submit_web_coroutine",
                side_effect=completed_web_command,
            ):
                response = client.post("/api/tasks/web-preview-3/cancel")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["status"], "cancelled")
            self.assertTrue(node.is_stop_transmission)
            self.assertNotIn("web-preview-3", self.web_module._pending_web_task_previews)
            self.assertEqual(
                get_task_store().get_task("web-preview-3").status,
                TaskStatus.CANCELLED,
            )

    def test_resource_delivery_api_lists_enriched_jobs_and_manages_safe_actions(self):
        from module.resource_bot_store import ResourceBotStore

        class FakePackageStore:
            @staticmethod
            def get_package(package_id):
                return {
                    "id": int(package_id),
                    "title": f"Package {package_id}",
                    "source_chat_title": "Source Channel",
                }

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            resource_store = ResourceBotStore(
                os.path.join(tmp_dir, "resource_bot.sqlite3")
            )
            resource_store.initialize()
            key = resource_store.create_activation_key(1)
            self.assertTrue(resource_store.redeem_activation_key(key, 200))
            resource_store.bind_channel(200, -1001, "Target", "target")
            job, _ = resource_store.create_delivery_job(
                idempotency_key="web-action",
                user_id=200,
                package_id=12,
                package_revision=3,
                target_chat_id=-1001,
                total_items=2,
            )
            app.resource_bot_store = resource_store
            app.channel_library_service = SimpleNamespace(store=FakePackageStore())
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.get(
                "/api/resource-deliveries?page=1&page_size=100"
            )

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["total"], 1)
            self.assertEqual(payload["items"][0]["public_id"], job["public_id"])
            self.assertEqual(payload["items"][0]["package_title"], "Package 12")
            self.assertEqual(payload["items"][0]["source_title"], "Source Channel")
            self.assertEqual(payload["items"][0]["target_title"], "Target")
            self.assertEqual(payload["summary"]["queued"], 1)

            missing_csrf = client.post(
                f"/api/resource-deliveries/{job['public_id']}/cancel"
            )
            self.assertEqual(missing_csrf.status_code, 403)

            csrf = client.get("/api/csrf-token").get_json()["csrf_token"]
            cancelled = client.post(
                f"/api/resource-deliveries/{job['public_id']}/cancel",
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(cancelled.status_code, 200)
            self.assertEqual(cancelled.get_json()["job"]["status"], "cancelled")

            cleared = client.post(
                f"/api/resource-deliveries/{job['public_id']}/clear",
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(cleared.status_code, 200)
            self.assertTrue(cleared.get_json()["cleared"])

    def test_resource_delivery_api_rejects_active_cancel_and_clears_terminal_history(self):
        from module.resource_bot_store import ResourceBotStore

        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            resource_store = ResourceBotStore(
                os.path.join(tmp_dir, "resource_bot.sqlite3")
            )
            resource_store.initialize()
            key = resource_store.create_activation_key(1)
            self.assertTrue(resource_store.redeem_activation_key(key, 200))
            resource_store.bind_channel(200, -1001, "Target", None)
            active, _ = resource_store.create_delivery_job(
                idempotency_key="active",
                user_id=200,
                package_id=12,
                package_revision=3,
                target_chat_id=-1001,
                total_items=1,
            )
            terminal, _ = resource_store.create_delivery_job(
                idempotency_key="terminal",
                user_id=200,
                package_id=13,
                package_revision=3,
                target_chat_id=-1001,
                total_items=1,
            )
            resource_store.claim_next_delivery_job()
            resource_store.cancel_queued_delivery_job(terminal["public_id"])
            app.resource_bot_store = resource_store
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()
            csrf = client.get("/api/csrf-token").get_json()["csrf_token"]

            conflict = client.post(
                f"/api/resource-deliveries/{active['public_id']}/cancel",
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(conflict.status_code, 409)

            cleared = client.post(
                "/api/resource-deliveries/clear-terminal",
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(cleared.status_code, 200)
            self.assertEqual(cleared.get_json()["cleared"], 1)
            self.assertIsNotNone(resource_store.get_delivery_job(active["id"]))

    def test_resource_delivery_api_is_unavailable_without_resource_bot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            app.resource_bot_store = None
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.get("/api/resource-deliveries")

            self.assertEqual(response.status_code, 503)
            self.assertEqual(
                response.get_json()["error_code"], "service_unavailable"
            )

    def test_index_contains_industry_app_shell(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            app = build_web_test_app(tmp_dir)
            self.web_module._current_app = app
            self.web_module._flask_app.config["LOGIN_DISABLED"] = True
            client = self.web_module.get_flask_app().test_client()

            response = client.get("/")

            self.assertEqual(response.status_code, 200)
            html = response.get_data(as_text=True)
            self.assertIn('class="app"', html)
            self.assertIn('class="app-nav"', html)
            self.assertIn('id="download_state"', html)
            self.assertIn('id="logout_btn"', html)
            self.assertIn('id="tab_tasks"', html)
            self.assertIn('id="tab_files"', html)
            self.assertIn('id="tab_publishing"', html)
            self.assertIn('id="tab_config"', html)
            self.assertIn('id="app_version"', html)
            self.assertIn('id="foot_speed"', html)
            self.assertNotIn("static/layui", html)

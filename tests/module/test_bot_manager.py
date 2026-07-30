"""Tests for the unified management/resource Bot lifecycle."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from module.bot import BotManager, resource_bot_db_path
from module.download_runtime import DownloadRuntime, run_application


def run(coroutine):
    return asyncio.run(coroutine)


class FakeAdminRole:
    def __init__(self, events, fail=False):
        self.events = events
        self.fail = fail
        self.bot = FakeAdminClient(events)
        self.allowed_user_ids = [1]

    async def start(self, app, client, add_download_task, download_chat_task):
        self.events.append("admin.start")
        if self.fail:
            raise RuntimeError("admin start failed")

    async def stop(self):
        self.events.append("admin.stop")


class FakeAdminClient:
    def __init__(self, events):
        self.events = events
        self.handlers = []
        self.commands = []

    def add_handler(self, handler, group=0):
        self.handlers.append(handler)

    async def set_bot_commands(self, commands):
        self.commands = list(commands)
        self.events.append("admin.commands")


class FakeStore:
    def __init__(self, path, events):
        self.path = Path(path)
        self.events = events

    def initialize(self):
        self.events.append(("store.initialize", self.path))


class FakeResourceRole:
    def __init__(self, app, client, store, channel_store, events, fail=False):
        self.events = events
        self.fail = fail
        self.bot = object()
        self.delivery_service = None

    async def start(self):
        self.events.append("resource.start")
        if self.fail:
            raise RuntimeError("resource start failed")

    async def stop(self):
        self.events.append("resource.stop")


class FakeDeliveryService:
    def __init__(
        self,
        app,
        client,
        resource_client,
        store,
        channel_store,
        *,
        temp_root,
        events,
    ):
        self.events = events
        self.temp_root = Path(temp_root)

    async def start(self):
        self.events.append("delivery.start")

    async def stop(self):
        self.events.append("delivery.stop")


def app_config(*, admin_token="admin", resource_token=""):
    return SimpleNamespace(
        bot_token=admin_token,
        resource_bot_token=resource_token,
        resource_bot_store=None,
        channel_library_service=SimpleNamespace(store=object()),
        temp_save_path="/tmp/resource-bot-test",
    )


def make_manager(events, *, admin_fail=False, resource_fail=False):
    admin = FakeAdminRole(events, fail=admin_fail)
    return BotManager(
        admin_role=admin,
        store_factory=lambda path: FakeStore(path, events),
        resource_role_factory=lambda app, client, store, channel_store: (
            FakeResourceRole(
                app,
                client,
                store,
                channel_store,
                events,
                fail=resource_fail,
            )
        ),
        delivery_factory=lambda *args, **kwargs: FakeDeliveryService(
            *args, **kwargs, events=events
        ),
        db_path_resolver=lambda: Path("/tmp/resource-bot-test.sqlite3"),
    )


def test_only_management_role_starts_without_resource_token():
    async def scenario():
        events = []
        manager = make_manager(events)

        await manager.start(app_config(), object(), object(), object())
        await manager.stop()

        assert events == ["admin.start", "admin.stop"]
        assert manager.resource_role is None

    run(scenario())


def test_both_roles_and_delivery_start_from_one_manager():
    async def scenario():
        events = []
        manager = make_manager(events)
        app = app_config(resource_token="resource")

        await manager.start(
            app,
            object(),
            object(),
            object(),
        )

        assert events[:5] == [
            "admin.start",
            ("store.initialize", Path("/tmp/resource-bot-test.sqlite3")),
            "resource.start",
            "delivery.start",
            "admin.commands",
        ]
        assert manager.resource_role.delivery_service is manager.delivery_service
        assert app.resource_bot_store is manager.resource_store

        await manager.stop()
        assert events[-3:] == [
            "delivery.stop",
            "resource.stop",
            "admin.stop",
        ]
        assert app.resource_bot_store is None

    run(scenario())


def test_resource_token_without_management_token_is_rejected():
    async def scenario():
        manager = make_manager([])
        with pytest.raises(ValueError, match="resource_bot_token requires bot_token"):
            await manager.start(
                app_config(admin_token="", resource_token="resource"),
                object(),
                object(),
                object(),
            )

    run(scenario())


def test_partial_start_failure_unwinds_started_roles():
    async def scenario():
        events = []
        manager = make_manager(events, resource_fail=True)

        with pytest.raises(RuntimeError, match="resource start failed"):
            await manager.start(
                app_config(resource_token="resource"),
                object(),
                object(),
                object(),
            )

        assert events == [
            "admin.start",
            ("store.initialize", Path("/tmp/resource-bot-test.sqlite3")),
            "resource.start",
            "resource.stop",
            "admin.stop",
        ]
        assert not manager.started

    run(scenario())


def test_partial_management_start_failure_is_cleaned_up():
    async def scenario():
        events = []
        manager = make_manager(events, admin_fail=True)

        with pytest.raises(RuntimeError, match="admin start failed"):
            await manager.start(
                app_config(resource_token=""),
                object(),
                object(),
                object(),
            )

        assert events == ["admin.start", "admin.stop"]
        assert not manager.started

    run(scenario())


def test_repeated_start_and_stop_are_safe():
    async def scenario():
        events = []
        manager = make_manager(events)
        app = app_config(resource_token="resource")

        await manager.start(app, object(), object(), object())
        await manager.start(app, object(), object(), object())
        await manager.stop()
        await manager.stop()

        assert events.count("admin.start") == 1
        assert events.count("admin.stop") == 1
        assert events.count("resource.start") == 1
        assert events.count("resource.stop") == 1
        assert events.count("delivery.start") == 1
        assert events.count("delivery.stop") == 1

    run(scenario())


def test_resource_database_path_default_and_environment_override(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("TMD_RESOURCE_BOT_DB_PATH", raising=False)
    assert resource_bot_db_path() == Path.cwd() / "resource_bot.sqlite3"

    override = tmp_path / "isolated.sqlite3"
    monkeypatch.setenv("TMD_RESOURCE_BOT_DB_PATH", str(override))
    assert resource_bot_db_path() == override


def test_runtime_uses_single_bot_entry_when_only_resource_token_is_set():
    events = []

    class FakeLoop:
        def run_until_complete(self, coroutine):
            return asyncio.run(coroutine)

        def create_task(self, coroutine):
            coroutine.close()
            return SimpleNamespace(cancel=lambda: None)

    class FakeApplication:
        enable_web = False
        max_concurrent_transmissions = 1
        max_download_task = 0
        bot_token = ""
        resource_bot_token = "resource"
        loop = FakeLoop()
        total_download_task = 0
        cloud_drive_config = SimpleNamespace(total_upload_success_file_count=0)

        def pre_run(self):
            events.append("pre_run")

        def update_config(self):
            events.append("update_config")

    async def start_bot(*args):
        events.append("bot.start")

    async def stop_bot():
        events.append("bot.stop")

    async def noop_async(*args):
        return None

    runtime = DownloadRuntime(
        logger=SimpleNamespace(
            info=lambda *args: None,
            success=lambda *args: None,
            warning=lambda *args: None,
            exception=lambda *args: None,
        ),
        translate=lambda value: value,
        init_web=lambda *args: None,
        set_max_concurrent_transmissions=lambda *args: None,
        start_server=noop_async,
        stop_server=noop_async,
        start_channel_library_service=lambda *args: None,
        stop_channel_library_service=lambda *args: None,
        download_all_chat=noop_async,
        periodic_progress_refresh=noop_async,
        worker=noop_async,
        start_download_bot=start_bot,
        stop_download_bot=stop_bot,
        add_download_task=lambda *args: None,
        download_chat_task=lambda *args: None,
        exec_loop=lambda: None,
        print_performance_stats=lambda: None,
    )

    run_application(FakeApplication(), object(), runtime)

    assert "bot.start" in events
    assert "bot.stop" in events

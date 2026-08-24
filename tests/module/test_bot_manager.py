"""Tests for the unified management/resource Bot lifecycle."""

import asyncio
import signal
from pathlib import Path
from types import SimpleNamespace

import pytest

from module.bot import BotManager, resource_bot_db_path
from module.download_operations import DownloadOperations
from module.download_runtime import DownloadRuntime, run_application
from module.runtime_health import RuntimeHealth, RuntimePhase


def run(coroutine):
    return asyncio.run(coroutine)


NOOP_OPERATIONS = DownloadOperations(*([lambda *_args, **_kwargs: None] * 8))


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
        staging_chat_id,
        events,
    ):
        self.events = events
        self.temp_root = Path(temp_root)
        self.staging_chat_id = int(staging_chat_id)

    async def start(self):
        self.events.append("delivery.start")

    async def stop(self):
        self.events.append("delivery.stop")


def app_config(*, admin_token="admin", resource_token=""):
    return SimpleNamespace(
        bot_token=admin_token,
        resource_bot_token=resource_token,
        resource_staging_chat_id=-1009,
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


def test_resource_role_and_delivery_never_start_from_one_manager():
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

        assert events == ["admin.start"]
        assert manager.resource_role is None
        assert manager.delivery_service is None
        assert app.resource_bot_store is None

        await manager.stop()
        assert events[-1] == "admin.stop"
        assert app.resource_bot_store is None

    run(scenario())


def test_resource_token_without_management_token_no_longer_blocks_startup():
    async def scenario():
        events = []
        manager = make_manager(events)
        await manager.start(
            app_config(admin_token="", resource_token="resource"),
            object(),
            object(),
            object(),
        )
        assert manager.started is True
        assert events == ["admin.start"]

    run(scenario())


def test_resource_start_failure_is_unreachable_when_publishing_is_disabled():
    async def scenario():
        events = []
        manager = make_manager(events, resource_fail=True)

        await manager.start(
            app_config(resource_token="resource"),
            object(),
            object(),
            object(),
        )

        assert events == ["admin.start"]
        assert manager.started

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
        assert "resource.start" not in events
        assert "resource.stop" not in events
        assert "delivery.start" not in events
        assert "delivery.stop" not in events

    run(scenario())


def test_resource_database_path_default_and_environment_override(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("TMD_RESOURCE_BOT_DB_PATH", raising=False)
    assert resource_bot_db_path() == Path.cwd() / "resource_bot.sqlite3"

    override = tmp_path / "isolated.sqlite3"
    monkeypatch.setenv("TMD_RESOURCE_BOT_DB_PATH", str(override))
    assert resource_bot_db_path() == override


def test_runtime_does_not_start_a_bot_when_only_resource_token_is_set():
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

    async def start_bot(
        _app,
        _client,
        _add_download_task,
        _download_chat_task,
        operations,
    ):
        assert operations is NOOP_OPERATIONS
        events.append("bot.start")

    async def stop_bot():
        events.append("bot.stop")

    async def noop_async(*args):
        return None

    def start_channel(_app, _client, operations):
        assert operations is NOOP_OPERATIONS

    runtime = DownloadRuntime(
        logger=SimpleNamespace(
            info=lambda *args: None,
            success=lambda *args: None,
            warning=lambda *args: None,
            exception=lambda *args: None,
        ),
        translate=lambda value: value,
        operations=NOOP_OPERATIONS,
        initialize_task_store=lambda: events.append("task_store.initialize"),
        init_web=lambda *args: None,
        set_max_concurrent_transmissions=lambda *args: None,
        start_server=noop_async,
        stop_server=noop_async,
        start_channel_library_service=start_channel,
        stop_channel_library_service=lambda *args: None,
        download_all_chat=noop_async,
        periodic_progress_refresh=noop_async,
        worker=noop_async,
        start_download_bot=start_bot,
        stop_download_bot=stop_bot,
        add_download_task=lambda *args: None,
        download_chat_task=lambda *args: None,
        exec_loop=lambda _shutdown_request: None,
        print_performance_stats=lambda: None,
    )

    run_application(FakeApplication(), object(), runtime)

    assert events[:2] == ["pre_run", "task_store.initialize"]
    assert "bot.start" not in events
    assert "bot.stop" not in events


def test_resource_role_is_never_started_even_when_token_is_configured(tmp_path):
    events = []
    manager = BotManager(
        FakeAdminRole(events),
        store_factory=lambda path: (_ for _ in ()).throw(
            AssertionError("resource store must not be created")
        ),
        resource_role_factory=lambda *args: (_ for _ in ()).throw(
            AssertionError("resource role must not be created")
        ),
        delivery_factory=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("delivery service must not be created")
        ),
        db_path_resolver=lambda: tmp_path / "resource_bot.sqlite3",
    )
    app = SimpleNamespace(
        bot_token="admin-token",
        resource_bot_token="resource-token",
        resource_staging_chat_id=0,
        temp_save_path=str(tmp_path),
        channel_library_service=None,
        resource_bot_store="sentinel",
    )

    run(manager.start(app, SimpleNamespace(), lambda *_: None, lambda *_: None))

    assert manager.started is True
    assert manager.resource_role is None
    assert manager.delivery_service is None
    assert app.resource_bot_store is None
    assert "admin.start" in events


def _lifecycle_runtime(events, **overrides):
    async def noop_async(*_args):
        return None

    values = {
        "logger": SimpleNamespace(
            info=lambda *args: None,
            success=lambda *args: None,
            warning=lambda *args: None,
            exception=lambda *args: None,
        ),
        "translate": lambda value: value,
        "operations": NOOP_OPERATIONS,
        "initialize_task_store": lambda: events.append("task_store.initialize"),
        "init_web": lambda *args: None,
        "set_max_concurrent_transmissions": lambda *args: None,
        "start_server": noop_async,
        "stop_server": noop_async,
        "start_channel_library_service": lambda *args: None,
        "stop_channel_library_service": lambda *args: events.append("channel.stop"),
        "download_all_chat": noop_async,
        "periodic_progress_refresh": noop_async,
        "worker": noop_async,
        "start_download_bot": noop_async,
        "stop_download_bot": noop_async,
        "add_download_task": lambda *args: None,
        "download_chat_task": lambda *args: None,
        "exec_loop": lambda shutdown_request: None,
        "print_performance_stats": lambda: None,
    }
    values.update(overrides)
    return DownloadRuntime(**values)


class _LifecycleApplication:
    enable_web = False
    max_concurrent_transmissions = 1
    max_download_task = 0
    bot_token = ""
    resource_bot_token = ""
    total_download_task = 0
    cloud_drive_config = SimpleNamespace(total_upload_success_file_count=0)

    def __init__(self, events):
        self.events = events
        self.loop = asyncio.new_event_loop()
        self.is_running = True
        self.runtime_health = RuntimeHealth()

    def pre_run(self):
        self.events.append("pre_run")

    def update_config(self):
        self.events.append("update_config")

    def close_runtime_resources(self):
        self.events.append("resources.close")
        self.loop.close()


def test_runtime_awaits_cancelled_worker_finalizers_before_closing_resources():
    events = []
    app = _LifecycleApplication(events)
    app.max_download_task = 1

    async def blocking_task(name):
        try:
            events.append(f"{name}.start")
            await asyncio.Event().wait()
        finally:
            events.append(f"{name}.finalized")

    def exec_loop(_shutdown_request):
        app.loop.run_until_complete(asyncio.sleep(0))

    runtime = _lifecycle_runtime(
        events,
        download_all_chat=lambda *_args: blocking_task("download"),
        periodic_progress_refresh=lambda: blocking_task("progress"),
        worker=lambda *_args: blocking_task("worker"),
        exec_loop=exec_loop,
    )

    run_application(app, object(), runtime)

    assert "worker.finalized" in events
    assert events.index("worker.finalized") < events.index("resources.close")


def test_sigint_and_sigterm_share_one_shutdown_request(monkeypatch):
    import module.download_runtime as runtime_module

    events = []
    app = _LifecycleApplication(events)
    installed = {}
    previous = {
        signal.SIGINT: object(),
        signal.SIGTERM: object(),
    }

    def fake_signal(signum, handler):
        old_handler = installed.get(signum, previous[signum])
        installed[signum] = handler
        return old_handler

    monkeypatch.setattr(runtime_module.signal, "signal", fake_signal)

    def exec_loop(shutdown_request):
        assert installed[signal.SIGINT] is installed[signal.SIGTERM]
        installed[signal.SIGTERM](signal.SIGTERM, None)
        app.loop.run_until_complete(shutdown_request.wait())
        events.append("shutdown.requested")

    runtime = _lifecycle_runtime(events, exec_loop=exec_loop)

    run_application(app, object(), runtime)

    assert "shutdown.requested" in events
    assert installed == previous


def test_web_server_stops_before_runtime_resources_close():
    events = []
    app = _LifecycleApplication(events)
    app.enable_web = True

    class RecordingWebServer:
        def stop(self, timeout):
            events.append(("web.stop", timeout))

    def init_web(_app, _client, operations):
        assert operations is NOOP_OPERATIONS
        return RecordingWebServer()

    runtime = _lifecycle_runtime(events, init_web=init_web)

    run_application(app, object(), runtime)

    assert events.index(("web.stop", 5)) < events.index("resources.close")


def test_config_flush_failure_does_not_skip_runtime_resource_close():
    events = []
    app = _LifecycleApplication(events)

    def fail_update_config():
        events.append("update_config.failed")
        raise OSError("disk unavailable")

    app.update_config = fail_update_config
    runtime = _lifecycle_runtime(events)

    run_application(app, object(), runtime)

    assert "update_config.failed" in events
    assert "resources.close" in events


def test_runtime_marks_ready_only_after_required_services_start():
    events = []
    app = _LifecycleApplication(events)
    app.bot_token = "configured"

    async def start_server(*_args):
        events.append("telegram.start")

    def start_channel(*_args):
        events.append("channel.start")

    async def start_bot(*_args):
        events.append("bot.start")

    def exec_loop(_shutdown_request):
        events.append(("runtime.phase", app.runtime_health.phase))

    runtime = _lifecycle_runtime(
        events,
        start_server=start_server,
        start_channel_library_service=start_channel,
        start_download_bot=start_bot,
        exec_loop=exec_loop,
    )

    run_application(app, object(), runtime)

    ready_event = ("runtime.phase", RuntimePhase.READY)
    assert ready_event in events
    assert events.index("telegram.start") < events.index(ready_event)
    assert events.index("channel.start") < events.index(ready_event)
    assert events.index("bot.start") < events.index(ready_event)
    assert app.runtime_health.phase is RuntimePhase.STOPPING


def test_runtime_propagates_required_service_startup_failure():
    events = []
    app = _LifecycleApplication(events)

    def fail_channel_start(*_args):
        raise RuntimeError("channel startup failed")

    runtime = _lifecycle_runtime(
        events,
        start_channel_library_service=fail_channel_start,
    )

    with pytest.raises(RuntimeError, match="channel startup failed"):
        run_application(app, object(), runtime)

    assert app.runtime_health.phase is RuntimePhase.FAILED
    assert "resources.close" in events


def test_runtime_propagates_telegram_startup_failure_without_success_log():
    events = []
    app = _LifecycleApplication(events)

    async def fail_telegram_start(*_args):
        raise RuntimeError("telegram startup failed")

    runtime = _lifecycle_runtime(
        events,
        logger=SimpleNamespace(
            info=lambda *args: None,
            success=lambda message, *args: events.append(("success", message)),
            warning=lambda *args: None,
            exception=lambda *args: None,
        ),
        start_server=fail_telegram_start,
    )

    with pytest.raises(RuntimeError, match="telegram startup failed"):
        run_application(app, object(), runtime)

    assert app.runtime_health.phase is RuntimePhase.FAILED
    success_messages = [
        item[1]
        for item in events
        if isinstance(item, tuple) and len(item) == 2 and item[0] == "success"
    ]
    assert "Successfully started (Press Ctrl+C to stop)" not in success_messages

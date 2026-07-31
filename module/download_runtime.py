"""Application lifecycle orchestration for the downloader process."""

import asyncio
import inspect
import signal
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DownloadRuntime:
    """Dependencies supplied by the compatibility entrypoint."""

    logger: Any
    translate: Callable[[str], str]
    initialize_task_store: Callable[..., Any]
    init_web: Callable[..., Any]
    set_max_concurrent_transmissions: Callable[..., Any]
    start_server: Callable[..., Any]
    stop_server: Callable[..., Any]
    start_channel_library_service: Callable[..., Any]
    stop_channel_library_service: Callable[..., Any]
    download_all_chat: Callable[..., Any]
    periodic_progress_refresh: Callable[..., Any]
    worker: Callable[..., Any]
    start_download_bot: Callable[..., Any]
    stop_download_bot: Callable[..., Any]
    add_download_task: Callable[..., Any]
    download_chat_task: Callable[..., Any]
    exec_loop: Callable[..., Any]
    print_performance_stats: Callable[..., Any]


async def _cancel_and_await(tasks) -> None:
    """Cancel every task and await real asyncio awaitables to finalization."""

    awaitables = []
    for task in tasks:
        task.cancel()
        if inspect.isawaitable(task):
            awaitables.append(task)
    if awaitables:
        await asyncio.gather(*awaitables, return_exceptions=True)


async def _cancel_remaining_tasks() -> None:
    """Drain owner-loop tasks not included in the main worker list."""

    current = asyncio.current_task()
    pending = [
        task for task in asyncio.all_tasks() if task is not current and not task.done()
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


def _run_until_complete(loop, awaitable):
    """Run one awaitable or close an unsubmitted coroutine on loop failure."""

    is_closed = getattr(loop, "is_closed", lambda: False)
    try:
        if is_closed():
            raise RuntimeError("application event loop is closed")
        return loop.run_until_complete(awaitable)
    except Exception:
        if inspect.iscoroutine(awaitable):
            awaitable.close()
        raise


def run_application(application, client, runtime: DownloadRuntime) -> None:
    """Run all process services on the application's owner event loop."""

    tasks = []
    web_server = None
    runtime_health = getattr(application, "runtime_health", None)
    startup_failed = False
    shutdown_request = asyncio.Event()
    previous_signal_handlers = {}

    def request_shutdown(_signum=None, _frame=None):
        application.is_running = False
        if runtime_health is not None:
            try:
                runtime_health.mark_stopping()
            except Exception as error:
                runtime.logger.warning(f"runtime health update failed: {error}")
        try:
            application.loop.call_soon_threadsafe(shutdown_request.set)
        except RuntimeError:
            shutdown_request.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            previous_signal_handlers[signum] = signal.signal(
                signum,
                request_shutdown,
            )
        except (OSError, ValueError) as error:
            runtime.logger.warning(f"signal handler unavailable: {error}")

    try:
        if runtime_health is not None:
            runtime_health.mark_starting()
        application.pre_run()
        runtime.initialize_task_store()
        if application.enable_web:
            web_server = runtime.init_web(application, client)
        else:
            runtime.logger.info("Web UI disabled (enable_web=false)")

        runtime.set_max_concurrent_transmissions(
            client, application.max_concurrent_transmissions
        )
        _run_until_complete(application.loop, runtime.start_server(client))
        runtime.start_channel_library_service(application, client)

        tasks.append(application.loop.create_task(runtime.download_all_chat(client)))
        tasks.append(application.loop.create_task(runtime.periodic_progress_refresh()))
        runtime.logger.info(
            "Created periodic progress refresh task (interval: 20 seconds)"
        )

        runtime.logger.info(
            f"Creating {application.max_download_task} download workers"
        )
        for _ in range(application.max_download_task):
            tasks.append(application.loop.create_task(runtime.worker(client)))

        if application.bot_token or application.resource_bot_token:
            _run_until_complete(
                application.loop,
                runtime.start_download_bot(
                    application,
                    client,
                    runtime.add_download_task,
                    runtime.download_chat_task,
                ),
            )
        if runtime_health is not None:
            runtime_health.mark_ready()
        runtime.logger.success(
            runtime.translate("Successfully started (Press Ctrl+C to stop)")
        )
        runtime.exec_loop(shutdown_request)
    except KeyboardInterrupt:
        request_shutdown()
        runtime.logger.info(runtime.translate("KeyboardInterrupt"))
    except Exception as error:
        startup_failed = True
        if runtime_health is not None:
            try:
                runtime_health.mark_failed()
            except Exception as health_error:
                runtime.logger.warning(
                    f"runtime health failure update failed: {health_error}"
                )
        runtime.logger.exception("{}", error)
        raise
    finally:
        try:
            application.is_running = False
            if runtime_health is not None and not startup_failed:
                try:
                    runtime_health.mark_stopping()
                except Exception as error:
                    runtime.logger.warning(f"runtime health update failed: {error}")
            if web_server is not None:
                try:
                    web_server.stop(timeout=5)
                except Exception as error:
                    runtime.logger.warning(f"stop_web_server ignore: {error}")
            try:
                runtime.stop_channel_library_service(application)
            except Exception as error:
                runtime.logger.warning(f"stop_channel_library_service ignore: {error}")
            if application.bot_token or application.resource_bot_token:
                try:
                    _run_until_complete(
                        application.loop,
                        runtime.stop_download_bot(),
                    )
                except Exception as error:
                    runtime.logger.warning(f"stop_download_bot ignore: {error}")

            try:
                _run_until_complete(
                    application.loop,
                    runtime.stop_server(client),
                )
            except Exception as error:
                runtime.logger.warning(f"stop_server ignore: {error}")

            try:
                _run_until_complete(
                    application.loop,
                    _cancel_and_await(tasks),
                )
            except Exception as error:
                runtime.logger.warning(f"cancel tasks ignore: {error}")

            try:
                _run_until_complete(
                    application.loop,
                    _cancel_remaining_tasks(),
                )
            except Exception as error:
                runtime.logger.warning(f"cancel remaining tasks ignore: {error}")

            runtime.logger.info(runtime.translate("Stopped!"))
            runtime.logger.info(f"{runtime.translate('update config')}......")
            config_updated = False
            try:
                application.update_config()
                config_updated = True
            except Exception as error:
                runtime.logger.warning(f"update_config failed: {error}")
            try:
                runtime.print_performance_stats()
            except Exception as error:
                runtime.logger.warning(f"print_performance_stats failed: {error}")
            if config_updated:
                runtime.logger.success(
                    f"{runtime.translate('Updated last read message_id to config file')},"
                    f"{runtime.translate('total download')} "
                    f"{application.total_download_task}, "
                    f"{runtime.translate('total upload file')} "
                    f"{application.cloud_drive_config.total_upload_success_file_count}"
                )
            close_resources = getattr(
                application,
                "close_runtime_resources",
                None,
            )
            if close_resources is not None:
                try:
                    close_resources()
                except Exception as error:
                    runtime.logger.warning(f"close_runtime_resources failed: {error}")
        finally:
            for signum, previous_handler in previous_signal_handlers.items():
                try:
                    signal.signal(signum, previous_handler)
                except (OSError, ValueError) as error:
                    runtime.logger.warning(f"signal restore unavailable: {error}")

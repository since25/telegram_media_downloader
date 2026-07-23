"""Application lifecycle orchestration for the downloader process."""

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DownloadRuntime:
    """Dependencies supplied by the compatibility entrypoint."""

    logger: Any
    translate: Callable[[str], str]
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


def run_application(application, client, runtime: DownloadRuntime) -> None:
    """Run all process services on the application's owner event loop."""

    tasks = []
    try:
        application.pre_run()
        if application.enable_web:
            runtime.init_web(application, client)
        else:
            runtime.logger.info("Web UI disabled (enable_web=false)")

        runtime.set_max_concurrent_transmissions(
            client, application.max_concurrent_transmissions
        )
        application.loop.run_until_complete(runtime.start_server(client))
        runtime.start_channel_library_service(application, client)
        runtime.logger.success(
            runtime.translate("Successfully started (Press Ctrl+C to stop)")
        )

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

        if application.bot_token:
            application.loop.run_until_complete(
                runtime.start_download_bot(
                    application,
                    client,
                    runtime.add_download_task,
                    runtime.download_chat_task,
                )
            )
        runtime.exec_loop()
    except KeyboardInterrupt:
        runtime.logger.info(runtime.translate("KeyboardInterrupt"))
    except Exception as error:
        runtime.logger.exception("{}", error)
    finally:
        application.is_running = False
        runtime.stop_channel_library_service(application)
        if application.bot_token:
            try:
                application.loop.run_until_complete(runtime.stop_download_bot())
            except Exception as error:
                runtime.logger.warning(f"stop_download_bot ignore: {error}")

        try:
            application.loop.run_until_complete(runtime.stop_server(client))
        except Exception as error:
            runtime.logger.warning(f"stop_server ignore: {error}")

        for task in tasks:
            task.cancel()

        runtime.logger.info(runtime.translate("Stopped!"))
        runtime.logger.info(f"{runtime.translate('update config')}......")
        application.update_config()
        runtime.print_performance_stats()
        runtime.logger.success(
            f"{runtime.translate('Updated last read message_id to config file')},"
            f"{runtime.translate('total download')} {application.total_download_task}, "
            f"{runtime.translate('total upload file')} "
            f"{application.cloud_drive_config.total_upload_success_file_count}"
        )

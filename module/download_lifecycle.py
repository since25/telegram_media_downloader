"""One-file lifecycle with separate download and upload phases."""

import os
import time
import traceback
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from module.app import DownloadStatus
from module.task_state import FileStatus, TaskStatus


@dataclass(frozen=True)
class FileLifecycleRuntime:
    """Dependencies and process-owned metrics for a file lifecycle."""

    app: Any
    logger: Any
    download_media: Callable[..., Awaitable[Any]]
    save_msg_to_file: Callable[..., Awaitable[Any]]
    upload_telegram_chat: Callable[..., Awaitable[Any]]
    update_cloud_upload_stat: Callable[..., Any]
    report_bot_download_status: Callable[..., Awaitable[Any]]
    task_store: Any
    snapshot_node: Callable[..., Any]
    naming_snapshot_context: Any
    queue_entry_times: dict
    task_start_times: dict
    performance_stats: dict
    get_download_result: Callable[..., dict]


async def run_download_phase(
    client,
    message,
    node,
    naming_snapshot: Optional[dict],
    runtime: FileLifecycleRuntime,
) -> tuple[Any, Optional[str]]:
    """Download one file and persist only download-stage evidence."""

    message_id = message.id
    if getattr(node, "task_id", None):
        runtime.task_store.update_task(node.task_id, status=TaskStatus.DOWNLOADING)
        runtime.task_store.upsert_file(
            node.task_id,
            message_id,
            status=FileStatus.DOWNLOADING,
        )

    token = runtime.naming_snapshot_context.set(naming_snapshot)
    try:
        download_status, file_name = await runtime.download_media(
            client,
            message,
            runtime.app.media_types,
            runtime.app.file_formats,
            node,
        )
    finally:
        runtime.naming_snapshot_context.reset(token)

    if runtime.app.enable_download_txt and message.text and not message.media:
        download_status, file_name = await runtime.save_msg_to_file(
            runtime.app, node.chat_id, message
        )

    if not node.bot:
        runtime.app.set_download_id(node, message_id, download_status)
    node.download_status[message_id] = download_status

    if getattr(node, "task_id", None):
        if download_status is DownloadStatus.SuccessDownload:
            file_status = FileStatus.DOWNLOADED
        elif download_status is DownloadStatus.SkipDownload:
            file_status = FileStatus.SKIPPED
        else:
            file_status = FileStatus.FAILED
        runtime.task_store.upsert_file(
            node.task_id,
            message_id,
            status=file_status,
            filename=file_name or "",
            save_path=file_name or "",
        )

    node.stat(download_status, node.chat_id, message_id, file_name)
    runtime.logger.info(
        "download_task: 任务状态更新 - "
        f"success={node.success_download_task}, "
        f"failed={node.failed_download_task}, "
        f"skip={node.skip_download_task}, "
        f"skip_not_found={node.skip_not_found_download_task}"
    )
    return download_status, file_name


async def run_upload_phase(
    client,
    message,
    node,
    download_status,
    file_name: Optional[str],
    telegram_permit,
    runtime: FileLifecycleRuntime,
) -> None:
    """Run Telegram forwarding and cloud upload without re-entering download."""

    message_id = message.id
    await runtime.upload_telegram_chat(
        client,
        node.upload_user if node.upload_user else client,
        runtime.app,
        node,
        message,
        download_status,
        file_name,
    )

    if telegram_permit is not None:
        await telegram_permit.release_and_wait()

    if (
        node.upload_telegram_chat_id
        or download_status is not DownloadStatus.SuccessDownload
        or not file_name
    ):
        return

    runtime.logger.info(
        "download_task: 准备上传文件到云盘 - "
        f"file_name={file_name}, "
        f"enable_upload_file={runtime.app.cloud_drive_config.enable_upload_file}"
    )
    if not runtime.app.cloud_drive_config.enable_upload_file:
        runtime.logger.debug(f"download_task: 云盘上传未启用，跳过上传 - file_name={file_name}")
        return

    ui_file_name = file_name
    if runtime.app.hide_file_name:
        ui_file_name = f"****{os.path.splitext(file_name)[-1]}"

    try:
        if getattr(node, "task_id", None):
            runtime.task_store.update_task(node.task_id, status=TaskStatus.UPLOADING)
            runtime.task_store.upsert_file(
                node.task_id,
                message_id,
                status=FileStatus.UPLOADING,
                filename=file_name,
                save_path=file_name,
            )
        upload_result = await runtime.app.upload_file(
            file_name,
            runtime.update_cloud_upload_stat,
            (node, message_id, ui_file_name),
        )
        if upload_result:
            node.upload_success_count += 1
            if getattr(node, "task_id", None):
                runtime.task_store.upsert_file(
                    node.task_id,
                    message_id,
                    status=FileStatus.UPLOADED,
                    filename=file_name,
                    save_path=file_name,
                )
            runtime.logger.info(
                "download_task: 文件上传成功 - "
                f"file_name={file_name}, "
                f"upload_success_count={node.upload_success_count}"
            )
            return

        if getattr(node, "task_id", None):
            runtime.task_store.upsert_file(
                node.task_id,
                message_id,
                status=FileStatus.UPLOAD_FAILED,
                filename=file_name,
                save_path=file_name,
                error="upload_failed",
            )
        runtime.logger.warning(f"download_task: 文件上传失败 - file_name={file_name}")
    except Exception as error:
        if getattr(node, "task_id", None):
            runtime.task_store.upsert_file(
                node.task_id,
                message_id,
                status=FileStatus.UPLOAD_FAILED,
                filename=file_name,
                save_path=file_name,
                error="upload_failed",
            )
        runtime.logger.error(
            "download_task: 文件上传异常 - " f"file_name={file_name}, error={error}",
            exc_info=True,
        )


def _record_performance(
    node,
    message_id: Optional[int],
    download_status,
    runtime: FileLifecycleRuntime,
) -> None:
    if not message_id or (node.chat_id, message_id) not in runtime.task_start_times:
        return

    task_start_time = runtime.task_start_times.pop((node.chat_id, message_id))
    task_duration = time.time() - task_start_time
    stats = runtime.performance_stats
    stats["total_download_time"] += task_duration
    stats["download_task_count"] += 1
    if download_status == DownloadStatus.SuccessDownload:
        stats["successful_downloads"] += 1
    elif download_status == DownloadStatus.FailedDownload:
        stats["failed_downloads"] += 1
    elif download_status == DownloadStatus.SkipDownload:
        stats["skipped_downloads"] += 1
    if stats["download_task_count"] > 0:
        stats["avg_download_time"] = (
            stats["total_download_time"] / stats["download_task_count"]
        )
    if stats["successful_downloads"] > 0:
        stats["avg_queue_time"] = (
            stats["total_queue_time"] / stats["download_task_count"]
        )
    runtime.logger.debug(
        f"Task performance: message_id={message_id}, "
        f"duration={task_duration:.2f}s, status={download_status}"
    )


async def run_file_lifecycle(
    client,
    message,
    node,
    telegram_permit,
    naming_snapshot: Optional[dict],
    runtime: FileLifecycleRuntime,
) -> None:
    """Run download then upload while preserving independent phase evidence."""

    download_status = None
    file_name = None
    file_size = 0
    message_id = None
    try:
        if not message:
            runtime.logger.info("download_task: message is None，跳过下载")
            node.skip_not_found_download_task += 1
            node.download_status[0] = DownloadStatus.SkipDownload
            return
        if not hasattr(message, "id"):
            runtime.logger.info("download_task: message has no id attribute，跳过下载")
            node.skip_not_found_download_task += 1
            node.download_status[0] = DownloadStatus.SkipDownload
            return

        message_id = message.id
        task_start_time = time.time()
        runtime.task_start_times[(node.chat_id, message_id)] = task_start_time
        queue_wait_time = 0
        queue_key = (node.chat_id, message_id)
        if queue_key in runtime.queue_entry_times:
            queue_wait_time = task_start_time - runtime.queue_entry_times.pop(queue_key)
            runtime.performance_stats["total_queue_time"] += queue_wait_time

        runtime.logger.info(
            f"download_task: Processing message id={message_id}, "
            f"type={type(message)}, has_media={message.media is not None}, "
            f"queue_wait_time={queue_wait_time:.2f}s"
        )
        download_status, file_name = await run_download_phase(
            client, message, node, naming_snapshot, runtime
        )
        if file_name and os.path.exists(file_name):
            file_size = os.path.getsize(file_name)
        runtime.logger.info(
            f"download_task: Download completed for message {message_id}, "
            f"status={download_status}, file_name={file_name}, size={file_size}"
        )

        await run_upload_phase(
            client,
            message,
            node,
            download_status,
            file_name,
            telegram_permit,
            runtime,
        )
        await runtime.report_bot_download_status(
            node.bot,
            node,
            download_status,
            file_size,
            chat_id=node.chat_id,
            message_id=message_id,
            file_name=file_name,
        )
        if getattr(node, "task_id", None):
            runtime.snapshot_node(node)
    except Exception as error:
        runtime.logger.error(f"Error in download_task: {error}")
        traceback.print_exc()
        node.failed_download_task += 1
        runtime.logger.info(
            "download_task: 异常导致任务失败 - " f"失败计数={node.failed_download_task}"
        )
        if message_id:
            node.download_status[message_id] = DownloadStatus.FailedDownload
        if message_id and node.bot:
            try:
                await runtime.report_bot_download_status(
                    node.bot,
                    node,
                    DownloadStatus.FailedDownload,
                    0,
                    chat_id=node.chat_id,
                    message_id=message_id,
                    file_name=file_name,
                )
            except Exception as report_error:
                runtime.logger.error(f"Error reporting download status: {report_error}")
    finally:
        _record_performance(node, message_id, download_status, runtime)
        if message_id:
            download_result = runtime.get_download_result()
            if (
                node.chat_id in download_result
                and message_id in download_result[node.chat_id]
            ):
                del download_result[node.chat_id][message_id]

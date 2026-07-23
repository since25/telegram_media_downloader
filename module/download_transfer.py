"""Single-file Telegram transfer engine and filesystem primitives."""

import asyncio
import os
import shutil
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import pyrogram

from module.app import DownloadStatus


def check_download_finish(
    media_size: int, download_path: str, ui_file_name: str, logger, translate
) -> None:
    """Validate the completed file and remove an invalid target."""

    download_size = os.path.getsize(download_path)
    if media_size == download_size:
        logger.success(f"{translate('Successfully downloaded')} - {ui_file_name}")
        return

    logger.warning(
        f"{translate('Media downloaded with wrong size')}: "
        f"{download_size}, {translate('actual')}: "
        f"{media_size}, {translate('file name')}: {ui_file_name}"
    )
    try:
        os.remove(download_path)
    except Exception:
        pass
    raise ValueError(f"size mismatch: {download_size} != {media_size}")


def move_to_download_path(temp_download_path: str, download_path: str) -> None:
    """Move a completed temporary file into its final directory."""

    directory, _ = os.path.split(download_path)
    os.makedirs(directory, exist_ok=True)
    shutil.move(temp_download_path, download_path)


def retry_timed_out(retry: int, _: int) -> bool:
    """Return whether the legacy retry counter reached its timeout point."""

    return retry == 2


def can_download(
    media_type: str, file_formats: dict, file_format: Optional[str]
) -> bool:
    """Return whether a media format is enabled by configuration."""

    if media_type in {"audio", "document", "video"}:
        allowed_formats: list = file_formats[media_type]
        if file_format not in allowed_formats and allowed_formats[0] != "all":
            return False
    return True


def is_file(file_path: str) -> bool:
    """Return whether a path exists and is not a directory."""

    return not os.path.isdir(file_path) and os.path.exists(file_path)


@dataclass(frozen=True)
class TransferRuntime:
    """Dependencies owned by the compatibility entrypoint."""

    app: Any
    logger: Any
    translate: Callable[[str], str]
    fetch_message: Callable[..., Awaitable[Any]]
    get_media_meta: Callable[..., Awaitable[tuple[str, str, Optional[str]]]]
    record_message_marker: Callable[..., None]
    can_download: Callable[..., bool]
    is_file: Callable[[str], bool]
    check_download_finish: Callable[..., None]
    move_to_download_path: Callable[..., None]
    retry_timed_out: Callable[..., bool]
    update_download_status: Callable[..., Any]
    get_download_result: Callable[..., dict]
    retry_timeout: float
    stall_timeout: int
    last_progress_ts: dict[int, float]
    last_progress_bytes: dict[int, int]
    stalled_message_ids: set[int]


async def watch_stall(
    message_id: int,
    timeout_s: int,
    target_task: asyncio.Task,
    ui_file_name: str,
    runtime: TransferRuntime,
) -> None:
    """Cancel a transfer only after its byte progress has stopped."""

    runtime.last_progress_ts[message_id] = time.time()
    runtime.last_progress_bytes.setdefault(message_id, -1)
    while not target_task.done():
        await asyncio.sleep(5)
        last_ts = runtime.last_progress_ts.get(message_id)
        if last_ts is None:
            continue
        if time.time() - last_ts > timeout_s:
            runtime.logger.warning(
                f"Message[{message_id}] {ui_file_name}: stalled for > "
                f"{timeout_s}s, cancelling download..."
            )
            runtime.stalled_message_ids.add(message_id)
            target_task.cancel()
            return


def _flood_wait_seconds(error: BaseException) -> int:
    """Read the wait duration across supported Pyrogram versions."""

    value = getattr(error, "value", None)
    if value is None:
        value = getattr(error, "seconds", None)
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


async def transfer_media(
    client,
    message,
    media_types: list[str],
    file_formats: dict,
    node,
    naming_snapshot: Optional[dict],
    runtime: TransferRuntime,
):
    """Download one Telegram media file with bounded, classified retries."""

    file_name = ""
    temp_file_name = ""
    ui_file_name = ""
    task_start_time = time.time()
    media_size = 0
    media = None

    try:
        message = await runtime.fetch_message(client, message)
        if not message or getattr(message, "empty", False):
            message_id = getattr(message, "id", "N/A") if message else "N/A"
            runtime.logger.info(f"Message[{message_id}]: message不存在或为空，跳过下载")
            node.skip_not_found_download_task += 1
            runtime.record_message_marker(
                node, "skip_not_found_message_ids", message_id
            )
            return DownloadStatus.SkipDownload, None
    except (pyrogram.errors.BadRequest, pyrogram.errors.NotFound) as error:
        message_id = getattr(message, "id", "N/A")
        runtime.logger.info(
            f"Message[{message_id}]: 无法获取message "
            f"({type(error).__name__}: {error})，跳过下载"
        )
        node.skip_not_found_download_task += 1
        runtime.record_message_marker(node, "skip_not_found_message_ids", message_id)
        return DownloadStatus.SkipDownload, None
    except Exception as error:
        message_id = getattr(message, "id", "N/A")
        runtime.logger.warning(
            f"Message[{message_id}]: 获取message失败 "
            f"({type(error).__name__}: {error})，跳过下载"
        )
        node.skip_not_found_download_task += 1
        runtime.record_message_marker(node, "skip_not_found_message_ids", message_id)
        return DownloadStatus.SkipDownload, None

    try:
        for media_type in media_types:
            media = getattr(message, media_type, None)
            if media is None:
                continue
            file_name, temp_file_name, file_format = await runtime.get_media_meta(
                node.chat_id,
                message,
                media,
                media_type,
                node,
                naming_snapshot=naming_snapshot,
            )
            media_size = getattr(media, "file_size", 0)
            ui_file_name = file_name
            if runtime.app.hide_file_name:
                ui_file_name = f"****{os.path.splitext(file_name)[-1]}"

            if not runtime.can_download(media_type, file_formats, file_format):
                return DownloadStatus.SkipDownload, None
            if runtime.is_file(file_name):
                local_size = os.path.getsize(file_name)
                if local_size == media_size:
                    runtime.logger.info(
                        f"id={message.id} {ui_file_name} "
                        f"{runtime.translate('already download,download skipped')}.\n"
                    )
                    runtime.record_message_marker(
                        node, "completed_file_skip_message_ids", message.id
                    )
                    return DownloadStatus.SkipDownload, None
                runtime.logger.warning(
                    f"id={message.id} {ui_file_name} local size {local_size} "
                    f"!= {media_size}, remove and redownload."
                )
                os.remove(file_name)
            break
    except Exception as error:
        runtime.logger.error(
            f"Message[{message.id}]: "
            f"{runtime.translate('could not be downloaded due to following exception')}:"
            f"\n[{error}].",
            exc_info=True,
        )
        return DownloadStatus.FailedDownload, None

    if media is None:
        return DownloadStatus.SkipDownload, None

    message_id = message.id
    runtime.logger.info(f"Message[{message_id}] {ui_file_name}")
    max_retries = 3
    initial_retry_delay = 1
    max_retry_delay = 30

    try:
        for retry in range(max_retries):
            download_task = None
            watchdog_task = None
            try:
                runtime.logger.info(
                    f"Message[{message_id}] ({ui_file_name}): "
                    f"Starting retry {retry + 1}/{max_retries}..."
                )
                runtime.last_progress_ts[message_id] = time.time()
                runtime.last_progress_bytes.pop(message_id, None)
                runtime.stalled_message_ids.discard(message_id)

                download_result = runtime.get_download_result()
                if (
                    node.chat_id in download_result
                    and message_id in download_result[node.chat_id]
                ):
                    del download_result[node.chat_id][message_id]

                try:
                    if temp_file_name and os.path.exists(temp_file_name):
                        runtime.logger.warning(
                            f"Message[{message_id}] removing temp file: "
                            f"{temp_file_name}"
                        )
                        os.remove(temp_file_name)
                    else:
                        runtime.logger.info(
                            f"Message[{message_id}] no temp file to remove: "
                            f"{temp_file_name}"
                        )

                    if file_name and os.path.exists(file_name):
                        local_size = os.path.getsize(file_name)
                        if local_size != media_size:
                            runtime.logger.warning(
                                f"Message[{message_id}] removing incomplete file: "
                                f"{file_name} (size {local_size} != {media_size})"
                            )
                            os.remove(file_name)
                        else:
                            runtime.logger.info(
                                f"Message[{message_id}] file exists and size is "
                                f"correct, no need to remove: {file_name}"
                            )
                            runtime.record_message_marker(
                                node, "completed_file_skip_message_ids", message_id
                            )
                            return DownloadStatus.SkipDownload, None
                    else:
                        runtime.logger.info(
                            f"Message[{message_id}] final file not found, "
                            f"no need to remove: {file_name}"
                        )
                except Exception as error:
                    runtime.logger.warning(
                        f"Message[{message_id}] error removing files: {error}"
                    )

                retry_delay = min(initial_retry_delay * (2**retry), max_retry_delay)
                if retry > 0:
                    runtime.logger.info(
                        f"Message[{message_id}] Waiting {retry_delay}s before retry..."
                    )
                    await asyncio.sleep(retry_delay)

                download_task = runtime.app.loop.create_task(
                    client.download_media(
                        message,
                        file_name=temp_file_name,
                        progress=runtime.update_download_status,
                        progress_args=(
                            message_id,
                            ui_file_name,
                            task_start_time,
                            node,
                            client,
                        ),
                    )
                )
                watchdog_task = runtime.app.loop.create_task(
                    watch_stall(
                        message_id,
                        runtime.stall_timeout,
                        download_task,
                        ui_file_name,
                        runtime,
                    )
                )
                temp_download_path = await download_task
                if temp_download_path and isinstance(temp_download_path, str):
                    runtime.check_download_finish(
                        media_size, temp_download_path, ui_file_name
                    )
                    await asyncio.sleep(0.5)
                    runtime.move_to_download_path(temp_download_path, file_name)
                    return DownloadStatus.SuccessDownload, file_name
                raise ValueError("download_media returned empty path")

            except asyncio.CancelledError:
                if message_id not in runtime.stalled_message_ids:
                    raise
                runtime.stalled_message_ids.discard(message_id)
                runtime.logger.warning(
                    f"Message[{message_id}]: stalled >{runtime.stall_timeout}s "
                    f"(no progress), cancelled and retrying... "
                    f"({retry + 1}/{max_retries})"
                )
                await asyncio.sleep(1)

            except pyrogram.errors.BadRequest:
                if runtime.retry_timed_out(retry, message_id):
                    runtime.logger.error(
                        f"Message[{message_id}]: file reference expired for "
                        "3 retries, download skipped."
                    )
                    return DownloadStatus.FailedDownload, None
                runtime.logger.warning(
                    f"Message[{message_id}]: file reference expired, refetching..."
                )
                await asyncio.sleep(runtime.retry_timeout)
                message = await runtime.fetch_message(client, message)

            except pyrogram.errors.FloodWait as error:
                wait_seconds = _flood_wait_seconds(error)
                runtime.logger.warning(
                    "Message[{}]: FlowWait {}", message_id, wait_seconds
                )
                await asyncio.sleep(wait_seconds)

            except TypeError:
                if runtime.retry_timed_out(retry, message_id):
                    runtime.logger.error(
                        f"Message[{message_id}]: Timing out after 3 reties, "
                        "download skipped."
                    )
                    return DownloadStatus.FailedDownload, None
                runtime.logger.warning(
                    f"{runtime.translate('Timeout Error occurred when downloading Message')}"
                    f"[{message_id}], {runtime.translate('retrying after')} "
                    f"{runtime.retry_timeout} {runtime.translate('seconds')} "
                    f"({retry + 1}/{max_retries})"
                )
                await asyncio.sleep(runtime.retry_timeout)

            except ValueError as error:
                runtime.logger.warning(
                    f"Message[{message_id}]: {error}, retrying... "
                    f"({retry + 1}/{max_retries})"
                )
                await asyncio.sleep(1)

            except Exception as error:
                server_error_cls = getattr(pyrogram.errors, "ServerError", None)
                connection_error_cls = getattr(pyrogram.errors, "ConnectionError", None)
                if server_error_cls and isinstance(error, server_error_cls):
                    runtime.logger.warning(
                        f"Message[{message_id}]: Telegram Server Error - "
                        f"retrying after {initial_retry_delay * 2}s... "
                        f"({retry + 1}/{max_retries})"
                    )
                    await asyncio.sleep(initial_retry_delay * 2)
                    continue
                if connection_error_cls and isinstance(error, connection_error_cls):
                    runtime.logger.warning(
                        f"Message[{message_id}]: Connection Error - "
                        f"retrying after {initial_retry_delay * 3}s... "
                        f"({retry + 1}/{max_retries})"
                    )
                    await asyncio.sleep(initial_retry_delay * 3)
                    continue

                runtime.logger.error(
                    f"Message[{message_id}]: "
                    f"{runtime.translate('could not be downloaded due to following exception')}: "
                    f"[{error}].",
                    exc_info=True,
                )
                retry_delay = min(initial_retry_delay * (2**retry), max_retry_delay)
                await asyncio.sleep(retry_delay)
            finally:
                if watchdog_task:
                    watchdog_task.cancel()
                if download_task and not download_task.done():
                    download_task.cancel()

        runtime.logger.error(
            f"Message[{message_id}] ({ui_file_name}): "
            f"All {retry + 1} retries failed."
        )
        return DownloadStatus.FailedDownload, None
    finally:
        runtime.last_progress_ts.pop(message_id, None)
        runtime.last_progress_bytes.pop(message_id, None)
        runtime.stalled_message_ids.discard(message_id)
        download_result = runtime.get_download_result()
        if (
            node.chat_id in download_result
            and message_id in download_result[node.chat_id]
        ):
            del download_result[node.chat_id][message_id]

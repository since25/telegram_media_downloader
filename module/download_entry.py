"""Compatibility exports and dependency assembly for downloader clients."""
import asyncio
import contextvars
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import (
    AbstractSet,
    Any,
    Callable,
    Dict,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
)
from urllib.parse import urlsplit

import pyrogram

# 导入Pyrogram错误类
# 使用更通用的导入方式，避免特定异常模块导入错误
import pyrogram.errors
from loguru import logger
from pyrogram import raw
from pyrogram import utils as pyrogram_utils
from pyrogram.client import Client as PyrogramClient
from pyrogram.types import Audio, Document, Photo, Video, VideoNote, Voice
from rich.logging import RichHandler

from module.app import Application, ChatDownloadConfig, DownloadStatus, TaskNode
from module.bot import start_download_bot, stop_download_bot
from module.channel_library_service import ChannelLibraryService
from module.channel_library_store import ChannelLibraryStore
from module.download_stat import (
    get_active_task_nodes,
    get_download_result,
    update_download_status,
)
from module.download_models import (
    PackageCallbackError,
    PackageDownloadResult,
    PackageFinishedCallback,
    PackageMessageResult,
    PackageStartedCallback,
    PreparePackageCallback,
)
from module.download_lifecycle import FileLifecycleRuntime, run_file_lifecycle
from module.download_transfer import (
    TransferRuntime,
    can_download as _transfer_can_download,
    check_download_finish as _transfer_check_download_finish,
    is_file as _transfer_is_file,
    move_to_download_path as _transfer_move_to_download_path,
    retry_timed_out as _transfer_retry_timed_out,
    transfer_media,
    watch_stall as _watch_transfer_stall,
)
from module.download_runtime import DownloadRuntime, run_application
from module.download_queue import enqueue_download, run_worker
from module.package_download import (
    build_package_result as _build_package_result,
    maybe_await as _package_maybe_await,
    run_package_callback as _execute_package_callback,
    run_packages,
)
from module.task_state import get_task_store, snapshot_node
from module.get_chat_history_v2 import get_chat_history_v2
from module.language import _t
from module.pyrogram_extension import (
    HookClient,
    fetch_message,
    get_extension,
    record_download_status,
    report_bot_download_status,
    set_max_concurrent_transmissions,
    set_meta_data,
    update_cloud_upload_stat,
    upload_telegram_chat,
)
from module.telegram_activity import DownloadIntent, get_telegram_activity_gate
from module.web import init_web
from utils.format import truncate_filename, validate_title
from utils.log import LogFilter
from utils.meta import print_meta
from utils.meta_data import MetaData
from utils.updates import check_for_updates

# ---- stall watchdog state ----
DOWNLOAD_LAST_PROGRESS_TS: dict[int, float] = {}
DOWNLOAD_LAST_PROGRESS_BYTES: dict[int, int] = {}
DOWNLOAD_STALLED_MESSAGE_IDS: set[int] = set()


class CommentScanResult(NamedTuple):
    discussion_group_id: int
    comments: list
    failed_comment_ids: list


class MessagePackageScanResult(NamedTuple):
    chat_id: Union[int, str]
    messages: list
    package_plan: Any
    failed_message_ids: list
    following_package_plans: Optional[list] = None


@dataclass
class PrescanScanResult:
    chat_id: Union[int, str]
    prescan_plan: Any
    messages: list
    failed_message_ids: list


def _record_message_marker(node: TaskNode, attribute: str, message_id: Any) -> None:
    if not isinstance(message_id, int):
        return
    values = getattr(node, attribute, None)
    if not isinstance(values, set):
        values = set()
        setattr(node, attribute, values)
    values.add(message_id)


def _comment_thread_reference_ids(comment) -> List[int]:
    """Return known discussion-root ids referenced by a comment message."""

    reference_ids: List[int] = []
    for attr_name in (
        "reply_to_message_id",
        "reply_to_top_message_id",
        "message_thread_id",
    ):
        value = getattr(comment, attr_name, None)
        if isinstance(value, int) and value > 0:
            reference_ids.append(value)

    for attr_name in ("reply_to_message", "reply_to_top_message"):
        nested_message = getattr(comment, attr_name, None)
        nested_id = getattr(nested_message, "id", None)
        if isinstance(nested_id, int) and nested_id > 0:
            reference_ids.append(nested_id)

    return reference_ids


def _is_comment_in_discussion_thread(comment, discussion_message) -> bool:
    """Return whether a fetched discussion-group message belongs to this post."""

    discussion_root_id = getattr(discussion_message, "id", None)
    if not isinstance(discussion_root_id, int) or discussion_root_id <= 0:
        return True

    if getattr(comment, "id", None) == discussion_root_id:
        return True

    reference_ids = _comment_thread_reference_ids(comment)
    if not reference_ids:
        return True

    return discussion_root_id in reference_ids


async def _scan_comment_replies_from_source(
    client,
    chat_id,
    base_message_id,
    start_comment_id,
    end_comment_id,
    expected_comment_count: Optional[int] = None,
    max_scan_count: int = 500,
) -> CommentScanResult:
    """Fetch comments via the source post's replies, matching t.me comment URLs."""

    peer = await client.resolve_peer(chat_id)
    min_id = max(start_comment_id - 1, 0)
    max_id = end_comment_id + 1 if end_comment_id else 0
    offset_id = 0
    comments = []
    seen_ids = set()
    max_scan_count = max(1, max_scan_count)

    while len(comments) < max_scan_count:
        remaining = max_scan_count - len(comments)
        if expected_comment_count is not None:
            remaining = min(remaining, expected_comment_count - len(comments))
        if remaining <= 0:
            break

        limit = min(100, remaining)
        rpc = raw.functions.messages.GetReplies(
            peer=peer,
            msg_id=base_message_id,
            offset_id=offset_id,
            offset_date=0,
            add_offset=0,
            limit=limit,
            max_id=max_id,
            min_id=min_id,
            hash=0,
        )
        raw_messages = await client.invoke(rpc, sleep_threshold=-1)
        page = await pyrogram_utils.parse_messages(client, raw_messages, replies=0)
        page_comments = [
            message
            for message in page
            if message
            and hasattr(message, "id")
            and start_comment_id <= message.id <= end_comment_id
            and not getattr(message, "empty", False)
        ]
        if not page_comments:
            break

        for comment in page_comments:
            if comment.id in seen_ids:
                continue
            comments.append(comment)
            seen_ids.add(comment.id)

        if (
            expected_comment_count is not None
            and len(comments) >= expected_comment_count
        ):
            break

        next_offset_id = min(comment.id for comment in page_comments)
        if next_offset_id <= start_comment_id or next_offset_id == offset_id:
            break
        offset_id = next_offset_id

    comments.sort(key=lambda comment: comment.id)
    return CommentScanResult(chat_id, comments, [])


# ---- performance monitoring ----
PERFORMANCE_STATS: dict[str, float] = {
    "total_download_time": 0,  # 总下载时间
    "total_queue_time": 0,  # 总队列等待时间
    "total_network_time": 0,  # 总网络请求时间
    "total_io_time": 0,  # 总磁盘IO时间
    "download_task_count": 0,  # 总下载任务数
    "successful_downloads": 0,  # 成功下载数
    "failed_downloads": 0,  # 失败下载数
    "skipped_downloads": 0,  # 跳过下载数
    "avg_download_speed": 0,  # 平均下载速度
    "avg_queue_time": 0,  # 平均队列等待时间
    "avg_download_time": 0,  # 平均下载时间
}

# 用于跟踪单个任务的开始时间
TASK_START_TIMES: dict[
    tuple[Union[int, str], int], float
] = {}  # (chat_id, message_id) -> start_time

# 用于跟踪队列等待时间
QUEUE_ENTRY_TIMES: dict[
    tuple[Union[int, str], int], float
] = {}  # (chat_id, message_id) -> queue_entry_time

# 携带单次 download_task -> download_media -> _get_media_meta 调用链的命名快照。
# download_media 被 module.pyrogram_extension.record_download_status 装饰，
# 装饰器只透传固定的位置参数、不支持额外关键字参数，因此用 ContextVar 在
# 同一个 asyncio 调用链内传递命名快照；每次调用后立即 reset，不做跨调用的
# 持久/全局状态。
_naming_snapshot_ctx: "contextvars.ContextVar[Optional[dict]]" = contextvars.ContextVar(
    "_naming_snapshot_ctx", default=None
)

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler()],
)

CONFIG_NAME = "config.yaml"
DATA_FILE_NAME = "data.yaml"
APPLICATION_NAME = "media_downloader"
app = Application(CONFIG_NAME, DATA_FILE_NAME, APPLICATION_NAME)

queue: asyncio.Queue = asyncio.Queue()
RETRY_TIME_OUT = 3
STALL_TIMEOUT = 600  # 10分钟无进度就判定卡死
logging.getLogger("pyrogram.session.session").addFilter(LogFilter())
logging.getLogger("pyrogram.client").addFilter(LogFilter())

logging.getLogger("pyrogram").setLevel(logging.WARNING)


def _check_download_finish(media_size: int, download_path: str, ui_file_name: str):
    """Check download task if finish"""
    return _transfer_check_download_finish(
        media_size, download_path, ui_file_name, logger, _t
    )


def _move_to_download_path(temp_download_path: str, download_path: str):
    """Move file to download path

    Parameters
    ----------
    temp_download_path: str
        Temporary download path

    download_path: str
        Download path

    """

    return _transfer_move_to_download_path(temp_download_path, download_path)


def _check_timeout(retry: int, _: int):
    """Check if message download timeout, then add message id into failed_ids

    Parameters
    ----------
    retry: int
        Retry download message times

    message_id: int
        Try to download message 's id

    """
    return _transfer_retry_timed_out(retry, _)


def _can_download(_type: str, file_formats: dict, file_format: Optional[str]) -> bool:
    """
    Check if the given file format can be downloaded.

    Parameters
    ----------
    _type: str
        Type of media object.
    file_formats: dict
        Dictionary containing the list of file_formats
        to be downloaded for `audio`, `document` & `video`
        media types
    file_format: str
        Format of the current file to be downloaded.

    Returns
    -------
    bool
        True if the file format can be downloaded else False.
    """
    return _transfer_can_download(_type, file_formats, file_format)


def _is_exist(file_path: str) -> bool:
    """
    Check if a file exists and it is not a directory.

    Parameters
    ----------
    file_path: str
        Absolute path of the file to be checked.

    Returns
    -------
    bool
        True if the file exists else False.
    """
    return _transfer_is_file(file_path)


# pylint: disable = R0912


async def _get_media_meta(
    chat_id: Union[int, str],
    message: pyrogram.types.Message,
    media_obj: Union[Audio, Document, Photo, Video, VideoNote, Voice],
    _type: str,
    node: Optional["TaskNode"] = None,
    naming_snapshot: Optional[dict] = None,
) -> Tuple[str, str, Optional[str]]:
    """Extract file name and file id from media object.

    Parameters
    ----------
    media_obj: Union[Audio, Document, Photo, Video, VideoNote, Voice]
        Media object to be extracted.
    _type: str
        Type of media object.
    naming_snapshot: Optional[dict]
        Optional per-queue-item naming context captured at enqueue time
        (``{"context": PackageNamingContext, "item": PackageMediaItem|None}``).
        When provided, it takes precedence over ``node.package_naming_context``
        / ``node.package_media_items`` so a stray message is always named by
        the package it was actually enqueued for.

    Returns
    -------
    Tuple[str, str, Optional[str]]
        file_name, file_format
    """
    if _type in ["audio", "document", "video"]:
        # pylint: disable = C0301
        file_format: Optional[str] = media_obj.mime_type.split("/")[-1]  # type: ignore
    else:
        file_format = None

    file_name = None
    temp_file_name = None
    dirname = validate_title(f"{chat_id}")
    if message.chat and message.chat.title:
        dirname = validate_title(f"{message.chat.title}")

    if message.date:
        datetime_dir_name = message.date.strftime(app.date_format)
    else:
        datetime_dir_name = "0"

    if _type in ["voice", "video_note"]:
        # pylint: disable = C0209
        file_format = media_obj.mime_type.split("/")[-1]  # type: ignore
        file_save_path = app.get_file_save_path(_type, dirname, datetime_dir_name)
        file_name = "{} - {}_{}.{}".format(
            message.id,
            _type,
            media_obj.date.isoformat(),  # type: ignore
            file_format,
        )
        file_name = validate_title(file_name)

        # 如果有标签，添加到文件名前面
        if node and hasattr(node, "file_name_tag") and node.file_name_tag:
            tag = validate_title(node.file_name_tag)
            max_tag_len = 30
            if len(tag) > max_tag_len:
                tag = tag[:max_tag_len]
            file_name = f"{message.id} - {tag} - {file_name}"

        temp_file_name = os.path.join(app.temp_save_path, dirname, file_name)

        file_name = os.path.join(file_save_path, file_name)
    else:
        file_name = getattr(media_obj, "file_name", None)
        caption = getattr(message, "caption", None)

        file_name_suffix = ".unknown"
        if not file_name:
            file_name_suffix = get_extension(
                media_obj.file_id, getattr(media_obj, "mime_type", "")
            )
        else:
            # file_name = file_name.split(".")[0]
            _, file_name_without_suffix = os.path.split(os.path.normpath(file_name))
            file_name, file_name_suffix = os.path.splitext(file_name_without_suffix)
            if not file_name_suffix:
                file_name_suffix = get_extension(
                    media_obj.file_id, getattr(media_obj, "mime_type", "")
                )

        media_group_id = (
            str(message.media_group_id) if message.media_group_id is not None else None
        )

        if caption:
            caption = validate_title(caption)
            app.set_caption_name(chat_id, media_group_id, caption)
            app.set_caption_entities(chat_id, media_group_id, message.caption_entities)
        else:
            caption = app.get_caption_name(chat_id, media_group_id)

        if not file_name and message.photo:
            file_name = f"{message.photo.file_unique_id}"

        # DEBUG: 看看 caption 到底有没有拿到、media_group_id 是不是同一组
        logger.debug(
            "meta: chat_id={} msg_id={} group_id={} raw_caption={!r} final_caption={!r} base_name={!r} suffix={!r}",
            chat_id,
            getattr(message, "id", None),
            getattr(message, "media_group_id", None),
            getattr(message, "caption", None),
            caption,
            file_name,
            file_name_suffix,
        )

        gen_file_name = (
            app.get_file_name(message.id, file_name, caption) + file_name_suffix
        )

        # 自动从 caption 提取标签（如果 node.file_name_tag 为空）
        # 如果有手动指定的统一标签，则同时保留 caption 标签和手动标签
        auto_caption_tag = None
        if caption and "caption" not in app.file_name_prefix:
            auto_caption_tag = (
                validate_title(caption[:30])
                if len(caption) > 30
                else validate_title(caption)
            )

        manual_tag = None
        if node and hasattr(node, "file_name_tag") and node.file_name_tag:
            manual_tag = validate_title(node.file_name_tag)
            if len(manual_tag) > 30:
                manual_tag = manual_tag[:30]

        # 组合标签：优先 caption，如果有手动标签则追加
        combined_tag = None
        if auto_caption_tag and manual_tag:
            # 两者都有：caption + 手动标签
            combined_tag = f"{auto_caption_tag} - {manual_tag}"
        elif auto_caption_tag:
            combined_tag = auto_caption_tag
        elif manual_tag:
            combined_tag = manual_tag

        # 如果有标签，添加到文件名前面
        if combined_tag:
            split = app.file_name_prefix_split
            prefix = f"{message.id}{split}"
            if gen_file_name.startswith(prefix):
                gen_file_name = (
                    prefix + combined_tag + split + gen_file_name[len(prefix) :]
                )
            else:
                gen_file_name = (
                    f"{message.id}{split}{combined_tag}{split}{gen_file_name}"
                )

        if node and getattr(node, "comment_naming_context", None):
            from module.comment_workflow import build_name_for_strategy

            gen_file_name = build_name_for_strategy(
                message, node.comment_naming_context
            )

        context = (naming_snapshot or {}).get("context") or getattr(
            node, "package_naming_context", None
        )
        if node and context:
            from module.comment_workflow import (
                PackageMediaItem,
                build_package_name_for_strategy,
            )

            package_item = (naming_snapshot or {}).get("item")
            if package_item is None:
                package_media_items = getattr(node, "package_media_items", None)
                if isinstance(package_media_items, dict):
                    package_item = package_media_items.get(message.id)

            if package_item is None:
                raw_caption = getattr(message, "caption", None)
                package_item = PackageMediaItem(
                    message=message,
                    media_type=_type,
                    caption_for_naming=(raw_caption or context.package_title),
                    original_caption=raw_caption,
                    inherited_caption=not bool(raw_caption),
                )

            gen_file_name = build_package_name_for_strategy(package_item, context)

        file_save_path = app.get_file_save_path(_type, dirname, datetime_dir_name)

        temp_file_name = os.path.join(app.temp_save_path, dirname, gen_file_name)

        file_name = os.path.join(file_save_path, gen_file_name)
    return truncate_filename(file_name), truncate_filename(temp_file_name), file_format


async def add_download_task(
    message: pyrogram.types.Message,
    node: TaskNode,
):
    """Compatibility wrapper for queue admission."""

    return await enqueue_download(
        message,
        node,
        queue,
        QUEUE_ENTRY_TIMES,
        get_telegram_activity_gate(),
        PyrogramClient,
        logger,
    )


async def save_msg_to_file(
    app, chat_id: Union[int, str], message: pyrogram.types.Message
):
    """Write message text into file"""
    dirname = validate_title(
        message.chat.title if message.chat and message.chat.title else str(chat_id)
    )
    datetime_dir_name = message.date.strftime(app.date_format) if message.date else "0"

    file_save_path = app.get_file_save_path("msg", dirname, datetime_dir_name)
    file_name = os.path.join(
        app.temp_save_path,
        file_save_path,
        f"{app.get_file_name(message.id, None, None)}.txt",
    )

    os.makedirs(os.path.dirname(file_name), exist_ok=True)

    if _is_exist(file_name):
        return DownloadStatus.SkipDownload, None

    with open(file_name, "w", encoding="utf-8") as f:
        f.write(message.text or "")

    return DownloadStatus.SuccessDownload, file_name


def _build_file_lifecycle_runtime() -> FileLifecycleRuntime:
    return FileLifecycleRuntime(
        app=app,
        logger=logger,
        download_media=download_media,
        save_msg_to_file=save_msg_to_file,
        upload_telegram_chat=upload_telegram_chat,
        update_cloud_upload_stat=update_cloud_upload_stat,
        report_bot_download_status=report_bot_download_status,
        task_store=get_task_store(),
        snapshot_node=snapshot_node,
        naming_snapshot_context=_naming_snapshot_ctx,
        queue_entry_times=QUEUE_ENTRY_TIMES,
        task_start_times=TASK_START_TIMES,
        performance_stats=PERFORMANCE_STATS,
        get_download_result=get_download_result,
    )


async def download_task(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    node: TaskNode,
    telegram_permit: Optional[DownloadIntent] = None,
    naming_snapshot: Optional[dict] = None,
):
    """Compatibility wrapper for one download/upload lifecycle."""

    await run_file_lifecycle(
        client,
        message,
        node,
        telegram_permit,
        naming_snapshot,
        _build_file_lifecycle_runtime(),
    )


# pylint: disable = R0915,R0914


async def _stall_watchdog(
    message_id: int, timeout_s: int, target_task: asyncio.Task, ui_file_name: str
):
    """Compatibility wrapper around the transfer stall watchdog."""

    await _watch_transfer_stall(
        message_id,
        timeout_s,
        target_task,
        ui_file_name,
        _build_transfer_runtime(),
    )


def _build_transfer_runtime() -> TransferRuntime:
    return TransferRuntime(
        app=app,
        logger=logger,
        translate=_t,
        fetch_message=fetch_message,
        get_media_meta=_get_media_meta,
        record_message_marker=_record_message_marker,
        can_download=_can_download,
        is_file=_is_exist,
        check_download_finish=_check_download_finish,
        move_to_download_path=_move_to_download_path,
        retry_timed_out=_check_timeout,
        update_download_status=update_download_status,
        get_download_result=get_download_result,
        retry_timeout=RETRY_TIME_OUT,
        stall_timeout=STALL_TIMEOUT,
        last_progress_ts=DOWNLOAD_LAST_PROGRESS_TS,
        last_progress_bytes=DOWNLOAD_LAST_PROGRESS_BYTES,
        stalled_message_ids=DOWNLOAD_STALLED_MESSAGE_IDS,
    )


@record_download_status
async def download_media(
    client: PyrogramClient,
    message: pyrogram.types.Message,
    media_types: List[str],
    file_formats: dict,
    node: TaskNode,
):
    """Compatibility wrapper around the single-file transfer engine."""

    return await transfer_media(
        client,
        message,
        media_types,
        file_formats,
        node,
        _naming_snapshot_ctx.get(),
        _build_transfer_runtime(),
    )


def _load_config():
    """Load config"""
    app.load_config()


def _check_config() -> bool:
    """Check config"""
    print_meta(logger)
    try:
        _load_config()
        logger.add(
            os.path.join(app.log_file_path, "tdl.log"),
            rotation="10 MB",
            retention="10 days",
            level=app.log_level,
        )
    except Exception as e:
        logger.exception(f"load config error: {e}")
        return False

    return True


def print_performance_stats():
    """Print performance statistics"""
    logger.info("=== Performance Statistics ===")
    logger.info(f"Total download time: {PERFORMANCE_STATS['total_download_time']:.2f}s")
    logger.info(f"Total queue time: {PERFORMANCE_STATS['total_queue_time']:.2f}s")
    logger.info(f"Total tasks: {PERFORMANCE_STATS['download_task_count']}")
    logger.info(f"Successful downloads: {PERFORMANCE_STATS['successful_downloads']}")
    logger.info(f"Failed downloads: {PERFORMANCE_STATS['failed_downloads']}")
    logger.info(f"Skipped downloads: {PERFORMANCE_STATS['skipped_downloads']}")
    logger.info(f"Average download time: {PERFORMANCE_STATS['avg_download_time']:.2f}s")
    logger.info(f"Average queue time: {PERFORMANCE_STATS['avg_queue_time']:.2f}s")
    logger.info("=============================")


async def periodic_progress_refresh():
    """
    定期刷新所有活跃TaskNode的进度信息
    每30秒执行一次
    """
    import time

    from module.pyrogram_extension import report_bot_status

    # 全局冷却时间，确保短时间内不会有太多API请求
    global_last_refresh_time = 0
    GLOBAL_COOLDOWN = 8  # 全局冷却时间：8秒
    MAX_NODES_PER_REFRESH = 5  # 每次刷新最多处理5个节点

    while app.is_running:
        try:
            # 获取所有活跃的TaskNode
            active_nodes = get_active_task_nodes()

            # 如果没有活跃节点，跳过这次刷新
            if not active_nodes:
                await asyncio.sleep(30)
                continue

            # 只处理部分活跃节点，减少API请求量
            nodes_to_refresh = list(active_nodes.items())[:MAX_NODES_PER_REFRESH]

            # 为选中的活跃TaskNode更新进度
            for task_id, node in nodes_to_refresh:
                if node.bot and node.reply_message_id:
                    # 检查全局冷却时间
                    current_time = time.time()
                    if current_time - global_last_refresh_time < GLOBAL_COOLDOWN:
                        # 等待到冷却时间结束
                        await asyncio.sleep(
                            GLOBAL_COOLDOWN - (current_time - global_last_refresh_time)
                        )

                    try:
                        # 使用immediate_reply=False，尊重现有的1秒更新限制
                        # 但我们的全局冷却和节点数量限制已经提供了额外保护
                        await report_bot_status(node.bot, node)
                        # 更新全局冷却时间
                        global_last_refresh_time = time.time()

                        # 小延迟，避免过快发送请求
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.debug(
                            f"Failed to refresh progress for task {task_id}: {e}"
                        )
                        # 出错时也更新冷却时间，避免重试风暴
                        global_last_refresh_time = time.time()
        except Exception as e:
            logger.debug(f"Periodic progress refresh error: {e}")

        # 等待30秒后再次执行
        await asyncio.sleep(30)


async def worker(client: PyrogramClient):
    """Compatibility wrapper around the process-local download queue."""

    await run_worker(
        client,
        queue,
        download_task,
        get_telegram_activity_gate(),
        logger,
    )


async def scan_comment_range(
    client,
    chat_id,
    base_message_id,
    start_comment_id,
    end_comment_id,
    expected_comment_count: Optional[int] = None,
    missing_streak_limit: Optional[int] = None,
):
    """Resolve a post discussion group and fetch comments in an inclusive range."""
    if not isinstance(expected_comment_count, int) or expected_comment_count <= 0:
        expected_comment_count = None
    if not isinstance(missing_streak_limit, int) or missing_streak_limit <= 0:
        missing_streak_limit = None

    max_scan_count = max(1, end_comment_id - start_comment_id + 1)
    try:
        return await _scan_comment_replies_from_source(
            client,
            chat_id,
            base_message_id,
            start_comment_id,
            end_comment_id,
            expected_comment_count=expected_comment_count,
            max_scan_count=max_scan_count,
        )
    except Exception as source_error:
        logger.warning(
            "scan_comment_range: source replies scan failed, "
            f"falling back to discussion chat: {source_error}"
        )

    # 获取讨论组信息
    try:
        # 使用get_discussion_message获取讨论组信息
        logger.info(
            f"download_comments: 尝试获取讨论组信息 - chat_id={chat_id}, base_message_id={base_message_id}"
        )
        discussion_message = await client.get_discussion_message(
            chat_id, base_message_id
        )

        if not discussion_message:
            logger.error(
                f"download_comments: 无法获取讨论组消息 - chat_id={chat_id}, base_message_id={base_message_id}"
            )
            raise ValueError("discussion message not found")

        logger.info(
            f"download_comments: 成功获取讨论组消息 - id={discussion_message.id}, chat_id={discussion_message.chat.id}, title={discussion_message.chat.title}"
        )
        discussion_group_id = discussion_message.chat.id
        logger.info(f"download_comments: 使用讨论组ID: {discussion_group_id}")
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"download_comments: 获取讨论组信息失败: {e}")
        import traceback

        traceback.print_exc()
        raise

    # 生成评论ID列表
    comment_ids = list(range(start_comment_id, end_comment_id + 1))
    logger.info(f"download_comments: 生成评论ID列表: {comment_ids}")

    # 获取所有评论对象 - 使用批量获取提高效率
    comments = []
    failed_comment_ids = []
    matched_comment_count = 0
    missing_streak = 0
    scan_complete = False
    BATCH_SIZE = 50  # Pyrogram批量获取的建议最大限制

    # 将评论ID列表分成多个批次
    for i in range(0, len(comment_ids), BATCH_SIZE):
        batch_ids = comment_ids[i : i + BATCH_SIZE]
        logger.info(
            f"download_comments: 批量获取评论 - 批次 {i//BATCH_SIZE + 1}/{len(comment_ids)//BATCH_SIZE + 1}, 评论ID={batch_ids}"
        )

        try:
            # 批量获取评论
            batch_comments = await client.get_messages(discussion_group_id, batch_ids)
            if not isinstance(batch_comments, list):
                batch_comments = [batch_comments]

            # 处理批量获取的结果
            for comment in batch_comments:
                if not comment or getattr(comment, "empty", False):
                    missing_streak += 1
                    logger.warning(f"download_comments: 未找到评论 - 可能ID不存在")
                    if (
                        missing_streak_limit is not None
                        and missing_streak >= missing_streak_limit
                    ):
                        scan_complete = True
                        break
                    continue

                has_comment_id = hasattr(comment, "id")
                # 检查评论对象的详细信息
                logger.info(
                    f"download_comments: 评论对象信息 - id={getattr(comment, 'id', None)}, type={type(comment)}, empty={getattr(comment, 'empty', None)}, has_media={getattr(comment, 'media', None) is not None}"
                )
                logger.info(
                    f"download_comments: 评论属性 - hasattr(comment, 'id')={has_comment_id}, hasattr(comment, 'chat')={hasattr(comment, 'chat')}"
                )

                # 即使comment.empty为True，也尝试检查是否有有价值的信息
                if has_comment_id:
                    if not _is_comment_in_discussion_thread(
                        comment, discussion_message
                    ):
                        logger.info(
                            "download_comments: 评论 " f"{comment.id} 不属于当前讨论串，跳过"
                        )
                        missing_streak += 1
                        if (
                            missing_streak_limit is not None
                            and missing_streak >= missing_streak_limit
                        ):
                            scan_complete = True
                            break
                        continue
                    # 如果评论有ID，无论是否为空，都添加到列表中
                    logger.info(f"download_comments: 评论 {comment.id} 信息可用，添加到下载列表")
                    comments.append(comment)
                    missing_streak = 0
                    matched_comment_count += 1
                    if (
                        expected_comment_count is not None
                        and matched_comment_count >= expected_comment_count
                    ):
                        scan_complete = True
                        break
                else:
                    missing_streak += 1
                    logger.warning(f"download_comments: 评论没有ID属性，跳过")
                    if (
                        missing_streak_limit is not None
                        and missing_streak >= missing_streak_limit
                    ):
                        scan_complete = True
                        break
                    continue
            if scan_complete:
                break

        except Exception as e:
            logger.error(f"download_comments: 批量获取评论失败 - 批次 {i//BATCH_SIZE + 1}: {e}")
            import traceback

            traceback.print_exc()
            # 对于批量获取失败的情况，尝试单独获取每个评论
            for comment_id in batch_ids:
                try:
                    logger.info(f"download_comments: 单独重试获取评论 - id={comment_id}")
                    comment = await client.get_messages(discussion_group_id, comment_id)
                    if (
                        not comment
                        or getattr(comment, "empty", False)
                        or not hasattr(comment, "id")
                    ):
                        missing_streak += 1
                        if (
                            missing_streak_limit is not None
                            and missing_streak >= missing_streak_limit
                        ):
                            scan_complete = True
                            break
                        continue
                    if comment and hasattr(comment, "id"):
                        if not _is_comment_in_discussion_thread(
                            comment, discussion_message
                        ):
                            logger.info(
                                "download_comments: 评论 " f"{comment.id} 不属于当前讨论串，跳过"
                            )
                            missing_streak += 1
                            if (
                                missing_streak_limit is not None
                                and missing_streak >= missing_streak_limit
                            ):
                                scan_complete = True
                                break
                            continue
                        comments.append(comment)
                        missing_streak = 0
                        matched_comment_count += 1
                        logger.info(f"download_comments: 单独获取评论 {comment.id} 成功")
                        if (
                            expected_comment_count is not None
                            and matched_comment_count >= expected_comment_count
                        ):
                            scan_complete = True
                            break
                except Exception as single_e:
                    logger.error(
                        f"download_comments: 单独获取评论 {comment_id} 失败: {single_e}"
                    )
                    failed_comment_ids.append(comment_id)
                    missing_streak += 1
                    if (
                        missing_streak_limit is not None
                        and missing_streak >= missing_streak_limit
                    ):
                        scan_complete = True
                        break
            if scan_complete:
                break

    # 按评论ID排序
    comments.sort(key=lambda x: x.id)
    logger.info(f"评论排序完成，顺序: {[c.id for c in comments]}")

    return CommentScanResult(discussion_group_id, comments, failed_comment_ids)


async def scan_message_package(
    client: PyrogramClient,
    chat_id: Union[int, str],
    start_message_id: int,
    max_scan_count: int = 500,
    batch_size: int = 50,
    following_package_count: int = 3,
) -> MessagePackageScanResult:
    """Fetch a bounded ordinary-message window and plan one package plus followers."""
    from module.comment_workflow import plan_message_package_sequence

    max_scan_count = max(0, max_scan_count)
    batch_size = max(1, batch_size)
    following_package_count = max(0, following_package_count)
    message_ids = list(range(start_message_id, start_message_id + max_scan_count))
    fetched_messages = []
    failed_message_ids = []

    def build_result() -> MessagePackageScanResult:
        sequence_plan = plan_message_package_sequence(
            fetched_messages,
            start_message_id=start_message_id,
            following_package_count=following_package_count,
            max_scan_count=max_scan_count,
        )
        package_plan = sequence_plan.primary
        package_messages = [item.message for item in package_plan.items]
        return MessagePackageScanResult(
            chat_id,
            package_messages,
            package_plan,
            failed_message_ids,
            sequence_plan.following,
        )

    def has_enough_following_packages(result: MessagePackageScanResult) -> bool:
        following_plans = result.following_package_plans or []
        return len(following_plans) >= following_package_count

    for index in range(0, len(message_ids), batch_size):
        batch_ids = message_ids[index : index + batch_size]
        try:
            batch_messages = await client.get_messages(chat_id, batch_ids)
            if not isinstance(batch_messages, list):
                batch_messages = [batch_messages]
            fetched_count_before_batch = len(fetched_messages)
            fetched_messages.extend(
                message
                for message in batch_messages
                if message and hasattr(message, "id")
            )
        except Exception as e:
            logger.error(
                "scan_message_package: batch fetch failed "
                f"chat_id={chat_id} ids={batch_ids}: {e}"
            )
            for message_id in batch_ids:
                try:
                    message = await client.get_messages(chat_id, message_id)
                    if message and hasattr(message, "id"):
                        fetched_messages.append(message)
                except Exception as single_e:
                    logger.error(
                        "scan_message_package: single fetch failed "
                        f"chat_id={chat_id} id={message_id}: {single_e}"
                    )
                    failed_message_ids.append(message_id)

                result = build_result()
                if has_enough_following_packages(result):
                    return result

            continue

        result = build_result()
        if has_enough_following_packages(result):
            return result
        if (
            fetched_count_before_batch
            and len(fetched_messages) == fetched_count_before_batch
        ):
            return result

    return build_result()


async def scan_prescan_packages(
    client: PyrogramClient,
    chat_id: Union[int, str],
    start_message_id: int,
    max_messages: int = 5000,
    max_packages: int = 50,
    missing_streak_limit: int = 200,
    batch_size: int = 50,
    batch_delay_seconds: int = 1,
    sleep=asyncio.sleep,
    progress_callback=None,
    should_stop=None,
) -> PrescanScanResult:
    """Slowly fetch ordinary messages and build a multi-package prescan plan."""
    from module.prescan_workflow import PrescanLimits, plan_prescan_packages

    max_messages = max(0, max_messages)
    batch_size = max(1, batch_size)
    limits = PrescanLimits(
        max_messages=max_messages,
        max_packages=max_packages,
        missing_streak_limit=missing_streak_limit,
    )
    message_ids = list(range(start_message_id, start_message_id + max_messages))
    fetched_messages = []
    failed_message_ids = []
    saw_message = False
    missing_streak = 0

    def build_plan():
        return plan_prescan_packages(
            fetched_messages,
            start_message_id=start_message_id,
            limits=limits,
        )

    async def report_progress(rate_limited_seconds=None):
        if progress_callback is None:
            return build_plan()

        current_plan = build_plan()
        latest_package = current_plan.packages[-1] if current_plan.packages else None
        try:
            result = progress_callback(
                {
                    "scanned_count": current_plan.scanned_count,
                    "package_count": len(current_plan.packages),
                    "latest_package": latest_package,
                    "rate_limited_seconds": rate_limited_seconds,
                }
            )
            if hasattr(result, "__await__"):
                await result
        except Exception as progress_error:
            logger.warning(
                f"scan_prescan_packages: progress callback failed: {progress_error}"
            )
        return current_plan

    def flood_wait_value(error):
        value = getattr(error, "value", None)
        if isinstance(value, int) and value > 0:
            return value
        return None

    def add_batch_messages(batch_messages):
        if not isinstance(batch_messages, list):
            batch_messages = [batch_messages]
        valid_messages = [
            message for message in batch_messages if message and hasattr(message, "id")
        ]
        fetched_messages.extend(valid_messages)
        return {message.id for message in valid_messages}

    def track_missing_streak(batch_ids, present_ids):
        nonlocal saw_message, missing_streak
        for message_id in batch_ids:
            if message_id in present_ids:
                saw_message = True
                missing_streak = 0
            elif saw_message:
                missing_streak += 1

    async def fetch_batch(batch_ids):
        batch_messages = await client.get_messages(chat_id, batch_ids)
        present_ids = add_batch_messages(batch_messages)
        track_missing_streak(batch_ids, present_ids)

    async def fetch_messages_individually(batch_ids):
        for message_id in batch_ids:
            try:
                message = await client.get_messages(chat_id, message_id)
                present_ids = add_batch_messages(message)
                track_missing_streak([message_id], present_ids)
            except Exception as single_error:
                logger.error(
                    "scan_prescan_packages: single fetch failed "
                    f"chat_id={chat_id} id={message_id}: {single_error}"
                )
                failed_message_ids.append(message_id)
                track_missing_streak([message_id], set())

    for index in range(0, len(message_ids), batch_size):
        if should_stop and should_stop():
            logger.info(
                "scan_prescan_packages: stop requested, ending scan early "
                f"chat_id={chat_id} scanned={len(fetched_messages)}"
            )
            break
        batch_ids = message_ids[index : index + batch_size]
        try:
            await fetch_batch(batch_ids)
        except Exception as e:
            wait_seconds = flood_wait_value(e)
            if wait_seconds is None:
                logger.error(
                    "scan_prescan_packages: batch fetch failed "
                    f"chat_id={chat_id} ids={batch_ids}: {e}"
                )
                await fetch_messages_individually(batch_ids)
            else:
                rate_limited_seconds = wait_seconds + 1
                await report_progress(rate_limited_seconds=rate_limited_seconds)
                await sleep(rate_limited_seconds)
                try:
                    await fetch_batch(batch_ids)
                except Exception as retry_e:
                    logger.error(
                        "scan_prescan_packages: retry after FloodWait failed "
                        f"chat_id={chat_id} ids={batch_ids}: {retry_e}"
                    )
                    await fetch_messages_individually(batch_ids)

        await report_progress()
        should_stop_for_missing = saw_message and missing_streak >= missing_streak_limit
        is_final_batch = index + batch_size >= len(message_ids)
        if should_stop_for_missing:
            break
        if not is_final_batch and batch_delay_seconds > 0:
            await sleep(batch_delay_seconds)

    return PrescanScanResult(
        chat_id=chat_id,
        prescan_plan=build_plan(),
        messages=fetched_messages,
        failed_message_ids=failed_message_ids,
    )


async def download_prepared_comments(
    comments,
    download_filter,
    node,
    failed_comment_ids=None,
):
    """Download already-scanned comment media and preserve preview scan failures."""
    from module.download_stat import remove_active_task_node
    from module.pyrogram_extension import report_bot_status, set_meta_data
    from utils.format import validate_title
    from utils.meta_data import MetaData

    failed_comment_ids = list(failed_comment_ids or [])

    try:
        if download_filter:

            class TempChatDownloadConfig:
                def __init__(self):
                    self.download_filter = download_filter

            temp_config = TempChatDownloadConfig()
            filtered_comments = []
            for comment in comments:
                meta_data = MetaData()
                caption = comment.caption
                if caption:
                    caption = validate_title(caption)
                set_meta_data(meta_data, comment, caption)

                if app.exec_filter(temp_config, meta_data):
                    filtered_comments.append(comment)

            comments = filtered_comments

        expected_comment_tasks = len(comments) + len(failed_comment_ids)
        logger.info(f"设置预期评论任务数: {expected_comment_tasks}")

        if failed_comment_ids:
            node.failed_download_task += len(failed_comment_ids)
            node.total_download_task += len(failed_comment_ids)
            node.total_task += len(failed_comment_ids)
            await report_bot_status(node.bot, node)

        logger.info(f"开始下载评论媒体，共 {len(comments)} 条评论")
        for i, comment in enumerate(comments):
            if not node.is_running:
                logger.info("任务已停止，中断下载")
                break

            logger.info(
                f"处理评论 {i+1}/{len(comments)}: id={comment.id}, has_media={comment.media is not None}, type={type(comment)}"
            )

            try:
                comment_chat_id = comment.chat.id if comment.chat else "未知"
                logger.info(
                    f"准备添加下载任务: comment_id={comment.id}, chat_id={comment_chat_id}"
                )
                total_task_before_enqueue = node.total_task
                total_download_task_before_enqueue = node.total_download_task
                result = await add_download_task(comment, node)
                logger.info(f"添加下载任务结果: {result}")
                if result is False:
                    node.failed_download_task += 1
                    if node.total_task == total_task_before_enqueue:
                        node.total_task += 1
                    if node.total_download_task == total_download_task_before_enqueue:
                        node.total_download_task += 1
                    await report_bot_status(node.bot, node)
            except Exception as e:
                logger.error(f"处理评论 {comment.id} 失败: {e}")
                import traceback

                traceback.print_exc()
                node.failed_download_task += 1
                if node.total_task == total_task_before_enqueue:
                    node.total_task += 1
                if node.total_download_task == total_download_task_before_enqueue:
                    node.total_download_task += 1
                await report_bot_status(node.bot, node)

        logger.info(f"评论下载任务已添加 {len(comments)} 条评论到下载队列，等待下载完成")

        while True:
            completed_tasks = (
                node.success_download_task
                + node.failed_download_task
                + node.skip_download_task
            )
            logger.info(f"下载进度: 已完成 {completed_tasks}/{expected_comment_tasks} 个任务")

            if completed_tasks >= expected_comment_tasks:
                logger.info("所有下载任务已完成")
                break

            if not node.is_running or node.is_stop_transmission:
                logger.info("任务已停止，结束评论下载等待")
                break

            await report_bot_status(node.bot, node)
            await asyncio.sleep(5)

        await report_bot_status(node.bot, node)
        logger.info(
            f"评论下载任务已全部完成 - 成功: {node.success_download_task}, 失败: {node.failed_download_task}, 跳过: {node.skip_download_task}"
        )
    finally:
        remove_active_task_node(node.task_id)


def _package_download_complete(node, message_ids) -> bool:
    """True when every message_id has reached a terminal download status."""
    status = getattr(node, "download_status", None) or {}
    for message_id in message_ids:
        state = status.get(message_id)
        if state is None or state == DownloadStatus.Downloading:
            return False
    return True


async def download_prepared_messages(
    messages,
    download_filter,
    node,
    failed_message_ids=None,
    manage_parent_lifecycle: bool = True,
):
    """Download already-scanned ordinary package media and preserve scan failures."""
    from module.comment_workflow import PackageMediaItem, filter_media_comments
    from module.download_stat import remove_active_task_node
    from module.pyrogram_extension import report_bot_status, set_meta_data
    from utils.format import validate_title
    from utils.meta_data import MetaData

    failed_message_ids = list(dict.fromkeys(failed_message_ids or []))

    try:
        media_messages = filter_media_comments(messages)

        if getattr(node, "package_naming_context", None):
            package_media_items = getattr(node, "package_media_items", None)
            if not isinstance(package_media_items, dict):
                package_media_items = {}
                node.package_media_items = package_media_items
            media_message_ids = {message.id for message in media_messages}
            package_plan = getattr(node, "package_plan", None)
            planned_items = getattr(package_plan, "items", None)
            if planned_items:
                for item in planned_items:
                    item_message_id = getattr(
                        getattr(item, "message", None),
                        "id",
                        None,
                    )
                    if item_message_id not in media_message_ids:
                        continue
                    package_media_items.setdefault(item_message_id, item)
            for message in media_messages:
                if message.id in package_media_items:
                    continue
                raw_caption = getattr(message, "caption", None)
                package_media_items[message.id] = PackageMediaItem(
                    message=message,
                    media_type=getattr(message, "media", None),
                    caption_for_naming=(
                        raw_caption or node.package_naming_context.package_title
                    ),
                    original_caption=raw_caption,
                    inherited_caption=not bool(raw_caption),
                )

        if download_filter:

            class TempChatDownloadConfig:
                def __init__(self):
                    self.download_filter = download_filter

            temp_config = TempChatDownloadConfig()
            filtered_messages = []
            for message in media_messages:
                meta_data = MetaData()
                caption = getattr(message, "caption", None)
                if caption:
                    caption = validate_title(caption)
                set_meta_data(meta_data, message, caption)

                if app.exec_filter(temp_config, meta_data):
                    filtered_messages.append(message)

            media_messages = filtered_messages

        package_message_ids = {message.id for message in media_messages} | set(
            failed_message_ids
        )

        completed_tasks_baseline = (
            node.success_download_task
            + node.failed_download_task
            + node.skip_download_task
        )
        expected_message_tasks = (
            completed_tasks_baseline + len(media_messages) + len(failed_message_ids)
        )
        logger.info(f"设置预期消息任务数: {expected_message_tasks}")

        if failed_message_ids:
            if not hasattr(node, "download_status") or node.download_status is None:
                node.download_status = {}
            for failed_message_id in failed_message_ids:
                node.download_status[failed_message_id] = DownloadStatus.FailedDownload
                node.stat(
                    DownloadStatus.FailedDownload,
                    node.chat_id,
                    failed_message_id,
                    None,
                )
                node.total_download_task += 1
                node.total_task += 1
            await report_bot_status(node.bot, node)

        logger.info(f"开始下载消息媒体，共 {len(media_messages)} 条消息")
        for index, message in enumerate(media_messages):
            if not node.is_running:
                logger.info("任务已停止，中断下载")
                break

            logger.info(
                f"处理消息 {index + 1}/{len(media_messages)}: "
                f"id={message.id}, has_media={message.media is not None}, "
                f"type={type(message)}"
            )

            total_task_before_enqueue = node.total_task
            total_download_task_before_enqueue = node.total_download_task
            try:
                result = await add_download_task(message, node)
                logger.info(f"添加消息下载任务结果: {result}")
                if result is False:
                    if (
                        not hasattr(node, "download_status")
                        or node.download_status is None
                    ):
                        node.download_status = {}
                    node.download_status[message.id] = DownloadStatus.FailedDownload
                    node.stat(
                        DownloadStatus.FailedDownload,
                        node.chat_id,
                        message.id,
                        None,
                    )
                    if node.total_task == total_task_before_enqueue:
                        node.total_task += 1
                    if node.total_download_task == total_download_task_before_enqueue:
                        node.total_download_task += 1
                    await report_bot_status(node.bot, node)
            except Exception as e:
                logger.error(f"处理消息 {message.id} 失败: {e}")
                import traceback

                traceback.print_exc()
                if not hasattr(node, "download_status") or node.download_status is None:
                    node.download_status = {}
                node.download_status[message.id] = DownloadStatus.FailedDownload
                node.stat(
                    DownloadStatus.FailedDownload,
                    node.chat_id,
                    message.id,
                    None,
                )
                if node.total_task == total_task_before_enqueue:
                    node.total_task += 1
                if node.total_download_task == total_download_task_before_enqueue:
                    node.total_download_task += 1
                await report_bot_status(node.bot, node)

        logger.info(f"消息下载任务已添加 {len(media_messages)} 条消息到下载队列，等待下载完成")

        while True:
            completed_tasks = (
                node.success_download_task
                + node.failed_download_task
                + node.skip_download_task
            )
            logger.info(f"下载进度: 已完成 {completed_tasks}/{expected_message_tasks} 个任务")

            if _package_download_complete(node, package_message_ids):
                logger.info("所有下载任务已完成")
                break

            if not node.is_running or node.is_stop_transmission:
                logger.info("任务已停止，结束消息下载等待")
                break

            await report_bot_status(node.bot, node)
            await asyncio.sleep(5)

        await report_bot_status(node.bot, node)
        logger.info(
            "消息下载任务已全部完成 - "
            f"成功: {node.success_download_task}, "
            f"失败: {node.failed_download_task}, "
            f"跳过: {node.skip_download_task}"
        )
    finally:
        if manage_parent_lifecycle and not getattr(
            node, "prescan_batch_in_progress", False
        ):
            remove_active_task_node(node.task_id)


async def _maybe_await(value: Any) -> Any:
    return await _package_maybe_await(value)


async def _run_package_callback(callback: Callable[..., Any], *args: Any) -> None:
    await _execute_package_callback(callback, *args, logger=logger)


def _package_download_result(
    package: Any, parent_node: TaskNode
) -> PackageDownloadResult:
    return _build_package_result(package, parent_node)


async def download_prescan_packages(
    packages: Sequence[Any],
    channel: str,
    parent_node: TaskNode,
    selected_package_ids: AbstractSet[int],
    on_package_started: Optional[PackageStartedCallback] = None,
    on_package_finished: Optional[PackageFinishedCallback] = None,
    manage_parent_lifecycle: bool = True,
    prepare_package: Optional[PreparePackageCallback] = None,
) -> list[PackageDownloadResult]:
    """Compatibility wrapper for serial resource-package execution."""

    return await run_packages(
        packages,
        channel,
        parent_node,
        selected_package_ids,
        download_prepared_messages,
        logger,
        on_package_started=on_package_started,
        on_package_finished=on_package_finished,
        manage_parent_lifecycle=manage_parent_lifecycle,
        prepare_package=prepare_package,
    )


async def download_comments(
    client: PyrogramClient,
    chat_id: int,
    base_message_id: int,
    start_comment_id: int,
    end_comment_id: int,
    download_filter: str,
    node: TaskNode,
):
    """Download comments for a specific message"""
    from module.pyrogram_extension import report_bot_status

    try:
        logger.info(
            f"download_comments: 开始下载评论 - chat_id={chat_id}, base_message_id={base_message_id}, start_comment_id={start_comment_id}, end_comment_id={end_comment_id}"
        )
        logger.info(
            f"download_comments: 任务节点信息 - task_id={node.task_id}, is_running={node.is_running}, is_stop_transmission={node.is_stop_transmission}"
        )

        try:
            async with get_telegram_activity_gate().download_permit():
                scan_result = await scan_comment_range(
                    client,
                    chat_id,
                    base_message_id,
                    start_comment_id,
                    end_comment_id,
                )
            comments = scan_result.comments
            failed_comment_ids = scan_result.failed_comment_ids
        except ValueError:
            return
        except Exception:
            return

        logger.info(f"共找到 {len(comments)} 条符合条件的评论")
        await download_prepared_comments(
            comments,
            download_filter,
            node,
            failed_comment_ids=failed_comment_ids,
        )

    except Exception as e:
        logger.error(f"Error downloading comments: {e}")
        import traceback

        traceback.print_exc()
        # 发生异常时，我们需要确保任务状态正确
        await report_bot_status(node.bot, node)
        # 清理任务节点
        from module.download_stat import remove_active_task_node

        remove_active_task_node(node.task_id)


async def download_chat_task(
    client: PyrogramClient,
    chat_download_config: ChatDownloadConfig,
    node: TaskNode,
):
    """Download all task"""
    messages_iter = get_chat_history_v2(
        client,
        node.chat_id,
        limit=node.limit,
        max_id=node.end_offset_id,
        offset_id=chat_download_config.last_read_message_id,
        reverse=True,
    )

    chat_download_config.node = node

    if chat_download_config.ids_to_retry:
        logger.info(f"{_t('Downloading files failed during last run')}...")
        skipped_messages: list = await client.get_messages(  # type: ignore
            chat_id=node.chat_id, message_ids=chat_download_config.ids_to_retry
        )

        for message in skipped_messages:
            await add_download_task(message, node)

    async for message in messages_iter:  # type: ignore
        meta_data = MetaData()

        caption = message.caption
        media_group_id = (
            str(message.media_group_id) if message.media_group_id is not None else None
        )
        if caption:
            caption = validate_title(caption)
            app.set_caption_name(node.chat_id, media_group_id, caption)
            app.set_caption_entities(
                node.chat_id, media_group_id, message.caption_entities
            )
        else:
            caption = app.get_caption_name(node.chat_id, media_group_id)
        set_meta_data(meta_data, message, caption)

        if app.need_skip_message(chat_download_config, message.id):
            continue

        if app.exec_filter(chat_download_config, meta_data):
            await add_download_task(message, node)
        else:
            node.download_status[message.id] = DownloadStatus.SkipDownload
            if message.media_group_id:
                await upload_telegram_chat(
                    client,
                    node.upload_user,
                    app,
                    node,
                    message,
                    DownloadStatus.SkipDownload,
                )

    chat_download_config.need_check = True
    chat_download_config.total_task = node.total_task
    node.is_running = True


async def download_all_chat(client: PyrogramClient):
    """Download All chat"""
    for key, value in app.chat_download_config.items():
        value.node = TaskNode(chat_id=key)
        try:
            await download_chat_task(client, value, value.node)
        except Exception as e:
            logger.warning(f"Download {key} error: {e}")
        finally:
            value.need_check = True


async def run_until_all_task_finish():
    """Normal download"""
    while True:
        finish: bool = True
        for _, value in app.chat_download_config.items():
            if not value.need_check or value.total_task != value.finish_task:
                finish = False

        if (not app.bot_token and finish) or app.restart_program:
            break

        await asyncio.sleep(1)


def _exec_loop():
    """Exec loop"""

    app.loop.run_until_complete(run_until_all_task_finish())


async def start_server(client: PyrogramClient):
    """
    Start the server using the provided client.
    """
    await client.start()


async def stop_server(client: PyrogramClient):
    """
    Stop the server using the provided client.
    """
    await client.stop()


def _start_channel_library_service(
    application: Application, client: PyrogramClient
) -> Optional[ChannelLibraryService]:
    """Start the persistent channel service on the application's owner loop."""

    application.channel_library_service = None
    try:
        service = ChannelLibraryService(
            application,
            client,
            ChannelLibraryStore(Path.cwd() / "channel_library.sqlite3"),
            application.channel_library_config,
            task_store=get_task_store(),
        )
        application.loop.run_until_complete(service.start())
    except Exception:
        logger.exception("Channel library service initialization failed")
        application.channel_library_service = None
        return None
    application.channel_library_service = service
    return service


def _stop_channel_library_service(application: Application) -> None:
    """Stop all channel-owned tasks before Telegram and the main task set."""

    service = getattr(application, "channel_library_service", None)
    if service is None:
        return
    application.channel_library_service = None
    try:
        application.loop.run_until_complete(service.stop())
    except Exception:
        logger.exception("Channel library service shutdown failed")


def _sanitize_monitor_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """返回可安全写日志的 monitor 配置副本，webhook_url 只保留 scheme+host。"""
    safe = dict(cfg)
    url = safe.get("webhook_url")
    if url:
        parts = urlsplit(str(url))
        if parts.scheme and parts.netloc:
            safe["webhook_url"] = f"{parts.scheme}://{parts.netloc}/***"
        else:
            safe["webhook_url"] = "***"
    return safe


def main():
    """Build the Pyrogram adapter and hand ownership to the runtime module."""

    client = HookClient(
        "media_downloader",
        api_id=app.api_id,
        api_hash=app.api_hash,
        proxy=app.proxy,
        workdir=app.session_file_path,
        start_timeout=app.start_timeout,
    )
    runtime = DownloadRuntime(
        logger=logger,
        translate=_t,
        init_web=init_web,
        set_max_concurrent_transmissions=set_max_concurrent_transmissions,
        start_server=start_server,
        stop_server=stop_server,
        start_channel_library_service=_start_channel_library_service,
        stop_channel_library_service=_stop_channel_library_service,
        download_all_chat=download_all_chat,
        periodic_progress_refresh=periodic_progress_refresh,
        worker=worker,
        start_download_bot=start_download_bot,
        stop_download_bot=stop_download_bot,
        add_download_task=add_download_task,
        download_chat_task=download_chat_task,
        exec_loop=_exec_loop,
        print_performance_stats=print_performance_stats,
    )
    run_application(app, client, runtime)

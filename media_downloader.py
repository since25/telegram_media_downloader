"""Downloads media from telegram."""
import asyncio
import logging
import yaml
import os
import aiohttp
import shutil
import time
from typing import List, Optional, Tuple, Union
import sys
if __name__ == "__main__":
    sys.modules["media_downloader"] = sys.modules[__name__]
import pyrogram
from loguru import logger
from pyrogram.types import Audio, Document, Photo, Video, VideoNote, Voice
from rich.logging import RichHandler

from module.app import Application, ChatDownloadConfig, DownloadStatus, TaskNode
from module.bot import start_download_bot, stop_download_bot
from module.download_stat import get_download_result, update_download_status, get_active_task_nodes
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
# 导入Pyrogram错误类
# 使用更通用的导入方式，避免特定异常模块导入错误
import pyrogram.errors
from module.web import init_web
from utils.format import truncate_filename, validate_title
from utils.log import LogFilter
from utils.meta import print_meta
from utils.meta_data import MetaData
# ---- stall watchdog state ----
DOWNLOAD_LAST_PROGRESS_TS: dict[int, float] = {}
DOWNLOAD_LAST_PROGRESS_BYTES: dict[int, int] = {}

# ---- performance monitoring ----
PERFORMANCE_STATS = {
    "total_download_time": 0,  # 总下载时间
    "total_queue_time": 0,     # 总队列等待时间
    "total_network_time": 0,   # 总网络请求时间
    "total_io_time": 0,        # 总磁盘IO时间
    "download_task_count": 0,  # 总下载任务数
    "successful_downloads": 0, # 成功下载数
    "failed_downloads": 0,     # 失败下载数
    "skipped_downloads": 0,    # 跳过下载数
    "avg_download_speed": 0,   # 平均下载速度
    "avg_queue_time": 0,       # 平均队列等待时间
    "avg_download_time": 0     # 平均下载时间
}

# 用于跟踪单个任务的开始时间
TASK_START_TIMES: dict[tuple[int, int], float] = {}  # (chat_id, message_id) -> start_time

# 用于跟踪队列等待时间
QUEUE_ENTRY_TIMES: dict[tuple[int, int], float] = {}  # (chat_id, message_id) -> queue_entry_time

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
    download_size = os.path.getsize(download_path)
    if media_size == download_size:
        logger.success(f"{_t('Successfully downloaded')} - {ui_file_name}")
        return

    logger.warning(
        f"{_t('Media downloaded with wrong size')}: "
        f"{download_size}, {_t('actual')}: "
        f"{media_size}, {_t('file name')}: {ui_file_name}"
    )
    try:
        os.remove(download_path)
    except Exception:
        pass
    # 用 ValueError 更稳：不会依赖 pyrogram 的异常构造参数
    raise ValueError(f"size mismatch: {download_size} != {media_size}")


def _move_to_download_path(temp_download_path: str, download_path: str):
    """Move file to download path

    Parameters
    ----------
    temp_download_path: str
        Temporary download path

    download_path: str
        Download path

    """

    directory, _ = os.path.split(download_path)
    os.makedirs(directory, exist_ok=True)
    shutil.move(temp_download_path, download_path)


def _check_timeout(retry: int, _: int):
    """Check if message download timeout, then add message id into failed_ids

    Parameters
    ----------
    retry: int
        Retry download message times

    message_id: int
        Try to download message 's id

    """
    if retry == 2:
        return True
    return False


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
    if _type in ["audio", "document", "video"]:
        allowed_formats: list = file_formats[_type]
        if not file_format in allowed_formats and allowed_formats[0] != "all":
            return False
    return True


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
    return not os.path.isdir(file_path) and os.path.exists(file_path)


# pylint: disable = R0912


async def _get_media_meta(
    chat_id: Union[int, str],
    message: pyrogram.types.Message,
    media_obj: Union[Audio, Document, Photo, Video, VideoNote, Voice],
    _type: str,
    node: Optional["TaskNode"] = None,
) -> Tuple[str, str, Optional[str]]:
    """Extract file name and file id from media object.

    Parameters
    ----------
    media_obj: Union[Audio, Document, Photo, Video, VideoNote, Voice]
        Media object to be extracted.
    _type: str
        Type of media object.

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
        if node and hasattr(node, 'file_name_tag') and node.file_name_tag:
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

        if caption:
            caption = validate_title(caption)
            app.set_caption_name(chat_id, message.media_group_id, caption)
            app.set_caption_entities(
                chat_id, message.media_group_id, message.caption_entities
            )
        else:
            caption = app.get_caption_name(chat_id, message.media_group_id)

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

        # 如果有标签，添加到文件名前面
        if node and hasattr(node, 'file_name_tag') and node.file_name_tag:
            tag = validate_title(node.file_name_tag)
            # 限制标签长度
            max_tag_len = 30
            if len(tag) > max_tag_len:
                tag = tag[:max_tag_len]
            # 在文件名前面添加标签
            prefix = f"{message.id} - "
            if gen_file_name.startswith(prefix):
                gen_file_name = prefix + tag + " - " + gen_file_name[len(prefix):]
            else:
                gen_file_name = f"{message.id} - {tag} - {gen_file_name}"

        if caption:
            safe_caption = validate_title(caption)
            max_cap_len = 60
            if len(safe_caption) > max_cap_len:
                safe_caption = safe_caption[:max_cap_len]

            prefix = f"{message.id} - "
            if gen_file_name.startswith(prefix):
                gen_file_name = prefix + safe_caption + " - " + gen_file_name[len(prefix):]
            else:
                gen_file_name = f"{message.id} - {safe_caption} - {gen_file_name}"

        file_save_path = app.get_file_save_path(_type, dirname, datetime_dir_name)

        temp_file_name = os.path.join(app.temp_save_path, dirname, gen_file_name)

        file_name = os.path.join(file_save_path, gen_file_name)
    return truncate_filename(file_name), truncate_filename(temp_file_name), file_format


async def add_download_task(
    message: pyrogram.types.Message,
    node: TaskNode,
):
    """Add Download task"""
    try:
        msg_id = getattr(message, "id", None)

        logger.info(
            f"add_download_task: start "
            f"message_id={msg_id if msg_id is not None else 'N/A'} "
            f"queue_id={id(queue)} queue_size_before={queue.qsize()}"
        )

        # ---- 基础校验：只做“不会误杀”的检查 ----
        if message is None:
            logger.error("add_download_task: message is None")
            return False

        if msg_id is None:
            logger.error(f"add_download_task: message has no id - type={type(message)}")
            return False

        # Pyrogram 的 empty / service 等情况不统一，别用 message.empty 做硬判断
        # 只要它是 Message 并且后续 download_task 能识别 has_media，就让它进队列
        if node is None:
            logger.error("add_download_task: node is None")
            return False

        # ---- 初始化 node 统计字段 ----
        if not hasattr(node, "download_status") or node.download_status is None:
            node.download_status = {}

        if not hasattr(node, "total_task") or node.total_task is None:
            node.total_task = 0

        if not hasattr(node, "total_download_task") or node.total_download_task is None:
            node.total_download_task = 0

        # 标记下载中
        node.download_status[msg_id] = DownloadStatus.Downloading

        # ---- 入队：这是核心，必须尽快完成 ----
        # 记录任务进入队列的时间
        queue_entry_time = time.time()
        QUEUE_ENTRY_TIMES[(node.chat_id, msg_id)] = queue_entry_time
        
        await queue.put((message, node))

        node.total_task += 1
        node.total_download_task += 1

        logger.info(
            f"add_download_task: enqueued "
            f"message_id={msg_id} queue_id={id(queue)} queue_size_after={queue.qsize()} "
            f"node_task_id={getattr(node, 'task_id', 'N/A')}"
        )

        # ---- 状态上报：不要影响主流程，建议加超时 + 容错 ----
        # 这里你原来用 node.bot，很可能不是 pyrogram.Client。
        # 更稳的是：优先用 node.bot_client / node.client 之类（如果你工程里有），
        # 没有就跳过，不要阻塞入队成功。
        bot_client = None

        # 如果你 TaskNode 里确实有 bot_client / client，这里可按实际字段调整
        if hasattr(node, "bot_client"):
            bot_client = getattr(node, "bot_client", None)
        elif hasattr(node, "bot") and isinstance(getattr(node, "bot", None), pyrogram.Client):
            bot_client = node.bot

        if bot_client:
            try:
                from module.pyrogram_extension import report_bot_status

                # 给个超时，防止 Telegram API 卡住把 add_task 卡住
                await asyncio.wait_for(
                    report_bot_status(client=bot_client, node=node, immediate_reply=True),
                    timeout=5,
                )
            except asyncio.TimeoutError:
                logger.warning(f"add_download_task: report_bot_status timeout - message_id={msg_id}")
            except Exception as e:
                logger.warning(f"add_download_task: report_bot_status failed - {e}")

        return True

    except Exception as e:
        logger.exception(f"add_download_task: failed - {e}")
        return False


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


async def download_task(
    client: pyrogram.Client, message: pyrogram.types.Message, node: TaskNode
):
    """Download and Forward media"""
    # 初始化变量，确保在任何情况下都有定义
    download_status = None
    file_name = None
    file_size = 0
    message_id = None
    
    try:
        # 确保消息对象存在
        if not message:
            logger.info("download_task: message is None，跳过下载")
            # 更新skip_not_found计数
            node.skip_not_found_download_task += 1
            node.download_status[0] = DownloadStatus.SkipDownload  # 使用0作为占位ID
            return
            
        # 确保消息ID可用
        if not hasattr(message, 'id'):
            logger.info("download_task: message has no id attribute，跳过下载")
            # 更新skip_not_found计数
            node.skip_not_found_download_task += 1
            node.download_status[0] = DownloadStatus.SkipDownload  # 使用0作为占位ID
            return
            
        message_id = message.id
        
        # 记录任务开始时间
        task_start_time = time.time()
        TASK_START_TIMES[(node.chat_id, message_id)] = task_start_time
        
        # 计算队列等待时间
        queue_wait_time = 0
        if (node.chat_id, message_id) in QUEUE_ENTRY_TIMES:
            queue_entry_time = QUEUE_ENTRY_TIMES[(node.chat_id, message_id)]
            queue_wait_time = task_start_time - queue_entry_time
            PERFORMANCE_STATS["total_queue_time"] += queue_wait_time
            del QUEUE_ENTRY_TIMES[(node.chat_id, message_id)]  # 清理已处理的条目
        
        logger.info(f"download_task: Processing message id={message_id}, type={type(message)}, has_media={message.media is not None}, queue_wait_time={queue_wait_time:.2f}s")
        
        # 下载媒体
        download_status, file_name = await download_media(
            client, message, app.media_types, app.file_formats, node
        )

        if app.enable_download_txt and message.text and not message.media:
            download_status, file_name = await save_msg_to_file(app, node.chat_id, message)

        if not node.bot:
            app.set_download_id(node, message_id, download_status)

        node.download_status[message_id] = download_status

        # 更新任务完成状态
        # 使用stat方法更新状态，这样会同时填充success_tasks列表
        node.stat(download_status, node.chat_id, message_id, file_name)
        
        logger.info(f"download_task: 任务状态更新 - success={node.success_download_task}, failed={node.failed_download_task}, skip={node.skip_download_task}, skip_not_found={node.skip_not_found_download_task}")

        # 只在需要时获取文件大小
        if file_name and os.path.exists(file_name):
            file_size = os.path.getsize(file_name)
        
        logger.info(f"download_task: Download completed for message {message_id}, status={download_status}, file_name={file_name}, size={file_size}")

        await upload_telegram_chat(
            client,
            node.upload_user if node.upload_user else client,
            app,
            node,
            message,
            download_status,
            file_name,
        )
        
        # rclone upload (云盘上传)
        # 条件：1. 没有设置telegram转发目标 2. 下载成功 3. 有文件路径
        if (
            not node.upload_telegram_chat_id
            and download_status is DownloadStatus.SuccessDownload
            and file_name
        ):
            logger.info(f"download_task: 准备上传文件到云盘 - file_name={file_name}, enable_upload_file={app.cloud_drive_config.enable_upload_file}")
            
            if app.cloud_drive_config.enable_upload_file:
                ui_file_name = file_name
                if app.hide_file_name:
                    ui_file_name = f"****{os.path.splitext(file_name)[-1]}"
                
                try:
                    upload_result = await app.upload_file(
                        file_name, update_cloud_upload_stat, (node, message_id, ui_file_name)
                    )
                    if upload_result:
                        node.upload_success_count += 1
                        logger.info(f"download_task: 文件上传成功 - file_name={file_name}, upload_success_count={node.upload_success_count}")
                    else:
                        logger.warning(f"download_task: 文件上传失败 - file_name={file_name}")
                except Exception as e:
                    logger.error(f"download_task: 文件上传异常 - file_name={file_name}, error={e}", exc_info=True)
            else:
                logger.debug(f"download_task: 云盘上传未启用，跳过上传 - file_name={file_name}")
        
        await report_bot_download_status(
            node.bot,
            node,
            download_status,
            file_size,
            chat_id=node.chat_id,
            message_id=message_id,
            file_name=file_name,
        )
        
    except Exception as e:
        logger.error(f"Error in download_task: {e}")
        import traceback
        traceback.print_exc()
        # 更新失败任务计数
        node.failed_download_task += 1
        logger.info(f"download_task: 异常导致任务失败 - 失败计数={node.failed_download_task}")
        
        # 在异常情况下也尝试报告状态
        if message_id and node.bot:
            try:
                await report_bot_download_status(
                    node.bot,
                    node,
                    DownloadStatus.FailedDownload,
                    0,
                    chat_id=node.chat_id,
                    message_id=message_id,
                    file_name=file_name,
                )
            except Exception as report_err:
                logger.error(f"Error reporting download status: {report_err}")
    finally:
        # 记录任务完成时间并更新性能统计
        if message_id and (node.chat_id, message_id) in TASK_START_TIMES:
            task_start_time = TASK_START_TIMES[(node.chat_id, message_id)]
            task_duration = time.time() - task_start_time
            PERFORMANCE_STATS["total_download_time"] += task_duration
            PERFORMANCE_STATS["download_task_count"] += 1
            
            # 更新任务类型统计
            if download_status == DownloadStatus.SuccessDownload:
                PERFORMANCE_STATS["successful_downloads"] += 1
            elif download_status == DownloadStatus.FailedDownload:
                PERFORMANCE_STATS["failed_downloads"] += 1
            elif download_status == DownloadStatus.SkipDownload:
                PERFORMANCE_STATS["skipped_downloads"] += 1
                # skip_not_found已经包含在skipped_downloads中，这里不需要重复计数
            
            # 更新平均统计
            if PERFORMANCE_STATS["download_task_count"] > 0:
                PERFORMANCE_STATS["avg_download_time"] = PERFORMANCE_STATS["total_download_time"] / PERFORMANCE_STATS["download_task_count"]
                
            if PERFORMANCE_STATS["successful_downloads"] > 0:
                PERFORMANCE_STATS["avg_queue_time"] = PERFORMANCE_STATS["total_queue_time"] / PERFORMANCE_STATS["download_task_count"]
            
            # 清理已处理的条目
            del TASK_START_TIMES[(node.chat_id, message_id)]
            
            logger.debug(f"Task performance: message_id={message_id}, duration={task_duration:.2f}s, status={download_status}")
        
        # 清理下载结果中的进度信息，释放内存
        if message_id:
            download_result = get_download_result()
            if node.chat_id in download_result and message_id in download_result[node.chat_id]:
                del download_result[node.chat_id][message_id]
        
        # 释放资源引用
        del download_status
        del file_name
        del file_size
        del message_id
        del message
        del client
        del node


# pylint: disable = R0915,R0914

async def _stall_watchdog(message_id: int, timeout_s: int, target_task: asyncio.Task, ui_file_name: str):
    """
    If no progress for timeout_s seconds, cancel target_task.
    """
    # 初始化：认为刚开始时有“心跳”
    DOWNLOAD_LAST_PROGRESS_TS[message_id] = time.time()
    DOWNLOAD_LAST_PROGRESS_BYTES.setdefault(message_id, -1)

    while not target_task.done():
        await asyncio.sleep(5)  # 检查频率：5秒一次即可
        last_ts = DOWNLOAD_LAST_PROGRESS_TS.get(message_id)
        if last_ts is None:
            # 没有记录就保守一点，不杀
            continue
        if time.time() - last_ts > timeout_s:
            logger.warning(
                f"Message[{message_id}] {ui_file_name}: stalled for > {timeout_s}s, cancelling download..."
            )
            target_task.cancel()
            return
@record_download_status

async def download_media(
    client: pyrogram.client.Client,
    message: pyrogram.types.Message,
    media_types: List[str],
    file_formats: dict,
    node: TaskNode,
):
    """
    Download media from Telegram.

    Each of the files to download are retried 3 times with a
    delay of 5 seconds each.

    Parameters
    ----------
    client: pyrogram.client.Client
        Client to interact with Telegram APIs.
    message: pyrogram.types.Message
        Message object retrieved from telegram.
    media_types: list
        List of strings of media types to be downloaded.
        Ex : `["audio", "photo"]`
        Supported formats:
            * audio
            * document
            * photo
            * video
            * voice
    file_formats: dict
        Dictionary containing the list of file_formats
        to be downloaded for `audio`, `document` & `video`
        media types.

    Returns
    -------
    int
        Current message id.
    """

    # pylint: disable = R0912

    file_name: str = ""
    ui_file_name: str = ""
    task_start_time: float = time.time()
    media_size = 0
    _media = None
    
    # 尝试获取message，如果失败则归为skip_not_found
    try:
        message = await fetch_message(client, message)
        # 检查message是否为空或无效
        if not message or (hasattr(message, 'empty') and message.empty):
            message_id = getattr(message, 'id', 'N/A') if message else 'N/A'
            logger.info(f"Message[{message_id}]: message不存在或为空，跳过下载")
            node.skip_not_found_download_task += 1
            return DownloadStatus.SkipDownload, None
    except pyrogram.errors.BadRequest as e:
        # message不存在/不可见/不属于thread等情况
        message_id = getattr(message, 'id', 'N/A')
        logger.info(f"Message[{message_id}]: 无法获取message (BadRequest: {e})，跳过下载")
        node.skip_not_found_download_task += 1
        return DownloadStatus.SkipDownload, None
    except pyrogram.errors.NotFound as e:
        # message不存在
        message_id = getattr(message, 'id', 'N/A')
        logger.info(f"Message[{message_id}]: message不存在 (NotFound: {e})，跳过下载")
        node.skip_not_found_download_task += 1
        return DownloadStatus.SkipDownload, None
    except Exception as e:
        # 其他获取message的错误，也归为skip_not_found
        message_id = getattr(message, 'id', 'N/A')
        logger.warning(f"Message[{message_id}]: 获取message失败 ({type(e).__name__}: {e})，跳过下载")
        node.skip_not_found_download_task += 1
        return DownloadStatus.SkipDownload, None
    
    try:
        for _type in media_types:
            _media = getattr(message, _type, None)
            if _media is None:
                continue
            file_name, temp_file_name, file_format = await _get_media_meta(
                node.chat_id, message, _media, _type, node
            )
            media_size = getattr(_media, "file_size", 0)

            ui_file_name = file_name
            if app.hide_file_name:
                ui_file_name = f"****{os.path.splitext(file_name)[-1]}"

            if _can_download(_type, file_formats, file_format):
                if _is_exist(file_name):
                    file_size = os.path.getsize(file_name)
                    if file_size == media_size:
                        logger.info(
                            f"id={message.id} {ui_file_name} "
                            f"{_t('already download,download skipped')}.\n"
                        )
                        return DownloadStatus.SkipDownload, None
                    else:
                        logger.warning(
                            f"id={message.id} {ui_file_name} local size {file_size} != {media_size}, remove and redownload."
                        )
                        os.remove(file_name)
            else:
                return DownloadStatus.SkipDownload, None

            break
    except Exception as e:
        logger.error(
            f"Message[{message.id}]: "
            f"{_t('could not be downloaded due to following exception')}:\n[{e}].",
            exc_info=True,
        )
        return DownloadStatus.FailedDownload, None
    if _media is None:
        return DownloadStatus.SkipDownload, None

    message_id = message.id

    logger.info(f"Message[{message_id}] {ui_file_name}")
    
    # 增强的重试策略配置
    MAX_RETRIES = 5  # 增加最大重试次数到5次
    INITIAL_RETRY_DELAY = 1  # 初始重试延迟
    MAX_RETRY_DELAY = 30  # 最大重试延迟
    
    for retry in range(MAX_RETRIES):
        download_task = None
        watchdog_task = None
        try:
            # 重试开始时的明确日志
            logger.info(f"Message[{message_id}] ({ui_file_name}): Starting retry {retry + 1}/{MAX_RETRIES}...")
            
            # 每次 retry 前重置心跳：避免上一次残留时间戳误杀
            DOWNLOAD_LAST_PROGRESS_TS[message_id] = time.time()
            DOWNLOAD_LAST_PROGRESS_BYTES.pop(message_id, None)
            
            # 清理下载结果中的进度信息，确保WebUI显示正确的进度
            download_result = get_download_result()
            if node.chat_id in download_result and message_id in download_result[node.chat_id]:
                del download_result[node.chat_id][message_id]
            
            # ✅ 关键：retry 前清理临时文件和可能的不完整最终文件
            try:
                # 清理临时文件
                if temp_file_name and os.path.exists(temp_file_name):
                    logger.warning(f"Message[{message_id}] removing temp file: {temp_file_name}")
                    os.remove(temp_file_name)
                else:
                    logger.info(f"Message[{message_id}] no temp file to remove: {temp_file_name}")
                
                # 清理可能存在的不完整最终文件
                if file_name and os.path.exists(file_name):
                    file_size = os.path.getsize(file_name)
                    if file_size != media_size:
                        logger.warning(f"Message[{message_id}] removing incomplete file: {file_name} (size {file_size} != {media_size})"
                        )
                        os.remove(file_name)
                    else:
                        logger.info(f"Message[{message_id}] file exists and size is correct, no need to remove: {file_name}")
                        return DownloadStatus.SkipDownload, None  # 文件已存在且完整，跳过下载
                else:
                    logger.info(f"Message[{message_id}] final file not found, no need to remove: {file_name}")
            except Exception as e:
                logger.warning(f"Message[{message_id}] error removing files: {e}")
            
            # 指数退避重试延迟
            retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry), MAX_RETRY_DELAY)
            if retry > 0:
                logger.info(f"Message[{message_id}] Waiting {retry_delay}s before retry...")
                await asyncio.sleep(retry_delay)
            
            download_task = app.loop.create_task(
                client.download_media(
                    message,
                    file_name=temp_file_name,
                    progress=update_download_status,
                    progress_args=(
                        message_id,
                        ui_file_name,
                        task_start_time,
                        node,
                        client,
                    ),
                )
            )

            watchdog_task = app.loop.create_task(
                _stall_watchdog(message_id, STALL_TIMEOUT, download_task, ui_file_name)
            )

            temp_download_path = await download_task

            if temp_download_path and isinstance(temp_download_path, str):
                _check_download_finish(media_size, temp_download_path, ui_file_name)
                await asyncio.sleep(0.5)
                _move_to_download_path(temp_download_path, file_name)

                # ✅ 成功后清理心跳记录，防止字典膨胀
                DOWNLOAD_LAST_PROGRESS_TS.pop(message_id, None)
                DOWNLOAD_LAST_PROGRESS_BYTES.pop(message_id, None)

                return DownloadStatus.SuccessDownload, file_name

            # download_media 正常不该返回 None/非 str，这里当失败走重试
            raise ValueError("download_media returned empty path")

        except asyncio.CancelledError:
            # ✅ watchdog cancel 会走这里
            logger.warning(
                f"Message[{message_id}]: stalled >{STALL_TIMEOUT}s (no progress), cancelled and retrying... ({retry + 1}/{MAX_RETRIES})"
            )
            # 对于stall错误，缩短重试延迟
            await asyncio.sleep(1)

        except pyrogram.errors.BadRequest as bad_err:
            # file reference expired / 或者别的 400
            logger.warning(
                f"Message[{message_id}]: BadRequest ({bad_err.error_code}): {bad_err.MESSAGE} - refetching... ({retry + 1}/{MAX_RETRIES})"
            )
            await asyncio.sleep(RETRY_TIME_OUT)
            message = await fetch_message(client, message)

        except pyrogram.errors.FloodWait as wait_err:
            # FloodWait 必须等够时间，并且不计入重试次数
            logger.warning(f"Message[{message_id}]: FloodWait {wait_err.value}s - pausing download...")
            await asyncio.sleep(wait_err.value)
            # 重置重试次数，因为这不是我们的错误
            retry = -1  # 因为循环会+1，所以设置为-1

        except pyrogram.errors.ServerError:
            # Telegram服务器错误，需要更长时间重试
            logger.warning(
                f"Message[{message_id}]: Telegram Server Error - retrying after {INITIAL_RETRY_DELAY * 2}s... ({retry + 1}/{MAX_RETRIES})"
            )
            await asyncio.sleep(INITIAL_RETRY_DELAY * 2)

        except pyrogram.errors.ConnectionError:
            # 网络连接错误，需要更长时间重试
            logger.warning(
                f"Message[{message_id}]: Connection Error - retrying after {INITIAL_RETRY_DELAY * 3}s... ({retry + 1}/{MAX_RETRIES})"
            )
            await asyncio.sleep(INITIAL_RETRY_DELAY * 3)

        except TypeError:
            # 旧逻辑保留：pyrogram 内部某些情况下会抛 TypeError 当 timeout
            logger.warning(
                f"{_t('Timeout Error occurred when downloading Message')}[{message_id}], "
                f"{_t('retrying after')} {RETRY_TIME_OUT} {_t('seconds')} ({retry + 1}/{MAX_RETRIES})"
            )
            await asyncio.sleep(RETRY_TIME_OUT)

        except ValueError as e:
            # ✅ 包括 size mismatch / 空路径等
            logger.warning(f"Message[{message_id}]: {e}, retrying... ({retry + 1}/{MAX_RETRIES})")
            await asyncio.sleep(1)

        except Exception as e:
            logger.error(
                f"Message[{message_id}]: {_t('could not be downloaded due to following exception')}: [{e}].",
                exc_info=True,
            )
            # 对于未知错误，使用指数退避延迟
            retry_delay = min(INITIAL_RETRY_DELAY * (2 ** retry), MAX_RETRY_DELAY)
            await asyncio.sleep(retry_delay)

        finally:
            # ✅ 无论成功/失败都停止 watchdog，避免后台悬挂
            if watchdog_task:
                watchdog_task.cancel()

            # ✅ 如果 download_task 还活着（例如异常提前跳出），也确保 cancel
            if download_task and not download_task.done():
                download_task.cancel()

    # 失败后也清理，防止字典膨胀
    DOWNLOAD_LAST_PROGRESS_TS.pop(message_id, None)
    DOWNLOAD_LAST_PROGRESS_BYTES.pop(message_id, None)
    
    # 清理下载结果中的进度信息，确保WebUI不再显示失败任务的进度
    download_result = get_download_result()
    if node.chat_id in download_result and message_id in download_result[node.chat_id]:
        del download_result[node.chat_id][message_id]
    
    logger.warning(f"Message[{message_id}] ({ui_file_name}): All {retry + 1} retries failed.")

    return DownloadStatus.FailedDownload, None


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
    from module.pyrogram_extension import report_bot_status
    import time
    
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
                        await asyncio.sleep(GLOBAL_COOLDOWN - (current_time - global_last_refresh_time))
                    
                    try:
                        # 使用immediate_reply=False，尊重现有的1秒更新限制
                        # 但我们的全局冷却和节点数量限制已经提供了额外保护
                        await report_bot_status(node.bot, node)
                        # 更新全局冷却时间
                        global_last_refresh_time = time.time()
                        
                        # 小延迟，避免过快发送请求
                        await asyncio.sleep(1)
                    except Exception as e:
                        logger.debug(f"Failed to refresh progress for task {task_id}: {e}")
                        # 出错时也更新冷却时间，避免重试风暴
                        global_last_refresh_time = time.time()
        except Exception as e:
            logger.debug(f"Periodic progress refresh error: {e}")
        
        # 等待30秒后再次执行
        await asyncio.sleep(30)


async def worker(client: pyrogram.client.Client):
    """Work for download task"""
    logger.info("worker: 工作线程已启动")
    logger.info(f"worker start queue_id={id(queue)}")

    while True:
        item = await queue.get()   # ✅ 只 get 一次
        message = None
        node = None
        real_client = None
        
        try:
            logger.info(
                f"worker: got item queue_size={queue.qsize()} "
                f"queue_id={id(queue)} item_type={type(item)}"
            )

            # ✅ 防御性解包
            try:
                message, node = item
            except Exception:
                logger.error(f"worker: invalid queue item (expect (message,node)): {item!r}")
                continue

            # 确保node对象存在
            if not node:
                logger.error("worker: node is None")
                continue
                
            msg_id = getattr(message, "id", "N/A")
            task_id = getattr(node, "task_id", "N/A")

            if getattr(node, "is_stop_transmission", False):
                logger.info(f"worker: 任务已停止 - message_id={msg_id}, task_id={task_id}")
                continue

            logger.info(f"worker: 开始处理下载任务 - message_id={msg_id}, task_id={task_id}")

            real_client = getattr(node, "client", None) or client

            # ✅ 这里必须 await（你说“缺了一部分 await”，核心就在这里）
            await download_task(real_client, message, node)

            logger.info(f"worker: 完成下载任务 - message_id={msg_id}, task_id={task_id}")

        except asyncio.CancelledError:
            # ✅ 服务退出时正常取消，不要吞掉
            logger.info("worker: cancelled, exiting")
            raise
        except Exception as e:
            logger.exception(f"worker: 处理下载任务失败: {e}")
            # 可选：异常后稍微 sleep，避免持续异常刷屏
            await asyncio.sleep(0.5)
        finally:
            # ✅ 无论成功/continue/异常，都保证 task_done 一次
            try:
                queue.task_done()
            except Exception as e:
                logger.error(f"worker: task_done failed: {e}")
            
            # 清理资源引用
            del message
            del node
            del real_client
            del item

async def download_comments(
    client: pyrogram.Client,
    chat_id: int,
    base_message_id: int,
    start_comment_id: int,
    end_comment_id: int,
    download_filter: str,
    node: TaskNode,
):
    """Download comments for a specific message"""
    from module.download_stat import remove_active_task_node
    from module.pyrogram_extension import report_bot_status, set_meta_data
    from utils.meta_data import MetaData
    from utils.format import validate_title
    
    try:
        logger.info(f"download_comments: 开始下载评论 - chat_id={chat_id}, base_message_id={base_message_id}, start_comment_id={start_comment_id}, end_comment_id={end_comment_id}")
        logger.info(f"download_comments: 任务节点信息 - task_id={node.task_id}, is_running={node.is_running}, is_stop_transmission={node.is_stop_transmission}")
        
        # 获取讨论组信息
        try:
            # 使用get_discussion_message获取讨论组信息
            logger.info(f"download_comments: 尝试获取讨论组信息 - chat_id={chat_id}, base_message_id={base_message_id}")
            discussion_message = await client.get_discussion_message(chat_id, base_message_id)
            
            if not discussion_message:
                logger.error(f"download_comments: 无法获取讨论组消息 - chat_id={chat_id}, base_message_id={base_message_id}")
                return
                
            logger.info(f"download_comments: 成功获取讨论组消息 - id={discussion_message.id}, chat_id={discussion_message.chat.id}, title={discussion_message.chat.title}")
            discussion_group_id = discussion_message.chat.id
            logger.info(f"download_comments: 使用讨论组ID: {discussion_group_id}")
        except Exception as e:
            logger.error(f"download_comments: 获取讨论组信息失败: {e}")
            import traceback
            traceback.print_exc()
            return
        
        # 生成评论ID列表
        comment_ids = list(range(start_comment_id, end_comment_id + 1))
        logger.info(f"download_comments: 生成评论ID列表: {comment_ids}")
        
        # 获取所有评论对象 - 使用批量获取提高效率
        comments = []
        BATCH_SIZE = 50  # Pyrogram批量获取的建议最大限制
        
        # 将评论ID列表分成多个批次
        for i in range(0, len(comment_ids), BATCH_SIZE):
            batch_ids = comment_ids[i:i+BATCH_SIZE]
            logger.info(f"download_comments: 批量获取评论 - 批次 {i//BATCH_SIZE + 1}/{len(comment_ids)//BATCH_SIZE + 1}, 评论ID={batch_ids}")
            
            try:
                # 批量获取评论
                batch_comments = await client.get_messages(discussion_group_id, batch_ids)
                
                # 处理批量获取的结果
                for comment in batch_comments:
                    if not comment:
                        logger.warning(f"download_comments: 未找到评论 - 可能ID不存在")
                        continue
                        
                    # 检查评论对象的详细信息
                    logger.info(f"download_comments: 评论对象信息 - id={comment.id}, type={type(comment)}, empty={comment.empty}, has_media={comment.media is not None}")
                    logger.info(f"download_comments: 评论属性 - hasattr(comment, 'id')={hasattr(comment, 'id')}, hasattr(comment, 'chat')={hasattr(comment, 'chat')}")
                    
                    # 即使comment.empty为True，也尝试检查是否有有价值的信息
                    if hasattr(comment, 'id'):
                        # 如果评论有ID，无论是否为空，都添加到列表中
                        logger.info(f"download_comments: 评论 {comment.id} 信息可用，添加到下载列表")
                        comments.append(comment)
                    else:
                        logger.warning(f"download_comments: 评论没有ID属性，跳过")
                        continue
                        
            except Exception as e:
                logger.error(f"download_comments: 批量获取评论失败 - 批次 {i//BATCH_SIZE + 1}: {e}")
                import traceback
                traceback.print_exc()
                # 对于批量获取失败的情况，尝试单独获取每个评论
                for comment_id in batch_ids:
                    try:
                        logger.info(f"download_comments: 单独重试获取评论 - id={comment_id}")
                        comment = await client.get_messages(discussion_group_id, comment_id)
                        if comment and hasattr(comment, 'id'):
                            comments.append(comment)
                            logger.info(f"download_comments: 单独获取评论 {comment.id} 成功")
                    except Exception as single_e:
                        logger.error(f"download_comments: 单独获取评论 {comment_id} 失败: {single_e}")
                        node.failed_download_task += 1
                        await report_bot_status(node.bot, node)
        
        logger.info(f"共找到 {len(comments)} 条符合条件的评论")
        
        # 按评论ID排序
        comments.sort(key=lambda x: x.id)
        logger.info(f"评论排序完成，顺序: {[c.id for c in comments]}")
        
        # 设置总任务数
        node.total_download_task = len(comments)
        logger.info(f"设置总任务数: {len(comments)}")
        await report_bot_status(node.bot, node)
        
        # 处理下载过滤
        if download_filter:
            from utils.format import replace_date_time
            from module.app import app
            
            # 创建临时ChatDownloadConfig用于过滤
            class TempChatDownloadConfig:
                def __init__(self):
                    self.download_filter = download_filter
            
            temp_config = TempChatDownloadConfig()
            
            # 应用过滤
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
            node.total_download_task = len(comments)
            await report_bot_status(node.bot, node)
        
        # 下载评论中的媒体
        logger.info(f"开始下载评论媒体，共 {len(comments)} 条评论")
        for i, comment in enumerate(comments):
            if not node.is_running:
                logger.info(f"任务已停止，中断下载")
                break
            
            logger.info(f"处理评论 {i+1}/{len(comments)}: id={comment.id}, has_media={comment.media is not None}, type={type(comment)}")
            
            try:
                # 确保comment.chat存在
                chat_id = comment.chat.id if comment.chat else "未知"
                logger.info(f"准备添加下载任务: comment_id={comment.id}, chat_id={chat_id}")
                result = await add_download_task(comment, node)
                logger.info(f"添加下载任务结果: {result}")
            except Exception as e:
                logger.error(f"处理评论 {comment.id} 失败: {e}")
                import traceback
                traceback.print_exc()
                node.failed_download_task += 1
                await report_bot_status(node.bot, node)
        
        # 等待所有下载任务完成
        logger.info(f"评论下载任务已添加 {len(comments)} 条评论到下载队列，等待下载完成")
        
        # 定期检查下载状态，直到所有任务完成
        while True:
            # 计算已完成的任务数
            completed_tasks = node.success_download_task + node.failed_download_task + node.skip_download_task
            logger.info(f"下载进度: 已完成 {completed_tasks}/{len(comments)} 个任务")
            
            if completed_tasks >= len(comments):
                logger.info("所有下载任务已完成")
                break
                
            # 更新状态报告
            await report_bot_status(node.bot, node)
            
            # 等待5秒后再次检查
            await asyncio.sleep(5)
        
        # 所有任务完成后，报告最终状态
        await report_bot_status(node.bot, node)
        logger.info(f"评论下载任务已全部完成 - 成功: {node.success_download_task}, 失败: {node.failed_download_task}, 跳过: {node.skip_download_task}")
        
        # 清理任务节点
        from module.download_stat import remove_active_task_node
        remove_active_task_node(node.task_id)
        
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
    client: pyrogram.Client,
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
        if caption:
            caption = validate_title(caption)
            app.set_caption_name(node.chat_id, message.media_group_id, caption)
            app.set_caption_entities(
                node.chat_id, message.media_group_id, message.caption_entities
            )
        else:
            caption = app.get_caption_name(node.chat_id, message.media_group_id)
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


async def download_all_chat(client: pyrogram.Client):
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


async def start_server(client: pyrogram.Client):
    """
    Start the server using the provided client.
    """
    await client.start()


async def stop_server(client: pyrogram.Client):
    """
    Stop the server using the provided client.
    """
    await client.stop()


def main():
    """Main function of the downloader."""
    tasks = []
    client = HookClient(
        "media_downloader",
        api_id=app.api_id,
        api_hash=app.api_hash,
        proxy=app.proxy,
        workdir=app.session_file_path,
        start_timeout=app.start_timeout,
    )

    # ======================================================
    # --- 监控插件开始：强力加载 config.yaml 中的监控配置 ---
    # ======================================================
    try:
        # 直接读取文件，防止 app.config 过滤掉非原生字段
        with open(CONFIG_NAME, "r", encoding="utf-8") as f:
            _full_cfg = yaml.safe_load(f)
        
        m_cfg = _full_cfg.get("monitor", {})
        # 添加下面这一行
        print(f"DEBUG: monitor config is: {m_cfg}")
        if m_cfg and m_cfg.get("enabled"):
            MONITOR_CHATS = m_cfg.get("chats", [])
            KEYWORDS = m_cfg.get("keywords", [])
            WEBHOOK_URL = m_cfg.get("webhook_url")
            MIN_INTERVAL = m_cfg.get("min_interval", 5)
            
            # 内部变量用于频率控制，使用字典防止闭包作用域问题
            state = {"last_post_time": 0}

            async def send_to_discord(content):
                async with aiohttp.ClientSession() as session:
                    try:
                        async with session.post(WEBHOOK_URL, json={"content": content}) as resp:
                            if resp.status not in [200, 204]:
                                logger.warning(f"Webhook 转发失败，状态码: {resp.status}")
                    except Exception as e:
                        logger.error(f"Webhook 网络错误: {e}")

            @client.on_message(pyrogram.filters.chat(MONITOR_CHATS))
            async def keyword_monitor_handler(c, message):
                text = message.text or message.caption
                if not text: return
                
                matched = [w for w in KEYWORDS if w in text]
                if matched:
                    current_time = time.time()
                    if current_time - state["last_post_time"] < MIN_INTERVAL:
                        return
                    
                    chat_title = message.chat.title or "未知频道"
                    # 构造链接
                    clean_id = str(message.chat.id).replace("-100", "")
                    msg_link = f"https://t.me/c/{clean_id}/{message.id}"
                    
                    discord_msg = (
                        f"🔔 **关键词命中: {', '.join(matched)}**\n"
                        f"来自频道: **{chat_title}**\n"
                        f"内容: {text[:500]}\n"
                        f"🔗 [点击跳转]({msg_link})"
                    )
                    
                    # 异步任务发送，不占用主消息循环
                    asyncio.create_task(send_to_discord(discord_msg))
                    state["last_post_time"] = current_time
            
            logger.success(f"✅ 监控插件已加载！监控频道: {len(MONITOR_CHATS)} 个, 关键词: {len(KEYWORDS)} 个")
        else:
            logger.info("ℹ️ 监控插件未启用 (enabled=false)")
    except Exception as e:
        logger.error(f"❌ 监控插件加载过程中出现异常: {e}")
    # ======================================================
    # --- 监控插件结束 ---
    # ======================================================

    try:
        app.pre_run()
        init_web(app)

        set_max_concurrent_transmissions(client, app.max_concurrent_transmissions)

        app.loop.run_until_complete(start_server(client))
        logger.success(_t("Successfully started (Press Ctrl+C to stop)"))

        app.loop.create_task(download_all_chat(client))
        
        # 你的原有任务
        if "periodic_progress_refresh" in globals():
            app.loop.create_task(periodic_progress_refresh())
            logger.info("Created periodic progress refresh task (interval: 20 seconds)")
        
        logger.info(f"Creating {app.max_download_task} download workers")
        for _ in range(app.max_download_task):
            task = app.loop.create_task(worker(client))
            tasks.append(task)

        if app.bot_token:
            app.loop.run_until_complete(
                start_download_bot(app, client, add_download_task, download_chat_task)
            )
        _exec_loop()
    except KeyboardInterrupt:
        logger.info(_t("KeyboardInterrupt"))
    except Exception as e:
        logger.exception("{}", e)
    finally:
        app.is_running = False
        if app.bot_token:
            try:
                app.loop.run_until_complete(stop_download_bot())
            except Exception as e:
                logger.warning(f"stop_download_bot ignore: {e}")

        try:
            app.loop.run_until_complete(stop_server(client))
        except Exception as e:
            logger.warning(f"stop_server ignore: {e}")
        for task in tasks:
            task.cancel()
        logger.info(_t("Stopped!"))
        # check_for_updates(app.proxy)
        logger.info(f"{_t('update config')}......")
        app.update_config()
        
        # 打印性能统计信息
        print_performance_stats()
        
        logger.success(
            f"{_t('Updated last read message_id to config file')},"
            f"{_t('total download')} {app.total_download_task}, "
            f"{_t('total upload file')} "
            f"{app.cloud_drive_config.total_upload_success_file_count}"
        )


if __name__ == "__main__":
    if _check_config():
        main()

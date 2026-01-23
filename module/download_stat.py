"""Download Stat"""
import asyncio
import time
from enum import Enum

from pyrogram import Client

from module.app import TaskNode

DOWNLOAD_LAST_PROGRESS_TS: dict[int, float] = {}
DOWNLOAD_LAST_PROGRESS_BYTES: dict[int, int] = {}

class DownloadState(Enum):
    """Download state"""

    Downloading = 1
    StopDownload = 2


_download_result: dict = {}
_total_download_speed: int = 0
_total_download_size: int = 0
_last_download_time: float = time.time()
_download_state: DownloadState = DownloadState.Downloading
_active_task_nodes: dict = {}  # 全局活跃TaskNode管理: {task_id: TaskNode}


def get_download_result() -> dict:
    """get global download result"""
    return _download_result


def add_active_task_node(node) -> None:
    """添加或更新活跃的TaskNode
    
    Args:
        node: TaskNode实例
    """
    if node.task_id:
        _active_task_nodes[node.task_id] = node


def remove_active_task_node(task_id: int) -> None:
    """移除活跃的TaskNode
    
    Args:
        task_id: TaskNode的task_id
    """
    if task_id in _active_task_nodes:
        del _active_task_nodes[task_id]


def get_active_task_nodes() -> dict:
    """获取所有活跃的TaskNode
    
    Returns:
        dict: {task_id: TaskNode} 格式的活跃TaskNode字典
    """
    return _active_task_nodes


def get_total_download_speed() -> int:
    """get total download speed"""
    return _total_download_speed


def get_download_state() -> DownloadState:
    """get download state"""
    return _download_state


# pylint: disable = W0603
def set_download_state(state: DownloadState):
    """set download state"""
    global _download_state
    _download_state = state


async def update_download_status(
    down_byte: int,
    total_size: int,
    message_id: int,
    file_name: str,
    start_time: float,
    node: TaskNode,
    client: Client,
):
    """update_download_status"""
    cur_time = time.time()

    # ---- stall watchdog heartbeat ----
    DOWNLOAD_LAST_PROGRESS_TS[message_id] = cur_time

    prev_bytes = DOWNLOAD_LAST_PROGRESS_BYTES.get(message_id, -1)
    if down_byte > prev_bytes:
        DOWNLOAD_LAST_PROGRESS_BYTES[message_id] = down_byte
    # ---- end heartbeat ----
    # pylint: disable = W0603
    global _total_download_speed
    global _total_download_size
    global _last_download_time

    if node.is_stop_transmission:
        client.stop_transmission()

    chat_id = node.chat_id

    while get_download_state() == DownloadState.StopDownload:
        if node.is_stop_transmission:
            client.stop_transmission()
        await asyncio.sleep(1)

    if not _download_result.get(chat_id):
        _download_result[chat_id] = {}

    if _download_result[chat_id].get(message_id):
        last_download_byte = _download_result[chat_id][message_id]["down_byte"]
        last_time = _download_result[chat_id][message_id]["end_time"]
        download_speed = _download_result[chat_id][message_id]["download_speed"]
        each_second_total_download = _download_result[chat_id][message_id][
            "each_second_total_download"
        ]
        end_time = _download_result[chat_id][message_id]["end_time"]

        _total_download_size += down_byte - last_download_byte
        each_second_total_download += down_byte - last_download_byte

        if cur_time - last_time >= 1.0:
            download_speed = int(each_second_total_download / (cur_time - last_time))
            end_time = cur_time
            each_second_total_download = 0

        download_speed = max(download_speed, 0)

        _download_result[chat_id][message_id]["down_byte"] = down_byte
        _download_result[chat_id][message_id]["end_time"] = end_time
        _download_result[chat_id][message_id]["download_speed"] = download_speed
        _download_result[chat_id][message_id][
            "each_second_total_download"
        ] = each_second_total_download
    else:
        each_second_total_download = down_byte
        _download_result[chat_id][message_id] = {
            "down_byte": down_byte,
            "total_size": total_size,
            "file_name": file_name,
            "start_time": start_time,
            "end_time": cur_time,
            "download_speed": down_byte / (cur_time - start_time),
            "each_second_total_download": each_second_total_download,
            "task_id": node.task_id,
        }
        _total_download_size += down_byte

    if cur_time - _last_download_time >= 1.0:
        # update speed
        _total_download_speed = int(
            _total_download_size / (cur_time - _last_download_time)
        )
        _total_download_speed = max(_total_download_speed, 0)
        _total_download_size = 0
        _last_download_time = cur_time

    # Report download status to bot - 添加速率限制
    from module.pyrogram_extension import report_bot_status
    
    # 计算下载进度百分比
    progress_percent = (down_byte / total_size * 100) if total_size > 0 else 0
    
    # 速率限制规则：
    # 1. 只在下载进度变化超过1%时更新
    # 2. 至少间隔2秒才更新一次
    # 3. 在下载接近完成时(>95%)可以更频繁地更新
    
    # 获取上次更新的进度和时间
    last_report = getattr(node, "last_progress_report", {})
    last_percent = last_report.get("percent", -1)
    last_time = last_report.get("time", 0)
    
    should_report = False
    
    # 检查是否需要更新
    if cur_time - last_time >= 2:  # 至少间隔2秒
        if abs(progress_percent - last_percent) >= 1:  # 进度变化超过1%
            should_report = True
        elif progress_percent > 95:  # 接近完成时更频繁更新
            should_report = True
    
    # 总是在下载完成或进度为0时更新
    if progress_percent == 100 or progress_percent == 0:
        should_report = True
    
    if should_report:
        # 更新上次报告的信息
        node.last_progress_report = {
            "percent": progress_percent,
            "time": cur_time
        }
        await report_bot_status(client=client, node=node)

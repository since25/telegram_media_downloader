"""Download Stat"""

import asyncio
import copy
import re
import threading
import time
from enum import Enum
from typing import Any, Callable

from pyrogram import Client

from module.app import TaskNode
from module.progress_persistence import download_progress_persistence
from module.task_state import FileStatus, TaskStatus, get_task_store, snapshot_node
from module.transfer_progress import TransferKey, TransferProgressTracker, transfer_key

download_progress_tracker = TransferProgressTracker()


class DownloadState(Enum):
    """Download state"""

    Downloading = 1
    StopDownload = 2


class DownloadResultStore:
    """Own process-local transfer display state behind synchronized snapshots."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._entries: dict[TransferKey, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._total_download_speed = 0
        self._total_download_size = 0
        self._last_download_time = self._clock()

    def observe(
        self,
        key: TransferKey,
        *,
        downloaded_size: int,
        total_size: int,
        file_name: str,
        start_time: float,
    ) -> int:
        """Record one progress sample and return its current bytes-per-second rate."""

        now = self._clock()
        downloaded = int(downloaded_size)
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                per_file_delta = downloaded
                download_speed = downloaded / max(now - float(start_time), 0.001)
                entry = {
                    "down_byte": downloaded,
                    "total_size": int(total_size),
                    "file_name": file_name,
                    "start_time": float(start_time),
                    "end_time": now,
                    "download_speed": download_speed,
                    "each_second_total_download": downloaded,
                    "task_id": key[0],
                    "chat_id": key[1],
                    "message_id": key[2],
                }
                self._entries[key] = entry
            else:
                previous_size = int(entry["down_byte"])
                per_file_delta = max(downloaded - previous_size, 0)
                last_time = float(entry["end_time"])
                download_speed = float(entry["download_speed"])
                each_second_total = int(entry["each_second_total_download"])
                each_second_total += per_file_delta
                end_time = last_time
                if now - last_time >= 1.0:
                    download_speed = int(each_second_total / (now - last_time))
                    end_time = now
                    each_second_total = 0
                entry.update(
                    {
                        "down_byte": downloaded,
                        "total_size": int(total_size),
                        "file_name": file_name,
                        "end_time": end_time,
                        "download_speed": max(download_speed, 0),
                        "each_second_total_download": each_second_total,
                    }
                )

            self._total_download_size += per_file_delta
            if now - self._last_download_time >= 1.0:
                self._total_download_speed = max(
                    int(self._total_download_size / (now - self._last_download_time)),
                    0,
                )
                self._total_download_size = 0
                self._last_download_time = now
            return max(int(entry["download_speed"]), 0)

    def snapshot(self) -> dict[TransferKey, dict[str, Any]]:
        """Return an independent snapshot safe for Flask and reporting threads."""

        with self._lock:
            return copy.deepcopy(self._entries)

    def remove(self, key: TransferKey) -> None:
        with self._lock:
            self._entries.pop(key, None)

    def clear_completed(self) -> int:
        """Remove fully downloaded display entries while preserving live progress."""

        with self._lock:
            completed = [
                key
                for key, value in self._entries.items()
                if int(value.get("total_size", 0) or 0) > 0
                and int(value.get("down_byte", 0) or 0)
                == int(value.get("total_size", 0) or 0)
            ]
            for key in completed:
                self._entries.pop(key, None)
            return len(completed)

    @property
    def total_download_speed(self) -> int:
        with self._lock:
            return self._total_download_speed

    def reset(self) -> None:
        """Clear process-local display and aggregate state for test isolation."""

        with self._lock:
            self._entries.clear()
            self._total_download_speed = 0
            self._total_download_size = 0
            self._last_download_time = self._clock()


_download_results = DownloadResultStore()
_download_state: DownloadState = DownloadState.Downloading
_download_state_lock = threading.RLock()
_active_task_nodes: dict = {}  # 全局活跃TaskNode管理: {task_id: TaskNode}
_active_task_nodes_lock = threading.RLock()


def get_download_result() -> dict[TransferKey, dict[str, Any]]:
    """Return a thread-safe snapshot of process-local download progress."""

    return _download_results.snapshot()


def record_download_result(
    node: TaskNode,
    message_id: int,
    *,
    downloaded_size: int,
    total_size: int,
    file_name: str,
    start_time: float,
) -> int:
    """Record one progress sample under the complete transfer identity."""

    return _download_results.observe(
        transfer_key(node, message_id),
        downloaded_size=downloaded_size,
        total_size=total_size,
        file_name=file_name,
        start_time=start_time,
    )


def remove_download_result(node: TaskNode, message_id: int) -> None:
    """Remove only the progress entry owned by one task transfer."""

    _download_results.remove(transfer_key(node, message_id))


def reset_download_runtime_state_for_tests() -> None:
    """Reset process-local download state without exposing mutable internals."""

    _download_results.reset()
    set_download_state(DownloadState.Downloading)


def clear_completed_download_result() -> int:
    """Drop fully-downloaded entries from the display cache; keep in-progress ones."""

    return _download_results.clear_completed()


def add_active_task_node(
    node,
    source: str | None = None,
    task_type: str | None = None,
    publish_snapshot: bool = True,
) -> None:
    """添加或更新活跃的TaskNode

    Args:
        node: TaskNode实例
    """
    if node.task_id:
        with _active_task_nodes_lock:
            if source:
                node.task_source = source
            if task_type:
                node.task_display_type = task_type
            _active_task_nodes[node.task_id] = node
            if publish_snapshot:
                snapshot_node(node)


def remove_active_task_node(task_id: int) -> None:
    """移除活跃的TaskNode

    Args:
        task_id: TaskNode的task_id
    """
    with _active_task_nodes_lock:
        if task_id in _active_task_nodes:
            snapshot_node(_active_task_nodes[task_id])
            get_task_store().complete_task(task_id)
            del _active_task_nodes[task_id]


def get_active_task_nodes() -> dict:
    """获取所有活跃的TaskNode

    Returns:
        dict: {task_id: TaskNode} 格式的活跃TaskNode字典
    """
    with _active_task_nodes_lock:
        return dict(_active_task_nodes)


def get_total_download_speed() -> int:
    """get total download speed"""
    return _download_results.total_download_speed


_RCLONE_SPEED_UNITS = {
    "": 1,
    "B": 1,
    "KB": 1024,
    "KIB": 1024,
    "MB": 1024**2,
    "MIB": 1024**2,
    "GB": 1024**3,
    "GIB": 1024**3,
}


def _parse_rclone_speed(speed: str) -> int:
    """Parse an rclone progress speed string (e.g. "1.234 MiB/s", "512 KiB/s",
    "0 B/s", or "") into bytes/s. Returns 0 for anything unparseable."""
    if not speed:
        return 0
    text = speed.strip()
    if text.endswith("/s"):
        text = text[: -len("/s")].strip()
    match = re.match(r"^([\d.]+)\s*([A-Za-z]*)$", text)
    if not match:
        return 0
    try:
        value = float(match.group(1))
    except ValueError:
        return 0
    unit = match.group(2).upper()
    return int(value * _RCLONE_SPEED_UNITS.get(unit, 1))


def get_total_upload_speed() -> int:
    """sum live per-file upload speed across active task nodes

    This deployment uploads via rclone/cloud-drive, so speeds come from
    node.cloud_drive_upload_stat_dict (rclone-formatted strings), not the
    Telegram re-upload node.upload_status/upload_stat_dict path.
    """
    total = 0
    for node in get_active_task_nodes().values():
        for stat in (getattr(node, "cloud_drive_upload_stat_dict", {}) or {}).values():
            total += _parse_rclone_speed(getattr(stat, "speed", "") or "")
    return total


def get_download_state() -> DownloadState:
    """get download state"""
    with _download_state_lock:
        return _download_state


# pylint: disable = W0603
def set_download_state(state: DownloadState):
    """set download state"""
    global _download_state
    with _download_state_lock:
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

    progress_key = transfer_key(node, message_id)
    download_progress_tracker.observe(progress_key, down_byte)

    if node.is_stop_transmission:
        client.stop_transmission()

    while get_download_state() == DownloadState.StopDownload:
        if node.is_stop_transmission:
            client.stop_transmission()
        await asyncio.sleep(1)

    download_speed = record_download_result(
        node,
        message_id,
        downloaded_size=down_byte,
        total_size=total_size,
        file_name=file_name,
        start_time=start_time,
    )

    if getattr(node, "task_id", None):
        await download_progress_persistence.persist_download(
            get_task_store(),
            node.task_id,
            message_id,
            total_count=max(
                int(getattr(node, "total_download_task", 0) or 0),
                len(getattr(node, "download_status", {}) or {}),
            ),
            filename=file_name,
            total_size=total_size,
            downloaded_size=down_byte,
            download_speed=int(download_speed),
            force=down_byte >= total_size > 0,
        )

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
        setattr(
            node,
            "last_progress_report",
            {"percent": progress_percent, "time": cur_time},
        )
        await report_bot_status(client=client, node=node)

"""Process-local queue worker for individual Telegram media files."""

import asyncio
import time
from typing import Any, Awaitable, Callable

from module.app import DownloadStatus
from module.task_state import FileStatus, TaskStatus, get_task_store, snapshot_node


async def enqueue_download(
    message,
    node,
    queue: asyncio.Queue,
    queue_entry_times: dict,
    activity_gate,
    pyrogram_client_type,
    logger,
) -> bool:
    """Validate and enqueue one file with its immutable naming snapshot."""

    download_intent = None
    enqueued = False
    try:
        msg_id = getattr(message, "id", None)
        logger.info(
            f"add_download_task: start "
            f"message_id={msg_id if msg_id is not None else 'N/A'} "
            f"queue_id={id(queue)} queue_size_before={queue.qsize()}"
        )
        if message is None:
            logger.error("add_download_task: message is None")
            return False
        if msg_id is None:
            logger.error(f"add_download_task: message has no id - type={type(message)}")
            return False
        if node is None:
            logger.error("add_download_task: node is None")
            return False

        if not hasattr(node, "download_status") or node.download_status is None:
            node.download_status = {}
        if not hasattr(node, "total_task") or node.total_task is None:
            node.total_task = 0
        if not hasattr(node, "total_download_task") or node.total_download_task is None:
            node.total_download_task = 0

        node.download_status[msg_id] = DownloadStatus.Downloading
        if getattr(node, "task_id", None):
            snapshot_node(node)
            get_task_store().update_task(
                node.task_id,
                status=TaskStatus.QUEUED,
                total_count=max(
                    node.total_download_task + 1, len(node.download_status)
                ),
            )
            get_task_store().upsert_file(
                node.task_id,
                msg_id,
                status=FileStatus.QUEUED,
            )

        queue_entry_times[(node.chat_id, msg_id)] = time.time()
        naming_snapshot = None
        naming_context = getattr(node, "package_naming_context", None)
        if naming_context is not None:
            items = getattr(node, "package_media_items", None) or {}
            naming_snapshot = {
                "context": naming_context,
                "item": items.get(msg_id),
            }

        download_intent = await activity_gate.register_download_intent()
        try:
            await queue.put((message, node, download_intent, naming_snapshot))
            enqueued = True
        except BaseException:
            download_intent.cancel()
            raise

        node.total_task += 1
        node.total_download_task += 1
        logger.info(
            f"add_download_task: enqueued "
            f"message_id={msg_id} queue_id={id(queue)} "
            f"queue_size_after={queue.qsize()} "
            f"node_task_id={getattr(node, 'task_id', 'N/A')}"
        )

        bot_client = None
        if hasattr(node, "bot_client"):
            bot_client = getattr(node, "bot_client", None)
        elif hasattr(node, "bot") and isinstance(
            getattr(node, "bot", None), pyrogram_client_type
        ):
            bot_client = node.bot

        if bot_client:
            from module.pyrogram_extension import report_bot_status

            try:
                await asyncio.wait_for(
                    report_bot_status(
                        client=bot_client, node=node, immediate_reply=True
                    ),
                    timeout=5,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"add_download_task: report_bot_status timeout - "
                    f"message_id={msg_id}"
                )
            except Exception as error:
                logger.warning(f"add_download_task: report_bot_status failed - {error}")
        return True
    except Exception as error:
        if download_intent is not None and not enqueued:
            download_intent.cancel()
        logger.exception(f"add_download_task: failed - {error}")
        return False


async def run_worker(
    client,
    queue: asyncio.Queue,
    download_task: Callable[..., Awaitable[Any]],
    activity_gate,
    logger,
) -> None:
    """Consume file work while preserving legacy queue item compatibility."""

    logger.info("worker: 工作线程已启动")
    logger.info(f"worker start queue_id={id(queue)}")

    while True:
        item = await queue.get()
        message = None
        node = None
        real_client = None
        download_intent = None
        naming_snapshot = None

        try:
            logger.info(
                f"worker: got item queue_size={queue.qsize()} "
                f"queue_id={id(queue)} item_type={type(item)}"
            )

            if isinstance(item, (tuple, list)) and len(item) == 4:
                message, node, download_intent, naming_snapshot = item
            elif isinstance(item, (tuple, list)) and len(item) == 3:
                message, node, download_intent = item
            elif isinstance(item, (tuple, list)) and len(item) == 2:
                message, node = item
            else:
                logger.error(
                    "worker: invalid queue item "
                    f"(expect (message,node[,intent])): {item!r}"
                )
                continue

            if not node:
                logger.error("worker: node is None")
                continue

            msg_id = getattr(message, "id", "N/A")
            task_id = getattr(node, "task_id", "N/A")
            if getattr(node, "is_stop_transmission", False):
                logger.info(f"worker: 任务已停止 - message_id={msg_id}, task_id={task_id}")
                if download_intent is not None:
                    download_intent.cancel()
                continue

            logger.info(f"worker: 开始处理下载任务 - message_id={msg_id}, task_id={task_id}")
            real_client = getattr(node, "client", None) or client
            if download_intent is None:
                download_intent = await activity_gate.acquire_download()
            else:
                await download_intent.activate()

            extra_kwargs = (
                {"naming_snapshot": naming_snapshot}
                if naming_snapshot is not None
                else {}
            )
            await download_task(
                real_client,
                message,
                node,
                telegram_permit=download_intent,
                **extra_kwargs,
            )
            logger.info(f"worker: 完成下载任务 - message_id={msg_id}, task_id={task_id}")
        except asyncio.CancelledError:
            logger.info("worker: cancelled, exiting")
            raise
        except Exception as error:
            logger.exception(f"worker: 处理下载任务失败: {error}")
            await asyncio.sleep(0.5)
        finally:
            if download_intent is not None:
                download_intent.release()
            try:
                queue.task_done()
            except Exception as error:
                logger.error(f"worker: task_done failed: {error}")

            del message
            del node
            del real_client
            del item

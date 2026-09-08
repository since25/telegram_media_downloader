"""入队路径的性能契约与终态任务保护。"""

import asyncio
import unittest
from types import SimpleNamespace

import pyrogram

from module.app import DownloadStatus, TaskNode
from module.download_queue import enqueue_download
from module.task_state import (
    FileStatus,
    TaskStateStore,
    TaskStatus,
    reset_task_store_for_tests,
)


class _Logger:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def exception(self, *_args, **_kwargs):
        pass


class _Intent:
    def cancel(self):
        pass


class _ActivityGate:
    async def register_download_intent(self):
        return _Intent()


class _CountingStore(TaskStateStore):
    """记录每次入队真正发生了多少次文件级写入。"""

    def __init__(self):
        super().__init__()
        self.file_writes = 0

    def transition_file(self, *args, **kwargs):
        self.file_writes += 1
        return super().transition_file(*args, **kwargs)


def _node_with_history(task_id: str, history: int) -> TaskNode:
    node = TaskNode(chat_id=-1006, task_id=task_id)
    node.download_status = {
        index: DownloadStatus.SuccessDownload for index in range(history)
    }
    node.total_task = history
    node.total_download_task = history
    return node


async def _enqueue(node, message_id, store):
    queue: asyncio.Queue = asyncio.Queue()
    ok = await enqueue_download(
        SimpleNamespace(id=message_id),
        node,
        queue,
        {},
        _ActivityGate(),
        pyrogram.Client,
        _Logger(),
    )
    return ok, queue, store


class EnqueueCostTestCase(unittest.TestCase):
    def setUp(self):
        self.store = _CountingStore()
        self.previous_store = reset_task_store_for_tests(self.store)
        self.addCleanup(reset_task_store_for_tests, self.previous_store)

    def test_enqueue_cost_does_not_grow_with_task_size(self):
        """一次入队只写当前这一个文件，与任务里已有多少文件无关。

        这条契约是关键：以前入队会回写任务下的全部文件，
        导致整批入队退化成平方级，把事件循环整个占死。
        """

        small_node = _node_with_history("small", 5)
        asyncio.run(_enqueue(small_node, 1000, self.store))
        small_writes = self.store.file_writes

        self.store.file_writes = 0
        large_node = _node_with_history("large", 500)
        asyncio.run(_enqueue(large_node, 2000, self.store))
        large_writes = self.store.file_writes

        self.assertEqual(small_writes, 1)
        self.assertEqual(large_writes, 1)

    def test_enqueue_records_the_new_file(self):
        node = _node_with_history("records", 3)

        ok, queue, _ = asyncio.run(_enqueue(node, 4242, self.store))

        self.assertTrue(ok)
        self.assertEqual(queue.qsize(), 1)
        task = self.store.get_task("records")
        self.assertEqual(task.files["4242"].status, FileStatus.QUEUED)

    def test_enqueue_into_terminal_task_does_not_raise(self):
        """恢复出来的终态任务继续入队时不能抛状态机异常。"""

        self.store.create_task(
            "terminal", status=TaskStatus.COMPLETED_WITH_ERRORS
        )
        node = _node_with_history("terminal", 2)

        ok, _, _ = asyncio.run(_enqueue(node, 7000, self.store))

        self.assertTrue(ok)
        task = self.store.get_task("terminal")
        self.assertEqual(task.status, TaskStatus.COMPLETED_WITH_ERRORS)
        self.assertEqual(task.files["7000"].status, FileStatus.QUEUED)


if __name__ == "__main__":
    unittest.main()

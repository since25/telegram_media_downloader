import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from module.app import DownloadStatus, TaskNode
from module.download_lifecycle import FileLifecycleRuntime, _record_performance
from module.download_queue import enqueue_download
from module.download_stat import DownloadResultStore
from module.transfer_progress import transfer_key


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class _Intent:
    def cancel(self):
        return None


class _Gate:
    async def register_download_intent(self):
        return _Intent()


def test_download_results_isolate_same_message_in_same_chat_by_task():
    timestamps = iter((10.0, 10.1, 10.2, 10.3))
    store = DownloadResultStore(clock=lambda: next(timestamps))
    first = ("task-1", "-1001", "42")
    second = ("task-2", "-1001", "42")

    store.observe(
        first,
        downloaded_size=100,
        total_size=1000,
        file_name="first.mp4",
        start_time=1.0,
    )
    store.observe(
        second,
        downloaded_size=200,
        total_size=2000,
        file_name="second.mp4",
        start_time=1.0,
    )
    store.remove(first)

    snapshot = store.snapshot()
    assert first not in snapshot
    assert snapshot[second]["down_byte"] == 200
    assert snapshot[second]["file_name"] == "second.mp4"


def test_download_result_snapshot_is_independent_during_concurrent_updates():
    counter = 0
    counter_lock = threading.Lock()

    def clock():
        nonlocal counter
        with counter_lock:
            counter += 1
            return float(counter)

    store = DownloadResultStore(clock=clock)
    key = ("task-1", "-1001", "42")

    def writer():
        for downloaded_size in range(1, 100):
            store.observe(
                key,
                downloaded_size=downloaded_size,
                total_size=100,
                file_name="file.mp4",
                start_time=0.0,
            )

    def reader():
        for _ in range(100):
            snapshot = store.snapshot()
            if key in snapshot:
                snapshot[key]["down_byte"] = -1

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(writer), executor.submit(reader), executor.submit(reader)]
        for future in futures:
            future.result(timeout=5)

    assert store.snapshot()[key]["down_byte"] == 99


def test_enqueue_timing_identity_includes_task_id_for_same_chat_message():
    queue = asyncio.Queue()
    queue_entry_times = {}
    message = SimpleNamespace(id=42)
    first = TaskNode(chat_id=-1001, task_id="task-1")
    second = TaskNode(chat_id=-1001, task_id="task-2")

    async def run():
        assert await enqueue_download(
            message,
            first,
            queue,
            queue_entry_times,
            _Gate(),
            object,
            _Logger(),
        )
        assert await enqueue_download(
            message,
            second,
            queue,
            queue_entry_times,
            _Gate(),
            object,
            _Logger(),
        )

    asyncio.run(run())

    assert set(queue_entry_times) == {
        transfer_key(first, message.id),
        transfer_key(second, message.id),
    }


def test_performance_cleanup_does_not_remove_another_tasks_same_message():
    first = TaskNode(chat_id=-1001, task_id="task-1")
    second = TaskNode(chat_id=-1001, task_id="task-2")
    first_key = transfer_key(first, 42)
    second_key = transfer_key(second, 42)
    task_start_times = {first_key: 1.0, second_key: 2.0}
    runtime = FileLifecycleRuntime(
        app=SimpleNamespace(),
        logger=_Logger(),
        download_media=None,
        save_msg_to_file=None,
        upload_telegram_chat=None,
        update_cloud_upload_stat=None,
        report_bot_download_status=None,
        task_store=None,
        snapshot_node=None,
        naming_snapshot_context=None,
        queue_entry_times={},
        task_start_times=task_start_times,
        performance_stats={
            "total_download_time": 0,
            "download_task_count": 0,
            "successful_downloads": 0,
            "failed_downloads": 0,
            "skipped_downloads": 0,
            "avg_download_time": 0,
            "avg_queue_time": 0,
            "total_queue_time": 0,
        },
        remove_download_result=lambda *_args: None,
    )

    _record_performance(first, 42, DownloadStatus.SuccessDownload, runtime)

    assert first_key not in task_start_times
    assert second_key in task_start_times

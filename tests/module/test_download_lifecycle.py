import asyncio
import contextvars
from types import SimpleNamespace

from module.app import DownloadStatus, TaskNode
from module.download_lifecycle import FileLifecycleRuntime, run_file_lifecycle
from module.task_state import FileStatus


class _Store:
    def __init__(self):
        self.files = {}
        self.tasks = {}

    def update_task(self, task_id, **updates):
        self.tasks.setdefault(str(task_id), {}).update(updates)

    def upsert_file(self, task_id, message_id, **updates):
        self.files.setdefault((str(task_id), str(message_id)), {}).update(updates)

    def transition_file(
        self,
        task_id,
        message_id,
        *,
        task_updates=None,
        file_updates=None,
    ):
        self.tasks.setdefault(str(task_id), {}).update(task_updates or {})
        self.files.setdefault((str(task_id), str(message_id)), {}).update(
            file_updates or {}
        )


class _Logger:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def test_reporting_failure_does_not_change_successful_download_result():
    store = _Store()
    naming_context = contextvars.ContextVar("naming_context", default=None)
    node = TaskNode(chat_id=-1001, task_id="task-1", bot=object())
    node.is_running = True
    node.total_task = 1
    node.total_download_task = 1
    message = SimpleNamespace(id=101, media=object(), text=None)

    async def download_media(*_args, **_kwargs):
        return DownloadStatus.SuccessDownload, None

    async def ignore_async(*_args, **_kwargs):
        return None

    async def fail_report(*_args, **_kwargs):
        raise RuntimeError("notification unavailable")

    runtime = FileLifecycleRuntime(
        app=SimpleNamespace(
            media_types=[],
            file_formats={},
            enable_download_txt=False,
            cloud_drive_config=SimpleNamespace(enable_upload_file=False),
            hide_file_name=False,
        ),
        logger=_Logger(),
        download_media=download_media,
        save_msg_to_file=ignore_async,
        upload_telegram_chat=ignore_async,
        update_cloud_upload_stat=lambda *_args, **_kwargs: None,
        report_bot_download_status=fail_report,
        task_store=store,
        snapshot_node=lambda *_args, **_kwargs: None,
        naming_snapshot_context=naming_context,
        queue_entry_times={},
        task_start_times={},
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

    asyncio.run(
        run_file_lifecycle(
            client=object(),
            message=message,
            node=node,
            telegram_permit=None,
            naming_snapshot=None,
            runtime=runtime,
        )
    )

    assert node.success_download_task == 1
    assert node.failed_download_task == 0
    assert node.download_status[101] is DownloadStatus.SuccessDownload
    assert store.files[("task-1", "101")]["status"] == FileStatus.DOWNLOADED

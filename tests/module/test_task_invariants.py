import asyncio

from module.app import DownloadStatus, TaskNode


def _running_node(planned: int = 1) -> TaskNode:
    node = TaskNode(chat_id=-1001, task_id=1)
    node.is_running = True
    node.total_task = planned
    node.total_download_task = planned
    return node


def test_planned_file_without_terminal_result_is_not_finished():
    node = _running_node()

    assert node.is_finish() is False


def test_each_terminal_result_finishes_one_planned_file():
    for status in (
        DownloadStatus.SuccessDownload,
        DownloadStatus.FailedDownload,
        DownloadStatus.SkipDownload,
    ):
        node = _running_node()

        node.stat(status, node.chat_id, 101, "sample.bin")

        assert node.is_finish() is True


def test_running_task_without_planned_files_is_not_finished():
    node = _running_node(planned=0)

    assert node.is_finish() is False


def test_prescan_batch_and_cancellation_keep_explicit_terminal_rules():
    node = _running_node()
    node.stat(DownloadStatus.SuccessDownload, node.chat_id, 101, "sample.bin")
    node.prescan_batch_in_progress = True

    assert node.is_finish() is False

    node.stop_transmission()

    assert node.is_finish() is True


def test_duplicate_file_result_is_counted_once():
    node = _running_node()

    node.stat(DownloadStatus.SuccessDownload, node.chat_id, 101, "sample.bin")
    node.stat(DownloadStatus.SuccessDownload, node.chat_id, 101, "sample.bin")

    assert node.success_download_task == 1
    assert node.failed_download_task == 0
    assert node.skip_download_task == 0
    assert node.success_tasks == [(-1001, 101, "sample.bin")]


def test_reporting_reads_result_without_recording_it_again(monkeypatch):
    from module import pyrogram_extension

    node = _running_node()
    node.bot = object()
    node.reply_message_id = 1

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("reporting must not mutate the file result")

    async def ignore_status(*_args, **_kwargs):
        return None

    monkeypatch.setattr(node, "stat", fail_if_called)
    monkeypatch.setattr(pyrogram_extension, "report_bot_status", ignore_status)

    asyncio.run(
        pyrogram_extension.report_bot_download_status(
            node.bot,
            node,
            DownloadStatus.SuccessDownload,
            10,
            chat_id=node.chat_id,
            message_id=101,
            file_name="sample.bin",
        )
    )

    assert node.total_download_byte == 10

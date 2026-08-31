"""评论下载扫描失败时必须走清理路径，不能静默消失。"""

import asyncio
from types import SimpleNamespace

import pytest

from module import download_entry


class _FakePermit:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


@pytest.mark.parametrize(
    "error",
    [
        ValueError("无法读取该讨论组"),
        RuntimeError("扫描评论失败"),
    ],
)
def test_scan_failure_reports_status_and_releases_the_task_node(monkeypatch, error):
    """扫描失败必须上报状态并释放 TaskNode。

    回归场景：download_comments 内层的 `except ValueError: return` 和
    `except Exception: return` 无日志无清理地吞掉扫描失败，绕过了外层
    已经会 report_bot_status + remove_active_task_node 的处理分支。
    结果是坏链接或无权限时命令凭空消失，节点留在全局活跃注册表里直到
    重启，用户的回复消息永远显示"进行中"。
    """
    reported = []
    removed = []

    monkeypatch.setattr(
        download_entry,
        "get_telegram_activity_gate",
        lambda: SimpleNamespace(download_permit=_FakePermit),
    )

    async def failing_scan(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(download_entry, "scan_comment_range", failing_scan)

    async def fake_report(_bot_client, node):
        reported.append(node.task_id)

    monkeypatch.setattr(
        "module.pyrogram_extension.report_bot_status",
        fake_report,
    )
    monkeypatch.setattr(
        "module.download_stat.remove_active_task_node",
        lambda task_id: removed.append(task_id),
    )

    node = SimpleNamespace(
        task_id=42,
        bot=object(),
        is_running=True,
        is_stop_transmission=False,
    )

    asyncio.run(
        download_entry.download_comments(
            client=object(),
            chat_id=-1001234567890,
            base_message_id=1,
            start_comment_id=1,
            end_comment_id=5,
            download_filter=None,
            node=node,
        )
    )

    assert reported == [42]
    assert removed == [42]

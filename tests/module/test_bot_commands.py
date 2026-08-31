"""Contracts for the management Bot command surface."""

import asyncio
from pathlib import Path
from types import SimpleNamespace

from module import bot


def test_admin_command_menu_excludes_legacy_forward():
    names = [command.command for command in bot.build_admin_bot_commands()]

    assert "forward" not in names
    assert "listen_forward" in names


def test_admin_help_excludes_legacy_forward():
    help_text = bot.build_admin_help_text()

    assert "/forward -" not in help_text
    assert "/listen_forward -" in help_text


def test_resource_bot_configuration_is_documented_without_real_secret():
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    readme = Path("README_CN.md").read_text(encoding="utf-8")
    handoff = Path("docs/resource-bot-server-handoff.md").read_text(
        encoding="utf-8"
    )

    assert "resource_bot_token: your_resource_bot_token" in example
    assert "resource_bot_token" in readme
    assert "resource_bot.sqlite3" in handoff
    assert "tg-downloader.service" in handoff


def test_gen_task_id_skips_persisted_task_ids():
    """Bot task ids must not collide with ids persisted before a restart.

    Regression: the in-memory counter resets to zero on restart while the
    task store keeps terminal bot tasks, so the first new task reused a
    'completed' id and every enqueue failed with
    invalid_task_transition: 'completed' -> 'queued'.
    """
    from module import bot
    from module.task_state import TaskStatus, get_task_store

    store = get_task_store()
    store.create_task("1", status=TaskStatus.COMPLETED)
    store.create_task("3", status=TaskStatus.FAILED)

    instance = bot.DownloadBot()
    instance.task_id = 0

    assert instance.gen_task_id() == 2  # skip persisted "1"
    assert instance.gen_task_id() == 4  # skip persisted "3"


def test_gen_task_id_falls_back_to_counter_without_task_store(monkeypatch):
    """gen_task_id still works when the task store is not initialized."""
    from module import bot

    instance = bot.DownloadBot()
    instance.task_id = 5

    def uninitialized_store():
        raise RuntimeError("task store is not initialized")

    monkeypatch.setattr(
        "module.task_state.get_task_store",
        uninitialized_store,
    )

    assert instance.gen_task_id() == 6


def test_update_config_writes_to_the_bot_config_path(tmp_path, monkeypatch):
    """Bot 设置必须写回 config_path，而不是一个叫 d 的垃圾文件。

    回归场景：update_config 把配置 dump 到字面量文件 "d"，而 start() 从
    self.config_path 读取，导致通过 bot 设置的过滤器每次重启全部丢失，
    并在运行目录里堆积名为 "d" 的垃圾文件。
    """
    monkeypatch.chdir(tmp_path)
    instance = bot.DownloadBot()
    instance.config_path = str(tmp_path / "bot.yaml")
    instance.download_filter = "id > 5"

    instance.update_config()

    assert not (tmp_path / "d").exists()
    assert "id > 5" in (tmp_path / "bot.yaml").read_text(encoding="utf-8")


def test_add_filter_survives_a_config_round_trip(tmp_path, monkeypatch):
    """/add_filter 设置的过滤器必须能存盘并在重启后读回。

    回归场景：handler 把值写进 _bot.app.down —— 全库无任何其他引用的黑洞属性，
    用户却收到"设置成功"回复，过滤器实际从未生效也从未持久化。
    """
    monkeypatch.chdir(tmp_path)
    instance = bot.DownloadBot()
    instance.config_path = str(tmp_path / "bot.yaml")
    # 生产环境里 app 已挂载，这里补上以便复现"静默写进黑洞"而不是 AttributeError
    instance.app = SimpleNamespace()

    replies = []

    class FakeClient:
        async def send_message(self, user_id, text):
            replies.append(text)

    message = SimpleNamespace(
        text="/add_filter id > 5",
        from_user=SimpleNamespace(id=1),
    )

    monkeypatch.setattr(bot, "_bot", instance)
    asyncio.run(bot.add_filter(FakeClient(), message))
    instance.update_config()

    # 模拟重启：新实例从同一份配置文件加载
    restarted = bot.DownloadBot()
    restarted.config_path = instance.config_path
    with open(restarted.config_path, encoding="utf-8") as handle:
        restarted.assign_config(restarted._yaml.load(handle.read()))

    assert replies == ["Add download filter : id > 5"]
    assert restarted.download_filter == "id > 5"

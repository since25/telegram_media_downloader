"""Contracts for the management Bot command surface."""

from pathlib import Path

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

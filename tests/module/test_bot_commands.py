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

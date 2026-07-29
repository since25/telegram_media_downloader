"""Contracts for the management Bot command surface."""

from module import bot


def test_admin_command_menu_excludes_legacy_forward():
    names = [command.command for command in bot.build_admin_bot_commands()]

    assert "forward" not in names
    assert "listen_forward" in names


def test_admin_help_excludes_legacy_forward():
    help_text = bot.build_admin_help_text()

    assert "/forward -" not in help_text
    assert "/listen_forward -" in help_text

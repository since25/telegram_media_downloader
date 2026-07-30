from pathlib import Path


def test_mutable_state_path_resolvers_honor_environment(monkeypatch, tmp_path):
    from module import bot, download_entry, task_state, web

    expected = {
        "TMD_TASK_DB_PATH": tmp_path / "web_tasks.sqlite3",
        "TMD_CHANNEL_LIBRARY_DB_PATH": tmp_path / "channel_library.sqlite3",
        "TMD_RESOURCE_BOT_DB_PATH": tmp_path / "resource_bot.sqlite3",
        "TMD_WEB_AUTH_FILE": tmp_path / ".web_auth.json",
    }
    for name, path in expected.items():
        monkeypatch.setenv(name, str(path))

    assert task_state._default_storage_path() == expected["TMD_TASK_DB_PATH"]
    assert (
        download_entry.channel_library_db_path()
        == expected["TMD_CHANNEL_LIBRARY_DB_PATH"]
    )
    assert bot.resource_bot_db_path() == expected["TMD_RESOURCE_BOT_DB_PATH"]
    assert web._web_auth_file_path() == expected["TMD_WEB_AUTH_FILE"]


def test_channel_library_path_defaults_to_runtime_directory(monkeypatch, tmp_path):
    from module import download_entry

    monkeypatch.delenv("TMD_CHANNEL_LIBRARY_DB_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    assert download_entry.channel_library_db_path() == Path(
        tmp_path / "channel_library.sqlite3"
    )

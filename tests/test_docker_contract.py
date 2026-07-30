from pathlib import Path

from ruamel.yaml import YAML


ROOT = Path(__file__).resolve().parents[1]


def _compose_service():
    compose = YAML(typ="safe").load(
        (ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    )
    return compose["services"]["telegram_media_downloader"]


def test_compose_persists_all_mutable_application_state():
    service = _compose_service()
    environment = service.get("environment") or {}
    volumes = service.get("volumes") or []

    assert environment["TMD_TASK_DB_PATH"] == "/app/state/web_tasks.sqlite3"
    assert (
        environment["TMD_CHANNEL_LIBRARY_DB_PATH"]
        == "/app/state/channel_library.sqlite3"
    )
    assert (
        environment["TMD_RESOURCE_BOT_DB_PATH"]
        == "/app/state/resource_bot.sqlite3"
    )
    assert environment["TMD_WEB_AUTH_FILE"] == "/app/state/.web_auth.json"
    assert "./state/:/app/state/" in volumes

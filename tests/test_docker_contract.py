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
    assert environment["TMD_RESOURCE_BOT_DB_PATH"] == "/app/state/resource_bot.sqlite3"
    assert environment["TMD_WEB_AUTH_FILE"] == "/app/state/.web_auth.json"
    assert "./state/:/app/state/" in volumes


def test_runtime_image_uses_only_the_local_compile_stage():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "COPY --from=compile-image /usr/bin/rclone" in dockerfile
    assert (
        "COPY --from=compile-image /usr/local/lib/python3.11/site-packages"
        in dockerfile
    )
    assert "telegram_media_downloader_compile:latest" not in dockerfile
    assert "COPY config.yaml data.yaml" not in dockerfile
    assert "config.example.yaml" in dockerfile
    assert "data.example.yaml" in dockerfile


def test_docker_build_context_excludes_runtime_state_and_secrets():
    ignored = {
        line.strip()
        for line in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }

    required = {
        ".git",
        ".env*",
        "config.yaml",
        "data.yaml",
        "sessions/",
        "state/",
        "downloads/",
        "log/",
        "temp/",
        "*.session",
        "*.sqlite3",
        ".web_auth.json",
    }
    assert required <= ignored


def test_docker_publish_builds_runtime_directly_from_checkout():
    workflow = (ROOT / ".github/workflows/docker-publish.yml").read_text(
        encoding="utf-8"
    )

    assert "telegram_media_downloader_compile" not in workflow
    assert "target: compile-image" not in workflow
    assert workflow.count("uses: docker/build-push-action@") == 1
    assert "target: runtime-image" in workflow

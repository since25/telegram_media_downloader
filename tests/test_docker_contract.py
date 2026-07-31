import re
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

    assert (
        "COPY --from=compile-image --chown=app:app "
        "/usr/bin/rclone /app/rclone/rclone" in dockerfile
    )
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
        "rclone/",
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


def test_container_health_checks_do_not_require_the_optional_web_listener():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    service = _compose_service()
    healthcheck = service.get("healthcheck") or {}
    compose_command = " ".join(str(part) for part in healthcheck.get("test") or [])

    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["python", "-m", "module.runtime_health"]' in dockerfile
    assert "python -m module.runtime_health" in compose_command
    assert "TMD_RUNTIME_HEALTH_PATH=/app/state/runtime-health.json" in dockerfile
    assert "http://127.0.0.1:5000/healthz" not in dockerfile
    assert "http://127.0.0.1:5000/healthz" not in compose_command


def test_runtime_base_and_apk_inputs_are_immutably_pinned():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    base_lines = [
        line for line in dockerfile.splitlines() if line.startswith("FROM python:")
    ]

    assert len(base_lines) == 2
    assert all(
        line.startswith(
            "FROM python:3.11.9-alpine@"
            "sha256:f9ce6fe33d9a5499e35c976df16d24ae80f6ef0a28be5433140236c2ca482686"
        )
        for line in base_lines
    )
    assert "gcc=13.2.1_git20240309-r1" in dockerfile
    assert "musl-dev=1.2.5-r3" in dockerfile
    assert "rclone=1.66.0-r5" in dockerfile
    assert not re.search(r"apk add[^\\n]*\\brclone(?:\\s|$)", dockerfile)


def test_runtime_user_and_writable_mount_migration_are_explicit():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    service = _compose_service()
    environment = service.get("environment") or {}
    volumes = service.get("volumes") or []
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    readme_cn = (ROOT / "README_CN.md").read_text(encoding="utf-8")

    assert "USER app:app" in dockerfile
    assert "10001" in dockerfile
    assert service["user"] == "${TMD_UID:-10001}:${TMD_GID:-10001}"
    assert environment["TMD_CONFIG_PATH"] == "/app/state/config.yaml"
    assert environment["TMD_DATA_PATH"] == "/app/state/data.yaml"
    assert "./config.yaml:/app/config.yaml" not in volumes
    assert "./data.yaml:/app/data.yaml" not in volumes
    assert "./rclone/:/home/app/.config/rclone/" in volumes
    assert all("$HOME/.config/rclone" not in volume for volume in volumes)

    for document in (readme, readme_cn):
        assert "TMD_UID" in document
        assert "TMD_GID" in document
        assert "TMD_RUNTIME_HEALTH_PATH" in document
        assert "state/config.yaml" in document
        assert "state/data.yaml" in document
        assert "chown -R" in document
        assert "runtime-health.json" in document

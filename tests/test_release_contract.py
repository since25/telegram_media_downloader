import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parents[1]


def _workflow():
    return YAML(typ="safe").load(
        (ROOT / ".github/workflows/docker-publish.yml").read_text(encoding="utf-8")
    )


def test_docker_publication_depends_on_complete_verification():
    workflow = _workflow()
    verify = workflow["jobs"]["verify"]
    publish = workflow["jobs"]["build-and-push"]

    assert publish["needs"] == "verify"
    verification_commands = "\n".join(
        str(step.get("run", "")) for step in verify["steps"] if isinstance(step, dict)
    )
    for required_command in (
        "python -m pytest -q",
        "python check_imports.py",
        "python -m compileall -q module tests",
        "python -m pip check",
        "make style_check PYTHON=python",
        "docker compose -f docker-compose.yaml config",
    ):
        assert required_command in verification_commands


def test_docker_publication_supports_controlled_manual_dispatch():
    triggers = _workflow()["on"]

    assert "push" in triggers
    assert "workflow_dispatch" in triggers


def test_docker_publication_uses_commit_addressable_and_guarded_latest_tags():
    publish = _workflow()["jobs"]["build-and-push"]
    metadata_step = next(
        step
        for step in publish["steps"]
        if step.get("uses") == "docker/metadata-action@v5"
    )
    build_step = next(
        step
        for step in publish["steps"]
        if step.get("uses") == "docker/build-push-action@v6"
    )
    tags = metadata_step["with"]["tags"]

    assert "type=sha,format=long,prefix=sha-" in tags
    assert "type=raw,value=latest,enable={{is_default_branch}}" in tags
    assert "type=ref,event=tag" in tags
    assert build_step["with"]["tags"] == "${{ steps.meta.outputs.tags }}"


def test_built_wheel_contains_runtime_packages_and_web_assets(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    shutil.copy2(ROOT / "setup.py", source / "setup.py")
    shutil.copy2(ROOT / "media_downloader.py", source / "media_downloader.py")
    shutil.copytree(ROOT / "module", source / "module")
    shutil.copytree(ROOT / "utils", source / "utils")
    dist = tmp_path / "dist"

    subprocess.run(
        [
            sys.executable,
            "setup.py",
            "bdist_wheel",
            "--dist-dir",
            str(dist),
        ],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )

    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1
    with ZipFile(wheels[0]) as wheel:
        names = set(wheel.namelist())

    required_files = {
        "media_downloader.py",
        "module/__init__.py",
        "module/download_entry.py",
        "module/runtime_health.py",
        "module/templates/index.html",
        "module/templates/login.html",
        "module/static/css/index.css",
        "module/static/request/index.js",
        "module/static/layui/layui.js",
        "utils/__init__.py",
        "utils/format.py",
    }
    assert required_files <= names

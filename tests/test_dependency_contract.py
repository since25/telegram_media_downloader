import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_pyrogram_dependency_uses_immutable_commit_and_hash():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pyrogram_lines = [
        line.strip()
        for line in requirements.splitlines()
        if "github.com/tangyoha/pyrogram/archive/" in line and not line.startswith("#")
    ]

    assert len(pyrogram_lines) == 1
    dependency = pyrogram_lines[0]
    assert "/refs/heads/" not in dependency
    assert re.search(r"/archive/[0-9a-f]{40}\.zip", dependency)
    assert re.search(r"#sha256=[0-9a-f]{64}$", dependency)


def test_every_installed_python_requirement_is_version_or_hash_pinned():
    active_requirements = [
        line.strip()
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    for requirement in active_requirements:
        if requirement.startswith("https://"):
            assert re.search(r"#sha256=[0-9a-f]{64}$", requirement)
        else:
            assert re.fullmatch(r"[A-Za-z0-9_.-]+==[^=<>!~]+", requirement)


def test_mcp_adapter_requirements_are_version_pinned():
    lines = [
        line.strip()
        for line in (ROOT / "mcp-requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert lines
    for requirement in lines:
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[^=<>!~]+", requirement)

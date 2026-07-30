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

import os
from pathlib import Path

import pytest

from module.config_persistence import atomic_write_yaml


def test_serialization_failure_leaves_previous_file_unchanged(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text("previous: true\n", encoding="utf-8")

    def failing_writer(_value, handle):
        handle.write("partial:")
        raise ValueError("serialization failed")

    with pytest.raises(ValueError, match="serialization failed"):
        atomic_write_yaml(target, {"next": True}, failing_writer)

    assert target.read_text(encoding="utf-8") == "previous: true\n"
    assert list(tmp_path.glob(".config.yaml.*.tmp")) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX file modes are required")
def test_atomic_write_uses_owner_only_file_mode(tmp_path):
    target = Path(tmp_path) / "config.yaml"

    atomic_write_yaml(
        target,
        {"value": 1},
        lambda _value, handle: handle.write("value: 1\n"),
    )

    assert target.read_text(encoding="utf-8") == "value: 1\n"
    assert target.stat().st_mode & 0o777 == 0o600

"""Atomic persistence helpers for application YAML state."""

import os
import tempfile
from pathlib import Path
from typing import Any, Callable, TextIO

YamlWriter = Callable[[Any, TextIO], Any]


def atomic_write_yaml(path: Path, value: Any, yaml_writer: YamlWriter) -> None:
    """Serialize YAML to an owner-only temporary file and atomically replace."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml_writer(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        if os.name == "posix":
            os.chmod(target, 0o600)
            directory = os.open(target.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise

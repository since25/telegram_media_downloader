"""Atomic persistence helpers for application YAML state."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Callable, TextIO

YamlWriter = Callable[[Any, TextIO], Any]


def _sync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


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
            _sync_directory(target.parent)
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


def _pair_journal_path(first_path: Path, second_path: Path) -> Path:
    first = Path(first_path).resolve()
    second = Path(second_path).resolve()
    identity = hashlib.sha256(f"{first}\0{second}".encode("utf-8")).hexdigest()[:16]
    return first.parent / f".{first.name}.{identity}.pair.journal"


def _serialize_yaml_stage(
    path: Path,
    value: Any,
    yaml_writer: YamlWriter,
) -> tuple[Path, str]:
    target = Path(path).resolve()
    descriptor, stage_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".stage",
        dir=target.parent,
        text=True,
    )
    stage_path = Path(stage_name)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml_writer(value, handle)
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(target.parent)
        return stage_path, hashlib.sha256(stage_path.read_bytes()).hexdigest()
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            stage_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_pair_journal(path: Path, journal: dict) -> None:
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
        text=True,
    )
    temp_path = Path(temp_name)
    try:
        if os.name == "posix":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(journal, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        if os.name == "posix":
            os.chmod(path, 0o600)
        _sync_directory(path.parent)
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


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _replace_pair_entry(entry: dict) -> None:
    target = Path(entry["target"])
    staged = Path(entry["staged"])
    expected_hash = entry["sha256"]
    if staged.exists():
        if _file_sha256(staged) != expected_hash:
            raise RuntimeError("configuration pair staged file hash mismatch")
        os.replace(staged, target)
        if os.name == "posix":
            os.chmod(target, 0o600)
        _sync_directory(target.parent)
        return
    if not target.exists() or _file_sha256(target) != expected_hash:
        raise RuntimeError("configuration pair recovery state is inconsistent")
    if os.name == "posix":
        os.chmod(target, 0o600)


def recover_yaml_pair(first_path: Path, second_path: Path) -> bool:
    """Finish an interrupted paired YAML commit, if one is journaled."""

    targets = (Path(first_path).resolve(), Path(second_path).resolve())
    journal_path = _pair_journal_path(*targets)
    if not journal_path.exists():
        return False
    try:
        journal = json.loads(journal_path.read_text(encoding="utf-8"))
        entries = journal["entries"]
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("configuration pair journal is invalid") from error
    if journal.get("version") != 1 or not isinstance(entries, list):
        raise RuntimeError("configuration pair journal is invalid")
    if [entry.get("target") for entry in entries] != [
        str(target) for target in targets
    ]:
        raise RuntimeError("configuration pair journal targets do not match")
    for entry, target in zip(entries, targets):
        staged = Path(entry.get("staged", ""))
        if (
            staged.parent != target.parent
            or not staged.name.startswith(f".{target.name}.")
            or not staged.name.endswith(".stage")
            or not isinstance(entry.get("sha256"), str)
        ):
            raise RuntimeError("configuration pair journal is invalid")
        _replace_pair_entry(entry)
    journal_path.unlink()
    _sync_directory(journal_path.parent)
    return True


def atomic_write_yaml_pair(
    first_path: Path,
    first_value: Any,
    second_path: Path,
    second_value: Any,
    yaml_writer: YamlWriter,
) -> None:
    """Commit two YAML files as one recoverable generation."""

    targets = (Path(first_path).resolve(), Path(second_path).resolve())
    for target in targets:
        target.parent.mkdir(parents=True, exist_ok=True)
    recover_yaml_pair(*targets)

    staged_entries = []
    journal_path = _pair_journal_path(*targets)
    journal_committed = False
    try:
        for target, value in zip(targets, (first_value, second_value)):
            staged, digest = _serialize_yaml_stage(target, value, yaml_writer)
            staged_entries.append(
                {
                    "target": str(target),
                    "staged": str(staged),
                    "sha256": digest,
                }
            )
        _write_pair_journal(
            journal_path,
            {
                "version": 1,
                "entries": staged_entries,
            },
        )
        journal_committed = True
        for entry in staged_entries:
            _replace_pair_entry(entry)
        journal_path.unlink()
        _sync_directory(journal_path.parent)
    except Exception:
        if not journal_committed:
            for entry in staged_entries:
                try:
                    Path(entry["staged"]).unlink()
                except FileNotFoundError:
                    pass
        raise

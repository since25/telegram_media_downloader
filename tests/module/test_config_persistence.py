import json
import os
from pathlib import Path
from unittest import mock

import pytest

import module.config_persistence as config_persistence
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


def test_interrupted_pair_commit_is_recovered_deterministically(tmp_path):
    config_path = tmp_path / "config.yaml"
    data_path = tmp_path / "data.yaml"
    config_path.write_text("generation: 1\n", encoding="utf-8")
    data_path.write_text("generation: 1\n", encoding="utf-8")
    original_replace = os.replace
    committed_targets = []

    def interrupt_second_target(source, destination):
        destination = Path(destination)
        if destination in {config_path, data_path}:
            committed_targets.append(destination)
            if destination == data_path:
                raise RuntimeError("simulated interruption")
        return original_replace(source, destination)

    writer = lambda value, handle: handle.write(  # noqa: E731
        f"generation: {value['generation']}\n"
    )
    with mock.patch(
        "module.config_persistence.os.replace",
        side_effect=interrupt_second_target,
    ):
        with pytest.raises(RuntimeError, match="simulated interruption"):
            config_persistence.atomic_write_yaml_pair(
                config_path,
                {"generation": 2},
                data_path,
                {"generation": 2},
                writer,
            )

    assert committed_targets == [config_path, data_path]
    assert config_path.read_text(encoding="utf-8") == "generation: 2\n"
    assert data_path.read_text(encoding="utf-8") == "generation: 1\n"
    assert len(list(tmp_path.glob(".*.journal"))) == 1

    config_persistence.recover_yaml_pair(config_path, data_path)

    assert config_path.read_text(encoding="utf-8") == "generation: 2\n"
    assert data_path.read_text(encoding="utf-8") == "generation: 2\n"
    assert list(tmp_path.glob(".*.journal")) == []
    assert list(tmp_path.glob(".*.stage")) == []


def test_pair_serialization_failure_leaves_both_generations_unchanged(tmp_path):
    config_path = tmp_path / "config.yaml"
    data_path = tmp_path / "data.yaml"
    config_path.write_text("generation: 1\n", encoding="utf-8")
    data_path.write_text("generation: 1\n", encoding="utf-8")

    def fail_second_value(value, handle):
        handle.write(f"generation: {value['generation']}\n")
        if value["generation"] == 3:
            raise ValueError("second serialization failed")

    with pytest.raises(ValueError, match="second serialization failed"):
        config_persistence.atomic_write_yaml_pair(
            config_path,
            {"generation": 2},
            data_path,
            {"generation": 3},
            fail_second_value,
        )

    assert config_path.read_text(encoding="utf-8") == "generation: 1\n"
    assert data_path.read_text(encoding="utf-8") == "generation: 1\n"
    assert list(tmp_path.glob(".*.journal")) == []
    assert list(tmp_path.glob(".*.stage")) == []


def test_pair_recovery_rejects_missing_stage_and_mismatched_target(tmp_path):
    config_path = tmp_path / "config.yaml"
    data_path = tmp_path / "data.yaml"
    config_path.write_text("generation: 1\n", encoding="utf-8")
    data_path.write_text("generation: 1\n", encoding="utf-8")
    original_replace = os.replace

    def interrupt_second_target(source, destination):
        if Path(destination) == data_path:
            raise RuntimeError("simulated interruption")
        return original_replace(source, destination)

    with mock.patch(
        "module.config_persistence.os.replace",
        side_effect=interrupt_second_target,
    ):
        with pytest.raises(RuntimeError, match="simulated interruption"):
            config_persistence.atomic_write_yaml_pair(
                config_path,
                {"generation": 2},
                data_path,
                {"generation": 2},
                lambda value, handle: handle.write(
                    f"generation: {value['generation']}\n"
                ),
            )

    journal_path = next(tmp_path.glob(".*.journal"))
    journal = json.loads(journal_path.read_text(encoding="utf-8"))
    Path(journal["entries"][1]["staged"]).unlink()

    with pytest.raises(RuntimeError, match="recovery state is inconsistent"):
        config_persistence.recover_yaml_pair(config_path, data_path)

    assert data_path.read_text(encoding="utf-8") == "generation: 1\n"
    assert journal_path.exists()

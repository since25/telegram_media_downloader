from module.runtime_health import RuntimeHealth, RuntimePhase, health_file_is_ready


def test_runtime_health_transitions_control_persisted_readiness(tmp_path):
    path = tmp_path / "runtime-health.json"
    health = RuntimeHealth(path)

    health.mark_starting()
    assert health.phase is RuntimePhase.STARTING
    assert health.is_ready is False
    assert health_file_is_ready(path) is False

    health.mark_ready()
    assert health.phase is RuntimePhase.READY
    assert health.is_ready is True
    assert health_file_is_ready(path) is True

    health.mark_stopping()
    assert health.phase is RuntimePhase.STOPPING
    assert health.is_ready is False
    assert health_file_is_ready(path) is False

    health.mark_failed()
    assert health.phase is RuntimePhase.FAILED
    assert health.is_ready is False
    assert health_file_is_ready(path) is False

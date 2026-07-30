import json
import os

import pytest

from module.web_auth import LoginAttemptLimiter, WebAuthState


def test_plaintext_auth_file_migrates_to_password_verifier(tmp_path):
    auth_path = tmp_path / ".web_auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "username": "root",
                "password": "existing-password",
                "password_source": "local",
                "session_secret": "session-secret",
            }
        ),
        encoding="utf-8",
    )
    if os.name == "posix":
        os.chmod(auth_path, 0o644)

    state = WebAuthState.load_or_create(auth_path, "")
    persisted = json.loads(auth_path.read_text(encoding="utf-8"))

    assert state.verify_password("existing-password")
    assert not state.verify_password("wrong-password")
    assert "password" not in persisted
    assert persisted["password_hash"]
    assert "existing-password" not in auth_path.read_text(encoding="utf-8")
    if os.name == "posix":
        assert auth_path.stat().st_mode & 0o777 == 0o600


def test_generated_bootstrap_password_is_removed_after_first_login(tmp_path):
    auth_path = tmp_path / ".web_auth.json"

    state = WebAuthState.load_or_create(auth_path, "")
    persisted = json.loads(auth_path.read_text(encoding="utf-8"))
    bootstrap_password = persisted["bootstrap_password"]

    assert state.verify_password(bootstrap_password)
    assert state.consume_bootstrap_password()
    migrated = json.loads(auth_path.read_text(encoding="utf-8"))
    assert "bootstrap_password" not in migrated
    assert state.verify_password(bootstrap_password)
    assert not state.consume_bootstrap_password()


def test_configured_password_is_never_persisted_in_plaintext(tmp_path):
    auth_path = tmp_path / ".web_auth.json"

    state = WebAuthState.load_or_create(auth_path, "configured-secret")
    payload = auth_path.read_text(encoding="utf-8")

    assert state.verify_password("configured-secret")
    assert not state.verify_password("wrong")
    assert "configured-secret" not in payload
    assert "bootstrap_password" not in json.loads(payload)


def test_invalid_auth_path_parent_is_reported(tmp_path):
    auth_path = tmp_path / "parent-file" / ".web_auth.json"
    auth_path.parent.write_text("not a directory", encoding="utf-8")

    with pytest.raises(OSError):
        WebAuthState.load_or_create(auth_path, "secret")


def test_login_attempt_limiter_blocks_fifth_failure_and_expires():
    now = [100.0]
    limiter = LoginAttemptLimiter(
        max_failures=5,
        window_seconds=300,
        retry_delay_seconds=60,
        clock=lambda: now[0],
    )

    for _ in range(4):
        assert limiter.record_failure("127.0.0.1") == 0
    assert limiter.record_failure("127.0.0.1") == 60
    assert limiter.retry_after("127.0.0.1") == 60

    now[0] += 61
    assert limiter.retry_after("127.0.0.1") == 0


def test_login_attempt_limiter_success_resets_failures():
    limiter = LoginAttemptLimiter(max_failures=2)

    assert limiter.record_failure("client") == 0
    limiter.record_success("client")
    assert limiter.record_failure("client") == 0

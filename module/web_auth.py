"""Local Web authentication verifier and bootstrap lifecycle."""

import json
import os
import secrets
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from math import ceil
from pathlib import Path
from typing import Any, Callable

from werkzeug.security import check_password_hash, generate_password_hash


class LoginAttemptLimiter:
    """Bound repeated password failures per client without credential disclosure."""

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: int = 300,
        retry_delay_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.max_failures = max(int(max_failures), 1)
        self.window_seconds = max(int(window_seconds), 1)
        self.retry_delay_seconds = max(int(retry_delay_seconds), 1)
        self.clock = clock
        self._failures: dict[str, deque[float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.RLock()

    def _prune(self, key: str, now: float) -> deque[float]:
        failures = self._failures.setdefault(key, deque())
        cutoff = now - self.window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        return failures

    def retry_after(self, client_key: str) -> int:
        key = str(client_key or "unknown")
        with self._lock:
            now = self.clock()
            blocked_until = self._blocked_until.get(key, 0.0)
            if blocked_until <= now:
                self._blocked_until.pop(key, None)
                return 0
            return max(int(ceil(blocked_until - now)), 1)

    def record_failure(self, client_key: str) -> int:
        key = str(client_key or "unknown")
        with self._lock:
            retry_after = self.retry_after(key)
            if retry_after:
                return retry_after
            now = self.clock()
            failures = self._prune(key, now)
            failures.append(now)
            if len(failures) < self.max_failures:
                return 0
            self._blocked_until[key] = now + self.retry_delay_seconds
            return self.retry_delay_seconds

    def record_success(self, client_key: str) -> None:
        key = str(client_key or "unknown")
        with self._lock:
            self._failures.pop(key, None)
            self._blocked_until.pop(key, None)


def _load_auth_payload(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as auth_file:
            payload = json.load(auth_file)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _atomic_write_auth_payload(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        with os.fdopen(descriptor, "w", encoding="utf-8") as auth_file:
            json.dump(payload, auth_file, ensure_ascii=False, indent=2)
            auth_file.write("\n")
            auth_file.flush()
            os.fsync(auth_file.fileno())
        os.replace(temp_path, path)
        if os.name == "posix":
            os.chmod(path, 0o600)
            directory = os.open(path.parent, os.O_RDONLY)
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


def _password_matches(password_hash: str, candidate: str) -> bool:
    try:
        return bool(password_hash) and check_password_hash(password_hash, candidate)
    except (TypeError, ValueError):
        return False


@dataclass
class WebAuthState:
    """Password verifier and session secret for one local Web installation."""

    path: Path
    username: str
    password_hash: str
    session_secret: str
    password_source: str
    _payload: dict[str, Any] = field(repr=False)
    _lock: threading.RLock = field(
        default_factory=threading.RLock,
        repr=False,
    )

    @classmethod
    def load_or_create(
        cls,
        path: Path,
        configured_password: str,
    ) -> "WebAuthState":
        auth_path = Path(path)
        payload = _load_auth_payload(auth_path)
        configured = str(configured_password or "")
        plaintext = str(payload.pop("password", "") or "")
        password_hash = str(payload.get("password_hash") or "")
        bootstrap_password = str(payload.get("bootstrap_password") or "")

        if configured:
            if not _password_matches(password_hash, configured):
                password_hash = generate_password_hash(configured)
            payload.pop("bootstrap_password", None)
            password_source = "config.web_login_secret"
        elif plaintext:
            password_hash = generate_password_hash(plaintext)
            payload.pop("bootstrap_password", None)
            password_source = str(payload.get("password_source") or "local")
        elif password_hash:
            password_source = str(payload.get("password_source") or "local")
        else:
            bootstrap_password = secrets.token_urlsafe(18)
            password_hash = generate_password_hash(bootstrap_password)
            payload["bootstrap_password"] = bootstrap_password
            password_source = "local"

        session_secret = str(payload.get("session_secret") or "")
        if not session_secret:
            session_secret = secrets.token_urlsafe(32)

        payload.update(
            {
                "username": "root",
                "password_hash": password_hash,
                "password_source": password_source,
                "session_secret": session_secret,
            }
        )
        _atomic_write_auth_payload(auth_path, payload)
        return cls(
            path=auth_path,
            username="root",
            password_hash=password_hash,
            session_secret=session_secret,
            password_source=password_source,
            _payload=payload,
        )

    @property
    def has_bootstrap_password(self) -> bool:
        return bool(self._payload.get("bootstrap_password"))

    def verify_password(self, candidate: str) -> bool:
        return _password_matches(self.password_hash, str(candidate or ""))

    def consume_bootstrap_password(self) -> bool:
        with self._lock:
            if "bootstrap_password" not in self._payload:
                return False
            self._payload.pop("bootstrap_password", None)
            _atomic_write_auth_payload(self.path, self._payload)
            return True

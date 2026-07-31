"""Process readiness state shared by Web and container health probes."""

import json
import os
import tempfile
import threading
import time
from enum import Enum
from pathlib import Path
from typing import Optional

RUNTIME_HEALTH_PATH_ENV = "TMD_RUNTIME_HEALTH_PATH"


class RuntimePhase(str, Enum):
    """Externally meaningful process lifecycle phases."""

    STARTING = "starting"
    READY = "ready"
    STOPPING = "stopping"
    FAILED = "failed"


def _process_start_token(pid: int) -> Optional[str]:
    """Return the Linux process start tick used to reject stale PID markers."""

    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    closing_paren = stat.rfind(")")
    if closing_paren < 0:
        return None
    fields_after_name = stat[closing_paren + 2 :].split()
    if len(fields_after_name) <= 19:
        return None
    return fields_after_name[19]


class RuntimeHealth:
    """Own in-memory readiness and an optional atomic health marker."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else None
        self._phase = RuntimePhase.STARTING
        self._lock = threading.RLock()
        self._pid = os.getpid()
        self._process_start_token = _process_start_token(self._pid)

    @classmethod
    def from_environment(cls) -> "RuntimeHealth":
        """Build a health owner without writing until lifecycle startup."""

        configured_path = os.environ.get(RUNTIME_HEALTH_PATH_ENV)
        return cls(Path(configured_path) if configured_path else None)

    @property
    def phase(self) -> RuntimePhase:
        with self._lock:
            return self._phase

    @property
    def is_ready(self) -> bool:
        with self._lock:
            return self._phase is RuntimePhase.READY

    def mark_starting(self) -> None:
        self._set_phase(RuntimePhase.STARTING)

    def mark_ready(self) -> None:
        self._set_phase(RuntimePhase.READY)

    def mark_stopping(self) -> None:
        self._set_phase(RuntimePhase.STOPPING)

    def mark_failed(self) -> None:
        self._set_phase(RuntimePhase.FAILED)

    def _set_phase(self, phase: RuntimePhase) -> None:
        with self._lock:
            self._phase = phase
            if self._path is not None:
                self._persist()

    def _persist(self) -> None:
        assert self._path is not None
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": self._phase.value,
            "pid": self._pid,
            "process_start_token": self._process_start_token,
            "updated_at": time.time(),
        }
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self._path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def health_file_is_ready(path: Path) -> bool:
    """Return whether a marker belongs to the live ready application process."""

    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        pid = int(payload["pid"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return False

    if payload.get("status") != RuntimePhase.READY.value or pid <= 0:
        return False

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass

    recorded_start = payload.get("process_start_token")
    if recorded_start is not None:
        current_start = _process_start_token(pid)
        if current_start is None or current_start != recorded_start:
            return False
    return True


def main() -> int:
    """Exit successfully only when the configured runtime marker is ready."""

    configured_path = os.environ.get(RUNTIME_HEALTH_PATH_ENV)
    if not configured_path:
        return 1
    return 0 if health_file_is_ready(Path(configured_path)) else 1


if __name__ == "__main__":
    raise SystemExit(main())

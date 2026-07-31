"""Explicit construction and lazy compatibility access for process resources."""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Callable

from module.app import Application

ApplicationFactory = Callable[[str, str, str], Application]
QueueFactory = Callable[[], Any]


@dataclass(frozen=True)
class ApplicationBootstrap:
    """Resources owned by one downloader process."""

    application: Application
    download_queue: asyncio.Queue[Any]


def create_application(
    config_path: str,
    data_path: str,
    application_name: str,
    *,
    application_factory: ApplicationFactory = Application,
) -> Application:
    """Construct one application only when a caller explicitly requests it."""

    return application_factory(config_path, data_path, application_name)


class RuntimeBootstrap:
    """Create the application and queue together at the process boundary."""

    def __init__(
        self,
        config_path: str,
        data_path: str,
        application_name: str,
        *,
        application_factory: ApplicationFactory = Application,
        queue_factory: QueueFactory = asyncio.Queue,
    ) -> None:
        self._config_path = config_path
        self._data_path = data_path
        self._application_name = application_name
        self._application_factory = application_factory
        self._queue_factory = queue_factory
        self._state: ApplicationBootstrap | None = None
        self._lock = threading.RLock()

    @property
    def initialized(self) -> bool:
        """Return whether process resources have been constructed."""

        with self._lock:
            return self._state is not None

    def create_application(self) -> Application:
        """Construct an independent application without installing it globally."""

        return create_application(
            self._config_path,
            self._data_path,
            self._application_name,
            application_factory=self._application_factory,
        )

    def initialize(self) -> ApplicationBootstrap:
        """Construct and retain process resources exactly once."""

        with self._lock:
            if self._state is not None:
                return self._state

            application = self.create_application()
            try:
                download_queue = self._queue_factory()
            except BaseException:
                application.close_runtime_resources()
                raise
            self._state = ApplicationBootstrap(application, download_queue)
            return self._state


class LazyApplication:
    """Compatibility proxy that defers construction until first real use."""

    def __init__(self, bootstrap: RuntimeBootstrap) -> None:
        object.__setattr__(self, "_bootstrap", bootstrap)
        object.__setattr__(self, "_delegated_originals", {})

    def __getattr__(self, name: str) -> Any:
        application = self._bootstrap.initialize().application
        return getattr(application, name)

    def __setattr__(self, name: str, value: Any) -> None:
        application = self._bootstrap.initialize().application
        if hasattr(application, name):
            self._delegated_originals.setdefault(name, []).append(
                getattr(application, name)
            )
        setattr(application, name, value)

    def __delattr__(self, name: str) -> None:
        application = self._bootstrap.initialize().application
        originals = self._delegated_originals.get(name)
        if originals:
            setattr(application, name, originals.pop())
            if not originals:
                self._delegated_originals.pop(name, None)
            return
        delattr(application, name)


class LazyDownloadQueue:
    """Compatibility proxy sharing the explicitly bootstrapped process queue."""

    def __init__(self, bootstrap: RuntimeBootstrap) -> None:
        object.__setattr__(self, "_bootstrap", bootstrap)

    def __getattr__(self, name: str) -> Any:
        download_queue = self._bootstrap.initialize().download_queue
        return getattr(download_queue, name)

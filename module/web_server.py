"""Owned lifecycle for the local Werkzeug Web server."""

import threading
from typing import Any, Callable, Optional

from werkzeug.serving import make_server


class WebServer:
    """Start and stop one Werkzeug server and its owned thread."""

    def __init__(
        self,
        application,
        host: str,
        port: int,
        *,
        server_factory: Callable[..., Any] = make_server,
    ):
        self._application = application
        self._host = str(host)
        self._port = int(port)
        self._server_factory = server_factory
        self._server: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

    @property
    def bound_port(self) -> int:
        """Return the configured or currently bound TCP port."""

        with self._lock:
            if self._server is None:
                return self._port
            return int(self._server.server_port)

    @property
    def is_running(self) -> bool:
        """Return whether the owned server thread is alive."""

        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        """Bind synchronously so startup failures reach the caller."""

        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            server = self._server_factory(
                self._host,
                self._port,
                self._application,
                threaded=True,
            )
            thread = threading.Thread(
                target=server.serve_forever,
                name="telegram-media-downloader-web",
            )
            self._server = server
            self._thread = thread
            thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        """Shut down the server and join its owned thread."""

        with self._lock:
            server = self._server
            thread = self._thread
        if server is None or thread is None:
            return

        server.shutdown()
        thread.join(timeout=max(float(timeout), 0.0))
        if thread.is_alive():
            raise TimeoutError("Web server thread did not stop before timeout")
        server.server_close()

        with self._lock:
            if self._server is server:
                self._server = None
            if self._thread is thread:
                self._thread = None

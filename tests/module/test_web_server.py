import socket
from urllib.request import urlopen

import pytest
from flask import Flask

from module.web_server import WebServer


def _test_app():
    app = Flask(__name__)

    @app.get("/ready")
    def ready():
        return "ready"

    return app


def test_web_server_start_serves_bound_application():
    server = WebServer(_test_app(), "127.0.0.1", 0)
    try:
        server.start()
        with urlopen(
            f"http://127.0.0.1:{server.bound_port}/ready",
            timeout=2,
        ) as response:
            assert response.status == 200
            assert response.read() == b"ready"
        assert server.is_running
    finally:
        server.stop(timeout=2)


def test_web_server_stop_joins_owned_thread():
    server = WebServer(_test_app(), "127.0.0.1", 0)
    server.start()

    server.stop(timeout=2)

    assert not server.is_running


def test_web_server_start_reports_port_conflict():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    port = listener.getsockname()[1]
    server = WebServer(_test_app(), "127.0.0.1", port)
    try:
        with pytest.raises(OSError):
            server.start()
    finally:
        listener.close()
        server.stop(timeout=2)


def test_web_server_double_stop_is_idempotent():
    server = WebServer(_test_app(), "127.0.0.1", 0)
    server.start()

    server.stop(timeout=2)
    server.stop(timeout=2)

    assert not server.is_running

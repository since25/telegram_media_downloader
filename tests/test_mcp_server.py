"""Contract tests for the MCP stdio adapter that runs beside Hermes."""

import json

import pytest

import mcp_server


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.response


def test_client_sends_bearer_credentials():
    session = FakeSession(FakeResponse(200, {"items": []}))
    client = mcp_server.DownloaderClient(
        "https://example.invalid", "secret", session=session
    )

    client.search_packages(q="python")

    _method, url, kwargs = session.calls[0]
    assert url == "https://example.invalid/api/mcp/packages"
    assert kwargs["headers"]["Authorization"] == "Bearer secret"
    assert kwargs["params"] == {"q": "python"}


def test_client_maps_error_status_to_tool_error():
    session = FakeSession(
        FakeResponse(409, {"error_code": "state_conflict", "message": "no"})
    )
    client = mcp_server.DownloaderClient(
        "https://example.invalid", "secret", session=session
    )

    with pytest.raises(mcp_server.ToolError) as error:
        client.search_packages()

    assert error.value.error_code == "state_conflict"


def test_client_maps_transport_failure_to_service_unavailable():
    class BrokenSession:
        def request(self, *args, **kwargs):
            raise OSError("connection refused")

    client = mcp_server.DownloaderClient(
        "https://example.invalid", "secret", session=BrokenSession()
    )

    with pytest.raises(mcp_server.ToolError) as error:
        client.get_system_status()

    assert error.value.error_code == "service_unavailable"


def test_tool_definitions_are_complete_and_unique():
    names = [tool["name"] for tool in mcp_server.TOOL_DEFINITIONS]

    assert names == sorted(set(names))
    assert set(names) == {
        "get_download_task",
        "get_resource_package",
        "get_system_status",
        "list_download_tasks",
        "search_resource_packages",
        "submit_download",
    }
    for tool in mcp_server.TOOL_DEFINITIONS:
        assert tool["description"]
        assert tool["inputSchema"]["type"] == "object"
        json.dumps(tool["inputSchema"])


def test_submit_download_tool_requires_an_idempotency_key():
    tool = next(
        item
        for item in mcp_server.TOOL_DEFINITIONS
        if item["name"] == "submit_download"
    )

    assert set(tool["inputSchema"]["required"]) == {"package_ids", "idempotency_key"}


def test_adapter_logs_to_stderr_only():
    source = mcp_server.__file__

    with open(source, encoding="utf-8") as handle:
        text = handle.read()

    assert "print(" not in text
    assert "stream=sys.stderr" in text

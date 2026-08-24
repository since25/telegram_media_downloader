"""MCP stdio adapter for the Telegram Media Downloader control interface.

Runs beside Hermes, not on the downloader host. It only translates MCP tool
calls into authenticated HTTP calls; it never touches SQLite or Pyrogram.
"""

import logging
import os
import sys


logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("tmd-mcp")

BASE_URL_ENVIRONMENT_VARIABLE = "TMD_MCP_BASE_URL"
API_KEY_ENVIRONMENT_VARIABLE = "TMD_MCP_API_KEY"
DEFAULT_BASE_URL = "https://tgdn.wyichuan.cc"
REQUEST_TIMEOUT_SECONDS = 20


class ToolError(Exception):
    """One control-interface failure carried back to the MCP client."""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = str(error_code)
        self.message = str(message)


class DownloaderClient:
    """Authenticated HTTP client for the downloader control interface."""

    def __init__(self, base_url: str, api_key: str, session=None):
        self.base_url = str(base_url).rstrip("/")
        self.api_key = str(api_key)
        if session is None:
            import requests

            session = requests.Session()
        self.session = session

    def _call(self, method: str, path: str, *, params=None, json_body=None):
        url = f"{self.base_url}{path}"
        try:
            response = self.session.request(
                method,
                url,
                params=params,
                json=json_body,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except Exception as error:
            logger.warning("MCP control call failed: %s", type(error).__name__)
            raise ToolError(
                "service_unavailable",
                "The downloader control interface is unreachable",
            ) from error
        if response.status_code >= 400:
            payload = {}
            try:
                payload = response.json()
            except Exception:
                payload = {}
            raise ToolError(
                str(payload.get("error_code") or "service_unavailable"),
                str(
                    payload.get("message") or "The control interface returned an error"
                ),
            )
        try:
            return response.json()
        except Exception as error:
            logger.warning(
                "MCP control returned invalid JSON: %s", type(error).__name__
            )
            raise ToolError(
                "service_unavailable",
                "The control interface returned invalid JSON",
            ) from error

    def search_packages(self, **params):
        return self._call("GET", "/api/mcp/packages", params=params or None)

    def get_package(self, package_id: int, **params):
        return self._call(
            "GET", f"/api/mcp/packages/{int(package_id)}", params=params or None
        )

    def get_system_status(self):
        return self._call("GET", "/api/mcp/system")

    def list_tasks(self, **params):
        return self._call("GET", "/api/mcp/tasks", params=params or None)

    def get_task(self, task_id: str):
        return self._call("GET", f"/api/mcp/tasks/{task_id}")

    def submit_download(self, package_ids, idempotency_key: str, redownload=False):
        return self._call(
            "POST",
            "/api/mcp/downloads",
            json_body={
                "package_ids": [int(value) for value in package_ids],
                "idempotency_key": str(idempotency_key),
                "redownload": bool(redownload),
            },
        )

    def pause_downloads(self):
        return self._call("POST", "/api/mcp/downloads/pause")

    def resume_downloads(self):
        return self._call("POST", "/api/mcp/downloads/resume")

    def cancel_download_task(self, task_id: str):
        return self._call("POST", f"/api/mcp/tasks/{task_id}/cancel")

    def list_keyword_monitors(self):
        return self._call("GET", "/api/mcp/keyword-monitors")

    def get_keyword_monitor(self, group_id: int):
        return self._call("GET", f"/api/mcp/keyword-monitors/{int(group_id)}")

    def create_keyword_monitor(
        self,
        name: str,
        enabled=True,
        required_keywords=None,
        match_keywords=None,
        blacklist_keywords=None,
    ):
        return self._call(
            "POST",
            "/api/mcp/keyword-monitors",
            json_body={
                "name": str(name),
                "enabled": bool(enabled),
                "required_keywords": list(required_keywords or []),
                "match_keywords": list(match_keywords or []),
                "blacklist_keywords": list(blacklist_keywords or []),
            },
        )

    def update_keyword_monitor(self, group_id: int, **payload):
        return self._call(
            "PUT",
            f"/api/mcp/keyword-monitors/{int(group_id)}",
            json_body=dict(payload),
        )

    def delete_keyword_monitor(self, group_id: int):
        return self._call("DELETE", f"/api/mcp/keyword-monitors/{int(group_id)}")

    def get_keyword_monitor_history(self, group_id: int, **params):
        return self._call(
            "GET",
            f"/api/mcp/keyword-monitors/{int(group_id)}/history",
            params=params or None,
        )

    def retry_keyword_monitor_failures(self, group_id: int):
        return self._call(
            "POST",
            f"/api/mcp/keyword-monitors/{int(group_id)}/retry-failures",
        )


TOOL_DEFINITIONS = [
    {
        "name": "cancel_download_task",
        "description": "Cancel one download task through the downloader owner loop.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "create_keyword_monitor",
        "description": "Create a keyword monitor and immediately match current stable packages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "enabled": {"type": "boolean"},
                "required_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "match_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "blacklist_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["name", "match_keywords"],
        },
    },
    {
        "name": "delete_keyword_monitor",
        "description": "Delete a keyword monitor without deleting its download history.",
        "inputSchema": {
            "type": "object",
            "properties": {"group_id": {"type": "integer"}},
            "required": ["group_id"],
        },
    },
    {
        "name": "get_download_task",
        "description": "Read one download task by its string task id.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
        },
    },
    {
        "name": "get_keyword_monitor",
        "description": "Read one keyword monitor configuration and progress summary.",
        "inputSchema": {
            "type": "object",
            "properties": {"group_id": {"type": "integer"}},
            "required": ["group_id"],
        },
    },
    {
        "name": "get_keyword_monitor_history",
        "description": "Read paginated keyword-monitor matches and download progress.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "cursor": {"type": "string"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["group_id"],
        },
    },
    {
        "name": "get_resource_package",
        "description": "Read one indexed resource package and a page of its media items.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_id": {"type": "integer"},
                "cursor": {"type": "string"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "required": ["package_id"],
        },
    },
    {
        "name": "get_system_status",
        "description": "Read downloader health, pause state, throughput, disk, and task counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_download_tasks",
        "description": "List recent download tasks only. History is bounded and not time-searchable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 200},
            },
        },
    },
    {
        "name": "list_keyword_monitors",
        "description": "List keyword monitors with enabled counts and trigger summaries.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pause_downloads",
        "description": "Set the global download state to paused idempotently.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "resume_downloads",
        "description": "Set the global download state to downloading idempotently.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "retry_keyword_monitor_failures",
        "description": "Retry recoverable download failures for one keyword monitor.",
        "inputSchema": {
            "type": "object",
            "properties": {"group_id": {"type": "integer"}},
            "required": ["group_id"],
        },
    },
    {
        "name": "search_resource_packages",
        "description": (
            "Search indexed resource packages. Results include boundary_status and "
            "downloadable; only downloadable packages can be submitted."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string"},
                "library_ids": {"type": "string"},
                "download_status": {"type": "string"},
                "date_from": {"type": "string"},
                "date_to": {"type": "string"},
                "cursor": {"type": "string"},
                "page_size": {"type": "integer", "minimum": 1, "maximum": 200},
            },
        },
    },
    {
        "name": "submit_download",
        "description": (
            "Submit exactly these packages for download. Repeating the same "
            "idempotency_key returns the existing batches instead of new ones."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "package_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 1,
                },
                "idempotency_key": {"type": "string", "maxLength": 160},
                "redownload": {"type": "boolean"},
            },
            "required": ["package_ids", "idempotency_key"],
        },
    },
    {
        "name": "update_keyword_monitor",
        "description": "Replace one keyword monitor and immediately match current stable packages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "group_id": {"type": "integer"},
                "name": {"type": "string"},
                "enabled": {"type": "boolean"},
                "required_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "match_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                },
                "blacklist_keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            "required": ["group_id", "name", "match_keywords"],
        },
    },
]


def build_client() -> DownloaderClient:
    """Build one client from the environment without any auto discovery."""

    api_key = str(os.environ.get(API_KEY_ENVIRONMENT_VARIABLE, "")).strip()
    if not api_key:
        raise SystemExit(f"{API_KEY_ENVIRONMENT_VARIABLE} is required")
    base_url = str(
        os.environ.get(BASE_URL_ENVIRONMENT_VARIABLE, DEFAULT_BASE_URL)
    ).strip()
    return DownloaderClient(base_url, api_key)


def dispatch(client: DownloaderClient, name: str, arguments: dict):
    """Route one tool call onto the control client."""

    arguments = dict(arguments or {})
    if name == "cancel_download_task":
        return client.cancel_download_task(str(arguments["task_id"]))
    if name == "create_keyword_monitor":
        return client.create_keyword_monitor(**arguments)
    if name == "delete_keyword_monitor":
        return client.delete_keyword_monitor(arguments["group_id"])
    if name == "search_resource_packages":
        return client.search_packages(**arguments)
    if name == "get_resource_package":
        return client.get_package(arguments.pop("package_id"), **arguments)
    if name == "get_system_status":
        return client.get_system_status()
    if name == "list_download_tasks":
        return client.list_tasks(**arguments)
    if name == "list_keyword_monitors":
        return client.list_keyword_monitors()
    if name == "pause_downloads":
        return client.pause_downloads()
    if name == "retry_keyword_monitor_failures":
        return client.retry_keyword_monitor_failures(arguments["group_id"])
    if name == "resume_downloads":
        return client.resume_downloads()
    if name == "get_download_task":
        return client.get_task(str(arguments["task_id"]))
    if name == "get_keyword_monitor":
        return client.get_keyword_monitor(arguments["group_id"])
    if name == "get_keyword_monitor_history":
        group_id = arguments.pop("group_id")
        return client.get_keyword_monitor_history(group_id, **arguments)
    if name == "submit_download":
        return client.submit_download(
            arguments["package_ids"],
            arguments["idempotency_key"],
            redownload=bool(arguments.get("redownload", False)),
        )
    if name == "update_keyword_monitor":
        group_id = arguments.pop("group_id")
        return client.update_keyword_monitor(group_id, **arguments)
    raise ToolError("not_found", f"Unknown tool {name}")


def main() -> int:
    """Serve the MCP stdio protocol; the SDK is imported only here."""

    import asyncio
    import json

    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    client = build_client()

    async def list_tools(_context, _params):
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name=tool["name"],
                    description=tool["description"],
                    inputSchema=tool["inputSchema"],
                )
                for tool in TOOL_DEFINITIONS
            ]
        )

    async def call_tool(_context, params):
        try:
            result = await asyncio.to_thread(
                dispatch, client, params.name, params.arguments or {}
            )
        except ToolError as error:
            payload = {"error_code": error.error_code, "message": error.message}
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=json.dumps(payload))],
                isError=True,
            )
        return types.CallToolResult(
            content=[
                types.TextContent(
                    type="text", text=json.dumps(result, ensure_ascii=False)
                )
            ]
        )

    server = Server(
        "telegram-media-downloader",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )

    async def serve():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    asyncio.run(serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

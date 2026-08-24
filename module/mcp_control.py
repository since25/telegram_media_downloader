"""Bearer-authenticated control routes for the MCP adapter."""

import logging
from functools import wraps

from flask import Blueprint, jsonify, request

from module.mcp_auth import load_mcp_api_key, verify_mcp_api_key
from module.web_auth import LoginAttemptLimiter


logger = logging.getLogger(__name__)

mcp_blueprint = Blueprint("mcp", __name__, url_prefix="/api/mcp")

_current_app = None
_limiter = LoginAttemptLimiter()


class McpError(Exception):
    """One MCP control failure with a stable error code."""

    def __init__(self, status: int, error_code: str, message: str):
        super().__init__(message)
        self.status = int(status)
        self.error_code = str(error_code)
        self.message = str(message)


def reset_mcp_limiter_for_tests() -> None:
    """Give one test an unpolluted failure limiter."""

    global _limiter
    _limiter = LoginAttemptLimiter()


def _client_key() -> str:
    return str(request.remote_addr or "unknown")


def _bearer_token() -> str:
    header = str(request.headers.get("Authorization", ""))
    if not header.startswith("Bearer "):
        return ""
    return header[len("Bearer ") :].strip()


def _authenticate() -> None:
    client_key = _client_key()
    retry_after = _limiter.retry_after(client_key)
    if retry_after:
        raise McpError(429, "rate_limited", "Too many failed attempts")
    expected = load_mcp_api_key(getattr(_current_app, "config_file", ""))
    if not verify_mcp_api_key(expected, _bearer_token()):
        delay = _limiter.record_failure(client_key)
        logger.warning("MCP authentication failed from %s", client_key)
        if delay:
            raise McpError(429, "rate_limited", "Too many failed attempts")
        raise McpError(401, "unauthorized", "A valid API key is required")
    _limiter.record_success(client_key)


def mcp_route(function):
    """Authenticate, rate limit, and map failures onto one JSON contract."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        try:
            _authenticate()
            return function(*args, **kwargs)
        except McpError as error:
            payload = {"error_code": error.error_code, "message": error.message}
            if error.status == 429:
                payload["retry_after"] = _limiter.retry_after(_client_key()) or 1
            return jsonify(payload), error.status
        except KeyError:
            return (
                jsonify(
                    {"error_code": "not_found", "message": "The object does not exist"}
                ),
                404,
            )
        except Exception as error:
            from module.web import _ChannelApiError

            if isinstance(error, _ChannelApiError):
                return (
                    jsonify(
                        {
                            "error_code": error.error_code,
                            "message": error.message,
                        }
                    ),
                    error.status,
                )
            logger.exception("MCP control operation failed")
            return (
                jsonify(
                    {
                        "error_code": "service_unavailable",
                        "message": "The downloader service is unavailable",
                    }
                ),
                503,
            )

    return wrapped


@mcp_blueprint.route("/ping")
@mcp_route
def ping():
    """Confirm credentials and reachability without touching the runtime."""

    return jsonify({"ok": True})


def register_mcp_blueprint(flask_app, app) -> bool:
    """Register MCP routes only when the feature is enabled."""

    global _current_app
    if not bool(getattr(app, "mcp_enabled", False)):
        return False
    _current_app = app
    if "mcp" not in flask_app.blueprints:
        flask_app.register_blueprint(mcp_blueprint)
    return True


MCP_FILTER_FIELDS = frozenset(
    {
        "q",
        "date_from",
        "date_to",
        "download_status",
        "message_id_min",
        "message_id_max",
        "media_count_min",
        "media_count_max",
        "size_min",
        "size_max",
        "include_unknown_size",
        "library_ids",
        "cursor",
        "page_size",
    }
)


def _service():
    service = getattr(_current_app, "channel_library_service", None)
    if service is None:
        raise McpError(
            503, "service_unavailable", "Channel library service is unavailable"
        )
    return service


def _invalid(message: str) -> None:
    raise McpError(400, "invalid_request", message)


def _package_view(package: dict) -> dict:
    view = dict(package)
    view["downloadable"] = view.get("boundary_status") == "stable"
    return view


@mcp_blueprint.route("/packages")
@mcp_route
def search_packages():
    """Return the same package set the browser sees, plus a downloadable flag."""

    from module.web import _filter_from_mapping, _library_ids_from_query, _page_inputs

    unknown = set(request.args) - MCP_FILTER_FIELDS
    if unknown:
        _invalid("Request contains unsupported query parameters")
    cursor, page_size = _page_inputs()
    page = _service().store.list_packages_aggregate(
        _library_ids_from_query(),
        _filter_from_mapping(
            request.args, query=True, extra_fields=frozenset({"library_ids"})
        ),
        cursor=cursor,
        limit=page_size,
    )
    return jsonify(
        {
            "items": [_package_view(item) for item in page.items],
            "next_cursor": page.next_cursor,
        }
    )


@mcp_blueprint.route("/packages/<int:package_id>")
@mcp_route
def package_detail(package_id: int):
    """Return one package with a bounded page of its media items."""

    from module.web import _page_inputs

    cursor, page_size = _page_inputs()
    store = _service().store
    package = store.get_package(package_id)
    if package is None:
        raise KeyError(f"Channel package {package_id} does not exist")
    page = store.list_package_items_aggregate(
        package_id, cursor=cursor, limit=page_size
    )
    return jsonify(
        {
            "package": _package_view(package),
            "items": page.items,
            "next_cursor": page.next_cursor,
        }
    )


@mcp_blueprint.route("/system")
@mcp_route
def system_status():
    """Return runtime health, pause state, throughput, disk, and task counts."""

    import shutil

    from module.download_stat import get_download_state, get_total_download_speed
    from module.task_state import get_task_store

    health = getattr(_current_app, "runtime_health", None)
    save_path = getattr(_current_app, "save_path", None) or "/"
    try:
        usage = shutil.disk_usage(save_path)
    except OSError:
        usage = shutil.disk_usage("/")
    dashboard = get_task_store().dashboard(limit=0)
    return jsonify(
        {
            "phase": health.phase.value if health is not None else "unknown",
            "download_state": get_download_state().name,
            "download_speed_bytes": get_total_download_speed(),
            "disk_free": int(usage.free),
            "disk_total": int(usage.total),
            "active_task_count": dashboard["active_task_count"],
            "completed_task_count": dashboard["completed_task_count"],
        }
    )


@mcp_blueprint.route("/tasks")
@mcp_route
def list_tasks():
    """Return a bounded page of recent tasks, optionally filtered by status."""

    from module.task_state import get_task_store

    unknown = set(request.args) - {"status", "limit"}
    if unknown:
        _invalid("Request contains unsupported query parameters")
    raw_limit = request.args.get("limit", "50")
    if not raw_limit.isascii() or not raw_limit.isdecimal():
        _invalid("limit must be a positive integer")
    limit = min(max(int(raw_limit), 1), 200)
    status = request.args.get("status")
    store = get_task_store()
    items = store.serialize_tasks(
        hide_file_name=bool(getattr(_current_app, "hide_file_name", False)),
        limit=limit if status is None else None,
    )
    if status is not None:
        items = [item for item in items if item.get("status") == status][:limit]
    dashboard = store.dashboard(limit=0)
    return jsonify(
        {
            "items": items,
            "counts": {
                "active": dashboard["active_task_count"],
                "completed": dashboard["completed_task_count"],
            },
        }
    )


@mcp_blueprint.route("/tasks/<task_id>")
@mcp_route
def task_detail(task_id: str):
    """Return one task by its string task id, plus its batch header if any."""

    from module.task_state import get_task_store

    task = get_task_store().get_task(task_id)
    if task is None:
        raise KeyError(f"Task {task_id} does not exist")
    service = getattr(_current_app, "channel_library_service", None)
    batch = (
        service.store.get_download_batch_header_by_task_id(task_id)
        if service is not None
        else None
    )
    return jsonify(
        {
            "task": task.to_dict(
                hide_file_name=bool(getattr(_current_app, "hide_file_name", False)),
                include_files=False,
            ),
            "batch": batch,
        }
    )


@mcp_blueprint.route("/downloads", methods=["POST"])
@mcp_route
def submit_download():
    """Create batches for exactly the requested packages."""

    from module.channel_library_store import RedownloadRequiredError

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        _invalid("A JSON object is required")
    if set(payload) - {"package_ids", "idempotency_key", "redownload"}:
        _invalid("Request contains unsupported fields")
    package_ids = payload.get("package_ids")
    if not isinstance(package_ids, list) or not package_ids:
        _invalid("package_ids must be a non-empty array")
    if any(type(value) is not int or value < 1 for value in package_ids):
        _invalid("package_ids must contain positive integers")
    idempotency_key = payload.get("idempotency_key")
    if not isinstance(idempotency_key, str) or not idempotency_key.strip():
        _invalid("idempotency_key is required")
    redownload = payload.get("redownload", False)
    if type(redownload) is not bool:
        _invalid("redownload must be a boolean")

    service = _service()
    try:
        results = service.create_download_batches_for_packages(
            package_ids, idempotency_key, redownload=redownload
        )
    except RedownloadRequiredError:
        raise McpError(
            409,
            "redownload_required",
            "The request requires explicit redownload confirmation",
        )
    except ValueError as error:
        raise McpError(409, "state_conflict", str(error))

    any_created = False
    batches = []
    for batch, created in results:
        any_created = any_created or created
        try:
            service.schedule_download_batch_threadsafe(int(batch["id"]))
        except RuntimeError:
            raise McpError(
                503,
                "service_unavailable",
                "Batches were persisted and resume when the service returns",
            )
        batches.append(
            {
                "id": batch["id"],
                "task_id": batch["task_id"],
                "status": batch["status"],
                "package_count": len(batch.get("packages", [])),
                "created": created,
            }
        )
    return jsonify({"batches": batches, "created": any_created}), (
        202 if any_created else 200
    )

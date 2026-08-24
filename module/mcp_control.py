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


def _set_download_state(target):
    """Set the global download state explicitly on the owner loop."""

    from module.download_stat import get_download_state, set_download_state
    from module.web_commands import (
        WebCommandTimeout,
        submit_web_coroutine,
        wait_for_web_command,
    )

    async def apply():
        set_download_state(target)
        return get_download_state().name

    try:
        return wait_for_web_command(
            submit_web_coroutine(getattr(_current_app, "loop", None), apply()),
            timeout=1,
        )
    except WebCommandTimeout as error:
        raise McpError(
            503, "service_unavailable", "The state change timed out"
        ) from error
    except RuntimeError as error:
        raise McpError(
            503, "service_unavailable", "The owner loop is unavailable"
        ) from error


@mcp_blueprint.route("/downloads/pause", methods=["POST"])
@mcp_route
def pause_downloads():
    """Pause downloads idempotently; a second call keeps the paused state."""

    from module.download_stat import DownloadState

    return jsonify({"download_state": _set_download_state(DownloadState.StopDownload)})


@mcp_blueprint.route("/downloads/resume", methods=["POST"])
@mcp_route
def resume_downloads():
    """Resume downloads idempotently."""

    from module.download_stat import DownloadState

    return jsonify({"download_state": _set_download_state(DownloadState.Downloading)})


@mcp_blueprint.route("/tasks/<task_id>/cancel", methods=["POST"])
@mcp_route
def cancel_task(task_id: str):
    """Cancel through the same owner-loop path the browser console uses."""

    from module import web

    payload, status = web._cancel_task_payload(task_id)
    if status == 404:
        raise KeyError(f"Task {task_id} does not exist")
    if status == 409:
        raise McpError(
            409,
            str(payload.get("error_code") or "state_conflict"),
            str(payload.get("error") or "The task cannot be cancelled"),
        )
    if status >= 400:
        raise McpError(
            503, "service_unavailable", "The downloader service is unavailable"
        )
    return jsonify(payload)


def _monitor_payload():
    from module.web import _keyword_list

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        _invalid("A JSON object is required")
    allowed = {
        "name",
        "enabled",
        "required_keywords",
        "match_keywords",
        "blacklist_keywords",
    }
    if set(payload) - allowed:
        _invalid("Request contains unsupported fields")
    name = payload.get("name")
    enabled = payload.get("enabled", True)
    if not isinstance(name, str) or not name.strip():
        _invalid("name must be a non-empty string")
    if type(enabled) is not bool:
        _invalid("enabled must be a boolean")
    return {
        "name": name,
        "enabled": enabled,
        "required_keywords": _keyword_list(payload, "required_keywords"),
        "match_keywords": _keyword_list(payload, "match_keywords"),
        "blacklist_keywords": _keyword_list(payload, "blacklist_keywords"),
    }


def _save_monitor(group_id=None):
    service = _service()
    try:
        group = service.store.save_keyword_monitor_group(
            group_id=group_id, **_monitor_payload()
        )
    except ValueError as error:
        _invalid(str(error))
    service.trigger_keyword_monitors()
    return group


@mcp_blueprint.route("/keyword-monitors")
@mcp_route
def list_keyword_monitors():
    """List every monitor group with its trigger summary."""

    groups = _service().store.list_keyword_monitor_groups()
    return jsonify(
        {
            "items": groups,
            "total": len(groups),
            "enabled": sum(1 for group in groups if group["enabled"]),
            "disabled": sum(1 for group in groups if not group["enabled"]),
        }
    )


@mcp_blueprint.route("/keyword-monitors", methods=["POST"])
@mcp_route
def create_keyword_monitor():
    """Create one monitor group and match current packages immediately."""

    return jsonify({"group": _save_monitor()}), 201


@mcp_blueprint.route("/keyword-monitors/<int:group_id>")
@mcp_route
def get_keyword_monitor(group_id: int):
    """Read one monitor group with its current progress summary."""

    group = _service().store.get_keyword_monitor_group(group_id)
    if group is None:
        raise KeyError(f"Monitor group {group_id} does not exist")
    return jsonify({"group": group})


@mcp_blueprint.route("/keyword-monitors/<int:group_id>", methods=["PUT"])
@mcp_route
def update_keyword_monitor(group_id: int):
    """Replace one monitor group and match current packages immediately."""

    if _service().store.get_keyword_monitor_group(group_id) is None:
        raise KeyError(f"Monitor group {group_id} does not exist")
    return jsonify({"group": _save_monitor(group_id)})


@mcp_blueprint.route("/keyword-monitors/<int:group_id>", methods=["DELETE"])
@mcp_route
def delete_keyword_monitor(group_id: int):
    """Delete one monitor group without touching its download history."""

    if not _service().store.delete_keyword_monitor_group(group_id):
        raise KeyError(f"Monitor group {group_id} does not exist")
    return jsonify({"deleted": True, "group_id": group_id})


@mcp_blueprint.route("/keyword-monitors/<int:group_id>/history")
@mcp_route
def keyword_monitor_history(group_id: int):
    """Return one page of matched packages with their task progress."""

    from module.web import _page_inputs

    cursor, page_size = _page_inputs()
    service = _service()
    try:
        page = service.store.list_keyword_monitor_history(
            group_id, cursor=cursor, limit=page_size
        )
    except (TypeError, ValueError) as error:
        raise McpError(400, "invalid_request", "Invalid history pagination") from error
    items = []
    for value in page.items:
        item = dict(value)
        task = service.task_store.get_task(item["task_id"])
        if task is not None:
            snapshot = task.to_dict()
            item["progress"] = {
                key: snapshot[key]
                for key in (
                    "status",
                    "total_count",
                    "success_count",
                    "failed_count",
                    "skipped_count",
                    "upload_success_count",
                    "updated_at",
                )
            }
        else:
            item["progress"] = None
        items.append(item)
    return jsonify(
        {
            "items": items,
            "next_cursor": page.next_cursor,
            "summary": service.store.get_keyword_monitor_summary(group_id),
        }
    )


@mcp_blueprint.route(
    "/keyword-monitors/<int:group_id>/retry-failures", methods=["POST"]
)
@mcp_route
def retry_keyword_monitor_failures(group_id: int):
    """Requeue recoverable failures through the owner loop."""

    from module.web_commands import WebCommandTimeout, wait_for_web_command

    service = _service()
    try:
        result = wait_for_web_command(
            service.retry_keyword_monitor_failures_threadsafe(group_id), timeout=5
        )
    except WebCommandTimeout as error:
        raise McpError(
            503, "service_unavailable", "Retry scheduling timed out"
        ) from error
    except RuntimeError as error:
        raise McpError(
            503, "service_unavailable", "Channel service is unavailable"
        ) from error
    if result["scheduled_count"] <= 0:
        raise McpError(409, "state_conflict", "No recoverable failures are available")
    return jsonify({"ok": True, **result}), 202

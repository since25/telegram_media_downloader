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
        except Exception:
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

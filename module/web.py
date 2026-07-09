"""web ui for media download"""

import hmac
import json
import logging
import os
import secrets
import threading
from pathlib import Path
from typing import Any, Optional

from flask import Flask, jsonify, render_template, request
from flask_login import LoginManager, UserMixin, login_required, login_user, logout_user

import utils
from module.app import Application
from module.download_stat import (
    DownloadState,
    get_download_result,
    get_download_state,
    get_total_download_speed,
    set_download_state,
)
from module.task_state import get_task_store
from utils.crypto import AesBase64
from utils.format import format_byte

log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)
logger = logging.getLogger(__name__)

_flask_app = Flask(__name__)

_flask_app.secret_key = "tdl"
_flask_app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
_login_manager = LoginManager()
_login_manager.login_view = "login"
_login_manager.init_app(_flask_app)
web_login_users: dict = {}
_current_app: Optional[Application] = None
deAesCrypt = AesBase64("1234123412ABCDEF", "ABCDEF1234123412")
WEB_AUTH_FILE_ENV = "TMD_WEB_AUTH_FILE"
WEB_AUTH_FILE_NAME = ".web_auth.json"
SUPPORTED_MEDIA_TYPES = ["audio", "photo", "video", "document", "voice", "video_note"]
PATH_PREFIX_OPTIONS = ["chat_title", "media_datetime", "media_type"]
NAME_PREFIX_OPTIONS = ["message_id", "file_name", "caption"]
FILE_FORMAT_TYPES = ["audio", "document", "video"]


class User(UserMixin):
    """Web Login User"""

    def __init__(self):
        self.sid = "root"

    @property
    def id(self):
        """ID"""
        return self.sid


@_login_manager.user_loader
def load_user(_):
    """
    Load a user object from the user ID.

    Returns:
        User: The user object.
    """
    return User()


def get_flask_app() -> Flask:
    """get flask app instance"""
    return _flask_app


def run_web_server(app: Application):
    """
    Runs a web server using the Flask framework.
    """

    get_flask_app().run(
        app.web_host, app.web_port, debug=app.debug_web, use_reloader=False
    )


def _web_auth_file_path() -> Path:
    """Return the local auth file path."""

    configured_path = os.environ.get(WEB_AUTH_FILE_ENV)
    if configured_path:
        return Path(configured_path)
    return Path(os.path.abspath(".")) / WEB_AUTH_FILE_NAME


def _load_json_file(path: Path) -> dict:
    """Load a JSON object, returning an empty dict on missing or invalid files."""

    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as auth_file:
            data = json.load(auth_file)
            return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as error:
        logger.warning("failed to load web auth file %s: %s", path, error)
        return {}


def _write_local_auth_file(path: Path, data: dict) -> None:
    """Persist local web auth state with owner-only permissions."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    file_descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    with os.fdopen(file_descriptor, "w", encoding="utf-8") as auth_file:
        auth_file.write(payload)
        auth_file.write("\n")


def _ensure_web_auth(app: Application) -> None:
    """Enable login with config secret or a generated local password."""

    global web_login_users

    auth_file_path = _web_auth_file_path()
    auth_data = _load_json_file(auth_file_path)
    password = str(app.web_login_secret or auth_data.get("password") or "")
    auth_changed = False
    if not password:
        password = secrets.token_urlsafe(18)
        auth_data["password"] = password
        auth_changed = True

    session_secret = str(auth_data.get("session_secret") or "")
    if not session_secret:
        session_secret = secrets.token_urlsafe(32)
        auth_data["session_secret"] = session_secret
        auth_changed = True

    auth_data["username"] = "root"
    if app.web_login_secret:
        auth_data["password_source"] = "config.web_login_secret"
    else:
        auth_data["password_source"] = "local"

    if auth_changed:
        _write_local_auth_file(auth_file_path, auth_data)
        logger.warning("web auth initialized at %s", auth_file_path)

    _flask_app.secret_key = session_secret
    _flask_app.config["LOGIN_DISABLED"] = False
    web_login_users = {"root": password}


# pylint: disable = W0603
def init_web(app: Application):
    """
    Set the value of the users variable.

    Args:
        users: The list of users to set.

    Returns:
        None.
    """
    global _current_app
    _current_app = app
    _ensure_web_auth(app)
    if app.debug_web:
        threading.Thread(target=run_web_server, args=(app,)).start()
    else:
        threading.Thread(
            target=get_flask_app().run, daemon=True, args=(app.web_host, app.web_port)
        ).start()


@_flask_app.route("/login", methods=["GET", "POST"])
def login():
    """
    Function to handle the login route.

    Parameters:
    - No parameters

    Returns:
    - If the request method is "POST" and the username and
      password match the ones in the web_login_users dictionary,
      it returns a JSON response with a code of "1".
    - Otherwise, it returns a JSON response with a code of "0".
    - If the request method is not "POST", it returns the rendered "login.html" template.
    """
    if request.method == "POST":
        username = "root"
        web_login_form = {}
        for key, value in request.form.items():
            if value:
                try:
                    value = deAesCrypt.decrypt(value)
                except Exception:
                    return jsonify({"code": "0"})
            web_login_form[key] = value

        if not web_login_form.get("password"):
            return jsonify({"code": "0"})

        password = web_login_form["password"]
        if username in web_login_users and hmac.compare_digest(
            web_login_users[username], password
        ):
            user = User()
            login_user(user)
            return jsonify({"code": "1"})

        return jsonify({"code": "0"})

    return render_template("login.html")


@_flask_app.route("/logout", methods=["POST"])
@login_required
def logout():
    """Log out current web user."""

    logout_user()
    return jsonify({"code": "1"})


@_flask_app.route("/")
@login_required
def index():
    """Index html"""
    return render_template(
        "index.html",
        download_state=(
            "pause" if get_download_state() is DownloadState.Downloading else "continue"
        ),
    )


@_flask_app.route("/get_download_status")
@login_required
def get_download_speed():
    """Get download speed"""
    return jsonify(
        {
            "download_speed": format_byte(get_total_download_speed()) + "/s",
            "upload_speed": "0.00 B/s",
        }
    )


@_flask_app.route("/set_download_state", methods=["POST"])
@login_required
def web_set_download_state():
    """Set download state"""
    state = request.args.get("state")

    if state == "continue" and get_download_state() is DownloadState.StopDownload:
        set_download_state(DownloadState.Downloading)
        return "pause"

    if state == "pause" and get_download_state() is DownloadState.Downloading:
        set_download_state(DownloadState.StopDownload)
        return "continue"

    return state


@_flask_app.route("/get_app_version")
@login_required
def get_app_version():
    """Get telegram_media_downloader version"""
    return utils.__version__


@_flask_app.route("/get_download_list")
@login_required
def get_download_list():
    """get download list"""
    if request.args.get("already_down") is None:
        return "[]"

    already_down = request.args.get("already_down") == "true"

    result = []
    for chat_id, messages in download_result.items():
        for idx, value in messages.items():
            is_already_down = value["down_byte"] == value["total_size"]

            if already_down and not is_already_down:
                continue

            download_speed = format_byte(value["download_speed"]) + "/s"
            total_size = value["total_size"] or 1
            result.append(
                {
                    "chat": f"{chat_id}",
                    "id": f"{idx}",
                    "filename": os.path.basename(value["file_name"]),
                    "total_size": format_byte(value["total_size"]),
                    "download_progress": round(
                        value["down_byte"] / total_size * 100, 1
                    ),
                    "download_speed": download_speed,
                    "save_path": value["file_name"].replace("\\", "/"),
                }
            )

    return jsonify(result)


def _task_dashboard_payload(app: Optional[Application] = None) -> dict:
    """Build the Web task dashboard payload."""

    hide_file_name = bool(getattr(app, "hide_file_name", False)) if app else False
    payload = get_task_store().dashboard(hide_file_name=hide_file_name)
    payload.update(
        {
            "download_state": get_download_state().name,
            "download_speed": format_byte(get_total_download_speed()) + "/s",
            "download_speed_bytes": get_total_download_speed(),
        }
    )
    return payload


@_flask_app.route("/api/task-dashboard")
@login_required
def task_dashboard():
    """Return task dashboard summary for the Web UI."""

    app = _active_app()
    return jsonify(_task_dashboard_payload(app))


@_flask_app.route("/api/tasks")
@login_required
def task_list():
    """Return task summaries for the Web UI."""

    app = _active_app()
    return jsonify(
        get_task_store().serialize_tasks(
            hide_file_name=bool(getattr(app, "hide_file_name", False))
        )
    )


@_flask_app.route("/api/tasks/<task_id>")
@login_required
def task_detail(task_id: str):
    """Return one task with file details."""

    app = _active_app()
    task = get_task_store().get_task(task_id)
    if not task:
        return jsonify({"error": "task not found"}), 404
    return jsonify(
        task.to_dict(
            hide_file_name=bool(getattr(app, "hide_file_name", False)),
            include_files=True,
        )
    )


def _active_app() -> Application:
    """Return the web-bound application or fail with a JSON-friendly error."""

    if _current_app is None:
        raise RuntimeError("web application is not initialized")
    return _current_app


def _as_bool(value: Any, default: bool = False) -> bool:
    """Parse a web boolean value."""

    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return default


def _as_positive_int(value: Any, default: int, minimum: int = 1, maximum: int = 10000):
    """Parse a bounded positive integer."""

    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed_value, minimum), maximum)


def _as_string_list(
    value: Any, allowed_values: Optional[list[str]] = None
) -> list[str]:
    """Normalize comma-separated or JSON-list string input."""

    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = []

    normalized = []
    for item in items:
        if not item:
            continue
        if allowed_values and item not in allowed_values:
            continue
        if item not in normalized:
            normalized.append(item)
    return normalized


def _settings_from_app(app: Application) -> dict:
    """Serialize advanced download settings for the web UI."""

    return {
        "save_path": app.save_path,
        "media_types": list(app.media_types),
        "file_formats": {
            media_type: list(app.file_formats.get(media_type, []))
            for media_type in FILE_FORMAT_TYPES
        },
        "file_path_prefix": list(app.file_path_prefix),
        "file_name_prefix": list(app.file_name_prefix),
        "file_name_prefix_split": app.file_name_prefix_split,
        "max_download_task": app.max_download_task,
        "max_concurrent_transmissions": app.max_concurrent_transmissions,
        "start_timeout": app.start_timeout,
        "date_format": app.date_format,
        "hide_file_name": app.hide_file_name,
        "drop_no_audio_video": app.drop_no_audio_video,
        "enable_download_txt": app.enable_download_txt,
        "after_upload_telegram_delete": app.after_upload_telegram_delete,
        "upload_drive": {
            "enable_upload_file": app.cloud_drive_config.enable_upload_file,
            "upload_adapter": app.cloud_drive_config.upload_adapter,
            "rclone_path": app.cloud_drive_config.rclone_path,
            "remote_dir": app.cloud_drive_config.remote_dir,
            "before_upload_file_zip": app.cloud_drive_config.before_upload_file_zip,
            "after_upload_file_delete": app.cloud_drive_config.after_upload_file_delete,
        },
        "web": {
            "enable_web": app.enable_web,
            "web_host": app.web_host,
            "web_port": app.web_port,
        },
        "chats": [
            {
                "chat_id": chat_id,
                "last_read_message_id": chat_config.last_read_message_id,
                "download_filter": chat_config.download_filter or "",
                "upload_telegram_chat_id": chat_config.upload_telegram_chat_id or "",
            }
            for chat_id, chat_config in app.chat_download_config.items()
        ],
        "options": {
            "media_types": SUPPORTED_MEDIA_TYPES,
            "file_path_prefix": PATH_PREFIX_OPTIONS,
            "file_name_prefix": NAME_PREFIX_OPTIONS,
        },
    }


def _update_chat_config(app: Application, chats: Any) -> None:
    """Apply editable per-chat download settings."""

    if not isinstance(chats, list):
        return

    config_chats = app.config.setdefault("chat", [])
    chat_config_by_id = {
        chat.get("chat_id"): chat for chat in config_chats if isinstance(chat, dict)
    }
    for chat_payload in chats:
        if not isinstance(chat_payload, dict):
            continue
        chat_id = chat_payload.get("chat_id")
        if chat_id not in app.chat_download_config:
            continue

        chat_config = app.chat_download_config[chat_id]
        chat_config.download_filter = str(chat_payload.get("download_filter") or "")
        chat_config.last_read_message_id = _as_positive_int(
            chat_payload.get("last_read_message_id"),
            chat_config.last_read_message_id,
            minimum=0,
        )
        upload_chat_id = str(chat_payload.get("upload_telegram_chat_id") or "").strip()
        chat_config.upload_telegram_chat_id = upload_chat_id or None

        config_entry = chat_config_by_id.get(chat_id)
        if config_entry is None:
            config_entry = {"chat_id": chat_id}
            config_chats.append(config_entry)
            chat_config_by_id[chat_id] = config_entry
        config_entry["last_read_message_id"] = chat_config.last_read_message_id
        config_entry["download_filter"] = chat_config.download_filter
        if chat_config.upload_telegram_chat_id:
            config_entry[
                "upload_telegram_chat_id"
            ] = chat_config.upload_telegram_chat_id
        else:
            config_entry.pop("upload_telegram_chat_id", None)


def _apply_settings(app: Application, payload: dict) -> dict:
    """Apply web settings to the running app and config.yaml."""

    restart_fields = set()
    if "save_path" in payload:
        save_path = str(payload.get("save_path") or "").strip()
        if save_path:
            app.save_path = save_path
            app.config["save_path"] = save_path

    media_types = _as_string_list(payload.get("media_types"), SUPPORTED_MEDIA_TYPES)
    if media_types:
        app.media_types = media_types
        app.config["media_types"] = media_types

    file_formats = payload.get("file_formats")
    if isinstance(file_formats, dict):
        normalized_formats = {}
        for media_type in FILE_FORMAT_TYPES:
            values = _as_string_list(file_formats.get(media_type))
            normalized_formats[media_type] = values or ["all"]
        app.file_formats = normalized_formats
        app.config["file_formats"] = normalized_formats

    path_prefix = _as_string_list(payload.get("file_path_prefix"), PATH_PREFIX_OPTIONS)
    if path_prefix:
        app.file_path_prefix = path_prefix
        app.config["file_path_prefix"] = path_prefix

    name_prefix = _as_string_list(payload.get("file_name_prefix"), NAME_PREFIX_OPTIONS)
    if name_prefix:
        app.file_name_prefix = name_prefix
        app.config["file_name_prefix"] = name_prefix

    if "file_name_prefix_split" in payload:
        app.file_name_prefix_split = str(payload.get("file_name_prefix_split") or "")
        app.config["file_name_prefix_split"] = app.file_name_prefix_split

    old_max_download_task = app.max_download_task
    app.max_download_task = _as_positive_int(
        payload.get("max_download_task"), app.max_download_task, minimum=1, maximum=32
    )
    app.config["max_download_task"] = app.max_download_task
    if app.max_download_task != old_max_download_task:
        restart_fields.add("max_download_task")

    app.max_concurrent_transmissions = _as_positive_int(
        payload.get("max_concurrent_transmissions"),
        app.max_concurrent_transmissions,
        minimum=1,
        maximum=200,
    )
    app.config["max_concurrent_transmissions"] = app.max_concurrent_transmissions

    app.start_timeout = _as_positive_int(
        payload.get("start_timeout"), app.start_timeout, minimum=1, maximum=3600
    )
    app.config["start_timeout"] = app.start_timeout

    if "date_format" in payload:
        app.date_format = str(payload.get("date_format") or app.date_format)
        app.config["date_format"] = app.date_format

    for key in (
        "hide_file_name",
        "drop_no_audio_video",
        "enable_download_txt",
        "after_upload_telegram_delete",
    ):
        if key in payload:
            setattr(app, key, _as_bool(payload.get(key), getattr(app, key)))
            app.config[key] = getattr(app, key)

    upload_drive = payload.get("upload_drive")
    if isinstance(upload_drive, dict):
        upload_config = app.config.setdefault("upload_drive", {})
        for key in (
            "enable_upload_file",
            "before_upload_file_zip",
            "after_upload_file_delete",
        ):
            if key in upload_drive:
                setattr(
                    app.cloud_drive_config,
                    key,
                    _as_bool(
                        upload_drive.get(key), getattr(app.cloud_drive_config, key)
                    ),
                )
                upload_config[key] = getattr(app.cloud_drive_config, key)
        for key in ("upload_adapter", "rclone_path", "remote_dir"):
            if key in upload_drive:
                setattr(app.cloud_drive_config, key, str(upload_drive.get(key) or ""))
                upload_config[key] = getattr(app.cloud_drive_config, key)

    web_config = payload.get("web")
    if isinstance(web_config, dict):
        web_host = str(web_config.get("web_host") or app.web_host)
        web_port = _as_positive_int(
            web_config.get("web_port"), app.web_port, minimum=1, maximum=65535
        )
        app.config["web_host"] = web_host
        app.config["web_port"] = web_port
        app.config["enable_web"] = _as_bool(
            web_config.get("enable_web"), app.enable_web
        )
        if web_host != app.web_host or web_port != app.web_port:
            restart_fields.add("web")
        app.web_host = web_host
        app.web_port = web_port
        app.enable_web = app.config["enable_web"]

    _update_chat_config(app, payload.get("chats"))
    app.update_config(True)
    return {
        "restart_required": bool(restart_fields),
        "restart_fields": sorted(restart_fields),
    }


@_flask_app.route("/api/settings", methods=["GET", "POST"])
@login_required
def web_settings():
    """Read or update advanced download settings."""

    app = _active_app()
    if request.method == "GET":
        return jsonify(_settings_from_app(app))

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "invalid json"}), 400

    result = _apply_settings(app, payload)
    return jsonify({"ok": True, "settings": _settings_from_app(app), **result})

# Hermes MCP Control Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给常驻下载器加一层 Bearer 鉴权的 MCP 控制接口，让运行在 `ubuntu-wg` 上的 Hermes 通过 `https://tgdn.wyichuan.cc` 查询资源包、提交下载、读取任务与系统状态，并在同一批工作里停用 `resource_delivery` 发布链路。

**Architecture:** MCP 控制路由以 `/api/mcp/` 前缀挂在现有 Flask 进程与现有监听端口上，只接受 Bearer API Key，不接受 Session/Cookie，复用现有的 `ChannelLibraryService`、`TaskStateStore` 和 owner-loop 桥接函数。MCP `stdio` 适配器是一个独立文件，运行在 Hermes 同机，只做协议转换与 HTTP 调用，不直接访问数据库或 Pyrogram。下载器仍是唯一事实来源。

**Tech Stack:** Python 3.11、Flask 2.2.2、Werkzeug 2.2.2、flask-login、SQLite（WAL）、pytest；MCP 适配器侧使用 `mcp` Python SDK 与 `requests`。

**Spec:** `docs/superpowers/specs/2026-08-24-mcp-hermes-control-design.md`

## Global Constraints

- 目标机器：RackNerd，1 vCPU / 961 MiB 内存、Python 3.11.2、系统 Python 无 venv。任何新增常驻内存与全量序列化都要按这个上限权衡。
- 服务器 Web 监听 `0.0.0.0:80`，源站可绕过 Cloudflare 直连。MCP 的安全设计不得依赖“只能从 Cloudflare 进来”。
- 不改数据库 schema，不改现有 Web 路由的鉴权方式，不动 Pyrogram 与下载队列。
- MCP 路由与浏览器路由复用同一批 service 函数；所有运行时命令必须回到 owner event loop。
- 每个行为修正先写失败测试再实现（TDD）。
- 每个任务结束追加一条 `progress.md`，并产生一个独立 commit。
- 密钥、token、真实用户数据不得进入代码、测试夹具、日志或文档。
- 本地验证命令：`python -m pytest tests -q`。

---

## Phase A：停用 `resource_delivery`

### Task 1: 不再启动 Resource Bot 与发布服务

**Files:**
- Modify: `module/bot.py:483`（`resource_bot_token requires bot_token` 校验）、`module/bot.py:498-546`（资源角色启动块）
- Modify: `module/download_runtime.py:139`、`module/download_runtime.py:187`
- Test: `tests/module/test_bot_manager.py`

**Interfaces:**
- Consumes: 无
- Produces: `BotManager.start()` 在任何配置下都不再创建 `ResourceBotStore` / `ResourceBotRole` / `ResourceDeliveryService`；`app.resource_bot_store` 恒为 `None`。

- [ ] **Step 1: 写失败测试**

在 `tests/module/test_bot_manager.py` 末尾追加：

```python
def test_resource_role_is_never_started_even_when_token_is_configured(tmp_path):
    events = []
    manager = BotManager(
        FakeAdminRole(events),
        store_factory=lambda path: (_ for _ in ()).throw(
            AssertionError("resource store must not be created")
        ),
        resource_role_factory=lambda *args: (_ for _ in ()).throw(
            AssertionError("resource role must not be created")
        ),
        delivery_factory=lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("delivery service must not be created")
        ),
        db_path_resolver=lambda: tmp_path / "resource_bot.sqlite3",
    )
    app = SimpleNamespace(
        bot_token="admin-token",
        resource_bot_token="resource-token",
        resource_staging_chat_id=0,
        temp_save_path=str(tmp_path),
        channel_library_service=None,
        resource_bot_store="sentinel",
    )

    run(manager.start(app, SimpleNamespace(), lambda *_: None, lambda *_: None))

    assert manager.started is True
    assert manager.resource_role is None
    assert manager.delivery_service is None
    assert app.resource_bot_store is None
    assert "admin.start" in events


def test_resource_token_without_bot_token_no_longer_blocks_startup(tmp_path):
    events = []
    manager = BotManager(
        FakeAdminRole(events),
        db_path_resolver=lambda: tmp_path / "resource_bot.sqlite3",
    )
    app = SimpleNamespace(
        bot_token="",
        resource_bot_token="resource-token",
        resource_staging_chat_id=0,
        temp_save_path=str(tmp_path),
        channel_library_service=None,
        resource_bot_store=None,
    )

    run(manager.start(app, SimpleNamespace(), lambda *_: None, lambda *_: None))

    assert manager.started is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_bot_manager.py -q -k resource_role_is_never_started`
Expected: FAIL —— 现在仍会调用 `store_factory` 并抛出 `AssertionError`。

- [ ] **Step 3: 实现最小改动**

`module/bot.py` 的 `BotManager.start()`：删除 `if app.resource_bot_token and not app.bot_token: raise ValueError(...)`，并把整个 `if app.resource_bot_token:` 分支（建 store、起 `resource_role`、起 `delivery_service`、注册 `ResourceAdminCommands`、`set_bot_commands`）整体删除，只保留：

```python
            await self.admin_role.start(
                app,
                client,
                add_download_task,
                download_chat_task,
            )
            app.resource_bot_store = None
            self.started = True
```

`module/download_runtime.py` 两处分支判断改为只看管理 Bot：

```python
        if application.bot_token:
```

`stop` 路径与异常回滚里针对 `resource_role` / `delivery_service` 的分支保留不动——它们在字段恒为 `None` 时是无操作，删除会扩大改动面。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_bot_manager.py tests/module/test_resource_bot.py tests/module/test_resource_delivery.py -q`
Expected: PASS。若 `test_resource_bot.py` / `test_resource_delivery.py` 中存在断言“配置 token 就会启动资源角色”的用例，改为断言新的停用行为，不要删除整个文件——模块本身要保留以支持回滚。

- [ ] **Step 5: 提交**

```bash
git add module/bot.py module/download_runtime.py tests/module/test_bot_manager.py tests/module/test_resource_bot.py tests/module/test_resource_delivery.py progress.md
git commit -m "feat: stop starting the resource delivery publishing path"
```

---

### Task 2: 发布接口的停用契约

**Files:**
- Modify: `module/web.py:408-417`（`_resource_store`）、`module/web.py:729-763`（`resource_deliveries`）
- Test: `tests/module/test_channel_library_web.py`

**Interfaces:**
- Consumes: Task 1 的 `app.resource_bot_store is None`
- Produces: `GET /api/resource-deliveries` 停用时返回 `200` 且 `{"disabled": true, "items": []}`；其余发布路由返回 `410` `resource_delivery_disabled`。

- [ ] **Step 1: 写失败测试**

在 `tests/module/test_channel_library_web.py` 末尾追加：

```python
def test_resource_delivery_read_reports_disabled_instead_of_failing(web_env):
    web_env.app.resource_bot_store = None

    response = web_env.client.get("/api/resource-deliveries?page=1&page_size=100")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["disabled"] is True
    assert payload["items"] == []


def test_resource_delivery_writes_return_disabled_error(web_env):
    web_env.app.resource_bot_store = None
    headers = csrf_headers(web_env)

    response = web_env.client.post(
        "/api/resource-deliveries/clear-terminal", headers=headers
    )

    assert response.status_code == 410
    assert response.get_json()["error_code"] == "resource_delivery_disabled"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_channel_library_web.py -q -k resource_delivery`
Expected: FAIL —— 现在读接口返回 503，写接口返回 503 `service_unavailable`。

- [ ] **Step 3: 实现最小改动**

`module/web.py`：

```python
def _resource_delivery_disabled() -> bool:
    return getattr(_active_app(), "resource_bot_store", None) is None


def _resource_store():
    store = getattr(_active_app(), "resource_bot_store", None)
    if store is None:
        raise _ChannelApiError(
            410,
            "resource_delivery_disabled",
            "Resource delivery is disabled",
        )
    return store
```

在 `resource_deliveries()` 的 `_require_no_body()` 之后插入：

```python
    if _resource_delivery_disabled():
        return jsonify(
            {
                "items": [],
                "page": 1,
                "page_size": 0,
                "total": 0,
                "summary": {},
                "disabled": True,
            }
        )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_channel_library_web.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/web.py tests/module/test_channel_library_web.py progress.md
git commit -m "feat: report resource delivery as disabled instead of unavailable"
```

---

### Task 3: 控制台隐藏发布面板

**Files:**
- Modify: `module/templates/index.html:956-970`（`pollResourceDeliveries`）及发布面板容器
- Test: `tests/module/test_task_page_ui.py`

**Interfaces:**
- Consumes: Task 2 的 `disabled: true` 标记
- Produces: 前端在收到 `disabled` 后隐藏面板并停止轮询。

- [ ] **Step 1: 写失败测试**

在 `tests/module/test_task_page_ui.py` 末尾追加：

```python
def test_console_hides_delivery_panel_when_backend_reports_disabled():
    html = INDEX_TEMPLATE.read_text(encoding="utf-8")

    assert "payload.disabled" in html
    assert "state.resourceDelivery.disabled" in html
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_task_page_ui.py -q -k delivery_panel`
Expected: FAIL —— 模板里没有 `payload.disabled`。

- [ ] **Step 3: 实现最小改动**

在 `pollResourceDeliveries` 内，取到 `payload` 后立即判断：

```javascript
        const payload = await channelRequest('/api/resource-deliveries?page=1&page_size=100');
        if (payload.disabled) {
          state.resourceDelivery.disabled = true;
          const panel = document.querySelector('[data-panel="resource-delivery"]');
          if (panel) panel.hidden = true;
          return;
        }
```

并在函数入口的 `if (state.resourceDelivery.polling) return;` 之后补一行 `if (state.resourceDelivery.disabled) return;`。给发布面板的最外层容器补上 `data-panel="resource-delivery"` 属性。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_task_page_ui.py tests/module/test_channel_library_web.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/templates/index.html tests/module/test_task_page_ui.py progress.md
git commit -m "feat: hide the console delivery panel when publishing is disabled"
```

---

## Phase B：MCP 控制面基础

### Task 4: MCP 开关与 API Key 装载

**Files:**
- Create: `module/mcp_auth.py`
- Modify: `module/app.py:490`（字段初始化）、`module/app.py:618`（`assign_config`）
- Modify: `config.example.yaml`
- Test: `tests/module/test_mcp_auth.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `Application.mcp_enabled: bool`
  - `module.mcp_auth.mcp_api_key_path(config_file: str) -> Path`
  - `module.mcp_auth.load_mcp_api_key(config_file: str) -> str`
  - `module.mcp_auth.verify_mcp_api_key(expected: str, supplied: str) -> bool`

- [ ] **Step 1: 写失败测试**

创建 `tests/module/test_mcp_auth.py`：

```python
"""API key loading and comparison for the MCP control interface."""

import os

from module.mcp_auth import load_mcp_api_key, mcp_api_key_path, verify_mcp_api_key


def test_environment_variable_wins_over_key_file(tmp_path, monkeypatch):
    config_file = str(tmp_path / "config.yaml")
    mcp_api_key_path(config_file).write_text("file-key\n", encoding="utf-8")
    monkeypatch.setenv("TMD_MCP_API_KEY", "env-key")

    assert load_mcp_api_key(config_file) == "env-key"


def test_key_file_is_used_when_environment_is_absent(tmp_path, monkeypatch):
    config_file = str(tmp_path / "config.yaml")
    key_path = mcp_api_key_path(config_file)
    key_path.write_text("  file-key  \n", encoding="utf-8")
    monkeypatch.delenv("TMD_MCP_API_KEY", raising=False)

    assert load_mcp_api_key(config_file) == "file-key"
    assert oct(key_path.stat().st_mode)[-3:] == "600"


def test_missing_key_returns_empty_string(tmp_path, monkeypatch):
    monkeypatch.delenv("TMD_MCP_API_KEY", raising=False)

    assert load_mcp_api_key(str(tmp_path / "config.yaml")) == ""


def test_verification_rejects_empty_expected_key():
    assert verify_mcp_api_key("", "") is False
    assert verify_mcp_api_key("secret", "secret") is True
    assert verify_mcp_api_key("secret", "other") is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_mcp_auth.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'module.mcp_auth'`。

- [ ] **Step 3: 实现最小代码**

创建 `module/mcp_auth.py`：

```python
"""API key material for the MCP control interface."""

import hmac
import os
from pathlib import Path

KEY_ENVIRONMENT_VARIABLE = "TMD_MCP_API_KEY"


def mcp_api_key_path(config_file: str) -> Path:
    """Return the owner-only key file that sits beside the YAML config."""

    return Path(config_file).resolve().parent / "mcp_api_key"


def load_mcp_api_key(config_file: str) -> str:
    """Read the key from the environment first, then the owner-only file."""

    environment_key = str(os.environ.get(KEY_ENVIRONMENT_VARIABLE, "")).strip()
    if environment_key:
        return environment_key
    key_path = mcp_api_key_path(config_file)
    if not key_path.exists():
        return ""
    if os.name == "posix":
        os.chmod(key_path, 0o600)
    return key_path.read_text(encoding="utf-8").strip()


def verify_mcp_api_key(expected: str, supplied: str) -> bool:
    """Compare in constant time and never accept an unconfigured key."""

    if not expected:
        return False
    return hmac.compare_digest(str(expected), str(supplied or ""))
```

`module/app.py`：在 `self.web_port: int = 5000` 附近加 `self.mcp_enabled: bool = False`；在 `assign_config` 里 `self.web_port = ...` 之后加：

```python
        self.mcp_enabled = bool((_config.get("mcp") or {}).get("enabled", False))
```

`config.example.yaml` 追加（只有开关，不放密钥）：

```yaml
mcp:
  enabled: false
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_mcp_auth.py tests/module/test_app.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/mcp_auth.py module/app.py config.example.yaml tests/module/test_mcp_auth.py progress.md
git commit -m "feat: load the MCP api key from environment or an owner-only file"
```

---

### Task 5: Bearer 鉴权与 MCP 蓝图骨架

**Files:**
- Create: `module/mcp_control.py`
- Modify: `module/web.py:232-255`（`init_web`）
- Test: `tests/module/test_mcp_control.py`

**Interfaces:**
- Consumes: Task 4 的 `load_mcp_api_key`、`verify_mcp_api_key`、`Application.mcp_enabled`
- Produces:
  - `module.mcp_control.mcp_blueprint`（`url_prefix="/api/mcp"`）
  - `module.mcp_control.register_mcp_blueprint(flask_app, app) -> bool`
  - `module.mcp_control.mcp_route(function)` 装饰器：鉴权 + 限速 + 错误映射
  - `GET /api/mcp/ping` 返回 `{"ok": true}`

- [ ] **Step 1: 写失败测试**

创建 `tests/module/test_mcp_control.py`：

```python
"""Bearer authentication contract for the MCP control blueprint."""

from types import SimpleNamespace

import pytest
from flask import Flask

from module import mcp_control


@pytest.fixture
def mcp_env(tmp_path, monkeypatch):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    app = SimpleNamespace(
        mcp_enabled=True,
        config_file=str(tmp_path / "config.yaml"),
    )
    monkeypatch.setenv("TMD_MCP_API_KEY", "test-key")
    monkeypatch.setattr(mcp_control, "_current_app", app, raising=False)
    mcp_control.reset_mcp_limiter_for_tests()
    assert mcp_control.register_mcp_blueprint(flask_app, app) is True
    with flask_app.test_client() as client:
        yield SimpleNamespace(client=client, app=app)


def test_valid_key_is_accepted(mcp_env):
    response = mcp_env.client.get(
        "/api/mcp/ping", headers={"Authorization": "Bearer test-key"}
    )

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_missing_key_returns_json_401_not_a_login_redirect(mcp_env):
    response = mcp_env.client.get("/api/mcp/ping")

    assert response.status_code == 401
    assert response.get_json()["error_code"] == "unauthorized"
    assert "Location" not in response.headers


def test_session_cookie_is_not_accepted_as_credential(mcp_env):
    mcp_env.client.set_cookie("localhost", "session", "forged")

    response = mcp_env.client.get("/api/mcp/ping")

    assert response.status_code == 401


def test_repeated_failures_are_rate_limited(mcp_env):
    for _ in range(5):
        mcp_env.client.get(
            "/api/mcp/ping", headers={"Authorization": "Bearer wrong"}
        )

    response = mcp_env.client.get(
        "/api/mcp/ping", headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code == 429
    assert response.get_json()["retry_after"] >= 1


def test_blueprint_is_not_registered_when_disabled(tmp_path):
    flask_app = Flask(__name__)
    app = SimpleNamespace(mcp_enabled=False, config_file=str(tmp_path / "config.yaml"))

    assert mcp_control.register_mcp_blueprint(flask_app, app) is False

    with flask_app.test_client() as client:
        assert client.get("/api/mcp/ping").status_code == 404


def test_error_responses_never_echo_key_material(mcp_env):
    response = mcp_env.client.get(
        "/api/mcp/ping", headers={"Authorization": "Bearer super-secret-value"}
    )

    assert "super-secret-value" not in response.get_data(as_text=True)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_mcp_control.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'module.mcp_control'`。

- [ ] **Step 3: 实现最小代码**

创建 `module/mcp_control.py`：

```python
"""Bearer-authenticated control routes for the MCP adapter."""

import logging
from functools import wraps
from typing import Optional

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
```

`module/web.py` 的 `init_web` 在 `get_flask_app().debug = ...` 之后插入：

```python
    register_mcp_blueprint(get_flask_app(), app)
```

并在文件头部 import：`from module.mcp_control import register_mcp_blueprint`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_mcp_control.py tests/test_web_csrf_contract.py -q`
Expected: PASS。`test_web_csrf_contract.py` 会遍历路由检查 CSRF 覆盖；如果它把 MCP 路由算成需要 CSRF 的写路由，在该测试里把 `/api/mcp/` 前缀显式排除，并注明原因是 Bearer 路由不使用 Session。

- [ ] **Step 5: 提交**

```bash
git add module/mcp_control.py module/web.py tests/module/test_mcp_control.py tests/test_web_csrf_contract.py progress.md
git commit -m "feat: add the bearer-authenticated MCP control blueprint"
```

---

## Phase C：只读工具

### Task 6: 资源包搜索与详情

**Files:**
- Modify: `module/mcp_control.py`
- Test: `tests/module/test_mcp_packages.py`

**Interfaces:**
- Consumes: Task 5 的 `mcp_blueprint`、`mcp_route`、`McpError`
- Produces:
  - `GET /api/mcp/packages` → `{"items": [...], "next_cursor": str|null}`，每项含 `boundary_status` 与 `downloadable`
  - `GET /api/mcp/packages/<int:package_id>` → `{"package": {...}, "items": [...], "next_cursor": ...}`

- [ ] **Step 1: 写失败测试**

创建 `tests/module/test_mcp_packages.py`，沿用 `tests/module/test_channel_library_web.py` 的 `insert_package` / `insert_package_item` 辅助函数（用 `from tests.module.test_channel_library_web import insert_package, insert_package_item, build_app` 导入）：

```python
"""Read-only MCP package queries mirror the browser queries."""

from types import SimpleNamespace

import pytest
from flask import Flask

from module import mcp_control
from module.channel_library_service import ChannelLibraryService
from module.channel_library_store import ChannelLibraryConfig, ChannelLibraryStore
from module.task_state import TaskStateStore
from tests.module.test_channel_library_web import (
    build_app,
    insert_package,
    insert_package_item,
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    flask_app = Flask(__name__)
    flask_app.config["TESTING"] = True
    app = build_app(tmp_path)
    app.mcp_enabled = True
    store = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    store.initialize()
    task_store = TaskStateStore(storage_path=tmp_path / "web-tasks.sqlite3")
    app.channel_library_service = ChannelLibraryService(
        app, SimpleNamespace(), store, ChannelLibraryConfig(), task_store=task_store
    )
    monkeypatch.setenv("TMD_MCP_API_KEY", "test-key")
    mcp_control.reset_mcp_limiter_for_tests()
    mcp_control.register_mcp_blueprint(flask_app, app)
    library, _job = store.create_or_get_library_with_full_job(
        -1001, "channel", "demo", "Demo", "https://t.me/demo/1", 10
    )
    try:
        with flask_app.test_client() as client:
            yield SimpleNamespace(
                client=client, app=app, store=store, library=library
            )
    finally:
        app.loop.close()


def auth():
    return {"Authorization": "Bearer test-key"}


def test_search_returns_non_superseded_packages_with_downloadable_flag(env):
    stable_id = insert_package(env.store, env.library["id"], 10)
    provisional_id = insert_package(
        env.store, env.library["id"], 20, boundary_status="provisional"
    )

    response = env.client.get("/api/mcp/packages?page_size=50", headers=auth())

    assert response.status_code == 200
    items = {int(item["id"]): item for item in response.get_json()["items"]}
    assert set(items) == {stable_id, provisional_id}
    assert items[stable_id]["downloadable"] is True
    assert items[provisional_id]["downloadable"] is False
    assert items[provisional_id]["boundary_status"] == "provisional"


def test_search_rejects_unknown_query_parameters(env):
    response = env.client.get("/api/mcp/packages?nope=1", headers=auth())

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_package_detail_returns_metadata_and_items(env):
    package_id = insert_package(env.store, env.library["id"], 10)
    insert_package_item(env.store, env.library["id"], package_id, 10)

    response = env.client.get(f"/api/mcp/packages/{package_id}", headers=auth())

    assert response.status_code == 200
    payload = response.get_json()
    assert int(payload["package"]["id"]) == package_id
    assert len(payload["items"]) == 1


def test_missing_package_returns_not_found(env):
    response = env.client.get("/api/mcp/packages/999999", headers=auth())

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "not_found"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_mcp_packages.py -q`
Expected: FAIL —— `/api/mcp/packages` 返回 404。

- [ ] **Step 3: 实现最小代码**

在 `module/mcp_control.py` 追加：

```python
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
```

`module/web.py` 的 `_invalid_request` 抛的是 `_ChannelApiError`，MCP 里不能直接透传，所以 `mcp_route` 需要再补一个分支，把它翻译成 MCP 错误：

```python
        except _ChannelApiError as error:
            return (
                jsonify({"error_code": error.error_code, "message": error.message}),
                error.status,
            )
```

在 `module/mcp_control.py` 顶部按需 `from module.web import _ChannelApiError`（延迟导入，放在函数内，避免 `web` 与 `mcp_control` 循环导入）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_mcp_packages.py tests/module/test_mcp_control.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/mcp_control.py tests/module/test_mcp_packages.py progress.md
git commit -m "feat: expose package search and detail over MCP"
```

---

### Task 7: 系统状态与任务读取

**Files:**
- Modify: `module/mcp_control.py`
- Test: `tests/module/test_mcp_status.py`

**Interfaces:**
- Consumes: Task 5、Task 6 的基础设施
- Produces:
  - `GET /api/mcp/system` → `{"phase", "download_state", "download_speed_bytes", "disk_free", "disk_total", "active_task_count", "completed_task_count"}`
  - `GET /api/mcp/tasks?status=&limit=` → `{"items": [...], "counts": {...}}`
  - `GET /api/mcp/tasks/<task_id>` → `{"task": {...}, "batch": {...}|null}`

- [ ] **Step 1: 写失败测试**

创建 `tests/module/test_mcp_status.py`：

```python
"""System status and task reads over MCP stay bounded and secret-free."""

from tests.module.test_mcp_packages import auth, env  # noqa: F401

from module.task_state import TaskStatus, get_task_store


def test_system_status_reports_state_without_secrets(env):
    env.app.api_hash = "super-secret-hash"

    response = env.client.get("/api/mcp/system", headers=auth())

    assert response.status_code == 200
    payload = response.get_json()
    assert set(payload) == {
        "phase",
        "download_state",
        "download_speed_bytes",
        "disk_free",
        "disk_total",
        "active_task_count",
        "completed_task_count",
    }
    assert "super-secret-hash" not in response.get_data(as_text=True)


def test_task_list_is_capped_and_filterable(env):
    store = get_task_store()
    for index in range(5):
        store.create_task(
            task_id=f"task-{index}",
            task_type="channel_batch",
            source="mcp-test",
            status=TaskStatus.QUEUED,
        )

    capped = env.client.get("/api/mcp/tasks?limit=2", headers=auth())
    filtered = env.client.get(
        f"/api/mcp/tasks?status={TaskStatus.DOWNLOADING}", headers=auth()
    )

    assert len(capped.get_json()["items"]) == 2
    assert filtered.get_json()["items"] == []


def test_task_detail_returns_not_found_for_unknown_id(env):
    response = env.client.get("/api/mcp/tasks/missing", headers=auth())

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "not_found"
```

实现前先运行 `python -m pytest tests/module/test_task_state.py -q -k create` 确认 `TaskStateStore` 创建任务的真实签名，并据此修正上面的 `store.create_task(...)` 调用参数——签名以代码为准，不要臆造。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_mcp_status.py -q`
Expected: FAIL —— `/api/mcp/system` 返回 404。

- [ ] **Step 3: 实现最小代码**

在 `module/mcp_control.py` 追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_mcp_status.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/mcp_control.py tests/module/test_mcp_status.py progress.md
git commit -m "feat: expose system status and task reads over MCP"
```

---

## Phase D：提交下载

### Task 8: 不触碰勾选状态的批次创建

**Files:**
- Modify: `module/channel_library_service.py:335`（`create_download_batch_result` 之后新增方法）
- Test: `tests/module/test_channel_library_service.py`

**Interfaces:**
- Consumes: 现有 `create_download_batch_result(library_id, key, redownload=, package_ids=)`
- Produces: `ChannelLibraryService.create_download_batches_for_packages(package_ids: Sequence[int], idempotency_key: str, redownload: bool = False) -> list[tuple[dict, bool]]`
  - 抛 `KeyError`（包不存在）、`ValueError`（非 stable 或键为空）、`RedownloadRequiredError`

- [ ] **Step 1: 写失败测试**

在 `tests/module/test_channel_library_service.py` 末尾追加（沿用该文件已有的 store 构造方式）：

```python
def test_explicit_package_batches_never_touch_selection_state(tmp_path):
    from types import SimpleNamespace

    from module.task_state import TaskStateStore
    from tests.module.test_channel_library_web import build_app, insert_package

    app = build_app(tmp_path)
    store = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    store.initialize()
    service = ChannelLibraryService(
        app,
        SimpleNamespace(),
        store,
        ChannelLibraryConfig(),
        task_store=TaskStateStore(storage_path=tmp_path / "web-tasks.sqlite3"),
    )
    library, _job = store.create_or_get_library_with_full_job(
        -1001, "channel", "demo", "Demo", "https://t.me/demo/1", 10
    )
    first = insert_package(store, library["id"], 10)
    second = insert_package(store, library["id"], 20)
    store.set_package_selected_aggregate(first, True)
    before = store.selection_summary_aggregate()

    results = service.create_download_batches_for_packages(
        [first, second], "mcp-key-1"
    )

    assert len(results) == 1
    assert all(created for _batch, created in results)
    assert store.selection_summary_aggregate() == before
    app.loop.close()


def test_explicit_package_batches_are_idempotent(tmp_path):
    from types import SimpleNamespace

    from module.task_state import TaskStateStore
    from tests.module.test_channel_library_web import build_app, insert_package

    app = build_app(tmp_path)
    store = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    store.initialize()
    service = ChannelLibraryService(
        app,
        SimpleNamespace(),
        store,
        ChannelLibraryConfig(),
        task_store=TaskStateStore(storage_path=tmp_path / "web-tasks.sqlite3"),
    )
    library, _job = store.create_or_get_library_with_full_job(
        -1001, "channel", "demo", "Demo", "https://t.me/demo/1", 10
    )
    package_id = insert_package(store, library["id"], 10)

    first = service.create_download_batches_for_packages([package_id], "mcp-key-2")
    second = service.create_download_batches_for_packages([package_id], "mcp-key-2")

    assert first[0][1] is True
    assert second[0][1] is False
    assert first[0][0]["task_id"] == second[0][0]["task_id"]
    app.loop.close()


def test_explicit_package_batches_reject_unstable_packages(tmp_path):
    from types import SimpleNamespace

    from module.task_state import TaskStateStore
    from tests.module.test_channel_library_web import build_app, insert_package

    app = build_app(tmp_path)
    store = ChannelLibraryStore(tmp_path / "channel-library.sqlite3")
    store.initialize()
    service = ChannelLibraryService(
        app,
        SimpleNamespace(),
        store,
        ChannelLibraryConfig(),
        task_store=TaskStateStore(storage_path=tmp_path / "web-tasks.sqlite3"),
    )
    library, _job = store.create_or_get_library_with_full_job(
        -1001, "channel", "demo", "Demo", "https://t.me/demo/1", 10
    )
    package_id = insert_package(
        store, library["id"], 10, boundary_status="provisional"
    )

    with pytest.raises(ValueError):
        service.create_download_batches_for_packages([package_id], "mcp-key-3")
    app.loop.close()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_channel_library_service.py -q -k explicit_package_batches`
Expected: FAIL with `AttributeError: 'ChannelLibraryService' object has no attribute 'create_download_batches_for_packages'`。

- [ ] **Step 3: 实现最小代码**

在 `module/channel_library_service.py` 的 `create_download_batch_result` 之后追加：

```python
    def create_download_batches_for_packages(
        self,
        package_ids: Sequence[int],
        idempotency_key: str,
        redownload: bool = False,
    ) -> list[tuple[dict, bool]]:
        """Create batches for exactly these packages without reading selection."""

        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("Idempotency key is required")
        if len(key) > 160:
            raise ValueError("Idempotency key is too long")
        ordered_ids = list(dict.fromkeys(int(value) for value in package_ids))
        if not ordered_ids:
            raise ValueError("At least one package is required")

        groups: dict[tuple[int, int], list[int]] = {}
        for package_id in ordered_ids:
            package = self.store.get_package(package_id)
            if package is None:
                raise KeyError(f"Channel package {package_id} does not exist")
            if package["boundary_status"] != "stable":
                raise ValueError(
                    f"Channel package {package_id} is not a stable package"
                )
            library_id = int(package["library_id"])
            source_chat_id = int(
                package["source_chat_id"] or package["chat_id"]
            )
            groups.setdefault((library_id, source_chat_id), []).append(package_id)

        results = []
        for (library_id, source_chat_id), grouped_ids in groups.items():
            batch, created = self.create_download_batch_result(
                library_id,
                f"{key}:library:{library_id}:source:{source_chat_id}",
                redownload=redownload,
                package_ids=grouped_ids,
            )
            results.append((batch, created))
        return results
```

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_channel_library_service.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/channel_library_service.py tests/module/test_channel_library_service.py progress.md
git commit -m "feat: create download batches from explicit package ids"
```

---

### Task 9: `submit_download` 控制接口

**Files:**
- Modify: `module/mcp_control.py`
- Test: `tests/module/test_mcp_submit.py`

**Interfaces:**
- Consumes: Task 8 的 `create_download_batches_for_packages`
- Produces: `POST /api/mcp/downloads` 接受 `{"package_ids": [int], "idempotency_key": str, "redownload": bool}`，返回 `{"batches": [{"id", "task_id", "status", "package_count", "created"}], "created": bool}`

- [ ] **Step 1: 写失败测试**

创建 `tests/module/test_mcp_submit.py`：

```python
"""Download submission over MCP is explicit, idempotent, and selection-free."""

from tests.module.test_mcp_packages import auth, env  # noqa: F401
from tests.module.test_channel_library_web import insert_package


def test_submit_creates_one_batch_and_leaves_selection_untouched(env):
    package_id = insert_package(env.store, env.library["id"], 10)
    env.store.set_package_selected_aggregate(package_id, True)
    before = env.store.selection_summary_aggregate()

    response = env.client.post(
        "/api/mcp/downloads",
        headers=auth(),
        json={"package_ids": [package_id], "idempotency_key": "mcp-1"},
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["created"] is True
    assert payload["batches"][0]["task_id"]
    assert env.store.selection_summary_aggregate() == before


def test_repeated_submit_returns_the_same_batch_without_creating(env):
    package_id = insert_package(env.store, env.library["id"], 10)
    body = {"package_ids": [package_id], "idempotency_key": "mcp-2"}

    first = env.client.post("/api/mcp/downloads", headers=auth(), json=body)
    second = env.client.post("/api/mcp/downloads", headers=auth(), json=body)

    assert first.status_code == 202
    assert second.status_code == 200
    assert second.get_json()["created"] is False
    assert (
        first.get_json()["batches"][0]["task_id"]
        == second.get_json()["batches"][0]["task_id"]
    )


def test_submit_rejects_unstable_package_with_state_conflict(env):
    package_id = insert_package(
        env.store, env.library["id"], 20, boundary_status="provisional"
    )

    response = env.client.post(
        "/api/mcp/downloads",
        headers=auth(),
        json={"package_ids": [package_id], "idempotency_key": "mcp-3"},
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "state_conflict"


def test_submit_requires_an_idempotency_key(env):
    package_id = insert_package(env.store, env.library["id"], 30)

    response = env.client.post(
        "/api/mcp/downloads", headers=auth(), json={"package_ids": [package_id]}
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_submit_requires_explicit_redownload_flag_type(env):
    package_id = insert_package(env.store, env.library["id"], 40)

    response = env.client.post(
        "/api/mcp/downloads",
        headers=auth(),
        json={
            "package_ids": [package_id],
            "idempotency_key": "mcp-4",
            "redownload": "yes",
        },
    )

    assert response.status_code == 400
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_mcp_submit.py -q`
Expected: FAIL —— `/api/mcp/downloads` 返回 404。

- [ ] **Step 3: 实现最小代码**

在 `module/mcp_control.py` 追加：

```python
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
```

注意 `ValueError` 分支要放在 `RedownloadRequiredError` 之后：`RedownloadRequiredError` 是 `ValueError` 的子类，顺序反了会被吞掉。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_mcp_submit.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/mcp_control.py tests/module/test_mcp_submit.py progress.md
git commit -m "feat: submit downloads over MCP without selection side effects"
```

---

## Phase E：stdio 适配器

### Task 10: MCP `stdio` 服务

**Files:**
- Create: `mcp_server.py`
- Create: `mcp-requirements.txt`
- Test: `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: Phase C / D 的 HTTP 契约
- Produces:
  - `mcp_server.DownloaderClient(base_url: str, api_key: str, session=None)`，方法 `search_packages(**params)`、`get_package(package_id, **params)`、`get_system_status()`、`list_tasks(**params)`、`get_task(task_id)`、`submit_download(package_ids, idempotency_key, redownload=False)`
  - `mcp_server.TOOL_DEFINITIONS: list[dict]`，每项含 `name`、`description`、`inputSchema`
  - `mcp_server.main()`（`mcp` SDK 只在此函数内 import）

- [ ] **Step 1: 写失败测试**

创建 `tests/test_mcp_server.py`：

```python
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
```

并追加一条依赖固定测试到 `tests/test_dependency_contract.py`：

```python
def test_mcp_adapter_requirements_are_version_pinned():
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    lines = [
        line.strip()
        for line in (root / "mcp-requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert lines
    for requirement in lines:
        assert re.fullmatch(r"[A-Za-z0-9_.-]+==[^=<>!~]+", requirement)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_mcp_server.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'mcp_server'`。

- [ ] **Step 3: 实现最小代码**

创建 `mcp-requirements.txt`（版本号在实现时取当时的最新稳定版并写死）：

```text
mcp==1.2.0
requests==2.32.3
```

创建 `mcp_server.py`：

```python
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
                "service_unavailable", "The downloader control interface is unreachable"
            )
        if response.status_code >= 400:
            payload = {}
            try:
                payload = response.json()
            except Exception:
                payload = {}
            raise ToolError(
                str(payload.get("error_code") or "service_unavailable"),
                str(payload.get("message") or "The control interface returned an error"),
            )
        return response.json()

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


TOOL_DEFINITIONS = [
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
    if name == "search_resource_packages":
        return client.search_packages(**arguments)
    if name == "get_resource_package":
        return client.get_package(arguments.pop("package_id"), **arguments)
    if name == "get_system_status":
        return client.get_system_status()
    if name == "list_download_tasks":
        return client.list_tasks(**arguments)
    if name == "get_download_task":
        return client.get_task(str(arguments["task_id"]))
    if name == "submit_download":
        return client.submit_download(
            arguments["package_ids"],
            arguments["idempotency_key"],
            redownload=bool(arguments.get("redownload", False)),
        )
    raise ToolError("not_found", f"Unknown tool {name}")


def main() -> int:
    """Serve the MCP stdio protocol; the SDK is imported only here."""

    import asyncio
    import json

    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    client = build_client()
    server = Server("telegram-media-downloader")

    @server.list_tools()
    async def list_tools():
        return [
            types.Tool(
                name=tool["name"],
                description=tool["description"],
                inputSchema=tool["inputSchema"],
            )
            for tool in TOOL_DEFINITIONS
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            result = await asyncio.to_thread(dispatch, client, name, arguments)
        except ToolError as error:
            payload = {"error_code": error.error_code, "message": error.message}
            return [types.TextContent(type="text", text=json.dumps(payload))]
        return [
            types.TextContent(
                type="text", text=json.dumps(result, ensure_ascii=False)
            )
        ]

    async def serve():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream, write_stream, server.create_initialization_options()
            )

    asyncio.run(serve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`main()` 里的 SDK 用法以实现时安装的 `mcp` 版本为准；如果 API 与上面不一致，以 SDK 文档为准调整 `main()`，但 `DownloaderClient`、`TOOL_DEFINITIONS`、`dispatch` 三者的签名不能改——测试依赖它们。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_mcp_server.py tests/test_dependency_contract.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add mcp_server.py mcp-requirements.txt tests/test_mcp_server.py tests/test_dependency_contract.py progress.md
git commit -m "feat: add the MCP stdio adapter for the downloader control interface"
```

---

## Phase F：写操作（第二批）

### Task 11: 暂停、继续与取消

**Files:**
- Modify: `module/mcp_control.py`
- Test: `tests/module/test_mcp_controls.py`

**Interfaces:**
- Consumes: `module.web_commands.submit_web_coroutine` / `wait_for_web_command`、`module.web._cancel_web_task_owned`、`ChannelLibraryService.cancel_download_batch_threadsafe`
- Produces:
  - `POST /api/mcp/downloads/pause` 与 `/resume` → `{"download_state": "Downloading"|"StopDownload"}`
  - `POST /api/mcp/tasks/<task_id>/cancel` → `{"ok": true, "task_id", "status"}` 或 `{"ok": true, "task_id", "removed": true}`

- [ ] **Step 1: 写失败测试**

创建 `tests/module/test_mcp_controls.py`：

```python
"""Pause, resume, and cancel over MCP are explicit and owner-loop bound."""

from tests.module.test_mcp_packages import auth, env  # noqa: F401

from module.download_stat import DownloadState, get_download_state, set_download_state


def test_pause_is_idempotent_and_does_not_toggle(env):
    set_download_state(DownloadState.Downloading)

    first = env.client.post("/api/mcp/downloads/pause", headers=auth())
    second = env.client.post("/api/mcp/downloads/pause", headers=auth())

    assert first.get_json()["download_state"] == DownloadState.StopDownload.name
    assert second.get_json()["download_state"] == DownloadState.StopDownload.name
    assert get_download_state() is DownloadState.StopDownload


def test_resume_returns_the_resulting_state(env):
    set_download_state(DownloadState.StopDownload)

    response = env.client.post("/api/mcp/downloads/resume", headers=auth())

    assert response.get_json()["download_state"] == DownloadState.Downloading.name


def test_cancel_unknown_task_returns_not_found(env):
    response = env.client.post("/api/mcp/tasks/missing/cancel", headers=auth())

    assert response.status_code == 404
    assert response.get_json()["error_code"] == "not_found"
```

`env` fixture 需要一个可用的 owner loop：在 fixture 里补 `app.loop` 已由 `build_app` 提供，若测试报“application loop is not available”，在该测试文件里起一个后台事件循环线程并赋给 `app.loop`，参照 `tests/module/test_channel_library_web.py` 中已有的 owner-loop 处理方式。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_mcp_controls.py -q`
Expected: FAIL —— 路由返回 404。

- [ ] **Step 3: 实现最小代码**

在 `module/mcp_control.py` 追加：

```python
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
    except WebCommandTimeout:
        raise McpError(503, "service_unavailable", "The state change timed out")
    except RuntimeError:
        raise McpError(503, "service_unavailable", "The owner loop is unavailable")


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

    result = web.cancel_task(task_id)
    body, status = result if isinstance(result, tuple) else (result, 200)
    payload = body.get_json()
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
```

`web.cancel_task` 带 `@login_required` 与 `@_require_csrf` 装饰器，不能直接调用。实现时把 `cancel_task` 的函数体抽成模块级 `_cancel_task_payload(task_id) -> tuple[dict, int]`，让 Web 路由和 MCP 路由都调用它；这是本任务唯一允许的 `web.py` 结构性改动，且必须保持 Web 路由的既有响应完全不变——`tests/test_web_cancel_task.py` 是这条约束的守门测试。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_mcp_controls.py tests/test_web_cancel_task.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/mcp_control.py module/web.py tests/module/test_mcp_controls.py progress.md
git commit -m "feat: expose explicit pause, resume, and cancel over MCP"
```

---

### Task 12: 关键词监控组

**Files:**
- Modify: `module/mcp_control.py`
- Test: `tests/module/test_mcp_keyword_monitors.py`

**Interfaces:**
- Consumes: `ChannelLibraryStore.list_keyword_monitor_groups` / `get_keyword_monitor_group` / `save_keyword_monitor_group` / `delete_keyword_monitor_group` / `list_keyword_monitor_history` / `get_keyword_monitor_summary`；`ChannelLibraryService.trigger_keyword_monitors` / `retry_keyword_monitor_failures_threadsafe`
- Produces:
  - `GET /api/mcp/keyword-monitors`、`GET|PUT|DELETE /api/mcp/keyword-monitors/<int:group_id>`
  - `POST /api/mcp/keyword-monitors`
  - `GET /api/mcp/keyword-monitors/<int:group_id>/history`
  - `POST /api/mcp/keyword-monitors/<int:group_id>/retry-failures`

- [ ] **Step 1: 写失败测试**

创建 `tests/module/test_mcp_keyword_monitors.py`：

```python
"""Keyword monitor management over MCP mirrors the browser contract."""

from tests.module.test_mcp_packages import auth, env  # noqa: F401


def body(name="Python", match=("python",)):
    return {
        "name": name,
        "enabled": True,
        "required_keywords": [],
        "match_keywords": list(match),
        "blacklist_keywords": [],
    }


def test_create_list_and_get_round_trip(env):
    created = env.client.post(
        "/api/mcp/keyword-monitors", headers=auth(), json=body()
    )
    group_id = created.get_json()["group"]["id"]

    listed = env.client.get("/api/mcp/keyword-monitors", headers=auth())
    fetched = env.client.get(
        f"/api/mcp/keyword-monitors/{group_id}", headers=auth()
    )

    assert created.status_code == 201
    assert [item["id"] for item in listed.get_json()["items"]] == [group_id]
    assert fetched.get_json()["group"]["name"] == "Python"


def test_create_requires_at_least_one_match_keyword(env):
    response = env.client.post(
        "/api/mcp/keyword-monitors", headers=auth(), json=body(match=())
    )

    assert response.status_code == 400
    assert response.get_json()["error_code"] == "invalid_request"


def test_delete_removes_the_group(env):
    created = env.client.post(
        "/api/mcp/keyword-monitors", headers=auth(), json=body()
    )
    group_id = created.get_json()["group"]["id"]

    deleted = env.client.delete(
        f"/api/mcp/keyword-monitors/{group_id}", headers=auth()
    )
    listed = env.client.get("/api/mcp/keyword-monitors", headers=auth())

    assert deleted.status_code == 200
    assert listed.get_json()["items"] == []


def test_retry_without_recoverable_failures_returns_conflict(env):
    created = env.client.post(
        "/api/mcp/keyword-monitors", headers=auth(), json=body()
    )
    group_id = created.get_json()["group"]["id"]

    response = env.client.post(
        f"/api/mcp/keyword-monitors/{group_id}/retry-failures", headers=auth()
    )

    assert response.status_code == 409
    assert response.get_json()["error_code"] == "state_conflict"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/module/test_mcp_keyword_monitors.py -q`
Expected: FAIL —— 路由返回 404。

- [ ] **Step 3: 实现最小代码**

在 `module/mcp_control.py` 追加下列路由。校验逻辑直接复用 `module/web.py` 的 `_keyword_list`（延迟导入），保存后立即调用 `trigger_keyword_monitors()`，与 Web 行为一致：

```python
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
    store = _service().store
    page = store.list_keyword_monitor_history(
        group_id, cursor=cursor, limit=page_size
    )
    return jsonify(
        {
            "items": page.items,
            "next_cursor": page.next_cursor,
            "summary": store.get_keyword_monitor_summary(group_id),
        }
    )


@mcp_blueprint.route("/keyword-monitors/<int:group_id>/retry-failures", methods=["POST"])
@mcp_route
def retry_keyword_monitor_failures(group_id: int):
    """Requeue recoverable failures through the owner loop."""

    from module.web_commands import WebCommandTimeout, wait_for_web_command

    service = _service()
    try:
        result = wait_for_web_command(
            service.retry_keyword_monitor_failures_threadsafe(group_id), timeout=5
        )
    except WebCommandTimeout:
        raise McpError(503, "service_unavailable", "Retry scheduling timed out")
    except RuntimeError:
        raise McpError(503, "service_unavailable", "Channel service is unavailable")
    if result["scheduled_count"] <= 0:
        raise McpError(409, "state_conflict", "No recoverable failures are available")
    return jsonify({"ok": True, **result}), 202
```

实现前先确认 `delete_keyword_monitor_group` 与 `get_keyword_monitor_summary` 的真实方法名与返回值（`module/web.py:1529` 与 `:1576` 是现成的调用点），以代码为准，不要臆造。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/module/test_mcp_keyword_monitors.py tests/module/test_channel_library_web.py -q`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add module/mcp_control.py tests/module/test_mcp_keyword_monitors.py progress.md
git commit -m "feat: manage keyword monitors over MCP"
```

---

## Phase G：文档与整体验收

### Task 13: 运维文档与全量验证

**Files:**
- Create: `docs/mcp-control.md`
- Modify: `README_CN.md`（在功能列表处加一行指向 `docs/mcp-control.md`）
- Test: 全量 `python -m pytest tests -q`

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 一份可直接照做的部署与接入说明

- [ ] **Step 1: 写文档**

创建 `docs/mcp-control.md`，必须覆盖：

1. 拓扑图：Hermes（`ubuntu-wg`）→ MCP `stdio` → `https://tgdn.wyichuan.cc/api/mcp/*` → RackNerd 下载器。
2. 服务器端启用步骤：`config.yaml` 加 `mcp: {enabled: true}`；生成密钥 `python3 -c "import secrets;print(secrets.token_urlsafe(32))"`，写入与 `config.yaml` 同目录的 `mcp_api_key` 文件并 `chmod 600`，或设置 `TMD_MCP_API_KEY` 环境变量；`systemctl restart tg-downloader.service`。
3. Hermes 端接入：安装 `mcp-requirements.txt`，MCP client 配置 `command: python3`、`args: ["/path/to/mcp_server.py"]`、`env: {TMD_MCP_BASE_URL, TMD_MCP_API_KEY}`。
4. 工具清单与每个工具的语义边界，特别写明三点：搜索返回非 superseded 的全部包但只有 `downloadable` 的能提交；`list_download_tasks` 只覆盖最近任务；`submit_download` 必须带 `idempotency_key`。
5. 错误码表：`invalid_request` / `unauthorized` / `not_found` / `state_conflict` / `redownload_required` / `runtime_handle_missing` / `rate_limited` / `resource_delivery_disabled` / `service_unavailable`。
6. `resource_delivery` 已停用的说明与恢复路径。
7. 明确记录未处理的既有风险：源站 80 端口可绕过 Cloudflare 直连、控制台运行在 Werkzeug 开发服务器上（对应 spec 第 11 节）。

文档中不得出现任何真实密钥、真实频道 ID 或真实用户数据。

- [ ] **Step 2: 运行全量测试**

Run: `python -m pytest tests -q`
Expected: 全部 PASS。

- [ ] **Step 3: 手工验收（在服务器上执行，逐条对照 spec 第 8 节）**

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://tgdn.wyichuan.cc/api/mcp/ping
curl -s -o /dev/null -w "%{http_code}\n" -H "Authorization: Bearer $TMD_MCP_API_KEY" \
  https://tgdn.wyichuan.cc/api/mcp/ping
curl -s -H "Authorization: Bearer $TMD_MCP_API_KEY" \
  "https://tgdn.wyichuan.cc/api/mcp/packages?page_size=5" | head -c 400
```

Expected: 无 Key 返回 `401`；有效 Key 返回 `200`；搜索返回 JSON 且带 `boundary_status` 与 `downloadable`。

- [ ] **Step 4: 提交**

```bash
git add docs/mcp-control.md README_CN.md progress.md
git commit -m "docs: document the MCP control interface and its operational limits"
```

---

## Self-Review

**Spec coverage：**

| Spec 章节 | 覆盖任务 |
|---|---|
| §1 交付顺序 | Phase A → B → C → D → E → F → G |
| §2 运行约束 | Task 5（Bearer、无 Session）、Task 11（owner loop）、Global Constraints |
| §3 架构与防护 | Task 5（限速、常量时间、审计、JSON 401） |
| §4.1 资源包 | Task 6 |
| §4.2 下载任务 | Task 7（读）、Task 8/9（提交）、Task 11（暂停/继续/取消） |
| §4.3 关键词监控 | Task 12 |
| §4.4 运行状态 | Task 7 |
| §5 停用发布链路 | Task 1、2、3 |
| §6 错误与幂等 | Task 5（错误映射）、Task 8/9（幂等） |
| §7 配置与生命周期 | Task 4、Task 13 |
| §8 验证标准 1–13 | Task 5、6、8、9、10、11、12、13 |
| §9 回滚边界 | 每个任务独立 commit，`resource_bot.py` / `resource_delivery.py` / 数据库均保留 |
| §11 既有风险 | Task 13 文档记录，不做修复 |

**已知需要在实现时以代码为准核对的点**（已在对应步骤内标注，不是占位符）：`TaskStateStore` 创建任务的签名（Task 7）、`delete_keyword_monitor_group` 与 `get_keyword_monitor_summary` 的方法名（Task 12）、`mcp` SDK 的 server API 形态（Task 10）、`test_web_csrf_contract.py` 是否需要排除 `/api/mcp/` 前缀（Task 5）。

**类型一致性：** `create_download_batches_for_packages` 在 Task 8 定义、Task 9 使用，签名一致；`DownloaderClient` / `TOOL_DEFINITIONS` / `dispatch` 在 Task 10 内自洽；`mcp_blueprint`、`mcp_route`、`McpError`、`_service`、`_invalid` 在 Task 5 定义，被 Task 6、7、9、11、12 复用。

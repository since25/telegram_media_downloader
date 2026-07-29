# Dual-Role Resource Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the existing management Bot and add an activated-user resource Bot under one lifecycle, with keyword package search and main-account-download/resource-Bot-upload delivery.

**Architecture:** `module/bot.py` remains the only application Bot entry and owns a manager that starts both roles. New focused modules own the independent resource Bot SQLite state, resource Bot handlers, and one persistent serial delivery worker. The existing channel library remains read-only to the resource feature.

**Tech Stack:** Python 3.11, asyncio, SQLite, Pyrogram MTProto clients, pytest/unittest, ruamel.yaml.

## Global Constraints

- Keep two Telegram Bot accounts but one application start/stop entry.
- Remove only the public `/forward` command; preserve `/listen_forward` and `/forward_to_comments`.
- Primary transfer path is main-account download followed by resource-Bot upload.
- One-time activation keys; activation remains active until administrator revocation.
- One active destination channel per activated user.
- One global serial resource-delivery worker.
- Do not modify `channel_library.sqlite3` or `web_tasks.sqlite3` schema.
- Never commit or log `.env.new`, Bot tokens, full activation keys, or Telegram session data.
- Stop before production configuration, service restart, database migration, or server acceptance.
- Do not use multi-agent parallel modification for this plan.

---

### Task 1: Resource Bot Configuration And Public `/forward` Removal

**Files:**
- Modify: `.gitignore`
- Modify: `config.example.yaml`
- Modify: `module/app.py`
- Modify: `module/bot.py`
- Test: `tests/module/test_app.py`
- Create: `tests/module/test_bot_commands.py`

**Interfaces:**
- Produces: `Application.resource_bot_token: str`
- Produces: `build_admin_bot_commands() -> list[types.BotCommand]`
- Preserves: `start_download_bot(app, client, add_download_task, download_chat_task)` and `stop_download_bot()`

- [ ] **Step 1: Write failing configuration tests**

Add:

```python
def test_resource_bot_token_defaults_empty():
    app = Application("", "")
    assert app.resource_bot_token == ""


def test_resource_bot_token_loads_from_config():
    app = Application("", "")
    app.assign_config(
        {
            "api_id": "",
            "api_hash": "",
            "bot_token": "admin",
            "resource_bot_token": "resource",
            "media_types": [],
            "file_formats": {},
        }
    )
    assert app.resource_bot_token == "resource"
```

- [ ] **Step 2: Write failing command-contract tests**

Create `tests/module/test_bot_commands.py`:

```python
from module import bot


def test_admin_command_menu_excludes_legacy_forward():
    names = [command.command for command in bot.build_admin_bot_commands()]
    assert "forward" not in names
    assert "listen_forward" in names


def test_admin_help_excludes_legacy_forward():
    help_text = bot.build_admin_help_text()
    assert "/forward -" not in help_text
    assert "/listen_forward -" in help_text
```

- [ ] **Step 3: Verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/module/test_app.py::test_resource_bot_token_defaults_empty \
  tests/module/test_app.py::test_resource_bot_token_loads_from_config \
  tests/module/test_bot_commands.py
```

Expected: failures for the missing property and missing pure command/help builders.

- [ ] **Step 4: Implement configuration and pure command builders**

In `Application.__init__` and `assign_config`:

```python
self.resource_bot_token: str = ""
self.resource_bot_token = _config.get("resource_bot_token", "")
```

Move the inline management command list to:

```python
def build_admin_bot_commands():
    return [
        types.BotCommand("help", _t("Help")),
        types.BotCommand("get_info", _t("Get group and user info from message link")),
        types.BotCommand("download", _t("To download the video, use the method to directly enter /download to view")),
        types.BotCommand("prescan", "预扫模式"),
        types.BotCommand("listen_forward", _t("Listen forward, use the method to directly enter /listen_forward to view")),
        types.BotCommand("add_filter", _t("Add download filter, use the method to directly enter /add_filter to view")),
        types.BotCommand("set_language", _t("Set language")),
        types.BotCommand("stop", _t("Stop bot download or forward")),
        types.BotCommand("retry_failed", _t("Retry failed download tasks with chat_id|message_id pairs")),
    ]
```

Extract the help text into `build_admin_help_text()` and remove the `/forward` line. Remove the `/forward` MessageHandler registration while leaving the underlying shared functions for remaining callers.

Add to `.gitignore`:

```gitignore
/.env.new
```

Add to `config.example.yaml` beside the Telegram credentials:

```yaml
bot_token: your_bot_token
resource_bot_token: your_resource_bot_token
```

- [ ] **Step 5: Verify GREEN**

Run the focused command from Step 3. Expected: all pass.

- [ ] **Step 6: Run management Bot regressions**

Run:

```bash
.venv/bin/pytest -q tests/module/test_comment_workflow.py tests/module/test_app.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add .gitignore config.example.yaml module/app.py module/bot.py \
  tests/module/test_app.py tests/module/test_bot_commands.py
git commit -m "refactor: prepare dual-role bot configuration"
```

---

### Task 2: Persistent Activation, Binding, And Delivery State

**Files:**
- Create: `module/resource_bot_store.py`
- Create: `tests/module/test_resource_bot_store.py`

**Interfaces:**
- Produces: `ResourceBotStore(path)`
- Produces: `create_activation_key(created_by: int) -> str`
- Produces: `redeem_activation_key(key: str, user_id: int) -> bool`
- Produces: `revoke_user(user_id: int) -> bool`
- Produces: `is_user_active(user_id: int) -> bool`
- Produces: `bind_channel(user_id: int, chat_id: int, title: str, username: str | None) -> dict`
- Produces: `get_binding(user_id: int) -> dict | None`
- Produces: `mark_binding_permission_lost(chat_id: int) -> bool`
- Produces: `unbind_channel(user_id: int) -> bool`
- Produces: `create_delivery_job(idempotency_key: str, user_id: int, package_id: int, package_revision: int, target_chat_id: int, total_items: int) -> tuple[dict, bool]`
- Produces: queue claim, progress, terminal status, and restart recovery methods.

- [ ] **Step 1: Write failing activation tests**

Cover:

```python
def test_activation_key_is_hashed_and_redeems_once(store):
    key = store.create_activation_key(100)
    with store.connect() as connection:
        row = connection.execute(
            "SELECT key_hash, key_prefix FROM resource_activation_keys"
        ).fetchone()
    assert key not in row["key_hash"]
    assert key.startswith(row["key_prefix"])
    assert store.redeem_activation_key(key, 200) is True
    assert store.redeem_activation_key(key, 201) is False
    assert store.is_user_active(200) is True


def test_revoke_user_deactivates_binding_and_cancels_queued_jobs(store):
    key = store.create_activation_key(100)
    assert store.redeem_activation_key(key, 200) is True
    store.bind_channel(200, -1001, "Target", "target")
    job, _ = store.create_delivery_job(
        idempotency_key="queued-action",
        user_id=200,
        package_id=12,
        package_revision=3,
        target_chat_id=-1001,
        total_items=2,
    )

    assert store.revoke_user(200) is True

    assert store.is_user_active(200) is False
    assert store.get_binding(200)["status"] == "unbound"
    assert store.get_delivery_job(job["id"])["status"] == "cancelled"
```

- [ ] **Step 2: Write failing binding tests**

Cover one channel per user, one user per channel, unbind, permission loss, and active-only binding.

- [ ] **Step 3: Write failing delivery-job tests**

Cover:

```python
def test_delivery_job_creation_is_idempotent(store):
    first, created = store.create_delivery_job(
        idempotency_key="action-1",
        user_id=200,
        package_id=12,
        package_revision=3,
        target_chat_id=-1001,
        total_items=2,
    )
    replay, replay_created = store.create_delivery_job(
        idempotency_key="action-1",
        user_id=200,
        package_id=12,
        package_revision=3,
        target_chat_id=-1001,
        total_items=2,
    )
    assert created is True
    assert replay_created is False
    assert replay["id"] == first["id"]


def test_recover_marks_active_jobs_failed_and_keeps_queued(store):
    first, _ = store.create_delivery_job(
        idempotency_key="active",
        user_id=200,
        package_id=12,
        package_revision=3,
        target_chat_id=-1001,
        total_items=2,
    )
    second, _ = store.create_delivery_job(
        idempotency_key="queued",
        user_id=200,
        package_id=13,
        package_revision=1,
        target_chat_id=-1001,
        total_items=1,
    )
    assert store.claim_next_delivery_job()["id"] == first["id"]

    assert store.recover_interrupted_jobs() == 1

    assert store.get_delivery_job(first["id"])["error_code"] == "restart_interrupted"
    assert store.get_delivery_job(second["id"])["status"] == "queued"
```

- [ ] **Step 4: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/module/test_resource_bot_store.py
```

Expected: import failure because `module.resource_bot_store` does not exist.

- [ ] **Step 5: Implement schema and transactions**

Create schema version `1`, enable WAL, foreign keys, busy timeout, and mode `0600`. Use:

```python
RESOURCE_BOT_SCHEMA_VERSION = 1
ACTIVATION_STATUSES = frozenset({"available", "redeemed", "revoked"})
USER_STATUSES = frozenset({"active", "revoked"})
BINDING_STATUSES = frozenset({"active", "permission_lost", "unbound"})
JOB_STATUSES = frozenset(
    {"queued", "downloading", "uploading", "completed", "failed", "cancelled"}
)
```

Use `BEGIN IMMEDIATE` for redemption, binding replacement, user revocation, idempotent job creation, and queue claim. Generate keys with `secrets.token_urlsafe(24)` and store `hashlib.sha256(key.encode("utf-8")).hexdigest()`.

Queue claim signature:

```python
def claim_next_delivery_job(self, now: float | None = None) -> dict | None:
    """Atomically move the oldest queued job to downloading."""
```

Progress signature:

```python
def update_job_progress(
    self,
    job_id: int,
    *,
    status: str | None = None,
    downloaded_items: int | None = None,
    uploaded_items: int | None = None,
) -> dict:
```

Terminal signature:

```python
def finish_delivery_job(
    self,
    job_id: int,
    status: str,
    error_code: str | None = None,
    error_summary: str | None = None,
) -> dict:
```

- [ ] **Step 6: Verify GREEN and database integrity**

Run:

```bash
.venv/bin/pytest -q tests/module/test_resource_bot_store.py
```

Expected: all pass, including `PRAGMA integrity_check == "ok"` and mode `0600`.

- [ ] **Step 7: Commit**

```bash
git add module/resource_bot_store.py tests/module/test_resource_bot_store.py
git commit -m "feat: add resource bot state store"
```

---

### Task 3: Resource Delivery Planning And Media Upload

**Files:**
- Create: `module/resource_delivery.py`
- Create: `tests/module/test_resource_delivery.py`

**Interfaces:**
- Consumes: `ResourceBotStore`
- Consumes: `ChannelLibraryStore`
- Consumes: main-account and resource-Bot Pyrogram clients
- Produces: `ResourceDeliveryService`
- Produces: `safe_delivery_filename(item: dict) -> str`
- Produces: `build_delivery_groups(items: list[PreparedDeliveryItem]) -> list[list[PreparedDeliveryItem]]`

- [ ] **Step 1: Write failing pure planning tests**

Cover path traversal prevention and media grouping:

```python
def test_safe_filename_strips_paths_and_prefixes_ordinal():
    item = {
        "ordinal": 2,
        "source_message_id": 30,
        "file_name": "../../secret.mp4",
        "media_type": "video",
        "mime_type": "video/mp4",
    }
    assert safe_delivery_filename(item) == "0002-30-secret.mp4"


def test_delivery_groups_keep_contiguous_album_order():
    items = [
        prepared(1, "album-a", "photo"),
        prepared(2, "album-a", "video"),
        prepared(3, None, "document"),
    ]
    groups = build_delivery_groups(items)
    assert [[item.ordinal for item in group] for group in groups] == [[1, 2], [3]]
```

- [ ] **Step 2: Write failing service tests**

Use fake main and Bot clients to cover:

- package revision change prevents download;
- missing source prevents all uploads;
- items download in ordinal order;
- resource Bot, not main client, performs upload calls;
- compatible media groups call `send_media_group`;
- voice/video-note groups fall back to sequential sends;
- download failure creates zero uploads;
- partial upload returns `partial_upload`;
- target permission loss prevents upload;
- temp directory is removed after success and failure;
- queued jobs run serially;
- stop cancels the worker and closes an active job with `restart_interrupted`.

- [ ] **Step 3: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/module/test_resource_delivery.py
```

Expected: import failure for `module.resource_delivery`.

- [ ] **Step 4: Implement immutable prepared items**

Create:

```python
@dataclass(frozen=True)
class PreparedDeliveryItem:
    ordinal: int
    source_chat_id: int
    source_message_id: int
    media_type: str
    media_group_id: str | None
    caption: str | None
    file_name: str
    local_path: Path | None = None
    message: Any = None
```

Only group contiguous items with the same non-empty `media_group_id`. Send as an album only when every type is group-compatible and the group is either photo/video, all audio, or all document.

- [ ] **Step 5: Implement `ResourceDeliveryService`**

Constructor:

```python
def __init__(
    self,
    app,
    main_client,
    resource_client,
    resource_store,
    channel_store,
    *,
    temp_root: Path,
    activity_gate=None,
    sleep=asyncio.sleep,
) -> None:
```

Public methods:

```python
async def start(self) -> None
async def stop(self) -> None
async def enqueue(
    self,
    *,
    idempotency_key: str,
    user_id: int,
    package_id: int,
    target_chat_id: int,
) -> tuple[dict, bool]
async def wake(self) -> None
```

Implementation rules:

- initialize restart recovery before starting the worker;
- load all package items through paginated `list_package_items_aggregate`;
- hold a Telegram download permit while fetching/downloading source messages;
- call `main_client.get_messages` and `main_client.download_media`;
- call only `resource_client.send_*` and `resource_client.send_media_group`;
- update persisted counts after each completed download/upload;
- notify the user privately on completion/failure with a safe summary;
- always clean `temp/resource-deliveries/<public_id>`.

- [ ] **Step 6: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/module/test_resource_delivery.py
```

Expected: all pass without pending asyncio tasks.

- [ ] **Step 7: Commit**

```bash
git add module/resource_delivery.py tests/module/test_resource_delivery.py
git commit -m "feat: deliver resource packages through bot uploads"
```

---

### Task 4: Activated Resource Bot Commands And Channel Binding

**Files:**
- Create: `module/resource_bot.py`
- Create: `tests/module/test_resource_bot.py`

**Interfaces:**
- Consumes: `ResourceBotStore`, `ResourceDeliveryService`, `ChannelLibraryStore`
- Produces: `ResourceBotRole`
- Produces: `ResourceAdminCommands`
- Produces: permission helpers for owner/admin and Bot post rights.

- [ ] **Step 1: Write failing permission-helper tests**

Cover owner, administrator, ordinary member, missing privileges, and `can_post_messages=False`.

- [ ] **Step 2: Write failing activation/admin command tests**

Cover:

- `/create_resource_key` returns the key once and logs no full key;
- `/revoke_resource_user <id>` revokes the user;
- `/activate <key>` works only in private chat;
- invalid/reused keys return stable messages;
- `/status` reports activation and current channel.

- [ ] **Step 3: Write failing binding tests**

Cover:

- `/bind` creates a pending intent only for active users;
- a `ChatMemberUpdated` event binds only when its actor has a pending intent;
- actor must be owner/admin;
- Bot must be administrator with `can_post_messages`;
- Bot removal or privilege loss marks the existing binding `permission_lost`;
- `/unbind` removes the binding without attempting to remove the Bot.

- [ ] **Step 4: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/module/test_resource_bot.py -k \
  "permission or activate or key or bind or unbind"
```

Expected: import failure for `module.resource_bot`.

- [ ] **Step 5: Implement role lifecycle and handlers**

`ResourceBotRole`:

```python
class ResourceBotRole:
    def __init__(self, app, main_client, store, channel_store) -> None:
        self.bot = None
        self.delivery_service = None
        self.pending_bind_users: dict[int, float] = {}
        self.search_sessions: dict[str, SearchSession] = {}

    async def start(self) -> None:
        self.bot = pyrogram.Client(
            self.app.application_name + "_resource_bot",
            api_hash=self.app.api_hash,
            api_id=self.app.api_id,
            bot_token=self.app.resource_bot_token,
            workdir=self.app.session_file_path,
            proxy=self.app.proxy,
        )
        await self.bot.start()
        self.bot_info = await self.bot.get_me()
        self._register_handlers()

    async def stop(self) -> None:
        if self.bot is not None:
            await self.bot.stop()
            self.bot = None
```

Create the client as:

```python
pyrogram.Client(
    app.application_name + "_resource_bot",
    api_hash=app.api_hash,
    api_id=app.api_id,
    bot_token=app.resource_bot_token,
    workdir=app.session_file_path,
    proxy=app.proxy,
)
```

Register `MessageHandler`, `CallbackQueryHandler`, and `ChatMemberUpdatedHandler` bound methods. Restrict activation, binding, search, and callbacks to private chats except the channel membership update.

Permission helpers must use `ChatMember.status` and `ChatMember.privileges.can_post_messages`, not `ChatPermissions`.

- [ ] **Step 6: Implement admin command registration**

`ResourceAdminCommands.register(admin_client, allowed_user_ids)` registers commands with `pyrogram.filters.user(allowed_user_ids)`.

The full key is sent only to the requesting administrator's private chat. Log only key prefix.

- [ ] **Step 7: Verify GREEN**

Run the focused command from Step 4. Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add module/resource_bot.py tests/module/test_resource_bot.py
git commit -m "feat: add activated resource bot access"
```

---

### Task 5: Resource Search, Pagination, And Idempotent Publish Actions

**Files:**
- Modify: `module/resource_bot.py`
- Modify: `tests/module/test_resource_bot.py`

**Interfaces:**
- Produces: `SearchSession`
- Produces: `/search <keyword>` and callback routes
- Consumes: `ResourceDeliveryService.enqueue(idempotency_key: str, user_id: int, package_id: int, target_chat_id: int)`

- [ ] **Step 1: Write failing search tests**

Cover:

```python
async def test_search_only_lists_stable_packages(resource_role, channel_store):
    channel_store.add_package(title="Stable Course", boundary_status="stable")
    channel_store.add_package(title="Draft Course", boundary_status="provisional")

    await resource_role.handle_search(
        resource_role.bot,
        resource_role.message(user_id=200, text="/search course"),
    )

    sent = resource_role.bot.sent_messages[-1]
    assert "Stable Course" in sent.text
    assert "Draft Course" not in sent.text


async def test_search_session_is_scoped_to_user(resource_role):
    session = resource_role.make_search_session(user_id=200, query="course")
    query = resource_role.callback(user_id=201, data=f"rs:{session.token}:next")

    await resource_role.handle_callback(resource_role.bot, query)

    assert query.answers[-1] == "搜索会话不属于当前用户。"


async def test_expired_search_callback_requires_new_search(resource_role):
    session = resource_role.make_search_session(
        user_id=200, query="course", created_at=0
    )
    query = resource_role.callback(user_id=200, data=f"rs:{session.token}:next")

    await resource_role.handle_callback(resource_role.bot, query)

    assert query.answers[-1] == "搜索已过期，请重新搜索。"


async def test_publish_requires_active_binding(resource_role):
    session = resource_role.make_search_session(user_id=200, query="course")
    session.packages[12] = {"id": 12, "boundary_status": "stable"}
    query = resource_role.callback(user_id=200, data=f"rp:{session.token}:12")

    await resource_role.handle_callback(resource_role.bot, query)

    assert query.answers[-1] == "请先绑定目标频道。"


async def test_repeated_publish_callback_returns_same_job(resource_role):
    resource_role.store.bind_channel(200, -1001, "Target", "target")
    session = resource_role.make_search_session(user_id=200, query="course")
    session.packages[12] = {"id": 12, "boundary_status": "stable"}
    first = resource_role.callback(user_id=200, data=f"rp:{session.token}:12")
    second = resource_role.callback(user_id=200, data=f"rp:{session.token}:12")

    await resource_role.handle_callback(resource_role.bot, first)
    await resource_role.handle_callback(resource_role.bot, second)

    assert resource_role.delivery_service.enqueue_calls == 1
    assert first.answers[-1] == second.answers[-1]
```

Assert each result contains title, source channel, date, media count, size, and a publish button. Assert page size is five.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/module/test_resource_bot.py -k "search or publish"
```

Expected: failures because search handlers and sessions are missing.

- [ ] **Step 3: Implement bounded search sessions**

Create:

```python
@dataclass
class SearchSession:
    token: str
    user_id: int
    query: str
    current_cursor: str | None
    next_cursor: str | None
    created_at: float
    packages: dict[int, dict]
    action_jobs: dict[int, str]
```

Use an eight-byte URL-safe token. Expire sessions after 30 minutes and cap each user's retained sessions to five.

Search with:

```python
PackageFilter(q=query)
```

Fetch additional store pages as needed until five stable packages are collected or no cursor remains. Do not write global selection records.

- [ ] **Step 4: Implement publish callbacks**

Callback data:

```text
rs:<session-token>:next
rp:<session-token>:<package-id>
```

Before enqueue:

- validate callback user;
- validate active activation;
- validate active binding;
- validate current Bot/channel permissions;
- validate stable package and revision;
- create a deterministic action key from session token, user ID, and package ID.

Call:

```python
job, created = await self.delivery_service.enqueue(
    idempotency_key=action_key,
    user_id=user_id,
    package_id=package_id,
    target_chat_id=binding["chat_id"],
)
```

- [ ] **Step 5: Verify GREEN**

Run the focused command from Step 2. Expected: all pass.

- [ ] **Step 6: Run the complete resource Bot module tests**

```bash
.venv/bin/pytest -q tests/module/test_resource_bot.py
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add module/resource_bot.py tests/module/test_resource_bot.py
git commit -m "feat: search and publish resource packages"
```

---

### Task 6: Unified Bot Manager Integration

**Files:**
- Modify: `module/bot.py`
- Modify: `module/download_runtime.py`
- Create: `tests/module/test_bot_manager.py`
- Modify: `tests/module/test_comment_workflow.py`

**Interfaces:**
- Consumes: `ResourceBotStore`, `ResourceBotRole`, `ResourceDeliveryService`
- Produces: one `_bot_manager`
- Preserves: module-level legacy management Handler functions.

- [ ] **Step 1: Write failing manager lifecycle tests**

Cover:

- only management Bot starts when `resource_bot_token == ""`;
- both roles start from the same entry when both tokens exist;
- resource store path defaults to `resource_bot.sqlite3`;
- `TMD_RESOURCE_BOT_DB_PATH` overrides the test path;
- partial startup failure unwinds components in reverse order;
- stop halts resource role, delivery service, then management role;
- repeated start/stop calls are safe.

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q tests/module/test_bot_manager.py
```

Expected: failures because `BotManager` does not exist.

- [ ] **Step 3: Implement manager**

Keep the existing management instance as the manager's admin role:

```python
class BotManager:
    def __init__(self, admin_role=None):
        self.admin_role = admin_role or DownloadBot()
        self.resource_store = None
        self.resource_role = None
        self.delivery_service = None
        self.started = False
```

The single entry performs:

```python
await self.admin_role.start(
    app,
    client,
    add_download_task,
    download_chat_task,
)
if app.resource_bot_token:
    self.resource_store = ResourceBotStore(resource_bot_db_path())
    self.resource_store.initialize()
    self.resource_role = ResourceBotRole(
        app,
        client,
        self.resource_store,
        (
            app.channel_library_service.store
            if app.channel_library_service is not None
            else None
        ),
    )
    await self.resource_role.start()
    self.delivery_service = ResourceDeliveryService(
        app,
        client,
        self.resource_role.bot,
        self.resource_store,
        app.channel_library_service.store,
        temp_root=Path(app.temp_save_path) / "resource-deliveries",
    )
    self.resource_role.delivery_service = self.delivery_service
    await self.delivery_service.start()
    self.resource_admin_commands = ResourceAdminCommands(self.resource_store)
    self.resource_admin_commands.register(
        self.admin_role.bot, self.admin_role.allowed_user_ids
    )
```

If the channel library service is unavailable, start the resource Bot for activation/binding but make search/delivery return `service_unavailable`.

Preserve an internal `_bot = _bot_manager.admin_role` compatibility alias only inside `module/bot.py`; no external second lifecycle entry is added.

- [ ] **Step 4: Update runtime liveness condition**

Use:

```python
if application.bot_token or application.resource_bot_token:
    application.loop.run_until_complete(
        runtime.start_download_bot(
            application,
            client,
            runtime.add_download_task,
            runtime.download_chat_task,
        )
    )
```

for the single manager start/stop condition and run-loop persistence. Reject `resource_bot_token` without `bot_token` with a clear configuration error because management role owns administrator key issuance.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
.venv/bin/pytest -q tests/module/test_bot_manager.py \
  tests/module/test_comment_workflow.py
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add module/bot.py module/download_runtime.py \
  tests/module/test_bot_manager.py tests/module/test_comment_workflow.py
git commit -m "refactor: unify management and resource bots"
```

---

### Task 7: Configuration Documentation And Operational Handoff

**Files:**
- Modify: `README_CN.md`
- Modify: `README.md` if its configuration section would otherwise contradict Chinese documentation
- Modify: `docs/web-control-console.md`
- Modify: `progress.md`
- Create: `docs/resource-bot-server-handoff.md`
- Test: `tests/module/test_bot_commands.py`

**Interfaces:**
- Produces: exact server-side configuration and acceptance checklist without executing it.

- [ ] **Step 1: Write failing documentation contract test**

Extend `tests/module/test_bot_commands.py`:

```python
from pathlib import Path


def test_resource_bot_configuration_is_documented_without_real_secret():
    example = Path("config.example.yaml").read_text(encoding="utf-8")
    readme = Path("README_CN.md").read_text(encoding="utf-8")
    handoff = Path("docs/resource-bot-server-handoff.md").read_text(encoding="utf-8")
    assert "resource_bot_token: your_resource_bot_token" in example
    assert "resource_bot_token" in readme
    assert "resource_bot.sqlite3" in handoff
    assert "tg-downloader.service" in handoff
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest -q \
  tests/module/test_bot_commands.py::test_resource_bot_configuration_is_documented_without_real_secret
```

Expected: failure because the handoff document is missing.

- [ ] **Step 3: Write user and server documentation**

Document:

- management vs resource Bot roles;
- `/create_resource_key`, `/revoke_resource_user`, `/activate`, `/bind`, `/search`;
- the user adds only the resource Bot to the target channel;
- download-then-upload behavior and partial-upload warning;
- local `.env.new` handling;
- production backup of `config.yaml`, sessions, and SQLite databases;
- adding `resource_bot_token` to production config;
- compile, dependency, database integrity, service, journal, Bot command, binding, search, single-media, and album acceptance checks;
- rollback without deleting existing channel/task databases.

Do not include the real token or server credentials.

- [ ] **Step 4: Verify GREEN**

Run the focused test from Step 2. Expected: pass.

- [ ] **Step 5: Append implementation evidence to `progress.md`**

Use the required format and include focused/full test outputs, changed files, and an executable rollback point. Do not record production deployment as completed.

- [ ] **Step 6: Commit**

```bash
git add README_CN.md README.md docs/web-control-console.md \
  docs/resource-bot-server-handoff.md progress.md \
  tests/module/test_bot_commands.py
git commit -m "docs: add resource bot operations and handoff"
```

---

### Task 8: Completion Audit And Local Verification

**Files:**
- Modify only files required by failures directly caused by Tasks 1-7.
- Modify: `progress.md` with final verification evidence.

**Interfaces:**
- Produces: a locally verified branch ready for the user to take over at production server acceptance.

- [ ] **Step 1: Run focused resource feature tests**

```bash
.venv/bin/pytest -q \
  tests/module/test_resource_bot_store.py \
  tests/module/test_resource_delivery.py \
  tests/module/test_resource_bot.py \
  tests/module/test_bot_manager.py \
  tests/module/test_bot_commands.py
```

Expected: all pass.

- [ ] **Step 2: Run management Bot and channel-library regressions**

```bash
.venv/bin/pytest -q \
  tests/module/test_comment_workflow.py \
  tests/module/test_channel_library_queries.py \
  tests/module/test_channel_library_store.py \
  tests/module/test_channel_library_service.py \
  tests/module/test_channel_library_workflow.py
```

Expected: all pass.

- [ ] **Step 3: Run complete suite**

Use an isolated state database:

```bash
verification_dir="$(mktemp -d)"
TMD_TASK_DB_PATH="$verification_dir/web_tasks.sqlite3" \
TMD_RESOURCE_BOT_DB_PATH="$verification_dir/resource_bot.sqlite3" \
  .venv/bin/pytest -q
```

Expected: all tests pass with only the repository's existing intentional skip.

- [ ] **Step 4: Run static and repository checks**

```bash
.venv/bin/python check_imports.py
.venv/bin/python -m py_compile \
  module/app.py module/bot.py module/resource_bot_store.py \
  module/resource_bot.py module/resource_delivery.py \
  module/download_runtime.py
.venv/bin/pip check
git diff --check
git status --short
```

Expected: imports, compile, dependency, and diff checks pass; only `.env.new` remains untracked and ignored after Task 1, so it must not appear in status.

- [ ] **Step 5: Verify database migration behavior**

Create a fresh resource database and assert:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from tempfile import TemporaryDirectory
from module.resource_bot_store import ResourceBotStore

with TemporaryDirectory() as directory:
    path = Path(directory) / "resource_bot.sqlite3"
    store = ResourceBotStore(path)
    store.initialize()
    with store.connect() as connection:
        print(connection.execute("PRAGMA user_version").fetchone()[0])
        print(connection.execute("PRAGMA integrity_check").fetchone()[0])
PY
```

Expected:

```text
1
ok
```

- [ ] **Step 6: Audit every design requirement**

Check the design document line by line and record evidence for:

- unified lifecycle;
- removed `/forward` entry;
- optional resource token;
- hashed one-time keys;
- revocation;
- one-channel binding and permission loss;
- stable search and pagination;
- idempotent enqueue;
- main-account download and Bot upload;
- album order;
- cleanup, partial failure, restart recovery;
- secret handling;
- documentation and server stop boundary.

- [ ] **Step 7: Append final local verification log**

Record exact commands and outcomes in `progress.md`. State that production config, service restart, live Bot binding, and final server acceptance remain for the user.

- [ ] **Step 8: Commit final verification evidence**

```bash
git add progress.md
git commit -m "test: verify dual-role resource bot"
```

- [ ] **Step 9: Stop before production**

Do not push production configuration, connect to the server, restart the service, or write the real token. Hand the user:

- branch and commit IDs;
- local test evidence;
- exact server config delta;
- backup/migration/restart/acceptance checklist;
- rollback instructions.

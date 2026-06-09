# Prescan Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Telegram bot menu-driven prescan mode that scans forward from one channel link, lets the user select discovered media packages, and downloads selected packages serially using C naming only.

**Architecture:** Keep pure package planning and Telegram text formatting outside the bot handler so it is easy to unit test. Add `module/prescan_workflow.py` for multi-package planning, selection state, callback data, and page formatting; keep `module/bot.py` responsible for command registration, per-user sessions, and callbacks; keep Telegram I/O and serial package download orchestration in `media_downloader.py`.

**Tech Stack:** Python, Pyrogram, unittest/pytest, existing `TaskNode`, existing `download_prepared_messages`, existing package naming helpers.

---

## File Structure

- Create: `module/prescan_workflow.py`
  - Pure dataclasses, constants, multi-package planner, callback helpers, and compact selection/progress formatters.
- Modify: `module/comment_workflow.py`
  - Add C-only preview builders/formatters while preserving existing strategy internals.
- Modify: `module/bot.py`
  - Register `/prescan`, track prescan sessions, route the next link to prescan, handle selection callbacks, and start serial downloads.
- Modify: `media_downloader.py`
  - Add slow prescan scanner and serial bulk package download orchestrator.
- Modify: `tests/module/test_comment_workflow.py`
  - Add C-only guided preview regression tests and keep existing package/comment tests updated.
- Create: `tests/module/test_prescan_workflow.py`
  - Pure tests for multi-package planning, callbacks, selection formatting, and pagination.
- Modify: `README_CN.md`
  - Document the menu entry, C-only behavior, slow scan limits, and serial selected-package downloads.

---

### Task 1: Make Existing Guided Confirmations C-Only

**Files:**
- Modify: `module/comment_workflow.py`
- Modify: `module/bot.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing tests for C-only preview text**

Add these tests to `CommentWorkflowTestCase` in `tests/module/test_comment_workflow.py`.

```python
def test_build_recommended_naming_previews_only_returns_c_for_comments(self):
    from module.comment_workflow import build_recommended_naming_previews

    comments = [
        MockMessage(
            id=4978,
            media="video",
            caption="夏日合集",
            video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
        )
    ]

    previews = build_recommended_naming_previews(
        comments,
        channel="zhyseseb",
        post_id=422,
        post_title="夏日合集",
    )

    self.assertEqual(len(previews), 1)
    self.assertEqual(previews[0].strategy, NamingStrategy.RECOMMENDED)
    self.assertEqual(
        previews[0].title,
        "推荐C：频道/原帖ID-标题/评论ID - 原文件名",
    )

def test_build_recommended_package_naming_previews_only_returns_c(self):
    from module.comment_workflow import (
        build_recommended_package_naming_previews,
        plan_message_package,
    )

    messages = [
        MockMessage(
            id=126711,
            media="video",
            caption="课程 第01章",
            video=MockVideo(file_name="01.mp4", mime_type="video/mp4"),
        )
    ]
    package_plan = plan_message_package(messages, start_message_id=126711)

    previews = build_recommended_package_naming_previews(
        package_plan.items,
        channel="Private Course",
        start_message_id=126711,
        package_title=package_plan.package_title,
    )

    self.assertEqual(len(previews), 1)
    self.assertEqual(previews[0].strategy, NamingStrategy.RECOMMENDED)
    self.assertEqual(
        previews[0].title,
        "推荐C：频道/起始ID-标题/消息ID - 原文件名",
    )
```

Update `test_build_package_naming_previews_and_preview_message` so it asserts A/B/D text is absent:

```python
self.assertIn("推荐C：频道/起始ID-标题/消息ID - 原文件名", preview_text)
self.assertNotIn("A：标题/消息ID - 作者 - 原文件名", preview_text)
self.assertNotIn("B：标题/消息ID - caption摘要 - 原文件名", preview_text)
self.assertNotIn("D：频道/年月/标题/消息ID - caption摘要", preview_text)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_recommended_naming_previews_only_returns_c_for_comments tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_recommended_package_naming_previews_only_returns_c tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_package_naming_previews_and_preview_message -q
```

Expected: FAIL because `build_recommended_naming_previews` and `build_recommended_package_naming_previews` do not exist, and package preview still includes A/B/D.

- [ ] **Step 3: Add C-only preview builders**

In `module/comment_workflow.py`, add these helpers immediately after `build_package_naming_previews(...)`.

```python
def build_recommended_naming_previews(
    comments: Sequence[CommentLike],
    channel: str,
    post_id: int,
    post_title: str,
    sample_size: int = 3,
) -> List[NamingPreview]:
    """Build only the recommended C naming preview for comment media."""

    sample_comments = filter_media_comments(comments)[:sample_size]
    context = CommentNamingContext(
        strategy=NamingStrategy.RECOMMENDED,
        channel=channel,
        post_id=post_id,
        post_title=post_title,
    )
    return [
        NamingPreview(
            strategy=NamingStrategy.RECOMMENDED,
            title="推荐C：频道/原帖ID-标题/评论ID - 原文件名",
            examples=[
                build_name_for_strategy(comment, context)
                for comment in sample_comments
            ],
        )
    ]


def build_recommended_package_naming_previews(
    items: Sequence[PackageMediaItem],
    channel: str,
    start_message_id: int,
    package_title: str,
    sample_size: int = 3,
) -> List[NamingPreview]:
    """Build only the recommended C naming preview for package media."""

    sample_items = list(items)[:sample_size]
    context = PackageNamingContext(
        strategy=NamingStrategy.RECOMMENDED,
        channel=channel,
        start_message_id=start_message_id,
        package_title=package_title,
    )
    return [
        NamingPreview(
            strategy=NamingStrategy.RECOMMENDED,
            title="推荐C：频道/起始ID-标题/消息ID - 原文件名",
            examples=[
                build_package_name_for_strategy(item, context)
                for item in sample_items
            ],
        )
    ]
```

- [ ] **Step 4: Replace bot-facing preview builders and buttons**

In `module/bot.py` imports, replace `build_naming_previews` and `build_package_naming_previews` with the new helpers:

```python
    build_recommended_naming_previews,
    build_recommended_package_naming_previews,
```

In `preview_comment_workflow(...)`, replace the preview builder call:

```python
previews = build_recommended_naming_previews(
    media_comments,
    channel=channel,
    post_id=workflow_request.post_id,
    post_title=post_title,
)
```

Replace the `buttons = InlineKeyboardMarkup(...)` block in `preview_comment_workflow(...)` with:

```python
buttons = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton(
                "开始下载",
                callback_data=build_callback_data(
                    token, NamingStrategy.RECOMMENDED
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "取消",
                callback_data=f"{COMMENT_WORKFLOW_PREFIX}:{token}:cancel",
            )
        ],
    ]
)
```

In `preview_package_workflow(...)`, replace the preview builder call:

```python
previews = build_recommended_package_naming_previews(
    package_items,
    channel=channel,
    start_message_id=workflow_request.start_message_id,
    package_title=package_title,
)
```

Replace the package `buttons = InlineKeyboardMarkup(...)` block with:

```python
buttons = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton(
                "开始下载",
                callback_data=build_package_callback_data(
                    token, NamingStrategy.RECOMMENDED
                ),
            )
        ],
        [
            InlineKeyboardButton(
                "取消",
                callback_data=f"{PACKAGE_WORKFLOW_PREFIX}:{token}:cancel",
            )
        ],
    ]
)
```

- [ ] **Step 5: Update confirmation text to avoid strategy choice language**

In `handle_package_workflow_callback(...)`, replace:

```python
confirm_text = f"已确认命名策略 {strategy.value}，开始下载连续资源包。"
```

with:

```python
confirm_text = "已确认，开始按推荐C格式下载连续资源包。"
```

In `handle_comment_workflow_callback(...)`, replace:

```python
confirm_text = f"已确认命名策略 {strategy.value}，开始下载评论媒体。"
```

with:

```python
confirm_text = "已确认，开始按推荐C格式下载评论媒体。"
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 1**

```bash
git add module/comment_workflow.py module/bot.py tests/module/test_comment_workflow.py
git commit -m "feat: simplify guided downloads to C naming"
```

---

### Task 2: Add Pure Prescan Planning And Selection Helpers

**Files:**
- Create: `module/prescan_workflow.py`
- Create: `tests/module/test_prescan_workflow.py`

- [ ] **Step 1: Write failing pure workflow tests**

Create `tests/module/test_prescan_workflow.py` with:

```python
"""Tests for prescan multi-package planning and selection helpers."""
import unittest

from tests.test_common import MockMessage, MockVideo


class PrescanWorkflowTestCase(unittest.TestCase):
    def test_plan_prescan_packages_splits_multiple_caption_packages(self):
        from module.prescan_workflow import PrescanLimits, plan_prescan_packages

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章 01/20",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
            MockMessage(
                id=101,
                media="video",
                video=MockVideo(file_name="02.mp4", mime_type="video/mp4", file_size=200),
            ),
            MockMessage(
                id=120,
                media="video",
                caption="课程 第02章 01/20",
                video=MockVideo(file_name="03.mp4", mime_type="video/mp4", file_size=300),
            ),
            MockMessage(
                id=121,
                media="video",
                video=MockVideo(file_name="04.mp4", mime_type="video/mp4", file_size=400),
            ),
        ]

        plan = plan_prescan_packages(
            messages,
            start_message_id=100,
            limits=PrescanLimits(max_messages=5000, max_packages=50),
        )

        self.assertEqual(plan.scanned_count, 4)
        self.assertEqual(len(plan.packages), 2)
        self.assertEqual(plan.packages[0].start_message_id, 100)
        self.assertEqual(plan.packages[0].end_message_id, 101)
        self.assertEqual(plan.packages[0].title, "课程 第01章 01/20")
        self.assertEqual([item.message.id for item in plan.packages[0].items], [100, 101])
        self.assertEqual(plan.packages[1].start_message_id, 120)
        self.assertEqual(plan.packages[1].end_message_id, 121)

    def test_selection_page_formats_mobile_compact_rows(self):
        from module.prescan_workflow import (
            PrescanLimits,
            format_prescan_selection_page,
            plan_prescan_packages,
        )

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
            MockMessage(
                id=120,
                media="video",
                caption="课程 第02章",
                video=MockVideo(file_name="02.mp4", mime_type="video/mp4", file_size=200),
            ),
        ]
        plan = plan_prescan_packages(messages, 100, PrescanLimits())

        text = format_prescan_selection_page(
            plan,
            channel="Private Course",
            page=0,
            selected_package_ids={2},
            page_size=8,
        )

        self.assertIn("预扫完成：", text)
        self.assertIn("频道：Private Course", text)
        self.assertIn("识别：2 个包", text)
        self.assertIn("已选：1 个", text)
        self.assertIn("1. 100-100｜1 个｜100.0B", text)
        self.assertIn("课程 第01章", text)

    def test_prescan_callback_data_round_trips(self):
        from module.prescan_workflow import (
            build_prescan_callback_data,
            parse_prescan_callback_data,
        )

        data = build_prescan_callback_data("abc123", "toggle", 7)

        self.assertEqual(data, "ps:abc123:toggle:7")
        self.assertEqual(parse_prescan_callback_data(data), ("abc123", "toggle", "7"))
        self.assertIsNone(parse_prescan_callback_data("pw:abc123:C"))
        self.assertIsNone(parse_prescan_callback_data("ps::toggle:7"))
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_prescan_workflow.py -q
```

Expected: FAIL because `module.prescan_workflow` does not exist.

- [ ] **Step 3: Create `module/prescan_workflow.py`**

Create `module/prescan_workflow.py` with:

```python
"""Pure helpers for Telegram prescan package discovery and selection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Set

from module.comment_workflow import (
    CommentScanSummary,
    MessagePackagePlan,
    PackageMediaItem,
    SizeSummary,
    build_size_summary,
    clean_segment,
    filter_media_comments,
    format_size_summary,
    plan_message_package,
)

PRESCAN_WORKFLOW_PREFIX = "ps"
PRESCAN_PAGE_SIZE = 8


@dataclass
class PrescanLimits:
    """Safety limits for a prescan run."""

    max_messages: int = 5000
    max_packages: int = 50
    missing_streak_limit: int = 200


@dataclass
class PrescanPackage:
    """One detected package in a prescan result."""

    package_id: int
    title: str
    start_message_id: int
    end_message_id: int
    items: List[PackageMediaItem]
    package_plan: MessagePackagePlan
    messages: list
    failed_message_ids: List[int] = field(default_factory=list)

    @property
    def media_count(self) -> int:
        return len(self.items)

    @property
    def size_summary(self) -> SizeSummary:
        return self.package_plan.size_summary


@dataclass
class PrescanPlan:
    """Pure prescan planning result."""

    start_message_id: int
    scanned_count: int
    packages: List[PrescanPackage]
    warning: Optional[str] = None


def plan_prescan_packages(
    messages: Sequence,
    start_message_id: int,
    limits: Optional[PrescanLimits] = None,
) -> PrescanPlan:
    """Split scanned messages into multiple continuous media packages."""

    limits = limits or PrescanLimits()
    candidates = sorted(
        [
            message
            for message in messages
            if message and hasattr(message, "id") and message.id >= start_message_id
        ],
        key=lambda message: message.id,
    )[: limits.max_messages]

    packages: List[PrescanPackage] = []
    cursor = start_message_id
    warning = None

    while len(packages) < limits.max_packages:
        remaining = [message for message in candidates if message.id >= cursor]
        if not remaining:
            break

        package_plan = plan_message_package(
            remaining,
            start_message_id=cursor,
            max_scan_count=len(remaining),
        )
        if not package_plan.items:
            break

        package_messages = [item.message for item in package_plan.items]
        media_ids = [message.id for message in package_messages]
        package_id = len(packages) + 1
        packages.append(
            PrescanPackage(
                package_id=package_id,
                title=package_plan.package_title,
                start_message_id=min(media_ids),
                end_message_id=max(media_ids),
                items=list(package_plan.items),
                package_plan=package_plan,
                messages=package_messages,
            )
        )

        next_message = package_plan.next_package_message
        if not next_message:
            break
        cursor = next_message.id

    if len(candidates) >= limits.max_messages:
        warning = "预扫已达到安全上限，结果可能不是频道最新消息。"
    if len(packages) >= limits.max_packages:
        warning = "预扫已达到包数量上限，结果可能不是频道最新消息。"

    return PrescanPlan(
        start_message_id=start_message_id,
        scanned_count=len(candidates),
        packages=packages,
        warning=warning,
    )


def build_prescan_callback_data(token: str, action: str, value: object = "") -> str:
    """Build prescan callback data within Telegram's small callback limit."""

    if value == "":
        return f"{PRESCAN_WORKFLOW_PREFIX}:{token}:{action}"
    return f"{PRESCAN_WORKFLOW_PREFIX}:{token}:{action}:{value}"


def parse_prescan_callback_data(data: str):
    """Parse prescan callback payloads."""

    parts = data.split(":")
    if len(parts) not in (3, 4):
        return None
    if parts[0] != PRESCAN_WORKFLOW_PREFIX or not parts[1] or not parts[2]:
        return None
    value = parts[3] if len(parts) == 4 else ""
    return parts[1], parts[2], value


def page_packages(plan: PrescanPlan, page: int, page_size: int = PRESCAN_PAGE_SIZE):
    """Return packages for one zero-based page."""

    safe_page = max(0, page)
    start = safe_page * page_size
    end = start + page_size
    return plan.packages[start:end]


def format_prescan_selection_page(
    plan: PrescanPlan,
    channel: str,
    page: int,
    selected_package_ids: Set[int],
    page_size: int = PRESCAN_PAGE_SIZE,
) -> str:
    """Format a compact mobile package selection page."""

    lines = [
        "预扫完成：",
        f"频道：{channel}",
        f"起点：{plan.start_message_id}",
        f"扫描：{plan.scanned_count} 条消息",
        f"识别：{len(plan.packages)} 个包",
        f"已选：{len(selected_package_ids)} 个",
    ]
    if plan.warning:
        lines.append(f"提示：{plan.warning}")
    lines.append("")

    for package in page_packages(plan, page, page_size):
        title = clean_segment(package.title, f"package-{package.package_id}", 60)
        size_text = format_size_summary(package.size_summary).replace("预计大小：", "")
        lines.append(
            f"{package.package_id}. "
            f"{package.start_message_id}-{package.end_message_id}"
            f"｜{package.media_count} 个｜{size_text}"
        )
        lines.append(f"   {title}")

    return "\n".join(lines).rstrip()


def summarize_prescan_progress(
    start_message_id: int,
    scanned_count: int,
    package_count: int,
    latest_package: Optional[PrescanPackage] = None,
    rate_limited_seconds: Optional[int] = None,
) -> str:
    """Format prescan progress for a status message."""

    lines = [
        "预扫中...",
        f"起点：{start_message_id}",
        f"已扫描：{scanned_count} 条消息",
        f"已识别：{package_count} 个包",
    ]
    if latest_package:
        lines.append(
            "最近包："
            f"{latest_package.start_message_id} - {latest_package.end_message_id} / "
            f"{clean_segment(latest_package.title, f'package-{latest_package.package_id}', 60)}"
        )
    if rate_limited_seconds is not None:
        lines.append(f"限流暂停：{rate_limited_seconds} 秒后继续")
    return "\n".join(lines)
```

- [ ] **Step 4: Run pure tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_prescan_workflow.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```bash
git add module/prescan_workflow.py tests/module/test_prescan_workflow.py
git commit -m "feat: add prescan package planning helpers"
```

---

### Task 3: Add Bot Prescan Menu, Awaiting-Link Session, And Selection Callbacks

**Files:**
- Modify: `module/bot.py`
- Modify: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing bot session and callback tests**

Add a new test class near the existing bot tests in `tests/module/test_comment_workflow.py`:

```python
class BotPrescanWorkflowTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_prescan_command_creates_awaiting_link_session(self):
        from module import bot as bot_module

        class FakeClient:
            def __init__(self):
                self.sent_messages = []

            async def send_message(self, chat_id, text, **kwargs):
                self.sent_messages.append((chat_id, text, kwargs))

        old_sessions = getattr(bot_module._bot, "pending_prescan_sessions", None)
        try:
            bot_module._bot.pending_prescan_sessions = {}
            message = MockMessage(id=5, text="/prescan", from_user=MockUser(id=123))
            client = FakeClient()

            await bot_module.start_prescan_mode(client, message)

            self.assertIn(123, bot_module._bot.pending_prescan_sessions)
            self.assertEqual(
                bot_module._bot.pending_prescan_sessions[123]["mode"],
                "awaiting_prescan_link",
            )
            self.assertIn("已进入预扫模式", client.sent_messages[0][1])
        finally:
            if old_sessions is None:
                delattr(bot_module._bot, "pending_prescan_sessions")
            else:
                bot_module._bot.pending_prescan_sessions = old_sessions

    async def test_download_from_link_routes_to_prescan_when_session_active(self):
        from module import bot as bot_module

        class FakeClient:
            pass

        old_sessions = getattr(bot_module._bot, "pending_prescan_sessions", None)
        try:
            bot_module._bot.pending_prescan_sessions = {
                123: {"mode": "awaiting_prescan_link"}
            }
            message = MockMessage(
                id=6,
                text="https://t.me/c/1298283297/126711",
                from_user=MockUser(id=123),
            )
            captured = {}

            async def fake_preview_prescan_workflow(client, routed_message, package_request):
                captured["message"] = routed_message
                captured["request"] = package_request

            with patch(
                "module.bot.preview_prescan_workflow",
                new=fake_preview_prescan_workflow,
            ):
                await bot_module.download_from_link(FakeClient(), message)

            self.assertIs(captured["message"], message)
            self.assertEqual(captured["request"].start_message_id, 126711)
            self.assertNotIn(123, bot_module._bot.pending_prescan_sessions)
        finally:
            if old_sessions is None:
                delattr(bot_module._bot, "pending_prescan_sessions")
            else:
                bot_module._bot.pending_prescan_sessions = old_sessions
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::BotPrescanWorkflowTestCase -q
```

Expected: FAIL because prescan bot functions and state do not exist.

- [ ] **Step 3: Import prescan helpers in `module/bot.py`**

Add imports near the existing `module.comment_workflow` imports:

```python
from module.prescan_workflow import (
    PRESCAN_WORKFLOW_PREFIX,
    build_prescan_callback_data,
    format_prescan_selection_page,
    parse_prescan_callback_data,
    summarize_prescan_progress,
)
```

- [ ] **Step 4: Add state storage and command registration**

In `DownloadBot.__init__`, add:

```python
self.pending_prescan_sessions: dict = {}
```

In the `commands` list inside `DownloadBot.start(...)`, add:

```python
types.BotCommand("prescan", "预扫模式"),
```

Add a handler after the retry handler:

```python
self.bot.add_handler(
    MessageHandler(
        start_prescan_mode,
        filters=pyrogram.filters.command(["prescan"])
        & pyrogram.filters.user(self.allowed_user_ids),
    )
)
```

- [ ] **Step 5: Add prescan mode command handler**

In `module/bot.py`, add this function before `download_from_link(...)`:

```python
async def start_prescan_mode(client: pyrogram.Client, message: pyrogram.types.Message):
    """Enter prescan mode for the next Telegram message link from this user."""

    user_id = message.from_user.id
    _bot.pending_prescan_sessions[user_id] = {
        "mode": "awaiting_prescan_link",
        "source_message_id": message.id,
        "created_at": datetime.now(),
    }
    await client.send_message(
        user_id,
        (
            "已进入预扫模式，请发送起始频道消息链接。\n"
            "例如：https://t.me/c/1446289027/156439"
        ),
        reply_to_message_id=message.id,
    )
```

- [ ] **Step 6: Route active prescan sessions before ordinary guided links**

At the top of `download_from_link(...)`, immediately after the `message.text` guard, add:

```python
user_id = message.from_user.id
prescan_session = _bot.pending_prescan_sessions.get(user_id)
if prescan_session and prescan_session.get("mode") == "awaiting_prescan_link":
    package_request = build_message_package_workflow_request(message.text.strip())
    if not package_request:
        await client.send_message(
            user_id,
            "预扫模式需要普通频道消息链接，例如：https://t.me/c/1446289027/156439",
            reply_to_message_id=message.id,
        )
        return
    _bot.pending_prescan_sessions.pop(user_id, None)
    await preview_prescan_workflow(client, message, package_request)
    return
```

- [ ] **Step 7: Add a minimal prescan preview entrypoint**

Add this small implementation before callback handlers so the routing path has a concrete async target. Task 5 expands the function after the scanner and selection UI exist.

```python
async def preview_prescan_workflow(client, message, workflow_request):
    """Acknowledge prescan input before scanner wiring is added."""

    await client.send_message(
        message.from_user.id,
        f"预扫任务已接收：{workflow_request.start_message_id}",
        reply_to_message_id=message.id,
    )
```

- [ ] **Step 8: Run bot session tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::BotPrescanWorkflowTestCase -q
```

Expected: PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add module/bot.py tests/module/test_comment_workflow.py
git commit -m "feat: add prescan menu session routing"
```

---

### Task 4: Add Slow Multi-Package Telegram Scanner

**Files:**
- Modify: `media_downloader.py`
- Modify: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing scanner tests**

Add tests to `tests/module/test_comment_workflow.py` near existing scanner tests:

```python
class FakeSleepRecorder:
    def __init__(self):
        self.calls = []

    async def __call__(self, seconds):
        self.calls.append(seconds)


class FloodWaitLike(Exception):
    def __init__(self, value):
        super().__init__(f"FloodWait {value}")
        self.value = value


class PrescanScannerTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_scan_prescan_packages_fetches_batches_and_sleeps_between_batches(self):
        from media_downloader import scan_prescan_packages

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            ),
            MockMessage(
                id=120,
                media="video",
                caption="课程 第02章",
                video=MockVideo(file_name="02.mp4", mime_type="video/mp4", file_size=200),
            ),
        ]

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def get_messages(self, chat_id, message_ids):
                self.calls.append(list(message_ids))
                return [message for message in messages if message.id in message_ids]

        sleep = FakeSleepRecorder()
        client = FakeClient()
        progress_events = []

        async def progress_callback(event):
            progress_events.append(event)

        result = await scan_prescan_packages(
            client,
            chat_id=-1001,
            start_message_id=100,
            max_messages=60,
            batch_size=20,
            batch_delay_seconds=1,
            sleep=sleep,
            progress_callback=progress_callback,
        )

        self.assertEqual(len(client.calls), 3)
        self.assertEqual(sleep.calls, [1, 1])
        self.assertEqual(len(result.packages), 2)
        self.assertEqual(progress_events[-1]["scanned_count"], 2)
        self.assertEqual(progress_events[-1]["package_count"], 2)

    async def test_scan_prescan_packages_sleeps_and_retries_after_floodwait(self):
        from media_downloader import scan_prescan_packages

        message = MockMessage(
            id=100,
            media="video",
            caption="课程 第01章",
            video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
        )

        class FakeClient:
            def __init__(self):
                self.calls = 0

            async def get_messages(self, chat_id, message_ids):
                self.calls += 1
                if self.calls == 1:
                    raise FloodWaitLike(3)
                return [message]

        sleep = FakeSleepRecorder()
        client = FakeClient()
        progress_events = []

        async def progress_callback(event):
            progress_events.append(event)

        result = await scan_prescan_packages(
            client,
            chat_id=-1001,
            start_message_id=100,
            max_messages=10,
            batch_size=10,
            batch_delay_seconds=1,
            sleep=sleep,
            progress_callback=progress_callback,
        )

        self.assertEqual(client.calls, 2)
        self.assertEqual(sleep.calls, [4])
        self.assertEqual(len(result.packages), 1)
        self.assertEqual(progress_events[0]["rate_limited_seconds"], 4)

    async def test_scan_prescan_packages_stops_after_missing_streak_once_media_seen(self):
        from media_downloader import scan_prescan_packages

        messages = [
            MockMessage(
                id=100,
                media="video",
                caption="课程 第01章",
                video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
            )
        ]

        class FakeClient:
            def __init__(self):
                self.calls = []

            async def get_messages(self, chat_id, message_ids):
                self.calls.append(list(message_ids))
                return [message for message in messages if message.id in message_ids]

        result = await scan_prescan_packages(
            FakeClient(),
            chat_id=-1001,
            start_message_id=100,
            max_messages=500,
            batch_size=50,
            batch_delay_seconds=0,
            missing_streak_limit=80,
            sleep=FakeSleepRecorder(),
        )

        self.assertEqual(len(result.packages), 1)
        self.assertLess(result.prescan_plan.scanned_count, 500)
```

- [ ] **Step 2: Run scanner tests and verify they fail**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::PrescanScannerTestCase -q
```

Expected: FAIL because `scan_prescan_packages` does not exist.

- [ ] **Step 3: Add scanner result dataclass**

In `media_downloader.py`, extend the import typing if needed and add this dataclass near `MessagePackageScanResult`:

```python
@dataclass
class PrescanScanResult:
    chat_id: Union[int, str]
    prescan_plan: Any
    messages: list
    failed_message_ids: list
```

- [ ] **Step 4: Implement slow scanner**

Add this function after `scan_message_package(...)`:

```python
async def scan_prescan_packages(
    client: PyrogramClient,
    chat_id: Union[int, str],
    start_message_id: int,
    max_messages: int = 5000,
    max_packages: int = 50,
    missing_streak_limit: int = 200,
    batch_size: int = 50,
    batch_delay_seconds: int = 1,
    sleep=asyncio.sleep,
    progress_callback=None,
) -> PrescanScanResult:
    """Slowly fetch messages and plan multiple media packages for prescan."""

    from module.prescan_workflow import PrescanLimits, plan_prescan_packages

    max_messages = max(0, max_messages)
    batch_size = max(1, batch_size)
    fetched_messages = []
    failed_message_ids = []
    message_ids = list(range(start_message_id, start_message_id + max_messages))
    missing_streak = 0
    saw_message = False

    async def report_progress(rate_limited_seconds=None):
        if not progress_callback:
            return
        current_plan = plan_prescan_packages(
            fetched_messages,
            start_message_id=start_message_id,
            limits=PrescanLimits(
                max_messages=max_messages,
                max_packages=max_packages,
                missing_streak_limit=missing_streak_limit,
            ),
        )
        await progress_callback(
            {
                "scanned_count": len(fetched_messages),
                "package_count": len(current_plan.packages),
                "latest_package": (
                    current_plan.packages[-1]
                    if current_plan.packages
                    else None
                ),
                "rate_limited_seconds": rate_limited_seconds,
            }
        )

    for index in range(0, len(message_ids), batch_size):
        batch_ids = message_ids[index:index + batch_size]
        batch_messages = []
        try:
            batch_messages = await client.get_messages(chat_id, batch_ids)
            if not isinstance(batch_messages, list):
                batch_messages = [batch_messages]
        except Exception as error:
            wait_seconds = getattr(error, "value", None)
            if isinstance(wait_seconds, int) and wait_seconds > 0:
                rate_limit_wait = wait_seconds + 1
                await report_progress(rate_limited_seconds=rate_limit_wait)
                await sleep(rate_limit_wait)
                batch_messages = await client.get_messages(chat_id, batch_ids)
                if not isinstance(batch_messages, list):
                    batch_messages = [batch_messages]
            else:
                logger.error(
                    "scan_prescan_packages: batch fetch failed "
                    f"chat_id={chat_id} ids={batch_ids}: {error}"
                )
                failed_message_ids.extend(batch_ids)

        valid_messages = [
            message
            for message in batch_messages
            if message and hasattr(message, "id")
        ]
        fetched_messages.extend(valid_messages)
        valid_ids = {message.id for message in valid_messages}
        for message_id in batch_ids:
            if message_id in valid_ids:
                saw_message = True
                missing_streak = 0
            elif saw_message:
                missing_streak += 1

        await report_progress()
        if saw_message and missing_streak >= missing_streak_limit:
            break

        if index + batch_size < len(message_ids):
            await sleep(batch_delay_seconds)

    prescan_plan = plan_prescan_packages(
        fetched_messages,
        start_message_id=start_message_id,
        limits=PrescanLimits(
            max_messages=max_messages,
            max_packages=max_packages,
            missing_streak_limit=missing_streak_limit,
        ),
    )
    return PrescanScanResult(
        chat_id=chat_id,
        prescan_plan=prescan_plan,
        messages=fetched_messages,
        failed_message_ids=failed_message_ids,
    )
```

- [ ] **Step 5: Run scanner tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::PrescanScannerTestCase -q
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```bash
git add media_downloader.py tests/module/test_comment_workflow.py
git commit -m "feat: add slow prescan scanner"
```

---

### Task 5: Wire Prescan Preview, Pagination, Selection, And Confirm Callback

**Files:**
- Modify: `module/bot.py`
- Modify: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing bot preview and selection tests**

Add these tests to `BotPrescanWorkflowTestCase`:

```python
async def test_preview_prescan_workflow_stores_plan_and_sends_selection_page(self):
    from module import bot as bot_module
    from module.comment_workflow import build_message_package_workflow_request
    from media_downloader import PrescanScanResult
    from module.prescan_workflow import PrescanLimits, plan_prescan_packages

    request = build_message_package_workflow_request(
        "https://t.me/c/1298283297/126711"
    )
    source_entity = SimpleNamespace(id=-1001298283297, username=None, title="Private Course")
    messages = [
        MockMessage(
            id=126711,
            media="video",
            caption="课程 第01章",
            video=MockVideo(file_name="01.mp4", mime_type="video/mp4", file_size=100),
        )
    ]

    class FakeUserClient:
        async def get_chat(self, chat_id):
            return source_entity

    class FakeBotClient:
        def __init__(self):
            self.sent_messages = []

        async def send_message(self, chat_id, text, **kwargs):
            msg = MockMessage(id=80, chat_id=chat_id, text=text)
            self.sent_messages.append((chat_id, text, kwargs, msg))
            return msg

    async def fake_scan_prescan_packages(client, chat_id, start_message_id, **kwargs):
        plan = plan_prescan_packages(messages, start_message_id, PrescanLimits())
        return PrescanScanResult(chat_id, plan, messages, [])

    old_client = bot_module._bot.client
    old_pending = getattr(bot_module._bot, "pending_prescan_workflows", None)
    try:
        bot_module._bot.client = FakeUserClient()
        bot_module._bot.pending_prescan_workflows = {}
        bot_client = FakeBotClient()
        message = MockMessage(id=9, text=request.url, from_user=MockUser(id=123))

        with patch("media_downloader.scan_prescan_packages", new=fake_scan_prescan_packages):
            await bot_module.preview_prescan_workflow(bot_client, message, request)

        self.assertEqual(len(bot_module._bot.pending_prescan_workflows), 1)
        pending = next(iter(bot_module._bot.pending_prescan_workflows.values()))
        self.assertEqual(pending["channel"], "Private Course")
        self.assertEqual(len(pending["plan"].packages), 1)
        self.assertIn("预扫完成", bot_client.sent_messages[-1][1])
        markup = bot_client.sent_messages[-1][2]["reply_markup"]
        self.assertTrue(markup.inline_keyboard)
    finally:
        bot_module._bot.client = old_client
        if old_pending is None:
            delattr(bot_module._bot, "pending_prescan_workflows")
        else:
            bot_module._bot.pending_prescan_workflows = old_pending
```

- [ ] **Step 2: Run preview test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::BotPrescanWorkflowTestCase::test_preview_prescan_workflow_stores_plan_and_sends_selection_page -q
```

Expected: FAIL because the preview function only acknowledges the task and does not store a plan or send a selection page yet.

- [ ] **Step 3: Add pending workflow storage**

In `DownloadBot.__init__`, add:

```python
self.pending_prescan_workflows: dict = {}
```

- [ ] **Step 4: Add inline keyboard builder**

In `module/bot.py`, add this helper near `preview_prescan_workflow(...)`:

```python
def _build_prescan_selection_buttons(token, plan, selected_package_ids, page):
    """Build inline buttons for one prescan selection page."""

    from module.prescan_workflow import PRESCAN_PAGE_SIZE, page_packages

    rows = []
    current_row = []
    for package in page_packages(plan, page, PRESCAN_PAGE_SIZE):
        selected = package.package_id in selected_package_ids
        label = f"{'[x]' if selected else '[ ]'} {package.package_id}"
        current_row.append(
            InlineKeyboardButton(
                label,
                callback_data=build_prescan_callback_data(
                    token, "toggle", package.package_id
                ),
            )
        )
        if len(current_row) == 4:
            rows.append(current_row)
            current_row = []
    if current_row:
        rows.append(current_row)

    nav_row = []
    if page > 0:
        nav_row.append(
            InlineKeyboardButton(
                "上一页",
                callback_data=build_prescan_callback_data(token, "page", page - 1),
            )
        )
    if (page + 1) * PRESCAN_PAGE_SIZE < len(plan.packages):
        nav_row.append(
            InlineKeyboardButton(
                "下一页",
                callback_data=build_prescan_callback_data(token, "page", page + 1),
            )
        )
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                "全选本页",
                callback_data=build_prescan_callback_data(token, "select_page", page),
            ),
            InlineKeyboardButton(
                "清空选择",
                callback_data=build_prescan_callback_data(token, "clear"),
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "下载已选",
                callback_data=build_prescan_callback_data(token, "download"),
            ),
            InlineKeyboardButton(
                "取消",
                callback_data=build_prescan_callback_data(token, "cancel"),
            ),
        ]
    )
    return InlineKeyboardMarkup(rows)
```

- [ ] **Step 5: Implement `preview_prescan_workflow(...)`**

Replace the Task 3 minimal implementation with:

```python
async def preview_prescan_workflow(client, message, workflow_request):
    """Scan from a pasted ordinary link and show multi-package selection."""

    from media_downloader import scan_prescan_packages

    try:
        entity = await _bot.client.get_chat(workflow_request.source_chat)
        status_message = await client.send_message(
            message.from_user.id,
            f"预扫中...\n起点：{workflow_request.start_message_id}",
            reply_to_message_id=message.id,
        )

        async def progress_callback(event):
            progress_text = summarize_prescan_progress(
                workflow_request.start_message_id,
                event.get("scanned_count", 0),
                event.get("package_count", 0),
                latest_package=event.get("latest_package"),
                rate_limited_seconds=event.get("rate_limited_seconds"),
            )
            try:
                await client.edit_message_text(
                    message.from_user.id,
                    status_message.id,
                    progress_text,
                )
            except Exception as progress_error:
                logger.warning(f"prescan progress edit failed: {progress_error}")

        scan_result = await scan_prescan_packages(
            _bot.client,
            entity.id,
            workflow_request.start_message_id,
            progress_callback=progress_callback,
        )
        plan = scan_result.prescan_plan
        if not plan.packages:
            await client.send_message(
                message.from_user.id,
                "未找到可下载的资源包。",
                reply_to_message_id=message.id,
            )
            return

        token = build_workflow_token(workflow_request.url, message.from_user.id)
        channel = entity.username or entity.title or str(entity.id)
        selected_package_ids = set()
        _bot.pending_prescan_workflows[token] = {
            "request": workflow_request,
            "entity_id": entity.id,
            "channel": channel,
            "plan": plan,
            "selected_package_ids": selected_package_ids,
            "page": 0,
            "source_message_id": message.id,
            "status_message_id": status_message.id,
        }
        text = format_prescan_selection_page(
            plan,
            channel=channel,
            page=0,
            selected_package_ids=selected_package_ids,
        )
        await client.send_message(
            message.from_user.id,
            text,
            reply_markup=_build_prescan_selection_buttons(
                token, plan, selected_package_ids, 0
            ),
            reply_to_message_id=message.id,
        )
    except Exception as error:
        logger.error(f"preview_prescan_workflow: failed: {error}", exc_info=True)
        await client.send_message(
            message.from_user.id,
            f"预扫失败：{error}",
            reply_to_message_id=message.id,
        )
```

- [ ] **Step 6: Implement prescan callback handler**

Add this before `handle_package_workflow_callback(...)`:

```python
async def handle_prescan_workflow_callback(client, query):
    """Handle prescan selection, pagination, cancellation, and download."""

    data = getattr(query, "data", None)
    if not data or not data.startswith(f"{PRESCAN_WORKFLOW_PREFIX}:"):
        return False

    parsed = parse_prescan_callback_data(data)
    message = getattr(query, "message", None)
    chat_id = _callback_chat_id(query)
    message_id = getattr(message, "id", None)
    if not parsed:
        await client.edit_message_text(chat_id, message_id, "无效的预扫操作。")
        return True

    token, action, value = parsed
    pending = _bot.pending_prescan_workflows.get(token)
    if not pending:
        await client.edit_message_text(chat_id, message_id, "预扫任务已过期，请重新开始。")
        return True

    plan = pending["plan"]
    selected_package_ids = pending["selected_package_ids"]
    page = pending.get("page", 0)

    if action == "cancel":
        _bot.pending_prescan_workflows.pop(token, None)
        await client.edit_message_text(chat_id, message_id, "已取消预扫任务。")
        return True
    if action == "toggle":
        package_id = int(value)
        if package_id in selected_package_ids:
            selected_package_ids.remove(package_id)
        else:
            selected_package_ids.add(package_id)
    elif action == "page":
        page = int(value)
        pending["page"] = page
    elif action == "select_page":
        from module.prescan_workflow import PRESCAN_PAGE_SIZE, page_packages

        page = int(value)
        pending["page"] = page
        for package in page_packages(plan, page, PRESCAN_PAGE_SIZE):
            selected_package_ids.add(package.package_id)
    elif action == "clear":
        selected_package_ids.clear()
    elif action == "download":
        if not selected_package_ids:
            await client.edit_message_text(
                chat_id,
                message_id,
                format_prescan_selection_page(
                    plan,
                    pending["channel"],
                    page,
                    selected_package_ids,
                )
                + "\n\n请先选择至少一个包。",
                reply_markup=_build_prescan_selection_buttons(
                    token, plan, selected_package_ids, page
                ),
            )
            return True
        await start_prescan_selected_download(client, query, token, pending)
        return True

    await client.edit_message_text(
        chat_id,
        message_id,
        format_prescan_selection_page(
            plan,
            pending["channel"],
            page,
            selected_package_ids,
        ),
        reply_markup=_build_prescan_selection_buttons(
            token, plan, selected_package_ids, page
        ),
    )
    return True
```

Add this small acknowledgement function below it. Task 6 replaces it with the serial downloader handoff.

```python
async def start_prescan_selected_download(client, query, token, pending):
    """Acknowledge selected downloads before serial orchestration is added."""

    chat_id = _callback_chat_id(query)
    message_id = getattr(getattr(query, "message", None), "id", None)
    await client.edit_message_text(chat_id, message_id, "预扫下载任务已接收。")
```

In `on_query_handler(...)`, add prescan handling first:

```python
if await handle_prescan_workflow_callback(client, query):
    return
```

- [ ] **Step 7: Run prescan bot tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::BotPrescanWorkflowTestCase -q
```

Expected: PASS.

- [ ] **Step 8: Commit Task 5**

```bash
git add module/bot.py tests/module/test_comment_workflow.py
git commit -m "feat: wire prescan package selection"
```

---

### Task 6: Add Serial Selected-Package Downloads And Docs

**Files:**
- Modify: `media_downloader.py`
- Modify: `module/bot.py`
- Modify: `README_CN.md`
- Modify: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing serial download test**

Add this test to a suitable async test class:

```python
async def test_download_prescan_packages_runs_selected_packages_serially(self):
    from media_downloader import download_prescan_packages
    from module.comment_workflow import NamingStrategy, PackageNamingContext, plan_message_package
    from module.prescan_workflow import PrescanPackage
    from module.app import TaskNode

    first_messages = [
        MockMessage(
            id=100,
            media="video",
            caption="课程 第01章",
            video=MockVideo(file_name="01.mp4", mime_type="video/mp4"),
        )
    ]
    second_messages = [
        MockMessage(
            id=120,
            media="video",
            caption="课程 第02章",
            video=MockVideo(file_name="02.mp4", mime_type="video/mp4"),
        )
    ]
    first_plan = plan_message_package(first_messages, 100)
    second_plan = plan_message_package(second_messages, 120)
    packages = [
        PrescanPackage(1, "课程 第01章", 100, 100, first_plan.items, first_plan, first_messages),
        PrescanPackage(2, "课程 第02章", 120, 120, second_plan.items, second_plan, second_messages),
    ]
    node = TaskNode(chat_id=-1001, bot=None, task_id=99)
    node.client = object()
    calls = []

    async def fake_download_prepared_messages(messages, download_filter, package_node, failed_message_ids=None):
        calls.append(
            (
                [message.id for message in messages],
                package_node.package_naming_context.start_message_id,
                package_node.package_naming_context.package_title,
            )
        )

    with patch("media_downloader.download_prepared_messages", new=fake_download_prepared_messages):
        await download_prescan_packages(
            packages,
            channel="Private Course",
            parent_node=node,
            selected_package_ids={1, 2},
        )

    self.assertEqual(
        calls,
        [
            ([100], 100, "课程 第01章"),
            ([120], 120, "课程 第02章"),
        ],
    )
    self.assertEqual(node.package_naming_context.strategy, NamingStrategy.RECOMMENDED)
    self.assertEqual(node.package_naming_context.channel, "Private Course")
```

- [ ] **Step 2: Run serial test and verify it fails**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::BotCommentWorkflowCallbackTestCase::test_download_prescan_packages_runs_selected_packages_serially -q
```

Expected: FAIL because `download_prescan_packages` does not exist.

- [ ] **Step 3: Implement serial download orchestrator**

Add to `media_downloader.py` after `download_prepared_messages(...)`:

```python
async def download_prescan_packages(
    packages,
    channel: str,
    parent_node,
    selected_package_ids,
):
    """Download selected prescan packages one after another using C naming."""

    from module.comment_workflow import NamingStrategy, PackageNamingContext

    selected_ids = set(selected_package_ids)
    ordered_packages = [
        package
        for package in sorted(packages, key=lambda item: item.start_message_id)
        if package.package_id in selected_ids
    ]

    for index, package in enumerate(ordered_packages, start=1):
        if not parent_node.is_running or parent_node.is_stop_transmission:
            logger.info(
                f"Prescan parent task stopped before package {package.package_id}"
            )
            break

        parent_node.package_naming_context = PackageNamingContext(
            strategy=NamingStrategy.RECOMMENDED,
            channel=channel,
            start_message_id=package.start_message_id,
            package_title=package.title,
        )
        parent_node.package_plan = package.package_plan
        parent_node.package_media_items = {
            item.message.id: item
            for item in package.items
        }
        parent_node.replay_message = (
            f"批量下载中：包 {index}/{len(ordered_packages)} "
            f"{package.start_message_id}-{package.end_message_id} {package.title}"
        )
        await download_prepared_messages(
            package.messages,
            None,
            parent_node,
            failed_message_ids=package.failed_message_ids,
        )
```

- [ ] **Step 4: Wire callback download starter**

Replace the Task 5 acknowledgement `start_prescan_selected_download(...)` in `module/bot.py` with:

```python
async def start_prescan_selected_download(client, query, token, pending):
    """Create one parent task and serially download selected prescan packages."""

    chat_id = _callback_chat_id(query)
    message_id = getattr(getattr(query, "message", None), "id", None)
    selected_package_ids = set(pending["selected_package_ids"])
    selected_count = len(selected_package_ids)

    await client.edit_message_text(
        chat_id,
        message_id,
        f"已确认 {selected_count} 个包，开始按推荐C格式串行下载。",
    )
    status_message = await client.send_message(
        chat_id,
        f"预扫批量下载任务已启动：{pending['channel']} / {selected_count} 个包",
        reply_to_message_id=pending.get("source_message_id"),
    )

    node = TaskNode(
        chat_id=pending["entity_id"],
        from_user_id=chat_id,
        reply_message_id=status_message.id,
        bot=_bot.bot,
        task_id=_bot.gen_task_id(),
    )
    node.client = _bot.client
    node.is_running = True

    from media_downloader import download_prescan_packages

    download_coroutine = download_prescan_packages(
        pending["plan"].packages,
        pending["channel"],
        node,
        selected_package_ids,
    )
    try:
        _bot.app.loop.create_task(download_coroutine)
    except Exception:
        download_coroutine.close()
        raise

    _bot.add_task_node(node)
    add_active_task_node(node)
    _bot.pending_prescan_workflows.pop(token, None)
```

- [ ] **Step 5: Update README_CN**

Add after the private-message package section in `README_CN.md`:

```markdown
#### 预扫模式批量资源包选择

在 Telegram bot 菜单里点击 `预扫模式`，然后发送起始频道消息链接：

```text
https://t.me/c/1446289027/156439
```

bot 会从这条消息开始慢速向后扫描，识别多个连续资源包，并用按钮分页展示。你可以勾选需要下载的包，再点击 `下载已选`。

预扫模式固定使用推荐 C 命名：

```text
频道名/起始ID-包标题/消息ID - 原文件名.ext
```

扫描会分批请求并在批次之间暂停；如果 Telegram 返回限流等待，bot 会等待后继续。选中多个包时不会同时并发下载，而是按消息顺序一个包一个包串行下载。
```

- [ ] **Step 6: Run focused tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_prescan_workflow.py tests/module/test_comment_workflow.py -q
```

Expected: PASS.

- [ ] **Step 7: Run full verification**

Run:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m py_compile module/comment_workflow.py module/prescan_workflow.py module/bot.py media_downloader.py
git diff --check
```

Expected: all tests pass, py_compile exits 0, and `git diff --check` prints nothing.

- [ ] **Step 8: Commit Task 6**

```bash
git add media_downloader.py module/bot.py README_CN.md tests/module/test_comment_workflow.py
git commit -m "feat: download selected prescan packages serially"
```

---

## Final Verification

- [ ] Run full test suite:

```bash
.venv/bin/python -m pytest -q
```

Expected: all tests pass.

- [ ] Run compile check:

```bash
.venv/bin/python -m py_compile module/comment_workflow.py module/prescan_workflow.py module/bot.py media_downloader.py
```

Expected: no output and exit code 0.

- [ ] Run whitespace check:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] Inspect final diff:

```bash
git status --short
git diff --stat
```

Expected: only implementation files from this plan are modified; unrelated `.gitignore` local changes remain unstaged unless the user explicitly asks otherwise.

## Self-Review Notes

- Spec coverage:
  - Menu entry and no manual typing: Task 3.
  - C-only guided interactions: Task 1.
  - Slow bounded scan and FloodWait handling: Task 4.
  - Multiple package detection and selection: Tasks 2 and 5.
  - Serial downloads, not parallel selected packages: Task 6.
  - Docs and regression verification: Task 6 and Final Verification.
- Red-flag scan: no unresolved markers or incomplete implementation gaps remain in this plan.
- Type consistency:
  - Prescan callback data uses `ps:<token>:<action>[:value]` throughout.
  - `PrescanPackage.package_id` is the selection id throughout.
  - Bot pending state uses `pending_prescan_sessions` for awaiting-link mode and `pending_prescan_workflows` for package selection.

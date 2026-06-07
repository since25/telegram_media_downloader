# Private Message Link Package Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a guided bot workflow where pasting an ordinary/private Telegram message link scans one continuous media package, previews size and naming, and downloads/uploads only after confirmation.

**Architecture:** Extend the existing pure `module/comment_workflow.py` helpers into shared guided-media workflow helpers for ordinary message packages and comment links. Keep Telegram I/O in `module/bot.py` and `media_downloader.py`, store prepared messages in short-lived pending state, and reuse the existing task queue/rclone upload/delete path.

**Tech Stack:** Python 3.11 via project `.venv`, Pyrogram message metadata, unittest/pytest, existing `TaskNode`, existing `utils.format.extract_info_from_link`, existing `utils.format.validate_title`, existing `format_byte` helper.

---

## File Structure

- Modify `module/comment_workflow.py`: add package request dataclasses, caption normalization/comparison helpers, size summary helpers, package naming helpers, package preview formatter, and package callback parsing/building. Also extend comment preview formatting with size summaries.
- Modify `media_downloader.py`: add `scan_message_package` and `download_prepared_messages`, both reusing `download_media`; extend `_get_media_meta` to support a package naming context without breaking comment naming.
- Modify `module/app.py`: add optional `package_naming_context` field to `TaskNode`.
- Modify `module/bot.py`: route direct ordinary message links into package preview, maintain pending package workflow state, render package buttons, handle package callbacks, and keep comment callbacks intact.
- Modify `tests/test_common.py`: ensure mock media/messages expose `file_size`, `media_group_id`, captions, dates, users, and filenames needed by package tests.
- Modify `tests/module/test_comment_workflow.py`: add pure tests for package parsing, caption inheritance, boundary detection, size summary, preview formatting, and bot callback behavior.
- Modify `tests/test_media_downloader.py`: add focused tests for package naming context in `_get_media_meta` and prepared-message download accounting.
- Modify `README_CN.md`: document direct private message package workflow and size preview after tests pass.

---

### Task 1: Add Pure Package Parser and Size Summary

**Files:**
- Modify: `module/comment_workflow.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing tests for ordinary/private link parsing and size summary**

Append these tests to `CommentWorkflowTestCase` in `tests/module/test_comment_workflow.py`:

```python
    def test_build_message_package_workflow_request_from_private_link(self):
        from module.comment_workflow import build_message_package_workflow_request

        request = build_message_package_workflow_request(
            "https://t.me/c/1298283297/126711"
        )

        self.assertEqual(request.source_chat, -1001298283297)
        self.assertEqual(request.start_message_id, 126711)
        self.assertEqual(request.url, "https://t.me/c/1298283297/126711")

    def test_build_message_package_workflow_request_rejects_comment_link(self):
        from module.comment_workflow import build_message_package_workflow_request

        self.assertIsNone(
            build_message_package_workflow_request(
                "https://t.me/zhyseseb/422?comment=4978"
            )
        )

    def test_build_size_summary_counts_known_unknown_and_largest(self):
        from module.comment_workflow import build_size_summary, format_size_summary

        messages = [
            MockMessage(
                id=126711,
                media="video",
                video=MockVideo(file_name="a.mp4", file_size=421 * 1024 * 1024),
            ),
            MockMessage(
                id=126712,
                media="video",
                video=MockVideo(file_name="b.mp4", file_size=388 * 1024 * 1024),
            ),
            MockMessage(
                id=126713,
                media="photo",
                photo=MockPhoto(file_unique_id="p1"),
            ),
        ]
        delattr(messages[2].photo, "file_size")

        summary = build_size_summary(messages)

        self.assertEqual(summary.known_total_size, 809 * 1024 * 1024)
        self.assertEqual(summary.unknown_size_count, 1)
        self.assertEqual(summary.largest.message_id, 126711)
        self.assertEqual(summary.samples[0].message_id, 126711)
        self.assertIn("809.00MB", format_size_summary(summary))
        self.assertIn("1 个未知大小文件", format_size_summary(summary))
```

- [ ] **Step 2: Run tests to verify missing symbols fail**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_message_package_workflow_request_from_private_link tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_message_package_workflow_request_rejects_comment_link tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_size_summary_counts_known_unknown_and_largest -v
```

Expected: FAIL with import errors for `build_message_package_workflow_request` or `build_size_summary`.

- [ ] **Step 3: Implement dataclasses, parser, and size helpers**

In `module/comment_workflow.py`, add imports and symbols near the existing dataclasses:

```python
import re
from utils.format import extract_info_from_link, format_byte, validate_title

PACKAGE_WORKFLOW_PREFIX = "pw"

@dataclass
class MessagePackageWorkflowRequest:
    """Parsed direct ordinary message-link package workflow request."""

    url: str
    source_chat: str | int
    start_message_id: int


@dataclass
class SizePreviewItem:
    """Small size preview entry for one media message."""

    message_id: int
    media_type: str
    size: int
    file_name: str


@dataclass
class SizeSummary:
    """Known and unknown file-size summary for preview."""

    known_total_size: int = 0
    unknown_size_count: int = 0
    samples: List[SizePreviewItem] = field(default_factory=list)
    largest: Optional[SizePreviewItem] = None
```

Add these helpers below `build_comment_workflow_request`:

```python
def build_message_package_workflow_request(
    text: str,
) -> Optional[MessagePackageWorkflowRequest]:
    """Return a package workflow request for direct non-comment message links."""

    if not text:
        return None

    url = text.strip()
    if not url.startswith("https://t.me"):
        return None

    link = extract_info_from_link(url)
    if link.group_id is None or link.post_id is None or link.comment_id is not None:
        return None
    if "comment" in url:
        return None

    return MessagePackageWorkflowRequest(
        url=url,
        source_chat=link.group_id,
        start_message_id=link.post_id,
    )


def media_payload_for_message(message: CommentLike):
    """Return `(media_type, media_obj)` for a supported media message."""

    if not message or getattr(message, "empty", False):
        return None, None
    media_name = _media_name(message)
    if media_name not in SUPPORTED_MEDIA_TYPES:
        return None, None
    media_obj = getattr(message, media_name, None)
    if not media_obj:
        return None, None
    return media_name, media_obj


def media_file_name_for_message(message: CommentLike) -> str:
    """Return a stable display filename for size previews."""

    media_name, media_obj = media_payload_for_message(message)
    raw_file_name = getattr(media_obj, "file_name", None)
    if raw_file_name:
        return clean_segment(raw_file_name, f"message-{message.id}-{media_name}", 80)
    if media_name == "photo":
        unique_id = getattr(media_obj, "file_unique_id", None)
        return clean_segment(unique_id, f"message-{message.id}-photo", 80)
    return clean_segment(None, f"message-{message.id}-{media_name}", 80)


def build_size_summary(messages: Sequence[CommentLike], sample_size: int = 3) -> SizeSummary:
    """Build known/unknown size preview from Telegram media metadata."""

    summary = SizeSummary()
    for message in filter_media_comments(messages):
        media_type, media_obj = media_payload_for_message(message)
        size = getattr(media_obj, "file_size", None)
        if not isinstance(size, int) or size <= 0:
            summary.unknown_size_count += 1
            continue

        item = SizePreviewItem(
            message_id=message.id,
            media_type=media_type,
            size=size,
            file_name=media_file_name_for_message(message),
        )
        summary.known_total_size += size
        if len(summary.samples) < sample_size:
            summary.samples.append(item)
        if summary.largest is None or item.size > summary.largest.size:
            summary.largest = item

    return summary


def format_size_summary(summary: SizeSummary) -> str:
    """Format a compact Chinese size summary for Telegram previews."""

    if summary.known_total_size <= 0 and summary.unknown_size_count:
        return "预计大小：未知"
    if summary.known_total_size <= 0:
        return "预计大小：0B"

    text = f"预计大小：{format_byte(summary.known_total_size)}"
    if summary.unknown_size_count:
        text += f" + {summary.unknown_size_count} 个未知大小文件"
    return text
```

- [ ] **Step 4: Run focused tests to verify parser and size summary pass**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_message_package_workflow_request_from_private_link tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_message_package_workflow_request_rejects_comment_link tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_size_summary_counts_known_unknown_and_largest -v
```

Expected: PASS.

- [ ] **Step 5: Commit pure parser and size helpers**

```bash
git add module/comment_workflow.py tests/module/test_comment_workflow.py
git commit -m "feat: parse private package links and summarize sizes"
```

---

### Task 2: Add Caption Continuity and Package Preview Planning

**Files:**
- Modify: `module/comment_workflow.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing caption inheritance and boundary tests**

Append these tests to `CommentWorkflowTestCase`:

```python
    def test_plan_message_package_inherits_caption_and_excludes_next_package(self):
        from module.comment_workflow import plan_message_package

        messages = [
            MockMessage(
                id=126711,
                media="video",
                caption="某某课程 第01章 01/40",
                video=MockVideo(file_name="001.mp4", file_size=100),
            ),
            MockMessage(
                id=126712,
                media="video",
                video=MockVideo(file_name="002.mp4", file_size=200),
            ),
            MockMessage(
                id=126713,
                media="video",
                caption="某某课程 第01章 02/40",
                video=MockVideo(file_name="003.mp4", file_size=300),
            ),
            MockMessage(
                id=126714,
                media="video",
                caption="某某课程 第02章",
                video=MockVideo(file_name="004.mp4", file_size=400),
            ),
        ]

        plan = plan_message_package(messages, start_message_id=126711)

        self.assertEqual([item.message.id for item in plan.items], [126711, 126712, 126713])
        self.assertEqual(plan.package_title, "某某课程 第01章 01_40")
        self.assertEqual(plan.inherited_caption_count, 1)
        self.assertEqual(plan.next_package_message.id, 126714)
        self.assertEqual(plan.summary.media_count, 3)
        self.assertEqual(plan.size_summary.known_total_size, 600)

    def test_plan_message_package_shares_album_caption_by_media_group(self):
        from module.comment_workflow import plan_message_package

        messages = [
            MockMessage(
                id=10,
                media="photo",
                media_group_id="album1",
                caption="相册标题 EP01",
                photo=MockPhoto(file_unique_id="p10", file_size=10),
            ),
            MockMessage(
                id=11,
                media="photo",
                media_group_id="album1",
                photo=MockPhoto(file_unique_id="p11", file_size=11),
            ),
            MockMessage(
                id=12,
                media="photo",
                media_group_id="album1",
                photo=MockPhoto(file_unique_id="p12", file_size=12),
            ),
        ]

        plan = plan_message_package(messages, start_message_id=10)

        self.assertEqual([item.caption_for_naming for item in plan.items], ["相册标题 EP01", "相册标题 EP01", "相册标题 EP01"])
        self.assertEqual(plan.inherited_caption_count, 2)
```

- [ ] **Step 2: Run tests to verify missing planner fails**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_plan_message_package_inherits_caption_and_excludes_next_package tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_plan_message_package_shares_album_caption_by_media_group -v
```

Expected: FAIL with import error for `plan_message_package`.

- [ ] **Step 3: Implement package planning dataclasses and caption comparison**

In `module/comment_workflow.py`, add dataclasses after `SizeSummary`:

```python
@dataclass
class PackageMediaItem:
    """Prepared media item with inherited caption metadata."""

    message: CommentLike
    media_type: str
    caption_for_naming: str
    original_caption: Optional[str]
    inherited_caption: bool = False


@dataclass
class MessagePackagePlan:
    """Pure package detection result."""

    items: List[PackageMediaItem]
    package_title: str
    summary: CommentScanSummary
    size_summary: SizeSummary
    inherited_caption_count: int = 0
    next_package_message: Optional[CommentLike] = None
    scan_warning: Optional[str] = None
```

Add helpers below `format_size_summary`:

```python
_NUMBERING_PATTERNS = [
    re.compile(r"\bEP\s*\d+\b", re.IGNORECASE),
    re.compile(r"第\s*\d+\s*[章节集部课]"),
    re.compile(r"\b\d+\s*/\s*\d+\b"),
    re.compile(r"^[\[【(（]?\s*\d{1,4}\s*[\]】)）]?"),
    re.compile(r"[\[【(（]?\s*\d{1,4}\s*[\]】)）]?$"),
]


def normalize_caption_for_boundary(caption: Optional[str]) -> str:
    """Normalize captions before deciding whether a new package started."""

    text = validate_title((caption or "").strip())
    text = re.sub(r"\s+", "", text)
    for pattern in _NUMBERING_PATTERNS:
        text = pattern.sub("", text)
    return text.strip("-_—:：.。 ")


def captions_are_similar(current: Optional[str], candidate: Optional[str]) -> bool:
    """Return True when captions should stay in the same package."""

    current_norm = normalize_caption_for_boundary(current)
    candidate_norm = normalize_caption_for_boundary(candidate)
    if not current_norm or not candidate_norm:
        return True
    if current_norm == candidate_norm:
        return True
    shorter, longer = sorted([current_norm, candidate_norm], key=len)
    return len(shorter) >= 4 and shorter in longer


def _message_caption(message: CommentLike) -> Optional[str]:
    caption = getattr(message, "caption", None)
    if caption:
        return validate_title(caption)
    return None


def plan_message_package(
    messages: Sequence[CommentLike],
    start_message_id: int,
    max_scan_count: int = 500,
) -> MessagePackagePlan:
    """Detect one continuous package from already-fetched messages."""

    scanned_messages = [message for message in messages if message and hasattr(message, "id")]
    scanned_messages = [message for message in scanned_messages if message.id >= start_message_id]
    scanned_messages = scanned_messages[:max_scan_count]

    current_caption: Optional[str] = None
    group_captions: Dict[str, str] = {}
    items: List[PackageMediaItem] = []
    next_package_message = None

    for message in scanned_messages:
        media_type, _ = media_payload_for_message(message)
        if not media_type:
            continue

        raw_caption = _message_caption(message)
        media_group_id = getattr(message, "media_group_id", None)
        group_key = str(media_group_id) if media_group_id is not None else None
        if raw_caption and group_key:
            group_captions[group_key] = raw_caption
        if not raw_caption and group_key:
            raw_caption = group_captions.get(group_key)

        if raw_caption:
            if current_caption and not captions_are_similar(current_caption, raw_caption):
                next_package_message = message
                break
            current_caption = current_caption or raw_caption

        caption_for_naming = raw_caption or current_caption or f"message-{start_message_id}"
        inherited = raw_caption is None and current_caption is not None
        items.append(
            PackageMediaItem(
                message=message,
                media_type=media_type,
                caption_for_naming=caption_for_naming,
                original_caption=raw_caption,
                inherited_caption=inherited,
            )
        )

    package_messages = [item.message for item in items]
    package_title = current_caption or f"message-{start_message_id}"
    warning = None
    if len(scanned_messages) >= max_scan_count and next_package_message is None:
        warning = f"未发现下一包边界，已达到扫描上限 {max_scan_count} 条。"

    return MessagePackagePlan(
        items=items,
        package_title=package_title,
        summary=summarize_comments(package_messages),
        size_summary=build_size_summary(package_messages),
        inherited_caption_count=sum(1 for item in items if item.inherited_caption),
        next_package_message=next_package_message,
        scan_warning=warning,
    )
```

- [ ] **Step 4: Run caption planner tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_plan_message_package_inherits_caption_and_excludes_next_package tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_plan_message_package_shares_album_caption_by_media_group -v
```

Expected: PASS.

- [ ] **Step 5: Commit package planner**

```bash
git add module/comment_workflow.py tests/module/test_comment_workflow.py
git commit -m "feat: plan caption-based media packages"
```

---

### Task 3: Add Package Naming and Preview Formatting

**Files:**
- Modify: `module/comment_workflow.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing tests for package naming and preview text**

Append these tests to `CommentWorkflowTestCase`:

```python
    def test_build_package_naming_previews_and_preview_message(self):
        from module.comment_workflow import (
            build_package_naming_previews,
            format_package_preview_message,
            plan_message_package,
        )

        messages = [
            MockMessage(
                id=126711,
                media="video",
                caption="某某课程 第01章",
                video=MockVideo(file_name="001/bad?.mp4", file_size=421 * 1024 * 1024),
            ),
            MockMessage(
                id=126712,
                media="video",
                video=MockVideo(file_name="002.mp4", file_size=388 * 1024 * 1024),
            ),
            MockMessage(
                id=126713,
                media="video",
                caption="某某课程 第02章",
                video=MockVideo(file_name="003.mp4", file_size=402 * 1024 * 1024),
            ),
        ]
        package_plan = plan_message_package(messages, start_message_id=126711)
        previews = build_package_naming_previews(
            package_plan.items,
            channel="私密频道",
            start_message_id=126711,
            package_title=package_plan.package_title,
        )
        preview_text = format_package_preview_message(
            channel="私密频道",
            start_message_id=126711,
            package_plan=package_plan,
            previews=previews,
            upload_enabled=True,
            delete_after_upload=True,
        )

        self.assertIn("识别到连续资源包", preview_text)
        self.assertIn("范围：126711 - 126712", preview_text)
        self.assertIn("预计大小：809.00MB", preview_text)
        self.assertIn("继承 caption：1 个", preview_text)
        self.assertIn("下一包起点预览：", preview_text)
        self.assertIn("126713 - 某某课程 第02章", preview_text)
        self.assertIn("私密频道/126711-某某课程 第01章/126711 - 001_bad_.mp4", preview_text)
```

- [ ] **Step 2: Run test to verify missing preview functions fail**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_package_naming_previews_and_preview_message -v
```

Expected: FAIL with import errors for package preview functions.

- [ ] **Step 3: Implement package naming context and preview formatting**

In `module/comment_workflow.py`, add dataclass near `CommentNamingContext`:

```python
@dataclass
class PackageNamingContext:
    """Values used to build final names for package media files."""

    strategy: NamingStrategy
    channel: str
    start_message_id: int
    package_title: str
```

Add naming helpers after `build_name_for_strategy`:

```python
def build_package_name_for_strategy(
    item: PackageMediaItem,
    context: PackageNamingContext,
) -> str:
    """Build a relative display path for a package media item."""

    message = item.message
    channel = clean_segment(context.channel, "channel", 40)
    title = clean_segment(context.package_title, f"message-{context.start_message_id}", 60)
    original_file_name = media_file_name_for_message(message)
    caption_summary = clean_segment(item.caption_for_naming, "no-caption", 40)
    extension = _extension_for_comment(message)

    if context.strategy is NamingStrategy.AUTHOR:
        return f"{title}/{message.id} - {author_for_comment(message)} - {original_file_name}"
    if context.strategy is NamingStrategy.CAPTION:
        return f"{title}/{message.id} - {caption_summary} - {original_file_name}"
    if context.strategy is NamingStrategy.MONTH_CAPTION:
        return f"{channel}/{month_for_comment(message)}/{title}/{message.id} - {caption_summary}.{extension}"
    return f"{channel}/{context.start_message_id}-{title}/{message.id} - {original_file_name}"


def build_package_naming_previews(
    items: Sequence[PackageMediaItem],
    channel: str,
    start_message_id: int,
    package_title: str,
    sample_size: int = 3,
) -> List[NamingPreview]:
    """Build concrete preview examples for package naming strategies."""

    sample_items = list(items)[:sample_size]
    strategies = [
        (NamingStrategy.RECOMMENDED, "推荐C：频道/起始ID-标题/消息ID - 原文件名"),
        (NamingStrategy.AUTHOR, "A：标题/消息ID - 作者 - 原文件名"),
        (NamingStrategy.CAPTION, "B：标题/消息ID - caption摘要 - 原文件名"),
        (NamingStrategy.MONTH_CAPTION, "D：频道/年月/标题/消息ID - caption摘要"),
    ]
    previews: List[NamingPreview] = []
    for strategy, title in strategies:
        context = PackageNamingContext(strategy, channel, start_message_id, package_title)
        previews.append(
            NamingPreview(
                strategy=strategy,
                title=title,
                examples=[build_package_name_for_strategy(item, context) for item in sample_items],
            )
        )
    return previews
```

Add preview formatter near `format_preview_message`:

```python
def _format_size_details(summary: SizeSummary) -> List[str]:
    lines = [format_size_summary(summary)]
    if summary.largest:
        lines.append(
            f"最大文件：{summary.largest.message_id} {summary.largest.media_type} {format_byte(summary.largest.size)}"
        )
    if summary.samples:
        lines.append("大小示例：")
        for item in summary.samples:
            lines.append(f"- {item.message_id} {item.media_type} {format_byte(item.size)}")
    return lines


def _preview_caption(message: CommentLike) -> str:
    caption = getattr(message, "caption", None)
    if caption:
        return clean_segment(caption, f"message-{message.id}", 60)
    return clean_segment(None, f"message-{message.id}", 60)


def format_package_preview_message(
    channel: str,
    start_message_id: int,
    package_plan: MessagePackagePlan,
    previews: Sequence[NamingPreview],
    upload_enabled: bool,
    delete_after_upload: bool,
) -> str:
    """Format package workflow preview text."""

    media_ids = [item.message.id for item in package_plan.items]
    range_text = f"{min(media_ids)} - {max(media_ids)}" if media_ids else "无"
    media_types = ", ".join(
        f"{key} {value} 个" for key, value in sorted(package_plan.summary.media_type_counts.items())
    ) or "无"

    lines = [
        "识别到连续资源包：",
        f"频道：{channel}",
        f"标题：{package_plan.package_title}",
        f"范围：{range_text}",
        f"媒体：{package_plan.summary.media_count} 个（{media_types}）",
        *_format_size_details(package_plan.size_summary),
        f"继承 caption：{package_plan.inherited_caption_count} 个",
        f"rclone上传：{'开启' if upload_enabled else '关闭'}",
        f"上传后删除本地：{'开启' if delete_after_upload else '关闭'}",
    ]
    if package_plan.scan_warning:
        lines.append(f"提示：{package_plan.scan_warning}")
    if package_plan.next_package_message:
        lines.extend(
            [
                "",
                "下一包起点预览：",
                f"{package_plan.next_package_message.id} - {_preview_caption(package_plan.next_package_message)}",
                "不会纳入本次下载。",
            ]
        )
    lines.append("")
    lines.append("命名预览：")
    for preview in previews:
        lines.append(preview.title)
        lines.extend(f"- {example}" for example in preview.examples)
    return "\n".join(lines)
```

- [ ] **Step 4: Run package preview test**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_package_naming_previews_and_preview_message -v
```

Expected: PASS.

- [ ] **Step 5: Commit package preview helpers**

```bash
git add module/comment_workflow.py tests/module/test_comment_workflow.py
git commit -m "feat: preview package naming and sizes"
```

---

### Task 4: Add Comment Workflow Size Preview

**Files:**
- Modify: `module/comment_workflow.py`
- Modify: `module/bot.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing test for comment preview size text**

Modify `test_format_preview_message_contains_summary_and_examples` in `tests/module/test_comment_workflow.py` so it passes `size_summary=build_size_summary(comments)` and asserts size text:

```python
        from module.comment_workflow import build_size_summary

        preview = format_preview_message(
            channel="zhyseseb",
            post_id=422,
            post_title="夏日合集",
            start_comment_id=4978,
            summary=summary,
            previews=previews,
            upload_enabled=True,
            delete_after_upload=True,
            size_summary=build_size_summary(comments),
        )

        self.assertIn("预计大小：", preview)
        self.assertIn("最大文件：", preview)
        self.assertIn("大小示例：", preview)
```

- [ ] **Step 2: Run test to verify old formatter rejects size_summary**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_format_preview_message_contains_summary_and_examples -v
```

Expected: FAIL with unexpected keyword argument `size_summary`.

- [ ] **Step 3: Extend comment preview formatter and bot call**

In `module/comment_workflow.py`, update `format_preview_message` signature:

```python
def format_preview_message(
    channel: str,
    post_id: int,
    post_title: str,
    start_comment_id: int,
    summary: CommentScanSummary,
    previews: Sequence[NamingPreview],
    upload_enabled: bool,
    delete_after_upload: bool,
    failed_comment_ids: Optional[Sequence[int]] = None,
    scan_warning: Optional[str] = None,
    size_summary: Optional[SizeSummary] = None,
) -> str:
```

Inside the function, after media count/type lines, add:

```python
    if size_summary is not None:
        lines.extend(_format_size_details(size_summary))
```

In `module/bot.py`, import `build_size_summary` from `module.comment_workflow`, then update the existing `format_preview_message(...)` call in `preview_comment_workflow`:

```python
            size_summary=build_size_summary(media_comments),
```

- [ ] **Step 4: Run comment preview tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_format_preview_message_contains_summary_and_examples tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_format_preview_message_includes_scan_warnings -v
```

Expected: PASS.

- [ ] **Step 5: Commit comment size preview**

```bash
git add module/comment_workflow.py module/bot.py tests/module/test_comment_workflow.py
git commit -m "feat: show size preview for comment workflows"
```

---

### Task 5: Add Telegram Package Scan and Prepared Download Execution

**Files:**
- Modify: `media_downloader.py`
- Modify: `module/app.py`
- Test: `tests/module/test_comment_workflow.py`
- Test: `tests/test_media_downloader.py`

- [ ] **Step 1: Write failing scan execution test**

Add this test to `CommentScanExecutionTestCase` in `tests/module/test_comment_workflow.py`:

```python
    async def test_scan_message_package_stops_before_next_caption(self):
        from media_downloader import scan_message_package

        messages = [
            MockMessage(id=100, media="video", caption="课程 第01章", video=MockVideo(file_name="1.mp4", file_size=10)),
            MockMessage(id=101, media="video", video=MockVideo(file_name="2.mp4", file_size=20)),
            MockMessage(id=102, media="video", caption="课程 第02章", video=MockVideo(file_name="3.mp4", file_size=30)),
        ]

        class FakeClient:
            async def get_messages(self, chat_id, message_ids):
                if isinstance(message_ids, list):
                    return [next((message for message in messages if message.id == mid), None) for mid in message_ids]
                return next((message for message in messages if message.id == message_ids), None)

        result = await scan_message_package(FakeClient(), -1001, 100, max_scan_count=10, batch_size=2)

        self.assertEqual([item.message.id for item in result.package_plan.items], [100, 101])
        self.assertEqual(result.package_plan.next_package_message.id, 102)
        self.assertEqual(result.failed_message_ids, [])
```

- [ ] **Step 2: Write failing package naming context test**

Add this test to `MediaDownloaderTestCase` in `tests/test_media_downloader.py`:

```python
    def test_get_media_meta_uses_package_naming_context_for_video(self):
        from module.comment_workflow import PackageNamingContext, NamingStrategy

        rest_app(MOCK_CONF)
        app.save_path = MOCK_DIR
        app.temp_save_path = os.path.join(MOCK_DIR, "temp")
        app.file_path_prefix = ["chat_title", "media_datetime"]
        app.file_name_prefix = ["message_id", "file_name"]
        app.file_name_prefix_split = " - "

        message = MockMessage(
            id=126711,
            chat_id=-1001,
            chat_title="Private",
            media="video",
            video=MockVideo(file_name="bad/name?.mp4", mime_type="video/mp4"),
            caption="caption text",
            date=datetime(2026, 6, 7),
        )
        node = TaskNode(chat_id=-1001)
        node.package_naming_context = PackageNamingContext(
            strategy=NamingStrategy.RECOMMENDED,
            channel="私密频道",
            start_message_id=126700,
            package_title="课程/第01章",
        )

        file_name, temp_file_name, file_format = self.loop.run_until_complete(
            _get_media_meta(-1001, message, message.video, "video", node=node)
        )

        self.assertEqual(file_format, "mp4")
        self.assertEqual(
            file_name,
            platform_generic_path(
                f"{MOCK_DIR}/Private/2026_06/私密频道/126700-课程_第01章/126711 - bad_name_.mp4"
            ),
        )
        self.assertEqual(
            temp_file_name,
            platform_generic_path(
                f"{MOCK_DIR}/temp/Private/私密频道/126700-课程_第01章/126711 - bad_name_.mp4"
            ),
        )
```

- [ ] **Step 3: Run tests to verify missing scan/context fail**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentScanExecutionTestCase::test_scan_message_package_stops_before_next_caption tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta_uses_package_naming_context_for_video -v
```

Expected: FAIL with missing `scan_message_package` or missing `package_naming_context` behavior.

- [ ] **Step 4: Add TaskNode package context**

In `module/app.py`, next to `self.comment_naming_context = None`, add:

```python
        # Guided ordinary message package workflow naming context.
        self.package_naming_context = None
```

- [ ] **Step 5: Implement scan and prepared-message download functions**

In `media_downloader.py`, add imports near other `module.comment_workflow` imports where needed:

```python
from module.comment_workflow import (
    PackageNamingContext,
    build_package_name_for_strategy,
    plan_message_package,
)
```

Add dataclass near `CommentScanResult`:

```python
@dataclass
class MessagePackageScanResult:
    """Telegram scan result for one ordinary message package."""

    package_plan: Any
    failed_message_ids: list[int]
```

Add functions before `download_comments`:

```python
async def scan_message_package(
    client: PyrogramClient,
    chat_id: int,
    start_message_id: int,
    max_scan_count: int = 500,
    batch_size: int = 50,
) -> MessagePackageScanResult:
    """Fetch a bounded message window and plan one continuous media package."""

    message_ids = list(range(start_message_id, start_message_id + max_scan_count))
    messages = []
    failed_message_ids: list[int] = []

    for index in range(0, len(message_ids), batch_size):
        batch_ids = message_ids[index : index + batch_size]
        try:
            batch_messages = await client.get_messages(chat_id, batch_ids)
            if not isinstance(batch_messages, list):
                batch_messages = [batch_messages]
            messages.extend(message for message in batch_messages if message)
            package_plan = plan_message_package(messages, start_message_id, max_scan_count=max_scan_count)
            if package_plan.next_package_message:
                return MessagePackageScanResult(package_plan, failed_message_ids)
        except Exception:
            for message_id in batch_ids:
                try:
                    message = await client.get_messages(chat_id, message_id)
                    if message:
                        messages.append(message)
                    package_plan = plan_message_package(messages, start_message_id, max_scan_count=max_scan_count)
                    if package_plan.next_package_message:
                        return MessagePackageScanResult(package_plan, failed_message_ids)
                except Exception:
                    failed_message_ids.append(message_id)

    return MessagePackageScanResult(
        plan_message_package(messages, start_message_id, max_scan_count=max_scan_count),
        failed_message_ids,
    )


async def download_prepared_messages(
    messages,
    download_filter: Optional[str],
    node: TaskNode,
    failed_message_ids: Optional[Sequence[int]] = None,
):
    """Download already-scanned ordinary package media messages."""

    from module.pyrogram_extension import report_bot_status

    media_messages = filter_media_comments(messages)
    node.total_download_task = len(media_messages) + len(failed_message_ids or [])
    node.total_task = node.total_download_task
    for failed_id in failed_message_ids or []:
        node.stat(DownloadStatus.FailedDownload, node.chat_id, failed_id)

    for message in media_messages:
        if node.is_stop_transmission:
            break
        if download_filter and not app.filter_exec(message, download_filter):
            node.stat(DownloadStatus.SkipDownload, node.chat_id, message.id)
            continue
        queued = await app.download_queue.put((node.client, message, node))
        if queued is False:
            node.stat(DownloadStatus.FailedDownload, node.chat_id, message.id)

    await report_bot_status(node.bot, node)
```

If `Queue.put` does not return a value in this project, mirror the pattern already used in `download_prepared_comments` instead of relying on `queued`.

- [ ] **Step 6: Extend `_get_media_meta` for package naming context**

In `media_downloader.py`, after the existing comment naming block:

```python
        if node and getattr(node, "package_naming_context", None):
            from module.comment_workflow import build_package_name_for_strategy, PackageMediaItem

            media_type, _ = media_payload_for_message(message)
            gen_file_name = build_package_name_for_strategy(
                PackageMediaItem(
                    message=message,
                    media_type=media_type,
                    caption_for_naming=getattr(message, "caption", None) or node.package_naming_context.package_title,
                    original_caption=getattr(message, "caption", None),
                    inherited_caption=not bool(getattr(message, "caption", None)),
                ),
                node.package_naming_context,
            )
```

Ensure the package block runs after comment naming and before `file_save_path`/`temp_file_name` are assembled, matching the existing comment naming block behavior.

- [ ] **Step 7: Run scan/context tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::CommentScanExecutionTestCase::test_scan_message_package_stops_before_next_caption tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta_uses_package_naming_context_for_video -v
```

Expected: PASS.

- [ ] **Step 8: Commit scan and package execution support**

```bash
git add media_downloader.py module/app.py tests/module/test_comment_workflow.py tests/test_media_downloader.py
git commit -m "feat: scan and name prepared message packages"
```

---

### Task 6: Add Bot Package Preview Routing and Confirmation Callback

**Files:**
- Modify: `module/bot.py`
- Modify: `module/comment_workflow.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing bot routing test**

Add this test to `BotPreviewWorkflowTestCase`:

```python
    async def test_download_from_link_routes_private_message_link_to_package_preview(self):
        import module.bot as bot_module

        class FakeBot:
            def __init__(self):
                self.client = object()
                self.pending_comment_workflows = {}
                self.pending_package_workflows = {}

        message = MockMessage(
            id=1,
            text="https://t.me/c/1298283297/126711",
            from_user=MockUser(id=777),
        )
        captured = {}

        async def fake_preview(client, preview_message, request):
            captured["request"] = request
            captured["message_id"] = preview_message.id

        with patch.object(bot_module, "_bot", FakeBot()), patch.object(
            bot_module, "preview_package_workflow", fake_preview
        ):
            await bot_module.download_from_link(object(), message)

        self.assertEqual(captured["request"].source_chat, -1001298283297)
        self.assertEqual(captured["request"].start_message_id, 126711)
        self.assertEqual(captured["message_id"], 1)
```

- [ ] **Step 2: Write failing package confirmation callback test**

Add this test to `BotCommentWorkflowCallbackTestCase`:

```python
    async def test_package_confirm_callback_starts_prepared_download_with_naming_context(self):
        import module.bot as bot_module
        from module.comment_workflow import (
            MessagePackageWorkflowRequest,
            NamingStrategy,
            PACKAGE_WORKFLOW_PREFIX,
            build_workflow_token,
        )

        request = MessagePackageWorkflowRequest(
            url="https://t.me/c/1298283297/126711",
            source_chat=-1001298283297,
            start_message_id=126711,
        )
        token = build_workflow_token(request.url, 777)
        messages = [
            MockMessage(id=126711, media="video", caption="课程 第01章", video=MockVideo(file_name="1.mp4")),
            MockMessage(id=126712, media="video", video=MockVideo(file_name="2.mp4")),
        ]

        class FakeBot:
            def __init__(self):
                self.bot = object()
                self.client = object()
                self.app = SimpleNamespace(loop=asyncio.get_running_loop())
                self.pending_package_workflows = {
                    token: {
                        "request": request,
                        "entity_id": -1001298283297,
                        "channel": "私密频道",
                        "package_title": "课程 第01章",
                        "messages": messages,
                        "failed_message_ids": [],
                        "source_message_id": 1,
                    }
                }
                self.task_nodes = []

            def gen_task_id(self):
                return "task-package"

            def add_task_node(self, node):
                self.task_nodes.append(node)

        class FakeClient:
            def __init__(self):
                self.edits = []
                self.sent = []

            async def edit_message_text(self, chat_id, message_id, text):
                self.edits.append((chat_id, message_id, text))

            async def send_message(self, chat_id, text, reply_to_message_id=None):
                sent = MockMessage(id=99, text=text)
                self.sent.append((chat_id, text, reply_to_message_id))
                return sent

        fake_bot = FakeBot()
        fake_client = FakeClient()
        query = SimpleNamespace(
            data=f"{PACKAGE_WORKFLOW_PREFIX}:{token}:C",
            from_user=MockUser(id=777),
            message=MockMessage(id=55),
        )
        captured = {}

        async def fake_download_prepared_messages(messages_arg, download_filter, node, failed_message_ids=None):
            captured["messages"] = messages_arg
            captured["node"] = node
            captured["failed_message_ids"] = failed_message_ids

        with patch.object(bot_module, "_bot", fake_bot), patch(
            "media_downloader.download_prepared_messages", fake_download_prepared_messages
        ):
            handled = await bot_module.handle_package_workflow_callback(fake_client, query)
            await asyncio.sleep(0)

        self.assertTrue(handled)
        self.assertEqual(captured["messages"], messages)
        self.assertEqual(captured["node"].package_naming_context.strategy, NamingStrategy.RECOMMENDED)
        self.assertEqual(captured["node"].package_naming_context.start_message_id, 126711)
        self.assertNotIn(token, fake_bot.pending_package_workflows)
```

- [ ] **Step 3: Run bot tests to verify missing route/callback fail**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::BotPreviewWorkflowTestCase::test_download_from_link_routes_private_message_link_to_package_preview tests/module/test_comment_workflow.py::BotCommentWorkflowCallbackTestCase::test_package_confirm_callback_starts_prepared_download_with_naming_context -v
```

Expected: FAIL with missing `preview_package_workflow` or `handle_package_workflow_callback`.

- [ ] **Step 4: Add package callback data helpers**

In `module/comment_workflow.py`, add:

```python
def build_package_callback_data(token: str, strategy: NamingStrategy) -> str:
    """Build package workflow callback data within Telegram limits."""

    return f"{PACKAGE_WORKFLOW_PREFIX}:{token}:{strategy.value}"


def parse_package_callback_data(data: str) -> Optional[tuple[str, NamingStrategy]]:
    """Parse package workflow callback data."""

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != PACKAGE_WORKFLOW_PREFIX or not parts[1]:
        return None
    try:
        return parts[1], NamingStrategy(parts[2])
    except ValueError:
        return None
```

- [ ] **Step 5: Route ordinary links before legacy single-message download**

In `module/bot.py`, import the new helpers:

```python
from module.comment_workflow import (
    PACKAGE_WORKFLOW_PREFIX,
    PackageNamingContext,
    build_message_package_workflow_request,
    build_package_callback_data,
    build_package_naming_previews,
    build_workflow_token,
    format_package_preview_message,
    parse_package_callback_data,
)
```

In `download_from_link`, after the existing comment workflow check and before legacy help/single download logic, add:

```python
    package_request = build_message_package_workflow_request(message.text.strip())
    if package_request:
        await preview_package_workflow(client, message, package_request)
        return
```

Ensure comment links still route to `preview_comment_workflow` first.

- [ ] **Step 6: Implement `preview_package_workflow`**

Add after `preview_comment_workflow` in `module/bot.py`:

```python
async def preview_package_workflow(client, message, workflow_request):
    """Scan a pasted ordinary message link and show package preview."""

    from media_downloader import scan_message_package

    try:
        entity = await _bot.client.get_chat(workflow_request.source_chat)
        scan_result = await scan_message_package(
            _bot.client,
            entity.id,
            workflow_request.start_message_id,
        )
        package_plan = scan_result.package_plan
        if not package_plan.items:
            await client.send_message(
                message.from_user.id,
                "未找到可下载的连续媒体资源包。",
                reply_to_message_id=message.id,
            )
            return

        token = build_workflow_token(workflow_request.url, message.from_user.id)
        channel = entity.username or entity.title or str(entity.id)
        previews = build_package_naming_previews(
            package_plan.items,
            channel=channel,
            start_message_id=workflow_request.start_message_id,
            package_title=package_plan.package_title,
        )
        _bot.pending_package_workflows[token] = {
            "request": workflow_request,
            "entity_id": entity.id,
            "channel": channel,
            "package_title": package_plan.package_title,
            "messages": [item.message for item in package_plan.items],
            "failed_message_ids": scan_result.failed_message_ids,
            "source_message_id": message.id,
        }

        cloud_drive_config = getattr(_bot.app, "cloud_drive_config", None)
        preview_text = format_package_preview_message(
            channel=channel,
            start_message_id=workflow_request.start_message_id,
            package_plan=package_plan,
            previews=previews,
            upload_enabled=bool(getattr(cloud_drive_config, "enable_upload_file", False)),
            delete_after_upload=bool(getattr(cloud_drive_config, "after_upload_file_delete", False)),
        )
        buttons = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("采用推荐C", callback_data=build_package_callback_data(token, NamingStrategy.RECOMMENDED))],
                [
                    InlineKeyboardButton("采用A", callback_data=build_package_callback_data(token, NamingStrategy.AUTHOR)),
                    InlineKeyboardButton("采用B", callback_data=build_package_callback_data(token, NamingStrategy.CAPTION)),
                    InlineKeyboardButton("采用D", callback_data=build_package_callback_data(token, NamingStrategy.MONTH_CAPTION)),
                ],
                [InlineKeyboardButton("取消", callback_data=f"{PACKAGE_WORKFLOW_PREFIX}:{token}:cancel")],
            ]
        )
        await client.send_message(
            message.from_user.id,
            preview_text,
            reply_markup=buttons,
            reply_to_message_id=message.id,
        )
    except Exception as error:
        logger.error(f"preview_package_workflow: failed: {error}", exc_info=True)
        await client.send_message(
            message.from_user.id,
            f"预览连续媒体资源包失败：{error}",
            reply_to_message_id=message.id,
        )
```

- [ ] **Step 7: Implement `handle_package_workflow_callback` and register it**

Add before `handle_comment_workflow_callback`:

```python
async def handle_package_workflow_callback(client, query):
    """Handle guided ordinary message package workflow callbacks."""

    data = getattr(query, "data", None)
    if not data or not data.startswith(f"{PACKAGE_WORKFLOW_PREFIX}:"):
        return False

    message = getattr(query, "message", None)
    chat_id = _callback_chat_id(query)
    message_id = getattr(message, "id", None)

    parts = data.split(":")
    if len(parts) == 3 and parts[2] == "cancel" and parts[1]:
        _bot.pending_package_workflows.pop(parts[1], None)
        await client.edit_message_text(chat_id, message_id, "已取消连续媒体资源包下载。")
        return True

    parsed = parse_package_callback_data(data)
    if not parsed:
        await client.edit_message_text(chat_id, message_id, "无效的连续媒体资源包下载操作。")
        return True

    token, strategy = parsed
    pending = _bot.pending_package_workflows.get(token)
    if not pending:
        await client.edit_message_text(chat_id, message_id, "任务已过期，请重新发送链接")
        return True

    request = pending["request"]
    confirm_text = f"已确认命名策略 {strategy.value}，开始下载连续媒体资源包。"
    try:
        await client.edit_message_text(chat_id, message_id, confirm_text)
    except Exception as error:
        logger.warning(f"package workflow confirm edit failed: {error}")
        await client.send_message(chat_id, confirm_text, reply_to_message_id=pending.get("source_message_id"))

    status_message = await client.send_message(
        chat_id,
        f"连续媒体资源包下载任务已启动：{pending['channel']}/{request.start_message_id}",
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
    node.package_naming_context = PackageNamingContext(
        strategy=strategy,
        channel=pending["channel"],
        start_message_id=request.start_message_id,
        package_title=pending["package_title"],
    )
    node.is_running = True

    from media_downloader import download_prepared_messages

    download_coroutine = download_prepared_messages(
        pending["messages"],
        None,
        node,
        failed_message_ids=pending.get("failed_message_ids"),
    )
    try:
        _bot.app.loop.create_task(download_coroutine)
    except Exception:
        download_coroutine.close()
        raise

    _bot.add_task_node(node)
    add_active_task_node(node)
    _bot.pending_package_workflows.pop(token, None)
    return True
```

In `callback_query`, before comment callback handling:

```python
    if await handle_package_workflow_callback(client, query):
        return
```

Also initialize `pending_package_workflows` wherever `pending_comment_workflows` is initialized in `DownloadBot`.

- [ ] **Step 8: Run bot route and callback tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py::BotPreviewWorkflowTestCase::test_download_from_link_routes_private_message_link_to_package_preview tests/module/test_comment_workflow.py::BotCommentWorkflowCallbackTestCase::test_package_confirm_callback_starts_prepared_download_with_naming_context -v
```

Expected: PASS.

- [ ] **Step 9: Commit bot package workflow**

```bash
git add module/bot.py module/comment_workflow.py tests/module/test_comment_workflow.py
git commit -m "feat: add guided private package bot workflow"
```

---

### Task 7: Documentation and Final Verification

**Files:**
- Modify: `README_CN.md`
- Test: focused and full test suites

- [ ] **Step 1: Document package workflow in Chinese README**

In `README_CN.md`, after the comment-link media wizard section, add:

```markdown
#### 私密消息链接连续资源包向导

直接把普通消息链接发送给 bot：

```text
https://t.me/c/1298283297/126711
```

bot 会自动把 `/c/1298283297/126711` 转换为内部 chat_id `-1001298283297` 和起始消息 ID `126711`，然后向后扫描连续媒体资源包。

适合一组连续视频/图片共用同一标题的频道：如果后续媒体没有 caption，会继承最近的资源包标题；如果扫描到新的不同 caption，会把它显示为“下一包起点预览”，但不会纳入本次下载。

确认下载前会展示：

- 本包标题和消息范围
- 可下载媒体数量和类型统计
- 预计总大小、单文件大小示例、最大文件
- 继承 caption 的媒体数量
- 下一包起点预览
- A/B/C/D 四套命名预览
- rclone 上传和上传后删除本地文件状态

确认命名方案后才会开始下载、上传，并按配置删除本地文件。
```

- [ ] **Step 2: Run focused pure workflow tests**

Run:

```bash
.venv/bin/python -m pytest tests/module/test_comment_workflow.py -v
```

Expected: PASS.

- [ ] **Step 3: Run focused media downloader tests**

Run:

```bash
.venv/bin/python -m pytest tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta_uses_package_naming_context_for_video tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta_uses_comment_naming_context_for_video tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta -v
```

Expected: PASS.

- [ ] **Step 4: Run compile check**

Run:

```bash
.venv/bin/python -m py_compile module/comment_workflow.py module/bot.py media_downloader.py module/app.py
```

Expected: no output and exit code 0.

- [ ] **Step 5: Run full test suite**

Run:

```bash
.venv/bin/python -m pytest -q
```

Expected: PASS with existing skip count only.

- [ ] **Step 6: Check git status**

Run:

```bash
git status --short --branch
```

Expected: only intended implementation files changed plus the user's pre-existing `.gitignore` modification if it still exists in the main checkout.

- [ ] **Step 7: Commit docs and final verification fixes**

```bash
git add README_CN.md module/comment_workflow.py module/bot.py media_downloader.py module/app.py tests/module/test_comment_workflow.py tests/test_media_downloader.py tests/test_common.py
git commit -m "docs: document private package workflow"
```

If only README changed in this task, commit only `README_CN.md`.

---

## Manual Runtime Smoke Test

After all automated tests pass and the branch is ready for deployment, use the real bot with a private link the user can access:

1. Send `https://t.me/c/1298283297/126711` to the bot.
2. Verify the preview shows a package title, range, media count, total size, sample sizes, and largest file.
3. Verify no-caption media are counted as inherited caption.
4. Verify a new different caption is shown as next-package preview and not included in the download range.
5. Click `采用推荐C`.
6. Verify downloaded files are under `频道名/126711-<包标题>/`.
7. Verify rclone upload runs through existing upload settings.
8. Verify local files are deleted only after successful upload when `after_upload_file_delete: true`.
9. Send a comment link and verify the comment preview now includes size summary.

## Implementation Notes

- Use the existing project `.venv`: run all commands as `.venv/bin/python ...`.
- Do not use system Python.
- Preserve existing `/download https://... start end tag` behavior.
- Preserve existing comment-link behavior except for adding size preview.
- Do not include the boundary message with a different new caption in prepared downloads.
- Keep all callback payloads under Telegram's 64-byte callback data limit.

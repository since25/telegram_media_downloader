# Comment Link Media Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a guided bot workflow where pasting a Telegram comment link scans the post's comment thread, filters media comments, previews naming strategies, and downloads/uploads only after user confirmation.

**Architecture:** Add a small pure planning module for parsing, scan summaries, media filtering, and naming previews so behavior can be tested without live Telegram. Keep Telegram I/O in `module/bot.py` and reuse the existing `media_downloader.download_comments` execution path after extending it to accept prepared comments and a selected naming strategy. Store short-lived pending confirmation state in `DownloadBot` keyed by callback token.

**Tech Stack:** Python 3, Pyrogram, unittest/pytest, existing `utils.format.validate_title`, existing `TaskNode`, existing rclone upload/delete path in `media_downloader.py`.

---

## File Structure

- Create `module/comment_workflow.py`: pure helpers and dataclasses for comment-link workflow parsing, media filtering, scan summary, naming strategy previews, callback token state, and selected naming context.
- Modify `module/app.py`: add optional naming strategy/context fields to `TaskNode` without changing existing constructors.
- Modify `media_downloader.py`: add a reusable comment media execution function, filter non-media comments before queuing downloads, and apply selected naming context in `_get_media_meta`.
- Modify `module/bot.py`: route direct comment links into the guided workflow, show summary/previews/buttons, persist pending state, and start download on callback confirmation.
- Modify `tests/test_common.py`: add minimal mock user display fields needed by naming previews.
- Create `tests/module/test_comment_workflow.py`: unit tests for parsing, media filtering, summaries, fallback naming, and callback payloads.
- Modify `tests/test_media_downloader.py`: focused tests for selected naming context in `_get_media_meta`.
- Modify `README_CN.md`: document the new comment-link workflow after implementation is green.

---

### Task 1: Add Pure Workflow Planner

**Files:**
- Create: `module/comment_workflow.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing parser and media-filter tests**

Add `tests/module/test_comment_workflow.py`:

```python
"""Tests for Telegram comment-link media workflow planning."""
import datetime
import unittest

from tests.test_common import MockDocument, MockMessage, MockPhoto, MockUser, MockVideo

from module.comment_workflow import (
    COMMENT_WORKFLOW_PREFIX,
    NamingStrategy,
    build_callback_data,
    build_comment_workflow_request,
    filter_media_comments,
    summarize_comments,
)


class CommentWorkflowTestCase(unittest.TestCase):
    def test_build_comment_workflow_request_from_comment_link(self):
        request = build_comment_workflow_request(
            "https://t.me/zhyseseb/422?comment=4978"
        )

        self.assertEqual(request.source_chat, "zhyseseb")
        self.assertEqual(request.post_id, 422)
        self.assertEqual(request.start_comment_id, 4978)

    def test_build_comment_workflow_request_rejects_non_comment_link(self):
        self.assertIsNone(
            build_comment_workflow_request("https://t.me/zhyseseb/422")
        )

    def test_filter_media_comments_skips_text_and_empty_messages(self):
        comments = [
            MockMessage(id=1, text="hello"),
            MockMessage(id=2, media="photo", photo=MockPhoto(date=datetime.datetime(2026, 6, 7), file_unique_id="p1")),
            MockMessage(id=3, empty=True),
            MockMessage(id=4, media="video", video=MockVideo(file_name="clip.mp4", mime_type="video/mp4")),
        ]

        media_comments = filter_media_comments(comments)

        self.assertEqual([comment.id for comment in media_comments], [2, 4])

    def test_summarize_comments_counts_media_types(self):
        comments = [
            MockMessage(id=4978, media="photo", photo=MockPhoto(date=datetime.datetime(2026, 6, 7), file_unique_id="p1")),
            MockMessage(id=4979, text="skip"),
            MockMessage(id=4980, media="video", video=MockVideo(file_name="clip.mp4", mime_type="video/mp4")),
            MockMessage(id=4981, media="document", document=MockDocument(file_name="book.pdf", mime_type="application/pdf")),
        ]

        summary = summarize_comments(comments)

        self.assertEqual(summary.scanned_count, 4)
        self.assertEqual(summary.media_count, 3)
        self.assertEqual(summary.media_type_counts, {"photo": 1, "video": 1, "document": 1})
        self.assertEqual(summary.first_comment_id, 4978)
        self.assertEqual(summary.last_comment_id, 4981)

    def test_build_callback_data_keeps_payload_short(self):
        callback_data = build_callback_data("abc123", NamingStrategy.RECOMMENDED)

        self.assertEqual(callback_data, f"{COMMENT_WORKFLOW_PREFIX}:abc123:C")
        self.assertLessEqual(len(callback_data.encode("utf-8")), 64)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify missing module failure**

Run:

```bash
pytest tests/module/test_comment_workflow.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'module.comment_workflow'`.

- [ ] **Step 3: Implement request parsing, filtering, summary, and callback data**

Create `module/comment_workflow.py`:

```python
"""Pure helpers for guided Telegram comment-link media downloads."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence

from utils.format import extract_info_from_link, validate_title

COMMENT_WORKFLOW_PREFIX = "cw"
SUPPORTED_MEDIA_TYPES = {
    "audio",
    "document",
    "photo",
    "video",
    "voice",
    "video_note",
}


class NamingStrategy(Enum):
    """Naming strategies shown in the confirmation UI."""

    AUTHOR = "A"
    CAPTION = "B"
    RECOMMENDED = "C"
    MONTH_CAPTION = "D"


@dataclass
class CommentWorkflowRequest:
    """Parsed direct comment-link workflow request."""

    url: str
    source_chat: str | int
    post_id: int
    start_comment_id: int


@dataclass
class CommentScanSummary:
    """Summary of comments discovered during a preview scan."""

    scanned_count: int
    media_count: int
    media_type_counts: Dict[str, int] = field(default_factory=dict)
    first_comment_id: Optional[int] = None
    last_comment_id: Optional[int] = None


@dataclass
class NamingPreview:
    """A single naming preview option."""

    strategy: NamingStrategy
    title: str
    examples: List[str]


@dataclass
class CommentNamingContext:
    """Values used to build final names for comment media files."""

    strategy: NamingStrategy
    channel: str
    post_id: int
    post_title: str


def build_comment_workflow_request(text: str) -> Optional[CommentWorkflowRequest]:
    """Return a workflow request when text is a t.me post comment link."""

    if not text or not text.startswith("https://t.me"):
        return None

    link = extract_info_from_link(text.strip())
    if link.group_id is None or link.post_id is None or link.comment_id is None:
        return None

    return CommentWorkflowRequest(
        url=text.strip(),
        source_chat=link.group_id,
        post_id=link.post_id,
        start_comment_id=link.comment_id,
    )


def is_media_comment(comment) -> bool:
    """Return True when a comment contains a supported media payload."""

    if not comment or getattr(comment, "empty", False):
        return False

    media = getattr(comment, "media", None)
    media_name = getattr(media, "value", media)
    return media_name in SUPPORTED_MEDIA_TYPES and bool(getattr(comment, media_name, None))


def filter_media_comments(comments: Iterable) -> List:
    """Keep only supported media comments."""

    return [comment for comment in comments if is_media_comment(comment)]


def summarize_comments(comments: Sequence) -> CommentScanSummary:
    """Build a scan summary for user confirmation."""

    comment_list = [comment for comment in comments if comment and hasattr(comment, "id")]
    media_comments = filter_media_comments(comment_list)
    media_type_counts: Dict[str, int] = {}

    for comment in media_comments:
        media_name = getattr(getattr(comment, "media", None), "value", getattr(comment, "media", None))
        media_type_counts[media_name] = media_type_counts.get(media_name, 0) + 1

    ids = [comment.id for comment in comment_list]
    return CommentScanSummary(
        scanned_count=len(comment_list),
        media_count=len(media_comments),
        media_type_counts=media_type_counts,
        first_comment_id=min(ids) if ids else None,
        last_comment_id=max(ids) if ids else None,
    )


def build_workflow_token(url: str, user_id: int | str) -> str:
    """Build a short stable token for callback state lookup."""

    digest = hashlib.sha1(f"{user_id}:{url}".encode("utf-8")).hexdigest()
    return digest[:12]


def build_callback_data(token: str, strategy: NamingStrategy) -> str:
    """Build callback data that fits Telegram's 64 byte limit."""

    return f"{COMMENT_WORKFLOW_PREFIX}:{token}:{strategy.value}"


def parse_callback_data(data: str) -> Optional[tuple[str, NamingStrategy]]:
    """Parse workflow callback data into token and naming strategy."""

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != COMMENT_WORKFLOW_PREFIX:
        return None

    try:
        strategy = NamingStrategy(parts[2])
    except ValueError:
        return None

    return parts[1], strategy


def clean_segment(value: Optional[str], fallback: str, max_len: int = 40) -> str:
    """Clean one filename/path segment with deterministic fallback."""

    text = (value or "").strip() or fallback
    text = " ".join(text.split())
    text = validate_title(text).strip(" .-_") or fallback
    return text[:max_len]
```

- [ ] **Step 4: Run tests to verify planner passes**

Run:

```bash
pytest tests/module/test_comment_workflow.py -v
```

Expected: PASS for the five tests.

- [ ] **Step 5: Commit planner**

```bash
git add module/comment_workflow.py tests/module/test_comment_workflow.py
git commit -m "feat: add comment workflow planner"
```

---

### Task 2: Add Naming Preview Generation

**Files:**
- Modify: `module/comment_workflow.py`
- Modify: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing preview tests**

Append these tests to `CommentWorkflowTestCase` in `tests/module/test_comment_workflow.py`:

```python
    def test_build_naming_previews_generates_four_clean_options(self):
        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="bad/name?.mp4", mime_type="video/mp4"),
                caption="第三张是重点，后面还有说明",
                from_user=MockUser(username="user/name"),
                date=datetime.datetime(2026, 6, 7),
            )
        ]

        previews = build_naming_previews(
            comments=comments,
            channel="zhyseseb",
            post_id=422,
            post_title="夏日/合集 Vol.12",
            sample_size=1,
        )

        self.assertEqual([preview.strategy.value for preview in previews], ["C", "A", "B", "D"])
        self.assertEqual(
            previews[0].examples[0],
            "zhyseseb/422-夏日_合集 Vol.12/4978 - bad_name_.mp4",
        )
        self.assertEqual(
            previews[1].examples[0],
            "夏日_合集 Vol.12/4978 - user_name - bad_name_.mp4",
        )
        self.assertEqual(
            previews[2].examples[0],
            "夏日_合集 Vol.12/4978 - 第三张是重点，后面还有说明 - bad_name_.mp4",
        )
        self.assertEqual(
            previews[3].examples[0],
            "zhyseseb/2026_06/夏日_合集 Vol.12/4978 - 第三张是重点，后面还有说明.mp4",
        )

    def test_build_naming_previews_uses_fallbacks(self):
        comments = [
            MockMessage(
                id=5000,
                media="photo",
                photo=MockPhoto(date=datetime.datetime(2026, 6, 7), file_unique_id="photo-id"),
                date=datetime.datetime(2026, 6, 7),
            )
        ]

        previews = build_naming_previews(
            comments=comments,
            channel="zhyseseb",
            post_id=422,
            post_title="",
            sample_size=1,
        )

        self.assertEqual(
            previews[0].examples[0],
            "zhyseseb/422-post-422/5000 - comment-5000-photo.jpg",
        )
        self.assertEqual(
            previews[3].examples[0],
            "zhyseseb/2026_06/post-422/5000 - no-caption.jpg",
        )
```

Also add `build_naming_previews` to the import list at the top of the test file.

- [ ] **Step 2: Run preview tests to verify failure**

Run:

```bash
pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_naming_previews_generates_four_clean_options tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_build_naming_previews_uses_fallbacks -v
```

Expected: FAIL with `ImportError` or `NameError` for `build_naming_previews`.

- [ ] **Step 3: Implement naming preview helpers**

Add to `module/comment_workflow.py`:

```python
def _media_name(comment) -> str:
    return getattr(getattr(comment, "media", None), "value", getattr(comment, "media", None)) or "media"


def _extension_for_comment(comment) -> str:
    media_name = _media_name(comment)
    media_obj = getattr(comment, media_name, None)
    file_name = getattr(media_obj, "file_name", None)
    if file_name and "." in file_name:
        return file_name.rsplit(".", 1)[1]
    if media_name == "photo":
        return "jpg"
    if media_name in ("video", "video_note"):
        return "mp4"
    if media_name == "voice":
        return "ogg"
    if media_name == "audio":
        return "mp3"
    return "bin"


def original_file_name_for_comment(comment) -> str:
    """Return cleaned original file name or a deterministic fallback."""

    media_name = _media_name(comment)
    media_obj = getattr(comment, media_name, None)
    file_name = getattr(media_obj, "file_name", None)
    if file_name:
        return clean_segment(file_name, f"comment-{comment.id}-{media_name}.{_extension_for_comment(comment)}", 80)
    return clean_segment(
        f"comment-{comment.id}-{media_name}.{_extension_for_comment(comment)}",
        f"comment-{comment.id}-{media_name}.bin",
        80,
    )


def caption_summary_for_comment(comment) -> str:
    """Return cleaned caption summary fallback."""

    return clean_segment(getattr(comment, "caption", None), "no-caption", 40)


def author_for_comment(comment) -> str:
    """Return cleaned user name fallback."""

    user = getattr(comment, "from_user", None)
    user_name = getattr(user, "username", None) or getattr(user, "first_name", None)
    return clean_segment(user_name, "anonymous", 40)


def month_for_comment(comment) -> str:
    """Return yyyy_mm from comment date or 0000_00 fallback."""

    date = getattr(comment, "date", None)
    if date and hasattr(date, "strftime"):
        return date.strftime("%Y_%m")
    return "0000_00"


def build_name_for_strategy(
    comment,
    context: CommentNamingContext,
) -> str:
    """Build a relative display path for a comment and naming context."""

    channel = clean_segment(context.channel, "unknown-channel", 50)
    post_title = clean_segment(context.post_title, f"post-{context.post_id}", 60)
    original_file_name = original_file_name_for_comment(comment)
    caption_summary = caption_summary_for_comment(comment)
    author = author_for_comment(comment)
    extension = _extension_for_comment(comment)

    if context.strategy is NamingStrategy.AUTHOR:
        return f"{post_title}/{comment.id} - {author} - {original_file_name}"
    if context.strategy is NamingStrategy.CAPTION:
        return f"{post_title}/{comment.id} - {caption_summary} - {original_file_name}"
    if context.strategy is NamingStrategy.MONTH_CAPTION:
        return f"{channel}/{month_for_comment(comment)}/{post_title}/{comment.id} - {caption_summary}.{extension}"
    return f"{channel}/{context.post_id}-{post_title}/{comment.id} - {original_file_name}"


def build_naming_previews(
    comments: Sequence,
    channel: str,
    post_id: int,
    post_title: str,
    sample_size: int = 3,
) -> List[NamingPreview]:
    """Build concrete preview examples for all naming strategies."""

    media_comments = filter_media_comments(comments)[:sample_size]
    strategies = [
        (NamingStrategy.RECOMMENDED, "推荐C：频道/原帖ID-标题/评论ID - 原文件名"),
        (NamingStrategy.AUTHOR, "A：原帖标题/评论ID - 作者 - 原文件名"),
        (NamingStrategy.CAPTION, "B：原帖标题/评论ID - caption摘要 - 原文件名"),
        (NamingStrategy.MONTH_CAPTION, "D：频道/年月/原帖标题/评论ID - caption摘要"),
    ]

    previews: List[NamingPreview] = []
    for strategy, title in strategies:
        context = CommentNamingContext(
            strategy=strategy,
            channel=channel,
            post_id=post_id,
            post_title=post_title,
        )
        previews.append(
            NamingPreview(
                strategy=strategy,
                title=title,
                examples=[build_name_for_strategy(comment, context) for comment in media_comments],
            )
        )
    return previews
```

- [ ] **Step 4: Run all workflow tests**

Run:

```bash
pytest tests/module/test_comment_workflow.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit naming previews**

```bash
git add module/comment_workflow.py tests/module/test_comment_workflow.py
git commit -m "feat: preview comment media naming strategies"
```

---

### Task 3: Support Selected Naming in Media Metadata

**Files:**
- Modify: `module/app.py`
- Modify: `media_downloader.py`
- Modify: `tests/test_media_downloader.py`

- [ ] **Step 1: Write failing `_get_media_meta` naming-context test**

Append this method inside `MediaDownloaderTestCase` in `tests/test_media_downloader.py`, immediately after the existing `test_get_media_meta` method. Also add `MockUser` to the existing import list from `.test_common`.

```python
    def test_get_media_meta_uses_comment_naming_context_for_video(self):
        from module.comment_workflow import CommentNamingContext, NamingStrategy

        rest_app(MOCK_CONF)
        app.save_path = MOCK_DIR
        app.temp_save_path = os.path.join(MOCK_DIR, "temp")
        app.file_path_prefix = ["chat_title", "media_datetime"]
        app.file_name_prefix = ["message_id", "file_name"]
        app.file_name_prefix_split = " - "

        message = MockMessage(
            id=4978,
            chat_id=-1001,
            chat_title="Discussion",
            media="video",
            video=MockVideo(file_name="bad/name?.mp4", mime_type="video/mp4"),
            caption="caption text",
            from_user=MockUser(username="user123"),
            date=datetime(2026, 6, 7),
        )
        node = TaskNode(chat_id=-1001)
        node.comment_naming_context = CommentNamingContext(
            strategy=NamingStrategy.RECOMMENDED,
            channel="zhyseseb",
            post_id=422,
            post_title="夏日/合集 Vol.12",
        )

        file_name, temp_file_name, file_format = self.loop.run_until_complete(
            _get_media_meta(-1001, message, message.video, "video", node=node)
        )

        self.assertEqual(file_format, "mp4")
        self.assertEqual(
            file_name,
            platform_generic_path(
                f"{MOCK_DIR}/Discussion/2026_06/zhyseseb/422-夏日_合集 Vol.12/4978 - bad_name_.mp4"
            ),
        )
        self.assertEqual(
            temp_file_name,
            platform_generic_path(
                f"{MOCK_DIR}/temp/Discussion/zhyseseb/422-夏日_合集 Vol.12/4978 - bad_name_.mp4"
            ),
        )
```

- [ ] **Step 2: Run focused metadata test to verify failure**

Run:

```bash
pytest tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta_uses_comment_naming_context_for_video -v
```

Expected: FAIL because `TaskNode` has no `comment_naming_context` behavior in `_get_media_meta`.

- [ ] **Step 3: Add TaskNode fields**

In `module/app.py`, inside `TaskNode.__init__` after `self.file_name_tag`:

```python
        # Comment-link guided workflow naming context.
        self.comment_naming_context = None
```

- [ ] **Step 4: Apply selected naming context in `_get_media_meta`**

In `media_downloader.py`, import helper inside the non-voice branch just before composing final paths:

```python
        if node and getattr(node, "comment_naming_context", None):
            from module.comment_workflow import build_name_for_strategy

            gen_file_name = build_name_for_strategy(message, node.comment_naming_context)
```

Place this after the existing `combined_tag` insertion block and before:

```python
        file_save_path = app.get_file_save_path(_type, dirname, datetime_dir_name)
```

Do not apply this to `voice`/`video_note` in the first pass unless the test suite shows those types need it immediately; the workflow still filters and queues them, and a later task can extend naming if required.

- [ ] **Step 5: Run focused metadata test to verify pass**

Run:

```bash
pytest tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta_uses_comment_naming_context_for_video -v
```

Expected: PASS.

- [ ] **Step 6: Run adjacent media downloader tests**

Run:

```bash
pytest tests/test_media_downloader.py -v
```

Expected: PASS. If this command fails, record the exact failing test and stop for review before changing unrelated code.

- [ ] **Step 7: Commit selected naming support**

```bash
git add module/app.py media_downloader.py tests/test_media_downloader.py
git commit -m "feat: apply selected comment naming strategy"
```

---

### Task 4: Split Comment Scan From Download Execution

**Files:**
- Modify: `media_downloader.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Write failing helper test for scan batching with fake client**

Append to `tests/module/test_comment_workflow.py`:

```python
class FakeDiscussionClient:
    def __init__(self, comments):
        self.comments = {comment.id: comment for comment in comments}
        self.discussion_message = MockMessage(id=1, chat_id=-200, chat_title="Discussion")

    async def get_discussion_message(self, chat_id, message_id):
        self.requested_chat_id = chat_id
        self.requested_message_id = message_id
        return self.discussion_message

    async def get_messages(self, chat_id, message_ids):
        if isinstance(message_ids, list):
            return [self.comments.get(message_id) for message_id in message_ids]
        return self.comments.get(message_ids)


class CommentScanExecutionTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_scan_comment_range_returns_comments_and_discussion_chat(self):
        from media_downloader import scan_comment_range

        comments = [
            MockMessage(id=4978, media="video", video=MockVideo(file_name="clip.mp4", mime_type="video/mp4")),
            MockMessage(id=4979, text="skip"),
        ]
        client = FakeDiscussionClient(comments)

        discussion_group_id, scanned_comments = await scan_comment_range(
            client=client,
            chat_id=-1001,
            base_message_id=422,
            start_comment_id=4978,
            end_comment_id=4979,
        )

        self.assertEqual(discussion_group_id, -200)
        self.assertEqual([comment.id for comment in scanned_comments], [4978, 4979])
```

- [ ] **Step 2: Run helper test to verify failure**

Run:

```bash
pytest tests/module/test_comment_workflow.py::CommentScanExecutionTestCase::test_scan_comment_range_returns_comments_and_discussion_chat -v
```

Expected: FAIL with `ImportError` for `scan_comment_range`.

- [ ] **Step 3: Add `scan_comment_range` helper**

In `media_downloader.py`, above `download_comments`, add:

```python
async def scan_comment_range(
    client: PyrogramClient,
    chat_id: int,
    base_message_id: int,
    start_comment_id: int,
    end_comment_id: int,
):
    """Resolve a post discussion group and fetch comments in an ID range."""

    discussion_message = await client.get_discussion_message(chat_id, base_message_id)
    if not discussion_message:
        raise ValueError("discussion message not found")

    discussion_group_id = discussion_message.chat.id
    comment_ids = list(range(start_comment_id, end_comment_id + 1))
    comments = []
    batch_size = 50

    for index in range(0, len(comment_ids), batch_size):
        batch_ids = comment_ids[index : index + batch_size]
        try:
            batch_comments = await client.get_messages(discussion_group_id, batch_ids)
            if not isinstance(batch_comments, list):
                batch_comments = [batch_comments]
            for comment in batch_comments:
                if comment and hasattr(comment, "id"):
                    comments.append(comment)
        except Exception:
            for comment_id in batch_ids:
                try:
                    comment = await client.get_messages(discussion_group_id, comment_id)
                    if comment and hasattr(comment, "id"):
                        comments.append(comment)
                except Exception as single_error:
                    logger.error(f"scan_comment_range: failed comment {comment_id}: {single_error}")

    comments.sort(key=lambda comment: comment.id)
    return discussion_group_id, comments
```

- [ ] **Step 4: Refactor `download_comments` to use `scan_comment_range`**

In `download_comments`, replace the existing discussion resolution and batch get block with:

```python
        discussion_group_id, comments = await scan_comment_range(
            client=client,
            chat_id=chat_id,
            base_message_id=base_message_id,
            start_comment_id=start_comment_id,
            end_comment_id=end_comment_id,
        )
        logger.info(f"download_comments: 使用讨论组ID: {discussion_group_id}")
        logger.info(f"共找到 {len(comments)} 条评论")
```

Keep the existing filter and queueing logic after this point.

- [ ] **Step 5: Run scan helper and existing comment tests**

Run:

```bash
pytest tests/module/test_comment_workflow.py::CommentScanExecutionTestCase::test_scan_comment_range_returns_comments_and_discussion_chat -v
pytest tests/module/test_comment_workflow.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit scan helper**

```bash
git add media_downloader.py tests/module/test_comment_workflow.py
git commit -m "refactor: split comment range scanning"
```

---

### Task 5: Add Bot Guided Preview State and UI

**Files:**
- Modify: `module/bot.py`
- Modify: `module/comment_workflow.py`
- Test: `tests/module/test_comment_workflow.py`

- [ ] **Step 1: Add formatting tests for confirmation message text**

Append to `tests/module/test_comment_workflow.py`:

```python
    def test_format_preview_message_contains_summary_and_examples(self):
        from module.comment_workflow import format_preview_message

        comments = [
            MockMessage(
                id=4978,
                media="video",
                video=MockVideo(file_name="clip.mp4", mime_type="video/mp4"),
                caption="caption text",
                date=datetime.datetime(2026, 6, 7),
            )
        ]
        summary = summarize_comments(comments)
        previews = build_naming_previews(comments, "zhyseseb", 422, "夏日合集", 1)

        message = format_preview_message(
            channel="zhyseseb",
            post_id=422,
            post_title="夏日合集",
            start_comment_id=4978,
            summary=summary,
            previews=previews,
            upload_enabled=True,
            delete_after_upload=True,
        )

        self.assertIn("频道：zhyseseb", message)
        self.assertIn("原帖：422", message)
        self.assertIn("媒体评论：1", message)
        self.assertIn("上传：enabled", message)
        self.assertIn("采用推荐C", message)
        self.assertIn("zhyseseb/422-夏日合集/4978 - clip.mp4", message)
```

Add `build_naming_previews` if not already imported in this test scope.

- [ ] **Step 2: Run formatting test to verify failure**

Run:

```bash
pytest tests/module/test_comment_workflow.py::CommentWorkflowTestCase::test_format_preview_message_contains_summary_and_examples -v
```

Expected: FAIL because `format_preview_message` is missing.

- [ ] **Step 3: Implement preview message formatter**

Add to `module/comment_workflow.py`:

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
) -> str:
    """Format scan summary and naming previews for the bot confirmation UI."""

    media_types = " / ".join(
        f"{media_type} {count}" for media_type, count in sorted(summary.media_type_counts.items())
    ) or "none"
    last_comment = summary.last_comment_id if summary.last_comment_id is not None else "unknown"
    cleaned_title = clean_segment(post_title, f"post-{post_id}", 80)

    lines = [
        "识别到评论媒体下载任务：",
        f"频道：{clean_segment(str(channel), 'unknown-channel', 80)}",
        f"原帖：{post_id}",
        f"原帖标题：{cleaned_title}",
        f"评论范围：{start_comment_id} → {last_comment}",
        f"扫描评论：{summary.scanned_count}",
        f"媒体评论：{summary.media_count}",
        f"类型：{media_types}",
        f"上传：{'enabled' if upload_enabled else 'disabled'}",
        f"上传后删除本地：{'enabled' if delete_after_upload else 'disabled'}",
        "",
        "请选择本次命名方案：",
    ]

    for preview in previews:
        lines.append("")
        lines.append(preview.title)
        if preview.strategy is NamingStrategy.RECOMMENDED:
            lines.append("按钮：采用推荐C")
        for example in preview.examples:
            lines.append(example)

    return "\n".join(lines)
```

- [ ] **Step 4: Add pending state fields to `DownloadBot`**

In `module/bot.py`, add imports near existing imports:

```python
from module.comment_workflow import (
    CommentNamingContext,
    NamingStrategy,
    build_callback_data,
    build_comment_workflow_request,
    build_naming_previews,
    build_workflow_token,
    filter_media_comments,
    format_preview_message,
    parse_callback_data,
    summarize_comments,
)
```

In `DownloadBot.__init__`, add:

```python
        self.pending_comment_workflows: dict = {}
```

- [ ] **Step 5: Add guided direct-link handler path**

In `download_from_link`, after the initial `if not message.text...` guard and before the existing help text parsing, add:

```python
    workflow_request = build_comment_workflow_request(message.text.strip())
    if workflow_request:
        await preview_comment_workflow(client, message, workflow_request)
        return
```

Add a new function in `module/bot.py` before `download_from_link`:

```python
async def preview_comment_workflow(client: pyrogram.Client, message: pyrogram.types.Message, workflow_request):
    """Scan a pasted comment link and show naming/download confirmation."""

    from media_downloader import scan_comment_range

    entity = await _bot.client.get_chat(workflow_request.source_chat)
    base_message = await _bot.client.get_messages(entity.id, workflow_request.post_id)
    post_title = (getattr(base_message, "text", None) or getattr(base_message, "caption", None) or "").strip()

    newest_comment_id = workflow_request.start_comment_id
    discussion_message = await _bot.client.get_discussion_message(entity.id, workflow_request.post_id)
    if discussion_message and getattr(discussion_message, "id", None):
        newest_comment_id = max(newest_comment_id, discussion_message.id)

    _, comments = await scan_comment_range(
        client=_bot.client,
        chat_id=entity.id,
        base_message_id=workflow_request.post_id,
        start_comment_id=workflow_request.start_comment_id,
        end_comment_id=newest_comment_id,
    )
    media_comments = filter_media_comments(comments)
    summary = summarize_comments(comments)
    previews = build_naming_previews(
        comments=media_comments,
        channel=getattr(entity, "username", None) or getattr(entity, "title", None) or str(entity.id),
        post_id=workflow_request.post_id,
        post_title=post_title,
    )

    if not media_comments:
        await client.send_message(message.from_user.id, "未找到可下载的媒体评论。", reply_to_message_id=message.id)
        return

    token = build_workflow_token(workflow_request.url, message.from_user.id)
    _bot.pending_comment_workflows[token] = {
        "request": workflow_request,
        "entity_id": entity.id,
        "channel": getattr(entity, "username", None) or getattr(entity, "title", None) or str(entity.id),
        "post_title": post_title,
        "comments": media_comments,
        "source_message_id": message.id,
    }

    upload_enabled = bool(getattr(_bot.app.cloud_drive_config, "enable_upload_file", False))
    delete_after_upload = bool(getattr(_bot.app.cloud_drive_config, "after_upload_file_delete", False))
    preview_text = format_preview_message(
        channel=_bot.pending_comment_workflows[token]["channel"],
        post_id=workflow_request.post_id,
        post_title=post_title,
        start_comment_id=workflow_request.start_comment_id,
        summary=summary,
        previews=previews,
        upload_enabled=upload_enabled,
        delete_after_upload=delete_after_upload,
    )

    await client.send_message(
        message.from_user.id,
        preview_text,
        reply_to_message_id=message.id,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("采用推荐C", callback_data=build_callback_data(token, NamingStrategy.RECOMMENDED))],
                [
                    InlineKeyboardButton("采用A", callback_data=build_callback_data(token, NamingStrategy.AUTHOR)),
                    InlineKeyboardButton("采用B", callback_data=build_callback_data(token, NamingStrategy.CAPTION)),
                    InlineKeyboardButton("采用D", callback_data=build_callback_data(token, NamingStrategy.MONTH_CAPTION)),
                ],
                [InlineKeyboardButton("取消", callback_data=f"{COMMENT_WORKFLOW_PREFIX}:{token}:cancel")],
            ]
        ),
    )
```

Also include `COMMENT_WORKFLOW_PREFIX` in the import list from `module.comment_workflow`.

- [ ] **Step 6: Run workflow tests**

Run:

```bash
pytest tests/module/test_comment_workflow.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit preview UI state**

```bash
git add module/comment_workflow.py module/bot.py tests/module/test_comment_workflow.py
git commit -m "feat: preview comment link download workflow"
```

---

### Task 6: Start Confirmed Comment Download From Callback

**Files:**
- Modify: `module/bot.py`
- Modify: `media_downloader.py`

- [ ] **Step 1: Add reusable prepared-comment execution function**

In `media_downloader.py`, above `download_comments`, add:

```python
async def download_prepared_comments(
    comments: Sequence,
    download_filter: str,
    node: TaskNode,
):
    """Queue already-scanned comments for download and wait for completion."""

    from module.pyrogram_extension import report_bot_status, set_meta_data
    from utils.meta_data import MetaData
    from utils.format import validate_title
    from module.app import app

    prepared_comments = list(comments)
    if download_filter:
        class TempChatDownloadConfig:
            def __init__(self, filter_text: str):
                self.download_filter = filter_text

        temp_config = TempChatDownloadConfig(download_filter)
        filtered_comments = []
        for comment in prepared_comments:
            meta_data = MetaData()
            caption = getattr(comment, "caption", None)
            if caption:
                caption = validate_title(caption)
            set_meta_data(meta_data, comment, caption)
            if app.exec_filter(temp_config, meta_data):
                filtered_comments.append(comment)
        prepared_comments = filtered_comments

    node.total_task = len(prepared_comments)
    node.total_download_task = len(prepared_comments)
    await report_bot_status(node.bot, node)

    for comment in prepared_comments:
        if not node.is_running:
            break
        try:
            await add_download_task(comment, node)
        except Exception as error:
            logger.error(f"download_prepared_comments: failed comment {getattr(comment, 'id', None)}: {error}")
            node.failed_download_task += 1
            await report_bot_status(node.bot, node)

    while True:
        completed_tasks = node.success_download_task + node.failed_download_task + node.skip_download_task
        if completed_tasks >= len(prepared_comments):
            break
        await report_bot_status(node.bot, node)
        await asyncio.sleep(5)

    await report_bot_status(node.bot, node)
```

Add `Sequence` to the `typing` import at the top of `media_downloader.py` if missing.

- [ ] **Step 2: Refactor `download_comments` to call prepared execution**

At the end of `download_comments`, after scan and optional range logging, replace duplicate queue/wait logic with:

```python
        await download_prepared_comments(comments, download_filter, node)
        remove_active_task_node(node.task_id)
```

Keep exception cleanup behavior.

- [ ] **Step 3: Handle workflow callbacks before stop handlers**

In `module/bot.py`, add function before `on_query_handler`:

```python
async def handle_comment_workflow_callback(client: pyrogram.Client, query: pyrogram.types.CallbackQuery) -> bool:
    """Start or cancel a pending comment-link workflow from inline button data."""

    if not query.data or not query.data.startswith(f"{COMMENT_WORKFLOW_PREFIX}:"):
        return False

    parts = query.data.split(":")
    if len(parts) == 3 and parts[2] == "cancel":
        _bot.pending_comment_workflows.pop(parts[1], None)
        await client.edit_message_text(query.message.chat.id, query.message.id, "已取消评论媒体下载。")
        return True

    parsed = parse_callback_data(query.data)
    if not parsed:
        await client.answer_callback_query(query.id, "无效的命名选择")
        return True

    token, strategy = parsed
    pending = _bot.pending_comment_workflows.pop(token, None)
    if not pending:
        await client.answer_callback_query(query.id, "任务已过期，请重新发送链接")
        return True

    request = pending["request"]
    reply_message = f"from {pending['channel']} download comment media from {request.start_comment_id} for post {request.post_id} !"
    await client.edit_message_text(query.message.chat.id, query.message.id, f"已确认命名方案 {strategy.value}，开始下载。")
    last_reply_message = await client.send_message(query.message.chat.id, reply_message)

    node = TaskNode(
        chat_id=pending["entity_id"],
        from_user_id=query.from_user.id,
        reply_message_id=last_reply_message.id,
        replay_message=reply_message,
        bot=_bot.bot,
        task_id=_bot.gen_task_id(),
    )
    node.comment_naming_context = CommentNamingContext(
        strategy=strategy,
        channel=pending["channel"],
        post_id=request.post_id,
        post_title=pending["post_title"],
    )
    node.is_running = True
    _bot.add_task_node(node)
    add_active_task_node(node)

    from media_downloader import download_prepared_comments

    _bot.app.loop.create_task(download_prepared_comments(pending["comments"], None, node))
    return True
```

At the top of `on_query_handler`, add:

```python
    if await handle_comment_workflow_callback(client, query):
        return
```

- [ ] **Step 4: Run targeted tests and import check**

Run:

```bash
pytest tests/module/test_comment_workflow.py -v
python -m py_compile module/comment_workflow.py module/bot.py media_downloader.py
```

Expected: PASS and no compile errors.

- [ ] **Step 5: Commit callback execution**

```bash
git add module/bot.py media_downloader.py
git commit -m "feat: confirm and start comment media downloads"
```

---

### Task 7: Document Workflow and Run Verification

**Files:**
- Modify: `README_CN.md`
- Modify: `docs/superpowers/specs/2026-06-07-comment-link-download-design.md` only if implementation changes the approved behavior.

- [ ] **Step 1: Update Chinese README with the new workflow**

In `README_CN.md`, after the existing bot manual tag section, add:

```markdown
#### 评论链接媒体下载向导

直接把评论链接发送给 bot：

```text
https://t.me/zhyseseb/422?comment=4978
```

bot 会自动识别原帖和评论起点，扫描该帖评论区，过滤非媒体评论，并在下载前展示：

- 评论扫描数量
- 可下载媒体数量
- 媒体类型统计
- A/B/C/D 四套命名预览
- rclone 上传和上传后删除本地文件状态

确认命名方案后才会开始下载。推荐默认命名为：

```text
频道名/原帖ID-原帖标题/评论ID - 原文件名.ext
```

所有路径和文件名都会先进行非法字符清理；如果标题、caption、作者或原文件名缺失，会使用稳定兜底名称。
```

- [ ] **Step 2: Run focused test suite**

Run:

```bash
pytest tests/module/test_comment_workflow.py tests/utils/test_format.py tests/test_media_downloader.py -v
```

Expected: PASS. If this command fails, record the exact failing test and stop for review before changing unrelated code.

- [ ] **Step 3: Run compile check**

Run:

```bash
python -m py_compile module/comment_workflow.py module/bot.py media_downloader.py module/app.py
```

Expected: no output and exit code 0.

- [ ] **Step 4: Check git status**

Run:

```bash
git status --short --branch
```

Expected: only intended implementation files changed plus the user’s pre-existing `.gitignore` modification if it is still present.

- [ ] **Step 5: Commit docs and final verification updates**

```bash
git add README_CN.md docs/superpowers/specs/2026-06-07-comment-link-download-design.md
git commit -m "docs: document comment media workflow"
```

If the spec file did not change, commit only `README_CN.md`.

---

## Manual Runtime Smoke Test

After all tasks pass locally, run the app with a real bot session and perform this smoke test:

1. Send `https://t.me/zhyseseb/422?comment=4978` to the bot.
2. Verify the bot replies with scan summary and naming previews.
3. Verify non-media comments are not counted as downloadable media.
4. Click `采用推荐C`.
5. Verify files are named under `zhyseseb/422-<post-title>/`.
6. Verify rclone upload runs through existing upload settings.
7. Verify local files are deleted only after successful upload when `after_upload_file_delete: true`.
8. Verify `/stop` can stop the active download task.

## Known Baseline Issue

Before implementation, venv baseline was run with:

```bash
.venv/bin/python -m pytest -q
```

Result:

```text
1 failed, 42 passed, 1 skipped
```

Known pre-existing failure to fix after the comment-link workflow is implemented:

```text
tests/test_media_downloader.py::MediaDownloaderTestCase::test_get_media_meta
```

Observed behavior: caption is duplicated in generated media filenames, for example:

```text
2 - #home #book - #home #book - ADAVKJYIFV.jpg
```

Expected behavior: caption appears once:

```text
2 - #home #book - ADAVKJYIFV.jpg
```

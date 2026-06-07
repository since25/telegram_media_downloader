"""Pure helpers for guided Telegram comment-link media downloads."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence

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


class CommentLike(Protocol):
    """Minimal message shape expected by the pure workflow helpers."""

    id: int
    media: Any
    empty: bool


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

    if not text:
        return None

    url = text.strip()
    if not url.startswith("https://t.me"):
        return None

    link = extract_info_from_link(url)
    if link.group_id is None or link.post_id is None or link.comment_id is None:
        return None

    return CommentWorkflowRequest(
        url=url,
        source_chat=link.group_id,
        post_id=link.post_id,
        start_comment_id=link.comment_id,
    )


def is_media_comment(comment: Optional[CommentLike]) -> bool:
    """Return True when a comment contains a supported media payload."""

    if not comment or getattr(comment, "empty", False):
        return False

    media_name = _media_name(comment)
    return (
        media_name in SUPPORTED_MEDIA_TYPES
        and bool(getattr(comment, media_name, None))
    )


def filter_media_comments(comments: Iterable[CommentLike]) -> List[CommentLike]:
    """Keep only supported media comments."""

    return [comment for comment in comments if is_media_comment(comment)]


def summarize_comments(comments: Sequence[CommentLike]) -> CommentScanSummary:
    """Build a scan summary for user confirmation."""

    comment_list = [
        comment for comment in comments if comment and hasattr(comment, "id")
    ]
    media_comments = filter_media_comments(comment_list)
    media_type_counts: Dict[str, int] = {}

    for comment in media_comments:
        media_name = _media_name(comment)
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
    if len(parts) != 3 or parts[0] != COMMENT_WORKFLOW_PREFIX or not parts[1]:
        return None

    try:
        strategy = NamingStrategy(parts[2])
    except ValueError:
        return None

    return parts[1], strategy


def clean_segment(value: Optional[str], fallback: str, max_len: int = 40) -> str:
    """Clean one filename/path segment with deterministic fallback."""

    text = _normalize_segment(value)
    if not text:
        text = _normalize_segment(fallback)
    if not text:
        text = "fallback"
    return text[:max_len]


def original_file_name_for_comment(comment: CommentLike) -> str:
    """Return cleaned original media filename or a stable fallback."""

    media_name = _media_name(comment)
    media = getattr(comment, media_name, None)
    extension = _extension_for_comment(comment)
    fallback = f"comment-{comment.id}-{media_name}.{extension}"
    raw_file_name = getattr(media, "file_name", None)
    raw_stem = os.path.splitext(raw_file_name or "")[0]
    if _normalize_segment(raw_stem):
        return clean_segment(raw_file_name, fallback, 80)

    return fallback


def caption_summary_for_comment(comment: CommentLike) -> str:
    """Return cleaned caption summary fallback."""

    return clean_segment(getattr(comment, "caption", None), "no-caption", 40)


def author_for_comment(comment: CommentLike) -> str:
    """Return cleaned author display fallback."""

    user = getattr(comment, "from_user", None)
    author = getattr(user, "username", None) or getattr(user, "first_name", None)
    return clean_segment(author, "anonymous", 40)


def month_for_comment(comment: CommentLike) -> str:
    """Return comment month partition or a stable fallback."""

    date = getattr(comment, "date", None)
    if not date:
        return "0000_00"
    return date.strftime("%Y_%m")


def build_name_for_strategy(
    comment: CommentLike,
    context: CommentNamingContext,
) -> str:
    """Build a relative display path for a comment and naming context."""

    channel = clean_segment(context.channel, "channel", 40)
    post_title = clean_segment(context.post_title, f"post-{context.post_id}", 60)
    original_file_name = original_file_name_for_comment(comment)
    caption_summary = caption_summary_for_comment(comment)
    extension = _extension_for_comment(comment)

    if context.strategy is NamingStrategy.AUTHOR:
        return f"{post_title}/{comment.id} - {author_for_comment(comment)} - {original_file_name}"
    if context.strategy is NamingStrategy.CAPTION:
        return f"{post_title}/{comment.id} - {caption_summary} - {original_file_name}"
    if context.strategy is NamingStrategy.MONTH_CAPTION:
        return f"{channel}/{month_for_comment(comment)}/{post_title}/{comment.id} - {caption_summary}.{extension}"
    return f"{channel}/{context.post_id}-{post_title}/{comment.id} - {original_file_name}"


def build_naming_previews(
    comments: Sequence[CommentLike],
    channel: str,
    post_id: int,
    post_title: str,
    sample_size: int = 3,
) -> List[NamingPreview]:
    """Build concrete preview examples for all naming strategies."""

    sample_comments = filter_media_comments(comments)[:sample_size]
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
                examples=[
                    build_name_for_strategy(comment, context)
                    for comment in sample_comments
                ],
            )
        )

    return previews


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
    """Format the guided comment workflow preview shown before download."""

    cleaned_title = clean_segment(post_title, f"post-{post_id}", 60)
    last_comment_id = summary.last_comment_id or start_comment_id
    media_type_counts = (
        "、".join(
            f"{media_type} {count}"
            for media_type, count in sorted(summary.media_type_counts.items())
        )
        or "无"
    )
    lines = [
        "评论媒体下载预览",
        f"频道：{channel}",
        f"原帖：{post_id}",
        f"原帖标题：{cleaned_title}",
        f"评论范围：{start_comment_id} → {last_comment_id}",
        f"扫描评论：{summary.scanned_count}",
        f"媒体评论：{summary.media_count}",
        f"类型：{media_type_counts}",
        f"上传：{'enabled' if upload_enabled else 'disabled'}",
        f"上传后删除本地：{'enabled' if delete_after_upload else 'disabled'}",
        "",
        "命名预览：",
    ]

    for preview in previews:
        title = preview.title
        if preview.strategy is NamingStrategy.RECOMMENDED:
            title = f"{title}（采用推荐C）"
        lines.append(title)
        if preview.examples:
            lines.extend(f"- {example}" for example in preview.examples)
        else:
            lines.append("- 无示例")

    return "\n".join(lines)


def _media_name(comment: CommentLike) -> str:
    media = getattr(comment, "media", None)
    return getattr(media, "value", media)


def _extension_for_comment(comment: CommentLike) -> str:
    media_name = _media_name(comment)
    media = getattr(comment, media_name, None)
    file_name = getattr(media, "file_name", None)
    if file_name:
        extension = os.path.splitext(file_name)[1].lstrip(".")
        if extension:
            return clean_segment(extension, "bin", 16)

    if media_name == "photo":
        return "jpg"
    if media_name in ("video", "video_note"):
        return "mp4"
    if media_name == "voice":
        return "ogg"
    if media_name == "audio":
        return "mp3"
    return "bin"


def _normalize_segment(value: Optional[str]) -> str:
    text = " ".join((value or "").split())
    return validate_title(text).strip(" .-_") if text else ""

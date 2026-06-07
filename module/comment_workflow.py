"""Pure helpers for guided Telegram comment-link media downloads."""

from __future__ import annotations

import hashlib
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


def _media_name(comment: CommentLike) -> str:
    media = getattr(comment, "media", None)
    return getattr(media, "value", media)


def _normalize_segment(value: Optional[str]) -> str:
    text = " ".join((value or "").split())
    return validate_title(text).strip(" .-_") if text else ""

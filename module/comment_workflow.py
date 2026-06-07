"""Pure helpers for guided Telegram comment-link media downloads."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Protocol, Sequence
from urllib.parse import parse_qs, urlparse

from utils.format import extract_info_from_link, format_byte, validate_title

COMMENT_WORKFLOW_PREFIX = "cw"
PACKAGE_WORKFLOW_PREFIX = "pw"
SUPPORTED_MEDIA_TYPES = {
    "audio",
    "document",
    "photo",
    "video",
    "voice",
    "video_note",
}

_SEQUENCE_PATTERNS = [
    re.compile(r"\d+\s*[/_]\s*\d+"),
    re.compile(r"EP\s*\d+", re.IGNORECASE),
    re.compile(r"第\s*\d+\s*[集话]"),
    re.compile(r"^[\[【(（]?\s*\d{1,4}\s*[\]】)）]?(?:[-_.:： ]+)?"),
    re.compile(r"(?:[-_.:： ]+)?[\[【(（]?\s*\d{1,4}\s*[\]】)）]?$"),
]


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
class MessagePackageWorkflowRequest:
    """Parsed direct ordinary message-link package workflow request."""

    url: str
    source_chat: str | int
    start_message_id: int


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


@dataclass
class PackageNamingContext:
    """Values used to build final names for package media files."""

    strategy: NamingStrategy
    channel: str
    start_message_id: int
    package_title: str


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


def build_message_package_workflow_request(
    text: str,
) -> Optional[MessagePackageWorkflowRequest]:
    """Return a package workflow request for direct non-comment message links."""

    if not text:
        return None

    url = text.strip()
    if not url.startswith("https://t.me"):
        return None

    query = parse_qs(urlparse(url).query, keep_blank_values=True)
    if "comment" in query:
        return None

    try:
        link = extract_info_from_link(url)
    except (TypeError, ValueError):
        return None

    if link.group_id is None or link.post_id is None or link.comment_id is not None:
        return None

    return MessagePackageWorkflowRequest(
        url=url,
        source_chat=link.group_id,
        start_message_id=link.post_id,
    )


def _message_caption(message: CommentLike) -> Optional[str]:
    """Return sanitized caption text for package planning."""

    return _sanitize_caption_text(getattr(message, "caption", None))


def normalize_caption_for_boundary(caption: Optional[str]) -> str:
    """Normalize caption text for loose package-boundary comparison."""

    text = _sanitize_caption_text(caption)
    normalized = re.sub(r"\s+", "", text or "")
    for pattern in _SEQUENCE_PATTERNS:
        normalized = pattern.sub("", normalized)
    return normalized.strip("-_—:：.。 ")


def captions_are_similar(current: Optional[str], candidate: Optional[str]) -> bool:
    """Return True when captions likely belong to the same package."""

    current_norm = normalize_caption_for_boundary(current)
    candidate_norm = normalize_caption_for_boundary(candidate)
    if not current_norm or not candidate_norm:
        return True
    if current_norm == candidate_norm:
        return True
    shorter, longer = sorted([current_norm, candidate_norm], key=len)
    return len(shorter) >= 4 and shorter in longer


def plan_message_package(
    messages: Sequence[CommentLike],
    start_message_id: int,
    max_scan_count: int = 500,
) -> MessagePackagePlan:
    """Plan one continuous ordinary-message media package from a start id."""

    candidates = sorted(
        [
            message
            for message in messages
            if message and hasattr(message, "id") and message.id >= start_message_id
        ],
        key=lambda message: message.id,
    )
    scanned_messages = candidates[:max_scan_count]
    scan_limit_hit = max_scan_count > 0 and len(scanned_messages) >= max_scan_count

    group_captions: Dict[str, str] = {}
    for message in scanned_messages:
        media_group_id = getattr(message, "media_group_id", None)
        if not media_group_id or media_group_id in group_captions:
            continue
        caption = _message_caption(message)
        if caption:
            group_captions[media_group_id] = caption

    items: List[PackageMediaItem] = []
    package_title: Optional[str] = None
    current_caption: Optional[str] = None
    next_package_message: Optional[CommentLike] = None
    inherited_caption_count = 0

    for message in scanned_messages:
        media_type, _media_obj = media_payload_for_message(message)
        if not media_type:
            continue

        raw_caption = _message_caption(message)
        media_group_id = getattr(message, "media_group_id", None)
        group_caption = group_captions.get(media_group_id) if media_group_id else None
        candidate_caption = raw_caption or group_caption

        if items and candidate_caption and current_caption:
            if not captions_are_similar(current_caption, candidate_caption):
                next_package_message = message
                break

        effective_caption = raw_caption
        if not effective_caption and media_group_id:
            effective_caption = group_captions.get(media_group_id)
        if not effective_caption:
            effective_caption = current_caption

        inherited_caption = raw_caption is None and effective_caption is not None
        if inherited_caption:
            inherited_caption_count += 1

        if raw_caption:
            current_caption = raw_caption
            if package_title is None:
                package_title = raw_caption
                for item in items:
                    if item.original_caption is not None:
                        continue
                    if item.caption_for_naming != f"message-{item.message.id}":
                        continue
                    item.caption_for_naming = raw_caption
                    item.inherited_caption = True
                    inherited_caption_count += 1
        elif effective_caption and current_caption is None:
            current_caption = effective_caption
            if package_title is None:
                package_title = effective_caption

        items.append(
            PackageMediaItem(
                message=message,
                media_type=media_type,
                caption_for_naming=effective_caption or f"message-{message.id}",
                original_caption=raw_caption,
                inherited_caption=inherited_caption,
            )
        )

    package_messages = [item.message for item in items]
    if package_title is None:
        package_title = f"message-{start_message_id}"

    scan_warning = None
    if scan_limit_hit and next_package_message is None:
        scan_warning = f"未发现下一包边界，已达到扫描上限 {max_scan_count} 条。"

    return MessagePackagePlan(
        items=items,
        package_title=package_title,
        summary=summarize_comments(package_messages),
        size_summary=build_size_summary(package_messages),
        inherited_caption_count=inherited_caption_count,
        next_package_message=next_package_message,
        scan_warning=scan_warning,
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


def build_size_summary(
    messages: Sequence[CommentLike], sample_size: int = 3
) -> SizeSummary:
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


def build_package_name_for_strategy(
    item: PackageMediaItem,
    context: PackageNamingContext,
) -> str:
    """Build a relative display path for a package media item."""

    message = item.message
    channel = clean_segment(context.channel, "channel", 40)
    title = clean_segment(
        context.package_title, f"message-{context.start_message_id}", 60
    )
    original_file_name = media_file_name_for_message(message)
    caption_summary = clean_segment(item.caption_for_naming, "no-caption", 40)
    extension = _extension_for_comment(message)

    if context.strategy is NamingStrategy.AUTHOR:
        return (
            f"{title}/{message.id} - "
            f"{author_for_comment(message)} - {original_file_name}"
        )
    if context.strategy is NamingStrategy.CAPTION:
        return f"{title}/{message.id} - {caption_summary} - {original_file_name}"
    if context.strategy is NamingStrategy.MONTH_CAPTION:
        return (
            f"{channel}/{month_for_comment(message)}/{title}/"
            f"{message.id} - {caption_summary}.{extension}"
        )
    return (
        f"{channel}/{context.start_message_id}-{title}/"
        f"{message.id} - {original_file_name}"
    )


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
        context = PackageNamingContext(
            strategy=strategy,
            channel=channel,
            start_message_id=start_message_id,
            package_title=package_title,
        )
        previews.append(
            NamingPreview(
                strategy=strategy,
                title=title,
                examples=[
                    build_package_name_for_strategy(item, context)
                    for item in sample_items
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
    failed_comment_ids: Optional[Sequence[int]] = None,
    scan_warning: Optional[str] = None,
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
    ]
    if scan_warning:
        lines.append(f"扫描警告：{scan_warning}")
    if failed_comment_ids:
        lines.append(f"扫描失败评论：{len(failed_comment_ids)}")
    lines.extend(["", "命名预览："])

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


def _format_size_details(summary: SizeSummary) -> List[str]:
    lines = [format_size_summary(summary)]
    if summary.largest:
        lines.append(
            "最大文件："
            f"{summary.largest.message_id} "
            f"{summary.largest.media_type} "
            f"{format_byte(summary.largest.size)}"
        )
    if summary.samples:
        lines.append("大小示例：")
        for item in summary.samples:
            lines.append(
                f"- {item.message_id} {item.media_type} {format_byte(item.size)}"
            )
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

    del start_message_id

    media_ids = [item.message.id for item in package_plan.items]
    range_text = f"{min(media_ids)} - {max(media_ids)}" if media_ids else "无"
    media_types = ", ".join(
        f"{key} {value} 个"
        for key, value in sorted(package_plan.summary.media_type_counts.items())
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
                (
                    f"{package_plan.next_package_message.id} - "
                    f"{_preview_caption(package_plan.next_package_message)}"
                ),
                "不会纳入本次下载。",
            ]
        )
    lines.append("")
    lines.append("命名预览：")
    for preview in previews:
        lines.append(preview.title)
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


def _sanitize_caption_text(caption: Optional[str]) -> Optional[str]:
    text = " ".join(str(caption or "").split())
    text = validate_title(text).strip()
    return text or None

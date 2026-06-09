"""Pure helpers for prescan package planning and selection UI."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Set, Tuple

from module.comment_workflow import (
    MessagePackagePlan,
    PackageMediaItem,
    clean_segment,
    format_size_summary,
    plan_message_package,
)

PRESCAN_WORKFLOW_PREFIX = "ps"
PRESCAN_PAGE_SIZE = 8

_MAX_MESSAGES_WARNING = "预扫已达到安全上限，结果可能不是频道最新消息。"
_MAX_PACKAGES_WARNING = "预扫已达到包数量上限，结果可能不是频道最新消息。"


@dataclass
class PrescanLimits:
    """Safety limits for prescan planning."""

    max_messages: int = 5000
    max_packages: int = 50
    missing_streak_limit: int = 200


@dataclass
class PrescanPackage:
    """One selectable package discovered during prescan."""

    package_id: int
    title: str
    start_message_id: int
    end_message_id: int
    items: List[PackageMediaItem]
    package_plan: MessagePackagePlan
    messages: List[Any]
    failed_message_ids: List[int] = field(default_factory=list)

    @property
    def media_count(self) -> int:
        """Return the number of media items in this package."""

        return len(self.items)

    @property
    def size_summary(self):
        """Return the package size summary."""

        return self.package_plan.size_summary


@dataclass
class PrescanPlan:
    """Prescan result containing selectable packages."""

    start_message_id: int
    scanned_count: int
    packages: List[PrescanPackage]
    warning: Optional[str] = None


def plan_prescan_packages(
    messages: Sequence[Any],
    start_message_id: int,
    limits: Optional[PrescanLimits] = None,
) -> PrescanPlan:
    """Split scanned messages into selectable media packages."""

    limits = limits or PrescanLimits()
    raw_candidates = sorted(
        [
            message
            for message in messages
            if message and hasattr(message, "id") and message.id >= start_message_id
        ],
        key=lambda message: message.id,
    )
    max_messages = max(limits.max_messages, 0)
    message_limit_hit = len(raw_candidates) > max_messages
    scanned_messages = raw_candidates[:max_messages] if max_messages else []

    packages: List[PrescanPackage] = []
    package_limit_hit = False
    current_start_message_id = start_message_id
    max_packages = max(limits.max_packages, 0)

    while max_packages and len(packages) < max_packages:
        remaining_messages = [
            message
            for message in scanned_messages
            if message.id >= current_start_message_id
        ]
        if not remaining_messages:
            break

        package_plan = plan_message_package(
            remaining_messages,
            start_message_id=current_start_message_id,
            max_scan_count=len(remaining_messages) + 1,
        )
        if not package_plan.items:
            break

        package = _build_prescan_package(len(packages) + 1, package_plan)
        packages.append(package)

        next_message = package_plan.next_package_message
        if not next_message:
            break
        if next_message.id <= current_start_message_id:
            break
        if len(packages) >= max_packages:
            package_limit_hit = True
            break
        current_start_message_id = next_message.id

    warning = None
    if message_limit_hit:
        warning = _MAX_MESSAGES_WARNING
    if package_limit_hit:
        warning = _MAX_PACKAGES_WARNING

    return PrescanPlan(
        start_message_id=start_message_id,
        scanned_count=len(scanned_messages),
        packages=packages,
        warning=warning,
    )


def build_prescan_callback_data(token: str, action: str, value: Any = "") -> str:
    """Build compact callback data for prescan controls."""

    if not token:
        raise ValueError("prescan callback token must not be empty")
    if not action:
        raise ValueError("prescan callback action must not be empty")
    token_text = _validate_callback_part("token", token)
    action_text = _validate_callback_part("action", action)
    value_text = _validate_callback_part("value", value)
    if value == "" or value is None:
        return f"{PRESCAN_WORKFLOW_PREFIX}:{token_text}:{action_text}"
    return f"{PRESCAN_WORKFLOW_PREFIX}:{token_text}:{action_text}:{value_text}"


def parse_prescan_callback_data(data: str) -> Optional[Tuple[str, str, str]]:
    """Parse prescan callback data into token, action, and value."""

    parts = data.split(":")
    if len(parts) not in (3, 4):
        return None
    if parts[0] != PRESCAN_WORKFLOW_PREFIX or not parts[1] or not parts[2]:
        return None

    value = parts[3] if len(parts) == 4 else ""
    return parts[1], parts[2], value


def _validate_callback_part(name: str, value: Any) -> str:
    text = str(value)
    if ":" in text:
        raise ValueError(f"prescan callback {name} must not contain ':'")
    return text


def page_packages(
    plan: PrescanPlan,
    page: int,
    page_size: int = PRESCAN_PAGE_SIZE,
) -> List[PrescanPackage]:
    """Return the packages visible on a zero-based selection page."""

    if page_size <= 0:
        return []
    page_index = max(page, 0)
    start = page_index * page_size
    return plan.packages[start : start + page_size]


def format_prescan_selection_page(
    plan: PrescanPlan,
    channel: str,
    page: int,
    selected_package_ids: Set[int],
    page_size: int = PRESCAN_PAGE_SIZE,
) -> str:
    """Format a compact mobile-friendly package selection page."""

    selected_count = sum(
        1 for package in plan.packages if package.package_id in selected_package_ids
    )
    lines = [
        "预扫完成：",
        f"频道：{channel}",
        f"起点：{plan.start_message_id}",
        f"扫描：{plan.scanned_count} 条消息",
        f"识别：{len(plan.packages)} 个包",
        f"已选：{selected_count} 个",
    ]
    if plan.warning:
        lines.append(f"提示：{plan.warning}")

    visible_packages = page_packages(plan, page, page_size)
    if visible_packages:
        lines.append("")
    for package in visible_packages:
        marker = "*" if package.package_id in selected_package_ids else ""
        range_text = f"{package.start_message_id}-{package.end_message_id}"
        size_text = _compact_size_summary(package)
        row = (
            f"{marker} {package.package_id}. {range_text}"
            f"｜{package.media_count} 个｜{size_text}"
        ).strip()
        lines.append(row)
        lines.append(package.title)

    return "\n".join(lines)


def summarize_prescan_progress(
    start_message_id: int,
    scanned_count: int,
    package_count: int,
    latest_package: Optional[PrescanPackage] = None,
    rate_limited_seconds: Optional[int] = None,
) -> str:
    """Format progress text while an async prescan is still running."""

    lines = [
        "预扫中...",
        f"起点：{start_message_id}",
        f"已扫描：{scanned_count} 条消息",
        f"已识别：{package_count} 个包",
    ]
    if latest_package:
        lines.append(
            "最近包："
            f"{latest_package.start_message_id}-{latest_package.end_message_id}"
            f"｜{latest_package.media_count} 个｜{latest_package.title}"
        )
    if rate_limited_seconds is not None:
        lines.append(f"限流暂停：{rate_limited_seconds} 秒")
    return "\n".join(lines)


def _build_prescan_package(
    package_id: int,
    package_plan: MessagePackagePlan,
) -> PrescanPackage:
    messages = [item.message for item in package_plan.items]
    message_ids = [message.id for message in messages]
    start_message_id = min(message_ids)
    end_message_id = max(message_ids)
    return PrescanPackage(
        package_id=package_id,
        title=_package_title(package_plan, start_message_id),
        start_message_id=start_message_id,
        end_message_id=end_message_id,
        items=list(package_plan.items),
        package_plan=package_plan,
        messages=messages,
    )


def _package_title(package_plan: MessagePackagePlan, start_message_id: int) -> str:
    for item in package_plan.items:
        caption = getattr(item.message, "caption", None)
        title = " ".join(str(caption or "").split())
        if title:
            return title[:80]
    return clean_segment(package_plan.package_title, f"message-{start_message_id}", 80)


def _compact_size_summary(package: PrescanPackage) -> str:
    size_text = format_size_summary(package.size_summary)
    prefix = "预计大小："
    if size_text.startswith(prefix):
        size_text = size_text[len(prefix) :]
    return re.sub(r"\b(\d+)B\b", r"\1.0B", size_text)

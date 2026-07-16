"""Persisted-message adaptation and package indexing for channel libraries."""

from __future__ import annotations

import datetime
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Optional

from module.channel_library_store import ChannelLibraryStore
from module.comment_workflow import (
    SUPPORTED_MEDIA_TYPES,
    media_payload_for_message,
    plan_message_package_sequence,
)


UTC = datetime.timezone.utc


@dataclass
class MediaDTO:
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None


def parse_utc_datetime(value: Any) -> Optional[datetime.datetime]:
    """Parse a stored datetime and normalize it to an aware UTC value."""

    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        parsed = datetime.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class PersistedMessageAdapter:
    """Restore the message protocol used by the existing package planner."""

    def __init__(self, row: Mapping[str, Any]):
        self.id = int(row["message_id"])
        self.empty = False
        self.caption = row.get("caption")
        self.media_group_id = row.get("media_group_id")
        self.date = parse_utc_datetime(row.get("message_date"))
        media_type = str(row["media_type"])
        self.media = media_type
        for name in SUPPORTED_MEDIA_TYPES:
            setattr(self, name, None)
        setattr(
            self,
            media_type,
            MediaDTO(
                file_name=row.get("file_name"),
                file_size=row.get("file_size"),
                mime_type=row.get("mime_type"),
                duration=row.get("duration"),
                width=row.get("width"),
                height=row.get("height"),
            ),
        )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "PersistedMessageAdapter":
        return cls(row)


def extract_media_row(message: Any) -> Optional[dict]:
    """Extract planner and listing metadata from one supported media message."""

    media_type, media = media_payload_for_message(message)
    if media_type is None or media is None:
        return None
    message_date = parse_utc_datetime(getattr(message, "date", None))
    row = {
        "message_id": int(message.id),
        "message_date": message_date.isoformat() if message_date else None,
        "media_type": media_type,
        "media_group_id": (
            str(message.media_group_id)
            if getattr(message, "media_group_id", None) is not None
            else None
        ),
        "caption": getattr(message, "caption", None),
        "file_name": getattr(media, "file_name", None),
        "file_size": getattr(media, "file_size", None),
        "mime_type": getattr(media, "mime_type", None),
        "duration": getattr(media, "duration", None),
        "width": getattr(media, "width", None),
        "height": getattr(media, "height", None),
    }
    fingerprint_payload = json.dumps(
        row,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    row["raw_fingerprint"] = hashlib.sha256(fingerprint_payload).hexdigest()
    return row


@dataclass(frozen=True)
class IndexResult:
    index_revision: int
    indexed_through_message_id: int
    stable_package_count: int
    changed_package_count: int
    superseded_package_count: int
    invalidated_selection_count: int


class ChannelPackageIndexer:
    """Plan persisted messages and atomically publish a derived package revision."""

    def index_through(
        self,
        store: ChannelLibraryStore,
        job: Mapping[str, Any],
        through_message_id: int,
    ) -> IndexResult:
        context = store.load_package_index_context(
            int(job["id"]),
            int(job["library_id"]),
            int(through_message_id),
        )
        messages = [
            PersistedMessageAdapter.from_row(row) for row in context["media_rows"]
        ]
        package_plans = []
        if messages:
            sequence = plan_message_package_sequence(
                messages,
                start_message_id=messages[0].id,
                following_package_count=len(messages),
                max_scan_count=len(messages) + 1,
            )
            package_plans = [
                package for package in sequence.all_packages if package.items
            ]

        through = int(through_message_id)
        snapshot_end = int(context["job"]["snapshot_max_message_id"])
        at_snapshot_end = through >= snapshot_end
        uncertain_intervals = []
        failure_updates = []
        package_starts = [plan.items[0].message.id for plan in package_plans]
        for failure in context["failures"]:
            starts_after_failure = [
                start
                for start in package_starts
                if start > int(failure["end_message_id"])
            ]
            if len(starts_after_failure) >= 2:
                uncertain_through = starts_after_failure[1] - 1
            else:
                uncertain_through = through
            uncertain_intervals.append(
                (int(failure["reindex_anchor_start"]), uncertain_through)
            )
            failure_updates.append(
                {
                    "failure_id": int(failure["id"]),
                    "uncertain_through_message_id": uncertain_through,
                }
            )

        packages = []
        for plan in package_plans:
            first_item = plan.items[0]
            last_item = plan.items[-1]
            start_message_id = int(first_item.message.id)
            end_message_id = int(last_item.message.id)
            boundary_status = (
                "stable"
                if plan.next_package_message is not None or at_snapshot_end
                else "provisional"
            )
            if any(
                uncertain_start <= start_message_id <= uncertain_end
                for uncertain_start, uncertain_end in uncertain_intervals
            ):
                boundary_status = "uncertain"
            published_at = first_item.message.date
            packages.append(
                {
                    "start_message_id": start_message_id,
                    "end_message_id": end_message_id,
                    "title": plan.package_title,
                    "published_at": (
                        published_at.isoformat() if published_at is not None else None
                    ),
                    "boundary_status": boundary_status,
                    "media_count": plan.summary.media_count,
                    "known_total_size": plan.size_summary.known_total_size,
                    "unknown_size_count": plan.size_summary.unknown_size_count,
                    "items": [
                        {
                            "message_id": int(item.message.id),
                            "ordinal": ordinal,
                            "media_type": item.media_type,
                            "caption_for_naming": item.caption_for_naming,
                            "original_caption": item.original_caption,
                            "inherited_caption": item.inherited_caption,
                        }
                        for ordinal, item in enumerate(plan.items)
                    ],
                }
            )

        publication = store.publish_indexed_packages(
            job_id=int(job["id"]),
            through_message_id=through,
            reindex_anchor_start=int(context["reindex_anchor_start"]),
            packages=packages,
            failure_updates=failure_updates,
        )
        return IndexResult(
            index_revision=publication["index_revision"],
            indexed_through_message_id=publication["indexed_through_message_id"],
            stable_package_count=publication["stable_package_count"],
            changed_package_count=publication["changed_package_count"],
            superseded_package_count=publication["superseded_package_count"],
            invalidated_selection_count=publication["invalidated_selection_count"],
        )

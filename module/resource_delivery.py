"""Deliver indexed resource packages through main-account download and Bot upload."""

from __future__ import annotations

import asyncio
import io
import mimetypes
import os
import shutil
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Optional

import pyrogram
from loguru import logger
from pyrogram import enums, types

from module.telegram_activity import get_telegram_activity_gate


GROUPABLE_MEDIA_TYPES = frozenset({"photo", "video", "audio", "document"})
DEFAULT_EXTENSIONS = {
    "audio": ".mp3",
    "document": ".bin",
    "photo": ".jpg",
    "video": ".mp4",
    "voice": ".ogg",
    "video_note": ".mp4",
}


class TransferSpeedTracker:
    """Report byte-per-second samples at a bounded persistence cadence."""

    def __init__(
        self,
        reporter: Callable[[int], None],
        *,
        clock=time.monotonic,
        interval: float = 1.0,
    ) -> None:
        self.reporter = reporter
        self.clock = clock
        self.interval = max(float(interval), 0.1)
        self.last_time: Optional[float] = None
        self.last_current = 0

    def observe(self, current: int, total: int) -> None:
        current_bytes = max(int(current), 0)
        total_bytes = max(int(total), 0)
        now = float(self.clock())
        if self.last_time is None:
            self.last_time = now
        elapsed = now - self.last_time
        terminal = total_bytes > 0 and current_bytes >= total_bytes
        if current_bytes == self.last_current and terminal:
            return
        if elapsed < self.interval and not terminal:
            return
        if elapsed <= 0:
            return
        transferred = max(current_bytes - self.last_current, 0)
        self.reporter(max(int(transferred / elapsed), 0))
        self.last_time = now
        self.last_current = current_bytes


class _TrackedUploadFile(io.BufferedReader):
    """Binary file wrapper that observes album upload reads without splitting it."""

    def __init__(self, path: Path, tracker: TransferSpeedTracker) -> None:
        super().__init__(io.FileIO(path, "rb"))
        self._tracker = tracker
        self._transferred = 0
        self._total = int(path.stat().st_size)

    def read(self, size: int = -1) -> bytes:
        chunk = super().read(size)
        self._transferred += len(chunk)
        self._tracker.observe(self._transferred, self._total)
        return chunk


class DeliveryError(RuntimeError):
    """Stable delivery failure safe to persist and show to users."""

    def __init__(self, code: str, summary: str):
        super().__init__(code)
        self.code = code
        self.summary = summary


@dataclass(frozen=True)
class PreparedDeliveryItem:
    """One immutable package item before or after local media preparation."""

    ordinal: int
    source_chat_id: int
    source_message_id: int
    media_type: str
    media_group_id: Optional[str]
    caption: Optional[str]
    file_name: str
    local_path: Optional[Path] = None
    message: Any = None


def safe_delivery_filename(item: dict) -> str:
    """Return a path-safe, stable filename scoped by package ordinal/message ID."""

    ordinal = max(int(item.get("ordinal") or 0), 0)
    message_id = int(
        item.get("source_message_id")
        or item.get("message_id")
        or 0
    )
    raw_name = str(item.get("file_name") or "").replace("\\", "/")
    basename = os.path.basename(raw_name).replace("\x00", "").strip()
    if basename in {"", ".", ".."}:
        media_type = str(item.get("media_type") or "document")
        extension = mimetypes.guess_extension(str(item.get("mime_type") or ""))
        extension = extension or DEFAULT_EXTENSIONS.get(media_type, ".bin")
        basename = f"{media_type}{extension}"
    return f"{ordinal:04d}-{message_id}-{basename}"


def _album_compatible(items: list[PreparedDeliveryItem]) -> bool:
    if len(items) < 2:
        return False
    media_types = {item.media_type for item in items}
    if not media_types <= GROUPABLE_MEDIA_TYPES:
        return False
    return (
        media_types <= {"photo", "video"}
        or media_types == {"audio"}
        or media_types == {"document"}
    )


def build_delivery_groups(
    items: list[PreparedDeliveryItem],
) -> list[list[PreparedDeliveryItem]]:
    """Preserve ordinal order and retain only Telegram-compatible albums."""

    ordered = sorted(items, key=lambda item: item.ordinal)
    grouped: list[list[PreparedDeliveryItem]] = []
    index = 0
    while index < len(ordered):
        item = ordered[index]
        if not item.media_group_id:
            grouped.append([item])
            index += 1
            continue
        contiguous = [item]
        index += 1
        while (
            index < len(ordered)
            and ordered[index].media_group_id == item.media_group_id
        ):
            contiguous.append(ordered[index])
            index += 1
        if _album_compatible(contiguous):
            for offset in range(0, len(contiguous), 10):
                grouped.append(contiguous[offset : offset + 10])
        else:
            grouped.extend([[entry] for entry in contiguous])
    return grouped


class ResourceDeliveryService:
    """Own one persistent serial resource delivery worker."""

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
        clock=time.monotonic,
    ) -> None:
        self.app = app
        self.main_client = main_client
        self.resource_client = resource_client
        self.resource_store = resource_store
        self.channel_store = channel_store
        self.temp_root = Path(temp_root)
        self.activity_gate = activity_gate or get_telegram_activity_gate()
        self.sleep = sleep
        self.clock = clock
        self.worker_task: Optional[asyncio.Task] = None
        self._wake_event: Optional[asyncio.Event] = None
        self._stopping = False

    async def start(self) -> None:
        """Recover persisted work and start exactly one worker."""

        if self.worker_task is not None and not self.worker_task.done():
            return
        self.resource_store.recover_interrupted_jobs()
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self._wake_event = asyncio.Event()
        self._stopping = False
        self.worker_task = asyncio.create_task(
            self._run_worker(), name="resource-delivery-worker"
        )
        await self.wake()

    async def stop(self) -> None:
        """Stop accepting work and interrupt the active non-atomic delivery."""

        self._stopping = True
        await self.wake()
        task = self.worker_task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.worker_task = None
        self._wake_event = None

    async def wake(self) -> None:
        if self._wake_event is not None:
            self._wake_event.set()

    async def enqueue(
        self,
        *,
        idempotency_key: str,
        user_id: int,
        package_id: int,
        target_chat_id: int,
    ) -> tuple[dict, bool]:
        """Snapshot one stable package into an idempotent queued delivery."""

        if self.channel_store is None:
            raise ValueError("service_unavailable")
        package = self.channel_store.get_package(int(package_id))
        if package is None:
            raise ValueError("package_not_found")
        if package.get("boundary_status") != "stable":
            raise ValueError("package_changed")
        items = self._load_package_items(int(package_id))
        job, created = self.resource_store.create_delivery_job(
            idempotency_key=idempotency_key,
            user_id=int(user_id),
            package_id=int(package_id),
            package_revision=int(package["index_revision"]),
            target_chat_id=int(target_chat_id),
            total_items=len(items),
        )
        if created:
            await self.wake()
        return job, created

    def _load_package_items(self, package_id: int) -> list[dict]:
        items: list[dict] = []
        cursor = None
        while True:
            page = self.channel_store.list_package_items_aggregate(
                int(package_id), cursor=cursor, limit=200
            )
            items.extend(page.items)
            cursor = page.next_cursor
            if cursor is None:
                return items

    async def _run_worker(self) -> None:
        while not self._stopping:
            if self._wake_event is not None:
                self._wake_event.clear()
            job = self.resource_store.claim_next_delivery_job()
            if job is not None:
                await self.process_job(job)
                continue
            if self._wake_event is None:
                return
            await self._wake_event.wait()

    async def process_job(self, job: dict) -> dict:
        """Execute one already-claimed job and persist its terminal result."""

        job_id = int(job["id"])
        job_dir = self.temp_root / str(job["public_id"])
        result = None
        try:
            package = self._validated_package(job)
            await self._require_target_permission(job)
            items = self._prepare_items(job)
            if not items:
                raise DeliveryError(
                    "source_message_missing", "Resource package has no media items"
                )
            job_dir.mkdir(parents=True, exist_ok=True)
            downloaded = await self._download_all(job, items, job_dir)
            self.resource_store.update_job_progress(
                job_id,
                status="uploading",
                downloaded_items=len(downloaded),
                uploaded_items=0,
                download_speed=0,
                upload_speed=0,
            )
            uploaded_count = await self._upload_all(job, downloaded)
            result = self.resource_store.finish_delivery_job(job_id, "completed")
            logger.info(
                "Resource delivery {} completed: package={} items={}",
                job["public_id"],
                package["id"],
                uploaded_count,
            )
        except DeliveryError as error:
            result = self.resource_store.finish_delivery_job(
                job_id, "failed", error.code, error.summary
            )
        except asyncio.CancelledError:
            self.resource_store.finish_delivery_job(
                job_id,
                "failed",
                "restart_interrupted",
                "Resource delivery was interrupted before completion",
            )
            raise
        except Exception as error:
            logger.exception(
                "Unexpected resource delivery failure for {}", job["public_id"]
            )
            result = self.resource_store.finish_delivery_job(
                job_id,
                "failed",
                "delivery_failed",
                f"Resource delivery failed ({error.__class__.__name__})",
            )
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
        if result is not None:
            await self._notify_user(result)
            return result
        return self.resource_store.get_delivery_job(job_id)

    def _validated_package(self, job: dict) -> dict:
        if self.channel_store is None:
            raise DeliveryError(
                "service_unavailable", "Resource package service is unavailable"
            )
        package = self.channel_store.get_package(int(job["package_id"]))
        if package is None:
            raise DeliveryError("package_not_found", "Resource package was not found")
        if (
            package.get("boundary_status") != "stable"
            or int(package["index_revision"]) != int(job["package_revision"])
        ):
            raise DeliveryError(
                "package_changed", "Resource package changed; search again"
            )
        return package

    async def _require_target_permission(self, job: dict) -> None:
        self._require_local_authorization(job)
        try:
            member = await self.resource_client.get_chat_member(
                int(job["target_chat_id"]), int(self.resource_client.me.id)
            )
        except Exception as error:
            logger.warning(
                "Resource Bot target permission check failed: {}",
                error.__class__.__name__,
            )
            member = None
        can_post = False
        if member is not None:
            if member.status == enums.ChatMemberStatus.OWNER:
                can_post = True
            elif member.status == enums.ChatMemberStatus.ADMINISTRATOR:
                privileges = getattr(member, "privileges", None)
                can_post = bool(
                    privileges and privileges.can_post_messages
                )
        if not can_post:
            self.resource_store.mark_binding_permission_lost(
                int(job["target_chat_id"])
            )
            raise DeliveryError(
                "target_permission_lost",
                "Resource Bot can no longer post to the target channel",
            )

    def _require_local_authorization(self, job: dict) -> None:
        if not self.resource_store.is_user_active(int(job["telegram_user_id"])):
            raise DeliveryError(
                "activation_revoked", "Resource Bot activation was revoked"
            )
        binding = self.resource_store.get_binding(int(job["telegram_user_id"]))
        if (
            binding is None
            or binding["status"] != "active"
            or int(binding["chat_id"]) != int(job["target_chat_id"])
        ):
            raise DeliveryError(
                "target_permission_lost", "Target channel binding is not active"
            )

    def _prepare_items(self, job: dict) -> list[PreparedDeliveryItem]:
        items = self._load_package_items(int(job["package_id"]))
        prepared = []
        for item in sorted(items, key=lambda value: int(value["ordinal"])):
            source_chat_id = item.get("source_chat_id")
            source_message_id = item.get("source_message_id") or item.get(
                "message_id"
            )
            if source_chat_id is None or source_message_id is None:
                raise DeliveryError(
                    "source_message_missing",
                    "Resource package contains an unresolved source message",
                )
            prepared.append(
                PreparedDeliveryItem(
                    ordinal=int(item["ordinal"]),
                    source_chat_id=int(source_chat_id),
                    source_message_id=int(source_message_id),
                    media_type=str(item["media_type"]),
                    media_group_id=(
                        str(item["media_group_id"])
                        if item.get("media_group_id") is not None
                        else None
                    ),
                    caption=item.get("original_caption"),
                    file_name=safe_delivery_filename(item),
                )
            )
        return prepared

    async def _download_all(
        self,
        job: dict,
        items: list[PreparedDeliveryItem],
        job_dir: Path,
    ) -> list[PreparedDeliveryItem]:
        downloaded: list[PreparedDeliveryItem] = []
        async with self.activity_gate.download_permit():
            for item in items:
                self._require_local_authorization(job)
                message = await self._get_source_message(item)
                local_path = job_dir / item.file_name
                try:
                    tracker = self._speed_tracker(
                        int(job["id"]), "download_speed"
                    )
                    downloaded_path = await self._download_message(
                        message, local_path, tracker
                    )
                except DeliveryError:
                    raise
                except Exception as error:
                    logger.warning(
                        "Resource media download failed: job={} message={} type={}",
                        job["public_id"],
                        item.source_message_id,
                        error.__class__.__name__,
                    )
                    raise DeliveryError(
                        "download_failed", "Resource media download failed"
                    ) from error
                downloaded.append(
                    replace(
                        item,
                        local_path=downloaded_path,
                        message=message,
                    )
                )
                self.resource_store.update_job_progress(
                    int(job["id"]),
                    downloaded_items=len(downloaded),
                    download_speed=0,
                )
        return downloaded

    async def _get_source_message(self, item: PreparedDeliveryItem):
        while True:
            try:
                message = await self.main_client.get_messages(
                    item.source_chat_id, item.source_message_id
                )
                if isinstance(message, (list, tuple)):
                    message = message[0] if message else None
                if message is None or getattr(message, "empty", False):
                    raise DeliveryError(
                        "source_message_missing",
                        "A source message is no longer available",
                    )
                return message
            except pyrogram.errors.FloodWait as error:
                await self.sleep(error.value)

    async def _download_message(
        self,
        message,
        local_path: Path,
        tracker: TransferSpeedTracker,
    ) -> Path:
        async def progress(current, total):
            tracker.observe(current, total)

        while True:
            try:
                result = await self.main_client.download_media(
                    message,
                    file_name=str(local_path),
                    progress=progress,
                )
                if not result:
                    raise DeliveryError(
                        "download_failed", "Resource media download returned no file"
                    )
                return Path(result)
            except pyrogram.errors.FloodWait as error:
                await self.sleep(error.value)

    async def _upload_all(
        self, job: dict, items: list[PreparedDeliveryItem]
    ) -> int:
        uploaded = 0
        for group in build_delivery_groups(items):
            self._require_local_authorization(job)
            try:
                await self._upload_group(
                    int(job["target_chat_id"]), group, int(job["id"])
                )
            except pyrogram.errors.FloodWait as error:
                await self.sleep(error.value)
                self._require_local_authorization(job)
                try:
                    await self._upload_group(
                        int(job["target_chat_id"]), group, int(job["id"])
                    )
                except Exception as retry_error:
                    code = "partial_upload" if uploaded else "upload_failed"
                    raise DeliveryError(
                        code,
                        f"Resource upload stopped after {uploaded} items",
                    ) from retry_error
            except Exception as error:
                code = "partial_upload" if uploaded else "upload_failed"
                raise DeliveryError(
                    code,
                    f"Resource upload stopped after {uploaded} items",
                ) from error
            uploaded += len(group)
            self.resource_store.update_job_progress(
                int(job["id"]),
                status="uploading",
                uploaded_items=uploaded,
                upload_speed=0,
            )
        return uploaded

    async def _upload_group(
        self,
        target_chat_id: int,
        group: list[PreparedDeliveryItem],
        job_id: int,
    ) -> None:
        if len(group) > 1:
            streams = []
            try:
                media = []
                for item in group:
                    tracker = self._speed_tracker(job_id, "upload_speed")
                    stream = _TrackedUploadFile(item.local_path, tracker)
                    streams.append(stream)
                    media.append(self._input_media(item, stream))
                await self.resource_client.send_media_group(target_chat_id, media)
            finally:
                for stream in streams:
                    stream.close()
            return
        item = group[0]
        path = str(item.local_path)
        tracker = self._speed_tracker(job_id, "upload_speed")

        async def progress(current, total):
            tracker.observe(current, total)

        if item.media_type == "photo":
            await self.resource_client.send_photo(
                target_chat_id, path, caption=item.caption, progress=progress
            )
        elif item.media_type == "video":
            await self.resource_client.send_video(
                target_chat_id, path, caption=item.caption, progress=progress
            )
        elif item.media_type == "audio":
            await self.resource_client.send_audio(
                target_chat_id, path, caption=item.caption, progress=progress
            )
        elif item.media_type == "document":
            await self.resource_client.send_document(
                target_chat_id, path, caption=item.caption, progress=progress
            )
        elif item.media_type == "voice":
            await self.resource_client.send_voice(
                target_chat_id, path, caption=item.caption, progress=progress
            )
        elif item.media_type == "video_note":
            await self.resource_client.send_video_note(
                target_chat_id, path, progress=progress
            )
        else:
            raise DeliveryError(
                "upload_failed",
                f"Unsupported resource media type: {item.media_type}",
            )

    def _speed_tracker(
        self, job_id: int, speed_field: str
    ) -> TransferSpeedTracker:
        def report(speed: int) -> None:
            self.resource_store.update_job_progress(
                job_id, **{speed_field: speed}
            )

        return TransferSpeedTracker(report, clock=self.clock)

    @staticmethod
    def _input_media(item: PreparedDeliveryItem, media=None):
        source = media if media is not None else str(item.local_path)
        if item.media_type == "photo":
            return types.InputMediaPhoto(source, caption=item.caption)
        if item.media_type == "video":
            return types.InputMediaVideo(source, caption=item.caption)
        if item.media_type == "audio":
            return types.InputMediaAudio(source, caption=item.caption)
        if item.media_type == "document":
            return types.InputMediaDocument(source, caption=item.caption)
        raise DeliveryError(
            "upload_failed",
            f"Unsupported media-group type: {item.media_type}",
        )

    async def _notify_user(self, job: dict) -> None:
        try:
            if job["status"] == "completed":
                text = (
                    f"资源发布完成：{job['uploaded_items']}/"
                    f"{job['total_items']} 项。"
                )
            else:
                text = (
                    f"资源发布失败：{job.get('error_code') or 'delivery_failed'}；"
                    f"已发布 {job['uploaded_items']}/{job['total_items']} 项。"
                )
            await self.resource_client.send_message(
                int(job["telegram_user_id"]), text
            )
        except Exception as error:
            logger.warning(
                "Resource delivery notification failed: {}",
                error.__class__.__name__,
            )

"""Event-loop-owned scheduler for recoverable channel-library scans."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import random
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from pyrogram import errors

from module.channel_library_store import ChannelLibraryConfig, ChannelLibraryStore
from module.channel_library_workflow import ChannelPackageIndexer, extract_media_row
from module.comment_workflow import build_message_package_workflow_request
from module.telegram_activity import get_telegram_activity_gate


LOGGER = logging.getLogger(__name__)
_SERVICE_OWNER_LOCK = threading.Lock()
_SERVICE_OWNERS: dict[str, Any] = {}


@dataclass(frozen=True)
class SubmitLibraryResult:
    """Result of resolving and deduplicating one submitted channel link."""

    library: dict
    created: bool
    job: Optional[dict]


class _TransientBatchFailure(Exception):
    """Internal marker for a Telegram batch that exhausted normal retries."""


def normalize_messages(messages: Any) -> list[Any]:
    """Normalize Pyrogram's singleton/list response without splitting objects."""

    if messages is None:
        return []
    if isinstance(messages, (list, tuple)):
        return list(messages)
    return [messages]


class ChannelLibraryService:
    """Own channel resolution and one global scan scheduler on Application.loop."""

    def __init__(
        self,
        app: Any,
        client: Any,
        store: ChannelLibraryStore,
        config: ChannelLibraryConfig,
        sleep: Callable[[float], Any] = asyncio.sleep,
        random_uniform: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.app = app
        self.client = client
        self.store = store
        self.config = config
        self.sleep = sleep
        self.random_uniform = random_uniform
        self.indexer = ChannelPackageIndexer()
        self.gate = get_telegram_activity_gate()
        self.owner_loop: Optional[asyncio.AbstractEventLoop] = None
        self.scheduler_task: Optional[asyncio.Task[None]] = None
        self._wake_event: Optional[asyncio.Event] = None
        self._stopping = False
        self._telegram_request_active = False
        self._telegram_request_finished: Optional[asyncio.Event] = None
        self._ownership_key: Optional[str] = None
        self._shutdown_task: Optional[asyncio.Task[None]] = None

    async def start(self) -> None:
        """Initialize recovery and start exactly one scheduler task."""

        loop = asyncio.get_running_loop()
        app_loop = getattr(self.app, "loop", loop)
        if app_loop is not loop:
            raise RuntimeError("ChannelLibraryService must start on Application.loop")
        if self.scheduler_task is not None and not self.scheduler_task.done():
            return
        self._acquire_store_ownership()
        try:
            self.owner_loop = loop
            self.store.initialize()
            self.store.recover_interrupted_jobs()
            self._wake_event = asyncio.Event()
            self._telegram_request_finished = asyncio.Event()
            self._telegram_request_finished.set()
            self._stopping = False
            self._shutdown_task = None
            self.scheduler_task = loop.create_task(
                self._run_scheduler(), name="channel-library-scheduler"
            )
        except BaseException:
            self._release_store_ownership()
            raise

    async def stop(self) -> None:
        """Stop the scheduler without cancelling an active Telegram request."""

        cleanup = self._shutdown_task
        if cleanup is None:
            self._stopping = True
            await self.wake()
            cleanup = asyncio.get_running_loop().create_task(
                self._finish_shutdown(), name="channel-library-shutdown"
            )
            self._shutdown_task = cleanup
        await asyncio.shield(cleanup)

    async def _finish_shutdown(self) -> None:
        """Finish scheduler shutdown independently of public stop waiters."""

        task = self.scheduler_task
        try:
            if task is None:
                return
            if not task.done():
                if (
                    self._telegram_request_active
                    and self._telegram_request_finished is not None
                ):
                    await self._telegram_request_finished.wait()
                task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            if task is None or task.done():
                self._release_store_ownership()

    async def wake(self) -> None:
        """Wake the owner-loop scheduler after a persisted command."""

        if self._wake_event is not None:
            self._wake_event.set()

    def _wake_threadsafe(self) -> None:
        if self.owner_loop is None or self._wake_event is None:
            return
        self.owner_loop.call_soon_threadsafe(self._wake_event.set)

    async def _run_scheduler(self) -> None:
        """Claim and execute persisted jobs one at a time."""

        while not self._stopping:
            self.store.recover_interrupted_jobs()
            job = self.store.claim_next_job()
            if job is not None:
                try:
                    await self._run_job(job)
                except asyncio.CancelledError:
                    raise
                except Exception:  # pragma: no cover - last-resort scheduler guard
                    LOGGER.exception("Channel-library scheduler job failed unexpectedly")
                    current = self.store.get_job(job["id"])
                    if current is not None and current["status"] == "running":
                        self.store.transition_job(
                            job["id"], "failed", last_error="internal scheduler error"
                        )
                continue
            await self._wait_for_work()

    async def _wait_for_work(self) -> None:
        if self._wake_event is None:
            return
        self._wake_event.clear()
        deadline = self.store.next_rate_limit_deadline()
        if deadline is None:
            await self._wake_event.wait()
            return
        timeout = max(0.0, deadline - time.time())
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout)
        except asyncio.TimeoutError:
            pass

    async def resolve_and_create_library(self, link: str) -> SubmitLibraryResult:
        """Resolve a Telegram message link and queue a snapshotted full scan."""

        self._require_owner_loop()
        request = build_message_package_workflow_request(str(link or "").strip())
        if request is None:
            raise ValueError("A direct Telegram channel message link is required")
        async with self.gate.download_permit():
            chat = await self.client.get_chat(request.source_chat)
            chat_type = self._chat_type_name(getattr(chat, "type", None))
            if chat_type not in {"channel", "supergroup"}:
                raise ValueError("Telegram link must resolve to a channel or supergroup")
            snapshot_max = 0
            async for message in self.client.get_chat_history(chat.id, limit=1):
                if message is not None and getattr(message, "id", None) is not None:
                    snapshot_max = int(message.id)
                    break

        library, job, created = self.store.create_or_get_library_with_full_job(
            int(chat.id),
            chat_type,
            getattr(chat, "username", None),
            str(getattr(chat, "title", None) or getattr(chat, "username", None) or chat.id),
            request.url,
            snapshot_max,
        )
        if job["status"] == "queued":
            await self.wake()
        return SubmitLibraryResult(library=library, created=created, job=job)

    def submit_library_link_threadsafe(
        self, link: str
    ) -> concurrent.futures.Future[SubmitLibraryResult]:
        """Schedule link resolution from Flask without calling Pyrogram there."""

        if self.owner_loop is None or not self.owner_loop.is_running():
            raise RuntimeError("ChannelLibraryService is not running")
        return asyncio.run_coroutine_threadsafe(
            self.resolve_and_create_library(link), self.owner_loop
        )

    def pause(self, job_id: int) -> dict:
        """Persist a user pause, deferring it when a batch is running."""

        job = self._get_required_job(job_id)
        if job["status"] == "paused_user":
            return job
        if job["status"] == "running":
            result = self.store.request_job_control(job_id, "pause")
        else:
            result = self.store.transition_job(job_id, "paused_user")
        self._wake_threadsafe()
        return result

    def resume(self, job_id: int) -> dict:
        """Resume the same paused or stopped persisted job."""

        job = self._get_required_job(job_id)
        if job["status"] == "queued":
            return job
        result = self.store.transition_job(job_id, "queued")
        self._wake_threadsafe()
        return result

    def stop_job(self, job_id: int) -> dict:
        """Persist a stop, deferring it when a batch is running."""

        job = self._get_required_job(job_id)
        if job["status"] == "stopped":
            return job
        if job["status"] == "running":
            result = self.store.request_job_control(job_id, "stop")
        else:
            result = self.store.transition_job(job_id, "stopped")
        self._wake_threadsafe()
        return result

    async def _run_job(self, job: dict) -> None:
        """Run one full scan from its durable checkpoint to immutable snapshot."""

        current = self._get_required_job(job["id"])
        if current["kind"] != "full":
            raise ValueError("Task 5 only executes full scan jobs")
        if current["status"] == "queued":
            current = self.store.transition_job(current["id"], "running")
        if current["status"] != "running":
            return

        try:
            while int(current["next_message_id"]) <= int(
                current["snapshot_max_message_id"]
            ):
                controlled = self.store.consume_job_control(current["id"])
                if controlled is not None:
                    return
                if await self.gate.has_download_activity():
                    self.store.transition_job(current["id"], "auto_paused_download")
                    await self.gate.wait_until_downloads_idle()
                    paused = self.store.get_job(current["id"])
                    if paused is not None and paused["status"] == "auto_paused_download":
                        self.store.transition_job(current["id"], "queued")
                        await self.wake()
                    return

                batch_ids = list(
                    range(
                        int(current["next_message_id"]),
                        min(
                            int(current["next_message_id"])
                            + self.config.full_scan_batch_size,
                            int(current["snapshot_max_message_id"]) + 1,
                        ),
                    )
                )
                batch_succeeded = True
                try:
                    messages = await self._fetch_batch(
                        int(current["id"]),
                        int(current["library_id"]),
                        batch_ids,
                    )
                    rows = [
                        row
                        for item in normalize_messages(messages)
                        if (row := extract_media_row(item)) is not None
                    ]
                    current = self.store.commit_fetched_batch(
                        current["id"], rows, end_id=batch_ids[-1]
                    )
                    self.indexer.index_through(
                        self.store,
                        self._get_required_job(current["id"]),
                        batch_ids[-1],
                    )
                except errors.FloodWait as error:
                    wait_seconds = float(error.value or 0) + self.random_uniform(1, 3)
                    self.store.transition_job(
                        current["id"],
                        "waiting_rate_limit",
                        wait_until=time.time() + wait_seconds,
                        wait_reason="FloodWait",
                        last_error=str(error),
                    )
                    return
                except self._permanent_errors() as error:
                    self.store.transition_job(
                        current["id"], "failed", last_error=str(error)
                    )
                    return
                except _TransientBatchFailure as error:
                    batch_succeeded = False
                    try:
                        self.store.record_failed_range(
                            current["id"],
                            batch_ids[0],
                            batch_ids[-1],
                            str(error),
                            reindex_anchor_start=1,
                            uncertain_through_message_id=batch_ids[-1],
                        )
                        current = self.store.commit_fetched_batch(
                            current["id"], [], end_id=batch_ids[-1]
                        )
                        self.indexer.index_through(
                            self.store,
                            self._get_required_job(current["id"]),
                            batch_ids[-1],
                        )
                    except Exception as persistence_error:
                        self.store.transition_job(
                            current["id"],
                            "failed",
                            last_error=str(persistence_error),
                        )
                        return
                except sqlite3.Error as error:
                    self.store.transition_job(
                        current["id"], "failed", last_error=str(error)
                    )
                    return
                except Exception as error:
                    self.store.transition_job(
                        current["id"], "failed", last_error=str(error)
                    )
                    return

                current = self._get_required_job(current["id"])
                controlled = self.store.consume_job_control(current["id"])
                if controlled is not None:
                    return
                if self._stopping:
                    self.store.transition_job(current["id"], "queued")
                    return
                if int(current["next_message_id"]) <= int(
                    current["snapshot_max_message_id"]
                ) and batch_succeeded:
                    delay = self.random_uniform(
                        self.config.full_scan_delay_min_sec,
                        self.config.full_scan_delay_max_sec,
                    )
                    await self.sleep(delay)

            current = self._get_required_job(current["id"])
            final_status = (
                "partial"
                if self.store.has_open_failures(current["library_id"])
                else "completed"
            )
            self.store.transition_job(current["id"], final_status)
        except asyncio.CancelledError:
            cancelled_job = self.store.get_job(job["id"])
            if cancelled_job is not None and cancelled_job["status"] == "running":
                controlled = self.store.consume_job_control(cancelled_job["id"])
                if controlled is None:
                    self.store.transition_job(cancelled_job["id"], "queued")
            raise

    async def _fetch_batch(
        self, job_id: int, library_id: int, batch_ids: Sequence[int]
    ) -> Any:
        library = self.store.get_library(library_id)
        if library is None:
            raise KeyError(f"Channel library {library_id} does not exist")
        retry_delays = tuple(self.config.transient_retry_delays_sec)
        job = self._get_required_job(job_id)
        retries_used = int(job["retry_count"])
        while True:
            try:
                async with self.gate.scan_permit():
                    self._mark_request_started()
                    try:
                        return await self.client.get_messages(
                            library["chat_id"], list(batch_ids)
                        )
                    finally:
                        self._mark_request_finished()
            except (errors.FloodWait,) + self._permanent_errors():
                raise
            except self._transient_errors() as error:
                if retries_used >= len(retry_delays):
                    raise _TransientBatchFailure(str(error)) from error
                updated = self.store.record_job_retry(job_id, str(error))
                delay = float(retry_delays[retries_used]) + self.random_uniform(0, 1)
                retries_used = int(updated["retry_count"])
                await self.sleep(delay)

    def _mark_request_started(self) -> None:
        self._telegram_request_active = True
        if self._telegram_request_finished is not None:
            self._telegram_request_finished.clear()

    def _mark_request_finished(self) -> None:
        self._telegram_request_active = False
        if self._telegram_request_finished is not None:
            self._telegram_request_finished.set()

    def _require_owner_loop(self) -> None:
        if self.owner_loop is None:
            raise RuntimeError("ChannelLibraryService is not running")
        if asyncio.get_running_loop() is not self.owner_loop:
            raise RuntimeError("Telegram resolution must run on the service owner loop")

    def _get_required_job(self, job_id: int) -> dict:
        job = self.store.get_job(job_id)
        if job is None:
            raise KeyError(f"Scan job {job_id} does not exist")
        return job

    def _acquire_store_ownership(self) -> None:
        key = str(self.store.path.expanduser().resolve())
        with _SERVICE_OWNER_LOCK:
            owner = _SERVICE_OWNERS.get(key)
            if owner is not None and owner is not self:
                raise RuntimeError(f"Channel library store is already owned: {key}")
            _SERVICE_OWNERS[key] = self
            self._ownership_key = key

    def _release_store_ownership(self) -> None:
        key = self._ownership_key
        if key is None:
            return
        with _SERVICE_OWNER_LOCK:
            if _SERVICE_OWNERS.get(key) is self:
                del _SERVICE_OWNERS[key]
        self._ownership_key = None

    @staticmethod
    def _chat_type_name(value: Any) -> str:
        raw = getattr(value, "value", value)
        return str(raw or "").rsplit(".", 1)[-1].lower()

    @staticmethod
    def _permanent_errors() -> tuple[type[BaseException], ...]:
        return (
            errors.BadRequest,
            errors.Unauthorized,
            errors.Forbidden,
            errors.NotAcceptable,
        )

    @staticmethod
    def _transient_errors() -> tuple[type[BaseException], ...]:
        return (
            errors.RPCError,
            OSError,
            TimeoutError,
            ConnectionError,
        )

"""Event-loop-owned scheduler for recoverable channel-library scans."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import random
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

from pyrogram import errors

from module.channel_library_store import ChannelLibraryConfig, ChannelLibraryStore
from module.channel_library_workflow import ChannelPackageIndexer, extract_media_row
from module.comment_workflow import build_message_package_workflow_request
from module.telegram_activity import get_telegram_activity_gate
from module.task_state import (
    FileStatus,
    TaskIdentityConflictError,
    TaskStatus,
    get_task_store,
)


LOGGER = logging.getLogger(__name__)
_SERVICE_OWNER_LOCK = threading.Lock()
_SERVICE_OWNERS: dict[str, Any] = {}
_DOWNLOAD_BATCH_RUNNER_LOCK = threading.Lock()
_DOWNLOAD_BATCH_RUNNERS: set[tuple[str, int]] = set()


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


def _snapshot_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _package_error_code(status: str) -> Optional[str]:
    if status == "completed":
        return None
    if status in {"upload_failed", "not_found", "cancelled"}:
        return status
    return "download_failed"


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
        task_store: Optional[Any] = None,
    ) -> None:
        self.app = app
        self.client = client
        self.store = store
        self.config = config
        self.sleep = sleep
        self.random_uniform = random_uniform
        self.task_store = task_store or get_task_store()
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
        self._running_download_batch_ids: set[int] = set()
        self._download_batch_tasks: dict[int, asyncio.Task[Any]] = {}
        self._command_lock = threading.Lock()
        self._accepting_commands = False
        self._command_futures: set[concurrent.futures.Future[Any]] = set()

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
            self.dispatch_pending_batches()
            self.reconcile_download_batches()
            self._wake_event = asyncio.Event()
            self._telegram_request_finished = asyncio.Event()
            self._telegram_request_finished.set()
            self._stopping = False
            self._shutdown_task = None
            self.scheduler_task = loop.create_task(
                self._run_scheduler(), name="channel-library-scheduler"
            )
            self.schedule_pending_download_batches()
            with self._command_lock:
                self._accepting_commands = True
        except BaseException:
            with self._command_lock:
                self._accepting_commands = False
            owned_tasks = list(self._download_batch_tasks.values())
            if self.scheduler_task is not None:
                owned_tasks.append(self.scheduler_task)
            for task in owned_tasks:
                if not task.done():
                    task.cancel()
            if owned_tasks:
                await asyncio.gather(*owned_tasks, return_exceptions=True)
            self._download_batch_tasks.clear()
            self._release_store_ownership()
            raise

    async def stop(self) -> None:
        """Stop the scheduler without cancelling an active Telegram request."""

        with self._command_lock:
            self._accepting_commands = False
            command_futures = tuple(self._command_futures)
        cleanup = self._shutdown_task
        if cleanup is None:
            self._stopping = True
            await self.wake()
            cleanup = asyncio.get_running_loop().create_task(
                self._finish_shutdown(command_futures),
                name="channel-library-shutdown",
            )
            self._shutdown_task = cleanup
        await asyncio.shield(cleanup)

    async def _finish_shutdown(
        self, command_futures: Sequence[concurrent.futures.Future[Any]]
    ) -> None:
        """Finish scheduler shutdown independently of public stop waiters."""

        if command_futures:
            await asyncio.gather(
                *(asyncio.wrap_future(future) for future in command_futures),
                return_exceptions=True,
            )
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
            download_tasks = list(self._download_batch_tasks.values())
            for download_task in download_tasks:
                if not download_task.done():
                    download_task.cancel()
            if download_tasks:
                await asyncio.gather(*download_tasks, return_exceptions=True)
            self._download_batch_tasks.clear()
            if task is None or task.done():
                self._release_store_ownership()

    async def wake(self) -> None:
        """Wake the owner-loop scheduler after a persisted command."""

        if self._wake_event is not None:
            self._wake_event.set()

    def create_download_batch(
        self,
        library_id: int,
        idempotency_key: str,
        redownload: bool = False,
    ) -> dict:
        """Commit a channel snapshot before idempotently creating its Web task."""

        batch, _created = self.create_download_batch_result(
            library_id, idempotency_key, redownload=redownload
        )
        return batch

    def create_download_batch_result(
        self,
        library_id: int,
        idempotency_key: str,
        redownload: bool = False,
    ) -> tuple[dict, bool]:
        """Return dispatched batch plus atomic channel-transaction creation state."""

        key = str(idempotency_key or "").strip()
        if not key:
            raise ValueError("Idempotency key is required")
        deterministic_uuid = uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"telegram-media-downloader:channel-library:{library_id}:{key}",
        )
        batch, created = self.store.create_download_batch_result(
            library_id,
            key,
            f"channel-batch-{deterministic_uuid}",
            allow_redownload=redownload,
        )
        return self._dispatch_download_batch_task(batch), created

    def schedule_pending_download_batches(self) -> list[int]:
        """Schedule every resumable dispatched batch once in this process."""

        scheduled = []
        for batch in self.store.list_active_download_batches():
            if self._schedule_download_batch_owned(int(batch["id"])):
                scheduled.append(int(batch["id"]))
        return scheduled

    def schedule_download_batch_threadsafe(
        self, batch_id: int
    ) -> concurrent.futures.Future[bool]:
        """Wake the owner loop to run one persisted download batch."""

        return self._submit_owner_command(
            lambda: self._schedule_download_batch_command(int(batch_id))
        )

    async def _schedule_download_batch_command(self, batch_id: int) -> bool:
        return self._schedule_download_batch_owned(batch_id)

    def _schedule_download_batch_owned(self, batch_id: int) -> bool:
        existing = self._download_batch_tasks.get(batch_id)
        if existing is not None and not existing.done():
            return False
        if self.owner_loop is None:
            raise RuntimeError("ChannelLibraryService is not running")
        task = self.owner_loop.create_task(
            self.run_download_batch(batch_id),
            name=f"channel-library-download-{batch_id}",
        )
        self._download_batch_tasks[batch_id] = task

        def discard(completed: asyncio.Task[Any]) -> None:
            if self._download_batch_tasks.get(batch_id) is completed:
                self._download_batch_tasks.pop(batch_id, None)
            if not completed.cancelled():
                try:
                    completed.exception()
                except Exception:  # pragma: no cover - defensive task callback
                    LOGGER.exception("Channel-library download task failed")

        task.add_done_callback(discard)
        return True

    def dispatch_pending_batches(self) -> list[dict]:
        """Replay committed outbox rows into the persistent Web task store."""

        dispatched = []
        for batch in self.store.list_pending_download_batches():
            try:
                dispatched.append(self._dispatch_download_batch_task(batch))
            except TaskIdentityConflictError:
                continue
        return dispatched

    def _dispatch_download_batch_task(self, batch: dict) -> dict:
        library = self.store.get_library(int(batch["library_id"]))
        if library is None:
            raise KeyError(f"Channel library {batch['library_id']} does not exist")
        total_count = sum(len(package["items"]) for package in batch["packages"])
        try:
            self.task_store.ensure_task(
                batch["task_id"],
                source="web",
                task_type="channel_library",
                chat_id=int(library["chat_id"]),
                title=f"{batch['channel_title']} / {len(batch['packages'])} packages",
                status=TaskStatus.QUEUED,
                total_count=total_count,
            )
        except TaskIdentityConflictError:
            self.store.mark_download_batch_dispatch_error(
                int(batch["id"]), "task_identity_conflict"
            )
            raise
        return self.store.mark_download_batch_dispatched(int(batch["id"]))

    def reconcile_download_batches(self) -> list[dict]:
        """Repair unfinished package summaries from durable Web task evidence."""

        reconciled: list[dict] = []
        for batch in self.store.list_active_download_batches():
            task = self.task_store.get_task(batch["task_id"])
            if task is not None and task.status not in {
                TaskStatus.COMPLETED,
                TaskStatus.COMPLETED_WITH_ERRORS,
                TaskStatus.CANCELLED,
                TaskStatus.FAILED,
            }:
                continue
            for package in batch["packages"]:
                if package["status"] not in {"queued", "downloading"}:
                    continue
                status = "failed"
                error = "download_failed"
                if task is not None and task.status == TaskStatus.CANCELLED:
                    status = "cancelled"
                    error = "cancelled"
                elif task is not None and task.status in {
                    TaskStatus.COMPLETED,
                    TaskStatus.COMPLETED_WITH_ERRORS,
                }:
                    item_files = [
                        task.files.get(str(item["message_id"]))
                        for item in package["items"]
                    ]
                    file_statuses = {
                        item.status for item in item_files if item is not None
                    }
                    if len(item_files) == len(package["items"]) and all(
                        item is not None
                        and item.status in {FileStatus.DOWNLOADED, FileStatus.UPLOADED}
                        for item in item_files
                    ):
                        status = "completed"
                        error = None
                    elif FileStatus.UPLOAD_FAILED in file_statuses:
                        status = "upload_failed"
                        error = "upload_failed"
                    else:
                        error = "download_failed"
                elif task is not None:
                    error = "download_failed"
                self.store.finish_download_batch_package(
                    int(batch["id"]),
                    int(package["package_id"]),
                    status,
                    last_error=error,
                )
            refreshed = self.store.get_download_batch(int(batch["id"]))
            if refreshed is not None:
                reconciled.append(refreshed)
        return reconciled

    async def run_download_batch(self, batch_id: int) -> list[Any]:
        """Claim and run one batch exactly once on this service owner loop."""

        batch_id = int(batch_id)
        runner_key = (str(self.store.path.resolve()), batch_id)
        with _DOWNLOAD_BATCH_RUNNER_LOCK:
            if runner_key in _DOWNLOAD_BATCH_RUNNERS:
                raise RuntimeError(f"Download batch {batch_id} is already running")
            _DOWNLOAD_BATCH_RUNNERS.add(runner_key)
        self._running_download_batch_ids.add(batch_id)
        try:
            self.store.prepare_download_batch_for_run(batch_id)
            return await self._run_download_batch_owned(batch_id)
        except asyncio.CancelledError:
            self._cancel_unfinished_download_batch(batch_id)
            raise
        finally:
            self._running_download_batch_ids.discard(batch_id)
            with _DOWNLOAD_BATCH_RUNNER_LOCK:
                _DOWNLOAD_BATCH_RUNNERS.discard(runner_key)

    def _cancel_unfinished_download_batch(self, batch_id: int) -> None:
        batch = self.store.get_download_batch(batch_id)
        if batch is None:
            return
        for package in batch["packages"]:
            if package["status"] in {"queued", "downloading"}:
                self.store.finish_download_batch_package(
                    batch_id,
                    int(package["package_id"]),
                    "cancelled",
                    last_error="cancelled",
                )
        self.task_store.update_task(
            batch["task_id"], status=TaskStatus.CANCELLED, error="cancelled"
        )

    async def _run_download_batch_owned(self, batch_id: int) -> list[Any]:
        """Refetch and serially download one committed immutable batch snapshot."""

        from media_downloader import PackageCallbackError, download_prescan_packages
        from module.app import TaskNode
        from module.comment_workflow import (
            MessagePackagePlan,
            PackageMediaItem,
            build_size_summary,
            summarize_comments,
        )
        from module.prescan_workflow import PrescanPackage

        batch = self.store.get_download_batch(batch_id)
        if batch is None:
            raise KeyError(f"Download batch {batch_id} does not exist")
        library = self.store.get_library(int(batch["library_id"]))
        if library is None:
            raise KeyError(f"Channel library {batch['library_id']} does not exist")
        packages = []
        attempt_packages = {}
        attempt_errors = {}
        for package_snapshot in batch["packages"]:
            if package_snapshot["status"] not in {"queued", "downloading"}:
                continue
            message_ids = [
                int(item["message_id"]) for item in package_snapshot["items"]
            ]
            fetch_error = None
            try:
                async with self.gate.download_permit():
                    raw_messages = await self.client.get_messages(
                        int(library["chat_id"]), message_ids
                    )
            except Exception as error:
                raw_messages = []
                fetch_error = "telegram_refetch_failed"
                LOGGER.exception(
                    "Telegram refetch failed for channel package %s",
                    package_snapshot["package_id"],
                )
            found_by_id = {
                int(message.id): message
                for message in normalize_messages(raw_messages)
                if message is not None and getattr(message, "id", None) is not None
            }
            media_items = []
            failed_message_ids = []
            for item_snapshot in package_snapshot["items"]:
                message_id = int(item_snapshot["message_id"])
                message = found_by_id.get(message_id)
                if message is None or getattr(message, "empty", False):
                    failed_message_ids.append(message_id)
                    continue
                media_items.append(
                    PackageMediaItem(
                        message=message,
                        media_type=item_snapshot["media_type"],
                        caption_for_naming=item_snapshot["caption_for_naming"],
                        original_caption=item_snapshot["original_caption"],
                        inherited_caption=_snapshot_bool(
                            item_snapshot["inherited_caption"]
                        ),
                    )
                )
            messages = [item.message for item in media_items]
            package_plan = MessagePackagePlan(
                items=media_items,
                package_title=package_snapshot["title"],
                summary=summarize_comments(messages),
                size_summary=build_size_summary(messages),
            )
            package = PrescanPackage(
                package_id=int(package_snapshot["package_id"]),
                title=package_snapshot["title"],
                start_message_id=int(package_snapshot["start_message_id"]),
                end_message_id=int(package_snapshot["end_message_id"]),
                items=media_items,
                package_plan=package_plan,
                messages=messages,
                failed_message_ids=failed_message_ids,
                expected_message_ids=message_ids,
            )
            package.package_revision = int(package_snapshot["package_revision"])
            package.attempt_id = f"{batch_id}:{package.package_id}"
            package.not_found_message_ids = (
                set(failed_message_ids) if fetch_error is None else set()
            )
            package.fetch_error = fetch_error
            packages.append(package)
            attempt_packages[package.attempt_id] = package.package_id
            attempt_errors[package.attempt_id] = fetch_error

        node = TaskNode(
            chat_id=int(library["chat_id"]),
            bot=None,
            task_id=batch["task_id"],
        )
        node.client = self.client
        node.preserve_task_identity = True

        async def on_package_started(attempt_id: Any, _package: Any) -> None:
            self.store.mark_download_batch_package_started(
                batch_id, attempt_packages[attempt_id]
            )

        async def on_package_finished(
            attempt_id: Any, message_results: dict[int, Any]
        ) -> None:
            statuses = {result.status for result in message_results.values()}
            if statuses and statuses <= {"completed", "completed_file_skip"}:
                status = "completed"
            elif "upload_failed" in statuses:
                status = "upload_failed"
            elif "not_found" in statuses:
                status = "not_found"
            elif "failed" in statuses:
                status = "failed"
            elif "cancelled" in statuses:
                status = "cancelled"
            else:
                status = "failed"
            self.store.finish_download_batch_package(
                batch_id,
                attempt_packages[attempt_id],
                status,
                last_error=(
                    "telegram_refetch_failed"
                    if attempt_errors[attempt_id]
                    else _package_error_code(status)
                ),
            )

        try:
            results = await download_prescan_packages(
                packages,
                channel=batch["channel_title"],
                parent_node=node,
                selected_package_ids={package.package_id for package in packages},
                on_package_started=on_package_started,
                on_package_finished=on_package_finished,
            )
        except Exception as error:
            error_code = (
                "callback_failed"
                if isinstance(error, PackageCallbackError)
                else "download_failed"
            )
            LOGGER.exception("Channel package batch download failed")
            for package in self.store.get_download_batch(batch_id)["packages"]:
                if package["status"] in {"queued", "downloading"}:
                    self.store.finish_download_batch_package(
                        batch_id,
                        int(package["package_id"]),
                        "failed",
                        last_error=error_code,
                    )
            self.task_store.update_task(
                batch["task_id"], status=TaskStatus.FAILED, error=error_code
            )
            raise
        completed_package_ids = {result.package_id for result in results}
        remaining_status = "cancelled" if node.is_stop_transmission else "failed"
        for package in packages:
            if package.package_id in completed_package_ids:
                continue
            self.store.finish_download_batch_package(
                batch_id,
                package.package_id,
                remaining_status,
                last_error=(
                    "cancelled" if remaining_status == "cancelled" else "download_failed"
                ),
            )
        if node.is_stop_transmission:
            self.task_store.update_task(
                batch["task_id"], status=TaskStatus.CANCELLED, error="cancelled"
            )
        return results

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

    async def queue_incremental(self, library_id: int) -> dict:
        """Snapshot and queue the new tail of a finished channel library."""

        self._require_owner_loop()
        library = self.store.get_library(library_id)
        if library is None:
            raise KeyError(f"Channel library {library_id} does not exist")
        if not self.store.has_finished_full_scan(library_id):
            raise ValueError("Incremental scan requires a finished full scan")

        snapshot_max = 0
        async with self.gate.scan_permit():
            async for message in self.client.get_chat_history(
                library["chat_id"], limit=1
            ):
                if message is not None and getattr(message, "id", None) is not None:
                    snapshot_max = int(message.id)
                    break
        start_message_id = int(library["fetched_through_message_id"]) + 1
        snapshot_max = max(snapshot_max, start_message_id - 1)
        job = self.store.create_scan_job(
            library_id,
            "incremental",
            start_message_id,
            snapshot_max,
        )
        await self.wake()
        return job

    def queue_repair(
        self, library_id: int, failure_ids: Optional[Sequence[int]] = None
    ) -> dict:
        """Queue all or selected unresolved ranges for one partial library."""

        job = self.store.create_repair_job(library_id, failure_ids)
        self._wake_threadsafe()
        return job

    def retry_failed_job(self, library_id: int, failed_job_id: int) -> dict:
        """Create a new same-kind job from a failed job's durable checkpoint."""

        failed = self._get_required_job(failed_job_id)
        if failed["library_id"] != library_id:
            raise ValueError("Failed scan does not belong to the requested library")
        if failed["status"] != "failed":
            raise ValueError("Only failed scans can be retried")
        if failed["kind"] == "repair":
            retried = self.store.retry_failed_repair_job(failed_job_id)
        else:
            retried = self.store.create_scan_job(
                library_id,
                failed["kind"],
                int(failed["start_message_id"]),
                int(failed["snapshot_max_message_id"]),
            )
        self._wake_threadsafe()
        return retried

    def submit_library_link_threadsafe(
        self, link: str
    ) -> concurrent.futures.Future[SubmitLibraryResult]:
        """Schedule link resolution from Flask without calling Pyrogram there."""

        return self._submit_owner_command(
            lambda: self.resolve_and_create_library(link)
        )

    def submit_incremental_threadsafe(
        self, library_id: int
    ) -> concurrent.futures.Future[dict]:
        """Schedule an incremental snapshot on the service owner loop."""

        return self._submit_owner_command(
            lambda: self.queue_incremental(library_id)
        )

    def _submit_owner_command(
        self, coroutine_factory: Callable[[], Any]
    ) -> concurrent.futures.Future[Any]:
        """Atomically accept and track one owner-loop command through completion."""

        with self._command_lock:
            if not self._accepting_commands:
                raise RuntimeError("ChannelLibraryService is not accepting commands")
            loop = self.owner_loop
            if loop is None or not loop.is_running():
                raise RuntimeError("ChannelLibraryService is not running")
            coroutine = coroutine_factory()
            try:
                future = asyncio.run_coroutine_threadsafe(coroutine, loop)
            except BaseException:
                coroutine.close()
                raise
            self._command_futures.add(future)
        future.add_done_callback(self._discard_command_future)
        return future

    def _discard_command_future(
        self, future: concurrent.futures.Future[Any]
    ) -> None:
        with self._command_lock:
            self._command_futures.discard(future)

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
        """Dispatch full, incremental, and repair work through one range runner."""

        current = self._get_required_job(job["id"])
        if current["status"] == "queued":
            current = self.store.transition_job(current["id"], "running")
        if current["status"] != "running":
            return

        try:
            if current["kind"] == "repair":
                for target in self.store.list_repair_targets(current["id"]):
                    if target["status"] == "completed":
                        continue
                    repair_job = dict(current)
                    repair_job["repair_failure_id"] = int(target["failure_id"])
                    finished = await self._scan_range(
                        repair_job,
                        int(target["next_message_id"]),
                        int(target["end_message_id"]),
                        self._incremental_delay_range(),
                    )
                    if not finished:
                        return
                    await self._index_until_published(
                        self._get_required_job(current["id"]),
                        int(target["uncertain_through_message_id"]),
                        resolve_failure_id=int(target["failure_id"]),
                        repair_failure_id=int(target["failure_id"]),
                    )
                    current = self._get_required_job(current["id"])
            else:
                if int(current["indexed_through_message_id"]) < int(
                    current["fetched_through_message_id"]
                ):
                    await self._index_until_published(
                        current, int(current["fetched_through_message_id"])
                    )
                    current = self._get_required_job(current["id"])
                delay_range = (
                    self._full_delay_range()
                    if current["kind"] == "full"
                    else self._incremental_delay_range()
                )
                finished = await self._scan_range(
                    current,
                    int(current["next_message_id"]),
                    int(current["snapshot_max_message_id"]),
                    delay_range,
                )
                if not finished:
                    return

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
        except Exception as error:
            failed_job = self.store.get_job(job["id"])
            if failed_job is not None and failed_job["status"] == "running":
                self.store.transition_job(
                    failed_job["id"], "failed", last_error=str(error)
                )

    async def _scan_range(
        self,
        job: dict,
        start_id: int,
        end_id: int,
        delay_range: tuple[float, float],
    ) -> bool:
        """Run one durable ID range with shared gate, retry, and control behavior."""

        next_id = start_id
        while next_id <= end_id:
            current = self._get_required_job(job["id"])
            if current["status"] != "running":
                return False
            controlled = self.store.consume_job_control(current["id"])
            if controlled is not None:
                return False
            if await self.gate.has_download_activity():
                self.store.transition_job(current["id"], "auto_paused_download")
                await self.gate.wait_until_downloads_idle()
                paused = self.store.get_job(current["id"])
                if paused is not None and paused["status"] == "auto_paused_download":
                    self.store.transition_job(current["id"], "queued")
                    await self.wake()
                return False

            batch_ids = list(
                range(next_id, min(next_id + self._batch_size(current), end_id + 1))
            )
            batch_succeeded = True
            batch_job = dict(current)
            if job.get("repair_failure_id") is not None:
                batch_job["repair_failure_id"] = int(job["repair_failure_id"])
            try:
                await self._fetch_commit_and_index(batch_job, batch_ids)
            except errors.FloodWait as error:
                wait_seconds = float(error.value or 0) + self.random_uniform(1, 3)
                self.store.transition_job(
                    current["id"],
                    "waiting_rate_limit",
                    wait_until=time.time() + wait_seconds,
                    wait_reason="FloodWait",
                    last_error=str(error),
                )
                return False
            except self._permanent_errors() as error:
                self.store.transition_job(current["id"], "failed", last_error=str(error))
                return False
            except _TransientBatchFailure as error:
                if current["kind"] == "repair":
                    self.store.transition_job(
                        current["id"], "failed", last_error=str(error)
                    )
                    return False
                batch_succeeded = False
                try:
                    anchor = self.store.reindex_anchor_for_message(
                        int(current["library_id"]), batch_ids[0]
                    )
                    self.store.record_failed_range(
                        current["id"],
                        batch_ids[0],
                        batch_ids[-1],
                        str(error),
                        reindex_anchor_start=anchor,
                        uncertain_through_message_id=batch_ids[-1],
                    )
                    self.store.commit_fetched_batch(
                        current["id"], [], end_id=batch_ids[-1]
                    )
                    await self._index_until_published(
                        self._get_required_job(current["id"]), batch_ids[-1]
                    )
                except Exception as persistence_error:
                    self.store.transition_job(
                        current["id"], "failed", last_error=str(persistence_error)
                    )
                    return False
            except Exception as error:
                self.store.transition_job(current["id"], "failed", last_error=str(error))
                return False

            next_id = batch_ids[-1] + 1
            current = self._get_required_job(current["id"])
            controlled = self.store.consume_job_control(current["id"])
            if controlled is not None:
                return False
            if self._stopping:
                self.store.transition_job(current["id"], "queued")
                return False
            if next_id <= end_id and batch_succeeded:
                await self.sleep(self.random_uniform(*delay_range))
        return True

    async def _fetch_commit_and_index(
        self, job: dict, batch_ids: Sequence[int]
    ) -> None:
        messages = await self._fetch_batch(
            int(job["id"]), int(job["library_id"]), batch_ids
        )
        rows = [
            row
            for item in normalize_messages(messages)
            if (row := extract_media_row(item)) is not None
        ]
        self.store.commit_fetched_batch(
            job["id"],
            rows,
            end_id=batch_ids[-1],
            repair_failure_id=job.get("repair_failure_id"),
        )
        await self._index_until_published(
            self._get_required_job(job["id"]),
            batch_ids[-1],
            repair_failure_id=job.get("repair_failure_id"),
        )

    async def _index_until_published(
        self,
        job: dict,
        through_message_id: int,
        resolve_failure_id: Optional[int] = None,
        repair_failure_id: Optional[int] = None,
    ) -> None:
        while True:
            result = self.indexer.index_through(
                self.store,
                self._get_required_job(job["id"]),
                through_message_id,
                resolve_failure_id=resolve_failure_id,
                repair_failure_id=repair_failure_id,
            )
            if not result.publication_deferred:
                return
            await self.gate.wait_until_downloads_idle()

    def _batch_size(self, job: dict) -> int:
        if job["kind"] == "full":
            return int(self.config.full_scan_batch_size)
        return int(self.config.incremental_scan_batch_size)

    def _full_delay_range(self) -> tuple[float, float]:
        return (
            float(self.config.full_scan_delay_min_sec),
            float(self.config.full_scan_delay_max_sec),
        )

    def _incremental_delay_range(self) -> tuple[float, float]:
        return (
            float(self.config.incremental_scan_delay_min_sec),
            float(self.config.incremental_scan_delay_max_sec),
        )

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

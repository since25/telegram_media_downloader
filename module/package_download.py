"""Resource-package execution and package-scoped result calculation."""

from typing import AbstractSet, Any, Awaitable, Callable, Optional, Sequence

from module.download_models import (
    PackageCallbackError,
    PackageDownloadResult,
    PackageFinishedCallback,
    PackageMessageResult,
    PackageStartedCallback,
    PreparePackageCallback,
)
from module.task_state import FileStatus, get_task_store


async def maybe_await(value: Any) -> Any:
    """Await callback results only when the callback is asynchronous."""

    if hasattr(value, "__await__"):
        return await value
    return value


async def run_package_callback(callback, *args: Any, logger) -> None:
    """Run a package lifecycle callback without exposing raw errors to callers."""

    try:
        await maybe_await(callback(*args))
    except Exception as error:
        logger.exception("Package lifecycle callback failed")
        raise PackageCallbackError() from error


def build_package_result(package: Any, parent_node) -> PackageDownloadResult:
    """Build a package result only from its immutable file snapshot."""

    snapshot_ids = getattr(package, "expected_message_ids", None)
    if snapshot_ids:
        expected_ids = tuple(dict.fromkeys(int(value) for value in snapshot_ids))
    else:
        expected_ids = tuple(
            dict.fromkeys(
                [
                    int(item.message.id)
                    for item in package.items
                    if getattr(getattr(item, "message", None), "id", None) is not None
                ]
                + [int(message_id) for message_id in package.failed_message_ids]
            )
        )

    task = get_task_store().get_task(parent_node.task_id)
    files = task.files if task is not None else {}
    not_found_ids = set(
        getattr(parent_node, "skip_not_found_message_ids", set()) or set()
    ) | set(getattr(package, "not_found_message_ids", set()) or set())
    completed_skip_ids = set(
        getattr(parent_node, "completed_file_skip_message_ids", set()) or set()
    )
    message_results: dict[int, PackageMessageResult] = {}

    for message_id in expected_ids:
        file_snapshot = files.get(str(message_id))
        if message_id in not_found_ids:
            status = "not_found"
        elif message_id in completed_skip_ids:
            status = "completed_file_skip"
        elif (
            file_snapshot is not None
            and file_snapshot.status == FileStatus.UPLOAD_FAILED
        ):
            status = "upload_failed"
        elif file_snapshot is not None and file_snapshot.status == FileStatus.FAILED:
            status = "failed"
        elif file_snapshot is not None and file_snapshot.status in {
            FileStatus.DOWNLOADED,
            FileStatus.UPLOADED,
        }:
            status = "completed"
        elif parent_node.is_stop_transmission:
            status = "cancelled"
        else:
            status = "failed"
        message_results[message_id] = PackageMessageResult(
            message_id=message_id,
            status=status,
            error=(file_snapshot.error if file_snapshot is not None else ""),
        )

    statuses = {result.status for result in message_results.values()}
    completed_statuses = {"completed", "completed_file_skip"}
    if statuses and statuses <= completed_statuses:
        package_status = "completed"
    elif "upload_failed" in statuses:
        package_status = "upload_failed"
    elif statuses & completed_statuses:
        package_status = "completed_with_errors"
    elif "not_found" in statuses:
        package_status = "not_found"
    elif "failed" in statuses:
        package_status = "failed"
    elif "cancelled" in statuses or parent_node.is_stop_transmission:
        package_status = "cancelled"
    else:
        package_status = "failed"

    return PackageDownloadResult(
        attempt_id=getattr(package, "attempt_id", package.package_id),
        package_id=int(package.package_id),
        status=package_status,
        expected_message_ids=expected_ids,
        message_results=message_results,
    )


async def run_packages(
    packages: Sequence[Any],
    channel: str,
    parent_node,
    selected_package_ids: AbstractSet[int],
    download_prepared_messages: Callable[..., Awaitable[Any]],
    logger,
    on_package_started: Optional[PackageStartedCallback] = None,
    on_package_finished: Optional[PackageFinishedCallback] = None,
    manage_parent_lifecycle: bool = True,
    prepare_package: Optional[PreparePackageCallback] = None,
) -> list[PackageDownloadResult]:
    """Run selected resource packages serially in their snapshot order."""

    from module.comment_workflow import NamingStrategy, PackageNamingContext
    from module.download_stat import (
        add_active_task_node,
        get_active_task_nodes,
        remove_active_task_node,
    )
    from module.pyrogram_extension import report_bot_status

    selected_ids = set(selected_package_ids)
    ordered_packages = [
        package
        for package in sorted(packages, key=lambda item: item.start_message_id)
        if package.package_id in selected_ids
    ]
    parent_node.prescan_batch_in_progress = True
    if not isinstance(getattr(parent_node, "skip_not_found_message_ids", None), set):
        parent_node.skip_not_found_message_ids = set()
    if not isinstance(
        getattr(parent_node, "completed_file_skip_message_ids", None), set
    ):
        parent_node.completed_file_skip_message_ids = set()

    results: list[PackageDownloadResult] = []
    try:
        if not parent_node.is_stop_transmission:
            parent_node.is_running = True
        if (
            manage_parent_lifecycle
            and parent_node.task_id not in get_active_task_nodes()
        ):
            add_active_task_node(parent_node)

        for index, descriptor in enumerate(ordered_packages, start=1):
            if not parent_node.is_running or parent_node.is_stop_transmission:
                logger.info(
                    f"Prescan parent task stopped before package {descriptor.package_id}"
                )
                break

            package = (
                descriptor
                if prepare_package is None
                else await prepare_package(descriptor)
            )
            parent_node.package_naming_context = PackageNamingContext(
                strategy=NamingStrategy.RECOMMENDED,
                channel=channel,
                start_message_id=package.start_message_id,
                package_title=package.title,
            )
            parent_node.package_plan = package.package_plan
            parent_node.package_media_items = {
                item.message.id: item for item in package.items
            }
            parent_node.replay_message = (
                f"批量下载中：包 {index}/{len(ordered_packages)} "
                f"{package.start_message_id}-{package.end_message_id} {package.title}"
            )
            attempt_id = getattr(package, "attempt_id", package.package_id)
            if on_package_started is not None:
                await run_package_callback(
                    on_package_started, attempt_id, package, logger=logger
                )
            await download_prepared_messages(
                package.messages,
                None,
                parent_node,
                failed_message_ids=list(package.failed_message_ids),
            )
            result = build_package_result(package, parent_node)
            results.append(result)
            if on_package_finished is not None:
                await run_package_callback(
                    on_package_finished,
                    attempt_id,
                    result.message_results,
                    logger=logger,
                )
    finally:
        parent_node.prescan_batch_in_progress = False
        await report_bot_status(parent_node.bot, parent_node, immediate_reply=True)
        if manage_parent_lifecycle and parent_node.task_id in get_active_task_nodes():
            remove_active_task_node(parent_node.task_id)
    return results

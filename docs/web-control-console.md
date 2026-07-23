# Web Control Console

The Web console shows downloader tasks from the same in-process task store used by bot and downloader workflows.

## Task Submission

After logging in, the Tasks tab can submit Telegram links directly:

- ordinary private message/package links, for example `https://t.me/c/1298283297/126711`
- comment links, for example `https://t.me/channel/422?comment=4978`
- prescan mode for selecting multiple packages after a bounded scan

Submitted links are scheduled on the running downloader event loop. The Web process must be started by `media_downloader.py` so the Web layer has access to the active Pyrogram client; calling the Flask app without the downloader client returns `503`.

Web-submitted package/comment tasks first scan into a preview state. The task row shows the detected type, title, media count, scan count, and preview file rows where available. The downloader does not enqueue media until the user clicks `Start`; clicking `Cancel` marks the waiting task cancelled.

Confirmed tasks use the existing scan and download pipeline and the recommended naming strategy. Task rows move through scan, confirmation, queue, download, upload, and completion states on `/api/task-dashboard`.

Prescan mode scans a bounded message window, writes package summaries to the Web state, and waits for the user to include packages before `Start`. Selected packages are downloaded serially through the existing prescan download path. The scan window is configurable per submission via `max_messages` (default 2000, capped at 10000).

Confirming a prescan keeps its package list in Web state instead of discarding it, so `GET /api/prescans/<task_id>/packages` keeps returning `200` (with each package's `selected` flag as of confirmation time) while the download is in progress, which is what backs the prescan download detail view. Cancelling a prescan, or clearing/clear-completing its task once it reaches a terminal state, drops the retained package list so it does not linger in memory.

## Resources And Channel Indexes

The Resources tab is the primary package interface. It searches, filters, selects, and
downloads packages across all indexed channels. Each package retains its `library_id`,
channel title, and Telegram `chat_id`; channels are optional multi-select filters rather
than the parent navigation required to reach a package.

Open the Channels tab to submit any accessible message link from a channel or supergroup.
The link identifies the conversation; the initial scan snapshots the latest visible
message ID and indexes the complete visible ID range. Submitting another link for the
same Telegram `chat_id` opens the existing library and its persisted checkpoint. Package
search and download controls live only in Resources; the selected channel workspace
shows stable/available, downloaded, pending, media, known-size, and failure counts plus
the stable-package distribution for enabled keyword monitor groups and match terms.

The initial full scan requests 50 consecutive message IDs per batch and waits a randomized 4-6 seconds between successful batches. Work is charged by the snapshotted ID range, not by visible-message count; deleted or unavailable gaps do not reduce the number of batches. A 15,000-ID range is exactly 300 batches and 299 inter-batch delays, so delay alone is theoretically 19 minutes 56 seconds to 29 minutes 54 seconds (about 20-30 minutes). This is not a completion promise: Telegram API latency, FloodWait, transient retries, automatic download priority, and user pause all extend elapsed time. Incremental and repair scans also use 50-ID batches with 1-2 second delays. These are validated server settings loaded from `config.yaml`; changing them requires a restart.

The scheduler runs one channel scan at a time. A queued or active Telegram media download takes priority: the current scan finishes its API call, moves to `auto_paused_download` at the batch boundary, and returns to the queue when Telegram download activity is idle. Upload-only work does not hold the Telegram activity gate. User pause and stop also take effect at a committed batch boundary, preserving metadata and the next-message checkpoint.

`channel_library.incremental_scan_cron` is one optional global five-field cron expression
for all libraries; empty disables it. `channel_library.incremental_scan_timezone`
defaults to `Asia/Shanghai`. At each tick the owner-loop cron task checks libraries in
ID order. A library is skipped when it has any queued, running, paused, rate-limited, or
stopped recoverable scan, including its initial/manual full scan. A latest-message check
that finds no new ID creates no job. Missed or skipped ticks are not accumulated. New
tails are persisted into the same FIFO scan scheduler as manual work, so the cron task
never starts a parallel Telegram scanner.

Scan states shown by the page are:

- `queued`, `running`, and `waiting_rate_limit`: waiting, scanning, or honoring a persisted Telegram deadline
- `auto_paused_download` and `paused_user`: download-priority pause or explicit user pause
- `stopped`: checkpoint retained until the same job is resumed
- `completed` / library `ready`: the snapshot and package index are complete
- `partial`: the snapshot endpoint was reached with one or more recorded failure ranges
- `failed`: the scan stopped on a permission, database, or indexing failure and can be retried after the cause is fixed

Stable packages are selectable. `provisional` is the current unproven tail, `uncertain` intersects a failed boundary closure, and `superseded` is retained history after a split or merge; these are not selectable. Package download summaries use `never`, `queued`, `downloading`, `completed`, `outdated`, `failed`, and `cancelled`.

Aggregate filters cover source channels, normalized title substring, UTC publication
range, inclusive media-count and known-size bounds, unknown-size inclusion, and download
status. Package and item lists use keyset cursors. “Select all filtered” is evaluated by
the server across every matching page and channel. One aggregate download submission is
split into one existing channel batch per source channel so Telegram refetch identity and
package naming remain stable.

A `partial` library remains browseable. Stable packages outside uncertain closures can be selected and downloaded; use Repair for all open failure ranges or selected failure IDs. A successful repair rebuilds the complete affected closure before publishing stable packages. After the first full scan finishes, Incremental snapshots and scans only the new ID tail.

Duplicate protection applies at three levels: channel links deduplicate by Telegram `chat_id`, selections bind to a package revision, and every download submission requires an `Idempotency-Key`. A package with any successful attempt, or a changed package marked `outdated`, requires explicit `redownload=true`. A later failed redownload does not erase the successful-download history.

## Keyword Monitor Groups

Keyword rules are stored in the channel-library database and managed only from the
Keyword Monitor tab. They are not loaded from `config.yaml`. A group contains a name,
enabled state, required keywords, match keywords, and blacklist keywords:

- every required keyword must occur in the normalized package title;
- at least one match keyword must occur;
- any blacklist keyword excludes the package.

Saving an enabled group immediately evaluates the current aggregate index. Full,
incremental, and repair scan completion evaluates all enabled groups again. Matching uses
Unicode NFKC plus case folding. Only stable `never` packages without historical success
are automatic candidates; successful, active, and `outdated` packages are not repeated.

Candidates are merged by package and revision before batch creation. One package matching
multiple groups creates one exact-package batch in chronological FIFO order, while each
group receives a separate history row containing its actual matched keyword subset,
channel, package revision, batch, task, and live download status.

## Channel Library API

The channel library uses the existing Web login session. Call `GET /api/csrf-token` after login and send its `csrf_token` value in `X-CSRF-Token` on every mutating channel-library request. The token is bound to that browser session. Only this authenticated GET mints a token; missing, wrong, and cross-session mutation attempts return `403` without creating or rotating session state. Read and write channel routes return `503 service_unavailable` until Telegram has started and the single channel-library service is running.

Errors use one JSON envelope: `{"error_code": "<stable_code>", "message": "<safe summary>"}`. Supported status classes are `400 invalid_request` or `invalid_link`, `403 csrf_failed`, `404 not_found`, `409 state_conflict` or `redownload_required`, and `503 service_unavailable` or `service_timeout`. Raw exceptions, Telegram session details, tokens, and configuration secrets are not returned.

Channel and scan routes:

- `GET /api/channel-libraries?cursor=&page_size=50`: keyset page with latest scan/count summary.
- `POST /api/channel-libraries`: `{"link": "https://t.me/..."}`; returns `202` when created and `200` for the existing library.
- `GET /api/channel-libraries/<library_id>`: library, opaque `library_version`, latest scan, package/download/size counts, enabled monitor keyword distribution, and safe failure summaries.
- `DELETE /api/channel-libraries/<library_id>`: `{"confirm_library_id": <id>, "library_version": "<version>"}`; atomically rejects version changes, active scans, and queued/downloading child attempts even if a parent batch summary is terminal.
- `POST /api/channel-libraries/<library_id>/scans`: `{"mode": "incremental"}`, `{"mode": "repair", "failure_ids": [<id>]}`, or `{"mode": "retry", "failed_job_id": <id>}`; returns `202`.
- `POST /api/channel-scans/<job_id>/pause`, `/resume`, or `/stop`: persists control at the next safe scan boundary.

Aggregate package, selection, and download routes:

- `GET /api/packages`: cross-channel package search; accepts repeated or comma-separated
  `library_ids` plus package filters, `cursor`, and `page_size`.
- `GET /api/packages/<package_id>/items`: keyset-paginated media metadata.
- `PUT /api/packages/<package_id>/selection`: `{"selected": true|false}`.
- `POST /api/packages/selection/select-filtered`: package filters plus optional
  `library_ids`.
- `POST /api/packages/selection/clear` and `GET /api/packages/selection`: clear or
  summarize aggregate selection.
- `POST /api/packages/download-batches`: optional `{"redownload": true|false}` plus
  required `Idempotency-Key`; returns one batch summary per selected source channel.

Keyword monitor routes:

- `GET|POST /api/keyword-monitor-groups`.
- `GET|PUT|DELETE /api/keyword-monitor-groups/<group_id>`.
- `GET /api/keyword-monitor-groups/<group_id>/history`.

Legacy channel-scoped package routes remain available for compatibility:

- `GET /api/channel-libraries/<library_id>/packages`: accepts `q`, UTC `date_from`/`date_to`, message/media/size min/max bounds, `include_unknown_size=true|false`, `download_status`, `cursor`, and `page_size` (1-200). Returns `next_cursor` and `library_revision` unchanged from the store.
- `GET /api/channel-libraries/<library_id>/packages/<package_id>/items`: keyset-paginated media metadata; respects `hide_file_name`.
- `PUT /api/channel-libraries/<library_id>/selection/packages/<package_id>`: `{"selected": true|false}`.
- `POST /api/channel-libraries/<library_id>/selection/select-filtered`: a JSON object containing the same package filters.
- `POST /api/channel-libraries/<library_id>/selection/clear` and `GET /api/channel-libraries/<library_id>/selection`: clear or summarize the persistent cross-page selection.
- `POST /api/channel-libraries/<library_id>/download-batches`: optional `{"redownload": true|false}` plus required `Idempotency-Key`. Creation/replay is decided in one SQLite write transaction: the true creator returns `202`, concurrent or later replay returns the same batch with `200`, and replay repairs a still-pending dispatch before returning.

Every route rejects undocumented query keys, JSON fields, and request bodies with `400 invalid_request`; pause/resume/stop and selection-clear accept either no body or an empty JSON object only. Flask performs synchronous validation, store reads, and persisted store commands only. Telegram link resolution, incremental snapshots, scan scheduling, and package downloads are submitted to the existing `Application.loop`; Flask never starts or awaits a second event loop. Link resolution waits at most 30 seconds, and a timeout returns `503` without cancelling persisted or in-flight owner-loop work. The service closes command admission before shutdown, drains every already-accepted owner-loop command, then stops scheduler/download tasks. The application clears its service reference before that drain so new Web requests immediately receive `503`; Telegram client stop occurs only afterward.

## Channel Library Operations

`channel_library.sqlite3` is created in the runtime directory with SQLite WAL, foreign keys, and file mode `0600`; startup tightens an existing file if its permissions are wider. It contains channel metadata, checkpoints, package revisions, selections, failure ranges, and immutable download-batch snapshots. `web_tasks.sqlite3` separately contains the dispatched Web task and file evidence. Telegram session files, credentials, downloaded media, and configuration secrets do not belong in either database.

Before an upgrade or rollback that could affect these stores:

1. Stop the service so no scan, dispatch, or task update is in flight.
2. Create consistent backups of both SQLite databases with the SQLite backup API or `sqlite3 <db> ".backup '<backup>'"`. Do not copy only the main database file while WAL is active.
3. Verify each backup opens and returns `ok` from `PRAGMA integrity_check`; back up `config.yaml` and the Telegram session separately with restricted permissions.
4. Upgrade and restart, then verify service status, Web login, the channel list/detail APIs, one scheduler instance, and existing task APIs. Do not submit an uncontrolled channel merely as a smoke test.

For code rollback, revert the relevant commit and restart the service. Preserve `channel_library.sqlite3` and `web_tasks.sqlite3`; code rollback must not delete indexed channels, checkpoints, selections, or task history. Restore a database backup only for confirmed data corruption or an incompatible schema rollback, with the service stopped and the current database retained as an additional rollback point.

## Resource Boundaries

The Web console persists task and file snapshots to `web_tasks.sqlite3` using SQLite WAL mode. The channel library persists its index in the separate `channel_library.sqlite3` described above. Runtime Telegram sessions, auth files, and downloaded media are not stored in these databases.

To keep small 1 vCPU / 1 GiB servers responsive:

- dashboard polling returns only recent task summaries
- large file lists are loaded through paginated APIs
- Web prescan defaults to 2000 messages and 30 packages
- Web prescan is capped at 10000 messages, 100 packages, and batch size 100
- only one Web prescan scan may run at a time

## APIs

- `GET /api/task-dashboard`: task summary plus current download speed. Each task row and file row now also carries `upload_progress` and `upload_speed` (task rows aggregate upload progress across their files).
- `GET /api/tasks`: task summaries.
- `GET /get_upload_list`: rows for files currently uploading (chat, id, filename, total_size, upload_progress, upload_speed).
- `GET /api/tasks/<task_id>`: one task with file rows.
- `GET /api/tasks/<task_id>/files?page=1&page_size=50`: paginated file rows.
- `POST /api/tasks`: submit JSON `{"link": "https://t.me/..."}`.
- `POST /api/tasks` with `{"mode": "prescan", "max_messages": 2000}`: start a bounded Web prescan (max_messages optional, clamped to 10000).
- `POST /api/tasks/<task_id>/confirm`: confirm a preview and queue the download.
- `POST /api/tasks/<task_id>/cancel`: cancel a preview before download.
- `GET /api/prescans/<task_id>/packages?page=1&page_size=50`: paginated prescan packages.
- `POST /api/prescans/<task_id>/packages/<package_id>/select`: include or exclude a package.
- `POST /api/prescans/<task_id>/packages/select-all`: include or exclude all packages at once with `{"selected": true|false}`.
- `POST /api/tasks/<task_id>/clear`: clear one terminal task from Web history.
- `POST /api/tasks/clear-completed`: clear completed task history.
- `GET /api/tasks/<task_id>/upload-retries`: returns only files whose retained local copy has an `upload_failed` state.
- `POST /api/tasks/<task_id>/retry`: channel-library tasks retry only retained cloud uploads. It returns `202` after scheduling; missing local sources remain in the retry list as `upload_source_missing` and are never re-downloaded implicitly. Other task types continue to return `409` because their original command metadata is not persisted.
- `POST /api/tasks/<task_id>/upload-retries/cleanup`: explicitly deletes retained channel-library upload-failure source files under `save_path`; each row remains visible as `upload_source_removed` and is never re-downloaded automatically.
- `GET /api/system`: CPU / memory / disk(save_path 卷)/ throughput 快照。

All APIs require the existing Web login session.

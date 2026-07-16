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

## Channel Library API

The channel library uses the existing Web login session. Call `GET /api/csrf-token` after login and send its `csrf_token` value in `X-CSRF-Token` on every mutating channel-library request. The token is bound to that browser session. Only this authenticated GET mints a token; missing, wrong, and cross-session mutation attempts return `403` without creating or rotating session state. Read and write channel routes return `503 service_unavailable` until Telegram has started and the single channel-library service is running.

Errors use one JSON envelope: `{"error_code": "<stable_code>", "message": "<safe summary>"}`. Supported status classes are `400 invalid_request` or `invalid_link`, `403 csrf_failed`, `404 not_found`, `409 state_conflict`, and `503 service_unavailable` or `service_timeout`. Raw exceptions, Telegram session details, tokens, and configuration secrets are not returned.

Channel and scan routes:

- `GET /api/channel-libraries?cursor=&page_size=50`: keyset page with latest scan/count summary.
- `POST /api/channel-libraries`: `{"link": "https://t.me/..."}`; returns `202` when created and `200` for the existing library.
- `GET /api/channel-libraries/<library_id>`: library, opaque `library_version`, latest scan, counts, and safe failure summaries.
- `DELETE /api/channel-libraries/<library_id>`: `{"confirm_library_id": <id>, "library_version": "<version>"}`; atomically rejects version changes, active scans, and queued/downloading child attempts even if a parent batch summary is terminal.
- `POST /api/channel-libraries/<library_id>/scans`: `{"mode": "incremental"}`, `{"mode": "repair", "failure_ids": [<id>]}`, or `{"mode": "retry", "failed_job_id": <id>}`; returns `202`.
- `POST /api/channel-scans/<job_id>/pause`, `/resume`, or `/stop`: persists control at the next safe scan boundary.

Package, selection, and download routes:

- `GET /api/channel-libraries/<library_id>/packages`: accepts `q`, UTC `date_from`/`date_to`, message/media/size min/max bounds, `include_unknown_size=true|false`, `download_status`, `cursor`, and `page_size` (1-200). Returns `next_cursor` and `library_revision` unchanged from the store.
- `GET /api/channel-libraries/<library_id>/packages/<package_id>/items`: keyset-paginated media metadata; respects `hide_file_name`.
- `PUT /api/channel-libraries/<library_id>/selection/packages/<package_id>`: `{"selected": true|false}`.
- `POST /api/channel-libraries/<library_id>/selection/select-filtered`: a JSON object containing the same package filters.
- `POST /api/channel-libraries/<library_id>/selection/clear` and `GET /api/channel-libraries/<library_id>/selection`: clear or summarize the persistent cross-page selection.
- `POST /api/channel-libraries/<library_id>/download-batches`: optional `{"redownload": true|false}` plus required `Idempotency-Key`. Creation/replay is decided in one SQLite write transaction: the true creator returns `202`, concurrent or later replay returns the same batch with `200`, and replay repairs a still-pending dispatch before returning.

Every route rejects undocumented query keys, JSON fields, and request bodies with `400 invalid_request`; pause/resume/stop and selection-clear accept either no body or an empty JSON object only. Flask performs synchronous validation, store reads, and persisted store commands only. Telegram link resolution, incremental snapshots, scan scheduling, and package downloads are submitted to the existing `Application.loop`; Flask never starts or awaits a second event loop. Link resolution waits at most 30 seconds, and a timeout returns `503` without cancelling persisted or in-flight owner-loop work. The service closes command admission before shutdown, drains every already-accepted owner-loop command, then stops scheduler/download tasks. The application clears its service reference before that drain so new Web requests immediately receive `503`; Telegram client stop occurs only afterward.

## Resource Boundaries

The Web console persists task and file snapshots to `web_tasks.sqlite3` using SQLite WAL mode. Runtime Telegram sessions, auth files, and downloaded media are not stored in this database.

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
- `POST /api/tasks/<task_id>/retry`: currently returns `409` until original command metadata is persisted for safe retry.
- `GET /api/system`: CPU / memory / disk(save_path 卷)/ throughput 快照。

All APIs require the existing Web login session.

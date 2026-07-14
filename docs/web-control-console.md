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

All APIs require the existing Web login session.

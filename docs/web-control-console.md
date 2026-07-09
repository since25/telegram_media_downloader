# Web Control Console

The Web console shows downloader tasks from the same in-process task store used by bot and downloader workflows.

## Task Submission

After logging in, the Tasks tab can submit Telegram links directly:

- ordinary private message/package links, for example `https://t.me/c/1298283297/126711`
- comment links, for example `https://t.me/channel/422?comment=4978`

Submitted links are scheduled on the running downloader event loop. The Web process must be started by `media_downloader.py` so the Web layer has access to the active Pyrogram client; calling the Flask app without the downloader client returns `503`.

Web-submitted package/comment tasks use the existing scan and download pipeline and the recommended naming strategy. Task rows move through scan, queue, download, upload, and completion states on `/api/task-dashboard`.

## APIs

- `GET /api/task-dashboard`: task summary plus current download speed.
- `GET /api/tasks`: task summaries.
- `GET /api/tasks/<task_id>`: one task with file rows.
- `POST /api/tasks`: submit JSON `{"link": "https://t.me/..."}`.

All APIs require the existing Web login session.

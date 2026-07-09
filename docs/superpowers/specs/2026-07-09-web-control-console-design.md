# Web Control Console Design

## Goal

Build a full Web control console that stays synchronized with backend download work through Phase 2:

- Phase 1: a reliable task status dashboard for bot and Web-created work.
- Phase 2: Web task submission for Telegram links, reusing existing downloader flows.
- Phase 3: Web prescan selection, persistent history, retry, and cleanup, defined here as the later extension target.

The design must not replace the current Telegram bot workflows or low-level download workers. It adds a shared task state layer and Web APIs around the existing system.

## Current Problem

The current Web UI is a transient download-speed monitor, not a task console.

- `module/templates/index.html` polls `get_download_status` for total speed and `get_download_list` for rows.
- `get_download_list` reads `module.download_stat.get_download_result()`.
- `download_result` is populated only while `client.download_media(... progress=update_download_status)` is reporting byte progress.
- `media_downloader.download_task()` deletes each message from `download_result` in `finally`.

This means the Web UI can miss submitted tasks, queued messages, scanning states, upload states, completion summaries, and failures. The Telegram bot status is closer to truth because it uses `TaskNode`, but the Web UI does not have a stable task-level model.

## Architecture

Add a task state layer beside the existing downloader:

1. `Task State Store`
   - In-memory source of truth for Web-readable task snapshots.
   - Mirrors important state from `TaskNode`, queue events, file progress, upload progress, and workflow stages.
   - Keeps recent completed tasks for the current process.

2. `Task Snapshot API`
   - Read-only Web API for dashboard data.
   - Returns task summaries, task details, current file progress, queue stats, and global speed.

3. `Web Command API`
   - Write API for Web actions.
   - Creates task commands from Telegram links and delegates execution to existing parsing and download paths.

4. `Existing Workers`
   - Continue to use `TaskNode`, `queue`, `download_task`, `download_prepared_messages`, comment workflows, package workflows, and prescan planning.
   - Web must not call low-level Pyrogram download methods directly.

## Data Model

### Task Snapshot

A task is one user-visible unit of work:

- single forwarded media download
- normal/private package link download
- comment link download
- prescan batch
- future Web-created task

Fields:

- `task_id`: string or int, stable within the process.
- `source`: `bot` or `web`.
- `task_type`: `single`, `package`, `comment`, `prescan`, or `manual_range`.
- `chat_id`: source chat when known.
- `title`: short display title from link, package title, caption, or fallback.
- `status`: one task status value.
- `created_at`, `updated_at`.
- `total_count`, `success_count`, `failed_count`, `skipped_count`, `upload_success_count`.
- `current_file`: latest active file summary when available.
- `error`: short safe error message when failed.
- `needs_confirmation`: true for prescan or workflows waiting for choice.

Task statuses:

```text
created -> scanning -> waiting_confirmation -> queued -> downloading -> uploading -> completed
                                                -> cancelled
                                                -> failed
```

Use `completed_with_errors` when the task finished but has failed downloads or upload failures.

### File Snapshot

A file is one Telegram message/media item inside a task.

Fields:

- `message_id`
- `status`
- `filename`
- `total_size`
- `downloaded_size`
- `download_progress`
- `download_speed`
- `save_path`
- `error`
- `updated_at`

File statuses:

```text
queued -> downloading -> downloaded -> uploading -> uploaded -> skipped -> failed
```

Use `upload_failed` when download succeeded but cloud upload failed.

### Workflow Snapshot

Workflow state is used for scan and prescan phases.

Fields:

- `workflow_type`: `package_scan`, `comment_scan`, `prescan`
- `status`: `scanning`, `waiting_confirmation`, `confirmed`, `failed`
- `scan_count`
- `media_count`
- `selected_count`
- `summary`
- `error`

## Data Flow

All task entrypoints register a `TaskSnapshot` early.

1. Link or command received.
2. Task state is created with `created`.
3. Scan or parse starts: `scanning`.
4. If user choice is required: `waiting_confirmation`.
5. Confirmed work is queued: `queued`.
6. Worker starts a file: `downloading`.
7. Download finishes and upload begins: `uploading`.
8. Task finishes: `completed`, `completed_with_errors`, `failed`, or `cancelled`.

The existing `download_result` remains a byte-progress source for active file downloads, but task existence and summaries come from the task state store.

## Web APIs

### Read APIs

`GET /api/task-dashboard`

Returns:

- global download state
- total download speed
- queue length
- active task count
- recent completed task count
- summarized task list

`GET /api/tasks`

Returns task summaries for all active tasks and recent completed tasks.

`GET /api/tasks/<task_id>`

Returns one task with file snapshots and workflow snapshot.

Existing `get_download_status` and `get_download_list` remain for compatibility during migration.

### Command APIs

`POST /api/tasks`

Payload:

```json
{
  "source": "web",
  "link": "https://t.me/c/1298283297/126711",
  "mode": "auto"
}
```

Behavior:

- Reject empty or non-Telegram links with `400`.
- Detect comment links and package links using existing helpers.
- Create a task state snapshot immediately.
- Delegate to existing scan/download orchestration.
- Return the created `task_id` and initial status.

`POST /api/tasks/<task_id>/cancel`

Phase 3 target. Sets the backing `TaskNode.is_stop_transmission` when possible and marks the task `cancelled`.

`POST /api/tasks/<task_id>/retry`

Phase 3 target. Requeues failed items using existing retry behavior where available.

## Phase 1: Task Status Dashboard

Deliverables:

- New task state store module.
- Registration/update helpers that can be called from bot and downloader paths.
- Task snapshot API.
- Web dashboard table driven by `/api/task-dashboard` or `/api/tasks`.
- Current file details continue to use active byte progress.
- Recent completed tasks are retained in memory.

Success criteria:

- A bot-submitted task appears in Web before a file begins downloading.
- Queued, downloading, uploading, completed, failed, and skipped counts are visible.
- Finished tasks remain visible after `download_result` cleanup.
- No local service needs to be started for verification.

## Phase 2: Web Task Submission

Deliverables:

- Web submission panel for Telegram links.
- API route `POST /api/tasks`.
- Reuse existing link parsing for ordinary/private package links and comment links.
- Create and track a `TaskNode` for Web-submitted work.
- Submitted tasks appear immediately in the dashboard.

Supported in Phase 2:

- direct ordinary/private message links handled as package downloads
- comment links handled as guided comment downloads when no extra Web choice is needed
- simple validation failures shown as failed tasks

Not supported until Phase 3:

- browser-based prescan package selection
- persistent task history after process restart
- Web-side editing of scan ranges
- retry and cancel controls

## Phase 3: Prescan, History, Retry, Cleanup

Phase 3 extends the same state model:

- Web prescan form submits a start link.
- Backend uses existing `module.prescan_workflow` package planning.
- Web displays package candidates and lets the user select packages.
- Selected packages are downloaded serially using existing recommended naming.
- Completed history is persisted with SQLite or JSONL.
- Failed files can be retried.
- Completed tasks can be cleared from the dashboard.

SQLite is preferred once history needs querying; JSONL is acceptable for append-only audit logs.

## Error Handling

- Invalid link: create a failed task or reject before creation with a clear message.
- Telegram scan failure: mark task `failed` with a safe error summary.
- FloodWait/rate limit: keep task `scanning` or `queued` and expose wait seconds when available.
- Single file failure: mark file failed and continue other files.
- Upload failure: mark file `upload_failed`; task becomes `completed_with_errors`.
- Service restart: Phase 1 and 2 in-memory task state is lost; Phase 3 adds persistent history.

## Security

- All APIs require existing Web login.
- Do not expose bot token, API hash, Telegram session data, Discord webhook URLs, rclone secrets, or raw config secrets.
- Respect `hide_file_name` in task and file snapshots.
- Web command APIs accept Telegram links and explicit command fields only; they do not accept arbitrary shell commands or filesystem paths.
- Cancellation must not kill the Python process; it should use task flags already understood by workers.

## Testing

Unit tests:

- task store creates, updates, completes, and retains tasks
- task store derives counts from file snapshots
- file progress updates do not remove task snapshots
- hidden filenames are masked when configured

Web API tests:

- unauthenticated API access is rejected
- authenticated `/api/task-dashboard` returns empty-state data
- `/api/tasks` returns active and completed tasks
- invalid Web submission returns a safe error
- valid submission creates a task and delegates to a patched orchestration function

Integration-style tests:

- a `TaskNode` registered through the store appears in task APIs
- file progress updates move a task into `downloading`
- completion keeps the task visible after active progress data is removed

Manual remote verification:

- deploy to RackNerd
- restart only `tg-downloader.service`
- verify `https://tgdn.wyichuan.cc/` still returns the login flow
- submit a Web task and verify it appears in the dashboard

## Rollout

Commit checkpoints:

1. design and plan
2. Phase 1 backend task state/API
3. Phase 1 Web dashboard
4. Phase 2 Web submission API/UI
5. remote deployment verification

Deployment:

- Do not start the service locally.
- Push or sync committed changes to the RackNerd checkout.
- Restart `tg-downloader.service` on the server.
- Verify remote HTTP behavior through Cloudflare.

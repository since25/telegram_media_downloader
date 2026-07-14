# Web Task Console UX and Ranged Batch Download Design

## Goal

Improve the Web control console in two independent deliverables, implemented in order:

- Feature A: task dashboard UX enhancement (status legibility, progress, errors, empty states, polling stability). Frontend only.
- Feature B: Web ranged batch scan and whole-batch download, extending the existing Web prescan with a user-set message count, raised safety limits, and a clearer selection/batch-download UX.

Both deliverables live on the Tasks tab and share the prescan detail panel, so they are designed together but built, verified, and logged as separate closed loops (A first, then B).

Non-goals: no change to bot workflows, the download pipeline, the task state store schema, or the deployment path. Feature B raises Web prescan limit constants and adds one bulk-select endpoint; it does not rewrite scanning or downloading.

## Background

The Web task dashboard already reports bot and Web tasks from the shared task store, supports Web submission (auto preview and prescan), preview confirm/cancel, prescan package selection with serial download, cancel of active nodes, clear/clear-completed, SQLite persistence with reload on restart, and a full settings tab.

Two problems motivate this work:

1. The task dashboard renders the store's data poorly. `status` shows raw enum text, file progress shows a raw number (worse than the legacy Files tab, which draws a `layui-progress` bar), `error` fields are present in the API payload but never displayed, counts are cryptic, and the 1-second poll reloads whole tables and drops the selected-row highlight.
2. Advanced batch operations (comment download, prescan continuous packages) run on the bot but are less flexible on the Web. Production log evidence shows the user's real high-frequency operation is batch package / prepared-message downloads, often Web-initiated, with real batches up to ~126 files in one session — larger than the current Web prescan package cap of 30.

The backend already exposes the data both features need:

- `FileSnapshot.to_dict()` returns human-readable `total_size`, `download_speed` (with `_bytes` companions), a `download_progress` percentage, and `error`.
- `TaskSnapshot.to_dict()` returns `error`, counts, and `current_file`.
- `_prescan_limits_from_payload(payload)` already reads `max_messages`, `max_packages`, and `batch_size` from the submit payload, bounded by `WEB_PRESCAN_MAX_*` constants.
- `scan_prescan_packages(client, chat_id, start_message_id, max_messages=...)` scans `range(start_message_id, start_message_id + max_messages)`, so an explicit message count maps directly to `max_messages`.
- `_run_confirmed_prescan_download(prescan)` already downloads all selected packages serially via `download_prescan_packages(packages, channel, node, selected_ids)`.

So Feature A is pure frontend, and Feature B is mostly frontend plus a limit-constant change and one bulk-select endpoint.

## Feature A: Task Dashboard UX

Scope: `module/templates/index.html` and `module/static/css/index.css` only. No backend change.

### Status badges

Render the `status` field as a colored layui badge instead of raw text. Mapping:

| Status | Color | Label |
| --- | --- | --- |
| `downloading`, `uploading`, `queued`, `scanning` | blue (`layui-bg-blue`) | as-is |
| `completed` | green (`layui-bg-green`) | `completed` |
| `completed_with_errors` | orange (`layui-bg-orange`) | `completed · errors` |
| `failed` | red (`layui-bg-red`) | `failed` |
| `waiting_confirmation` | cyan (`layui-bg-cyan`) | `waiting` |
| `cancelled`, `created` | gray (`layui-bg-gray`) | as-is |

The `completed_with_errors` label is shortened to `completed · errors`; the full status string is shown on hover via `title`.

### Error visibility

- Task list: when `task.error` is present, the status badge carries the error text in its `title` attribute.
- Detail panel: when the selected task has `task.error`, show a red error banner above the detail table.
- File detail table: add an `error` column that shows the file's `error` in red when present, blank otherwise.

### Progress bars

- File detail table: replace the raw `download_progress` number with a `layui-progress` bar, reusing the color rule already used by the legacy Files tab (>=100 green, >30 blue, else red). Show the percentage and formatted speed as small text under the bar for active files.
- Task list: add a compact task-level progress bar column driven by `(success_count + failed_count + skipped_count) / total_count` when `total_count > 0`, with the `done / total` count as small text. Show `-` when `total_count` is 0.

### Counts readability

Render the `ok/fail/skip/up` column as colored segments: success green, failed red (bold when > 0), skipped gray, uploaded blue. Keep the header text and add a `title` legend explaining the four numbers.

### Empty states and polling stability

- Give each task-related table a friendly `text: { none: ... }` empty message (for example, "No tasks yet — paste a link above to start a download").
- After `updateTaskDashboard` reloads the task list, re-apply the selected-row highlight for `selectedTaskId` in the table `done` callback.
- Set detail-table columns only when the selected task type changes; on the 1-second poll, reload data only, not columns.
- Skip the detail reload when a lightweight signature of the detail data is unchanged, to reduce flicker and scroll jumps.

These stability measures reduce, but do not fully eliminate, layui's full-table re-render on reload. Perfect diff-updating would require replacing the detail table with hand-built HTML, which is out of scope for this pass.

## Feature B: Web Ranged Batch Scan and Download

Scope: `module/templates/index.html`, `module/static/css/index.css`, and `module/web.py`. No change to `prescan_workflow.py`, `task_state.py`, or the download pipeline.

### Message count input

Add a "scan messages" number input to the prescan submit form on the Tasks tab. On prescan submit, the frontend sends `max_messages` in the JSON payload. The backend already reads it through `_prescan_limits_from_payload`; the value is clamped to the new ceiling. The count defines the scan window as `range(start_message_id, start_message_id + max_messages)`.

Range input method: start link plus message count (chosen over two-link or numeric start/end). The start link continues to define `start_message_id`; the count field defines the forward window.

### Raised limits

For this ranged mode, raise the Web prescan ceilings so real batches fit:

- `WEB_PRESCAN_MAX_MESSAGES`: 2000 -> 10000
- `WEB_PRESCAN_MAX_PACKAGES`: 30 -> 100
- `WEB_PRESCAN_DEFAULT_MESSAGES`: 1000 -> 2000 (default when the user leaves the count blank)
- `WEB_PRESCAN_DEFAULT_PACKAGES`: 20 -> 30
- `batch_size` (50 default, 100 max) and `WEB_PRESCAN_BATCH_DELAY_SECONDS` (1) unchanged
- the single-concurrent-scan lock and serial confirmed download are unchanged

Rationale and safety: scanning holds only message metadata in memory (no media), so ~10000 message objects is acceptable on a 1 vCPU / 1 GiB server; downloads remain serial and queued, so raising the count does not increase download concurrency. The hard ceiling (10000 messages, 100 packages) bounds worst-case memory. Trade-off: a large scan is slow because of the per-batch rate-limit delay (~1s per 50 messages, so ~10000 messages is roughly 3+ minutes); scan progress is already published to the dashboard, so the long scan is visible rather than silent.

### Selection and batch-download UX

Enhance the prescan detail panel:

- Add "Select all" and "Clear all" controls.
- Show a running summary: selected package count, total media count across selected packages, and estimated total size across selected packages. The size is computed client-side by summing each selected package's `known_total_size_bytes` and formatting the total.
- Add an explicit "Download N selected packages" button that calls the existing confirm endpoint; keep per-package Include/Exclude for fine control.

Add one backend endpoint for efficient bulk selection so "Select all" / "Clear all" do not issue one request per package:

`POST /api/prescans/<task_id>/packages/select-all`

Payload: `{ "selected": true }` to select every package in the prescan, `{ "selected": false }` to clear. Behavior mirrors the existing single-package select endpoint: update `selected_package_ids` for the pending prescan and refresh the workflow `selected_count`. Requires the existing Web login. Returns `{ "ok": true, "selected_count": N, "total": M }`. Returns 404 when the prescan is not found.

The confirm and serial download path is reused unchanged.

## Data Flow

Feature A changes only how existing dashboard/detail payloads are rendered; no new data flow.

Feature B extends the existing prescan flow:

1. User submits a start link in prescan mode with a message count.
2. `_submit_web_prescan` builds bounded limits (with the new ceiling) and schedules `_run_web_prescan_task`.
3. Scan runs within the count window, publishing progress; packages populate the pending prescan.
4. User selects packages (per-package or Select all / Clear all), sees the running summary.
5. User clicks "Download N selected packages"; the existing confirm endpoint queues `_run_confirmed_prescan_download`, which downloads selected packages serially.

## Error Handling

- Feature A surfaces existing `error` fields; it introduces no new failure modes.
- Feature B: invalid or non-Telegram links are rejected as today. A count above the ceiling is clamped, not rejected. A second concurrent scan is rejected by the existing single-scan lock. The bulk-select endpoint returns 404 when the prescan is missing. Scan failures continue to mark the task failed with a safe error summary, now visible via Feature A's error display.

## Security

- No change to auth; all APIs including the new bulk-select endpoint require the existing Web login.
- No new secrets are exposed. Filenames continue to respect `hide_file_name` through the existing snapshot serialization.
- The bulk-select endpoint accepts only a boolean and a task id; no filesystem paths or commands.

Out-of-scope note: the production log stores a Discord monitor webhook URL in plaintext (`log/tdl.log`). This is unrelated to this change and is flagged for a separate task; it is not addressed here.

## Testing

Feature A (frontend):

- Local browser verification with mock dashboard/detail payloads (no service started): confirm status badges, per-file and per-task progress bars, task and file error display, colored counts, empty states, and preserved selection highlight across a simulated poll.
- Run the existing Python suite to confirm no backend regression: `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`.

Feature B:

- Unit tests in `tests/module/test_web.py`:
  - prescan submit passes a user `max_messages` through to bounded limits and clamps values above the new ceiling
  - the new `select-all` endpoint selects and clears all packages and updates `selected_count`
  - `select-all` returns 404 for an unknown prescan and requires login
- Frontend verification of the count input, running summary, Select all / Clear all, and the batch-download button with mock data.

## Deployment

Follow the existing flow: do not start the service locally; push committed changes, fast-forward the RackNerd checkout, restart `tg-downloader.service`, and verify Web routes through Cloudflare still reach the login flow.

## Rollout Order

1. Feature A: implement, verify, log, commit.
2. Feature B: implement, verify, log, commit.
3. Deploy both to RackNerd and verify remote HTTP behavior.

Each feature is independently revertible via its own commit.

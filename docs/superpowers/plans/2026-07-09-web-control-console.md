# Web Control Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the Web control console through Phase 2: reliable task status dashboard plus Web submission for Telegram links.

**Architecture:** Add an in-memory task state store beside the existing downloader, expose read/write Web APIs, and update the existing Web UI to show stable task state. Reuse existing `TaskNode`, queue, comment-link workflow, package-link workflow, and downloader workers instead of creating a separate execution system.

**Tech Stack:** Python 3, Flask, Flask-Login, Pyrogram, existing Layui frontend, unittest/pytest.

## Global Constraints

- Do not start the service locally.
- Preserve existing bot workflows and low-level download workers.
- All new Web APIs must require existing Web login.
- Do not expose bot tokens, API hashes, Discord webhooks, session data, rclone secrets, or raw config secrets.
- Respect `hide_file_name` in task and file snapshots.
- Phase 1 and Phase 2 task history is in-memory only; persistent history is Phase 3.
- Add `progress.md` entries after repository file changes.

---

## File Structure

- Create `module/task_state.py`: task/file dataclasses, status constants, in-memory store, safe serializers, node snapshot helpers.
- Create `tests/module/test_task_state.py`: pure tests for task store behavior and masking.
- Modify `module/download_stat.py`: register and update task/file snapshots from active task nodes and progress callbacks.
- Modify `media_downloader.py`: publish queue, worker, download, upload, completion, and cleanup state transitions.
- Modify `module/bot.py`: ensure bot-created task nodes are registered with task metadata early.
- Modify `module/web.py`: add `/api/task-dashboard`, `/api/tasks`, `/api/tasks/<task_id>`, and `POST /api/tasks`.
- Modify `module/templates/index.html`: add task dashboard and Web task submission UI.
- Modify `tests/module/test_web.py`: cover dashboard API and Web task submission with patched orchestration.
- Modify `README_CN.md`: document Web dashboard and Web submission behavior.
- Modify `progress.md`: append implementation progress entries.

## Task 1: Add Task State Store

**Files:**
- Create: `module/task_state.py`
- Create: `tests/module/test_task_state.py`

**Interfaces:**
- Produces:
  - `TaskStatus`, `FileStatus` string constants.
  - `TaskStateStore.create_task(...) -> TaskSnapshot`
  - `TaskStateStore.update_task(task_id, **updates) -> TaskSnapshot | None`
  - `TaskStateStore.upsert_file(task_id, message_id, **updates) -> FileSnapshot`
  - `TaskStateStore.complete_task(task_id) -> TaskSnapshot | None`
  - `get_task_store() -> TaskStateStore`
  - `mask_display_name(name: str, hide: bool) -> str`
  - `snapshot_node(node, source="bot", task_type=None, title=None) -> TaskSnapshot`
- Consumes: existing `TaskNode` fields from `module.app`.

- [ ] **Step 1: Write tests for create/update/complete**

Add tests that create a task, update status/counts, add files, complete it, and assert completed tasks remain in serialized output.

- [ ] **Step 2: Implement dataclasses and store**

Implement `TaskSnapshot`, `FileSnapshot`, `WorkflowSnapshot`, and `TaskStateStore` with an `RLock` and recent completed limit.

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/module/test_task_state.py -q`

- [ ] **Step 4: Commit**

Commit message: `feat: add web task state store`

## Task 2: Expose Task Snapshot APIs

**Files:**
- Modify: `module/web.py`
- Modify: `tests/module/test_web.py`

**Interfaces:**
- Consumes `get_task_store()` from Task 1.
- Produces:
  - `GET /api/task-dashboard`
  - `GET /api/tasks`
  - `GET /api/tasks/<task_id>`

- [ ] **Step 1: Write API tests**

Add authenticated tests for empty dashboard, task list, and task detail. Add unauthenticated checks that redirect or reject.

- [ ] **Step 2: Implement API routes**

Return queue stats when available, global download state, total speed, active tasks, completed tasks, and serialized task rows.

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`

- [ ] **Step 4: Commit**

Commit message: `feat: expose web task snapshot api`

## Task 3: Publish Backend Task Transitions

**Files:**
- Modify: `module/download_stat.py`
- Modify: `media_downloader.py`
- Modify: `module/bot.py`
- Modify: `tests/module/test_task_state.py`
- Modify: `tests/test_media_downloader.py`

**Interfaces:**
- Consumes store APIs from Task 1.
- Produces helper calls that keep task snapshots aligned with queue, download, upload, and completion.

- [ ] **Step 1: Add tests for node snapshot and file progress**

Cover a `TaskNode` becoming visible in the store, a file progress update setting `downloading`, and completion retaining task data after active progress cleanup.

- [ ] **Step 2: Register bot task nodes**

Call `snapshot_node(...)` whenever `add_active_task_node(node)` is called for bot-created tasks.

- [ ] **Step 3: Update file progress**

In `update_download_status`, upsert file progress and mark task `downloading`.

- [ ] **Step 4: Update queue and completion states**

In queueing and worker/download code, mark files `queued`, `downloading`, `downloaded`, `uploading`, `uploaded`, `failed`, or `skipped`; mark tasks completed or completed_with_errors when all known work is done.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/module/test_task_state.py tests/test_media_downloader.py -q`

- [ ] **Step 6: Commit**

Commit message: `feat: publish downloader task states`

## Task 4: Build Phase 1 Dashboard UI

**Files:**
- Modify: `module/templates/index.html`
- Modify: `module/static/css/index.css`
- Modify: `tests/module/test_web.py`

**Interfaces:**
- Consumes `/api/task-dashboard`, `/api/tasks`, `/api/tasks/<task_id>`.

- [ ] **Step 1: Add rendered HTML smoke tests**

Assert the index page contains the task dashboard table, summary counters, and submission panel container.

- [ ] **Step 2: Replace transient table as primary dashboard**

Add dashboard counters and a task table. Keep old speed footer and advanced config tab.

- [ ] **Step 3: Poll task APIs**

Poll `/api/task-dashboard` every second on the dashboard tab. Render task rows with status, counts, current file, and updated time.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/module/test_web.py -q`

- [ ] **Step 5: Commit**

Commit message: `feat: add web task dashboard`

## Task 5: Add Web Task Submission API

**Files:**
- Modify: `module/web.py`
- Modify: `module/task_state.py`
- Modify: `module/bot.py` or `media_downloader.py`
- Modify: `tests/module/test_web.py`

**Interfaces:**
- Produces `POST /api/tasks` for Phase 2.
- Reuses existing link parsing and orchestration helpers.

- [ ] **Step 1: Write submission tests**

Test invalid link failure and valid private/comment link submission with orchestration patched so no network call is made.

- [ ] **Step 2: Add command handler function**

Create a small function that accepts `(app, link, source="web")`, creates task state, detects link type, and delegates to existing package/comment flow.

- [ ] **Step 3: Add route**

Implement `POST /api/tasks` that validates JSON and returns `task_id`, `status`, and safe message.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`

- [ ] **Step 5: Commit**

Commit message: `feat: add web task submission api`

## Task 6: Add Web Submission UI

**Files:**
- Modify: `module/templates/index.html`
- Modify: `module/static/css/index.css`
- Modify: `README_CN.md`
- Modify: `tests/module/test_web.py`
- Modify: `progress.md`

**Interfaces:**
- Consumes `POST /api/tasks`.

- [ ] **Step 1: Add HTML smoke tests**

Assert the page includes link input, submit button, and submission status area.

- [ ] **Step 2: Add UI controls**

Add a compact submission band above the task table with a Telegram link input and submit button.

- [ ] **Step 3: Wire submit behavior**

POST JSON to `/api/tasks`, show success/failure, and refresh the task dashboard.

- [ ] **Step 4: Update docs and progress log**

Document Web dashboard and Web submission in `README_CN.md`. Append `progress.md`.

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`

- [ ] **Step 6: Commit**

Commit message: `feat: add web task submission ui`

## Task 7: Final Verification and Remote Deployment

**Files:**
- Modify: `progress.md`

**Interfaces:**
- Consumes committed Phase 1/2 changes.

- [ ] **Step 1: Run local non-server verification**

Run unit tests only. Do not start a local Web service.

- [ ] **Step 2: Push code**

Push committed changes to the configured origin or otherwise sync the server checkout.

- [ ] **Step 3: Deploy on RackNerd**

SSH to `rn`, update `/root/telegram_media_downloader`, install dependencies if changed, and restart only `tg-downloader.service`.

- [ ] **Step 4: Verify remote**

Verify `https://tgdn.wyichuan.cc/` reaches the login flow and authenticated API/dashboard behavior works.

- [ ] **Step 5: Append deployment progress**

Record commands, results, changed files, and rollback in `progress.md`.

- [ ] **Step 6: Commit deployment log**

Commit message: `docs: record web console deployment`

## Self-Review Notes

- Spec coverage: Phase 1 task status and Phase 2 Web submission are covered by Tasks 1-6. Phase 3 is intentionally documented but not implemented in this plan.
- Placeholder scan: no intentional placeholder steps remain.
- Type consistency: all later tasks consume `TaskStateStore`, `TaskSnapshot`, and Web API names defined in Task 1 and Task 2.

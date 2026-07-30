# Telegram Media Downloader Architecture Hardening Implementation Plan

> Execute in order. Each implementation phase ends with focused verification, the full
> suite, a `progress.md` entry, and an independent Git commit.

**Goal:** Repair audited correctness, persistence, state/thread boundary, Web security,
Rclone, build reproducibility, and runtime declaration defects without rewriting stable
channel-library or resource-delivery subsystems.

**Architecture:** `TaskNode` remains the runtime compatibility object, while
`TaskStateStore` owns durable task/file transitions. Transfer functions record business
results; reporting functions only present them. Flask submits event-loop work through a
bounded thread-safe command boundary. Progress is sampled and persisted off-loop.
Docker builds from local immutable inputs and mounts all mutable state.

**Tech stack:** Python 3.11, asyncio, Flask, SQLite, Pyrogram, pytest/unittest, Docker
Compose, Rclone.

## Global Constraints

- Preserve existing public command, Web payload, task database, channel-library, and
  resource-delivery behavior unless a listed invariant requires a change.
- Do not replace Pyrogram, SQLite, the channel-library store, outbox, disk admission, or
  resource staging.
- Do not commit configuration secrets, `.env.new`, session files, Web auth data, SQLite
  data, logs, or downloaded media.
- Use failing regression tests before implementation changes.
- Do not begin the next phase until the current phase passes its focused tests and full
  regression suite and has its own commit.
- Append, never rewrite, `progress.md`.
- Do not deploy until the final adversarial review is clean.

---

## Phase 1: Task Correctness and Docker State Persistence

### Task 1.1: Lock the task completion invariant

**Files:**

- Modify: `module/app.py`
- Test: `tests/module/test_task_invariants.py`
- Regressions: `tests/module/test_comment_workflow.py`, `tests/test_media_downloader.py`

- [ ] Add failing tests proving:
  - zero terminal results cannot finish one planned file;
  - one success, failure, or skip finishes one planned file;
  - no planned work is not treated as a successfully completed running task;
  - an outer prescan batch still blocks completion;
  - cancellation remains terminal.
- [ ] Run the new test file and retain the failing result.
- [ ] Add a derived `completed_download_task` property and change `is_finish()` to compare
  terminal result count with `total_download_task`.
- [ ] Run focused TaskNode and Bot lifecycle tests.

### Task 1.2: Record each file result exactly once

**Files:**

- Modify: `module/app.py`
- Modify: `module/pyrogram_extension.py`
- Modify: `module/download_lifecycle.py`
- Test: `tests/module/test_task_invariants.py`
- Test: `tests/module/test_download_lifecycle.py`

- [ ] Add failing tests proving:
  - the same `(chat_id, message_id)` result cannot increment counters twice;
  - `report_bot_download_status()` does not call `TaskNode.stat()`;
  - a Bot-reporting exception after a successful download does not increment the failed
    count or replace the persisted file result.
- [ ] Run focused tests and retain the failing result.
- [ ] Make `TaskNode.stat()` idempotent for stable file identities.
- [ ] Remove business-result mutation from `report_bot_download_status()`.
- [ ] Isolate reporting exceptions inside `run_file_lifecycle()` from the transfer
  exception handler.
- [ ] Run lifecycle, Bot status, task state, and download regressions.

### Task 1.3: Persist Docker runtime state

**Files:**

- Modify: `docker-compose.yaml`
- Modify: `module/download_entry.py`
- Modify: `module/bot.py`
- Test: `tests/module/test_runtime_paths.py`
- Test: `tests/test_docker_contract.py`
- Modify: `README.md`
- Modify: `README_CN.md`
- Modify: `docs/web-control-console.md`

- [ ] Add failing tests proving every mutable database/auth path can be overridden and
  Compose maps one host state directory to the configured container paths.
- [ ] Add `TMD_CHANNEL_LIBRARY_DB_PATH`, retain `TMD_TASK_DB_PATH`,
  `TMD_RESOURCE_BOT_DB_PATH`, and `TMD_WEB_AUTH_FILE`, and point the Compose service at
  `/app/state`.
- [ ] Mount `./state:/app/state` and document backup ownership and migration from legacy
  root-level files.
- [ ] Validate the Compose model with `docker compose config` when Docker is available;
  otherwise validate the parsed YAML and record the missing runtime.

### Phase 1 verification and commit

- [ ] Run focused tests for TaskNode, lifecycle, runtime paths, Docker contract, Web
  status, comment workflow, and channel-library download integration.
- [ ] Run the complete suite with isolated task/resource/channel database paths.
- [ ] Run `check_imports.py`, changed-module compilation, `pip check`, and
  `git diff --check`.
- [ ] Append `progress.md`.
- [ ] Commit as `fix: enforce task lifecycle invariants`.

---

## Phase 2: Durable Transitions, Thread Ownership, and Sampled Progress

### Task 2.1: Add one durable task/file transition API

**Files:**

- Modify: `module/task_state.py`
- Modify: `module/download_queue.py`
- Modify: `module/download_lifecycle.py`
- Modify: `module/download_stat.py`
- Test: `tests/module/test_task_state.py`
- Test: `tests/module/test_download_lifecycle.py`

- [ ] Add failing tests proving one transition updates task and file state atomically and
  that a persistence failure cannot leave only half the transition committed.
- [ ] Add a `transition_file()` API that updates task/file fields in one lock scope and
  one SQLite transaction.
- [ ] Route queue, download, upload, and terminal transitions through this API.
- [ ] Keep `update_task()` and `upsert_file()` as compatibility operations for unrelated
  callers.

### Task 2.2: Sample progress and move SQLite work off-loop

**Files:**

- Create: `module/progress_persistence.py`
- Modify: `module/download_stat.py`
- Modify: `module/download_lifecycle.py`
- Test: `tests/module/test_progress_persistence.py`

- [ ] Add failing tests proving rapid callbacks coalesce, meaningful byte/time deltas
  persist, terminal progress flushes, and persistence runs outside the event-loop thread.
- [ ] Implement a bounded per-file sampler with at most one in-flight persistence write
  per file.
- [ ] Use `asyncio.to_thread()` for sampled SQLite transitions.
- [ ] Flush and clear sampler state on file terminal transitions and application shutdown.

### Task 2.3: Establish one Web-to-async command boundary

**Files:**

- Create: `module/web_commands.py`
- Modify: `module/web.py`
- Test: `tests/module/test_web_commands.py`
- Test: `tests/module/test_web.py`
- Test: `tests/test_web_prescan_retention.py`

- [ ] Add failing tests for loop ownership, scheduling failure, bounded wait timeout,
  exception propagation, and coroutine cleanup.
- [ ] Implement a small command submitter around `run_coroutine_threadsafe()`.
- [ ] Replace direct Web scheduling/mutation paths with the submitter without changing
  HTTP success payloads.
- [ ] Ensure request timeouts return `503` while submitted work remains safely owned by
  the application loop.

### Task 2.4: Make restart-orphaned Web confirmations deterministic

**Files:**

- Modify: `module/task_state.py`
- Modify: `module/web.py`
- Test: `tests/module/test_task_state.py`
- Test: `tests/test_web_cancel_task.py`
- Test: `tests/test_web_prescan_retention.py`

- [ ] Add failing restart tests proving waiting confirmations are not presented as
  usable when their process-only Telegram objects are gone.
- [ ] Persist bounded confirmation metadata and a stable `restart_interrupted` reason.
- [ ] On startup, close non-reconstructable confirmation tasks deterministically rather
  than leaving them waiting or relying on process dictionaries.
- [ ] Preserve channel-library resumable tasks and existing restart rules.

### Phase 2 verification and commit

- [ ] Run task-store, progress, Web command, Web prescan/cancel, lifecycle, and
  channel-library regressions.
- [ ] Run the complete suite with isolated databases.
- [ ] Run import, compilation, dependency, database integrity/migration, and diff checks.
- [ ] Append `progress.md`.
- [ ] Commit as `refactor: consolidate task state boundaries`.

---

## Phase 3: Web Security, Rclone Safety, and Reproducible Builds

### Task 3.1: Require CSRF for every authenticated mutation

**Files:**

- Modify: `module/web.py`
- Modify: `module/templates/index.html`
- Modify: `module/templates/login.html` if required
- Test: `tests/module/test_web.py`
- Test: `tests/module/test_channel_library_web.py`
- Test: `tests/test_web_csrf_contract.py`

- [ ] Enumerate Flask routes and add a failing contract test for every authenticated
  `POST`, `PUT`, `PATCH`, and `DELETE` endpoint.
- [ ] Apply the same session-bound CSRF decorator to legacy and new APIs, including
  logout, settings, download state, task submit/confirm/cancel/clear/retry/cleanup, and
  prescan selection.
- [ ] Replace direct frontend mutation `fetch()` calls with one CSRF-aware helper.
- [ ] Preserve unauthenticated login behavior and prove tokens are session-bound.

### Task 3.2: Execute Rclone without a shell

**Files:**

- Modify: `module/cloud_drive.py`
- Modify: `tests/test_web_upload_progress.py`
- Create: `tests/module/test_cloud_drive.py`

- [ ] Add failing tests for paths containing spaces, quotes, and shell metacharacters;
  non-zero exit codes; successful exit without a specific human-readable line; progress
  parsing; and cleanup only after success.
- [ ] Replace `Popen(..., shell=True)` with `subprocess.run([...], check=False)` for
  `mkdir`.
- [ ] Replace `create_subprocess_shell()` with `create_subprocess_exec()`.
- [ ] Decide success from `returncode == 0`; treat parsed output only as progress.
- [ ] Cache remote directories only after successful creation.

### Task 3.3: Make the Docker/dependency build reproducible

**Files:**

- Modify: `Dockerfile`
- Add: `.dockerignore`
- Modify: `requirements.txt`
- Modify: `.github/workflows/docker-publish.yml`
- Test: `tests/test_docker_contract.py`
- Test: `tests/test_dependency_contract.py`
- Modify: `README.md`
- Modify: `README_CN.md`

- [ ] Add failing contract tests for remote mutable compile images, real configuration in
  image layers, missing build-context exclusions, and mutable Git branch dependencies.
- [ ] Copy Rclone and site-packages from the local named compile stage.
- [ ] Copy only example/static application source into the image; mount real config at
  runtime.
- [ ] Pin Pyrogram to an immutable commit/archive with a recorded checksum where pip
  supports it.
- [ ] Simplify Docker publishing to build the runtime image from the checked-out source
  without a shared mutable compile tag.
- [ ] Build the image locally when Docker is available and run import/`pip check` smoke
  checks inside it.

### Phase 3 verification and commit

- [ ] Run all Web, CloudDrive, Docker, and dependency contract tests.
- [ ] Run the complete suite with isolated databases.
- [ ] Run import, compilation, dependency, Docker/YAML, and diff checks.
- [ ] Append `progress.md`.
- [ ] Commit as `security: harden web rclone and builds`.

---

## Phase 4: Targeted Modularization and Runtime Support

### Task 4.1: Remove residual presentation/business coupling

**Files:**

- Modify only modules touched in Phases 1-3.
- Test the affected lifecycle and Web contracts.

- [ ] Search for presentation/reporting functions that still mutate task result counts.
- [ ] Move only those mutations to lifecycle/transition helpers.
- [ ] Search for direct event-loop-owned dictionary mutations from Flask request paths
  and route only remaining cases through the command boundary.
- [ ] Do not split files solely to reduce line count.

### Task 4.2: Align Python and development tooling

**Files:**

- Modify: `setup.py`
- Modify: `dev-requirements.txt`
- Modify: `.github/workflows/unittest.yml`
- Modify: `.github/workflows/code-checks.yml`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `README_CN.md`
- Test: `tests/test_runtime_contract.py`

- [ ] Add failing tests proving metadata, CI, and documentation agree on Python 3.11.
- [ ] Set `python_requires` and classifiers to Python 3.11.
- [ ] Pin Python-3.11-compatible mypy, type stubs, pytest, lint, and formatting tools.
- [ ] Update CI action versions and test Python 3.11 as the production contract.
- [ ] Run mypy and distinguish real application errors from third-party untyped APIs;
  fix only defects in the current scope.

### Phase 4 verification and commit

- [ ] Run runtime contract, mypy, lint/pre-commit checks that are supported by the
  repository, and affected regressions.
- [ ] Run the complete suite with isolated databases.
- [ ] Run imports, compilation, `pip check`, and `git diff --check`.
- [ ] Append `progress.md`.
- [ ] Commit as `chore: align runtime and module boundaries`.

---

## Final Adversarial Review

- [ ] Verify every explicit invariant in the design against current source and tests.
- [ ] Run a route inventory and prove every authenticated mutation requires CSRF.
- [ ] Search for all `TaskNode.stat()` callers and prove one terminal result per file.
- [ ] Search for direct `TaskStateStore` split transitions in lifecycle paths.
- [ ] Search for `shell=True`, `create_subprocess_shell`, mutable Docker tags, mutable Git
  dependency URLs, real config copies, and unsupported Python declarations.
- [ ] Exercise SQLite migration/restart paths and `PRAGMA integrity_check`.
- [ ] Run the complete suite at least once from a clean isolated state.
- [ ] Run import, compile, dependency, mypy, lint/pre-commit, Docker build/config, and
  diff checks to the extent the local environment supports them.
- [ ] Request an independent code review focused on correctness, security, data
  compatibility, and missing tests.
- [ ] Fix every confirmed issue, repeat the relevant checks, append `progress.md`, and
  commit as `fix: address architecture hardening review`.

## Production Deployment

- [ ] Push reviewed `master` commits.
- [ ] Read-only preflight on `rn`: verify checkout path, current commit/worktree, service
  unit, config paths, active/queued tasks and deliveries, disk space, schemas, and
  database integrity.
- [ ] Stop `tg-downloader.service`.
- [ ] Create a mode-`0700` timestamped backup containing the pre-deploy commit,
  configuration, Web auth, sessions, and SQLite API backups of all three databases.
- [ ] Require every backup database `PRAGMA integrity_check` result to be `ok`.
- [ ] Fast-forward production with `git pull --ff-only origin master`.
- [ ] Apply only documented path/config migration required by the reviewed commits.
- [ ] Run imports, changed-module compilation, and `pip check` before restart.
- [ ] Start the service and verify service status, restart count, journal, database
  integrity/schema, authenticated Web access, CSRF, task APIs, Bot clients, and empty or
  preserved queues.
- [ ] Record the exact backup directory, pre/post commits, verification evidence, and
  executable rollback in `progress.md`; commit and push the deployment record.

# Telegram Media Downloader Architecture Hardening Design

## 1. Goal

Harden the existing production application without replacing the mature channel-library,
outbox, disk-admission, restart-reconciliation, or resource-delivery subsystems.

The change is successful only when:

- a task cannot finish before every planned file reaches one terminal download result;
- one file result is counted exactly once;
- reporting, notification, and display failures cannot change a completed transfer result;
- all mutable runtime state used by the Docker deployment survives container replacement;
- Web mutations use one authentication and CSRF policy;
- Flask threads cross into the asyncio owner loop through explicit thread-safe commands;
- progress persistence is bounded and does not perform unbounded synchronous SQLite work
  on the downloader event loop;
- Rclone execution does not use a shell and success is decided by the process return code;
- dependencies and Docker images are reproducible from immutable inputs;
- supported Python and development-tool versions describe the runtime that is actually
  tested.

This is a surgical hardening effort. It does not introduce new product features and
does not redesign stable subsystems that are outside these invariants.

## 2. First-Principles Invariants

### 2.1 Planned work and completed work are different facts

For one `TaskNode`:

- `total_download_task` is the number of planned/enqueued file transfers.
- `success_download_task`, `failed_download_task`, and `skip_download_task` are mutually
  exclusive terminal outcomes.
- `completed_download_task` is derived as the sum of those three terminal outcomes.
- `total_task` remains a compatibility mirror for callers that display or persist the
  planned file count; it is not a completion counter.

A normal task is complete only when it is running, is not a listen-forward task, is not
inside an outer prescan batch, has at least one planned file, and:

`completed_download_task >= total_download_task`

Cancellation remains an explicit terminal condition.

### 2.2 A file result is recorded once

The transfer lifecycle owns the business result. `run_download_phase()` records the
download outcome once. Reporting functions may read that result and add presentation
metadata such as transferred bytes, but must not call `TaskNode.stat()` again.

`TaskNode.stat()` must also be idempotent for a stable `(chat_id, message_id)` identity so
that an accidental duplicate callback cannot corrupt totals.

### 2.3 Business outcome and side effects are isolated

Download and upload execution produce business outcomes. Bot messages, progress
rendering, Web snapshots, and logs are secondary side effects.

- A reporting exception is logged but does not increment the failed download count.
- A persisted download success is never converted to a download failure by notification.
- Upload failure remains an upload-stage result and does not erase download evidence.

### 2.4 Persistent stores are authoritative for durable facts

The existing stores retain their bounded responsibilities:

- `web_tasks.sqlite3`: Web/task dashboard snapshots and file progress;
- `channel_library.sqlite3`: channel index, batches, attempts, and channel-library
  lifecycle;
- `resource_bot.sqlite3`: activation, binding, staging, and delivery jobs;
- `.web_auth.json`: Web credential verifier.

`TaskNode` and process dictionaries are runtime projections. They may improve latency,
but must not be the only copy of a fact needed after restart.

Preview and prescan material required after a Web request must be represented by a
persisted Web workflow record. Large Telegram message objects remain process-local and
are reconstructed from persisted identifiers when confirmation occurs.

### 2.5 Threads have explicit owners

The asyncio loop owns Telegram clients and transfer coroutines. Flask request threads
may validate requests and read thread-safe stores, but mutations that require Telegram
or asyncio state are submitted through `asyncio.run_coroutine_threadsafe()` and observed
through a bounded `Future` result.

No request handler directly mutates event-loop-owned task dictionaries.

### 2.6 Progress is sampled evidence

Progress is not a ledger event. The latest useful sample is sufficient.

- File progress writes are emitted only after a configured minimum time interval,
  meaningful byte delta, or terminal transition.
- SQLite writes are moved off the event-loop thread.
- A task/file terminal transition always flushes the final sample.
- Task and file changes that describe one transition share one store transaction.

### 2.7 Deployment inputs are explicit

- Docker builds all runtime dependencies from the current Dockerfile stage, not a remote
  mutable `latest` compile image.
- Real configuration, credentials, sessions, databases, logs, and downloads never enter
  the image build context.
- The Pyrogram dependency is pinned to an immutable commit or release archive.
- Python support matches the tested Python 3.11 runtime.

## 3. Phase Boundaries

### Phase 1: Correctness and Docker persistence

Implement:

- correct task completion semantics;
- idempotent single-record file results;
- reporting failure isolation;
- persistent Docker mounts for the three SQLite databases and Web auth state.

This phase must not change database schemas.

### Phase 2: State and thread boundary consolidation

Implement:

- a single task/file transition API in `TaskStateStore`;
- one transaction for the task and file parts of a transition;
- sampled, off-loop progress persistence;
- explicit Web-to-async command submission;
- persisted preview/prescan confirmation metadata sufficient to reject or recover
  restart-orphaned requests deterministically.

This phase may add columns to `web_tasks.sqlite3` only when required for persisted Web
workflow metadata. It must preserve existing task history and restart recovery.

### Phase 3: Security, Rclone, and build reproducibility

Implement:

- CSRF on every authenticated state-changing Web route, including legacy task,
  download-state, settings, prescan-selection, retry, cleanup, and logout routes;
- shared frontend helpers that attach the session-bound CSRF token;
- Rclone execution with argument arrays, no shell, captured output, and return-code
  success;
- local image-stage copying, immutable Python dependency inputs, and `.dockerignore`.

Configuration changes that affect production are documented, but production secrets are
never added to source control.

### Phase 4: Targeted module and runtime cleanup

Implement only the modular cleanup needed by Phases 1-3:

- move task result/transition responsibilities out of presentation functions;
- keep Web command and progress-persistence helpers in focused modules where that
  materially reduces cross-thread coupling;
- declare Python 3.11 as the supported runtime;
- update development tooling so type checks run on Python 3.11 without known
  toolchain/stub incompatibilities.

No unrelated formatting, public API redesign, or broad monolith rewrite is allowed.

## 4. Verification Strategy

Every phase follows red-green-refactor:

1. add a regression test that demonstrates the current defect;
2. run it and retain the failing result;
3. implement the minimum fix;
4. run the focused regression set;
5. run the complete suite;
6. run import, compilation, dependency, and diff checks as applicable;
7. append `progress.md`;
8. commit the phase independently.

The final adversarial review checks:

- task completion with zero, one, skipped, failed, duplicate, and reporting-error cases;
- restart and Docker volume paths;
- cross-thread Web commands and timeout behavior;
- progress write frequency and terminal flushes;
- every state-changing Web route for authentication and CSRF;
- Rclone paths containing spaces and shell metacharacters;
- Docker context contents and mutable image/dependency references;
- database integrity and backwards-compatible startup;
- complete test suite, imports, compilation, dependency health, static checks, and
  `git diff --check`.

## 5. Deployment and Rollback

Deployment uses the existing production target:

- SSH alias: `rn`
- checkout: `/root/telegram_media_downloader`
- service: `tg-downloader.service`
- public Web URL: `https://tgdn.wyichuan.cc/`

Before mutation, verify the real server commit, worktree, service status, active/queued
jobs, configuration, and database integrity. Stop the service before backup. Back up
configuration, sessions, Web auth, and all three SQLite databases using
`sqlite3.Connection.backup`; every database backup must pass `PRAGMA integrity_check`.

Production advances only by a fast-forward pull of the reviewed commits. After restart,
verify imports, compilation, dependencies, database schemas/integrity, authenticated Web
access, CSRF-protected mutations, Bot/service health, and recent journal errors.

Rollback is commit- and backup-based:

- stop the service;
- preserve the failed deployment state separately;
- return code to the recorded pre-deploy commit;
- restore only configuration/auth/database artifacts affected by the failing phase;
- restart and repeat health checks.

## 6. Explicit Non-Goals

- replacing Pyrogram;
- rewriting the channel-library database or outbox;
- changing resource-delivery staging semantics;
- adding a distributed queue or external database;
- supporting multi-process Web workers in this release;
- changing user-facing download naming or selection behavior;
- broad frontend redesign.

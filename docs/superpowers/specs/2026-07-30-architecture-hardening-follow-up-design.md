# Telegram Media Downloader Architecture Hardening Follow-up Design

## 1. Context

The first four architecture-hardening phases repaired task completion, single-result
accounting, progress persistence, Web CSRF coverage, Rclone execution, Docker state
persistence, dependency pinning, and the supported Python boundary.

The final review and first-principles audit found remaining defects in the boundaries
between download progress, Flask threads, the asyncio owner loop, persistent task state,
runtime configuration, Web authentication, and process shutdown. These defects must be
repaired before the reviewed local branch is deployed.

This follow-up preserves the current single-process product architecture. It does not
replace Pyrogram, SQLite, the channel-library saga/outbox, disk admission, resource
delivery staging, naming behavior, or the existing Web API surface.

## 2. Approaches Considered

### 2.1 Recommended: Surgical ownership consolidation

Keep the current application process and introduce focused ownership boundaries:

- one transfer-progress tracker shared by progress callbacks and stall watchdogs;
- one Web-to-owner-loop command path for every asyncio-owned mutation;
- explicit application-time task-store initialization;
- immutable task-store read snapshots;
- one atomic configuration persistence path;
- one owned Web server lifecycle;
- one explicit authentication verifier and login-attempt limiter.

This approach fixes the confirmed defects without migrating production databases or
rewriting mature channel and resource subsystems.

### 2.2 Rejected: Rewrite as one ASGI application

Moving Flask, Pyrogram, workers, and schedulers under a new ASGI runtime could provide a
cleaner long-term process model, but it would change almost every production boundary at
once. It would also require new deployment, session, cancellation, and database recovery
semantics. The risk is disproportionate to the confirmed defects.

### 2.3 Rejected: Split Web and downloader into separate processes

A separate Web control process would require an IPC protocol, durable command queue,
multi-process task leases, and new authentication/deployment behavior. The current
SQLite stores and process-local `TaskNode` controls are intentionally single-owner.
Introducing this split now would expand the task beyond hardening.

## 3. Follow-up Invariants

### 3.1 Transfer progress has one identity and one owner

Every active transfer is identified by:

`(task_id, chat_id, message_id)`

The progress callback and stall watchdog read and write the same tracker instance.
Progress from one channel or task cannot refresh, stall, or clear another transfer that
has the same Telegram message ID.

A transfer that continues to report increasing bytes beyond the ten-minute stall window
must not be cancelled. A transfer whose byte count does not advance for the full window
must be classified as stalled and retried according to the existing retry policy.

### 3.2 Accepted Web commands are executable

The Web command boundary accepts work only when the application loop exists, is not
closed, and is currently running. An open-but-stopped loop is unavailable.

Every accepted command is submitted with `asyncio.run_coroutine_threadsafe()`. Submission
failure closes the coroutine. HTTP timeout does not cancel already accepted owner-loop
work.

### 3.3 The owner loop mutates runtime task controls

Flask threads may read synchronized snapshots and validate requests. They must not call
`TaskNode.stop_transmission()` or mutate asyncio-owned task registries directly.

Ordinary Web task cancellation, channel-library cancellation, settings that affect live
runtime objects, and similar commands cross the same bounded owner-loop boundary.

### 3.4 Failure classifications preserve business truth

Only confirmed absence, inaccessibility represented by the existing not-found Telegram
exceptions, unsupported media, or an already complete local file may produce a skip.

Transient transport, server, session, and unexpected message-refetch failures produce a
failure or retry path. They must not be converted into a successful task through skip
accounting.

### 3.5 Importing code cannot recover or prune production state

Importing `module.task_state`, `module.web`, tests, or diagnostic scripts must not create,
recover, prune, or mutate `web_tasks.sqlite3`.

The application entrypoint explicitly initializes the process task store after
configuration is loaded and before Web, channel, Bot, or worker services use it.

Task-store read APIs return snapshots that callers cannot mutate behind the store lock.
All persistent changes use store commands. The task database uses WAL, a bounded busy
timeout, and owner-only file permissions on POSIX.

### 3.6 Configuration has an atomic and explicit activation contract

Configuration fields are divided into:

- hot-applied fields that can safely affect subsequent work in the running process;
- restart-required fields whose configured value is persisted but whose active runtime
  dependency remains unchanged until restart.

`save_path`, worker count, Pyrogram transmission concurrency, startup timeout, Web
host/port/enablement, and upload-adapter replacement are restart-required. They must not
partially update one runtime object while dependent services retain an old value.

Configuration and application-data files are serialized under one lock and replaced
atomically from owner-only temporary files. A failed write leaves the previous files
intact.

### 3.7 Authentication stores verifiers and bounds login attempts

Local Web authentication stores a password verifier instead of a reusable plaintext
password after bootstrap. Existing plaintext auth files migrate without changing the
valid password.

New installations may retain a generated bootstrap password only until the first
successful login. Authentication failures are rate-limited without disclosing whether a
credential exists. Sessions have a bounded lifetime, HTTP-only and SameSite cookies, and
an explicit secure-cookie production setting.

### 3.8 Shutdown is owned and observable

SIGINT and SIGTERM request the same shutdown path. The application stops accepting owner
commands, stops the Web server, stops channel and Bot services, cancels workers, awaits
their completion, flushes configuration, shuts down executors, and closes its event loop.

No worker is merely cancelled and abandoned. Shutdown verification checks for pending
tasks, unclosed executors, and an unjoined Web thread.

### 3.9 Supported adapters and containers tell the truth

The Aligo path either executes its blocking call in the configured executor and has
contract tests, or fails configuration explicitly before work starts. A boolean result
must never be passed to `run_in_executor()` as a callable.

The container remains single-process, uses an owned writable state surface, exposes a
minimal health check, and avoids unnecessary root execution where compatible with the
documented volume migration. Base and Python dependency inputs remain immutable enough
to reproduce the reviewed release.

## 4. Phase Boundaries

### Phase 5: Runtime correctness and command ownership

Implement:

- shared transfer-progress identity and tracker;
- stopped-loop command rejection;
- owner-loop ordinary Web cancellation;
- correct unexpected-refetch failure classification.

No database schema, authentication, configuration, Docker, or public payload change is
allowed in this phase.

### Phase 6: Persistent state and configuration ownership

Implement:

- explicit task-store initialization;
- immutable task snapshots and command-only writes;
- task database permission/timeout parity;
- atomic configuration persistence;
- restart-required versus hot-applied settings;
- owner-loop settings application.

No channel-library or resource-bot schema migration is allowed.

### Phase 7: Authentication, adapter, and shutdown lifecycle

Implement:

- password-verifier migration and bounded login attempts;
- secure session configuration with a production opt-in;
- correct optional Aligo executor behavior and startup validation;
- owned Web server start/stop;
- SIGINT/SIGTERM and awaited application shutdown.

Existing users and production configuration must retain a documented migration and
rollback path.

### Phase 8: Bounded module, static, and container cleanup

Implement only cleanup justified by Phases 5-7:

- keep transfer progress, config persistence, Web auth, and Web serving in focused
  modules;
- extend blocking type/lint checks to the new boundaries and touched call sites;
- add a minimal process health endpoint and container health contract;
- run the container as a non-root user only if the documented state/config volume
  migration is verified not to break existing deployments;
- pin any remaining mutable build input used by the runtime image.

Do not split the channel store, rewrite all Web routes, perform global formatting, or
attempt to eliminate historical typing debt unrelated to the touched boundaries.

## 5. Verification and Commit Policy

Every phase must:

1. add a regression that fails for the confirmed defect;
2. retain the failing command and expected failure in `progress.md`;
3. implement the minimum ownership fix;
4. pass focused regressions;
5. pass the complete suite in isolated state;
6. pass imports, compilation, dependency, static, diff, and applicable Docker checks;
7. append one `progress.md` record;
8. create one independent Git commit.

After Phase 8, an adversarial review must re-check every invariant from the original
architecture-hardening design and this follow-up. Every confirmed finding is fixed with
its own regression before deployment.

## 6. Deployment and Rollback

Production deployment retains the existing gate:

- push the reviewed local `master`;
- perform a fresh read-only preflight on SSH alias `rn`;
- stop `tg-downloader.service`;
- create a mode-`0700` timestamped backup;
- back up all three SQLite databases with `sqlite3.Connection.backup`;
- back up configuration, sessions, Web auth, and the pre-deploy commit;
- require every backup database integrity result to be `ok`;
- deploy only through `git pull --ff-only origin master`;
- install reviewed dependency changes;
- run import, compile, dependency, schema, integrity, Web, CSRF, Bot, queue, service, and
  journal checks;
- append exact production evidence and rollback steps to `progress.md`;
- commit and push the deployment record.

Rollback stops the service, preserves the failed deployment state, returns to the
recorded pre-deploy commit, restores only affected runtime artifacts, and repeats the
health and integrity checks.

## 7. Explicit Non-goals

- multi-process or horizontally scaled Web workers;
- an external queue, Redis, PostgreSQL, or a distributed lease;
- replacing Flask or Pyrogram;
- merging the three SQLite databases;
- changing channel-library batch snapshots or resource-delivery staging semantics;
- broad frontend redesign;
- global source formatting or historical type-error cleanup.

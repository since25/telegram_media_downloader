# First-Principles Architecture Remediation Plan

**Goal:** Repair the confirmed runtime-state, readiness, release, persistence, and
dependency-boundary defects; review the complete result adversarially; then deploy the
reviewed `master` through a backed-up, fast-forward-only production procedure.

**Architecture:** Preserve the current single-process Python 3.11 application, Pyrogram
adapter, Flask control plane, and three bounded SQLite stores. Tighten ownership and
truthfulness at the existing boundaries instead of replacing them with a new framework,
distributed queue, or database.

## Global constraints

- Keep Telegram commands, Web payloads, naming behavior, channel-library snapshots,
  resource staging, and existing database schemas compatible unless a phase explicitly
  proves that a compatible schema addition is required.
- Add a failing regression before every behavior correction.
- Do not hide confirmed defects behind retries, broad exception handling, lint
  suppression, or documentation.
- Append one `progress.md` entry per completed phase and create one independent commit.
- Do not push or deploy until the final adversarial review and all local gates pass.
- Do not expose configuration secrets, session files, authentication state, databases,
  logs, downloaded media, production paths containing secrets, or real user data.
- Production deployment requires a clean tracked worktree, idle queues, successful
  backups, database integrity checks, fast-forward-only code movement, and post-restart
  verification.

## Phase 1: Runtime state identity and owner-loop control

### Scope

- Give every process-local transfer fact the identity
  `(task_id, chat_id, message_id)`.
- Replace direct access to the live download-progress dictionary with synchronized
  command and snapshot APIs.
- Route pause/resume through the application owner loop.
- Refuse to report an active task as cancelled unless a live owner acknowledges
  cancellation or durable reconciliation proves that no work can still run.

### Success criteria

- Two concurrent tasks downloading the same message in the same chat retain independent
  progress, queue time, task time, display state, and cleanup.
- Concurrent Flask reads/clears and event-loop progress writes cannot mutate the same
  dictionary without synchronization.
- Pause/resume mutation executes on the owner-loop thread.
- An active persisted task without a live cancellation handle returns an explicit
  conflict instead of a false successful cancellation.

### Planned commit

`fix: unify runtime download state ownership`

## Phase 2: Truthful startup, readiness, and container health

### Scope

- Track process startup, ready, stopping, and failed states explicitly.
- Make Web readiness reflect the Telegram client and required runtime services.
- Give Docker a health contract that works when the optional Web console is disabled.
- Propagate fatal startup failures so the process exits non-zero.
- Treat required channel-service initialization failure as startup failure.

### Success criteria

- The readiness probe fails before startup completes and after shutdown starts.
- Container health does not depend on `enable_web`.
- Telegram or required service startup failure is observable as a failing process.
- No success log or readiness result is emitted for a partially started application.

### Planned commit

`fix: make runtime readiness truthful`

## Phase 3: Verified artifact publication and packaging contract

### Scope

- Gate Docker publication on unit, import, compile, dependency, static, and container
  contract checks in the same workflow dependency graph.
- Publish a commit-addressable image; promote `latest` only after verification.
- Make the Python package include the runtime `module` and `utils` packages, or remove
  unsupported installability claims.
- Add tests that reject an ungated release workflow and an incomplete wheel manifest.

### Success criteria

- A failed verification job makes image publication unreachable.
- Every published image can be mapped to an exact Git commit.
- A locally built wheel contains the modules imported by `media_downloader.py`.

### Planned commit

`ci: gate release artifacts on verification`

## Phase 4: Explicit durable task and configuration contracts

### Scope

- Define allowed task-status transitions, including retry and restart reconciliation.
- Return independent snapshots from every public task-store method.
- Prevent arbitrary callers from reviving terminal tasks without an explicit retry
  transition.
- Add a recoverable generation/journal contract for the paired configuration and
  application-data write.
- Validate all Web-editable configuration before changing active or configured state.

### Success criteria

- Invalid task transitions fail without changing memory or SQLite.
- Mutating any returned object cannot mutate store-owned state.
- A simulated interruption between the two YAML replacements is detected and recovered
  deterministically.
- Invalid date formats and malformed configuration are rejected before persistence.

### Planned commit

`refactor: enforce durable state contracts`

## Phase 5: Bootstrap and dependency-boundary cleanup

### Scope

- Introduce an explicit application/bootstrap factory.
- Stop constructing and installing the production event loop merely by importing the
  compatibility module.
- Replace dynamic `from media_downloader import ...` cycles in Web, Bot, and channel
  services with injected operation interfaces.
- Keep `media_downloader.py` as a compatibility facade without rewriting
  `sys.modules`.
- Expand the blocking static boundary to the repaired orchestration modules.

### Success criteria

- Importing the public module creates no event loop, executor, queue, database, auth
  file, or runtime service.
- Web, Bot, and channel-service modules do not dynamically import the CLI facade.
- CLI startup still loads configuration and starts the same supported services.
- The expanded mypy/Pylint boundary passes without new suppressions for repaired code.

### Planned commit

`refactor: make application bootstrap explicit`

## Phase 6: Complete adversarial review

### Review inventory

- Task/file lifecycle invariants and duplicate callbacks.
- Same-message concurrent transfers and cross-thread snapshots.
- Pause, cancellation, timeout, shutdown, and in-flight Web requests.
- Restart recovery, schema compatibility, SQLite busy handling, integrity, and modes.
- Readiness with Web enabled and disabled; partial startup and fatal failure.
- Authentication, CSRF, proxy-facing login limiting, sessions, and request bounds.
- Configuration interruption/recovery and restart-required settings.
- Wheel contents, dependency health, CI reachability, container build, non-root mounts,
  and health behavior.
- Import side effects and dependency cycles.

### Required gates

- Focused regressions and complete pytest suite.
- `pre-commit run --all-files`.
- Imports, compileall, `pip check`, mypy, Pylint, and `git diff --check`.
- SQLite schema/integrity/mode probes.
- Docker Compose render.
- Successful multi-platform CI image build before production deployment.

Any confirmed finding receives a failing regression and a corrective commit named:

`fix: address final first-principles review`

## Phase 7: Reviewed deployment

### Preflight and backup

- Push the reviewed `master`.
- Run a fresh read-only preflight through SSH alias `rn`.
- Require a clean tracked production worktree, healthy service, sufficient disk, and
  empty download, scan, retry, and resource-delivery queues.
- Stop `tg-downloader.service`.
- Create a timestamped mode-`0700` backup.
- Back up all three SQLite databases with `sqlite3.Connection.backup()` and require
  `PRAGMA integrity_check == 'ok'` on every backup.
- Back up configuration, data, sessions, Web authentication, and the pre-deploy commit.

### Deployment and verification

- Preserve production untracked files.
- Deploy only with `git pull --ff-only origin master`.
- Verify imports, compile, dependencies, schemas, integrity, permissions, and
  configuration before restart.
- Restart and verify systemd, journal, Telegram clients, Bots, Web login/session/CSRF,
  readiness, queues, and resource/channel services.
- Append exact evidence and rollback instructions to `progress.md`.

### Planned commit

`docs: record first-principles remediation deployment`

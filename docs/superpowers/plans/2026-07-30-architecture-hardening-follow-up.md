# Architecture Hardening Follow-up Implementation Plan

**Goal:** Repair the remaining runtime-ownership, persistence, configuration, authentication, shutdown, adapter, and container defects before production deployment.

**Architecture:** Preserve the current single-process application and mature SQLite subsystems. Introduce focused transfer-progress, configuration-persistence, Web-authentication, and Web-server boundaries; route live mutations through the asyncio owner loop; keep each phase independently testable and reversible.

**Tech Stack:** Python 3.11, asyncio, Flask/Werkzeug, SQLite, Pyrogram, pytest, Docker Compose, systemd.

## Global Constraints

- Preserve public Telegram commands, Web payloads, persisted channel/resource schemas, package naming, resource staging, and download ordering.
- Do not add multi-process workers, distributed queues, or a database replacement.
- Do not expose or commit configuration secrets, sessions, Web credentials, databases, logs, or downloaded media.
- Use test-first red-green cycles for every behavior change.
- Append `progress.md`; never rewrite its history.
- Complete each phase with focused checks, the full suite, and one independent commit.
- Do not deploy until the complete adversarial review is clean.

---

## Phase 5: Runtime Correctness and Command Ownership

### Task 5.1: Share transfer progress between callbacks and watchdogs

**Files:**
- Create: `module/transfer_progress.py`
- Modify: `module/download_transfer.py`
- Modify: `module/download_stat.py`
- Modify: `module/download_entry.py`
- Test: `tests/module/test_transfer_progress.py`
- Test: `tests/test_media_downloader.py`

**Interfaces:**
- Produces: `TransferKey = tuple[str, str, str]`.
- Produces: `transfer_key(node, message_id) -> TransferKey`.
- Produces: `TransferProgressTracker.start(key)`, `observe(key, downloaded_size)`, `downloaded_size(key)`, `last_progress_at(key)`, `mark_stalled(key)`, `consume_stalled(key)`, and `clear(key)`.
- `TransferRuntime` consumes one `progress_tracker` instead of three independent dictionaries.

- [x] **Step 1: Add failing tracker identity and isolation tests**

```python
def test_runtime_and_progress_callback_share_one_tracker():
    runtime = download_entry._build_transfer_runtime()
    assert runtime.progress_tracker is download_stat.download_progress_tracker


def test_same_message_id_in_two_chats_has_independent_progress():
    tracker = TransferProgressTracker(clock=lambda: 10.0)
    first = ("task-1", "-1001", "42")
    second = ("task-2", "-1002", "42")
    tracker.start(first)
    tracker.start(second)
    tracker.observe(first, 10)
    assert tracker.downloaded_size(first) == 10
    assert tracker.downloaded_size(second) == 0
```

- [x] **Step 2: Run the focused tests and retain RED evidence**

Run:

```bash
.venv/bin/python -m pytest -q \
  tests/module/test_transfer_progress.py \
  tests/test_media_downloader.py -k 'progress_tracker or same_message_id'
```

Expected: failure because the tracker module/interface does not exist and the runtime
still owns different dictionaries.

- [x] **Step 3: Implement the focused tracker**

```python
TransferKey = tuple[str, str, str]


def transfer_key(node, message_id) -> TransferKey:
    return (
        str(getattr(node, "task_id", "") or ""),
        str(getattr(node, "chat_id", "") or ""),
        str(message_id),
    )
```

The tracker stores monotonic last-progress time, last increasing byte count, and stalled
keys. `observe()` refreshes time only when bytes increase.

- [x] **Step 4: Route callback and watchdog through the same tracker**

`update_download_status()` computes the key and calls `observe()`. `transfer_media()` and
`watch_stall()` use the same key and tracker. Cleanup clears only that transfer key.

- [x] **Step 5: Verify focused and lifecycle regressions**

```bash
.venv/bin/python -m pytest -q \
  tests/module/test_transfer_progress.py \
  tests/module/test_download_lifecycle.py \
  tests/module/test_package_download.py \
  tests/test_media_downloader.py
```

Expected: all selected tests pass.

### Task 5.2: Reject open-but-stopped owner loops

**Files:**
- Modify: `module/web_commands.py`
- Modify: `tests/module/test_web_commands.py`
- Modify: `tests/module/test_web.py`

**Interfaces:**
- `submit_web_coroutine(loop, coroutine)` accepts only a running, open loop.
- Rejection closes the coroutine and raises `RuntimeError("application loop is not available")`.

- [x] **Step 1: Replace the incorrect stopped-loop success test with a failing rejection test**

```python
def test_submit_rejects_open_but_stopped_loop():
    loop = asyncio.new_event_loop()
    coroutine = AsyncMock()
    with pytest.raises(RuntimeError, match="not available"):
        submit_web_coroutine(loop, coroutine())
    loop.close()
```

- [x] **Step 2: Run the test and retain RED evidence**

```bash
.venv/bin/python -m pytest -q \
  tests/module/test_web_commands.py::test_submit_rejects_open_but_stopped_loop
```

Expected: the current implementation returns a completed Future instead of raising.

- [x] **Step 3: Implement the minimum rejection**

```python
if (
    loop is None
    or getattr(loop, "is_closed", lambda: False)()
    or not loop.is_running()
):
    coroutine.close()
    raise RuntimeError("application loop is not available")
```

- [x] **Step 4: Verify Web command and confirmation behavior**

```bash
.venv/bin/python -m pytest -q \
  tests/module/test_web_commands.py \
  tests/module/test_web.py \
  tests/test_web_prescan_retention.py
```

Expected: all selected tests pass and stopped-loop confirmation returns `503`.

### Task 5.3: Route ordinary Web cancellation through the owner loop

**Files:**
- Modify: `module/web.py`
- Modify: `tests/test_web_cancel_task.py`
- Modify: `tests/module/test_web.py`

**Interfaces:**
- Produces: `_cancel_web_task_owned(task_id, node, workflow_type) -> dict`.
- Flask submits it with `submit_web_coroutine()` and waits with `wait_for_web_command()`.

- [x] **Step 1: Add a failing thread-ownership cancellation test**

```python
def test_cancel_active_web_task_mutates_node_on_owner_loop(running_app):
    node = make_active_web_node("web-owned-cancel")
    response = client.post(
        "/api/tasks/web-owned-cancel/cancel",
        headers=csrf_headers(client),
    )
    assert response.status_code == 200
    assert node.cancel_thread_id == running_app.owner_thread_id
```

The fixture uses a real background owner loop and a `TaskNode` test double that records
the thread calling `stop_transmission()`.

- [x] **Step 2: Run the new test and retain RED evidence**

```bash
.venv/bin/python -m pytest -q \
  tests/test_web_cancel_task.py -k owner_loop
```

Expected: the recorded thread is the Flask request thread.

- [x] **Step 3: Implement owner-loop cancellation**

The owned coroutine stops the node, removes the scanning registry entry under its lock,
and applies the persistent cancelled transition. Waiting task removal remains
deterministic. Submission failure returns `503`; timeout returns `503` without cancelling
accepted owner work.

- [x] **Step 4: Verify cancel, prescan, and channel-library regressions**

```bash
.venv/bin/python -m pytest -q \
  tests/test_web_cancel_task.py \
  tests/test_web_prescan_retention.py \
  tests/module/test_web.py \
  tests/module/test_channel_library_web.py
```

Expected: all selected tests pass.

### Task 5.4: Preserve transient refetch failures as failures

**Files:**
- Modify: `module/download_transfer.py`
- Modify: `tests/module/test_package_download.py`
- Modify: `tests/test_media_downloader.py`

**Interfaces:**
- Confirmed `BadRequest`/`NotFound` keeps the existing skip result.
- Any other refetch exception returns `DownloadStatus.FailedDownload`.

- [x] **Step 1: Add a failing generic-refetch regression**

```python
async def test_unexpected_refetch_error_is_failed_not_skipped():
    async def fetch_message(_client, _message):
        raise ConnectionError("temporary")

    result = await transfer_media(...runtime_with(fetch_message=fetch_message))
    assert result == (DownloadStatus.FailedDownload, None)
    assert node.skip_not_found_download_task == 0
```

- [x] **Step 2: Run the regression and retain RED evidence**

```bash
.venv/bin/python -m pytest -q \
  tests/module/test_package_download.py -k unexpected_refetch
```

Expected: current code returns `SkipDownload`.

- [x] **Step 3: Implement the classification change**

Unexpected exceptions log the safe exception class and return `FailedDownload`; they do
not increment not-found counters or markers.

- [x] **Step 4: Run Phase 5 focused tests**

```bash
.venv/bin/python -m pytest -q \
  tests/module/test_transfer_progress.py \
  tests/module/test_web_commands.py \
  tests/test_web_cancel_task.py \
  tests/test_web_prescan_retention.py \
  tests/module/test_download_lifecycle.py \
  tests/module/test_package_download.py \
  tests/module/test_web.py \
  tests/test_media_downloader.py
```

- [x] **Step 5: Run full verification, append progress, and commit**

```bash
.venv/bin/python -m pytest -q
.venv/bin/python check_imports.py
.venv/bin/python -m compileall -q module tests
.venv/bin/python -m pip check
make style_check
git diff --check
git add module tests docs progress.md
git commit -m "fix: restore runtime ownership invariants"
```

---

## Phase 6: Persistent State and Configuration Ownership

### Task 6.1: Initialize the task store explicitly

**Files:**
- Modify: `module/task_state.py`
- Modify: `module/download_entry.py`
- Modify: `module/download_runtime.py`
- Test: `tests/module/test_task_state.py`
- Test: `tests/test_runtime_contract.py`

**Interfaces:**
- Produces: `initialize_task_store(storage_path=None, recover_interrupted=True) -> TaskStateStore`.
- Produces: `reset_task_store_for_tests(store=None)`.
- `get_task_store()` raises before application initialization unless a test explicitly installs a store.

- [x] Add a subprocess regression proving `import module.task_state` does not create or mutate a database.
- [x] Run it and retain RED evidence.
- [x] Replace import-time `_TASK_STORE = TaskStateStore(...)` with explicit initialization.
- [x] Initialize after configuration loading and before Web/channel/Bot/worker startup.
- [x] Verify restart recovery still runs once from the application lifecycle.

### Task 6.2: Return immutable task snapshots

**Files:**
- Modify: `module/task_state.py`
- Modify: `module/web.py`
- Modify: `module/channel_library_service.py`
- Test: `tests/module/test_task_state.py`
- Test: `tests/module/test_web.py`

**Interfaces:**
- `get_task()`, `tasks()`, and pagination readers return deep-copy snapshots.
- Produces: `update_workflow(task_id, **fields) -> Optional[TaskSnapshot]`.

- [x] Add a failing test proving mutation of a returned task/workflow/file does not alter stored state.
- [x] Add a failing concurrent serialization test that adds files while dashboard snapshots are read.
- [x] Implement snapshot reads and the focused workflow update command.
- [x] Replace direct `task.workflow.selected_count = ...` mutations with `update_workflow()`.
- [x] Verify channel reconciliation and Web task display regressions.

### Task 6.3: Harden the task database connection

**Files:**
- Modify: `module/task_state.py`
- Modify: `docs/web-control-console.md`
- Test: `tests/module/test_task_state.py`

**Interfaces:**
- SQLite connections use `timeout=5.0`, `PRAGMA busy_timeout=5000`, and WAL.
- POSIX database mode is `0600` after initialization.

- [x] Add failing permission and busy-timeout tests.
- [x] Implement the connection and permission parity.
- [x] Verify migration, rollback, recovery, and integrity tests.

### Task 6.4: Persist configuration atomically

**Files:**
- Create: `module/config_persistence.py`
- Modify: `module/app.py`
- Test: `tests/module/test_config_persistence.py`
- Test: `tests/module/test_app.py`

**Interfaces:**
- Produces: `atomic_write_yaml(path: Path, value, yaml_writer) -> None`.
- `Application.update_config()` holds one re-entrant lock and atomically replaces both files.

- [x] Add a failing test proving serialization failure leaves the previous file unchanged.
- [x] Add a failing concurrent-write test.
- [x] Implement owner-only temporary files, flush, `os.fsync()`, and `os.replace()`.
- [x] Route both configuration files through the helper.
- [x] Verify existing config compatibility tests.

### Task 6.5: Make Web settings activation explicit

**Files:**
- Modify: `module/web.py`
- Modify: `module/app.py`
- Modify: `module/channel_library_service.py`
- Modify: `module/templates/index.html`
- Modify: `docs/web-control-console.md`
- Test: `tests/module/test_web.py`

**Interfaces:**
- Produces: `SettingsApplyResult(active_settings, configured_settings, restart_fields)`.
- Produces: `_apply_settings_owned(app, payload)`.
- Restart-only fields are persisted without mutating active runtime dependencies.

- [x] Add failing tests for `save_path`, worker count, transmission concurrency, Web binding, and adapter replacement.
- [x] Prove `save_path` no longer diverges from the active disk-admission path.
- [x] Submit settings application through the owner-loop command boundary.
- [x] Return configured and active values plus exact restart fields.
- [x] Update the UI to label pending-restart values.

### Phase 6 verification and commit

- [x] Run task-store, settings, channel restart, config persistence, and full tests.
- [x] Run imports, compilation, dependency, static, database integrity, and diff checks.
- [x] Append `progress.md`.
- [x] Commit as `refactor: make state and config ownership explicit`.

---

## Phase 7: Authentication, Adapter, and Shutdown Lifecycle

### Task 7.1: Store a Web password verifier and migrate plaintext auth

**Files:**
- Create: `module/web_auth.py`
- Modify: `module/web.py`
- Modify: `docs/web-control-console.md`
- Modify: `README.md`
- Modify: `README_CN.md`
- Test: `tests/module/test_web_auth.py`
- Test: `tests/module/test_web.py`

**Interfaces:**
- Produces: `WebAuthState.load_or_create(path, configured_password)`.
- Produces: `verify_password(candidate) -> bool`.
- Existing plaintext password migrates to a Werkzeug password hash without changing the accepted credential.
- Generated bootstrap plaintext is removed after the first successful login.

- [ ] Add failing migration, bootstrap-removal, wrong-password, and file-mode tests.
- [ ] Implement password hashing and atomic auth-file persistence.
- [ ] Preserve the session secret and current login response contract.
- [ ] Document credential recovery and rollback.

### Task 7.2: Bound login attempts and session lifetime

**Files:**
- Modify: `module/web_auth.py`
- Modify: `module/web.py`
- Modify: `module/app.py`
- Modify: `config.example.yaml`
- Test: `tests/module/test_web_auth.py`
- Test: `tests/module/test_web.py`

**Interfaces:**
- Produces: `LoginAttemptLimiter`.
- Five failures in five minutes trigger a bounded retry delay.
- `web_secure_cookie` is explicit; production enables it.
- Session lifetime is twelve hours and `SESSION_REFRESH_EACH_REQUEST` is false.

- [ ] Add failing threshold, expiry, success-reset, cookie, and session tests.
- [ ] Implement the limiter with monotonic time.
- [ ] Apply safe generic error responses and `Retry-After`.
- [ ] Set `MAX_CONTENT_LENGTH` to one MiB.

### Task 7.3: Correct and validate optional Aligo execution

**Files:**
- Modify: `module/app.py`
- Modify: `module/cloud_drive.py`
- Modify: `module/web.py`
- Modify: `README.md`
- Modify: `README_CN.md`
- Test: `tests/module/test_cloud_drive.py`
- Test: `tests/module/test_app.py`

**Interfaces:**
- Blocking Aligo upload is passed to the executor as a callable created with `functools.partial`.
- Selecting Aligo is restart-required.
- Startup reports a clear configuration error when the optional package is unavailable.

- [ ] Add a failing executor-callable regression reproducing `'bool' object is not callable`.
- [ ] Add a failing missing-optional-dependency startup test.
- [ ] Implement the callable boundary and validation.
- [ ] Document the optional dependency contract without silently installing an unreviewed package.

### Task 7.4: Own the Web server lifecycle

**Files:**
- Create: `module/web_server.py`
- Modify: `module/web.py`
- Modify: `module/download_runtime.py`
- Test: `tests/module/test_web_server.py`
- Test: `tests/module/test_app.py`

**Interfaces:**
- Produces: `WebServer.start()` and `WebServer.stop(timeout=...)`.
- Uses one owned background thread and `werkzeug.serving.make_server`.
- Start failure is observable; stop shuts down and joins the thread.

- [ ] Add failing start, stop, port-conflict, and double-stop tests.
- [ ] Replace daemon `Flask.run()` threads with the owned server.
- [ ] Wire server stop before event-loop shutdown.

### Task 7.5: Await complete process shutdown

**Files:**
- Modify: `module/download_runtime.py`
- Modify: `module/download_entry.py`
- Modify: `module/app.py`
- Test: `tests/module/test_app.py`
- Test: `tests/module/test_bot_manager.py`

**Interfaces:**
- SIGINT and SIGTERM set one shutdown request.
- Worker tasks are cancelled and awaited with `asyncio.gather(..., return_exceptions=True)`.
- The custom executor and event loop are closed exactly once.

- [ ] Add failing tests for worker finalizers, SIGTERM, executor shutdown, and loop closure.
- [ ] Implement one idempotent shutdown sequence.
- [ ] Preserve config update and service stop ordering.

### Phase 7 verification and commit

- [ ] Run Web auth, login, CloudDrive, server, Bot, lifecycle, and full tests.
- [ ] Run imports, compilation, dependency, static, security-contract, and diff checks.
- [ ] Append `progress.md`.
- [ ] Commit as `security: harden web auth and shutdown`.

---

## Phase 8: Bounded Module, Static, and Container Cleanup

### Task 8.1: Enforce the new module boundaries

**Files:**
- Modify: `Makefile`
- Modify: `.pre-commit-config.yaml`
- Modify: `mypy.ini`
- Modify: `tests/test_runtime_contract.py`

**Interfaces:**
- Blocking mypy/Pylint coverage includes `transfer_progress.py`, `config_persistence.py`,
  `web_auth.py`, `web_server.py`, and touched ownership call sites.

- [ ] Add a failing runtime contract for the expanded boundary.
- [ ] Fix only errors in files changed by Phases 5-7.
- [ ] Keep historical unrelated errors documented rather than suppressed.

### Task 8.2: Add a minimal health contract

**Files:**
- Modify: `module/web.py`
- Modify: `Dockerfile`
- Modify: `docker-compose.yaml`
- Test: `tests/test_web_system_api.py`
- Test: `tests/test_docker_contract.py`

**Interfaces:**
- `GET /healthz` returns only process readiness and no secrets.
- Docker health check calls the local endpoint.

- [ ] Add failing endpoint and Docker contract tests.
- [ ] Implement the bounded response and health command.
- [ ] Verify login-protected operational APIs remain protected.

### Task 8.3: Finish reproducible and least-privilege container inputs

**Files:**
- Modify: `Dockerfile`
- Modify: `docker-compose.yaml`
- Modify: `requirements.txt`
- Modify: `README.md`
- Modify: `README_CN.md`
- Test: `tests/test_docker_contract.py`
- Test: `tests/test_dependency_contract.py`

**Interfaces:**
- Runtime base input is pinned immutably.
- The runtime user and writable directories have an explicit migration contract.
- Existing host state is never silently made inaccessible.

- [ ] Add failing mutable-base and root-runtime contracts.
- [ ] Resolve and record the reviewed base digest.
- [ ] Add the least-privilege user only with verified ownership instructions.
- [ ] Build and smoke-test the image when a Docker daemon is available; otherwise keep
  the environment gap explicit and require CI build evidence before deployment.

### Phase 8 verification and commit

- [ ] Run runtime, Docker, dependency, health, static, and full tests.
- [ ] Run all pre-commit hooks, imports, compilation, dependency, Compose, build, and diff checks.
- [ ] Append `progress.md`.
- [ ] Commit as `chore: tighten module and container boundaries`.

---

## Complete Adversarial Review

- [ ] Re-read both architecture designs and map every invariant to current source and a
  verification command.
- [ ] Reproduce the original stopped-loop, cross-thread cancellation, split-heartbeat,
  generic-refetch, import-side-effect, settings-divergence, plaintext-auth, Aligo,
  abandoned-shutdown, and container findings against the repaired code.
- [ ] Inventory every mutating Web route for login and CSRF.
- [ ] Inventory every Flask-to-owner-loop mutation.
- [ ] Inventory every task/file state write and direct snapshot mutation.
- [ ] Exercise restart recovery, SQLite migration, rollback, busy handling, permissions,
  and `PRAGMA integrity_check`.
- [ ] Exercise same-message-ID concurrent transfers and a simulated transfer longer than
  the stall threshold with continuing progress.
- [ ] Run the complete suite in isolated state.
- [ ] Run imports, compilation, `pip check`, mypy, Pylint, all pre-commit hooks, Compose,
  Docker build/smoke, and `git diff --check`.
- [ ] Request an independent adversarial review focused on correctness, security,
  concurrency, persistence, compatibility, shutdown, and missing tests.
- [ ] Fix every confirmed finding with a regression, rerun the complete gate, append
  `progress.md`, and commit as `fix: address follow-up adversarial review`.

## Production Deployment

- [ ] Push the reviewed `master`.
- [ ] Re-run read-only production preflight on `rn`.
- [ ] Require clean tracked state, healthy service, sufficient disk, and no active or
  queued download, scan, retry, or resource-delivery work.
- [ ] Stop `tg-downloader.service`.
- [ ] Create a mode-`0700` timestamped backup containing the pre-deploy commit,
  configuration, Web auth, sessions, and SQLite API backups of all three databases.
- [ ] Require every backup database integrity result to be `ok`.
- [ ] Fast-forward with `git pull --ff-only origin master`.
- [ ] Install reviewed dependency changes and apply only documented configuration/file
  permission migration.
- [ ] Run imports, compilation, dependency checks, schemas, and integrity before restart.
- [ ] Restart and verify service state, restart count, exit status, journal, Web login,
  secure session, CSRF rejection/acceptance, task APIs, management Bot, resource Bot,
  queues, database integrity, and health endpoint.
- [ ] Append exact backup, commit, migration, test, service, and rollback evidence to
  `progress.md`.
- [ ] Commit and push as `docs: record architecture hardening deployment`.

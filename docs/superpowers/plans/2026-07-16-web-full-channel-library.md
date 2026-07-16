# Web Full Channel Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent Web channel library that low-rate scans all visible channel/supergroup history, survives restarts, exposes stable package filtering/selection, and downloads selected packages through the existing serial recommended-C workflow.

**Architecture:** A new `channel_library.sqlite3` stores channels, scan checkpoints, media metadata, package revisions, selections, failures, and download outbox records. Scanner, indexer, download-priority Telegram gate, and outbox dispatcher run only on `Application.loop`; Flask writes commands and reads paginated state. Existing package planning and media download remain the source of truth, extended only with package lifecycle callbacks needed for reliable package status.

**Tech Stack:** Python 3, asyncio, Pyrogram, Flask/flask-login, sqlite3 WAL, ruamel.yaml, existing inline HTML/CSS/JavaScript Web console, pytest/unittest.

**Design spec:** `docs/superpowers/specs/2026-07-16-web-full-channel-library-design.md`

## Global Constraints

- Do not add third-party dependencies.
- Full scan: exactly 50 message IDs per batch and random delay 4-6 seconds. Incremental/repair: 50 IDs and delay 1-2 seconds.
- Config floors/caps: full delay >= 2 seconds, incremental delay >= 0.5 seconds, batch size <= 100.
- Only one channel scan runs globally; scan/client work runs on `Application.loop`, never the Flask thread or a second loop.
- Telegram downloads/previews have priority through one `TelegramActivityGate`; cloud-only upload does not block scans.
- `channel_library.sqlite3` is separate from `web_tasks.sqlite3`, uses WAL/foreign keys/short transactions, and is mode `0600`.
- Cross-database dispatch uses an idempotent outbox/saga and deterministic task IDs; never claim cross-SQLite atomicity.
- Package boundaries, caption inheritance, supported media, size summaries, recommended-C naming, and serial downloads reuse existing logic.
- A package cannot become stable because a 500-item planning window was exhausted.
- All new mutating APIs require login plus `X-CSRF-Token`; render all user/Telegram strings with existing escaping.
- Growing package lists use keyset cursor `(start_message_id, id)` and return `library_revision`; offset paging is forbidden.
- Do not refactor unrelated bot, comment, ordinary package, limited Prescan, upload, or config behavior.
- Use TDD. Every task ends in an independent commit. Do not push until Task 12.

## File Structure

- Create `module/channel_library_store.py`: schema, transactions, state, queries, selections, repair targets, revisions, and outbox.
- Create `module/channel_library_workflow.py`: persisted message adapter and package indexing.
- Create `module/telegram_activity.py`: download-priority gate.
- Create `module/channel_library_service.py`: app-loop scheduler/scanner/recovery/outbox/download bridge.
- Modify `module/app.py`, `media_downloader.py`, `module/web.py`, `module/templates/index.html`, `module/static/css/index.css`.
- Modify `config.example.yaml`, `README_CN.md`, `docs/web-control-console.md`, and `progress.md`.
- Add focused tests listed by task.

---

### Task 1: Validated Configuration And SQLite Foundation

**Files:**
- Create: `module/channel_library_store.py`
- Modify: `module/app.py`
- Modify: `config.example.yaml`
- Test: `tests/module/test_channel_library_store.py`
- Test: `tests/module/test_app.py`

**Interfaces:**
- Produces `ChannelLibraryConfig`, `ChannelLibraryStore`, state constants, `initialize() -> None`, `create_or_get_library(chat_id: int, chat_type: str, username: Optional[str], title: str, source_link: str) -> tuple[dict, bool]`, and `get_library(library_id: int) -> Optional[dict]`.
- Adds `Application.channel_library_config` and `Application.channel_library_service`.

- [ ] **Step 1: Write failing config and schema tests**

```python
def test_store_initializes_secure_wal_schema(tmp_path):
    store = ChannelLibraryStore(tmp_path / "channel_library.sqlite3")
    store.initialize()
    assert (store.path.stat().st_mode & 0o777) == 0o600
    with store.connect() as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    assert REQUIRED_TABLES <= tables

def test_library_is_unique_by_chat_id(tmp_path):
    store = ChannelLibraryStore(tmp_path / "library.sqlite3")
    store.initialize()
    first, created = store.create_or_get_library(-1001, "channel", "demo", "Demo", "https://t.me/demo/1")
    second, created_again = store.create_or_get_library(-1001, "channel", "demo", "Renamed", "https://t.me/demo/9")
    assert created is True and created_again is False
    assert second["id"] == first["id"] and second["title"] == "Renamed"
```

Add `test_channel_library_config_is_clamped` in `tests/module/test_app.py` and assert 999 batch becomes 100, zero full delay becomes 2.0, and zero incremental delay becomes 0.5.

- [ ] **Step 2: Run the tests and confirm import/config failures**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_app.py::test_channel_library_config_is_clamped -q
```

Expected: missing module/config attributes.

- [ ] **Step 3: Implement config and complete schema v1**

```python
@dataclass(frozen=True)
class ChannelLibraryConfig:
    full_scan_batch_size: int = 50
    full_scan_delay_min_sec: float = 4.0
    full_scan_delay_max_sec: float = 6.0
    incremental_scan_batch_size: int = 50
    incremental_scan_delay_min_sec: float = 1.0
    incremental_scan_delay_max_sec: float = 2.0
    transient_retry_delays_sec: Sequence[float] = (5.0, 15.0, 45.0)

    @classmethod
    def from_mapping(cls, raw: Optional[dict]) -> "ChannelLibraryConfig":
        raw = raw or {}
        full_min = max(float(raw.get("full_scan_delay_min_sec", 4)), 2.0)
        inc_min = max(float(raw.get("incremental_scan_delay_min_sec", 1)), 0.5)
        return cls(
            full_scan_batch_size=min(max(int(raw.get("full_scan_batch_size", 50)), 1), 100),
            full_scan_delay_min_sec=full_min,
            full_scan_delay_max_sec=max(float(raw.get("full_scan_delay_max_sec", 6)), full_min),
            incremental_scan_batch_size=min(max(int(raw.get("incremental_scan_batch_size", 50)), 1), 100),
            incremental_scan_delay_min_sec=inc_min,
            incremental_scan_delay_max_sec=max(float(raw.get("incremental_scan_delay_max_sec", 2)), inc_min),
            transient_retry_delays_sec=tuple(float(v) for v in raw.get("transient_retry_delays_sec", (5, 15, 45))),
        )
```

Implement every Spec section 5 table and index. `connect()` sets row factory, foreign keys, and 5000 ms busy timeout. `initialize()` creates schema v1, WAL, and calls `os.chmod(path, 0o600)`. Use parameterized SQL.

Load config in `Application.assign_config`; add the exact YAML defaults to `config.example.yaml`, but not `/api/settings`.

- [ ] **Step 4: Run focused tests**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_app.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add module/channel_library_store.py module/app.py config.example.yaml tests/module/test_channel_library_store.py tests/module/test_app.py
git commit -m "feat: add channel library storage foundation"
```

---

### Task 2: Scan State, Checkpoints, Failures, And Restart Recovery

**Files:**
- Modify: `module/channel_library_store.py`
- Test: `tests/module/test_channel_library_store.py`

**Interfaces:**
- Produces `create_scan_job`, `claim_next_job`, `transition_job`, `commit_fetched_batch`, `commit_indexed_revision`, `recover_interrupted_jobs`.
- Produces `record_failed_range`, `create_repair_job`, `list_repair_targets`, `resolve_repair_target`.

- [ ] **Step 1: Add failing atomicity/state tests**

```python
def test_fetched_batch_and_checkpoint_commit_together(store):
    job = make_full_job(store, snapshot_max_id=100)
    store.commit_fetched_batch(job["id"], [media_row(50)], end_id=50)
    assert store.get_job(job["id"])["fetched_through_message_id"] == 50
    assert store.get_media(job["library_id"], 50) is not None

def test_recovery_respects_rate_limit_deadline(store):
    job = make_job(store, status="waiting_rate_limit", wait_until=200.0)
    store.recover_interrupted_jobs(now=100.0)
    assert store.get_job(job["id"])["status"] == "waiting_rate_limit"
    store.recover_interrupted_jobs(now=201.0)
    assert store.get_job(job["id"])["status"] == "queued"
```

Also test independent fetch/index watermarks, illegal transitions, stopped-job uniqueness, failed-range merge, multiple repair cursors, and refusing ready/partial before both watermarks reach snapshot.

- [ ] **Step 2: Run and observe missing-method failures**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_store.py -q
```

- [ ] **Step 3: Implement the exact transition table and transactional methods**

```python
ALLOWED_SCAN_TRANSITIONS = {
    "queued": {"running", "paused_user", "stopped", "failed"},
    "running": {"queued", "paused_user", "auto_paused_download", "waiting_rate_limit", "stopped", "completed", "partial", "failed"},
    "auto_paused_download": {"queued", "paused_user", "stopped", "failed"},
    "waiting_rate_limit": {"queued", "paused_user", "stopped", "failed"},
    "paused_user": {"queued", "stopped"},
    "stopped": {"queued"},
    "completed": set(), "partial": set(), "failed": set(),
}
```

Media rows and fetch watermark commit together. Derived packages and index watermark/revision commit together. Recovery follows Spec 6.2 and preserves future `wait_until`.

- [ ] **Step 4: Run focused regressions**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_task_state.py -q
```

- [ ] **Step 5: Commit**

```bash
git add module/channel_library_store.py tests/module/test_channel_library_store.py
git commit -m "feat: persist channel scan recovery state"
```

---

### Task 3: Persisted Message Adapter And Revisioned Package Indexer

**Files:**
- Create: `module/channel_library_workflow.py`
- Modify: `module/channel_library_store.py`
- Test: `tests/module/test_channel_library_workflow.py`

**Interfaces:**
- Produces `MediaDTO`, `PersistedMessageAdapter`, `extract_media_row(message: Any) -> Optional[dict]`, and `ChannelPackageIndexer.index_through(store: ChannelLibraryStore, job: Mapping[str, Any], through_message_id: int) -> IndexResult`.
- Consumes existing `plan_message_package`, `plan_message_package_sequence`, and `media_payload_for_message`.

- [ ] **Step 1: Add adapter golden and boundary tests**

```python
def test_persisted_adapter_matches_real_message_plan():
    real = [fake_video(1, "Course 01", size=10), fake_video(2, None, size=20), fake_video(3, "Course 02", size=30)]
    adapted = [PersistedMessageAdapter.from_row(extract_media_row(item)) for item in real]
    expected = plan_message_package_sequence(real, 1, following_package_count=2, max_scan_count=4)
    actual = plan_message_package_sequence(adapted, 1, following_package_count=2, max_scan_count=4)
    assert summarize_sequence(actual) == summarize_sequence(expected)
```

Add tests for albums, media fields, cross-50 boundary, >500 same-caption media, provisional tail at snapshot end, failure closure, split/merge supersede, selection invalidation, and completed revision becoming outdated.

- [ ] **Step 2: Run and observe import failure**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_workflow.py -q
```

- [ ] **Step 3: Implement the exact adapter shape**

```python
@dataclass
class MediaDTO:
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    duration: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

class PersistedMessageAdapter:
    def __init__(self, row: Mapping[str, Any]):
        self.id = int(row["message_id"])
        self.empty = False
        self.caption = row.get("caption")
        self.media_group_id = row.get("media_group_id")
        self.date = parse_utc_datetime(row.get("message_date"))
        media_type = str(row["media_type"])
        self.media = media_type
        for name in SUPPORTED_MEDIA_TYPES:
            setattr(self, name, None)
        setattr(self, media_type, MediaDTO(
            file_name=row.get("file_name"), file_size=row.get("file_size"),
            mime_type=row.get("mime_type"), duration=row.get("duration"),
            width=row.get("width"), height=row.get("height"),
        ))

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "PersistedMessageAdapter":
        return cls(row)
```

Fingerprint deterministic JSON of package-affecting fields with SHA-256; return `None` for non-media.

- [ ] **Step 4: Implement tail indexing and revision semantics**

Load from reindex anchor, pass `max_scan_count=len(messages)+1`, persist only packages before a real next boundary, and stabilize final tail only at snapshot end with no affecting failure. UPSERT same-start identities, mark removed identities superseded, bind items to library/package/message, invalidate changed selections, and mark successful old revisions outdated.

- [ ] **Step 5: Run planner regressions**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_workflow.py tests/module/test_comment_workflow.py tests/module/test_prescan_workflow.py -q
```

- [ ] **Step 6: Commit**

```bash
git add module/channel_library_workflow.py module/channel_library_store.py tests/module/test_channel_library_workflow.py
git commit -m "feat: index revisioned channel packages"
```

---

### Task 4: Download-Priority Telegram Activity Gate

**Files:**
- Create: `module/telegram_activity.py`
- Modify: `media_downloader.py`
- Modify: `module/web.py`
- Test: `tests/module/test_telegram_activity.py`
- Test: `tests/test_media_downloader.py`

**Interfaces:**
- Produces `TelegramActivityGate.acquire_download() -> DownloadIntent`, `acquire_scan() -> ActivityPermit`, `download_permit()`, `scan_permit()`, `wait_until_idle()`, and `get_telegram_activity_gate()`.

- [ ] **Step 1: Add deterministic race tests**

```python
@pytest.mark.asyncio
async def test_waiting_download_blocks_next_scan_batch():
    gate = TelegramActivityGate()
    first_scan = await gate.acquire_scan()
    waiting_download = asyncio.create_task(gate.acquire_download())
    await asyncio.sleep(0)
    second_scan = asyncio.create_task(gate.acquire_scan())
    first_scan.release()
    download = await asyncio.wait_for(waiting_download, 1)
    assert not second_scan.done()
    download.release()
    scan = await asyncio.wait_for(second_scan, 1)
    scan.release()
```

Also test multiple downloads coexist, only one scan, cancellation release, and no cloud-upload gate use.

- [ ] **Step 2: Run and observe import failure**

```bash
.venv/bin/python -m pytest tests/module/test_telegram_activity.py -q
```

- [ ] **Step 3: Implement a condition-based priority gate**

Use one asyncio `Condition`, `waiting_downloads`, `active_downloads`, and `scan_active`. `register_download_intent()` increments waiting before enqueue and returns a `DownloadIntent`; `intent.activate()` waits for an in-flight scan, moves waiting to active, and returns the worker permit; `intent.cancel()` releases an item removed before work. Scan waits while a download is waiting/active. Permit release notifies all. Assert one owner loop after first acquire.

- [ ] **Step 4: Integrate existing Telegram work paths**

Register high-priority intent before media enqueue, add the intent token to the asyncio queue item, call `intent.activate()` in the worker, and release it in the worker `finally`. Every enqueue-failure/cancel path calls `intent.cancel()` so counters cannot leak. Wrap Web package/comment/Prescan Telegram preview reads. Do not wrap rclone upload. Use a helper such as:

```python
async def run_with_download_permit(awaitable_factory):
    async with get_telegram_activity_gate().download_permit():
        return await awaitable_factory()
```

- [ ] **Step 5: Run gate/downloader regressions**

```bash
.venv/bin/python -m pytest tests/module/test_telegram_activity.py tests/test_media_downloader.py tests/module/test_web.py -q
```

- [ ] **Step 6: Commit**

```bash
git add module/telegram_activity.py media_downloader.py module/web.py tests/module/test_telegram_activity.py tests/test_media_downloader.py
git commit -m "feat: prioritize telegram downloads over scans"
```

---

### Task 5: Full Scan Scheduler, Throttling, And Recovery

**Files:**
- Create: `module/channel_library_service.py`
- Modify: `module/channel_library_store.py`
- Test: `tests/module/test_channel_library_service.py`

**Interfaces:**
- Produces `ChannelLibraryService(app, client, store, config, sleep, random_uniform)`.
- Produces async `start()`, `stop()`, `wake()`, `_run_scheduler()`, `_run_job(job)`.
- Produces async `resolve_and_create_library(link: str) -> SubmitLibraryResult`, thread-safe `submit_library_link_threadsafe(link: str) -> concurrent.futures.Future`, and persisted commands `pause`, `resume`, and `stop_job`.

- [ ] **Step 1: Add fake-client full scan tests**

```python
@pytest.mark.asyncio
async def test_full_scan_uses_50_id_batches_and_persists_progress(service, fake_client):
    fake_client.latest_message_id = 150
    job = service.store.create_scan_job(1, "full", 1, 150)
    await service._run_job(job)
    assert fake_client.requested_ids == [
        list(range(1, 51)), list(range(51, 101)), list(range(101, 151))
    ]
    assert service.store.get_library(1)["fetched_through_message_id"] == 150
    assert service.sleep.delays == [pytest.approx(5.0), pytest.approx(5.0)]
```

Also test immutable snapshot max, resume from 51, one global job, pause/stop at batch boundary, gate auto-pause, retries `[5,15,45]`, persisted FloodWait, permanent permission error, SQLite failure not advancing checkpoint, and injected no-op sleep.

- [ ] **Step 2: Run and observe import failure**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_service.py -q
```

- [ ] **Step 3: Implement event-loop-owned service lifecycle**

`start()` records the owner loop, initializes/recover store, creates one scheduler task, and is idempotent. `stop()` signals, wakes, cancels only after request/transaction boundary, and awaits. Resolve links with `build_message_package_workflow_request`; accept only channel/supergroup. `submit_library_link_threadsafe` calls `asyncio.run_coroutine_threadsafe(self.resolve_and_create_library(link), self.owner_loop)` so `get_chat` and latest-message lookup run on `Application.loop` under a download-priority Telegram permit. Flask may wait on the future for 30 seconds but never calls Pyrogram. Duplicate chat IDs return the existing library. New libraries create a full queued job with a latest-message snapshot.

- [ ] **Step 4: Implement batch execution with gate and dual checkpoints**

```python
batch_ids = list(range(
    job["next_message_id"],
    min(job["next_message_id"] + batch_size, job["snapshot_max_message_id"] + 1),
))
async with gate.scan_permit():
    messages = await client.get_messages(job["chat_id"], batch_ids)
rows = [row for item in normalize_messages(messages) if (row := extract_media_row(item))]
store.commit_fetched_batch(job["id"], rows, end_id=batch_ids[-1])
indexer.index_through(store, store.get_job(job["id"]), batch_ids[-1])
```

Check control/download intent before each batch. Delay only between successful non-final batches. Errors follow Spec 6.3.

- [ ] **Step 5: Run focused tests**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_store.py tests/module/test_channel_library_workflow.py tests/module/test_telegram_activity.py -q
```

- [ ] **Step 6: Commit**

```bash
git add module/channel_library_service.py module/channel_library_store.py tests/module/test_channel_library_service.py
git commit -m "feat: add recoverable low-rate channel scans"
```

---

### Task 6: Incremental Scan And Failed-Range Repair

**Files:**
- Modify: `module/channel_library_service.py`
- Modify: `module/channel_library_store.py`
- Modify: `module/channel_library_workflow.py`
- Test: `tests/module/test_channel_library_service.py`
- Test: `tests/module/test_channel_library_workflow.py`

**Interfaces:**
- Produces `queue_incremental(library_id)`, `queue_repair(library_id, failure_ids=None)`, and `retry_failed_job(library_id, failed_job_id)`.
- Uses persistent `channel_scan_repair_targets` and one shared range runner.

- [ ] **Step 1: Add failing incremental/repair tests**

Cover incremental start at `fetched_through + 1`, a new immutable max, 1-2 second delay, old tail extension/outdated status, new-caption new package, incomplete-full conflict, default-all and selected repair targets, restart cursors, complete uncertainty closure, and delayed reindex publication while a package revision is downloading.

- [ ] **Step 2: Run and observe missing-command failures**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_workflow.py -q
```

- [ ] **Step 3: Implement shared range runner and commands**

```python
async def _scan_range(
    self,
    job: dict,
    start_id: int,
    end_id: int,
    delay_range: tuple[float, float],
) -> None:
    next_id = start_id
    while next_id <= end_id:
        current = self.store.get_job(job["id"])
        self._ensure_runnable(current)
        batch_ids = list(range(next_id, min(next_id + self._batch_size(current), end_id + 1)))
        await self._fetch_commit_and_index(current, batch_ids)
        next_id = batch_ids[-1] + 1
        if next_id <= end_id:
            await self.sleep(self.random_uniform(*delay_range))
```

Full, incremental, and each repair target call this method. `_fetch_commit_and_index` is the Task 5 gate/retry/FloodWait/checkpoint path. Incremental reindex anchor is last stable package start. Repair uses the persisted failure anchor and closure; do not duplicate the batch implementation in three workflows.

- [ ] **Step 4: Run focused tests**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_workflow.py tests/module/test_channel_library_store.py -q
```

- [ ] **Step 5: Commit**

```bash
git add module/channel_library_service.py module/channel_library_store.py module/channel_library_workflow.py tests/module/test_channel_library_service.py tests/module/test_channel_library_workflow.py
git commit -m "feat: add incremental and repair scans"
```

---

### Task 7: Filtered Queries, Keyset Pagination, And Persistent Selection

**Files:**
- Modify: `module/channel_library_store.py`
- Test: `tests/module/test_channel_library_queries.py`

**Interfaces:**
- Produces `PackageFilter`, `list_libraries`, `list_packages`, `list_package_items`.
- Produces `set_package_selected`, `select_filtered`, `clear_selection`, `selection_summary`.

- [ ] **Step 1: Add exact filter/pagination tests**

Cover normalized title substring, UTC `[from,to)` dates, intersecting message range, inclusive counts, unknown-size behavior, outdated status, max size 200, and insertion during keyset paging.

```python
first = store.list_packages(library_id, PackageFilter(), cursor=None, limit=2)
store.insert_test_package(library_id, start_message_id=999)
second = store.list_packages(library_id, PackageFilter(), cursor=first.next_cursor, limit=2)
assert not ({item["id"] for item in first.items} & {item["id"] for item in second.items})
assert second.library_revision > first.library_revision
```

Test select-filtered across all pages, exclusion of non-stable packages, reload persistence, and revision invalidation reason.

- [ ] **Step 2: Run and observe missing query APIs**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_queries.py -q
```

- [ ] **Step 3: Implement allow-listed SQL and opaque cursor**

Encode cursor as URL-safe base64 JSON with integer `start_message_id` and `id`. Reject malformed input. Build predicates from fixed fields/operators only. `select_filtered` performs one parameterized SQLite INSERT-SELECT using the same predicate and returns selected/skipped counts in one transaction.

- [ ] **Step 4: Run focused tests**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_queries.py tests/module/test_channel_library_store.py -q
```

- [ ] **Step 5: Commit**

```bash
git add module/channel_library_store.py tests/module/test_channel_library_queries.py
git commit -m "feat: query and select channel packages"
```

---

### Task 8: Idempotent Download Outbox And Per-Package Lifecycle

**Files:**
- Modify: `media_downloader.py`
- Modify: `module/channel_library_service.py`
- Modify: `module/channel_library_store.py`
- Modify: `module/download_stat.py`
- Test: `tests/test_channel_library_download.py`
- Test: `tests/test_media_downloader.py`
- Test: `tests/module/test_task_state.py`

**Interfaces:**
- Produces `create_download_batch`, `dispatch_pending_batches`, `reconcile_download_batches`.
- Extends `download_prescan_packages(packages: Sequence[PrescanPackage], channel: str, parent_node: TaskNode, selected_package_ids: AbstractSet[int], on_package_started: Optional[PackageStartedCallback] = None, on_package_finished: Optional[PackageFinishedCallback] = None, manage_parent_lifecycle: bool = True) -> list[PackageDownloadResult]`.

- [ ] **Step 1: Add failure-window and lifecycle tests**

Test outbox crashes before channel commit, after channel commit/before Web task, and after Web task/before dispatched mark. Restart must yield one batch and task. Add real TaskStateStore multi-package coverage: parent remains active after package one, callback message IDs are package-scoped, and completion occurs once after final package.

Test not-found/failure/upload_failed, acceptable complete-file skip, cancel semantics, and historical-success duplicate protection after a failed redownload.

- [ ] **Step 2: Run and observe outbox/callback failures**

```bash
.venv/bin/python -m pytest tests/test_channel_library_download.py tests/test_media_downloader.py tests/module/test_task_state.py -q
```

- [ ] **Step 3: Extend serial package download compatibly**

Existing callers retain default behavior. The outer function manages parent lifecycle once; inner per-package helper must not remove/complete the parent. Invoke optional callbacks and return per-message results:

```python
if on_package_started:
    await maybe_await(on_package_started(attempt_id, package_snapshot))
result = await download_one_prepared_package(
    package, parent_node, manage_parent_lifecycle=False
)
if on_package_finished:
    await maybe_await(on_package_finished(attempt_id, result.message_results))
```

- [ ] **Step 4: Implement outbox saga and immutable snapshots**

In one channel DB transaction validate selection revisions/boundaries, enforce `redownload`, generate `channel-batch-<uuid>`, enforce `(library_id,idempotency_key)`, and store batch/package/item snapshots as pending. Then idempotently create the same TaskState task and mark dispatched. Recovery replays pending rows. Dispatch refetches exact IDs and calls the callback-enabled serial downloader.

- [ ] **Step 5: Run focused regressions**

```bash
.venv/bin/python -m pytest tests/test_channel_library_download.py tests/test_media_downloader.py tests/module/test_task_state.py tests/test_web_upload_progress.py -q
```

- [ ] **Step 6: Commit**

```bash
git add media_downloader.py module/channel_library_service.py module/channel_library_store.py module/download_stat.py tests/test_channel_library_download.py tests/test_media_downloader.py tests/module/test_task_state.py
git commit -m "feat: dispatch channel package download batches"
```

---

### Task 9: Authenticated Web APIs, CSRF, And Service Lifecycle

**Files:**
- Modify: `module/web.py`
- Modify: `media_downloader.py`
- Test: `tests/module/test_channel_library_web.py`
- Test: `tests/module/test_web.py`

**Interfaces:**
- Adds every API from Spec section 7.
- Produces `GET /api/csrf-token` with a logged-in session token.
- Channel APIs return 503 until startup assigns `app.channel_library_service`; Flask reads store/calls service commands and never calls Pyrogram directly.

- [x] **Step 1: Add endpoint contract tests**

Cover login on all routes; missing/wrong CSRF 403; new create 202 and duplicate 200; invalid link/type 400; state 409; missing 404; keyset/filter/item paging; scan controls; versioned delete; selection/summary; required idempotency key; duplicate-key same batch; and safe `error_code` responses.

- [x] **Step 2: Run and observe route failures**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_web.py -q
```

Expected: new routes return 404.

- [x] **Step 3: Implement session-bound CSRF and thin adapters**

```python
def _csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token

def _require_csrf() -> None:
    supplied = request.headers.get("X-CSRF-Token", "")
    if not hmac.compare_digest(supplied, _csrf_token()):
        abort(403)
```

Validate JSON/query primitives, call store for reads, and call persisted service commands for writes. Link creation calls `submit_library_link_threadsafe`, waits at most 30 seconds for its result, and maps timeout to 503 without cancelling persisted work. Map domain exceptions to exact 400/404/409/503 errors. Do not put scan logic in `module/web.py`.

- [x] **Step 4: Wire service startup/shutdown on `Application.loop`**

After Telegram start succeeds:

```python
channel_service = ChannelLibraryService.from_application(app, client)
app.channel_library_service = channel_service
app.loop.run_until_complete(channel_service.start())
```

Before stopping Telegram/general task cancellation:

```python
if app.channel_library_service is not None:
    app.loop.run_until_complete(app.channel_library_service.stop())
```

If store initialization fails, Web stays available but channel APIs return safe 503.

- [x] **Step 5: Run Web/lifecycle regressions**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_web.py tests/module/test_web.py tests/test_web_cancel_task.py tests/test_web_prescan_retention.py -q
```

- [x] **Step 6: Commit**

```bash
git add module/web.py media_downloader.py tests/module/test_channel_library_web.py tests/module/test_web.py
git commit -m "feat: expose channel library web api"
```

---

### Task 10: Channel Library Web Tab

**Files:**
- Modify: `module/templates/index.html`
- Modify: `module/static/css/index.css`
- Test: `tests/module/test_channel_library_web.py`

**Interfaces:**
- Consumes Task 9 APIs.
- Produces existing-SPA nav `data-tab="channel-library"`, split pane, filters, keyset list, selection summary, item expansion, controls, and active-tab-only polling.

- [ ] **Step 1: Add DOM contract and escaping tests**

Assert unique channel-list/workspace/filter IDs, no second route dependency, no unescaped Telegram interpolation, CSRF in shared writes, and active-tab polling guard. Add assertions for empty, queued, scanning, auto-paused, paused, partial, ready, failed, provisional, uncertain, outdated, and superseded labels.

- [ ] **Step 2: Run and observe missing DOM failures**

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_web.py -q
```

- [ ] **Step 3: Add left-library/right-package layout**

Add nav/panel, left link form/channel rows, right status/control band, all Spec filters, selection summary, select-filtered/clear/download actions, package table, and paginated item expansion. Reuse existing Industry variables/classes/icons. Do not add nested cards, marketing sections, gradients/orbs, or a frontend framework.

- [ ] **Step 4: Add state-aware behavior**

Fetch CSRF once and include it in writes. Use `next_cursor`; reset to first page with compact notice when `library_revision` changes. Read selected totals from server. Enable downloads only for terminal ready/partial and stable packages. Confirm delete, large select-filtered, and redownload. Poll status only while active; reload packages on revision/user action.

- [ ] **Step 5: Browser verification**

Use mocked endpoints and inspect 1440x900, 1024x768, and 390x844. Exercise all Step 1 states. Verify no overlap, overflow, blank table, nested card, or inaccessible mobile control. Save screenshots outside version control.

```bash
.venv/bin/python -m pytest tests/module/test_channel_library_web.py tests/module/test_web.py -q
```

- [ ] **Step 6: Commit**

```bash
git add module/templates/index.html module/static/css/index.css tests/module/test_channel_library_web.py
git commit -m "feat: add web channel library view"
```

---

### Task 11: End-To-End, Fault Injection, Documentation, And Progress Log

**Files:**
- Create: `tests/test_channel_library_e2e.py`
- Modify: `README_CN.md`
- Modify: `docs/web-control-console.md`
- Modify: `progress.md`

**Interfaces:**
- Verifies all Spec acceptance criteria; adds no production interface unless a failing acceptance test proves it missing.

- [ ] **Step 1: Add a 15,000-ID end-to-end test without waits**

Use a fake client with boundaries across batches. Run 300 batches, interrupt after a committed checkpoint, recreate service/store, resume, then filter/select/download via fake bridge.

```python
assert fake_client.batch_call_count == 300
assert store.get_library(library_id)["fetched_through_message_id"] == 15000
assert unique_package_keys(store, library_id)
assert one_task_per_batch(store, task_store)
```

- [ ] **Step 2: Close every fault/contract requirement**

Ensure automated evidence for outbox crash windows, gate race, fetch/index crash, FloodWait restart, >500 package, failure closure/repair, revision/supersede/outdated, selection invalidation, keyset publish, CSRF/delete race/0600, parent lifecycle, and all existing workflows.

- [ ] **Step 3: Run full verification**

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pylint --errors-only module/channel_library_store.py module/channel_library_workflow.py module/channel_library_service.py module/telegram_activity.py module/web.py media_downloader.py
.venv/bin/python -m mypy module/channel_library_store.py module/channel_library_workflow.py module/channel_library_service.py module/telegram_activity.py
git diff --check
```

Expected: tests pass and no new pylint errors. If mypy hits the documented pre-existing markupsafe stub issue, record exact output; do not claim pass.

- [ ] **Step 4: Update user/operations docs and progress**

Document links, timing, rates, auto-pause, statuses, filters, partial/repair, duplicate protection, incrementals, DB security/backup/rollback, and API list. Do not document scheduled scans, thumbnails, private chats, or parallel scans. Append the required implementation entry to `progress.md` with exact verification results.

- [ ] **Step 5: Commit**

```bash
git add tests/test_channel_library_e2e.py README_CN.md docs/web-control-console.md progress.md
git commit -m "test: verify full channel library workflow"
```

---

### Task 12: Final Review, Push, Production Backup, Deploy, And Smoke Test

**Files:**
- Modify only files required by concrete final-review findings.
- Modify: `progress.md` with final verification/deployment evidence.

**Interfaces:**
- Produces pushed `master`, updated RackNerd checkout, active service, healthy public Web route, secure channel DB, and a proven rollback point.

- [ ] **Step 1: Run two-stage final review**

Dispatch one spec-compliance reviewer and one code-quality/security reviewer against the Spec and full implementation diff. Fix every actionable P0/P1/P2 with focused tests; rerun affected/full tests. Record rejected findings with technical evidence.

- [ ] **Step 2: Run final local verification**

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m pylint --errors-only module/channel_library_store.py module/channel_library_workflow.py module/channel_library_service.py module/telegram_activity.py module/web.py media_downloader.py
git diff --check
git status --short
git log --oneline -12
```

Expected: tests pass, no new pylint errors, diff clean, only `.omx/` may remain untracked, and feature commits are visible.

- [ ] **Step 3: Push master**

```bash
git push origin master
```

Expected: `master -> master` at final local commit.

- [ ] **Step 4: Create a consistent production backup**

Stop service; use SQLite backup, never a WAL-unsafe main-file copy:

```bash
ssh rn 'set -e; cd /root/telegram_media_downloader; umask 077; stamp=$(date +%Y%m%d-%H%M%S); mkdir -p backups; chmod 700 backups; systemctl stop tg-downloader.service; if [ -f web_tasks.sqlite3 ]; then if command -v sqlite3 >/dev/null 2>&1; then sqlite3 web_tasks.sqlite3 ".backup backups/web_tasks-${stamp}.sqlite3"; sqlite3 "backups/web_tasks-${stamp}.sqlite3" "PRAGMA integrity_check;"; else python3 -c "import sqlite3; s=sqlite3.connect(\"web_tasks.sqlite3\"); d=sqlite3.connect(\"backups/web_tasks-${stamp}.sqlite3\"); s.backup(d); print(d.execute(\"PRAGMA integrity_check\").fetchone()[0]); d.close(); s.close()"; fi; fi; cp config.yaml "backups/config-${stamp}.yaml"; find . -maxdepth 1 -type f -name "*.session" -exec cp {} backups/ \;; systemctl start tg-downloader.service; systemctl is-active tg-downloader.service'
```

Expected: integrity `ok`, service active. If `sqlite3` CLI is absent, use Python `sqlite3.Connection.backup`; do not deploy without a verified backup.

- [ ] **Step 5: Fast-forward deploy and restart**

```bash
ssh rn 'set -e; cd /root/telegram_media_downloader; git pull --ff-only origin master; systemctl restart tg-downloader.service; sleep 5; systemctl is-active tg-downloader.service; git log --oneline -1'
```

- [ ] **Step 6: Verify production without inventing a test channel**

```bash
curl -I https://tgdn.wyichuan.cc/
curl -I https://tgdn.wyichuan.cc/api/channel-libraries
ssh rn 'cd /root/telegram_media_downloader; stat -c "%a %n" channel_library.sqlite3; python3 -c "import sqlite3; c=sqlite3.connect(\"channel_library.sqlite3\"); print(c.execute(\"PRAGMA integrity_check\").fetchone()[0]); print(c.execute(\"PRAGMA journal_mode\").fetchone()[0])"; journalctl -u tg-downloader.service -n 120 --no-pager'
```

Expected: HTTP redirects to login, DB mode 600, integrity `ok`, journal `wal`, and no repeated exception/high-rate/secret log. Do not create a real scan without an explicit controlled link.

- [ ] **Step 7: Log deployment, commit, push, and fast-forward docs**

Append pushed/server commit, backup name/integrity, service status, HTTP results, DB verification, and residual risks to `progress.md`.

```bash
git add progress.md
git commit -m "docs: log full channel library deployment"
git push origin master
ssh rn 'cd /root/telegram_media_downloader && git pull --ff-only origin master && git log --oneline -1'
```

Rollback if smoke fails:

```bash
git revert --no-commit c388685..HEAD
git commit -m "revert: roll back full channel library"
git push origin master
ssh rn 'cd /root/telegram_media_downloader && git pull --ff-only origin master && systemctl restart tg-downloader.service && systemctl is-active tg-downloader.service'
```

Preserve `channel_library.sqlite3`; never delete it during rollback.

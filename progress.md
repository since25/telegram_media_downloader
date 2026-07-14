## 2026-07-09 - Task: Design Web control console

### What was done

- Defined the full Web control console design covering task status, Web task submission, and later prescan/history capabilities.
- Set Phase 1 and Phase 2 as the implementation target for the current deployment.

### Testing

- No runtime tests were run; this was a design/documentation step.
- Reviewed current Web status flow, task state helpers, `TaskNode`, and downloader queue references before writing the design.

### Notes

Changed files:
- `docs/superpowers/specs/2026-07-09-web-control-console-design.md`: Added the Web control console design.
- `progress.md`: Added the required progress log entry for the design step.

Rollback:
- `git revert <design-commit>` after the design commit is created, or remove the two added files before committing.

## 2026-07-09 - Task: Implement Web task status backend

### What was done

- Added an in-memory task state store for Web-readable task, file, and workflow snapshots.
- Added authenticated task dashboard/detail APIs.
- Published downloader task lifecycle state for active task registration, queueing, file download progress, upload progress, and task completion snapshots.

### Testing

- `.venv/bin/python -m pytest tests/module/test_task_state.py tests/module/test_web.py tests/test_media_downloader.py -q`
- Result: 29 passed.

### Notes

Changed files:
- `module/task_state.py`: Added task/file/workflow snapshot models and the process-local task store.
- `module/download_stat.py`: Registers active task nodes and file progress into the task store.
- `module/web.py`: Added task dashboard, task list, and task detail APIs.
- `media_downloader.py`: Publishes queue/download/upload lifecycle transitions to the task store.
- `tests/module/test_task_state.py`: Added store and progress publishing tests.
- `tests/module/test_web.py`: Added task API tests.

Rollback:
- `git revert <phase1-backend-commit>` after the backend commit is created.

## 2026-07-09 - Task: Implement Web task dashboard UI

### What was done

- Replaced the primary Web tab with a task dashboard backed by `/api/task-dashboard`.
- Added dashboard summary counters and task/file detail tables while keeping the existing file-progress tables available under the Files tab.

### Testing

- `.venv/bin/python -m pytest tests/module/test_task_state.py tests/module/test_web.py tests/test_media_downloader.py -q`
- Result: 30 passed.

### Notes

Changed files:
- `module/templates/index.html`: Added task dashboard tables, summary counters, row detail loading, and dashboard polling.
- `module/static/css/index.css`: Added task summary layout styles.
- `tests/module/test_web.py`: Added index-page smoke coverage for the task dashboard shell.
- `progress.md`: Recorded this implementation step.

Rollback:
- `git revert <phase1-ui-commit>` after the UI commit is created.

## 2026-07-09 - Task: Implement Web task submission

### What was done

- Added authenticated Web task submission for Telegram package links and comment links.
- Connected Web submissions to the running downloader client and existing scan/download queue so submitted tasks appear in the task dashboard lifecycle.
- Added a Tasks-tab submission control and user-facing submission status.
- Documented the Web console task submission behavior and API surface.

### Testing

- `.venv/bin/python -m pytest tests/module/test_task_state.py tests/module/test_web.py tests/test_media_downloader.py tests/module/test_comment_workflow.py -q`
- Result: 135 passed.

### Notes

Changed files:
- `module/web.py`: Added Web task submission validation, scheduling, and package/comment orchestration.
- `media_downloader.py`: Passes the running Pyrogram client into the Web layer.
- `module/download_stat.py`: Allows task source/type metadata to be preserved for Web-created active nodes.
- `module/task_state.py`: Preserves node-provided display source/type in snapshots.
- `module/templates/index.html`: Added the Web task submission control and submit handling.
- `module/static/css/index.css`: Added responsive submission control styles.
- `tests/module/test_web.py`: Added Web task submission API coverage.
- `docs/web-control-console.md`: Documented the Web dashboard APIs and submission behavior.
- `README_CN.md`: Linked the Web task submission documentation from the Web UI section.
- `progress.md`: Recorded this implementation step.

Rollback:
- `git revert <phase2-web-submission-commit>` after the implementation commit is created.

## 2026-07-09 - Task: Deploy Web console Phase 2 to RackNerd

### What was done

- Pushed the Phase 1 and Phase 2 Web console commits to `origin/master`.
- Updated the RackNerd checkout at `/root/telegram_media_downloader` with a fast-forward pull.
- Restarted `tg-downloader.service` on the server.
- Verified the public Cloudflare-proxied Web route still reaches the service and redirects unauthenticated users to login.

### Testing

- `git push origin master`
- Result: `master -> master`, latest pushed commit `a8ea37a`.
- `ssh rn 'cd /root/telegram_media_downloader && git pull --ff-only origin master'`
- Result: fast-forwarded server checkout to `a8ea37a`.
- `ssh rn 'cd /root/telegram_media_downloader && systemctl restart tg-downloader.service && sleep 3 && systemctl is-active tg-downloader.service && git log --oneline -1'`
- Result: service `active`, latest server commit `a8ea37a feat: add web task submission`.
- `curl -I https://tgdn.wyichuan.cc/`
- Result: `HTTP/2 302`, `location: /login?next=%2F`.
- `curl -I https://tgdn.wyichuan.cc/api/task-dashboard`
- Result: `HTTP/2 302`, `location: /login?next=%2Fapi%2Ftask-dashboard`.

### Notes

Changed files:
- `progress.md`: Recorded the RackNerd deployment and verification evidence.

Rollback:
- On the server, run `cd /root/telegram_media_downloader && git revert a8ea37a 44e31c0 9c58a10 08a6cb6 8f45025 && systemctl restart tg-downloader.service`, or reset to the pre-deployment commit only after explicitly confirming that runtime local files should be left untouched.

## 2026-07-09 - Task: Add Web preview confirmation before download

### What was done

- Changed Web task submission so package/comment links scan into a preview state instead of immediately starting downloads.
- Added Web confirm and cancel APIs for tasks waiting on preview confirmation.
- Added dashboard preview summaries and Start/Cancel actions for waiting tasks.
- Documented the new scan-preview-confirm behavior.

### Testing

- `.venv/bin/python -m pytest tests/module/test_task_state.py tests/module/test_web.py tests/test_media_downloader.py tests/module/test_comment_workflow.py -q`
- Result: 138 passed.

### Notes

Changed files:
- `module/web.py`: Stores Web preview results, waits for confirmation, and queues downloads only after confirmation.
- `module/download_stat.py`: Allows active-node registration without overwriting preview snapshots.
- `module/templates/index.html`: Adds preview summary and Start/Cancel actions to the task dashboard.
- `module/static/css/index.css`: Adds the dashboard action empty-state style.
- `tests/module/test_web.py`: Covers preview waiting, confirmation scheduling, cancellation, and dashboard action markup.
- `docs/web-control-console.md`: Documents preview confirmation and the confirm/cancel APIs.
- `README_CN.md`: Updates the Web UI usage summary.
- `progress.md`: Records this implementation step.

Rollback:
- `git revert <phase3a-preview-confirmation-commit>` after the implementation commit is created, then redeploy and restart `tg-downloader.service`.

## 2026-07-09 - Task: Deploy Web preview confirmation to RackNerd

### What was done

- Pushed the Web preview confirmation commit to `origin/master`.
- Fast-forwarded the RackNerd checkout at `/root/telegram_media_downloader`.
- Restarted `tg-downloader.service` on the server.
- Verified the public Cloudflare-proxied Web route and task dashboard API still reach the login flow.

### Testing

- `git push origin master`
- Result: `master -> master`, latest pushed commit `d1c5336`.
- `ssh rn 'cd /root/telegram_media_downloader && git pull --ff-only origin master && systemctl restart tg-downloader.service && sleep 3 && systemctl is-active tg-downloader.service && git log --oneline -1'`
- Result: service `active`, latest server commit `d1c5336 feat: require web preview confirmation`.
- `curl -I https://tgdn.wyichuan.cc/`
- Result: `HTTP/2 302`, `location: /login?next=%2F`.
- `curl -I https://tgdn.wyichuan.cc/api/task-dashboard`
- Result: `HTTP/2 302`, `location: /login?next=%2Fapi%2Ftask-dashboard`.

### Notes

Changed files:
- `progress.md`: Recorded the RackNerd deployment and verification evidence for Web preview confirmation.

Rollback:
- On the server, run `cd /root/telegram_media_downloader && git revert d1c5336 && systemctl restart tg-downloader.service`.

## 2026-07-09 - Task: Add Web persistence and resource guardrails

### What was done

- Added SQLite-backed task/file snapshot persistence with WAL mode for Web task history across process restarts.
- Added paginated task file retrieval so Web does not need to fetch large file lists in one response.
- Limited dashboard task rows returned during polling.
- Added Web prescan resource bounds and a single-prescan concurrency slot for small RackNerd servers.
- Ignored local SQLite runtime files in git.

### Testing

- `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`
- Result: 22 passed.

### Notes

Changed files:
- `module/task_state.py`: Added optional SQLite persistence, reload, bounded dashboard rows, and file pagination.
- `module/web.py`: Added paginated file API and Web prescan resource guardrail helpers.
- `tests/module/test_task_state.py`: Added persistence, pagination, and dashboard-limit coverage.
- `tests/module/test_web.py`: Added file pagination and prescan guardrail coverage.
- `docs/web-control-console.md`: Documented resource boundaries and paginated file API.
- `.gitignore`: Excludes SQLite runtime files.
- `progress.md`: Recorded this implementation step.

Rollback:
- `git revert <phase3b-persistence-guardrails-commit>` after the implementation commit is created, then redeploy and restart `tg-downloader.service`.

## 2026-07-09 - Task: Add Web prescan package selection

### What was done

- Added Prescan submission mode for Web tasks.
- Added bounded Web prescan scanning that waits for package selection instead of downloading immediately.
- Added paginated prescan package APIs and include/exclude selection.
- Confirming a prescan queues selected packages through the existing serial prescan download path.
- Added terminal task clearing and explicit retry limitation response.
- Updated the dashboard UI with Prescan mode and package selection actions.

### Testing

- `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q`
- Result: 27 passed.

### Notes

Changed files:
- `module/web.py`: Added Web prescan scheduling, package pagination/selection, selected-package confirmation, clear, and retry limitation APIs.
- `module/task_state.py`: Added task removal and completed-history clearing helpers.
- `module/templates/index.html`: Added Prescan mode, package detail rendering, and include/exclude actions.
- `module/static/css/index.css`: Adjusted the task submission layout for mode selection.
- `tests/module/test_web.py`: Added Web prescan, package selection, confirm, clear, and retry limitation coverage.
- `docs/web-control-console.md`: Documented Prescan mode and new APIs.
- `README_CN.md`: Updated the Web UI behavior summary.
- `progress.md`: Recorded this implementation step.

Rollback:
- `git revert <phase3c-prescan-selection-commit>` after the implementation commit is created, then redeploy and restart `tg-downloader.service`.

## 2026-07-09 - Task: Deploy Web Phase 3B and 3C to RackNerd

### What was done

- Pushed the Phase 3B and Phase 3C commits to `origin/master`.
- Fast-forwarded the RackNerd checkout at `/root/telegram_media_downloader`.
- Restarted `tg-downloader.service` on the server.
- Verified Cloudflare-proxied Web routes still reach the login flow.
- Checked the SQLite task database and post-restart memory footprint.

### Testing

- `git push origin master`
- Result: `master -> master`, latest pushed commit `b6fe588`.
- `ssh rn 'cd /root/telegram_media_downloader && git pull --ff-only origin master && systemctl restart tg-downloader.service && sleep 4 && systemctl is-active tg-downloader.service && git log --oneline -2'`
- Result: service `active`, latest server commits `b6fe588` and `edc71e1`.
- `curl -I https://tgdn.wyichuan.cc/`
- Result: `HTTP/2 302`, `location: /login?next=%2F`.
- `curl -I https://tgdn.wyichuan.cc/api/task-dashboard`
- Result: `HTTP/2 302`, `location: /login?next=%2Fapi%2Ftask-dashboard`.
- `ssh rn 'cd /root/telegram_media_downloader && ls -lh web_tasks.sqlite3* && free -h'`
- Result: SQLite task DB initialized at `24K`; memory available about `524MiB`.

### Notes

Changed files:
- `progress.md`: Recorded the RackNerd deployment and verification evidence for Phase 3B/3C.

Rollback:
- On the server, run `cd /root/telegram_media_downloader && git revert b6fe588 edc71e1 && systemctl restart tg-downloader.service`.

## 2026-07-09 - Task: Fix Web prescan progress visibility

### What was done

- Fixed the legacy `/get_download_list` endpoint so it reads the active download result store instead of an undefined local variable.
- Added Web prescan progress updates during long scans so the dashboard shows scanned message/package counts before the scan reaches package selection.

### Testing

- `.venv/bin/python -m pytest tests/module/test_task_state.py tests/module/test_web.py tests/test_media_downloader.py tests/module/test_comment_workflow.py -q`
- Result: 151 passed.

### Notes

Changed files:
- `module/web.py`: Fixed `get_download_list` and added prescan progress publishing.
- `tests/module/test_web.py`: Added regressions for download-list access and prescan progress updates.
- `progress.md`: Recorded this bugfix.

Rollback:
- `git revert <prescan-progress-fix-commit>` after the implementation commit is created, then redeploy and restart `tg-downloader.service`.

## 2026-07-14 - Task: Implement Web task dashboard UX enhancement

### What was done

- Rendered task/file statuses as colored badges (blue active, green completed, orange completed-with-errors, red failed, cyan waiting, gray cancelled; file-level downloaded/uploaded green and upload_failed red).
- Surfaced task and file errors in the Web UI: badge hover titles, a red detail banner, and a file error column.
- Replaced raw progress numbers with progress bars (per-file, plus a task-level done/total bar).
- Made the ok/fail/skip/up counts color-coded with failures emphasized, added friendly empty states, and stabilized the 1s polling (selected-row highlight re-applied after reload, detail columns set once per type, unchanged data skips reload).

### Testing

- `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q` — passed (frontend-only change; no backend regression).
- Browser harness with mock dashboard payloads verified badges, progress bars, error display, counts, empty states; a layui `done`-callback binding bug found in review was fixed and proven with a Node call-shape repro.
- Full suite at final review: 194 passed, 1 skipped.

### Notes

Changed files:
- `module/templates/index.html`: New render helpers, wired columns, error banner, polling stability.
- `module/static/css/index.css`: Badge, count, mini progress bar, error, and empty-state styles.

Rollback:
- `git revert 226a017 075ac21 a69c0c1 a0feb34 b5e2a33 b11412a` reverts both web features together (they share files), then redeploy and restart `tg-downloader.service`.

## 2026-07-14 - Task: Implement Web ranged batch prescan selection

### What was done

- Added a per-submission scan window to Web prescan: a message-count input sent as `max_messages` (default 2000, hard cap 10000; package cap raised to 100) for scanning many consecutive packages from a start link.
- Added bulk package selection: `POST /api/prescans/<task_id>/packages/select-all`, Select all / Clear all buttons, a live summary (selected packages · media · estimated size), and a "Download selected" button reusing the existing confirm + serial download path.
- Updated `docs/web-control-console.md` to the new limits and APIs.

### Testing

- TDD for the new endpoint: `test_prescan_select_all_and_clear` failed with 404 before implementation, passed after; select/clear/missing-prescan cases covered.
- `.venv/bin/python -m pytest tests/module/test_web.py tests/module/test_task_state.py -q` — 30 passed.
- Full suite at final review: 194 passed, 1 skipped. Browser harness verified count-input mode toggle, summary math, bulk selection flows, and submit-row layout at desktop/mobile widths.

### Notes

Changed files:
- `module/web.py`: Raised prescan limit constants; added the select-all endpoint (atomic set reassignment).
- `module/templates/index.html`: Count input, prescan controls bar, summary, bulk-select wiring.
- `module/static/css/index.css`: Controls/summary styles and 5-track submit grid.
- `tests/module/test_web.py`: select-all endpoint coverage.
- `docs/web-control-console.md`: New limits, `max_messages`, select-all API.

Rollback:
- Same combined revert as the dashboard UX entry above (shared files), then redeploy and restart `tg-downloader.service`.

## 2026-07-14 - Task: Deploy Web console UX and ranged prescan to RackNerd

### What was done

- Merged `feat/web-task-console-ux-batch` into `master` (fast-forward) and pushed to `origin/master`.
- Fast-forwarded the RackNerd checkout and restarted `tg-downloader.service`.
- Verified Cloudflare-proxied Web routes and the new bulk-select endpoint reach the login flow, and checked server memory and the task database.

### Testing

- `.venv/bin/python -m pytest tests/ -q` on merged master — 194 passed, 1 skipped.
- `git push origin master` — `97aa52f..ea0e8cf master -> master`.
- `ssh rn 'git pull --ff-only && systemctl restart tg-downloader.service && systemctl is-active ...'` — service `active`, server at `ea0e8cf`.
- `curl -I https://tgdn.wyichuan.cc/` and `/api/task-dashboard` — `HTTP/2 302` to login.
- `curl -I -X POST https://tgdn.wyichuan.cc/api/prescans/x/packages/select-all` — `HTTP/2 302` to login (route present, auth-gated).
- Server health: `web_tasks.sqlite3` 32K, memory available ~529MiB.

### Notes

Changed files:
- `progress.md`: Recorded this deployment.

Rollback:
- On the server: `cd /root/telegram_media_downloader && git reset --hard 97aa52f && systemctl restart tg-downloader.service` (or revert the six feature commits and redeploy).

## 2026-07-14 - Task: Mask Discord webhook URL in monitor config startup log

### What was done

- Fixed the production log leak flagged in the 2026-07-14 design doc: the startup `[MONITOR][CFG]` line no longer prints the full Discord webhook URL; it now logs a sanitized config copy with `webhook_url` reduced to scheme+host (`https://discord.com/***`), fail-closed to `***` when the value cannot be parsed.
- Added `_sanitize_monitor_cfg` with TDD regression tests (mask well-formed URL, fail-closed on unparseable value, pass-through when `webhook_url` absent/None; original dict not mutated).
- Fast-forwarded master, pushed, deployed to RackNerd, restarted `tg-downloader.service`, and verified the fresh log line is masked.

### Testing

- TDD: watched the new tests fail (ImportError, function missing) before implementing; `.venv/bin/python -m pytest tests/ -q` — 196 passed, 1 skipped.
- Pylint (errors-only) clean on changed lines; mypy blocked by a pre-existing markupsafe stub issue unrelated to this change.
- Deploy: server at `ea3aeaf`, `systemctl is-active` = active; newest `[MONITOR][CFG]` line in `log/tdl.log` shows `'webhook_url': 'https://discord.com/***'` with no `api/webhooks` fragment; `https://tgdn.wyichuan.cc/` returns 302 to login.
- Residual: 10 historical lines in `log/tdl.log` still contain the raw webhook URL — the exposed webhook must be rotated (user action), and old log lines can optionally be scrubbed.

### Notes

Changed files:
- `media_downloader.py`: Added `_sanitize_monitor_cfg`; `[MONITOR][CFG]` now logs the sanitized copy.
- `tests/test_media_downloader.py`: Two regression tests for the sanitizer.
- `progress.md`: This entry.

Rollback:
- `git revert ea3aeaf`, redeploy and restart `tg-downloader.service` (restores the plaintext logging — not recommended).

## 2026-07-14 - Task: Fix Web rejection of telegram.me links

### What was done

- Fixed "unsupported prescan link" for official alias hosts: Web link builders now accept `https://t.me`, `https://telegram.me`, and `https://telegram.dog` via a proper hostname check (prescan, preview, and comment submission all share these builders).
- The hostname check also closes a lookalike-host hole: prefixes such as `https://t.mexample.com` previously passed the old `startswith("https://t.me")` gate and parsed as real links.

### Testing

- TDD: new tests for `telegram.me` package/comment links and lookalike-host rejection failed first (including the reported link `https://telegram.me/c/1446289027/158156`), passed after the fix.
- `.venv/bin/python -m pytest tests/ -q` — 199 passed, 1 skipped (pre-change baseline 196 passed; delta is exactly the 3 new tests).

### Notes

Changed files:
- `module/comment_workflow.py`: Added `_is_telegram_link_url` host check; replaced three `startswith` gates.
- `tests/module/test_comment_workflow.py`: Host acceptance and lookalike rejection coverage.

Known limitation (unchanged, out of scope): the bot's own text handler (`module/bot.py:752`) still requires the `https://t.me` prefix.

Rollback:
- `git revert <this fix commit>` then redeploy and restart `tg-downloader.service`.

## 2026-07-14 - Task: Fix uncancellable Web scan phase

### What was done

- Made scan-phase Web tasks cancellable for all three types (prescan, package preview, comment preview): scanning nodes are now registered at creation so `/api/tasks/<id>/cancel` can find them, and the task row shows a Cancel button while scanning.
- Prescan scans now stop mid-flight: `scan_prescan_packages` accepts a `should_stop` callback checked before each batch, so cancelling a 10000-message scan takes effect within one batch instead of running minutes to completion (also frees the single-scan slot promptly).
- Guarded all three scan coroutines against resurrection: a cancelled task stays cancelled instead of being overwritten by the scan's completion write-back, and cancellation-induced scan errors report as cancelled rather than failed.
- Fixed a latent crash in cancel: cancelling a task found only in the active-node table (e.g. mid-download) previously hit `None.get` and returned 500.

### Testing

- TDD: five failing tests first (scan-loop early stop; cancel-during-scan via the new registry; prescan and package write-back guards; active-node cancel 500 regression), all passing after the fix.
- `.venv/bin/python -m pytest tests/ -q` — 204 passed, 1 skipped (previous baseline 199; delta is exactly the 5 new tests).

### Notes

Changed files:
- `media_downloader.py`: `scan_prescan_packages` gained the optional `should_stop` batch-boundary check.
- `module/web.py`: `_scanning_web_task_nodes` registry, `_mark_web_task_cancelled` helper, cancel lookup + crash fix, write-back guards in the three scan coroutines.
- `module/templates/index.html`: Cancel button on scanning task rows.
- `tests/module/test_web.py`, `tests/module/test_comment_workflow.py`: coverage above.

Rollback:
- `git revert <this fix commit>` then redeploy and restart `tg-downloader.service`.

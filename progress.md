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

## 2026-07-14 - Task: Add Industry design system CSS and app shell

### What was done

- Imported the approved Industry design handoff and made its complete design-system stylesheet the Web console CSS foundation.
- Replaced the layui dashboard markup with the shared Chinese app shell for Tasks, Files, and Advanced Config, including the running-state control and version/speed footer.
- Removed the obsolete layui request bootstrap and added a static shell harness for isolated browser verification.
- Updated the existing index-shell regression test to assert the new T1 DOM contract.

### Testing

- CSS source-prefix comparison, required-selector checks, HTML parser checks, layui-reference scan, and `git diff --check` passed.
- Chrome headless rendered `scratchpad/harness/shell.html` at 1440x900; verified the 1240px shadowed shell, square state chip with live dot, active Tab underline, no blueprint corner markers on the shell, and the two-sided footer. Google-hosted Barlow fonts rendered during this online check.
- `.venv/bin/python -m pytest tests/module/test_web.py::WebTestCase::test_index_contains_industry_app_shell -q` - 1 passed.
- `.venv/bin/python -m pytest tests/ -q` - 204 passed, 1 skipped.

### Notes

Changed files:
- `docs/design/frontend-redesign/`: Added the approved README, prototype, and complete design-system stylesheet handoff.
- `module/static/css/index.css`: Replaced layui-era page styles with the Industry design system and app-shell classes.
- `module/templates/index.html`: Replaced the old dashboard with the shared navigation, empty screen containers, and footer shell.
- `module/static/request/index.js`: Removed the layui-dependent request helper and left the T1 no-op placeholder.
- `tests/module/test_web.py`: Updated the index-page shell contract assertion for the new DOM.
- `scratchpad/harness/shell.html`: Added the isolated static shell preview used for browser verification.
- `progress.md`: Recorded this implementation and verification.

Rollback:
- `git revert <Task 1 commit>` to restore the prior layui dashboard shell and CSS.

## 2026-07-14 - Task: Web 控制台 Industry 蓝图风格前端重构（四屏 + 新监控）

### What was done

- 把 layui/jQuery 的 Web 控制台重构为统一 Industry 蓝图风格（钢蓝/方角/十字角标/Barlow），覆盖任务/文件/高级配置/登录四屏，全中文桌面优先。
- 新增系统资源监控卡（CPU/内存/磁盘，磁盘>80% 描边告警）与上传进度监控（按部署实际的 rclone/网盘上传接线）。
- 后端新增 `GET /api/system`、`GET /get_upload_list`（rclone）、`POST /clear_download_list`；修复预扫描确认后包状态丢失（含内存泄漏防护）。
- 去除 layui 依赖引用；登录页分栏重构，AES 加密逻辑保持不变。
- 执行中发现并修复：snapshot_node 上传接线缺失、`/get_upload_list` 文件名脱敏泄漏、预扫描保留引入的内存泄漏、任务标题/文件名存储型 XSS、文件页「清空已完成」打错接口、上传监控接错子系统（Telegram 转发→rclone 重接）。

### Testing

- 后端 `pytest tests/ -q` → 222 passed, 1 skipped（新增 4 个测试文件：system/upload/prescan-retention/clear-download-list）。
- 前端：scratchpad 浏览器 harness + mock 数据逐屏保真核对；四屏零红色、方角、角标、Barlow 均程序化验证；XSS 探针全部转义为惰性文本。
- 全分支终审（whole-branch review）通过；四屏视觉终审通过。
- 部署验证：`https://tgdn.wyichuan.cc/` 返回 302→/login；GET /login 200 且为新 Industry 版式、无 layui；static/css/index.css 与 crypto-js 资源在真实域名下 200；服务 active、下载 worker 正常、psutil 7.2.2 已装入 .venv。

### Notes

Changed files（相对 master 26dc3ee，19 commits）:
- `module/templates/index.html`: 三屏外壳 + 命令栏/汇总/系统监控/任务表/详情/文件页/配置页全部内联渲染（去 layui）。
- `module/templates/login.html`: 分栏登录，沿用 AES，改 form-encoded 直连（去 request()/layui 依赖）。
- `module/static/css/index.css`: 重写为 Industry 设计系统样式表。
- `module/static/request/index.js`: 置为 no-op（渲染逻辑内联到 index.html）。
- `module/web.py`: /api/system、/get_upload_list（rclone）、/clear_download_list、预扫描保留与孤儿清理。
- `module/task_state.py`: FileSnapshot/TaskSnapshot 上传字段 + snapshot_node 上传接线（rclone）。
- `module/download_stat.py`: get_total_upload_speed + _parse_rclone_speed + clear_completed_download_result。
- `module/cloud_drive.py`: rclone 上传成功时清理显示缓存条目。
- `requirements.txt`: 新增 psutil。
- `tests/`: 4 个新测试文件。
- `docs/superpowers/{specs,plans}/2026-07-14-web-industry-redesign-*.md`: spec 与实施计划。

Rollback:
- 代码回滚：`git revert -m 1 7eb71e8`（合并提交）后推送并在服务器 `git pull --ff-only && systemctl restart tg-downloader.service`；psutil 可保留无害。
- 或服务器直接 `git reset --hard 26dc3ee` 回到重构前并重启（丢弃本次全部改动）。

## 2026-07-14 - Task: Web 控制台 post-deploy 修复（取消/ID/抖动/身份/上传接线）

### What was done

- 修复取消逻辑：cancel_task 不再对重启产生的孤儿待确认任务返回 404；运行中任务停止并标记已取消，未开始/孤儿任务直接删除；下载中/上传中行新增取消按钮。
- 任务表：任务 ID 缩短显示（悬停看完整）；移除会抖动的「当前文件」列，改在任务详情中显示。
- 修复任务身份被覆盖：snapshot_node 回写时保留任务已有的 web/prescan 身份，不再被弱缺省值降级为 bot/unknown（此前导致预扫描任务下载中详情从包列表掉到文件列表）。
- 上传接线去重：删除 snapshot_node 中多余的 rclone 上传镜像循环，交回 media_downloader 既有的每文件上传状态逻辑；/get_upload_list 与 /api/system 继续读 rclone 实时进度/速度。
- 确认既有「退出热覆盖 config.yaml」设计（KillSignal=SIGINT → finally → update_config，ruamel 保留注释）对本次改动无影响；本分支未触碰 config 结构/update_config。

### Testing

- 全量 pytest 227 passed / 1 skipped；新增 tests/test_web_cancel_task.py（孤儿删除/活动取消/未知404）+ 身份保留测试。
- 部署验证：RackNerd 拉取至 339efc1、服务 active、无 error 日志、https://tgdn.wyichuan.cc/ 返回 302→/login。

### Notes

Changed files:
- `module/web.py`: cancel_task 重写（孤儿/运行中/未开始分流）。
- `module/task_state.py`: snapshot_node 身份保留 + 移除多余上传循环。
- `module/templates/index.html`: 取消按钮扩展、shortId、当前文件移入详情、详情随取消收起。
- `tests/test_web_cancel_task.py`(新)、`tests/test_web_upload_progress.py`(调整)。

Rollback:
- `git revert -m 1 339efc1` 后 push，服务器 `git pull --ff-only && systemctl restart tg-downloader.service`。

## 2026-07-16 - Task: 设计 Web 全频道包库与低频可恢复扫描

### What was done

- 完成 Web 全频道包库 Spec，明确全历史低频扫描、重启续扫、稳定包渐进展示、包级筛选/选择、增量扫描和现有串行下载接入。
- 通过三路独立对抗性审查，修复跨库一致性、扫描/下载竞态、双检查点、包 revision、失败闭包、长包窗口、包级下载回调、状态机、分页和安全/部署证据等设计缺口。
- 将 Visual Companion 草稿目录加入忽略，避免设计画布进入版本控制。

### Testing

- `rg -n "TBD|TODO|待定" docs/superpowers/specs/2026-07-16-web-full-channel-library-design.md`：无占位符。
- 对抗性审查：数据/恢复、产品/运维/安全、现有代码适配三路只读审查完成，所有高风险和中风险发现已写入 Spec 的明确契约与验收项。
- `git diff --check`：通过。

### Notes

Changed files:
- `docs/superpowers/specs/2026-07-16-web-full-channel-library-design.md`: 新增经对抗性审查修订的全频道包库设计。
- `.gitignore`: 忽略 `.superpowers/` 视觉设计草稿。
- `progress.md`: 记录本轮设计、审查和验证证据。

Rollback:
- 执行 `git revert c388685` 回滚设计文档、审查记录和视觉草稿忽略规则。

## 2026-07-16 - Task: 编写 Web 全频道包库实施计划

### What was done

- 将经对抗性审查的 Spec 拆分为 12 个可独立验证和提交的实施任务，覆盖存储、双水位恢复、包 revision、Telegram 活动门、全量/增量/补扫、筛选选择、下载 outbox、Web API、前端、端到端验证和生产部署。
- 固定了模块责任、跨任务接口、TDD 验证命令、提交边界、最终两阶段审查和一致性备份/回滚步骤。

### Testing

- `rg -n "TBD|TODO|\\.\\.\\." docs/superpowers/plans/2026-07-16-web-full-channel-library.md`：无占位内容。
- 校验 Task 1-12 标题、关键 Spec 约束映射和 `git diff --check`：通过。

### Notes

Changed files:
- `docs/superpowers/plans/2026-07-16-web-full-channel-library.md`: 新增完整实施与部署计划。
- `progress.md`: 记录计划产出与自检证据。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^docs: plan full channel library implementation$')"` 回滚实施计划与本条记录。

## 2026-07-16 - Task: 准备全频道包库隔离施工目录

### What was done

- 将项目本地 `.worktrees/` 加入忽略，为 subagent-driven development 创建隔离 worktree，避免直接在 `master` 施工或误提交 worktree 内容。

### Testing

- `git check-ignore -v .worktrees`：确认 `.worktrees/` 由根目录 `.gitignore` 忽略。
- `git diff --check`：通过。

### Notes

Changed files:
- `.gitignore`: 忽略本地 Git worktree 根目录。
- `progress.md`: 记录隔离施工准备与验证。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^chore: prepare isolated feature worktree$')"` 回滚本次准备改动。

## 2026-07-16 - Task: Validated Configuration And SQLite Foundation

### What was done

- 新增不可变的频道库运行配置及上下限校验，并在 Application 配置加载路径接入，保留后续服务接线属性。
- 新增独立频道库 SQLite v1 基础，覆盖频道、扫描任务、媒体、revision 包、失败补扫、持久选择和下载 outbox 全部表与索引；连接启用 WAL、外键、5000 ms busy timeout，数据库文件设为 `0600`。
- 重复提交同一 Telegram `chat_id` 时复用原频道库并刷新展示与审计字段，不重置已有扫描状态。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_app.py::test_channel_library_config_is_clamped -q`：按预期失败，`ModuleNotFoundError: No module named 'module.channel_library_store'`，`1 error in 0.06s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_app.py -q`：`5 passed in 0.06s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`230 passed, 1 skipped in 23.56s`。
- Schema 自检：schema version 1、外键启用、busy timeout 5000 ms、30 个索引、`PRAGMA foreign_key_check` 0 条违规；`py_compile` 与 `git diff --check` 均通过。

### Notes

Changed files:
- `module/channel_library_store.py`: 新增配置对象、状态常量、SQLite v1 schema/索引与频道库创建/读取接口。
- `module/app.py`: 接入频道库配置并新增运行期 service 属性。
- `config.example.yaml`: 增加已确认的频道库保守默认值。
- `tests/module/test_channel_library_store.py`: 覆盖安全 WAL schema 和 `chat_id` 唯一复用行为。
- `tests/module/test_app.py`: 覆盖批大小与扫描延迟下限夹断。
- `progress.md`: 追加本轮实施、验证与回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^feat: add channel library storage foundation$')"` 回滚 Task 1 全部已跟踪改动。

## 2026-07-16 - Task: 修复 repair target 跨频道关联约束

### What was done

- 为补扫 target 持久记录增加所属频道库 ID，并同时用复合外键绑定 scan job 与 scan failure 的频道归属。
- 保留同一 job/failure 组合唯一性，阻止频道 A 的 repair job 关联频道 B 的 failure，同时允许同频道合法关联。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py::test_repair_target_enforces_library_ownership -q`：`1 failed in 0.02s`，按预期报 `sqlite3.OperationalError: table channel_scan_repair_targets has no column named library_id`。
- GREEN regression：同一节点命令通过，`1 passed in 0.01s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_app.py -q`：`6 passed in 0.06s`。
- Schema 自检：`library_id` 非空、2 个复合外键共 4 个列映射、`PRAGMA foreign_key_check` 0 条违规；`py_compile` 与 `git diff --check` 通过。

### Notes

Changed files:
- `module/channel_library_store.py`: 以 `library_id` 和复合外键隔离 repair target 的 job/failure 归属。
- `tests/module/test_channel_library_store.py`: 新增同库成功、跨库触发完整性错误的回归测试。
- `progress.md`: 追加本轮 review 修复、验证与回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: enforce repair target library isolation$')"` 回滚本次 review 修复。

## 2026-07-16 - Task: Scan State, Checkpoints, Failures, And Restart Recovery

### What was done

- 新增频道扫描任务创建、原子领取和精确状态迁移，禁止未到期的限流任务提前恢复，并要求停止任务复用原 job。
- 新增媒体/抓取水位与索引水位/revision 的独立事务提交，终态前同时校验两条水位已追上不可变扫描快照。
- 新增相邻失败区间合并、多失败区间补扫 target 独立游标与完成状态持久化，以及重启后运行中、自动暂停和到期限流任务的恢复。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py -q`：按预期在收集阶段失败，`ImportError: cannot import name 'ALLOWED_SCAN_TRANSITIONS'`，`1 error in 0.04s`。
- GREEN store：同一命令通过，`26 passed in 0.13s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_task_state.py -q`：`34 passed in 0.64s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`254 passed, 1 skipped in 23.66s`。
- `py_compile` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/channel_library_store.py`: 新增扫描状态机、双检查点、失败区间、补扫游标和重启恢复存储接口。
- `tests/module/test_channel_library_store.py`: 新增扫描状态、事务原子性、失败补扫与重启恢复覆盖。
- `progress.md`: 追加 Task 2 实施与验证证据。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^feat: persist channel scan recovery state$')"` 回滚 Task 2 全部改动。

## 2026-07-16 - Task: Review Fixes For Channel Scan State Mutations

### What was done

- 将扫描领取收紧为全局单运行任务，并在状态迁移读取前取得 SQLite 写锁，避免多任务并行领取和并发控制覆盖。
- 禁止未解决失败区间发布 ready，要求 repair job 的全部 target 完成后才能进入完成/部分终态；仍有未解决失败时只允许发布 partial。
- 抓取与索引检查点只接受 running job，并在同一写事务内校验状态；用更新阶段中止触发器验证已插入媒体与检查点完整回滚。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py -q`：按预期覆盖全局领取、写锁顺序、非运行任务写入、失败区间终态和 repair target 守卫，`10 failed, 25 passed in 0.21s`。
- GREEN store：同一命令通过，`35 passed in 0.16s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_task_state.py -q`：`43 passed in 0.68s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`263 passed, 1 skipped in 23.70s`。
- `py_compile` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/channel_library_store.py`: 增加全局单扫描、原子状态迁移、终态失败区间和 running 检查点守卫。
- `tests/module/test_channel_library_store.py`: 增加五项 review 发现的确定性回归与更新阶段事务回滚证据。
- `progress.md`: 追加 Task 2 review 修复与验证证据。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: harden channel scan state mutations$')"` 回滚本次 review 修复。

## 2026-07-16 - Task: Guard Direct Channel Scan Claims

### What was done

- 修复直接调用状态迁移绕过全局单扫描约束的问题：`queued -> running` 在原有即时写事务内检查其他 running job，并在冲突时保持当前 job 为 queued。
- 保持既有扫描状态迁移表、公开接口和 schema 不变。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py::test_direct_running_transition_respects_global_single_scan -q`：按预期未抛出状态冲突，`1 failed in 0.03s`。
- GREEN regression：同一命令通过，`1 passed in 0.01s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_task_state.py -q`：`44 passed in 0.69s`。
- `py_compile` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/channel_library_store.py`: 在直接进入 running 前原子检查其他运行任务。
- `tests/module/test_channel_library_store.py`: 覆盖两频道直接状态迁移的全局互斥回归。
- `progress.md`: 追加本次 review addendum 与验证证据。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: guard direct channel scan claims$')"` 回滚本次修复。

## 2026-07-16 - Task: Persisted Message Adapter And Revisioned Package Indexer

### What was done

- 新增持久化媒体消息适配器和稳定 SHA-256 元数据摘要，使 SQLite 元数据可直接复用现有包规划、caption 继承、专辑和大小汇总规则。
- 新增重叠尾部索引与失败不确定闭包，跨 50 条扫描批次和超过 500 条同包媒体时只由真实下一包边界或扫描快照终点稳定尾包。
- 在单一事务中原位发布同起点 package revision、包成员、superseded 关系、选择失效、成功旧 revision 的 outdated 状态，以及 job/library 索引水位和全局 revision。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_workflow.py -q`：按预期在收集阶段失败，`ModuleNotFoundError: No module named 'module.channel_library_workflow'`，`1 error in 0.04s`。
- GREEN Task 3：同一命令通过，`11 passed in 0.09s`。
- GREEN planner regressions：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_workflow.py tests/module/test_comment_workflow.py tests/module/test_prescan_workflow.py -q`：`128 passed in 0.92s`。
- GREEN state regressions：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_task_state.py -q`：`44 passed in 0.56s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`275 passed, 1 skipped in 23.85s`。
- `py_compile` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/channel_library_workflow.py`: 新增媒体行提取、消息适配、失败闭包和 revision 包索引器。
- `module/channel_library_store.py`: 新增索引上下文读取与包、成员、选择、失败闭包、revision、水位的原子发布。
- `tests/module/test_channel_library_workflow.py`: 覆盖 planner 金标准、album、跨批边界、超过 500 条、尾部、失败闭包、拆并 supersede、选择失效、outdated 和事务回滚。
- `progress.md`: 追加 Task 3 实施、验证与回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^feat: index revisioned channel packages$')"` 回滚 Task 3 全部已跟踪改动。

## 2026-07-16 - Task: Download-Priority Telegram Activity Gate

### What was done

- 新增单事件循环、单 `asyncio.Condition` 的 Telegram activity gate，使等待或进行中的下载优先于下一扫描批，同时允许多个下载并行且全局仅一个扫描 permit。
- 在下载入队前登记 intent，兼容旧二元 queue item，并在入队失败/取消、停止前丢弃、worker 取消/异常/正常结束路径中幂等结算。
- 为 Web package、comment、Prescan 预览及确认后的评论读取加下载优先 permit；Telegram 阶段结束即释放，rclone/纯云盘上传保持不占 gate。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_telegram_activity.py -q`：收集阶段按预期报 `ModuleNotFoundError: No module named 'module.telegram_activity'`，`1 error in 0.04s`。
- 无效 GREEN（未采信）：首次实现后因仓库未安装 `pytest-asyncio`，异步测试被跳过，`1 passed, 5 skipped, 10 warnings in 0.02s`；改用 `asyncio.run` 后全部真实执行。
- GREEN gate：同一 gate 命令通过，`6 passed in 0.01s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_telegram_activity.py tests/test_media_downloader.py tests/module/test_web.py -q`：`62 passed in 23.38s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`289 passed, 1 skipped in 23.46s`。
- `py_compile` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/telegram_activity.py`: 新增下载优先、扫描互斥、单 loop 所有权与 context permit API。
- `media_downloader.py`: 入队 intent、worker 激活/取消/释放、旧 queue item 兼容及云上传前释放。
- `module/web.py`: Web package、comment、Prescan Telegram 预览读取接入 permit。
- `tests/module/test_telegram_activity.py`: 覆盖优先级竞态、并行下载、单扫描、取消释放与 loop 所有权。
- `tests/test_media_downloader.py`: 覆盖入队失败/取消、停止、worker 取消/异常、旧 item 与云上传边界。
- `tests/module/test_web.py`: 覆盖三类 Web 预览在扫描 permit 下等待。
- `.superpowers/sdd/task-4-report.md`: 记录 RED/GREEN、取消路径审计、自审与关注项。
- `progress.md`: 追加 Task 4 实施、验证与回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^feat: prioritize telegram downloads over scans$')"` 回滚 Task 4 全部改动。

## 2026-07-16 - Task: Complete Telegram Gate Release Before Cloud Upload

### What was done

- 为 download intent 增加可等待且幂等的 release completion；保留原同步 `release()`，并让同步释放后再等待复用同一次 Condition 计数结算。
- Telegram 下载/转发结束后先等待 active 计数扣减和 scan waiter 通知完成，再进入 rclone/Aligo/云盘上传阶段。
- 将原布尔 fake permit 测试升级为真实 gate 顺序测试，证明已等待的 scan 在 cloud callable 启动前取得 permit。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_telegram_activity.py::test_release_and_wait_finishes_counter_transition_once tests/test_media_downloader.py::MediaDownloaderTestCase::test_cloud_upload_starts_after_telegram_permit_is_released -q`：按预期报缺少 `release_and_wait()` 且云上传早于 scan，`2 failed in 0.94s`。
- GREEN targeted：同一命令通过，`2 passed in 0.73s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_telegram_activity.py tests/test_media_downloader.py tests/module/test_web.py -q`：`63 passed in 23.38s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`290 passed, 1 skipped in 23.81s`。
- `py_compile` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/telegram_activity.py`: 增加每 intent 的 release completion future 和可等待幂等释放。
- `media_downloader.py`: 云上传边界等待 gate 计数与通知结算完成。
- `tests/module/test_telegram_activity.py`: 覆盖同步释放后等待、重复等待和 scan 先行顺序。
- `tests/test_media_downloader.py`: 用真实 gate 验证 cloud callable 不早于等待中的 scan。
- `.superpowers/sdd/task-4-report.md`: 追加 review RED/GREEN、取消审计和自审。
- `progress.md`: 追加本轮 review 修复、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: release telegram gate before cloud upload$')"` 回滚本次 review 修复。

## 2026-07-16 - Task: Full Scan Scheduler, Throttling, And Recovery

### What was done

- 新增由 `Application.loop` 持有的频道库服务与全局单扫描 scheduler，支持线程安全链接解析、频道/超级群校验、最新消息不可变快照、重复 chat ID 去重，以及幂等启动和有界停止。
- 实现全量扫描的升序 50-ID 批次、singleton/list 响应归一化、scan permit、双 checkpoint、成功非末批限速、普通错误三次持久化重试、FloodWait 绝对截止时间、失败区间继续扫描及最终 partial。
- 增加持久化 pause/stop 边界意图和 download-only gate 观察/等待接口，使用户控制在当前请求及事务完成后生效，下载活动触发持久化自动让行并在空闲后重新排队。
- 覆盖权限永久错误、SQLite 写入/失败区间记录错误、包索引错误和 scheduler 取消恢复，确保数据库失败不推进 checkpoint，停止服务不取消进行中的 Telegram 请求。

### Testing

- RED service：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py -q`：收集阶段按预期报 `ModuleNotFoundError: No module named 'module.channel_library_service'`，`1 error in 0.59s`。
- RED store/gate：控制意图和 download-only API 的三个 targeted tests 按预期报缺少 `request_job_control` / `has_download_activity`，`3 failed in 0.06s`。
- RED review：失败区间持久化 SQLite 错误最初从 `_run_job` 逃逸，targeted regression 为 `1 failed in 0.60s`；修复后 `1 passed in 0.47s`。
- RED retry persistence：普通重试延迟正确但 `retry_count` 为 0，targeted regression 为 `1 failed in 0.61s`；修复后 `1 passed in 0.53s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_store.py tests/module/test_channel_library_workflow.py tests/module/test_telegram_activity.py -q`：`75 passed in 1.00s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`311 passed, 1 skipped in 23.71s`。
- `py_compile` 与 `git diff --check`：通过；新 `channel_library_service.py` 无 mypy 诊断，mypy 仍报告依赖模块已有的 24 条基线错误。

### Notes

Changed files:
- `module/channel_library_service.py`: 新增 owner-loop 生命周期、链接解析、全量扫描 scheduler、gate、限速、重试、FloodWait、控制和失败恢复。
- `module/channel_library_store.py`: schema v2 增加边界控制意图，并新增原子控制消费、普通重试、rate-limit deadline 和 open failure 查询。
- `module/telegram_activity.py`: 增加同一 Condition 下的 download-only 活动查询与空闲等待。
- `tests/module/test_channel_library_service.py`: 覆盖 fake-client 批次、生命周期、解析、控制、限速、错误和恢复路径。
- `tests/module/test_channel_library_store.py`: 覆盖 pause/stop 意图跨批持久化和原子消费。
- `tests/module/test_telegram_activity.py`: 覆盖 download-only 查询/等待且不受 scan 状态误阻塞。
- `.superpowers/sdd/task-5-report.md`: 记录 Task 5 RED/GREEN、全量结果、生命周期与错误路径审计。
- `progress.md`: 追加 Task 5 实施、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^feat: add recoverable low-rate channel scans$')"` 回滚 Task 5 全部改动。

## 2026-07-16 - Task: Harden Channel Scan Recovery Invariants

### What was done

- 增加按 canonical SQLite 路径加锁的进程内 service owner guard，在恢复前拒绝第二个 live service，并在 scheduler 正常、异常或取消停止的 finally 中释放所有权。
- 将普通重试改为消费持久化 `retry_count` 的剩余 `[5, 15, 45]` 预算；成功批或耗尽后跳过批在 checkpoint 同事务中归零，FloodWait 保持独立且不计数。
- 新增 library 与首次 full job 的单事务创建/去重，重复提交返回既有 job，legacy `new` 无 job 记录在同事务修复，job insert 失败回滚新 library。
- 增加 v1 无 `control_requested` 数据库到 schema v2 的双次初始化迁移证据，验证既有 library/job 行保留且版本记录不重复。

### Testing

- RED ownership：同路径第二个 service 未拒绝启动，`1 failed in 0.72s`；修复后 `1 passed in 0.57s`。
- RED durable retry：恢复后从 5 秒重新开始、重复重启重复消费首档且成功后计数不清零，`4 failed in 0.76s`；修复后 `4 passed in 0.62s`。
- RED atomic creation：缺少 library+initial-job 单事务 API，`3 failed in 0.08s`；修复后连同迁移证据 `4 passed in 0.03s`。
- Migration evidence：v1→v2 幂等迁移测试首跑即通过，`1 passed in 0.04s`，确认是测试缺口而非新增实现缺陷。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_store.py tests/module/test_channel_library_workflow.py tests/module/test_telegram_activity.py -q`：`83 passed in 1.00s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`319 passed, 1 skipped in 24.12s`。
- `py_compile` 与 `git diff --check`：通过；新 service 无 mypy 诊断，依赖模块仍有既存 24 条基线错误。

### Notes

Changed files:
- `module/channel_library_service.py`: 增加同路径 live service ownership，并从持久化计数恢复剩余重试预算，解析提交改用原子 store API。
- `module/channel_library_store.py`: 增加 library+initial-job 单事务创建/去重/孤儿修复，并在 fetched checkpoint 事务内归零 retry_count。
- `tests/module/test_channel_library_service.py`: 覆盖双 service 互斥与释放、跨重启剩余预算、重复重启上限、成功后新批预算和 duplicate job 返回。
- `tests/module/test_channel_library_store.py`: 覆盖原子创建回滚、重复/孤儿修复、retry reset 事务性及 v1→v2 双初始化迁移。
- `.superpowers/sdd/task-5-report.md`: 追加 review RED/GREEN、ownership、retry、atomicity 和 migration 审计。
- `progress.md`: 追加本次 review 修复、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: harden channel scan recovery invariants$')"` 回滚本次 review 修复。

## 2026-07-16 - Task: Retain Scan Ownership Through Cancelled Stop

### What was done

- 将 service shutdown 从公共 `stop()` 调用方中分离为单个可复用的内部清理任务；调用方取消仍向外传播，但不会取消进行中的 Telegram 请求或 scheduler 清理。
- 所有权保持到请求完成 checkpoint、scheduler 进入终态后才释放；清理期间同 canonical 数据库路径的第二个 service 仍会被拒绝，完成后可正常接管并恢复 queued job。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py::test_cancelled_stop_retains_ownership_until_internal_cleanup_finishes -q`：按预期报缺少 `_shutdown_task`，`1 failed in 0.58s`。
- GREEN targeted：同一命令通过，`1 passed in 0.47s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_store.py tests/module/test_channel_library_workflow.py tests/module/test_telegram_activity.py -q`：`84 passed in 1.01s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`320 passed, 1 skipped in 24.08s`。
- `py_compile` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/channel_library_service.py`: 增加可复用、shielded 的内部 shutdown task，并仅在 scheduler 终态后释放 store ownership。
- `tests/module/test_channel_library_service.py`: 增加取消公共 stop 后仍保持清理、checkpoint 与所有权的确定性回归测试。
- `.superpowers/sdd/task-5-report.md`: 追加取消路径 RED/GREEN 与 ownership 审计。
- `progress.md`: 追加本轮修复、验证与回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: retain scan ownership through cancelled stop$')"` 回滚本次修复。

## 2026-07-16 - Task: Incremental Scan And Failed-Range Repair

### What was done

- 新增从已提交 fetch 水位下一条开始、创建时冻结最新消息 ID 的增量扫描，并复用服务端 1-2 秒低频配置。
- 新增默认全部或指定失败区间的 repair、逐目标持久化 cursor、失败任务按原 kind/snapshot/checkpoint 重试，以及 fetched 领先 indexed 时不重复 Telegram 请求的恢复重建。
- 将 full、incremental 和每个 repair target 统一到同一 range/fetch/index/retry/control 路径，保留 Task 5 的 gate、持久化重试、FloodWait、控制边界、安全停止和全局单例行为。
- repair 批次的媒体元数据与 target cursor 同事务提交；完整不确定闭包的包 revision、index 水位、target 完成和 failure resolved 同事务发布。
- 重算与 `downloading` 包重叠时无修改返回 deferred；runner 等待下载活动清空后只重试已抓取数据的索引发布，不重复 Telegram 请求。

### Testing

- Brief 相对解释器检查：worktree 内 `.venv/bin/python` 不存在，命令在收集前以 exit 127 失败；随后使用主仓库虚拟环境完成全部测试。
- 接管 RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_workflow.py -q`：`7 failed, 35 passed in 0.94s`，失败均为缺少 Task 6 命令或 deferred 结果。
- 补充 RED：共享 runner、repair fetch/cursor 原子性、闭包发布/resolution 原子性、deferred runner 重试四个 targeted tests：`4 failed in 0.60s`，失败均为对应 Task 6 API 缺失。
- 补充 GREEN：同四个 targeted tests：`4 passed in 0.50s`；fetched/indexed 恢复与 deferred/closure targeted：`3 passed in 0.53s`。
- Brief focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_workflow.py tests/module/test_channel_library_store.py -q`：`89 passed in 1.24s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`333 passed, 1 skipped in 24.17s`。
- `py_compile module/channel_library_service.py module/channel_library_store.py module/channel_library_workflow.py` 与 `git diff --check`：通过。
- Targeted mypy：store 既有宽泛 `Mapping[str, object]`/SQLite 类型区域仍有 21 条诊断，service/workflow 无诊断；未扩大为 store 全量类型重构。
- Black check：报告 4 个 touched files 会被重排，且包含大量 Task 6 之外的既有行；为避免全文件格式化和超范围 churn，未执行自动重排。

### Notes

Changed files:
- `module/channel_library_service.py`: 增量/repair/retry 命令、共享 range runner、索引追赶与 deferred 重试。
- `module/channel_library_store.py`: 完成 full 检查、失败锚点、repair cursor 原子 checkpoint、closure resolution 原子发布及 repair retry 克隆。
- `module/channel_library_workflow.py`: deferred 结果与 repair failure 闭包重建参数。
- `tests/module/test_channel_library_service.py`: 增量快照/频率/冲突、repair 选择/恢复、共享 runner、retry、索引追赶与 deferred 重试覆盖。
- `tests/module/test_channel_library_workflow.py`: 新 caption 边界、旧尾包 revision、下载重叠 deferred、repair 两阶段原子性覆盖。
- `.superpowers/sdd/task-6-report.md`: 接管、RED/GREEN、共享 runner、repair/revision 审计和文件清单。
- `progress.md`: 追加本任务实现、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^feat: add incremental and repair scans$')"` 回滚 Task 6；保留 `channel_library.sqlite3`，避免丢失已扫描数据。

## 2026-07-16 - Task: Preserve Repair Uncertainty Across Retries

### What was done

- 修复多失败区间 repair 的重启安全问题：较早 target 的中间索引发布不再缩短或改写其他未解决 failure 的持久化不确定闭包。
- 未解决 failure 的规划闭包取持久值与本轮候选值的最大值；store 使用 SQL `MAX` 再次保证 closure 单调不减，并保持原始 `reindex_anchor_start` 不变。
- repair publication 的 failure update 与 resolution 必须属于同一个显式 active target；只有目标闭包的 package/item revision、index 水位、target completed 和 failure resolved 同事务成功后才解除该 failure 的不确定状态。
- 增加双 failure 的失败重试回归：前一 target 成功，后一 target 耗尽重试并从 failed job 重建，确认 closure 不缩短、最终库 ready 且 active uncertain 包为零。

### Testing

- Review RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py::test_later_repair_closure_survives_earlier_target_and_failed_retry tests/module/test_channel_library_workflow.py::test_repair_closure_publication_and_resolution_commit_atomically -q`：`1 failed, 1 passed in 0.37s`；较晚 failure closure 实际为 `20`，期望保留 `40`。
- Targeted GREEN：同命令最终 `2 passed in 0.56s`。
- Focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_service.py tests/module/test_channel_library_workflow.py tests/module/test_channel_library_store.py -q`：`90 passed in 1.20s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`334 passed, 1 skipped in 24.12s`。
- `py_compile module/channel_library_service.py module/channel_library_store.py module/channel_library_workflow.py` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/channel_library_service.py`: 将 active repair failure ID 贯穿中间与 resolution 索引发布。
- `module/channel_library_store.py`: 强制 repair target 作用域并以 SQL `MAX` 保证 closure 单调。
- `module/channel_library_workflow.py`: 保留持久化 closure，且 repair 只生成当前 target 的 failure update。
- `tests/module/test_channel_library_service.py`: 覆盖双失败区间、后段失败、failed-job retry 和最终无 uncertain 包。
- `tests/module/test_channel_library_workflow.py`: 更新 unresolved closure 单调断言并强化 resolution 失败的双 watermark 回滚证据。
- `.superpowers/sdd/task-6-report.md`: 追加 Critical RED/GREEN、重启链和 closure monotonicity 审计。
- `progress.md`: 追加本 review 修复、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: preserve repair uncertainty across retries$')"` 回滚本次 Critical 修复。

## 2026-07-16 - Task: Filtered Queries, Keyset Pagination, And Persistent Selection

### What was done

- 新增 typed 包筛选、频道/包/包项 keyset 查询，固定实现 Unicode 规范化标题子串、UTC 半开时间、消息区间相交、包含式数量/大小、未知大小 opt-in 和下载状态语义。
- 新增严格 URL-safe base64 JSON cursor 与 200 条分页上限；包页在同一 SQLite 读快照返回结果和 library revision，扫描中插入新包不会令后续页重复或漏掉原结果。
- 新增 revision 绑定的单包选择、全筛选结果选择、清空和汇总；全选使用共享谓词和单次参数化 `INSERT-SELECT`，跳过非稳定包，汇总区分有效选择与明确失效原因。

### Testing

- RED：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_queries.py -q`：按预期在收集阶段报缺少 `PackageFilter`，`1 error in 0.04s`。
- GREEN query：同命令实现后 `15 passed in 0.19s`。
- GREEN focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_queries.py tests/module/test_channel_library_store.py -q`：`57 passed in 0.45s`。
- Targeted keyset/selection：插入期间分页与跨页全选两个测试 `2 passed in 0.13s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`349 passed, 1 skipped in 24.68s`。
- `py_compile module/channel_library_store.py tests/module/test_channel_library_queries.py` 与 `git diff --check`：通过；store mypy 与 base commit 均为既存 22 条宽泛 SQLite/Mapping 类型诊断，本轮无新增。

### Notes

Changed files:
- `module/channel_library_store.py`: 增加 typed filters、固定 SQL 谓词、严格 cursors、三类查询和 revision 绑定选择 APIs。
- `tests/module/test_channel_library_queries.py`: 覆盖筛选边界、SQL 字面匹配、keyset 稳定性、分页上限、明细、持久选择和 revision 失效。
- `.superpowers/sdd/task-7-report.md`: 记录 RED/GREEN/full、filter/cursor SQL 审计及 selection/revision 审计。
- `progress.md`: 追加 Task 7 实施、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^feat: query and select channel packages$')"` 回滚 Task 7 查询与选择改动。

## 2026-07-16 - Task: Bound Channel Package Cursor Integers

### What was done

- 为包 cursor 的 `start_message_id` 和 `id` 增加 SQLite signed 64-bit 上界校验；超过 `2**63 - 1` 的整数在 decode 阶段统一返回 malformed-cursor `ValueError`，不再泄漏 SQLite bind `OverflowError`。
- 保留既有负数、bool、非整数及严格 shape/key 校验，并验证合法最大值可进入参数化 keyset 查询。

### Testing

- RED：两个字段分别使用 `2**63` 的 targeted 回归为 `2 failed, 1 passed in 0.07s`；两例均在 SQLite bind 处抛出 `OverflowError`，`2**63 - 1` 合法例通过。
- Targeted GREEN：同三个用例 `3 passed in 0.02s`。
- Focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/module/test_channel_library_queries.py tests/module/test_channel_library_store.py -q`：`60 passed in 0.47s`。
- Full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`352 passed, 1 skipped in 24.47s`。
- `py_compile module/channel_library_store.py tests/module/test_channel_library_queries.py` 与 `git diff --check`：通过。

### Notes

Changed files:
- `module/channel_library_store.py`: cursor decode 增加 SQLite 最大整数上界。
- `tests/module/test_channel_library_queries.py`: 覆盖两个 cursor 字段越界及合法最大值绑定。
- `.superpowers/sdd/task-7-report.md`: 追加 Important review RED/GREEN/full 与边界审计。
- `progress.md`: 追加 cursor 整数边界修复、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: bound channel package cursor integers$')"` 回滚本次 cursor 上界修复。

## 2026-07-16 - Task: Dispatch Channel Package Download Batches

### What was done

- 实现频道库下载批次的持久化 outbox/saga：频道事务先校验终态库、稳定 selection revision、历史成功与 active duplicate，再原子保存 batch/package/item 不可变快照和 queued 摘要；事务提交后才幂等创建确定性 Web task 并标记 dispatched。
- 实现 pending startup replay、终态对账、精确快照 ID 重取和逐包串行下载；真实缺失、读取失败、上传失败、完整文件跳过和取消分别持久化，不以父任务累计计数推导包结果。
- 扩展现有预扫包下载为一次父任务生命周期和可等待逐包回调；失败显式重下不清除历史成功事实，不同 idempotency key 不能并发圈入 active 包。
- 补充跨库故障窗口、真实 SQLite TaskState、多包生命周期、不可变命名快照、结果分类、取消、对账和重复保护文档及测试。

### Testing

- RED：`TaskStateStore.ensure_task` 缺失为 `1 failed`；多包 callback/result 为 `2 failed`；初始 outbox API 为 `5 failed`；immutable runner、refetch error、cancel window 和 active duplicate 各自先得到预期 `1 failed`。
- Initial focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/test_channel_library_download.py tests/test_media_downloader.py tests/module/test_task_state.py -q`：`48 passed in 23.45s`。
- Upload focused：加 `tests/test_web_upload_progress.py`：`59 passed in 23.62s`。
- Channel regressions：频道 store/service/workflow/query `108 passed in 1.65s`；旧评论包兼容用例 `2 passed`。
- Final targeted：`tests/test_channel_library_download.py -q` 为 `11 passed in 1.01s`；media/TaskState/upload 为 `49 passed in 23.62s`。
- Authoritative full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`366 passed, 1 skipped in 24.73s`。
- `py_compile` 与 `git diff --check`：通过。
- Mypy 在分析项目文件前被已安装 `markupsafe/_speedups.pyi` positional-only 语法错误阻断；显式 `--python-version 3.11` 结果相同。
- Black check 报告 6 个 touched 大文件会被重排；为避免全文件格式化和超范围 churn，未执行自动重排。

### Notes

Changed files:
- `media_downloader.py`: 包级结果、完整文件/未找到标记、一次父生命周期和可等待 callback。
- `module/channel_library_service.py`: 确定性任务派发、pending replay、对账、不可变快照 runner 和取消落盘。
- `module/channel_library_store.py`: 原子批次快照、active duplicate 校验、attempt/summary 状态持久化。
- `module/task_state.py`: 不回退既有任务状态的幂等 `ensure_task`。
- `tests/test_channel_library_download.py`: 三个 crash window、snapshot/dispatch/reconcile/result/cancel/duplicate 覆盖。
- `tests/test_media_downloader.py`: 真实 TaskState 多包父生命周期与逐包结果覆盖。
- `tests/module/test_task_state.py`: 确定性任务跨重启幂等覆盖。
- `docs/channel-library-download-outbox.md`: 两库 saga 顺序、状态语义和恢复说明。
- `.superpowers/sdd/task-8-report.md`: RED/GREEN、故障窗口、生命周期、验证与静态缺口审计。
- `progress.md`: 追加本任务实现、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^feat: dispatch channel package download batches$')"` 回滚 Task 8；保留两个 SQLite 文件，避免误删既有任务和频道库历史。

## 2026-07-16 - Task: Harden Channel Download Saga Consistency

### What was done

- 将 active package 排他判断改为事务内查询非终态 batch-package attempt，索引发布即使改写 package 摘要也不能让另一 idempotency key 重复圈入同一包。
- 为确定性 Web task 增加不可变身份校验；匹配的 active/terminal task 原样保留，冲突任务保持 batch `pending_dispatch` 并只记录稳定错误码。
- 修正混合终态逐包文件证据对账、正常返回的用户停止、缺失消息快照顺序及 TEXT 布尔重建；父任务、当前包和未启动包得到一致终态。
- 将频道下载 saga、包 callback 和上传异常的持久错误收口为 allow-listed 稳定码；原始异常仅写服务端日志，不进入频道下载行或 Web task/file error。

### Testing

- Review RED：11 个新增控制/回归用例首次组合执行为 `9 failed, 2 passed in 0.99s`；失败分别证明 active summary 绕过、task identity 冲突未拦截、mixed reconciliation 回退、raw refetch/callback error、正常 stop 父任务误终态、`"0"` 布尔误判和中间缺失 ID 顺序丢失。
- Review GREEN：同 11 个用例 `11 passed in 0.89s`。
- Task 8 focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/test_channel_library_download.py tests/test_media_downloader.py tests/module/test_task_state.py -q`：`61 passed in 24.18s`。
- Upload-inclusive：在 focused 命令追加 `tests/test_web_upload_progress.py`：`70 passed in 23.62s`。
- Channel regressions：store/service/workflow/query `108 passed in 1.70s`。
- Authoritative full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`376 passed, 1 skipped in 25.12s`。
- `py_compile` 与 `git diff --check`：通过。Mypy 仍在项目完整分析前被 `markupsafe/_speedups.pyi` 解析错误及 3 个第三方包缺少 typing marker 阻断；Black check 报 6 个既有大文件会被全文件重排，未自动格式化以避免超范围 churn。

### Notes

Changed files:
- `media_downloader.py`: 保留不可变消息顺序、包装 callback 异常并用稳定上传错误码。
- `module/channel_library_service.py`: 身份冲突 pending 语义、mixed reconciliation、stop 覆盖、显式布尔解析和 saga 错误脱敏。
- `module/channel_library_store.py`: attempt 表 active 排他、dispatch error 落盘及下载错误 allow-list。
- `module/prescan_workflow.py`: 向包结果适配器传递可选原始消息 ID 顺序。
- `module/task_state.py`: 确定性任务身份冲突和下载生命周期中的身份保持。
- `tests/test_channel_library_download.py`: 覆盖复审的排他、派发、对账、取消、安全和布尔问题。
- `tests/test_media_downloader.py`: 覆盖中间消息缺失时的结果/callback 快照顺序。
- `tests/module/test_task_state.py`: 覆盖匹配 terminal task 保留和 corrupt identity 拒绝。
- `docs/channel-library-download-outbox.md`: 补充身份、错误、取消和混合终态契约。
- `.superpowers/sdd/task-8-report.md`: 追加复审 RED/GREEN、故障窗口、生命周期和安全审计。
- `progress.md`: 追加本次复审修复、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: harden channel download saga consistency$')"` 回滚本次复审修复；不删除两个 SQLite 文件。

## 2026-07-16 - Task: Snapshot Channel Batch Execution Identity

### What was done

- 将频道标题作为不可变 `channel_title` 在 batch 创建事务内保存；Web task identity 和 recommended-C channel naming 只读取 batch 快照，频道后续改名不影响 crash replay 或执行命名。
- 将频道库 schema 升至 v3；新库使用非空标题列，旧库幂等新增并一次性回填，v1/v2 迁移记录和既有数据保持。
- 将取消处理提升到完整 runner 生命周期，覆盖等待 Telegram gate、阻塞 refetch 和 downloader；取消后稳定释放 permit、清理 active node，并将父任务和所有非终态包落为 cancelled。
- 增加以 `(channel DB path, batch_id)` 为键的单进程 runner claim；跨 service 同批并发在 refetch 前拒绝，started 的零行更新报状态冲突，进程重启重新调度前原子归一化 stale downloading attempts。

### Testing

- Re-review RED：标题迁移/replay/runner、两个 pre-refetch 取消点、同批并发、started 冲突和 restart resume 组合为 `8 failed in 2.59s`；跨 service process-local claim 强化用例另为 `1 failed in 1.00s`。
- Re-review GREEN：最终 8 个边界用例 `8 passed in 0.83s`。
- Task 8 focused：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest tests/test_channel_library_download.py tests/test_media_downloader.py tests/module/test_task_state.py -q`：`66 passed in 23.95s`。
- Upload-inclusive：在 focused 命令追加 `tests/test_web_upload_progress.py`：`75 passed in 23.77s`。
- Channel regressions：store/service/workflow/query `108 passed in 1.62s`。
- Authoritative full suite：`/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`：`381 passed, 1 skipped in 25.05s`。
- `py_compile` 与 `git diff --check`：通过。Mypy 仍在完整项目分析前被 `markupsafe` stub 解析错误和 3 个第三方包缺少 typing marker 阻断；Black check 报本轮 4 个大文件会被全文件重排，未自动格式化。

### Notes

Changed files:
- `module/channel_library_store.py`: schema v3 标题快照迁移、batch 创建快照、started 冲突和 stale runner 归一化。
- `module/channel_library_service.py`: batch 标题消费、全阶段取消清理和跨 service 单进程 runner claim。
- `tests/module/test_channel_library_store.py`: 覆盖 v1→v3 幂等迁移和列保留。
- `tests/test_channel_library_download.py`: 覆盖 rename crash replay、命名快照、gate/refetch 取消、并发 claim、状态冲突和 restart resume。
- `docs/channel-library-download-outbox.md`: 补充 v3 标题快照、全阶段取消和 runner ownership/restart 契约。
- `.superpowers/sdd/task-8-report.md`: 追加二次复审 RED/GREEN 与三项边界审计。
- `progress.md`: 追加本轮改动、验证和回滚记录。

Rollback:
- 执行 `git revert "$(git rev-list -1 --all --grep='^fix: snapshot channel batch execution identity$')"` 回滚代码；SQLite v3 新增列保留为空闲兼容字段，不执行破坏性降级或删列。

## 2026-07-16 - Task: Expose authenticated channel library Web APIs and lifecycle

### What was done

- Added login-protected channel library, scan, package/item, selection, and idempotent download-batch APIs with session-bound CSRF on every mutation, strict primitive/range validation, and stable safe error envelopes.
- Added atomic library overview/versioned deletion store operations and owner-loop-only incremental/download scheduling, including startup recovery/replay/reconciliation and shutdown-safe service task cancellation.
- Wired the channel service after Telegram startup and stopped it before Telegram shutdown/general task cancellation; initialization failures leave the Web server available with channel routes returning safe `503` responses.
- Documented the API bodies/statuses, authentication/CSRF contract, owner-loop boundary, lifecycle behavior, and timeout semantics.

### Testing

- RED: `.venv/bin/python -m pytest tests/module/test_channel_library_web.py -q` -> 28 failed in 1.17s from the expected missing routes and lifecycle/scheduling helpers.
- Lifecycle cleanup RED: `.venv/bin/python -m pytest tests/module/test_channel_library_web.py::test_service_start_cleans_owner_tasks_when_pending_schedule_fails -q` -> 1 failed because a partial startup left the scheduler pending.
- GREEN: `.venv/bin/python -m pytest tests/module/test_channel_library_web.py -q` -> 29 passed.
- Requested Web regressions: `.venv/bin/python -m pytest tests/module/test_channel_library_web.py tests/module/test_web.py tests/test_web_cancel_task.py tests/test_web_prescan_retention.py -q` -> 67 passed in 1.04s.
- Expanded channel/downloader regressions: `.venv/bin/python -m pytest tests/module/test_channel_library_store.py tests/module/test_channel_library_queries.py tests/module/test_channel_library_service.py tests/test_channel_library_download.py tests/test_media_downloader.py tests/module/test_task_state.py -q` -> 159 passed in 24.35s.
- Full suite: `.venv/bin/python -m pytest -q` -> 410 passed, 1 skipped in 24.86s.
- `python -m py_compile` for touched Python modules/tests and `git diff --check` passed.
- `pylint --errors-only` ran but remains non-clean from existing pylintrc/astroid issues and the pre-existing `media_downloader.py:2953` undefined `STARTUP_SCAN_WINDOW_SEC` monitor finding; no new Task 9 runtime or compile failure was found.

### Notes

Changed files:
- `module/web.py`: Added authenticated channel library routes, CSRF, validation, safe serialization, and status mapping.
- `module/channel_library_store.py`: Added overview/version helpers, atomic guarded deletion, and idempotency-key lookup.
- `module/channel_library_service.py`: Added owner-loop incremental submission, exactly-once process-local batch task scheduling, and startup/shutdown cleanup.
- `media_downloader.py`: Wired channel service startup after Telegram and shutdown before Telegram/general tasks.
- `tests/module/test_channel_library_web.py`: Added endpoint, security, storage race, scheduling, and lifecycle contracts.
- `tests/test_media_downloader.py`: Isolated legacy `main()` tests from production-named channel database creation.
- `docs/web-control-console.md`: Documented the channel API/auth/lifecycle contract.
- `progress.md`: Added Task 9 implementation and verification evidence.

Rollback:
- Run `git revert "$(git rev-list -1 --all --grep='^feat: expose channel library web api$')"`; preserve `channel_library.sqlite3` because rollback must not delete persisted channel indexes or download history.

## 2026-07-16 - Task: Harden channel Web API races after review

### What was done

- Made CSRF rejection read-only so only the authenticated token GET can create session state.
- Moved download-batch create/replay classification into the atomic store transaction and made same-key replay repair pending dispatch before returning.
- Added lock-protected owner-loop command admission/tracking so shutdown rejects new work and drains every accepted link, incremental, and batch-scheduling command before cleanup.
- Hardened versioned deletion against divergent terminal-parent/active-child download state and made every Task 9 route reject undocumented query/body inputs.

### Testing

- CSRF RED/GREEN: `2 failed, 2 passed` -> `4 passed` after corrected cookie-jar assertions.
- Idempotency RED/GREEN: `3 failed` -> `3 passed` for atomic creation, concurrent 202/200, and pending-dispatch repair.
- Lifecycle RED/GREEN: `4 failed` -> `4 passed` for command drain/rejection/scheduled-not-started and client-stop ordering.
- Delete RED/GREEN: divergent parent/child case `1 failed` -> delete group `2 passed`.
- Strict-input RED/GREEN: `24 failed, 3 passed` -> `27 passed`; complete channel Web contract `70 passed in 1.33s`.
- Route/lifecycle: `106 passed in 2.14s`.
- Requested Web/cancel/retention: `108 passed in 1.74s`.
- Expanded channel/download regressions: `162 passed in 24.25s`.
- Full suite: `454 passed, 1 skipped in 25.25s`.
- Touched-file `python -m py_compile` and `git diff --check` passed.

### Notes

Changed files:
- `module/web.py`: Read-only CSRF rejection, no Web idempotency pre-check, and complete strict-input validation.
- `module/channel_library_store.py`: Atomic batch creation result and direct active child-attempt delete guard.
- `module/channel_library_service.py`: Atomic batch result adapter and thread-safe accepted-command lifecycle tracking.
- `media_downloader.py`: Clears the published service before awaiting shutdown.
- `tests/module/test_channel_library_web.py`: Adds cookie, concurrency, dispatch repair, delete divergence, route matrix, and shutdown-order regressions.
- `tests/module/test_channel_library_service.py`: Adds blocking command drain/rejection and scheduled-not-started coverage.
- `docs/web-control-console.md`: Documents the hardened CSRF, idempotency, validation, delete, and shutdown contracts.
- `.superpowers/sdd/task-9-report.md`: Appends review RED/GREEN and updated security/race audits.
- `progress.md`: Appends review-fix evidence and rollback guidance.

Rollback:
- Run `git revert "$(git rev-list -1 --all --grep='^fix: harden channel web api races$')"`; preserve both SQLite databases and do not delete persisted channel or Web task state.

## 2026-07-16 - Task: Approve channel Web API review

### What was done

- Recorded independent approval of the complete Task 9 API, CSRF, idempotency, deletion, strict-input, and shutdown lifecycle implementation after all five Important review findings were closed.
- Marked Task 9 complete in the implementation plan and SDD ledger, and corrected stale internal report wording for the tracked owner-loop command path.

### Testing

- Read-only independent review of `e3cf66a..4ed6770` found no Critical or Important issues; the reviewer did not rerun tests and relied on the recorded `454 passed, 1 skipped` verification.
- `git diff --check` will be rerun before committing this review record.

### Notes

Changed files:
- `docs/superpowers/plans/2026-07-16-web-full-channel-library.md`: Marked all Task 9 implementation steps complete.
- `.superpowers/sdd/progress.md`: Marked Task 9 review clean.
- `.superpowers/sdd/task-9-report.md`: Corrected the owner-loop scheduling description.
- `progress.md`: Appended Task 9 review approval evidence.

Rollback:
- Revert the review-record commit only; do not revert the approved Task 9 implementation or modify either SQLite database.

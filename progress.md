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

## 2026-07-16 - Task: Add the channel library Web tab

### What was done

- Added a fourth same-SPA channel library tab with paginated channel navigation, full package filters, server-backed selection, package/item keyset pagination, scan controls, download/delete confirmations, and active-tab-only polling.
- Added request-generation and loading guards so delayed detail/package/item responses cannot mix data after switching channels, and revision changes reset stale pages and expanded item caches.
- Added responsive desktop/tablet/mobile layouts, keyboard tab navigation, visible download-disabled reasons, server-relative scan progress, explicit redownload classification, and escaped rendering for all Telegram metadata.
- Completed independent adversarial review with no remaining findings and browser-tested every required library/package state.

### Testing

- Independent Task 10 review: approve, no remaining findings; reviewer focused suite `90 passed`; `git diff --check` passed.
- Authoritative full suite: `/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/bin/python -m pytest -q`: `474 passed, 1 skipped in 25.41s`.
- Automated browser verification passed at 1440x900, 1024x768, and 390x844, including delayed channel A-to-B switching, all seven cursor-paginated channel states, ArrowLeft/ArrowRight navigation, inactive-tab polling stop, visible disabled reason, XSS node absence, page overflow, and mobile internal table scrolling.
- Fresh screenshots `/tmp/channel-library-1440x900-current.png`, `/tmp/channel-library-1024x768-current.png`, and `/tmp/channel-library-390x844-current.png` were visually inspected; no overlap, blank content, nested cards, or inaccessible primary controls were found.

### Notes

Changed files:
- `module/templates/index.html`: Added the channel library SPA surface and state-aware interactions.
- `module/static/css/index.css`: Added restrained responsive channel library layout and mobile overflow handling.
- `module/channel_library_store.py`: Added the typed explicit-redownload conflict used by the Web workflow.
- `module/web.py`: Added range-relative scan progress and the stable `redownload_required` response.
- `tests/module/test_channel_library_web.py`: Added API, DOM, accessibility, state, security, and async identity contracts.
- `docs/superpowers/plans/2026-07-16-web-full-channel-library.md`: Marked Task 10 complete.
- `.superpowers/sdd/progress.md`: Recorded Task 10 review completion.
- `.superpowers/sdd/task-10-report.md`: Recorded review and browser evidence.
- `progress.md`: Appended Task 10 implementation, verification, and rollback evidence.

Rollback:
- Revert the Task 10 commit; preserve `channel_library.sqlite3` and `web_tasks.sqlite3` because the Web view rollback must not remove persisted channel indexes, selections, or download history.

## 2026-07-16 - Task: Verify the full channel library workflow

### What was done

- Added a no-network, no-wait 15,000-ID acceptance workflow that runs exactly 300 batches, simulates process loss after a committed fetch/index checkpoint, rebuilds the store and service, resumes from the next ID, and proves 300 stable packages have unique package/item keys.
- Verified keyset filtering, cross-page selection persistence across another store reconstruction, immutable sorted batch snapshots, idempotent fake Web-task dispatch, and one task identity per persisted batch.
- Audited the existing automated evidence for outbox crash windows, Telegram gate races, fetch/index recovery, FloodWait deadlines, packages over 500 media, failure closure/repair, revisions and supersede/outdated states, selection invalidation, keyset publication, CSRF/delete/0600 safety, and parent download lifecycle.
- Documented channel-library links, conservative timing, automatic download priority, statuses, filters, partial repair, duplicate protection, manual incrementals, API contracts, database security, consistent backup, and rollback.

### Testing

- Worktree-local brief command: `.venv/bin/python -m pytest tests/test_channel_library_e2e.py -q` -> exit 127, `zsh:1: no such file or directory: .venv/bin/python`; the existing repository environment at `../../.venv` was used instead.
- Final E2E: `../../.venv/bin/python -m pytest tests/test_channel_library_e2e.py -q` -> `1 passed in 1.13s`.
- Focused channel/downloader fault contracts: `../../.venv/bin/python -m pytest tests/test_channel_library_e2e.py tests/module/test_channel_library_store.py tests/module/test_channel_library_workflow.py tests/module/test_channel_library_service.py tests/module/test_channel_library_queries.py tests/test_channel_library_download.py tests/module/test_channel_library_web.py tests/module/test_telegram_activity.py tests/test_media_downloader.py -q` -> `265 passed in 28.04s`.
- Final full suite: `../../.venv/bin/python -m pytest tests/ -q` -> `475 passed, 1 skipped in 26.10s`.
- Pylint: `../../.venv/bin/python -m pylint --errors-only module/channel_library_store.py module/channel_library_workflow.py module/channel_library_service.py module/telegram_activity.py module/web.py media_downloader.py` -> exit 14 from existing pylintrc option drift, `os`/Pyrogram no-member inference findings, and `media_downloader.py:2952` undefined `STARTUP_SCAN_WINDOW_SEC`; Task 11 changed no production Python and does not claim this command passed.
- Mypy: `../../.venv/bin/python -m mypy module/channel_library_store.py module/channel_library_workflow.py module/channel_library_service.py module/telegram_activity.py` -> exit 2 with four blocking errors: missing type markers/stubs for `psutil`, `flask_login`, and `ply`, plus `markupsafe/_speedups.pyi:1` reporting positional-only parameters unsupported; checking stopped before completion and is not claimed as passed.
- `git diff --check` passed.

### Notes

Changed files:
- `tests/test_channel_library_e2e.py`: Added the 15,000-ID restart, query, selection, and fake download-bridge acceptance workflow.
- `README_CN.md`: Added concise Channel Library usage, pacing, status, repair, incremental, and duplicate-protection guidance.
- `docs/web-control-console.md`: Added complete user workflow and secure database backup/rollback operations.
- `progress.md`: Appended Task 11 implementation and exact verification evidence.

Rollback:
- Run `git revert "$(git rev-list -1 --all --grep='^test: verify full channel library workflow$')"`; preserve `channel_library.sqlite3` and `web_tasks.sqlite3` because reverting tests/docs must not delete persisted channel or task data.

## 2026-07-16 - Task: Correct Task 11 acceptance evidence after review

### What was done

- Appended this correction after independent review; the earlier Task 11 entry remains unchanged.
- Extended the 15,000-ID E2E to schedule the real `ChannelLibraryService.run_download_batch` path through the real `download_prescan_packages` serial loop, while replacing only bottom-level media IO and bot status reporting.
- Separated 50-ID scan calls from package refetches, recorded package ranges/order/execution counts and active concurrency, and proved five ascending packages run once with `max_active == 1`, one process-local task, and completed package/batch/Web-task states.
- Added an exact `(4.0, 6.0)` random-range spy assertion for all 299 no-wait delay calls, documented the 300-batch timing example and ID-range accounting, and added the `redownload_required` API error code.

### Testing

- Fixture RED: `../../.venv/bin/python -m pytest tests/test_channel_library_e2e.py -q` -> `1 failed in 1.02s`; the extracted fake message constructor referenced removed local variables, so the service correctly marked the scan failed. The test fixture was corrected without production changes.
- Final E2E: `../../.venv/bin/python -m pytest tests/test_channel_library_e2e.py -q` -> `1 passed in 1.42s`.
- Focused channel/downloader contracts: `../../.venv/bin/python -m pytest tests/test_channel_library_e2e.py tests/module/test_channel_library_store.py tests/module/test_channel_library_workflow.py tests/module/test_channel_library_service.py tests/module/test_channel_library_queries.py tests/test_channel_library_download.py tests/module/test_channel_library_web.py tests/module/test_telegram_activity.py tests/test_media_downloader.py -q` -> `265 passed in 25.62s`.
- Full suite: `../../.venv/bin/python -m pytest tests/ -q` -> `475 passed, 1 skipped in 26.65s`.
- `git diff --check` passed before this append and was rerun after all tracked edits.
- Pylint was not rerun because Task 11 review requested the already recorded output be cited exactly. Original command and output, reproduced line for line:

```text
$ ../../.venv/bin/python -m pylint --errors-only module/channel_library_store.py module/channel_library_workflow.py module/channel_library_service.py module/telegram_activity.py module/web.py media_downloader.py
************* Module /Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.worktrees/web-full-channel-library/pylintrc
pylintrc:1: [W0012(unknown-option-value), ] Unknown option value for '--disable', expected a valid pylint message and got 'redefined-variable-type'
pylintrc:1: [R0022(useless-option-value), ] Useless option value for '--disable', 'bad-continuation' was removed from pylint, see https://github.com/PyCQA/pylint/pull/3571.
************* Module module.channel_library_store
module/channel_library_store.py:611: [E1101(no-member), ChannelLibraryStore.initialize] Module 'os' has no 'chmod' member
************* Module module.web
module/web.py:156: [E1101(no-member), _web_auth_file_path] Module 'os' has no 'environ' member
module/web.py:159: [E1101(no-member), _web_auth_file_path] Module 'os' has no 'path' member
module/web.py:181: [E1101(no-member), _write_local_auth_file] Module 'os' has no 'open' member
module/web.py:183: [E1101(no-member), _write_local_auth_file] Module 'os' has no 'O_WRONLY' member
module/web.py:183: [E1101(no-member), _write_local_auth_file] Module 'os' has no 'O_CREAT' member
module/web.py:183: [E1101(no-member), _write_local_auth_file] Module 'os' has no 'O_TRUNC' member
module/web.py:186: [E1101(no-member), _write_local_auth_file] Module 'os' has no 'fdopen' member
module/web.py:1021: [E1101(no-member), get_download_list] Module 'os' has no 'path' member
************* Module media_downloader
media_downloader.py:301: [E1101(no-member), _check_download_finish] Module 'os' has no 'path' member
media_downloader.py:312: [E1101(no-member), _check_download_finish] Module 'os' has no 'remove' member
media_downloader.py:332: [E1101(no-member), _move_to_download_path] Module 'os' has no 'path' member
media_downloader.py:333: [E1101(no-member), _move_to_download_path] Module 'os' has no 'makedirs' member
media_downloader.py:395: [E1101(no-member), _is_exist] Module 'os' has no 'path' member
media_downloader.py:395: [E1101(no-member), _is_exist] Module 'os' has no 'path' member
media_downloader.py:459: [E1101(no-member), _get_media_meta] Module 'os' has no 'path' member
media_downloader.py:461: [E1101(no-member), _get_media_meta] Module 'os' has no 'path' member
media_downloader.py:473: [E1101(no-member), _get_media_meta] Module 'os' has no 'path' member
media_downloader.py:473: [E1101(no-member), _get_media_meta] Module 'os' has no 'path' member
media_downloader.py:474: [E1101(no-member), _get_media_meta] Module 'os' has no 'path' member
media_downloader.py:585: [E1101(no-member), _get_media_meta] Module 'os' has no 'path' member
media_downloader.py:587: [E1101(no-member), _get_media_meta] Module 'os' has no 'path' member
media_downloader.py:722: [E1101(no-member), save_msg_to_file] Module 'os' has no 'path' member
media_downloader.py:728: [E1101(no-member), save_msg_to_file] Module 'os' has no 'makedirs' member
media_downloader.py:728: [E1101(no-member), save_msg_to_file] Module 'os' has no 'path' member
media_downloader.py:832: [E1101(no-member), download_task] Module 'os' has no 'path' member
media_downloader.py:833: [E1101(no-member), download_task] Module 'os' has no 'path' member
media_downloader.py:867: [E1101(no-member), download_task] Module 'os' has no 'path' member
media_downloader.py:1109: [E1101(no-member), download_media] Module 'pyrogram.errors' has no 'NotFound' member
media_downloader.py:1138: [E1101(no-member), download_media] Module 'os' has no 'path' member
media_downloader.py:1204: [E1101(no-member), download_media] Module 'os' has no 'path' member
media_downloader.py:1208: [E1101(no-member), download_media] Module 'os' has no 'remove' member
media_downloader.py:1215: [E1101(no-member), download_media] Module 'os' has no 'path' member
media_downloader.py:1216: [E1101(no-member), download_media] Module 'os' has no 'path' member
media_downloader.py:1221: [E1101(no-member), download_media] Module 'os' has no 'remove' member
media_downloader.py:1388: [E1101(no-member), _check_config] Module 'os' has no 'path' member
media_downloader.py:2952: [E0602(undefined-variable), main._init_baseline] Undefined variable 'STARTUP_SCAN_WINDOW_SEC'
```

- Pylint summary: exit 14; the command did not pass. Task 11 changes no production Python.
- Mypy was not rerun because Task 11 review requested the already recorded output be cited exactly. Original command and output, reproduced line for line:

```text
$ ../../.venv/bin/python -m mypy module/channel_library_store.py module/channel_library_workflow.py module/channel_library_service.py module/telegram_activity.py
module/web.py:17: error: Skipping analyzing "psutil": module is installed, but missing library stubs or py.typed marker
module/web.py:17: note: See https://mypy.readthedocs.io/en/stable/running_mypy.html#missing-imports
module/web.py:19: error: Skipping analyzing "flask_login": module is installed, but missing library stubs or py.typed marker
module/filter.py:7: error: Skipping analyzing "ply": module is installed, but missing library stubs or py.typed marker
/Users/wangyichuan/Desktop/wangcodemac/telegram_media_downloader/.venv/lib/python3.11/site-packages/markupsafe/_speedups.pyi:1: error: Positional-only parameters are only supported in Python 3.8 and greater
Found 4 errors in 3 files (errors prevented further checking)
```

- Mypy summary: exit 2; four errors in three files prevented further checking, so the command did not pass.

### Notes

Changed files:
- `tests/test_channel_library_e2e.py`: Exercised the real serial package download path and strengthened pacing/idempotent scheduling assertions.
- `README_CN.md`: Corrected ID-range timing guidance with the 15,000-ID example and delay caveats.
- `docs/web-control-console.md`: Corrected operational timing/accounting and documented `redownload_required`.
- `progress.md`: Appended this review correction and exact prior static-check output.

Rollback:
- Run `git revert "$(git rev-list -1 --all --grep='^fix: complete channel library acceptance evidence$')"`; preserve both SQLite databases because the review fix changes only tests and documentation.

## 2026-07-16 - Task 12 (part 1): Final whole-branch review and resource fixes

### What was done

- Ran the two-stage final review over the full `db986e9..HEAD` diff against the design spec: one spec-compliance reviewer and one code-quality/security reviewer.
  - Spec compliance: **PASS WITH MINOR** — every hard constraint verified in code (single global scan on `Application.loop`, download-priority gate + upload non-blocking, dual watermarks, restart recovery with preserved `wait_until`, outbox saga crash windows, >500-item non-truncation, keyset paging + `library_revision`, package-scoped completion, CSRF + escaping, separate WAL DB at 0600, no new deps). Only two P2 notes.
  - Code quality/security: correctness/concurrency/security core verified good by both reviewers; verdict **NEEDS FIXES** driven by resource behavior against the 1 vCPU / 1 GiB target.
- Fixed the two clearly-actionable, contract-preserving resource findings:
  - Added `ChannelLibraryStore.list_active_download_batches()` that filters `dispatch_status='dispatched' AND status IN ('queued','downloading')` in SQL (index `idx_channel_download_batches_dispatch`), and switched `schedule_pending_download_batches` and `reconcile_download_batches` to it. Previously both loaded every historical batch (including terminal ones) fully into memory on each startup/call and filtered in Python; terminal history grows unbounded. Behaviour is unchanged — the Python guard selected exactly this subset.
  - Widened the channel-library tab poll interval from 1s to 3s. The overview list fans out one `get_library_overview` (five COUNT aggregates, incl. `channel_media_messages`) per library each tick; scans only advance every 4-6s, so 1s polling wastes the single vCPU with no freshness benefit.

### Testing

- New focused test `tests/test_channel_library_download.py::test_list_active_download_batches_excludes_terminal_and_undispatched` -> `1 passed`.
- Focused: `../../.venv/bin/python -m pytest tests/test_channel_library_download.py tests/module/test_channel_library_service.py tests/test_channel_library_e2e.py -q` -> `61 passed`.
- Full suite: `../../.venv/bin/python -m pytest tests/ -q` -> `476 passed, 1 skipped in 25.66s`.
- `../../.venv/bin/python -m pylint --errors-only module/channel_library_store.py module/channel_library_service.py` -> no new errors (only the pre-existing `os`/`pyrogram` E1101 false positives and the `pylintrc` W0012/R0022 header noise already recorded in the Task 11 entry).
- `git diff --check` -> clean.

### Notes

Accepted findings (recorded with technical reasoning, not fixed pre-deploy — none is a correctness/security/data-loss defect):

- **Large "download all" batch creation is unbounded** (`create_download_batch_result` / `get_download_batch`). Selecting many thousands of packages copies every package+item into the snapshot tables inside one `BEGIN IMMEDIATE` and materializes the whole batch in memory. Risk is user-triggered, atomic (rolls back on failure, no partial batch or data loss), and recoverable by restart. A hard selection cap would change the feature's stated "full channel" contract, so it is left as the top follow-up (chunked/streamed batch creation). Single-operator scale keeps realistic exposure low.
- **O(n^2) reindex window when an early scan failure stays open.** An unresolved low-anchor failure forces reindex-from-anchor on every later batch until repaired. Situational (needs an unresolved early transient failure); fixing touches the indexing/repair logic both reviewers verified as correct, so deferred rather than risk a regression at deploy time.
- **WAL/SHM sidecars are not chmod 0600** and 0600 tightening is not logged. Spec only mandates 0600 on the main `.sqlite3` file; impact limited to other local users on a single-tenant VPS.
- **Incremental "latest message" read uses `scan_permit()` vs `download_permit()`** for the link-resolve path (spec P2-1). Both preserve the no-concurrent-API invariant; cosmetic.
- **Deterministic-task-id conflict would strand a batch as `pending_dispatch`.** Requires a `uuid5(library_id:key)` collision with a different prior task — effectively impossible.

Changed files:
- `module/channel_library_store.py`: Added `list_active_download_batches()` (SQL-filtered active-batch materialization).
- `module/channel_library_service.py`: `schedule_pending_download_batches`/`reconcile_download_batches` now iterate active batches only.
- `module/templates/index.html`: Channel-library poll interval 1s -> 3s.
- `tests/test_channel_library_download.py`: Added active-batch listing test.

Rollback:
- Run `git revert "$(git rev-list -1 --all --grep='^fix: bound channel library batch scan resource use$')"`; preserve `channel_library.sqlite3` and `web_tasks.sqlite3` (this change touches only query scoping, a poll constant, and a test).

## 2026-07-16 - Task 12 (part 2): Production deployment of full channel library

### What was done

- Fast-forwarded `master` to the reviewed feature tip and pushed to origin, then deployed to the RackNerd production host and smoke-tested the live service.
- Deployed commit: `d417479` (pushed `644aef3..d417479 master -> master`; `origin/master` and server `HEAD` both at `d417479`).
- Rollback point recorded before deploy: server was at `339efc1`.

### Testing

- Pre-push local verification on `master`: `.venv/bin/python -m pytest tests/ -q` -> `476 passed, 1 skipped`; `git diff --check` clean; only `.omx/` untracked.
- Consistent backup (service stopped, WAL-safe `sqlite3.Connection.backup`, `sqlite3` CLI absent so Python fallback used): `backups/web_tasks-20260716-103434.sqlite3` integrity `ok`; `backups/config-20260716-103434.yaml`; service returned `active`. (No `channel_library.sqlite3` existed pre-deploy; no `*.session` at repo root to copy.)
- Deploy: `git pull --ff-only origin master` -> `d417479`; `systemctl restart tg-downloader.service` -> `active`.
- Smoke test:
  - `curl -I https://tgdn.wyichuan.cc/` -> `HTTP/2 302`, `location: /login?next=%2F`.
  - `curl -I https://tgdn.wyichuan.cc/api/channel-libraries` -> `HTTP/2 302`, `location: /login?next=%2Fapi%2Fchannel-libraries` (route present, login enforced).
  - `channel_library.sqlite3` created on first startup: mode `600`, `PRAGMA integrity_check=ok`, `PRAGMA journal_mode=wal`, 13 tables.
  - `journalctl -u tg-downloader.service -n 80`: no exception/traceback/high-rate/secret lines; only benign INFO performance stats.

### Notes

Residual risks carried into production (documented in the Task 12 part-1 entry, none a correctness/security/data-loss defect): unbounded "download all" batch creation (top follow-up: chunked/streamed batch build), situational O(n^2) reindex on an unresolved early scan failure, WAL/SHM sidecars not chmod 0600, incremental link-resolve gate-priority parity, and the effectively-impossible deterministic-task-id conflict.

Changed files:
- `progress.md`: Appended this deployment record.

Rollback:
- `git revert --no-commit c388685..HEAD && git commit -m "revert: roll back full channel library" && git push origin master`, then on the server `git pull --ff-only origin master && systemctl restart tg-downloader.service`. Preserve `channel_library.sqlite3` and `web_tasks.sqlite3`; never delete them during rollback. Server rollback reference commit: `339efc1`.

## 2026-07-17 - Task: Stream channel download batches to bound memory

### What was done

- Fixed the "download all → OOM on 1 GiB" risk on the channel-library download path by materializing one package at a time instead of pre-building every package's Telegram messages up front.
- `download_prescan_packages` gained an optional async `prepare_package` hook: when provided, `packages` may be lightweight descriptors that are materialized (item snapshots loaded, messages refetched) immediately before each package's own download and released afterward. Default (no hook) behavior is unchanged for existing prescan/bot callers.
- `ChannelLibraryService._run_download_batch_owned` now streams package summaries from SQL and refetches each package inside the hook, so only one package's messages are ever in memory. The single `download_prescan_packages` call still owns the parent-node lifecycle and `prescan_batch_in_progress` guard exactly once, so package-scoped completion is unchanged. Cancel/exception paths use package summaries instead of the full batch.
- Added store accessors `get_download_batch_header`, `list_download_batch_package_summaries`, `get_download_batch_package_items`, `count_download_batch_items`.
- Batch creation now inserts each package's items with one `executemany` instead of a per-row loop, shrinking the write-lock window so a large "select all" batch cannot time out a concurrent scan commit.
- The `POST /download-batches` response now returns a lightweight batch summary (id, task_id, status, dispatch_status, channel_title, package_count, item_count) instead of the full package/item snapshot; the frontend only reads `created`/`id`.

### Testing

- New tests (TDD, each watched RED first):
  - `tests/test_media_downloader.py::...materializes_each_package_lazily_with_prepare_hook` — proves one package materialized at a time and lazy interleaving.
  - `tests/test_channel_library_download.py::...streams_one_package_into_memory_at_a_time` — proves refetch of package N+1 only after package N downloads.
  - `tests/test_channel_library_download.py::...streaming_batch_accessors_avoid_full_materialization` — header/summaries/per-package-items/count accessors.
  - `tests/module/test_channel_library_web.py::...response_is_a_lightweight_summary` — response omits packages/items, carries counts.
- Updated the run-path test fakes that replace `download_prescan_packages` to call the new `prepare_package` hook (assertions on refetch IDs, package fields, statuses unchanged).
- Full suite: `.venv/bin/python -m pytest tests/ -q` -> `480 passed, 1 skipped`.
- `pylint --errors-only` on the 4 changed modules -> no new errors (only the pre-existing `STARTUP_SCAN_WINDOW_SEC` E0602 and known `os`/`pyrogram` E1101 false positives). `git diff --check` clean.

### Notes

Deferred (documented, not OOM): `create_download_batch_result`/`get_download_batch` still materialize the whole batch once at creation (bounded DB-row dicts, a few MB — not the Pyrogram-message OOM); `reconcile_download_batches` still materializes an active batch's items for file-evidence repair. These are follow-up efficiency items, not crash risks.

Changed files:
- `media_downloader.py`: `download_prescan_packages` optional `prepare_package` lazy-materialization hook.
- `module/channel_library_service.py`: streamed `_run_download_batch_owned` + summary-based cancel/exception paths.
- `module/channel_library_store.py`: streaming batch accessors + `executemany` item inserts.
- `module/web.py`: `_batch_summary` lightweight create response.
- `tests/*`: new streaming tests + updated run-path fakes.

Rollback:
- `git revert` the commit `perf: stream channel download batches to bound memory`; preserve `channel_library.sqlite3` and `web_tasks.sqlite3` (no schema change was made).

## 2026-07-17 - Task: Deploy streaming channel download batches

### What was done

- Merged the streaming download-batch change to `master`, pushed, and deployed to the RackNerd production host for real-device testing.
- Adversarial correctness review of the streaming diff returned PASS (no correctness bugs). Two minor review notes were applied: removed the production-dead `count_download_batch_items` helper (commit `1c70fa9`) and corrected a docstring; a third note (a claimed test-isolation failure) did not reproduce — `tests/test_media_downloader.py` passes both alone (33) and in the full suite.
- Deployed commit: `1c70fa9` (pushed `5f1a037..1c70fa9`; `origin/master` and server `HEAD` both `1c70fa9`).
- Rollback point recorded before deploy: server was at `5f1a037`.

### Testing

- Full suite (pre-deploy, on master): `480 passed, 1 skipped`; `git diff --check` clean.
- Consistent backup (service stopped, WAL-safe Python `sqlite3.backup`): `backups/web_tasks-20260716-214400.sqlite3` and `backups/channel_library-20260716-214400.sqlite3` both integrity `ok`; `backups/config-20260716-214400.yaml`.
- Deploy: `git pull --ff-only origin master` -> `1c70fa9`; `systemctl restart` -> `active`.
- Smoke test: `curl -I https://tgdn.wyichuan.cc/` and `/api/channel-libraries` -> `302` to `/login`; `channel_library.sqlite3` mode `600`, integrity `ok`, journal `wal`; post-restart `journalctl` shows a clean startup with no traceback/channel-library error (the ERROR lines in the log window are pre-deploy Werkzeug HTTP access logs from internet scanners).

### Notes

Awaiting the user's real-device test of a large-channel "download all" to confirm bounded memory in production.

Changed files:
- `progress.md`: Appended this deployment record.

Rollback:
- `ssh rn 'cd /root/telegram_media_downloader && git reset --hard 5f1a037 && systemctl restart tg-downloader.service'` or `git revert 48224dc..HEAD` + push + server ff. No schema change was made; preserve both SQLite databases.

## 2026-07-17 - Task: Fix channel batch misfiling + selection scope

### What was done

- 修复频道批量下载的两个独立缺陷（线上 library 4、批次 b5f6741d 实锤）：
  - **错位归档（数据损坏）**：一个批次里 40 个文件（消息 121120–121159，属包 17899）被写进了另一个包 #18277 的文件夹。根因是 `download_prepared_messages` 用可溢出的聚合计数器判"包下完"（日志 96/90 提前放行），主循环随即覆盖共享的 `parent_node.package_naming_context`，队列里残留消息按下一个包命名。
  - **选择作用域（下载了没勾的包）**：下载请求不带包 ID、服务端下整份持久 `selected=1`、批次后不清空、列表带筛选分页导致残留勾选不可见。
- **B1**：`download_prepared_messages` 的完成屏障改为按本包精确 message_id 集合判终态（新增 `_package_download_complete`），本包消息全部落地前主循环不前进；对计数溢出免疫。
- **B2（纵深防御）**：入队时把包命名上下文快照进队列条目，出队命名优先用条目自带快照（经 `download_media` 的固定签名装饰器，用仅本次调用生效的 ContextVar 桥接），缺省回退旧字段，非批量路径行为不变。
- **A2**：`create_download_batch_result` 新建批次成功后在同一事务内清空该库 `channel_package_selections`（批次快照自包含，不影响执行/重试）。
- **A1**：前端"下载所选"改为下载前用服务端真实数字弹确认"即将下载 N 包 · M 文件（可能含未显示的已选包）"，并加刷新失败/中途切库守卫；移除按可见子集预判 redownload，改由后端 `redownload_required` 驱动。
- 线上受损数据已单独清理（40 个错位文件云盘移入 `_quarantine/`、`task_files` 40 行错位记录删除，均可回滚；正确副本齐全）。

### Testing

- 全量测试 `.venv/bin/python -m pytest tests/ -q` → **486 passed, 1 skipped**（含新增 B1 helper+集成、B2 命名快照、A2 清空选择测试；B1 修正一处共享函数的过时测试夹具）。
- 每个任务先构造会 RED 的复现测试再修（B1 集成测试证明旧逻辑把 121120–121159 记到 #18277 上下文、修后归位）。
- 前端 A1 用 scratchpad 浏览器 harness + mock 验证 4/4 用例（真实计数确认文案、取消不 POST、0 选不弹、刷新失败不用陈旧值）。
- `pylint --errors-only`（改动的 4 个 py 模块）无新增错误（仅既有 `os`/`pyrogram` E1101、`STARTUP_SCAN_WINDOW_SEC` E0602 误报）；`git diff --check` 干净。
- 子代理驱动：每任务实现者+复审者，复审独立复现 RED/GREEN 与并发隔离（ContextVar per-Task）、事务原子性（AST 核验）。

### Notes

Changed files:
- `media_downloader.py`: B1 精确 message_id 完成屏障 + `_package_download_complete`；B2 队列条目命名快照 + `_get_media_meta` 覆盖参数 + ContextVar 桥接。
- `module/channel_library_store.py`: A2 新建批次事务内清空该库选择。
- `module/templates/index.html`: A1 下载前真实数量确认 + 刷新失败/切库守卫 + 移除可见子集 redownload 预判。
- `tests/*`: 新增 B1/B2/A2 测试；对齐 4 个受新语义影响的既有选择测试（改用公开 API 复现同状态，未放宽守卫）与 1 个共享函数完成语义测试。

Rollback:
- `git revert` 本分支合并（无 schema/数据迁移，保留 `*.sqlite3`）。
- 数据清理回滚：云盘 `_quarantine/misfiled-b5f6741d-2025_12-129365/` 40 文件移回原路径；DB 用 `web_tasks.sqlite3.bak-20260717-085320` 覆盖。

## 2026-07-17 - Task: Deploy channel batch misfiling + selection scope fix

### What was done

- 合并 `fix/channel-batch-misfiling-and-selection-scope` 到 master（快进 38bd2cb..df1ac9a），推送 origin。
- 部署 RackNerd：`git pull --ff-only` 到 df1ac9a，`systemctl restart tg-downloader.service`。

### Testing

- 部署后：服务 `active`，新进程启动无 error 级日志，Flask `module.web` 正常、4 个下载 worker 已起；`https://tgdn.wyichuan.cc/` 返回 302 → /login。
- 合并前全量 `pytest tests/ -q` → 487 passed, 1 skipped；pylint 无新增错误；final whole-branch review（opus）READY TO MERGE。

### Notes

Changed files:
- 无新增代码改动（本轮仅合并+部署）。

Rollback:
- 服务器：`git reset --hard 38bd2cb && systemctl restart tg-downloader.service`（保留 `*.sqlite3`）；或 `git revert df1ac9a`。参考回滚基线提交 `38bd2cb`。

## 2026-07-23 - Task: Remediate P1-P3 web credential exposure risks

### What was done

- Ignored the root `.web_auth.json` file so generated Web login credentials and Flask session state cannot be added to Git accidentally.
- Replaced the static Flask session-secret fallback with a random value, while retaining the persistent random session secret created by Web authentication initialization.
- Removed the fixed client-side AES key/IV and CryptoJS login dependency; the browser now submits the password for server-side verification, with documentation requiring HTTPS outside localhost.
- Replaced weak Web password examples and synchronized design documents and the login prototype with the new behavior.

### Testing

- TDD red: `.venv/bin/python -m pytest tests/module/test_web.py -q` failed as expected for the old static secret and AES-only login behavior.
- Targeted green: `.venv/bin/python -m pytest tests/module/test_web.py -q` -> `28 passed`.
- Full suite: `.venv/bin/python -m pytest tests/ -q` -> `488 passed, 1 skipped`.
- Security checks: `.web_auth.json` is ignored; no fixed AES key/IV, client AES references, weak Web-secret examples, or stale AES login documentation remain outside vendored assets.
- `.venv/bin/python -m compileall -q module/web.py tests/module/test_web.py` and `git diff --check` passed.

### Notes

Changed files:
- `.gitignore`: ignores generated root Web authentication state.
- `module/web.py` and `module/templates/login.html`: remove fixed client-side AES and static Flask secret fallback.
- `tests/module/test_web.py`: covers random session secret and plaintext login submission.
- `config.example.yaml`, `README.md`, `README_CN.md`, and design docs: document strong Web passwords and HTTPS requirements.
- `progress.md`: records this remediation.

Rollback:
- `git revert <commit-containing-this-change>` restores the prior Web login path. No database or persistent-data migration was made.

## 2026-07-23 - Task: Replace Discord monitoring with indexed package auto-download rules

### What was done

- Replaced the active Telegram-to-Discord monitoring path with channel-library title rules under `channel_library.auto_download_rules`.
- Added Unicode-normalized, case-insensitive keyword matching for stable indexed package titles after a full, incremental, or repair scan reaches its terminal state.
- Added exact-package automatic download batches that preserve the user's manual Web selections.
- Added a persistent trigger record for each rule, package revision, matched keywords, and batch so repeat scans and restarts cannot enqueue duplicates.
- Kept successful and `outdated` packages out of automatic downloads while retaining the existing manual redownload workflow.
- Updated the example configuration and channel-library documentation; legacy real-time monitoring, history backfill, polling, and Discord delivery are no longer started.

### Testing

- `.venv/bin/pytest -q` -> `491 passed, 1 skipped`.
- `.venv/bin/pytest -q tests/module/test_channel_library_store.py tests/test_channel_library_download.py tests/module/test_channel_library_service.py tests/test_media_downloader.py -k 'auto_download or v1_migration or sanitize_monitor_cfg'` -> `6 passed`.
- `.venv/bin/black --check module/channel_library_store.py module/channel_library_service.py tests/module/test_channel_library_store.py tests/test_channel_library_download.py tests/module/test_channel_library_service.py` -> passed.
- `.venv/bin/python -m py_compile media_downloader.py module/channel_library_store.py module/channel_library_service.py` and `git diff --check` -> passed.

### Notes

Changed files:
- `module/channel_library_store.py`: adds v4 trigger persistence, rule parsing, candidate lookup, and exact-package batch creation.
- `module/channel_library_service.py`: runs configured rules after channel scans finish and schedules matching package batches.
- `media_downloader.py`: disables the legacy Discord-monitor runtime path.
- `config.example.yaml`, `README.md`, `README_CN.md`, and `docs/`: document title-rule auto-download configuration and behavior.
- `tests/`: cover rule parsing, automatic batch creation, manual selection preservation, successful/outdated exclusions, scan integration, and v4 migration.

Rollback:
- `git revert <commit-containing-this-change>` restores the prior runtime behavior and code.
- The new `channel_package_auto_download_triggers` table is additive. For a schema rollback, stop the service and retain a copy of `channel_library.sqlite3` before restoring a compatible database backup.

## 2026-07-23 - Task: Rework channel package download lifecycle

### What was done

- Added FIFO resource-package disk admission with a 3 GiB minimum free-space default. Each package snapshots its exact indexed size at submission and reserves that capacity through its download/upload lifecycle.
- Added schema version 5 to persist package-size snapshots and backfill existing attempt rows from their snapshotted media IDs. Packages with unknown source size now fail safely as `unknown_package_size` while later packages continue.
- Preserved upload failures as durable task-file records, exposed a dedicated upload-retry list, and added upload-only retry plus explicit retained-file cleanup for channel-library tasks. Neither action recreates downloads.
- Fixed task-state transitions so upload failures are not overwritten by later download snapshots and terminal tasks can become active during an upload retry.

### Testing

- Isolated Python 3.11 environment: `pytest -q` -> `498 passed, 1 skipped`.
- Targeted lifecycle coverage: `pytest -q tests/test_channel_library_download.py tests/module/test_task_state.py tests/module/test_download_admission.py tests/module/test_channel_library_store.py` -> `90 passed`.
- `python3 -m py_compile module/download_admission.py module/channel_library_store.py module/channel_library_service.py module/task_state.py module/web.py` and `git diff --check` -> passed.

### Notes

Changed files:
- `module/download_admission.py`: FIFO disk reservation controller.
- `module/channel_library_store.py` and `module/channel_library_service.py`: size snapshots, admission, upload-only retry, and cleanup lifecycle.
- `module/task_state.py` and `module/web.py`: durable upload-failure state and retry/cleanup APIs.
- `config.example.yaml`, `README_CN.md`, and `docs/`: configuration and operational behavior.
- `tests/`: admission, migration, task-state, upload-retry, and cleanup coverage.

Rollback:
- `git revert <commit-containing-this-change>` restores prior behavior.
- Schema version 5 is additive; retain a backup of `channel_library.sqlite3` before downgrading to code that does not understand the added batch-package columns.

## 2026-07-23 - Task: Decompose the downloader entrypoint and refactor download execution

### What was done

- Added the formal download-module refactor spec covering submission, package and file boundaries; global FIFO ordering; 3 GiB disk admission; same-name package identity; download interruption and stall handling; separate upload retries; cleanup; and Pyrogram adapter rules.
- Reduced the root `media_downloader.py` to a stable 13-line CLI/import facade while preserving existing `media_downloader` imports and monkeypatch targets through `module.download_entry`.
- Split process startup, queue admission/workers, single-file transfer, separate download/upload phases, package contracts, and package execution into focused modules with explicit dependency assembly.
- Removed the disabled real-time Telegram monitor, polling, Discord webhook and startup-backfill implementation from the runtime path.
- Changed FloodWait handling to wait for the server-provided duration and retry, and made external task cancellation propagate instead of being mistaken for a stall retry.
- Added package-attempt `completed_with_errors` when at least one snapshotted file completes and a sibling file fails or is unavailable; upload failures remain independently recoverable as `upload_failed`.

### Testing

- Isolated Python 3.11 full suite: `pytest -q` -> `501 passed, 1 skipped`.
- Refactored entrypoint, package and channel lifecycle suite: `pytest -q tests/module/test_package_download.py tests/test_channel_library_download.py tests/test_media_downloader.py` -> `73 passed`.
- Focused transfer/admission/channel package suite: `pytest -q tests/module/test_package_download.py tests/module/test_download_admission.py tests/test_channel_library_download.py` -> `38 passed`.
- `python -m py_compile` passed for the facade and all new download modules.
- Black check passed for the facade, new download modules and new tests.
- `check_imports.py` and `git diff --check` passed.
- Pylint `--errors-only` was not a clean validation source: the repository configuration reports removed options and the installed astroid reports existing false positives for standard `os` members and dynamic Pyrogram errors.

### Notes

Changed files:
- `media_downloader.py` and `module/download_entry.py`: thin CLI facade plus compatible dependency assembly and legacy workflow exports.
- `module/download_runtime.py`, `module/download_queue.py`, `module/download_lifecycle.py`, and `module/download_transfer.py`: process, queue, phase and transfer boundaries.
- `module/download_models.py` and `module/package_download.py`: package contracts, serial execution and package-scoped result calculation.
- `module/channel_library_service.py` and `module/channel_library_store.py`: persist and aggregate `completed_with_errors` package attempts.
- `docs/superpowers/specs/2026-07-23-download-module-refactor-design.md` and `docs/channel-library-download-outbox.md`: formal design and operational semantics.
- `tests/module/test_package_download.py` and `tests/test_channel_library_download.py`: cancellation, FloodWait, partial completion and reconciliation coverage.

Rollback:
- `git revert <commit-containing-this-change>` restores the previous monolithic entrypoint and package result semantics.
- This refactor adds no schema version; `completed_with_errors` is stored only in existing unconstrained batch and batch-package status columns.

## 2026-07-23 - Task: Add database keyword monitoring and aggregate resource packages

### What was done

- Removed channel-library keyword rules from `config.yaml`; monitor groups, normalized terms, and per-group trigger history are now owned by the channel-library database and managed through authenticated Web APIs.
- Added required, match, and blacklist keyword semantics with Unicode NFKC/casefold matching. Saving a group immediately evaluates the current index, and completed full, incremental, or repair scans evaluate enabled groups again.
- Merged overlapping group hits by package revision before creating exact-package batches. A package matching multiple groups creates one chronological FIFO batch while each group records its actual matched keywords, task, batch, source channel, and live persistent task progress.
- Promoted resource packages to a cross-channel aggregate API and Web tab with optional multi-channel filtering, aggregate selection, package-item expansion, and source-channel batch fan-out. The Channels tab now focuses on adding, scanning, and deleting indexes.
- Added a Keyword Monitor Web tab for group creation, editing, enable/disable, deletion, and paginated monitor/download history.
- Kept successful, active, and `outdated` packages out of automatic repeats while preserving explicit manual redownload behavior.
- Updated the formal design, operator docs, and README files; the legacy schema-v4 trigger table remains compatibility data but is no longer used by the runtime.

### Testing

- Full suite: `.venv/bin/python -m pytest tests/ -q` -> `507 passed, 1 skipped`.
- Targeted aggregate, monitor, migration, service, and Web suites -> `207 passed`, then `172 passed` after final boundary coverage.
- Browser validation with Chromium at 1440x1000 and 390x844 loaded two cross-channel packages and monitor history without page/console errors or page-level horizontal overflow; package/history tables remained locally scrollable.
- `python -m py_compile` passed for the facade, channel store/service/Web, and all refactored download modules.
- `check_imports.py` passed for the public downloader compatibility imports.
- Black check passed for 18 changed Python implementation/test files; inline Web JavaScript parsed successfully; `git diff --check` passed.

### Notes

Changed files:
- `module/channel_library_store.py`: schema v6 monitor tables, monitor CRUD/history/matching, aggregate package queries/selections, atomic monitor history, and aggregate idempotency lookup.
- `module/channel_library_service.py`: database-backed cross-group matching, chronological package ordering, exact-package deduplication, and scan/save triggers.
- `module/web.py`, `module/templates/index.html`, and `module/static/css/index.css`: aggregate package and keyword-monitor APIs, progress enrichment, and responsive Web views.
- `config.example.yaml`, `README.md`, `README_CN.md`, `docs/channel-library-download-outbox.md`, `docs/web-control-console.md`, and `docs/superpowers/specs/2026-07-23-download-module-refactor-design.md`: remove config keyword rules and document the database/aggregate model.
- `tests/module/test_channel_library_store.py`, `tests/module/test_channel_library_service.py`, `tests/module/test_channel_library_web.py`, and `tests/test_channel_library_download.py`: migration, matching, ordering, same-name cross-channel identity, API, UI, history, and idempotency coverage.
- `module/download_entry.py`: applied the repository's existing Black format during final whole-change verification.

Rollback:
- Revert the commit containing this task to restore the prior channel-scoped UI and config-rule runtime. The schema-v6 tables are additive and may remain unused after a code rollback.
- Before physically removing `keyword_monitor_groups`, `keyword_monitor_terms`, or `keyword_monitor_history`, stop the service and back up `channel_library.sqlite3`; dropping those tables permanently removes monitor definitions and history.

## 2026-07-23 - Task: Deploy download refactor, aggregate packages, and keyword monitoring

### What was done

- Committed and pushed the reviewed implementation to GitHub `master` as `a519c0e`.
- Created a consistent production release backup while `tg-downloader.service` was stopped, then restored the service before deployment.
- Fast-forwarded the RackNerd checkout from `df1ac9a` to `a519c0e` and restarted `tg-downloader.service`.
- Confirmed schema v6 initialized the database-owned keyword monitor tables without modifying existing package/library rows.

### Testing

- Pre-deploy full suite: `.venv/bin/python -m pytest tests/ -q` -> `507 passed, 1 skipped`.
- Production backup: `backups/release-20260723-101058` (158MB); SQLite integrity checks for both backed-up databases -> `ok`.
- Production service: `active`, commit `a519c0e`, four refactored download workers started, and no traceback/exception/error matches in the post-deploy journal window.
- Production data: `channel_library.sqlite3` integrity `ok`, journal `wal`, mode `600`, schema versions `[3, 6]`; `keyword_monitor_groups`, `keyword_monitor_terms`, and `keyword_monitor_history` exist. `web_tasks.sqlite3` integrity -> `ok`.
- Production imports and compile checks passed for the downloader facade, store, service, Web layer, and refactored entrypoint.
- Public smoke tests: `/` -> `302 /login`, `/login` -> `200`, `/api/packages` and `/api/keyword-monitor-groups` -> authenticated `302 /login`, and `/static/css/index.css` -> `200`.

### Notes

Changed files:
- `progress.md`: recorded the GitHub push, production backup, deployment, schema migration, and smoke-test evidence.

Rollback:
- Preferred code rollback: `git revert a519c0e`, push `master`, then run `git pull --ff-only origin master && systemctl restart tg-downloader.service` on RackNerd. Preserve both SQLite databases; schema-v6 tables are additive.
- Release backup: `/root/telegram_media_downloader/backups/release-20260723-101058`. Stop the service before any database restore and use SQLite backup/copy only after retaining the current databases.

## 2026-07-23 - Task: Add global incremental cron, channel statistics, and keyword form draft protection

### What was done

- Added one optional global five-field cron that checks every full-scanned channel for a new message tail and queues eligible incrementals through the existing serial scheduler.
- Skipped scheduled checks for channels with recoverable scan work, avoided empty scan jobs when the latest message ID is unchanged, and kept missed or skipped ticks from accumulating.
- Replaced the duplicate channel-scoped resource list in the Channels tab with available/downloaded/pending package totals, media/size/failure totals, and enabled monitor keyword distribution.
- Protected unsaved keyword monitor drafts from the five-second group/history refresh so moving between form fields no longer clears a new group name.
- Documented the global cron settings and added the maintained `croniter` dependency; automation remains disabled while `incremental_scan_cron` is empty.

### Testing

- `.venv/bin/python -m pytest tests/ -q` -> `514 passed, 1 skipped`.
- `.venv/bin/python -m py_compile media_downloader.py module/channel_library_store.py module/channel_library_service.py module/web.py module/app.py` -> passed.
- `.venv/bin/python check_imports.py` -> public downloader compatibility imports passed.
- `.venv/bin/pip check` -> no broken requirements.
- Black check for all changed Python implementation/test files, inline JavaScript parse, and `git diff --check` -> passed.
- Chromium at 1440x1000 and 390x844 showed the channel statistics without page-level horizontal overflow or console errors.
- Chromium keyword draft check entered a new group name and keywords, waited beyond the five-second polling interval, and confirmed every unsaved value remained unchanged.

### Notes

Changed files:
- `module/channel_library_service.py`, `module/channel_library_store.py`: global cron lifecycle, eligible-channel checks, no-op suppression, channel statistics, and cached keyword distribution.
- `module/templates/index.html`, `module/static/css/index.css`, `module/web.py`: channel statistics workspace, aggregate-only package interaction, and keyword draft protection.
- `requirements.txt`, `config.example.yaml`, `README.md`, `README_CN.md`, `docs/web-control-console.md`: cron dependency, configuration, behavior, and operations documentation.
- `tests/module/test_app.py`, `tests/module/test_channel_library_store.py`, `tests/module/test_channel_library_service.py`, `tests/module/test_channel_library_web.py`: cron validation/lifecycle, scheduling conflicts, statistics, DOM, and draft regression coverage.

Rollback:
- Revert the commit containing this task and restart the downloader. No database schema or stored rows were added or migrated by this change.
- Remove `channel_library.incremental_scan_cron` and `channel_library.incremental_scan_timezone` from runtime configuration, or leave the cron value empty, before rolling back the dependency if those settings were added later.

## 2026-07-23 - Task: Deploy global incremental cron and channel statistics

### What was done

- Pushed feature commit `cfae59a` to GitHub `master`.
- Backed up the production configuration, dependency snapshot, and prior commit marker before deployment.
- Fast-forwarded the RackNerd checkout, installed `croniter==2.0.7` into the service virtual environment, and restarted `tg-downloader.service`.
- Preserved the production `config.yaml`; global automatic incremental scanning remains disabled until an explicit cron expression is configured.

### Testing

- Production dependency check, Python compile check, and default channel-library configuration import -> passed.
- `tg-downloader.service` -> `active` on commit `cfae59a`; four download workers started.
- Post-restart journal scan -> 0 traceback/exception/error lines.
- Local production smoke: `/` -> `302 /login`, `/login` -> `200`, channel-library and keyword-monitor APIs -> authenticated `302`, static CSS -> `200`.
- `channel_library.sqlite3` and `web_tasks.sqlite3` integrity checks -> `ok`; schema versions remained `[3, 6]`.

### Notes

Changed files:
- `progress.md`: recorded the production backup, dependency installation, deployment state, and verification evidence.

Rollback:
- Revert `cfae59a`, push `master`, fast-forward production, restore the prior dependency set if required, and restart `tg-downloader.service`.
- Production backup: `/root/telegram_media_downloader/backups/release-20260723-112215-channel-cron`. Preserve both SQLite databases; this release did not migrate their schemas.

## 2026-07-23 - Task: Move incremental cron settings to Web and refine the channel workspace

### What was done

- Added schema v7 with one database-owned global automatic incremental-scan setting. Migration defaults it to disabled, retains saved cron expressions while disabled, and records the last trigger time.
- Removed cron and timezone ownership from `config.yaml`. The authenticated Channels page now loads, validates, saves, enables, and disables the five-field cron and IANA timezone with immediate owner-loop hot application.
- Kept one long-running watcher even while disabled. Setting changes wake it without restarting the service or cancelling active Telegram requests; missed ticks are not accumulated.
- Made automatic incremental sweeps yield globally to recoverable full scans, including a full scan that appears while a sweep is already checking channels. Eligible incrementals still enter the existing FIFO scheduler.
- Reworked the Channels page into a global schedule band plus channel identity, resource overview, operational scan metadata, and keyword distribution bars while preserving the existing application design language and responsive behavior.
- Updated operator and configuration documentation to make the database/Web ownership and no-restart behavior explicit.

### Testing

- Full suite: `.venv/bin/python -m pytest tests/ -q` -> `534 passed, 1 skipped`.
- Targeted store, service, Web, and application tests -> `203 passed`; final service/Web regression subset -> `149 passed`.
- `.venv/bin/python -m py_compile media_downloader.py module/app.py module/channel_library_store.py module/channel_library_service.py module/web.py` -> passed.
- `.venv/bin/python check_imports.py` -> public downloader compatibility imports passed.
- `.venv/bin/pip check` -> no broken requirements.
- Black check passed for all changed Python implementation and test files; inline Web JavaScript parsed successfully; `git diff --check` passed.
- Chromium at 1440x1000 and 390x844 saved and hot-applied `*/30 * * * *`, returned the next execution time, rendered populated channel statistics and keyword bars, and showed no console errors or page-level horizontal overflow.

### Notes

Changed files:
- `module/channel_library_store.py`, `module/channel_library_service.py`: schema-v7 singleton settings, validation, trigger timestamps, hot-update watcher, next-run calculation, and full-scan yielding.
- `module/web.py`, `module/templates/index.html`, `module/static/css/index.css`: authenticated settings API, global schedule controls, and responsive channel workspace hierarchy.
- `config.example.yaml`, `README.md`, `README_CN.md`, `docs/web-control-console.md`: removed YAML cron fields and documented database-backed Web management.
- `tests/module/test_app.py`, `tests/module/test_channel_library_store.py`, `tests/module/test_channel_library_service.py`, `tests/module/test_channel_library_web.py`: configuration ownership, migration, runtime, API, DOM, and regression coverage.

Rollback:
- Revert the implementation commit and restart the downloader to restore the prior YAML-owned cron behavior. Schema v7 is additive, so `channel_library_settings` may remain unused after code rollback.
- Before removing or restoring `channel_library_settings`, stop the service and back up `channel_library.sqlite3`; deleting the table permanently removes the saved Web schedule and trigger timestamp.

## 2026-07-23 - Task: Deploy Web-managed incremental cron and channel workspace

### What was done

- Pushed implementation commit `780ee78` to GitHub `master`.
- Stopped `tg-downloader.service` and created a consistent production backup of both SQLite databases and `config.yaml` before migrating.
- Fast-forwarded the RackNerd checkout from `e7bccae` to `780ee78`, ran production compile and dependency checks, and restarted the service.
- Confirmed schema v7 created one disabled `channel_library_settings` row without importing cron values from configuration or changing existing channel, package, scan, monitor, or history counts.

### Testing

- Backup directory: `/root/telegram_media_downloader/backups/release-20260723-115134-web-cron`; both backed-up SQLite integrity checks -> `ok`.
- Production compile check passed and `.venv/bin/pip check` reported no broken requirements.
- `tg-downloader.service` -> `active` on commit `780ee78`; post-restart journal scan found 0 traceback, exception, critical, error, or failed lines.
- Production schema versions -> `[3, 6, 7]`; settings singleton -> disabled, empty cron, `Asia/Shanghai`, no prior trigger. Live and backup counts matched for libraries, packages, scans, monitor groups, and monitor history.
- Live `channel_library.sqlite3` and `web_tasks.sqlite3` integrity checks -> `ok`; channel DB remained WAL mode `600`. Production `config.yaml` matched the backup SHA-256 and contained no legacy cron fields.
- Local production Web on port 80: `/login` -> `200`, `/` and the new cron API -> authenticated `302`, existing channel API -> authenticated `302`, CSS -> `200` with the new schedule styles.
- Public Web: `https://tgdn.wyichuan.cc/` -> `302 /login`, `/login` -> `200`, new cron API -> authenticated `302`, CSS -> `200`.

### Notes

Changed files:
- `progress.md`: recorded the release backup, schema migration, service restart, data-preservation checks, and local/public Web smoke tests.

Rollback:
- Preferred code rollback: `git revert 780ee78`, push `master`, fast-forward production, and restart `tg-downloader.service`. Preserve both live SQLite databases; schema v7 is additive and can remain unused.
- Release backup: `/root/telegram_media_downloader/backups/release-20260723-115134-web-cron`. Stop the service before restoring either database or `config.yaml`, and retain the current live files before replacement.

## 2026-07-29 - Task: Integrate comment threads into channel scanning and resource packages

### What was done

- Added per-channel scan modes for channel messages, comment threads, or both; existing and default channels remain channel-message-only.
- Integrated comment-thread discovery into full and incremental channel scans. Each source post's media comments now form one resource package that inherits the source post title while retaining the discussion-group message identity needed for downloading.
- Added source-post comment-count tracking so incremental scans skip unchanged threads and retry threads whose visible count has changed or whose replies have not yet synchronized completely.
- Routed mixed channel-message and comment-package selections into download batches grouped by their actual Telegram source, and exposed scan mode and package source type in the Web console.
- Upgraded the channel-library database to schema v8 and documented the new scan modes, comment package behavior, and migration semantics.

### Testing

- `.venv/bin/python -m pytest -q` -> `540 passed, 1 skipped`.
- `.venv/bin/python check_imports.py` -> passed.
- Python compile checks for the changed implementation modules -> passed.
- `git diff --check` -> passed.

### Notes

Changed files:
- `README_CN.md`, `docs/web-control-console.md`: documented comment scanning, resource packages, incremental synchronization, and scan modes.
- `module/channel_library_store.py`, `module/channel_library_service.py`, `module/channel_library_workflow.py`: schema v8, comment source tracking, package construction, incremental count checks, and scan orchestration.
- `module/download_entry.py`, `module/package_download.py`: discussion-group message resolution, comment naming, and source-aware download batching.
- `module/web.py`, `module/templates/index.html`: scan-mode API validation and Web controls/source labels.
- `tests/module/test_channel_library_store.py`, `tests/module/test_channel_library_service.py`, `tests/module/test_channel_library_web.py`: migration, comment packaging, pagination, incremental synchronization, downloading, and Web API coverage.
- `progress.md`: recorded implementation and verification evidence.

Rollback:
- Revert the commit containing this task. Schema v8 is additive; stop the service and back up `channel_library.sqlite3` before manually removing the new columns or tables.

## 2026-07-29 - Task: Deploy comment-thread channel scanning to RackNerd

### What was done

- Committed and pushed `00ee82e` to GitHub `master`, then fast-forwarded the RackNerd production checkout from `f990561` to `00ee82e`.
- Stopped `tg-downloader.service` and created a restricted, consistent release backup with the SQLite backup API before deploying schema v8; production configuration and sessions were included without modification.
- Restarted the service and confirmed the additive v8 migration retained all six existing channels as channel-message-only and preserved the existing 24,549 channel resource packages.

### Testing

- Pre-push full suite: `.venv/bin/python -m pytest -q` -> `540 passed, 1 skipped`; import, changed-module compile, and `git diff --check` checks passed.
- Production backup: `/root/telegram_media_downloader/backups/release-20260729-021758-comment-scanning` (159MB); both SQLite backup integrity checks -> `ok`.
- Production compile check passed and `.venv/bin/pip check` reported no broken requirements.
- `tg-downloader.service` -> `active` on `00ee82e`; four download workers started and the post-restart journal contained no traceback, exception, critical, error, or failed lines.
- Live schema versions -> `[3, 6, 7, 8]`; channel scan modes -> six `messages`; package kinds -> 24,549 `channel`; the new source-post table was empty before the first comment scan.
- Live `channel_library.sqlite3` and `web_tasks.sqlite3` integrity checks -> `ok`; channel DB remained WAL mode `600`, and `config.yaml` matched the pre-deploy backup.
- Local production `/` and the channel API redirected to login, `/login` returned `200`; public `https://tgdn.wyichuan.cc/` redirected to login and `/login` returned `200`.

### Notes

Changed files:
- `progress.md`: recorded the feature push, production backup, schema migration, service restart, data-preservation checks, and Web smoke tests.

Rollback:
- Preferred code rollback: `git revert 00ee82e`, push `master`, fast-forward production, and restart `tg-downloader.service`. Preserve both live SQLite databases; schema v8 is additive and can remain unused by older code.
- Release backup: `/root/telegram_media_downloader/backups/release-20260729-021758-comment-scanning`. Stop the service before restoring either database or configuration, and retain the current live files before replacement.

## 2026-07-29 - Task: Add channel-scoped resource insight and package preview

### What was done

- Added stable package-source and media-type distributions plus the indexed publication range to the selected channel overview, cached by channel index revision and omitted from the all-channel polling response.
- Added a read-only preview of the 20 most recently indexed stable packages to the channel workspace, with source type, title, publication time, media count, size, and download status.
- Added on-demand expansion of the first 10 media items for package content inspection. Package titles and the view-all action reuse the aggregate Resources page with the current channel filter applied; selection and download controls remain centralized there.
- Updated operator documentation to describe the channel-summary/package-management boundary and preview refresh behavior.

### Testing

- `.venv/bin/python -m pytest -q` -> `540 passed, 1 skipped`.
- Channel Web regression suite -> `106 passed`.
- Inline Web JavaScript parsed successfully with `node --check`.
- Changed Python modules compiled successfully and `.venv/bin/python check_imports.py` passed.
- `git diff --check` -> passed.
- Browser screenshot verification was not run because the workspace has no Playwright, Puppeteer, or equivalent browser runtime; no new browser dependency was installed and no Telegram-connected local service was started.

### Notes

Changed files:
- `module/channel_library_store.py`, `module/web.py`: revision-cached channel resource distributions and lightweight list/detail response separation.
- `module/templates/index.html`, `module/static/css/index.css`: resource composition, recent package preview, media expansion, responsive layout, and scoped navigation to Resources.
- `tests/module/test_channel_library_web.py`: distribution API and channel workspace DOM contracts.
- `README_CN.md`, `docs/web-control-console.md`: documented the channel preview and aggregate resource-management boundary.
- `progress.md`: recorded implementation and verification evidence.

Rollback:
- Revert the commit containing this task. No schema or persisted-data migration is required; restarting the service restores the prior channel overview.

## 2026-07-29 - Task: Deploy channel resource insight and package preview

### What was done

- Committed and pushed `ffaa0d2` to GitHub `master`, then fast-forwarded the RackNerd production checkout from `70898f5` to `ffaa0d2`.
- Restarted `tg-downloader.service` after production compile and dependency checks; this release made no schema, configuration, or persisted-data migration.
- Confirmed the live channel detail can calculate the new cached package-source, media-type, and publication-range distribution without triggering a channel scan.

### Testing

- Pre-push full suite: `.venv/bin/python -m pytest -q` -> `540 passed, 1 skipped`; channel Web regression suite -> `106 passed`.
- Inline JavaScript syntax, changed Python module compile, compatibility imports, and `git diff --check` all passed before deployment.
- Production compile check passed and `.venv/bin/pip check` reported no broken requirements.
- `tg-downloader.service` -> `active` on `ffaa0d2`; four download workers started and the post-restart journal contained no traceback, exception, critical, error, or failed lines.
- Live schema versions remained `[3, 6, 7, 8]`; 9 channel libraries and 24,938 resource packages were preserved; `channel_library.sqlite3` integrity -> `ok`.
- A live read-only channel overview returned `package_kinds`, `media_types`, and `published_at`; deployed template/CSS markers for the resource distribution and package preview were present.
- Local production `/` redirected to login, `/login` and the updated CSS returned `200`; public `/` redirected to login and public `/login` returned `200`.

### Notes

Changed files:
- `progress.md`: recorded the feature push, production restart, data-preservation checks, live distribution read, and Web smoke tests.

Rollback:
- Preferred rollback: `git revert ffaa0d2`, push `master`, fast-forward production, and restart `tg-downloader.service`. Preserve both SQLite databases; no database restore is required because this release did not change their schema or persisted contents.

## 2026-07-29 - Task: Design denser download-task and task-detail panels

### What was done

- Defined a desktop-first information hierarchy that consolidates the download task table from eight columns to five without changing task behavior or API contracts.
- Standardized the task-detail header, current-file row, detail states, empty states, selection semantics, and stale asynchronous response handling.
- Limited the implementation scope to the existing task page template, local styles, directly related tests, and operator documentation.

### Testing

- Reviewed the design for placeholders, contradictory requirements, ambiguous scope, unsupported backend assumptions, and rollback completeness.
- No runtime or browser verification was performed because this task produced a design specification only.

### Notes

Changed files:
- `docs/superpowers/specs/2026-07-29-task-panels-density-design.md`: Recorded the approved panel structure, interaction rules, scope, and verification criteria.
- `progress.md`: Recorded the design task and its validation boundary.

Rollback:
- Revert the design-only commit; no runtime, configuration, API, or persisted-data rollback is required.

## 2026-07-29 - Task: Optimize download-task and task-detail panels

### What was done

- Consolidated the task list from eight independent columns into five stable columns: task identity, status, progress, results, and actions.
- Grouped task title, source, type, and short ID into one hierarchy; added filter-specific empty states, a stronger selected-row marker, keyboard row selection, and accessible filter/selection state.
- Standardized ordinary and prescan task details around one title/status/action header, one metadata row, and one current-file row while retaining all existing APIs and task commands.
- Guarded asynchronous task and prescan detail responses so an older request cannot overwrite a newly selected task.
- Added scoped responsive styles without changing the application palette, global design system, backend, database, configuration, or polling frequency.

### Testing

- TDD red check: `.venv/bin/python -m pytest tests/module/test_task_page_ui.py -q` -> `4 failed` before implementation for the missing five-column, accessibility, detail, and CSS contracts.
- Focused UI contract: `.venv/bin/python -m pytest tests/module/test_task_page_ui.py -q` -> `4 passed`.
- Targeted Web regression: `.venv/bin/python -m pytest tests/module/test_task_page_ui.py tests/module/test_web.py tests/module/test_channel_library_web.py -q` -> `138 passed`.
- Full suite: `.venv/bin/python -m pytest -q` -> `544 passed, 1 skipped`.
- `.venv/bin/python check_imports.py` -> compatibility imports passed.
- Inline JavaScript parsed successfully with Node's `vm.Script`; `git diff --check` passed.
- Local mock-data browser check at 1440x1000: the 1240px application and task table fit without page or table overflow; row selection opened the correct detail and rendered the current filename, 37% progress, and 7.0 MB/s speed.
- Local mock-data browser check at 390x844: document width matched the viewport, the 820px task table scrolled only inside its 347px container, filters exposed the correct pressed state, Enter opened the selected task detail, and the console reported no errors.
- Browser checks used an isolated local Web preview with synthetic task rows only; Telegram was not connected and no download command was submitted.

### Notes

Changed files:
- `module/templates/index.html`: Added the five-column task renderer, unified detail hierarchy, accessible interactions, empty states, and stale-response guards.
- `module/static/css/index.css`: Added task-scoped desktop and narrow-screen styles.
- `tests/module/test_task_page_ui.py`: Added static DOM, interaction-contract, async-guard, and CSS tests.
- `docs/web-control-console.md`: Documented the compact task list and shared task-detail behavior.
- `docs/superpowers/plans/2026-07-29-task-panels-density.md`: Recorded the test-first implementation and verification plan.
- `progress.md`: Recorded implementation and fresh verification evidence.

Rollback:
- Revert the task-panel implementation and documentation commits. No database, API, configuration, runtime dependency, or persisted-data rollback is required.

## 2026-07-29 - Task: Deploy refined task panels to RackNerd

### What was done

- Pushed the four task-panel design, implementation, stale-detail fix, and documentation commits to GitHub `master`.
- Confirmed production tracked files were clean, preserved existing untracked backups, sessions, database backup, and runtime directories, then fast-forwarded the RackNerd checkout from `47299a3` to `6d5a3f4`.
- Verified the deployed task-page contracts and dependencies before restarting `tg-downloader.service`.
- Restarted the service and confirmed the updated task-panel CSS is available through both the production-local and public Web entrypoints.

### Testing

- GitHub `master` push -> `47299a3..6d5a3f4`; local and remote `master` matched at `6d5a3f4`.
- Production `.venv/bin/python` executed all four functions in `tests/module/test_task_page_ui.py` directly -> `4 task UI contracts passed`.
- Production `.venv/bin/pip check` -> no broken requirements.
- Production does not install the development-only `pytest` command or Node.js; no production dependencies were added. The full pytest suite and inline JavaScript syntax check had already passed locally before the push.
- `tg-downloader.service` -> `active` at `6d5a3f4`; four download workers started and the post-restart journal contained zero traceback, exception, critical, or error lines.
- Production-local Web: `/` -> `302`, `/login` -> `200`, updated CSS -> `200` with the `.task-table` marker.
- Public Web: `https://tgdn.wyichuan.cc/` -> `302`, `/login` -> `200`, updated CSS -> `200` with the `.task-table` marker.

### Notes

Changed files:
- `progress.md`: Recorded the push, production fast-forward, dependency boundaries, service restart, log review, and local/public smoke checks.

Rollback:
- Revert `160e2da` and `23bfe5f`, push `master`, fast-forward production, and restart `tg-downloader.service`. Preserve both SQLite databases, backups, sessions, and runtime files; this deployment made no schema, configuration, or dependency changes.

## 2026-07-29 - Task: Add direct download action for an undownloaded resource package

### What was done

- Added a compact download button beside the `未下载` status for stable aggregate resource packages.
- Added an exact-package download endpoint that creates and schedules a batch for only the clicked package.
- Kept the existing aggregate package selection unchanged when a direct package download is submitted.
- Added duplicate-submit protection through the existing idempotency-key contract and refreshed the package row after a successful submission.
- Documented the new aggregate single-package download API.

### Testing

- TDD red check: `.venv/bin/python -m pytest tests/module/test_channel_library_web.py::test_aggregate_single_package_download_preserves_existing_selection tests/module/test_channel_library_web.py::test_aggregate_package_and_keyword_monitor_tabs_have_complete_dom_contracts -q` -> `2 failed` before implementation because the route and UI action did not exist.
- Channel-library Web regression: `.venv/bin/python -m pytest tests/module/test_channel_library_web.py -q` -> `107 passed`.
- Full suite: `.venv/bin/python -m pytest -q` -> `545 passed, 1 skipped`.
- `.venv/bin/python check_imports.py` -> compatibility imports passed.
- Inline JavaScript parsed successfully with Node's `vm.Script`; `git diff --check` passed.

### Notes

Changed files:
- `module/templates/index.html`: Rendered and handled the direct package download button.
- `module/static/css/index.css`: Added compact inline status/action styling.
- `module/web.py`: Added the exact-package download-batch endpoint.
- `tests/module/test_channel_library_web.py`: Covered authentication, CSRF, idempotent exact-package creation, selection preservation, and UI contracts.
- `docs/web-control-console.md`: Documented the new endpoint.
- `progress.md`: Recorded the implementation and verification evidence.

Rollback:
- Revert this task's changes. No database schema, configuration, dependency, persisted selection, or deployment rollback is required.

## 2026-07-29 - Task: Align resource-package download status actions

### What was done

- Reserved a fixed-width invisible action slot beside non-downloadable package statuses.
- Kept the visible direct-download button and all empty status slots at the same width so the download-status column aligns vertically.
- Left download eligibility and click behavior unchanged.

### Testing

- TDD red check: `.venv/bin/python -m pytest tests/module/test_channel_library_web.py::test_aggregate_package_and_keyword_monitor_tabs_have_complete_dom_contracts tests/module/test_channel_library_web.py::test_channel_library_styles_define_responsive_split_workspace -q` -> `2 failed` before implementation because no placeholder contract or style existed.
- Channel-library Web regression: `.venv/bin/python -m pytest tests/module/test_channel_library_web.py -q` -> `107 passed`.
- Inline JavaScript parsed successfully with Node's `vm.Script`; `git diff --check` passed.

### Notes

Changed files:
- `module/templates/index.html`: Added the invisible status-action placeholder.
- `module/static/css/index.css`: Gave the button and placeholder a shared fixed action width.
- `tests/module/test_channel_library_web.py`: Added placeholder rendering and styling contracts.
- `progress.md`: Recorded the alignment change and verification evidence.

Rollback:
- Revert this alignment task to restore variable-width status cells. No API, database, configuration, dependency, or persisted-data rollback is required.

## 2026-07-29 - Task: Deploy direct resource-package download to RackNerd

### What was done

- Committed and pushed the direct resource-package download button, exact-package endpoint, and aligned status-action slots to GitHub `master`.
- Confirmed the production checkout had no tracked local changes, then fast-forwarded it from `9b1a1ef` to `ab47028`.
- Ran production compile and dependency checks before restarting `tg-downloader.service`.
- Verified the single-package route remains login-protected and the updated download-button CSS is served through both the production-local and public Web entrypoints.

### Testing

- Deployment-preflight full suite: `.venv/bin/python -m pytest -q` -> `545 passed, 1 skipped`.
- `.venv/bin/python check_imports.py` -> compatibility imports passed.
- Inline JavaScript parsed successfully with Node's `vm.Script`; `git diff --check` passed.
- GitHub `master` push -> `9b1a1ef..ab47028`.
- Production `.venv/bin/python -m py_compile module/web.py` passed and `.venv/bin/pip check` reported no broken requirements.
- `tg-downloader.service` -> `active` on `ab47028`; five worker-start log lines were present.
- The only post-restart line matching the broad failure keyword scan was the healthy performance counter `Failed downloads: 0`; there were no traceback, exception, critical, or real error lines.
- Production-local `/` -> `302`, `/login` -> `200`, the new single-package POST route -> authenticated `302`, and the CSS/template contained the new direct-download markers.
- Public `https://tgdn.wyichuan.cc/` -> `302`, `/login` -> `200`, the new single-package POST route -> authenticated `302`, and the public CSS contained the new placeholder marker.

### Notes

Changed files:
- `progress.md`: Recorded the push, production fast-forward, service restart, log review, and local/public smoke checks.

Rollback:
- Revert `ab47028`, push `master`, fast-forward production, and restart `tg-downloader.service`. Preserve both SQLite databases, backups, sessions, and runtime files; this release made no schema, configuration, dependency, or persisted-selection migration.

## 2026-07-29 - Task: Stabilize task progress and channel-package details

### What was done

- Replaced the generic single-package channel task title with the persisted resource-package title while preserving existing idempotent task identities.
- Added paginated channel-package task details with real package names, package status, processed/media progress, result counts, and known size.
- Switched ordinary task details to the existing paginated file endpoint and reduced channel detail refreshes to one bounded item-key query per page.
- Prevented overlapping dashboard/detail polls, preserved the last successful detail render during refresh or transient request failure, and removed the duplicate poll triggered by selecting a task.
- Added explicit processed, download-stage, and upload-stage counters so failed and skipped files no longer leave progress visually incomplete.
- Routed persisted channel-batch cancellation through the channel service so queued, scheduled, active, and upload-retry work can be cancelled while retaining cancelled task history.
- Added in-place task-action feedback while cancel, confirm, or clear requests are being submitted.

### Testing

- Focused TDD and regression set: `.venv/bin/pytest -q tests/module/test_task_state.py tests/test_channel_library_download.py tests/module/test_channel_library_web.py tests/module/test_task_page_ui.py tests/module/test_web.py` -> `193 passed`.
- Cancellation compatibility regression: `.venv/bin/pytest -q tests/test_web_cancel_task.py tests/test_web_prescan_retention.py tests/module/test_channel_library_web.py::test_cancel_channel_task_delegates_to_persisted_batch_service tests/module/test_channel_library_web.py::test_channel_task_packages_api_returns_exact_package_progress` -> `13 passed`.
- Full suite: `.venv/bin/pytest -q` -> `552 passed, 1 skipped`.
- `.venv/bin/python check_imports.py` -> compatibility imports passed.
- Inline JavaScript parsed successfully with Node `vm.Script`; changed Python modules compiled; `git diff --check` passed.
- Focused mypy did not produce a project type result because the existing environment lacks `pytz`/`croniter` stubs and the installed MarkupSafe stub reports an incompatible positional-only syntax error.
- Black check was reviewed but not claimed as repository-wide passing because the touched files contain pre-existing formatting drift outside this task; no unrelated bulk formatting was applied.

### Notes

Changed files:
- `module/task_state.py`: Added stable task-stage progress counters.
- `module/channel_library_store.py`: Added lightweight task-to-batch lookup and bounded package item-key loading.
- `module/channel_library_service.py`: Added persisted batch cancellation and single-package task titles.
- `module/web.py`: Added package detail pagination and channel-aware cancellation.
- `module/templates/index.html`: Added stable polling, paginated detail dispatch, package detail rendering, and action feedback.
- `module/static/css/index.css`: Styled package-level task detail rows.
- `tests/module/test_task_state.py`: Covered stage counters and aggregate-only progress.
- `tests/test_channel_library_download.py`: Covered package titles and queued cancellation.
- `tests/module/test_channel_library_web.py`: Covered package progress and Web cancellation delegation.
- `tests/module/test_task_page_ui.py`: Covered polling, pagination, package-title, and request-deduplication contracts.
- `docs/web-control-console.md`: Documented the task detail, polling, package progress, and cancellation behavior.
- `progress.md`: Recorded implementation and verification evidence.

Rollback:
- Revert the implementation commit, push `master`, fast-forward production, and restart `tg-downloader.service`. Preserve both SQLite databases and runtime files; this change adds no schema, configuration, dependency, or data migration.

## 2026-07-29 - Task: Deploy stable channel task details to RackNerd

### What was done

- Committed and pushed the reviewed task-progress, package-detail, polling, pagination, and channel-batch cancellation release to GitHub `master`.
- Confirmed the production checkout had no tracked local changes, then fast-forwarded it from `3f674ad` to `7805353`.
- Ran production compile, dependency, and deployed-template contract checks before restarting `tg-downloader.service`.
- Restarted the service and verified the task-detail CSS through both the production-local and public Web entrypoints.

### Testing

- GitHub push -> `3f674ad..7805353`; local, remote, and production `master` matched at `7805353`.
- Production `.venv/bin/python -m py_compile module/task_state.py module/channel_library_store.py module/channel_library_service.py module/web.py` passed.
- Production `.venv/bin/pip check` -> no broken requirements.
- Production template contract check found `taskPolling:false`, the paginated package endpoint, and `task-package-title`.
- `tg-downloader.service` -> `active`; four download workers started and the post-restart journal contained no traceback, exception, critical, or real error lines.
- `web_tasks.sqlite3` and `channel_library.sqlite3` integrity checks -> `ok`.
- Production-local `/` -> `302 /login`, `/login` -> `200`, and updated CSS marker -> present.
- Public `https://tgdn.wyichuan.cc/` -> `302 /login`, `/login` -> `200`, and updated CSS marker -> present.

### Notes

Changed files:
- `progress.md`: Recorded the push, production fast-forward, restart, database integrity, log review, and Web smoke checks.

Rollback:
- Revert `7805353`, push `master`, fast-forward production, and restart `tg-downloader.service`. Preserve both SQLite databases, backups, sessions, and runtime files; this release made no schema, configuration, dependency, or persisted-data migration.

## 2026-07-29 - Task: Harden persistent task restart recovery

### What was done

- Added additive schema-v1 migration for persisted upload byte and speed progress, with explicit rejection of databases created by newer unsupported code.
- Bounded persisted terminal task history and removed its file rows together with evicted tasks.
- Marked non-resumable ordinary tasks and their active file rows as interrupted after a service restart.
- Reconciled persisted channel tasks with durable download batches so resumable batches requeue, cancelled and completed batches retain their terminal meaning, and retained upload failures remain eligible for upload-only retry.
- Added a clear task-detail explanation when a task was interrupted by a service restart.
- Reviewed startup ordering, migration transaction boundaries, history cleanup, and channel restart reconciliation; no blocking correctness issue remained after using the shared restart error constant.

### Testing

- Focused task, channel-download, channel-Web, task-page, Web, cancellation, and prescan regressions: `TMD_TASK_DB_PATH=<temporary>/web_tasks.sqlite3 .venv/bin/python -m pytest -q tests/module/test_task_state.py tests/test_channel_library_download.py tests/module/test_channel_library_web.py tests/module/test_task_page_ui.py tests/module/test_web.py tests/test_web_cancel_task.py tests/test_web_prescan_retention.py` -> `213 passed`.
- Full suite with an isolated task database: `TMD_TASK_DB_PATH=<temporary>/web_tasks.sqlite3 .venv/bin/python -m pytest -q` -> `560 passed, 1 skipped`.
- Migrated a copy of the current workspace task database -> schema version `1`, upload-progress columns present, `PRAGMA integrity_check` -> `ok`.
- `.venv/bin/python check_imports.py` passed; changed Python modules compiled; inline JavaScript parsed successfully with Node; `git diff --check` passed.

### Notes

Changed files:
- `module/task_state.py`: Added schema migration, persisted upload progress, restart recovery, and bounded persistent history.
- `module/channel_library_service.py`: Added durable channel-task restart reconciliation.
- `module/channel_library_store.py`: Included persisted batch error state in lightweight task lookup.
- `module/templates/index.html`: Added the restart-interruption detail message.
- `module/static/css/index.css`: Styled task-detail error text.
- `tests/module/test_task_state.py`: Covered migration, persistence, history pruning, restart recovery, and newer-schema rejection.
- `tests/test_channel_library_download.py`: Covered resumable, upload-retry, and failed channel-task reconciliation.
- `tests/module/test_task_page_ui.py`: Covered the restart-interruption UI contract.
- `docs/web-control-console.md`: Documented schema v1, history bounds, and restart behavior.
- `progress.md`: Recorded implementation, audit, and verification evidence.

Rollback:
- Revert the phase-three implementation commit before deployment. If schema v1 has already been deployed, preserve the SQLite database: the two added columns and schema marker are additive, while production rollback should use the verified pre-deploy database backup if the older code must see schema version 0.

## 2026-07-29 - Task: Deploy persistent task restart recovery to RackNerd

### What was done

- Confirmed the production checkout had no tracked changes, fetched the reviewed `master`, and stopped `tg-downloader.service`.
- Created a restricted release backup with the SQLite backup API for both production databases, plus `config.yaml`, sessions, and the pre-deploy commit marker.
- Verified the schema-v0 task database migration on a separate backup copy before updating production.
- Fast-forwarded production from `7805353` to `96df898`, ran compile and dependency checks, then started the service.
- Confirmed the live task database migrated to schema v1 with the new upload-progress columns while the channel database remained intact.
- Verified the production-local and public Web entrypoints and the deployed task-detail error styling.

### Testing

- Backup directory: `/root/telegram_media_downloader/backups/release-20260729-093149-phase3`; database, configuration, and session backup files are mode `0600`.
- Backup `web_tasks.sqlite3` -> schema `0`, `PRAGMA integrity_check` -> `ok`; backup `channel_library.sqlite3` -> schema `0`, integrity -> `ok`.
- Migration check copy -> schema `1`, integrity -> `ok`, with `uploaded_size` and `upload_speed` present.
- Production `.venv/bin/python -m py_compile module/task_state.py module/channel_library_service.py module/channel_library_store.py module/web.py` passed; `.venv/bin/pip check` reported no broken requirements.
- Live `web_tasks.sqlite3` -> schema `1`, integrity -> `ok`, upload-progress columns present; live `channel_library.sqlite3` integrity -> `ok`.
- No ordinary task required `restart_interrupted` recovery during this deployment.
- `tg-downloader.service` -> `active`; four workers started and the post-start journal contained no traceback, exception, critical, or error lines.
- Current and backed-up `config.yaml` SHA-256 checksums match.
- Production-local `/` -> `302 /login`, `/login` -> `200`; public `/` -> `302 /login`, public `/login` -> `200`; public CSS contains `task-detail-error`.

### Notes

Changed files:
- `progress.md`: Recorded the production backup, migration rehearsal, fast-forward deployment, schema verification, service health, and Web smoke checks.

Rollback:
- Preferred code rollback: revert `96df898`, push `master`, fast-forward production, and restart `tg-downloader.service`; the additive columns can remain in place for the previous code.
- Exact pre-deploy data rollback, only if required and with the service stopped, is available from `/root/telegram_media_downloader/backups/release-20260729-093149-phase3`. Restoring that snapshot would discard task-state changes written after this deployment, so preserve the current databases before any restore.

## 2026-07-29 - Task: Design dual-role resource delivery Bot

### What was done

- Defined one unified Bot lifecycle that keeps the existing management Bot and adds a separate activated-user resource Bot role without creating a second application entrypoint.
- Selected main-account download plus resource-Bot upload as the primary delivery path, with one persistent serial worker and explicit partial-upload behavior.
- Defined one-time activation keys, one-channel-per-user binding, channel-admin permission verification, stable-package search, idempotent delivery jobs, and a separate resource Bot SQLite database.
- Scoped removal of the public `/forward` entry while preserving `/listen_forward` and `/forward_to_comments`.
- Defined the local secret-handling, configuration-example, testing, rollback, and final server-handoff boundaries.

### Testing

- Baseline full suite before implementation: `.venv/bin/pytest -q` -> `560 passed, 1 skipped`.
- Confirmed the installed Pyrogram patch exposes `ChatMemberUpdatedHandler`.
- Reviewed the design for placeholders, internal contradictions, scope expansion, secret exposure, database ownership, restart handling, and production handoff boundaries.

### Notes

Changed files:
- `docs/superpowers/specs/2026-07-29-dual-role-resource-bot-design.md`: Added the approved dual-role Bot architecture and delivery contract for user review.
- `progress.md`: Recorded the design decisions and pre-implementation test baseline.

Rollback:
- Revert the design commit; no runtime code, configuration, database, Telegram account, or production service state was changed.

## 2026-07-29 - Task: Plan dual-role resource Bot implementation

### What was done

- Converted the approved design into eight independently testable implementation tasks covering configuration, persistent access state, delivery, Bot interaction, lifecycle integration, documentation, and final verification.
- Locked the implementation interfaces for activation keys, channel binding, delivery-job idempotency, serial worker recovery, search sessions, and the unified Bot manager.
- Selected inline test-driven execution on the dedicated feature branch, with no multi-agent file modification.

### Testing

- Reviewed the plan against every section of `docs/superpowers/specs/2026-07-29-dual-role-resource-bot-design.md`.
- Scanned the plan for placeholder actions, missing test commands, inconsistent signatures, unowned files, and production actions outside the authorized boundary.

### Notes

Changed files:
- `docs/superpowers/plans/2026-07-29-dual-role-resource-bot.md`: Added the test-driven implementation plan and final completion audit.
- `progress.md`: Recorded the implementation-plan boundary and review evidence.

Rollback:
- Revert the implementation-plan commit; runtime code, local configuration, databases, Telegram clients, and production state remain unchanged.

## 2026-07-29 - Task: Prepare dual-role Bot configuration and remove `/forward`

### What was done

- Added the optional `resource_bot_token` application setting and safe placeholder values for both Bot roles in the example configuration.
- Added an exact local ignore rule for `.env.new` so the real resource Bot Token cannot be staged accidentally.
- Extracted the management Bot command menu and help text into testable builders.
- Removed the legacy `/forward` command from the management Bot menu, help text, and Handler registration while preserving `/listen_forward`, `/forward_to_comments`, and their shared implementation.

### Testing

- RED verification: focused configuration and command tests failed with missing `resource_bot_token`, `build_admin_bot_commands`, and `build_admin_help_text`.
- Focused GREEN verification: `.venv/bin/pytest -q tests/module/test_app.py::test_resource_bot_token_defaults_empty tests/module/test_app.py::test_resource_bot_token_loads_from_config tests/module/test_bot_commands.py` -> `4 passed`.
- Management Bot regression: `.venv/bin/pytest -q tests/module/test_comment_workflow.py tests/module/test_app.py` -> `111 passed`.
- `git check-ignore .env.new` confirmed the real local Token file is ignored.

### Notes

Changed files:
- `.gitignore`: Added the exact `.env.new` ignore rule.
- `config.example.yaml`: Added management and resource Bot Token placeholders.
- `module/app.py`: Loaded the optional resource Bot Token.
- `module/bot.py`: Added pure command/help builders and removed the `/forward` public entry.
- `tests/module/test_app.py`: Covered resource Bot configuration defaults and loading.
- `tests/module/test_bot_commands.py`: Covered the management command and help surface.
- `progress.md`: Recorded implementation and verification evidence.

Rollback:
- Revert this task commit to restore the original command entry and configuration surface; no database or production configuration was changed.

## 2026-07-29 - Task: Add resource Bot access and delivery state store

### What was done

- Added an independent schema-v1 SQLite store for one-time activation keys, activated users, one-channel bindings, and persistent resource-delivery jobs.
- Stored only activation-key SHA-256 digests and short display prefixes; key redemption and user activation are atomic.
- Added active-user enforcement, one-user/one-channel ownership, permission-loss persistence, unbinding, revocation, queued-job cancellation, idempotent job creation, serial queue claiming, bounded progress updates, terminal states, and restart interruption recovery.
- Applied WAL, foreign keys, busy timeout, newer-schema rejection, integrity coverage, and private `0600` database permissions.

### Testing

- RED verification: `.venv/bin/pytest -q tests/module/test_resource_bot_store.py` failed during collection because `module.resource_bot_store` did not exist.
- GREEN verification: `.venv/bin/pytest -q tests/module/test_resource_bot_store.py` -> `13 passed`.
- Tests covered fresh schema version/integrity, newer-schema rejection, hashed one-time keys, invalid keys, reactivation, binding ownership, permission loss, idempotent jobs, progress, restart recovery, and revocation.

### Notes

Changed files:
- `module/resource_bot_store.py`: Added the resource Bot state database and transactional API.
- `tests/module/test_resource_bot_store.py`: Added schema, activation, binding, queue, progress, recovery, and revocation tests.
- `progress.md`: Recorded implementation and verification evidence.

Rollback:
- Revert this task commit. The new `resource_bot.sqlite3` is independent and can be preserved unused or backed up and removed while the service is stopped.

## 2026-07-29 - Task: Add main-account download and resource Bot upload delivery

### What was done

- Added the persistent resource-delivery worker that reads package snapshots with the main Telegram account and uploads the downloaded media with the resource Bot.
- Enforced stable package revisions, active user/channel permissions, complete download before upload, safe temporary filenames, compatible Telegram album grouping, and deterministic cleanup.
- Persisted per-item download/upload progress and terminal errors for missing sources, download failures, target permission loss, upload failures, partial uploads, and service interruption.
- Kept delivery globally serial, recovered interrupted jobs at startup, notified users privately of terminal results, and prevented retries after a partial upload.

### Testing

- Focused delivery tests: `.venv/bin/pytest -q tests/module/test_resource_delivery.py` -> `12 passed`.
- Resource state and delivery regression: `.venv/bin/pytest -q tests/module/test_resource_bot_store.py tests/module/test_resource_delivery.py` -> `25 passed`.
- `.venv/bin/python -m py_compile module/resource_delivery.py tests/module/test_resource_delivery.py` passed.
- `git diff --check` passed.

### Notes

Changed files:
- `module/resource_delivery.py`: Added package snapshot validation, main-account download, resource-Bot upload, progress persistence, serial worker lifecycle, interruption handling, and cleanup.
- `tests/module/test_resource_delivery.py`: Added executable coverage for media planning, success/failure paths, permission loss, serial execution, and active-job interruption.
- `progress.md`: Recorded implementation and verification evidence.

Rollback:
- Revert the resource-delivery commit. Existing queued resource jobs should be backed up before rollback; this task does not modify the resource database schema.

## 2026-07-29 - Task: Add activated resource Bot access, binding, search, and publishing

### What was done

- Added management commands to create one-time resource activation keys and revoke activated users without logging full keys.
- Added the resource Bot private command flow for activation, status, binding instructions, channel status, unbinding, help, and keyword search.
- Bound channels only after a pending activated user is verified as the channel owner/administrator and the resource Bot is verified as an administrator with post permission.
- Added permission-loss handling for channel membership updates and revalidation before every publish action.
- Added user-scoped 30-minute search sessions, five-result stable-package pages, bounded session retention, callback ownership checks, and idempotent one-click delivery enqueue.

### Testing

- RED verification: `.venv/bin/pytest -q tests/module/test_resource_bot.py` failed during collection because `module.resource_bot` did not exist.
- Resource Bot command, permission, binding, search, and publish tests: `.venv/bin/pytest -q tests/module/test_resource_bot.py` -> `12 passed`.
- Resource store, delivery, and interaction regression: `.venv/bin/pytest -q tests/module/test_resource_bot_store.py tests/module/test_resource_delivery.py tests/module/test_resource_bot.py` -> `37 passed`.
- `.venv/bin/python -m py_compile module/resource_bot.py tests/module/test_resource_bot.py` passed.
- `git diff --check` passed.

### Notes

Changed files:
- `module/resource_bot.py`: Added management commands, resource Bot lifecycle/handlers, permission helpers, activation and channel binding, stable search sessions, pagination, and publish callbacks.
- `tests/module/test_resource_bot.py`: Added access, permission, binding, search, session isolation, and idempotent publish coverage.
- `progress.md`: Recorded implementation and verification evidence.

Rollback:
- Revert the resource Bot interaction commit. The independent resource database can remain unused; any issued activation keys and bindings should be preserved or explicitly revoked before a later deployment rollback.

## 2026-07-29 - Task: Unify management and resource Bot lifecycle

### What was done

- Replaced the single-role global startup with one manager behind the existing `start_download_bot` and `stop_download_bot` entrypoints.
- Kept the existing management `DownloadBot` as the compatibility role while conditionally starting the resource state store, resource Bot role, and serial delivery worker when `resource_bot_token` is configured.
- Added reverse cleanup for partial startup failures, idempotent repeated start/stop calls, resource administrator Handler registration, and a combined management command menu.
- Added the independent `resource_bot.sqlite3` default path plus `TMD_RESOURCE_BOT_DB_PATH` test override.
- Updated runtime liveness to use the same single entry for either configured Bot token and reject a resource Bot token without the management Bot token.

### Testing

- RED verification: `.venv/bin/pytest -q tests/module/test_bot_manager.py` failed during collection because `BotManager` did not exist.
- Unified lifecycle tests: `.venv/bin/pytest -q tests/module/test_bot_manager.py` -> `7 passed`.
- Management and lifecycle regression: `.venv/bin/pytest -q tests/module/test_bot_manager.py tests/module/test_comment_workflow.py tests/module/test_bot_commands.py tests/module/test_app.py` -> `120 passed`.
- `.venv/bin/python -m py_compile module/bot.py module/download_runtime.py module/resource_bot.py tests/module/test_bot_manager.py` passed.
- `git diff --check` passed.

### Notes

Changed files:
- `module/bot.py`: Added the unified manager, resource component construction/rollback, resource admin registration, and management-role stop lifecycle.
- `module/download_runtime.py`: Started and stopped the single Bot manager when either Bot token is configured.
- `module/resource_bot.py`: Added the management Bot resource command-menu entries.
- `tests/module/test_bot_manager.py`: Covered optional startup, dual-role startup, configuration rejection, rollback, stop ordering, idempotency, database paths, and runtime liveness.
- `progress.md`: Recorded implementation and verification evidence.

Rollback:
- Revert the unified-manager commit to restore the prior management-only lifecycle. Leave `resource_bot_token` unset during rollback so no unmanaged resource Bot client or delivery worker is expected.

## 2026-07-29 - Task: Document resource Bot usage and production handoff

### What was done

- Documented the management Bot and resource Bot role split, activation/revocation commands, channel binding, stable-package search, and one-click publication flow in Chinese and English.
- Clarified that the main Telegram account reads/downloads source media while only the resource Bot needs access to the user's destination channel.
- Documented serial delivery, Telegram album preservation, partial-upload behavior, restart handling, and the independent `resource_bot.sqlite3` state boundary.
- Added a production handoff checklist for restricted backups, the exact configuration delta, secret-safe validation, database initialization/integrity, service startup, live Telegram acceptance, and rollback.
- Kept `.env.new` as a local ignored token source and excluded all real tokens and server credentials from tracked files.

### Testing

- RED verification: `.venv/bin/pytest -q tests/module/test_bot_commands.py::test_resource_bot_configuration_is_documented_without_real_secret` failed because `docs/resource-bot-server-handoff.md` did not exist.
- Documentation contract: `.venv/bin/pytest -q tests/module/test_bot_commands.py` -> `3 passed`.
- `git diff --check` passed.
- Searched the updated documentation and example configuration for the expected resource token placeholder, resource commands, and independent database references.

### Notes

Changed files:
- `README_CN.md`: Added the dual-role user workflow, transfer model, commands, configuration, and partial-upload warning.
- `README.md`: Added the corresponding English role, workflow, configuration, and state summary.
- `docs/web-control-console.md`: Documented how resource Bot search and delivery read the channel index without changing Web selections.
- `docs/resource-bot-server-handoff.md`: Added the non-executed production backup, configuration, restart, acceptance, and rollback checklist.
- `tests/module/test_bot_commands.py`: Added a secret-safe documentation/configuration contract.
- `progress.md`: Recorded documentation and verification evidence.

Rollback:
- Revert the documentation commit. No production configuration, service, Bot account, Telegram channel, session, or database was changed by this task.

## 2026-07-29 - Task: Complete local dual-role resource Bot verification

### What was done

- Audited the implementation against the approved design and confirmed two Bot accounts are owned by one `bot.py` lifecycle while the public `/forward` command remains removed and `/listen_forward` plus `/forward_to_comments` remain registered.
- Added cleanup for a management Bot that fails during startup, restricted destination binding to Telegram channels, and rechecked activation/binding state at every media download/upload boundary so administrator revocation stops active work safely.
- Confirmed one-time hashed activation keys, administrator revocation, one-user/one-channel binding, permission-loss handling, stable five-item searches, user-scoped expiring callbacks, idempotent enqueue, main-account download, resource-Bot upload, media-group ordering, serial delivery, cleanup, partial failure, and restart interruption behavior.
- Confirmed the real local `.env.new` remains ignored and untracked, example/documentation values are placeholders, and production configuration/restart/live acceptance were not performed.

### Testing

- Focused resource feature tests: `.venv/bin/pytest -q tests/module/test_resource_bot_store.py tests/module/test_resource_delivery.py tests/module/test_resource_bot.py tests/module/test_bot_manager.py tests/module/test_bot_commands.py` -> `47 passed` before final audit hardening.
- Management Bot and channel-library regressions: `.venv/bin/pytest -q tests/module/test_comment_workflow.py tests/module/test_channel_library_queries.py tests/module/test_channel_library_store.py tests/module/test_channel_library_service.py tests/module/test_channel_library_workflow.py` -> `240 passed`.
- Final combined resource/management/channel regression after audit hardening -> `290 passed`.
- Final complete suite with isolated `TMD_TASK_DB_PATH` and `TMD_RESOURCE_BOT_DB_PATH` -> `612 passed, 1 skipped`.
- `.venv/bin/python check_imports.py` passed.
- Changed application modules compiled with `.venv/bin/python -m py_compile`.
- `.venv/bin/pip check` -> `No broken requirements found`.
- Fresh `resource_bot.sqlite3` -> schema `1`, `PRAGMA integrity_check` -> `ok`, file mode -> `0600`.
- `git diff --check` passed; `.env.new` is ignored by the exact `/.env.new` rule and is absent from tracked files.
- Secret-pattern scan found no Bot-token-shaped value in tracked implementation or operational documentation.

### Notes

Changed files:
- `module/bot.py`: Cleaned up partially started management Bot roles.
- `module/resource_bot.py`: Restricted binding events to Telegram channels.
- `module/resource_delivery.py`: Rechecked user activation and target binding at each safe media boundary and before FloodWait upload retry.
- `tests/module/test_bot_manager.py`: Covered management-role partial-start rollback.
- `tests/module/test_resource_bot.py`: Covered actual resource client Handler registration and channel-only binding.
- `tests/module/test_resource_delivery.py`: Covered active delivery interruption after administrator revocation.
- `progress.md`: Recorded the final requirement audit and local verification evidence.

Rollback:
- Revert the final verification commit to remove only the audit hardening and its tests/log entry, or revert the feature commits in reverse order for a complete local rollback. Production data/configuration rollback is not applicable because no production operation was performed.

## 2026-07-29 - Task: Deploy dual-role resource Bot to RackNerd

### What was done

- Fast-forwarded local `master` to the locally verified resource Bot implementation, pushed it to GitHub, and fast-forwarded the RackNerd production checkout from `b89ea3b` to `cc64bfd`.
- Stopped `tg-downloader.service` and created a restricted production backup of `config.yaml`, sessions, the pre-deploy commit, and both existing SQLite databases before changing code or configuration.
- Read the new resource Bot Token from the ignored local `.env.new` without displaying it, added only `resource_bot_token` to production `config.yaml`, and tightened the live configuration to mode `0600`.
- Initialized schema-v1 `resource_bot.sqlite3`, started the unified management/resource Bot lifecycle, and tightened the new resource Bot session files to mode `0600`.
- Verified both Telegram Bot identities and command menus, including removal of public `/forward` and preservation of the resource/management command split.

### Testing

- Production backup: `/root/telegram_media_downloader/backups/release-20260729-193337-resource-bot` (`177M`, directory mode `0700`); backed-up `channel_library.sqlite3` and `web_tasks.sqlite3` integrity -> `ok`; `config.yaml` and commit marker mode -> `0600`.
- Production code -> `cc64bfd`; `check_imports.py`, changed-module compilation, and `.venv/bin/pip check` passed before restart.
- Semantic configuration comparison against the backup reported only `resource_bot_token` as changed; management and resource Bot Tokens are both configured and distinct without printing either value.
- Live databases: `channel_library.sqlite3` schema `0`, `web_tasks.sqlite3` schema `1`, `resource_bot.sqlite3` schema `1`; all three `PRAGMA integrity_check` results -> `ok`.
- `resource_bot.sqlite3`, WAL, SHM, production `config.yaml`, and the resource Bot session/session-journal files are mode `0600`.
- Telegram Bot API identity checks -> management `@unraidnc_bot`, resource `@wang18transbot`.
- Management Bot commands -> `help,get_info,download,prescan,listen_forward,add_filter,set_language,stop,retry_failed,create_resource_key,revoke_resource_user`; resource Bot commands -> `start,activate,status,bind,channel,unbind,search,help`.
- `tg-downloader.service` -> `active/running`, `NRestarts=0`, `ExecMainStatus=0`, approximately `102MB` memory; four existing download workers started.
- Post-start journal -> `21` lines and `0` traceback/exception/critical/failed/error-like lines.
- Production-local Web `/` -> `302 /login`, `/login` -> `200`; public `https://tgdn.wyichuan.cc/` -> `302 /login`, public `/login` -> `200`.
- Live activation-key redemption, destination-channel binding, single-media publication, and album publication remain manual Telegram acceptance actions for the owner because they require an owner-controlled user and channel.

### Notes

Changed files:
- `progress.md`: Recorded the production backup, code/configuration deployment, database initialization, service health, Bot identities/commands, Web checks, and remaining manual Telegram acceptance.

Rollback:
- Stop `tg-downloader.service`, preserve the current configuration/sessions/three SQLite databases, restore `config.yaml` from `/root/telegram_media_downloader/backups/release-20260729-193337-resource-bot/config.yaml` (or remove only `resource_bot_token`), revert the resource Bot commits on `master`, fast-forward production, and restart the service.
- Preserve `resource_bot.sqlite3` during ordinary code rollback; the pre-feature code does not use it. Restore database backups only for confirmed corruption or an incompatible schema problem, with the service stopped and the current files retained first.

## 2026-07-30 - Task: Fix resource activation-key command dispatch

### What was done

- Diagnosed `/create_resource_key` producing no reply in production: the existing management Bot catch-all text Handler matched the command first in Handler group `0`, so the later resource administration Handler never ran.
- Registered `/create_resource_key` and `/revoke_resource_user` in Handler group `-1`, ahead of the generic management text Handler.
- Added a regression contract for the resource administration Handler priority and updated the lifecycle test fake to model Handler groups.

### Testing

- Production diagnosis before the fix: `resource_activation_keys` remained at `0` rows after the command, confirming the key Handler had not run; no service/database/Token error was present.
- RED verification: the new Handler-priority test observed groups `[0, 0]` instead of `[-1, -1]`.
- Focused management/resource regressions: `.venv/bin/pytest -q tests/module/test_resource_bot.py tests/module/test_bot_manager.py tests/module/test_bot_commands.py tests/module/test_comment_workflow.py` -> `131 passed`.
- Complete suite with isolated task/resource databases -> `613 passed, 1 skipped`.
- Changed modules compiled and `git diff --check` passed.

### Notes

Changed files:
- `module/resource_bot.py`: Registered resource administration commands in the higher-priority Handler group.
- `tests/module/test_resource_bot.py`: Added the Handler-priority regression contract.
- `tests/module/test_bot_manager.py`: Allowed the lifecycle fake client to record Handler groups.
- `progress.md`: Recorded the production symptom, root cause, fix, and verification.

Rollback:
- Revert the activation-command dispatch fix and restart `tg-downloader.service`; no schema, configuration, activation key, or other persisted production data is changed by this patch.

## 2026-07-30 - Task: Add independent resource publishing management page

### What was done

- Added an independent Web “发布” tab for resource Bot delivery jobs without mixing them into the existing download Tasks page.
- Added newest-first delivery listing, queue position, package/source/target context, project-level download and upload item counts, current download/upload speeds, timestamps, and safe result summaries.
- Added safe management actions: queued jobs can be cancelled, terminal rows can be cleared individually, and all terminal history can be cleared; active work and partial uploads are not retried or interrupted from Web.
- Migrated `resource_bot.sqlite3` additively from schema 1 to schema 2 with download/upload speed fields and exposed the live store through the existing application lifecycle.
- Added throttled transfer-speed persistence for normal downloads/uploads and retained Telegram media groups while measuring album upload reads.
- Documented the Publishing page, Web API, schema migration, progress semantics, and rollback boundary.

### Testing

- RED verification initially failed because `TransferSpeedTracker` and the independent Publishing DOM/API contracts did not exist.
- Focused resource/store/delivery/Bot/Web/UI tests -> `42 passed`.
- Web, task-page, resource Bot, and Bot-manager regressions -> `58 passed`.
- Complete suite with isolated task/resource databases -> `621 passed, 1 skipped`.
- Changed modules compiled with `.venv/bin/python -m compileall -q`.
- Inline JavaScript parsed successfully with Node (`inline scripts parse: 1`).
- `git diff --check` passed.

### Notes

Changed files:
- `module/resource_bot_store.py`: Added schema-v2 migration, speed state, delivery listing/summary, queued cancellation, and terminal-history cleanup.
- `module/resource_delivery.py`: Added throttled download/upload speed tracking while preserving media-group delivery.
- `module/app.py` and `module/bot.py`: Exposed and cleared the live resource store through the application lifecycle.
- `module/web.py`: Added authenticated, CSRF-protected resource delivery Web APIs.
- `module/templates/index.html` and `module/static/css/index.css`: Added the independent Publishing page, one-second polling, status filtering, and safe actions.
- `tests/module/`: Added schema migration, progress, lifecycle, API, DOM, and regression coverage.
- `README.md`, `README_CN.md`, and `docs/`: Documented the new page and schema behavior.
- `progress.md`: Recorded implementation and verification evidence.

Rollback:
- Revert this implementation commit and restart the service. Because schema 2 is not accepted by the previous schema-1 code, production rollback must restore the pre-deploy `resource_bot.sqlite3` backup with the service stopped; preserve the current schema-2 database separately before restoring.

## 2026-07-30 - Task: Deploy resource publishing management page

### What was done

- Pushed commit `80c085d` and fast-forwarded the RackNerd production checkout from `116bf21`.
- Stopped `tg-downloader.service` and created a restricted pre-deploy backup containing the previous commit marker, configuration/auth files, sessions, and consistent copies of all three SQLite databases.
- Migrated the live `resource_bot.sqlite3` from schema 1 to schema 2, restarted the unified application, and verified the independent Publishing page through the authenticated production Web session.
- Confirmed the two existing completed deliveries remain visible with their original package IDs and complete download/upload item counts.

### Testing

- Production backup: `/root/telegram_media_downloader/backups/release-20260729-204948-publishing-page` (`177M`, directory mode `0700`).
- Backup database integrity -> `channel_library.sqlite3: ok`, `web_tasks.sqlite3: ok`, `resource_bot.sqlite3: ok`; the backed-up resource database remains schema 1.
- Production code -> `80c085d`; `check_imports.py`, module compilation, and `.venv/bin/pip check` passed before restart.
- Live databases -> channel schema `0`, Web task schema `1`, resource Bot schema `2`; all integrity checks -> `ok`; live resource database mode -> `0600`.
- Authenticated production Web acceptance -> Publishing tab present, CSRF token available, delivery API returned exactly two completed jobs for packages `32926` and `32929`, with no queued or active work and zero inactive speeds.
- Persisted delivery counts remained `32926: 26/26 downloaded, 26/26 uploaded` and `32929: 12/12 downloaded, 12/12 uploaded`.
- Service -> `active/running`, `NRestarts=0`, `ExecMainStatus=0`, about `95MB` memory; four download workers started.
- Post-deploy journal -> `39` lines and `0` traceback/exception/critical/start-failure/error markers.
- Local and public Web roots redirect to login; public login returns `200`.

### Notes

Changed files:
- `progress.md`: Recorded the production backup, schema migration, service health, authenticated Publishing-page acceptance, preserved delivery history, and rollback point.

Rollback:
- Stop `tg-downloader.service`, preserve the current schema-2 resource database separately, restore `config.yaml`, sessions as needed, and `resource_bot.sqlite3` from `/root/telegram_media_downloader/backups/release-20260729-204948-publishing-page`, reset the code to commit `116bf21`, and restart the service. Do not restore the other databases unless their integrity is independently in question.

## 2026-07-30 - Task: Stream resource publishing by media group

### What was done

- Changed resource delivery from downloading an entire package before upload to processing one compatible media group or single item at a time.
- Preserved compatible Telegram albums with the existing 10-item group limit, uploaded each group before downloading the next, and deleted each successfully uploaded group's local files immediately.
- Kept cumulative project-level download/upload item counts and live transfer speeds across group transitions.
- Marked failures after any successful group as `partial_upload`, retained the published count, and kept partial jobs non-retryable to avoid duplicate channel posts.
- Documented the reduced temporary-disk footprint, partial-publication semantics, and live acceptance steps.

### Testing

- RED verification: the group-order test failed because the second group started downloading while the first group's files still existed; the later-group failure test observed no upload before the download failure.
- Resource delivery worker tests -> `15 passed`.
- Resource store, delivery, Bot, lifecycle, and command regressions -> `56 passed`.
- Complete suite with isolated `TMD_TASK_DB_PATH` and `TMD_RESOURCE_BOT_DB_PATH` -> `622 passed, 1 skipped`.
- Changed modules compiled, `check_imports.py` passed, and `git diff --check` passed.

### Notes

Changed files:
- `module/resource_delivery.py`: Added per-group download/upload/cleanup sequencing and cumulative partial-upload failure handling.
- `tests/module/test_resource_delivery.py`: Added ordering, immediate cleanup, and later-group download-failure regressions.
- `README.md`, `README_CN.md`, and `docs/`: Documented the group pipeline, bounded temporary disk use, and acceptance behavior.
- `progress.md`: Recorded implementation and verification evidence.

Rollback:
- Revert this implementation commit and restart `tg-downloader.service`; no schema, configuration, activation, binding, or existing delivery-history data changes are required.

## 2026-07-30 - Task: Stage complete resource packages before channel publication

### What was done

- Diagnosed production package `33383`: all 30 files downloaded, the first destination album upload failed at `0/30`, target-channel Bot permissions remained valid, temporary files were cleaned, and the service remained healthy.
- Replaced direct group publication with a private staging-channel pipeline: download one compatible group, stage it, immediately delete local files, then copy all staged groups to the user channel only after the complete package is ready.
- Preserved compatible Telegram albums through Pyrogram server-side media-group copy and kept the existing 10-item group limit.
- Added schema-3 staging manifests containing the exact temporary message IDs, plus startup and terminal cleanup so interrupted work does not leave untracked staging content.
- Required a configured private staging channel where the resource Bot can publish and delete messages, and added safe Telegram exception-type logging for staging/copy failures.
- Kept destination-copy partial failures as non-retryable `partial_upload`; download or staging failures before copying leave the user channel untouched.

### Testing

- RED verification: staging-flow tests initially failed because the delivery service had no staging-channel interface.
- Resource store, delivery, Bot, lifecycle, command, and application regressions -> `63 passed`.
- Complete suite with isolated `TMD_TASK_DB_PATH` and `TMD_RESOURCE_BOT_DB_PATH` -> `624 passed, 1 skipped`.
- Confirmed the installed Pyrogram client exposes `copy_media_group`, `copy_message`, and `delete_messages`.
- Changed modules compiled and `git diff --check` passed.

### Notes

Changed files:
- `module/resource_delivery.py`: Added staged group upload, deferred destination copy, exact-message cleanup, permission checks, and safer failure logging.
- `module/resource_bot_store.py`: Migrated to schema 3 and persisted staging manifests.
- `module/app.py`, `module/bot.py`, and `config.example.yaml`: Added and enforced `resource_staging_chat_id`.
- `tests/module/`: Added staging order, no-early-publication, partial-copy, migration, and recovered-cleanup coverage.
- `README.md`, `README_CN.md`, and `docs/`: Documented configuration, lifecycle, acceptance, and rollback behavior.
- `progress.md`: Recorded the production diagnosis, implementation, and verification evidence.

Rollback:
- Stop `tg-downloader.service`, preserve the schema-3 resource database, restore the pre-deploy schema-2 resource database and configuration backup, return code to the pre-deploy commit, and restart. Other databases do not require rollback.

## 2026-07-30 - Task: Deploy private staging-channel resource publishing

### What was done

- Derived production staging channel ID `-1004472735675` from the provided private-channel message link and verified the resource Bot is an administrator with publish and delete permissions.
- Confirmed there were no active or queued resource deliveries, stopped the service, and created a restricted pre-deploy backup.
- Fast-forwarded production from `70316fc` to `1a5d76a`, added only `resource_staging_chat_id` to protected configuration, and migrated `resource_bot.sqlite3` from schema 2 to schema 3.
- Restarted the unified service and verified authenticated Publishing-page/API access, preserved delivery history, empty staging manifests, service health, and live staging-channel send/delete behavior.

### Testing

- Production backup: `/root/telegram_media_downloader/backups/release-20260730-042143-staging-pipeline` (`177M`, directory mode `0700`).
- Backup database integrity -> channel `ok` schema 0, Web task `ok` schema 1, resource Bot `ok` schema 2.
- Production preflight -> `check_imports.py`, changed-module compilation, and `.venv/bin/pip check` passed.
- Live database integrity -> channel `ok` schema 0, Web task `ok` schema 1, resource Bot `ok` schema 3; resource database mode `0600`.
- Authenticated Web acceptance -> login `200/code=1`, root `200` with Publishing tab, delivery API `200`, three preserved jobs (`2 completed`, `1 failed`, no active/queued work).
- Staging acceptance -> Bot permission `administrator/post/delete`; one deployment-check message was successfully sent and deleted.
- Service -> `active/running`, `NRestarts=0`, `ExecMainStatus=0`, approximately `99MB` memory; recent journal contained no matching traceback, critical, startup, schema, or staging-permission failures.

### Notes

Changed files:
- `progress.md`: Recorded the production backup, configuration, schema migration, service health, authenticated Web acceptance, and staging-channel smoke test.

Rollback:
- Stop `tg-downloader.service`, preserve the live schema-3 resource database and configuration, restore `config.yaml` and `resource_bot.sqlite3` from `/root/telegram_media_downloader/backups/release-20260730-042143-staging-pipeline`, return code to commit `70316fc`, and restart. Do not restore the channel or Web-task databases unless independently required.

## 2026-07-30 - Task: Fix Pyrogram album upload stream filename serialization

### What was done

- Diagnosed failed staging job `g2UAjNeNiQxbV3LG`: the first 10-item album downloaded successfully but failed before creating a staging manifest or destination copy.
- Reproduced the production `AttributeError` with two valid small videos and obtained the complete Pyrogram traceback: `_TrackedUploadFile.name` was a `PosixPath`, while Pyrogram's MTProto serializer requires a string and calls `.encode()`.
- Normalized the tracked album stream path to `str` when opening `FileIO`, preserving album upload-speed tracking while making its filename serializable.
- Added a regression test that verifies the tracked stream exposes a string name and can be serialized by Pyrogram's raw `InputFile`.
- Confirmed the first two successful production packages predated commit `80c085d`, which introduced tracked album streams; the later failures therefore match the exact regression window.

### Testing

- RED verification: the new regression test observed `stream.name` as `PosixPath`.
- Resource delivery worker tests -> `17 passed`.
- Resource store, delivery, Bot, lifecycle, command, and application regressions -> `64 passed`.
- Complete suite with isolated `TMD_TASK_DB_PATH` and `TMD_RESOURCE_BOT_DB_PATH` -> `625 passed, 1 skipped`.
- Changed modules compiled, `check_imports.py` passed, and `git diff --check` passed.
- Production diagnostic reproduction produced `AttributeError: 'PosixPath' object has no attribute 'encode'` before any staging message was created.

### Notes

Changed files:
- `module/resource_delivery.py`: Converted the tracked album upload path to a string before opening the file stream.
- `tests/module/test_resource_delivery.py`: Added Pyrogram filename-type and raw-serialization regression coverage.
- `docs/web-control-console.md`: Documented the album speed-tracking compatibility boundary.
- `progress.md`: Recorded diagnosis, regression window, fix, and verification evidence.

Rollback:
- Revert this fix commit and restart the service. No schema, configuration, activation, binding, or delivery-history rollback is required.

## 2026-07-30 - Task: Deploy tracked album upload filename fix

### What was done

- Confirmed there were no active or queued resource deliveries, stopped the service, and created a restricted pre-deploy backup.
- Fast-forwarded production from `66aecdc` to `dd4eb00`, ran import/compile/dependency checks, and restarted the unified service.
- Performed a real Pyrogram acceptance test with two valid small videos using the production resource Bot and staging channel.
- Verified both tracked streams exposed string filenames, Telegram created one two-item media group, and both staging messages were deleted afterward.

### Testing

- Production backup: `/root/telegram_media_downloader/backups/release-20260730-044707-album-stream-fix`.
- Backup database integrity -> channel `ok` schema 0, Web task `ok` schema 1, resource Bot `ok` schema 3.
- Production preflight -> `check_imports.py`, changed-module compilation, and `.venv/bin/pip check` passed.
- Live Telegram acceptance -> stream filename types `str`, album sent `2` messages with `1` media-group ID, album cleanup deleted `2` messages.
- Live database integrity -> channel `ok` schema 0, Web task `ok` schema 1, resource Bot `ok` schema 3.
- Service -> `active/running`, `NRestarts=0`, `ExecMainStatus=0`; recent journal contained no matching traceback, critical, startup, PosixPath, or staging-upload failures.

### Notes

Changed files:
- `progress.md`: Recorded production backup, deployment, and real Telegram album acceptance evidence.

Rollback:
- Stop `tg-downloader.service`, return code to commit `66aecdc`, and restart. The backup at `/root/telegram_media_downloader/backups/release-20260730-044707-album-stream-fix` is available if configuration, sessions, or databases independently require restoration; this code-only fix does not require database rollback.

## 2026-07-30 - Task: Design architecture hardening

### What was done

- Defined the task-count, single-result, side-effect isolation, persistence, thread-ownership, sampled-progress, and reproducible-build invariants for the production downloader.
- Limited the remediation to four independently reviewable phases and explicitly preserved the stable channel-library, outbox, disk-admission, restart-reconciliation, and resource-delivery subsystems.
- Defined the final adversarial-review, production backup, deployment, acceptance, and rollback gates.

### Testing

- Inspected the current clean `master` worktree, recent deployment history, production handoff checklist, task lifecycle, Web state, task store, Rclone adapter, Docker files, dependencies, and runtime declarations.
- Confirmed the design maps each audited defect to an explicit invariant and verification gate.
- Documentation-only change; implementation regressions are deferred to the phase-specific red-green test cycles.

### Notes

Changed files:
- `docs/superpowers/specs/2026-07-30-architecture-hardening-design.md`: Added the approved surgical hardening design, invariants, phase boundaries, verification strategy, and deployment rollback policy.
- `progress.md`: Recorded the design scope and evidence.

Rollback:
- Revert the architecture-hardening design commit; no runtime, schema, configuration, or production state changes are involved.

## 2026-07-30 - Task: Plan architecture hardening implementation

### What was done

- Converted the approved architecture invariants into four ordered implementation phases with explicit red-green tests, verification gates, documentation updates, commit boundaries, final adversarial review, and production deployment steps.
- Bound each audited defect to concrete source/test areas while preventing unrelated rewrites of stable subsystems.
- Defined the production preflight, backup-integrity, fast-forward deployment, live acceptance, and rollback evidence required before completion.

### Testing

- Cross-checked the plan against current task lifecycle, Web route inventory, SQLite stores, Rclone adapter, Docker/Compose files, dependency declarations, CI workflows, and the existing production handoff.
- Confirmed every implementation phase has a focused test set, complete-suite gate, operational checks, `progress.md` entry, and independent commit.
- `git diff --check` is required before committing this documentation phase.

### Notes

Changed files:
- `docs/superpowers/plans/2026-07-30-architecture-hardening.md`: Added the ordered TDD implementation, review, and deployment plan.
- `progress.md`: Recorded the plan scope and verification evidence.

Rollback:
- Revert the architecture-hardening plan commit; no runtime, schema, configuration, or production state changes are involved.

## 2026-07-30 - Task: Enforce task lifecycle invariants and Docker persistence

### What was done

- Replaced the invalid planned-count equality completion check with a terminal-result invariant, so a task cannot finish before every planned file has one success, failure, or skip result.
- Made file-result accounting idempotent by stable chat/message identity, removed the second result mutation from Bot reporting, and isolated reporting/snapshot failures from the transfer outcome.
- Added an environment-overridable channel-library database path and made Docker Compose persist all three SQLite databases plus the Web auth verifier under one host `state/` mount.
- Documented Docker state ownership, existing-installation migration, backup, integrity, and rollback requirements.

### Testing

- RED verification -> `8 failed, 2 passed`: reproduced premature completion, duplicate result counting, reporting-side mutation, notification failure changing a success, missing channel-library path override, and missing Compose state persistence.
- New invariant/runtime/Docker tests after the fix -> `10 passed`.
- Focused task, lifecycle, Bot, package, channel-library, Web upload, path, and Docker regressions -> `235 passed`.
- Complete suite with isolated `TMD_TASK_DB_PATH`, `TMD_RESOURCE_BOT_DB_PATH`, and `TMD_WEB_AUTH_FILE` -> `635 passed, 1 skipped`.
- `check_imports.py`, changed-module/test compilation, `.venv/bin/pip check`, and `git diff --check` passed.
- `docker compose -f docker-compose.yaml config` passed and resolved the four state paths plus `./state:/app/state`; Compose reported only the pre-existing obsolete `version` key warning.

### Notes

Changed files:
- `module/app.py`: Added derived terminal-result completion and idempotent per-file result accounting.
- `module/download_lifecycle.py`, `module/pyrogram_extension.py`: Separated transfer results from reporting/snapshot side effects.
- `module/download_entry.py`: Added the `TMD_CHANNEL_LIBRARY_DB_PATH` resolver.
- `docker-compose.yaml`, `.gitignore`: Added the persistent state mount, explicit runtime paths, and ignored host state directory.
- `tests/module/`, `tests/test_docker_contract.py`: Added correctness, failure-isolation, path, and Compose regressions.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`: Documented state persistence, migration, backup, and integrity requirements.
- `progress.md`: Recorded red-green and full-regression evidence.

Rollback:
- Revert this phase commit. For Docker deployments that have already migrated files into `state/`, stop the container first and either keep the explicit environment/mount contract or move the verified files back to their prior runtime paths before starting older code; never copy a live WAL database.

## 2026-07-30 - Task: Consolidate task state boundaries

### What was done

- Added one atomic task/file lifecycle transition so queue, download, upload, and terminal evidence cannot be half-committed in memory or SQLite.
- Sampled high-frequency download progress off the event loop with time/byte/final thresholds and at most one in-flight write per file.
- Routed Flask-to-async work through one owner-loop command boundary with bounded waits that do not cancel accepted work.
- Locked shared Web preview/prescan state, passed immutable confirmation selections across threads, and made restart-orphaned confirmations fail deterministically with `restart_interrupted`.
- Prevented late download snapshots from regressing uploading, uploaded, or upload-failed file states.

### Testing

- Initial Phase 2 RED verification -> `9 failed`, covering missing atomic transitions, sampled progress, Web command ownership, and restart-orphan confirmation handling.
- Additional concurrency/state RED verification -> `3 failed`, covering concurrent per-file progress writes, upload-state regression, and mutable prescan confirmation state.
- Phase 2 focused task-store, progress, Web command, lifecycle, prescan/cancel, and channel-library regressions -> `161 passed`.
- Natural-order complete suite with isolated task/resource/auth paths -> `646 passed, 1 skipped`; no `Event loop is closed` failures reproduced.
- An earlier complete-suite run with `TMD_CHANNEL_LIBRARY_DB_PATH` forced externally produced one expected default-path contract failure; rerunning without that conflicting override passed completely.
- `check_imports.py`, changed-module/test compilation, `.venv/bin/pip check`, and `git diff --check` passed.
- Task database migration, transaction rollback, and restart recovery tests -> `3 passed`; temporary database verification -> `PRAGMA integrity_check = ok`, schema version `1`.

### Notes

Changed files:
- `module/task_state.py`: Added atomic task/file transitions and protected upload-stage states from late download snapshots.
- `module/progress_persistence.py`: Added sampled, off-loop, single-in-flight download progress persistence.
- `module/web_commands.py`: Added the shared Flask-to-owner-loop command boundary and bounded wait error.
- `module/download_queue.py`, `module/download_lifecycle.py`, `module/download_stat.py`: Routed lifecycle and progress persistence through the consolidated boundaries.
- `module/web.py`: Routed async submissions and waits through the command helper and synchronized process-local Web confirmation state.
- `tests/module/test_task_state.py`, `tests/module/test_progress_persistence.py`, `tests/module/test_web_commands.py`, `tests/module/test_download_lifecycle.py`, `tests/test_web_cancel_task.py`, `tests/test_web_prescan_retention.py`: Added atomicity, rollback, sampling, loop-ownership, immutable-confirmation, restart, and state-regression coverage.
- `docs/web-control-console.md`: Documented atomic lifecycle writes, progress sampling, owner-loop timeouts, immutable confirmation snapshots, and restart behavior.
- `progress.md`: Recorded Phase 2 implementation and verification evidence.

Rollback:
- Revert the Phase 2 commit. No schema version change is introduced; existing `web_tasks.sqlite3` data remains compatible with the prior Phase 1 code.

## 2026-07-30 - Task: Harden Web mutations, Rclone, and builds

### What was done

- Required the authenticated session-bound CSRF token on every Web state-changing route while preserving unauthenticated login.
- Routed every frontend mutation through a shared CSRF-aware fetch helper, including logout, settings, download state, task actions, and prescan selection.
- Removed Rclone shell execution, passed mkdir/copy arguments directly, decided success from exit code, and limited cache/counter/file cleanup changes to successful operations.
- Pinned the Pyrogram fork to immutable commit `51a100c5e2745471ee89c1dd96dd69962973108b` with SHA-256 verification.
- Made the runtime image consume only its local compile stage, excluded runtime secrets/state from the Docker context, and simplified Docker publishing to one checkout-based runtime build.

### Testing

- Initial Phase 3 contract run -> `10 failed, 3 passed`, reproducing incomplete CSRF coverage, direct mutating frontend fetches, Rclone shell/exit-code defects, remote mutable compile-image use, missing build-context exclusions, and the mutable Pyrogram branch.
- Phase 3 focused Web, channel-library, CSRF, Rclone, Docker, and dependency regressions -> `179 passed`.
- Natural-order complete suite with isolated task/resource/auth paths -> `658 passed, 1 skipped`.
- Immutable Pyrogram archive download succeeded and matched SHA-256 `30e55236a741deec461a952fec638e2857e4cf7bb2d8c6616d41fd2e4e0685ca`.
- Fresh dependency wheel resolution from `requirements.txt` succeeded, including building the pinned Pyrogram wheel.
- `docker compose -f docker-compose.yaml config` passed; it emitted only the existing obsolete top-level `version` warning.
- Local Docker image build was not run because Docker CLI could not connect to the configured Colima daemon socket; this remains an environment verification gap, not a claimed pass.
- Workflow/Compose YAML parsing, `check_imports.py`, changed-module/test compilation, `.venv/bin/pip check`, focused Black checks, and `git diff --check` passed.

### Notes

Changed files:
- `module/web.py`, `module/templates/index.html`: Unified authenticated mutation CSRF enforcement and frontend token attachment.
- `module/cloud_drive.py`: Replaced shell execution with argument arrays and return-code-based Rclone lifecycle handling.
- `requirements.txt`: Pinned the Pyrogram fork to an immutable archive and checksum.
- `Dockerfile`, `.dockerignore`, `.github/workflows/docker-publish.yml`: Made the runtime build local-stage, context-bounded, and checkout-reproducible.
- `tests/test_web_csrf_contract.py`, `tests/module/test_cloud_drive.py`, `tests/test_dependency_contract.py`, `tests/test_docker_contract.py`: Added Web security, command execution, immutable dependency, and Docker build contracts.
- `tests/module/test_web.py`, `tests/module/test_channel_library_web.py`, `tests/test_web_cancel_task.py`, `tests/test_web_clear_download_list.py`, `tests/test_web_prescan_retention.py`, `tests/test_web_upload_progress.py`: Updated mutation and Rclone regressions for the hardened contracts.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`: Documented runtime-mounted configuration, CSRF coverage, immutable build inputs, and return-code-based Rclone behavior.
- `progress.md`: Recorded Phase 3 implementation, verification, and the unavailable Docker daemon gap.

Rollback:
- Revert the Phase 3 commit. The change introduces no database schema migration; restore the prior image/workflow and requirements file together so the remote compile-image and mutable dependency behavior are not mixed with the new runtime Dockerfile.

## 2026-07-30 - Task: Align runtime and module boundaries

### What was done

- Protected the process-local active-task registry with a re-entrant lock and made every reader receive a shallow container snapshot instead of the live mutable dictionary.
- Unified package metadata, CI, local commands, documentation, and development tools on the production Python 3.11 runtime.
- Upgraded and isolated the formatting, type-checking, lint, test, and pre-commit toolchain, with a blocking static-analysis boundary around the architecture-hardened task, lifecycle, progress, admission, Rclone, Telegram-activity, and Web-command modules.
- Removed obsolete Pylint configuration values and made test cleanup use the public active-task lifecycle API instead of mutating registry internals.

### Testing

- Initial Phase 4 RED verification -> `5 failed`, covering the live registry container and inconsistent package, CI, Makefile, documentation, dependency, and pre-commit runtime declarations.
- Pinned development dependencies installed successfully under Python `3.11.15`.
- Upgraded full-source mypy scan ran and reported `330` pre-existing errors across generated parser data, implicit Optional annotations, dynamic Pyrogram APIs, and legacy store/Web modules; these were recorded as historical debt rather than suppressed or expanded into an unrelated refactor.
- Blocking static boundary -> mypy `Success: no issues found in 9 source files`; Pylint error-only check passed without the obsolete-config warnings.
- Focused runtime, registry, task-state, lifecycle, progress, Web-command, Rclone, activity, and admission regressions -> `49 passed`; final runtime/registry contract rerun -> `5 passed`.
- Natural-order complete suite with isolated task/resource/auth paths -> `664 passed, 1 skipped`.
- All six isolated pre-commit hooks passed: trailing whitespace, end-of-file, Black, isort, mypy, and Pylint.
- `check_imports.py`, changed-module/test compilation, `.venv/bin/python -m pip check`, `make style_check`, `docker compose -f docker-compose.yaml config`, and `git diff --check` passed. Compose emitted only the existing obsolete top-level `version` warning.

### Notes

Changed files:
- `module/download_stat.py`: Locked active-task registry mutations and returned shallow snapshots to readers.
- `module/task_state.py`, `module/cloud_drive.py`, `module/web_commands.py`: Narrowed current-scope types without changing persisted schemas or public behavior.
- `setup.py`, `Makefile`, `dev-requirements.txt`, `pylintrc`: Declared Python 3.11 and aligned install, test, type, lint, and tool versions.
- `.github/workflows/unittest.yml`, `.github/workflows/code-checks.yml`, `.pre-commit-config.yaml`: Aligned CI actions, Python, isolated hooks, and the blocking static-analysis boundary.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`: Documented the Python 3.11 and active-task ownership contracts.
- `tests/test_runtime_contract.py`, `tests/module/test_task_state.py`: Added runtime/toolchain and registry snapshot contracts.
- `tests/test_media_downloader.py`, `tests/test_channel_library_download.py`, `tests/test_channel_library_e2e.py`: Replaced direct registry-container cleanup with the public removal API.
- `progress.md`: Recorded Phase 4 red-green, static-analysis scope, regression, and operational evidence.

Rollback:
- Revert the Phase 4 commit. No database schema, persisted task data, production configuration, or runtime state migration is introduced; revert the metadata, CI, toolchain, registry boundary, tests, and documentation together.

## 2026-07-30 - Task: Design and plan architecture hardening follow-up

### What was done

- Converted the final adversarial findings and first-principles audit into explicit transfer-progress, command-acceptance, runtime-ownership, failure-classification, import-safety, configuration, authentication, adapter, shutdown, static-analysis, container, and deployment invariants.
- Selected a surgical single-process ownership consolidation instead of an ASGI rewrite or multi-process service split, preserving the mature channel-library saga, disk admission, resource staging, database schemas, public commands, and Web payloads.
- Defined four ordered implementation phases with red-green tests, full-suite gates, independent commits, a complete adversarial review, production backup, fast-forward deployment, acceptance, and rollback requirements.

### Testing

- Cross-checked the follow-up scope against the current clean `49af7c8` worktree, the original hardening design/plan, the independent review findings, transfer progress/watchdog data flow, Web cancellation and settings paths, task-store initialization, Web auth, Aligo execution, application shutdown, CI/static boundaries, Docker inputs, and current production preflight evidence.
- Confirmed each confirmed defect is assigned to one implementation phase and every phase includes focused tests, full regression, operational checks, documentation, progress logging, and one commit boundary.
- `rg -n "TBD|TODO|待定|implement later|Similar to" <follow-up-design> <follow-up-plan>`: no placeholders found.
- `git diff --check` and `git diff --no-index --check /dev/null <new-document>`: passed for the tracked update and both new Markdown files.
- `.venv/bin/python` documentation contract check: passed; both documents contain Phases 5-8, the complete adversarial-review gate, the production-deployment gate, and all four independent phase commit boundaries.

### Notes

Changed files:
- `docs/superpowers/specs/2026-07-30-architecture-hardening-follow-up-design.md`: Added the follow-up design, alternatives, ownership invariants, phase boundaries, verification policy, and deployment/rollback contract.
- `docs/superpowers/plans/2026-07-30-architecture-hardening-follow-up.md`: Added the ordered TDD implementation, full adversarial review, and production deployment plan.
- `progress.md`: Recorded the approved follow-up design and implementation-plan scope.

Rollback:
- Revert the follow-up documentation commit. No runtime code, database schema, configuration, dependency, service, or production state is changed.

## 2026-07-30 - Task: Phase 5 runtime correctness and command ownership

### What was done

- Replaced split message-ID-only stall state with one transfer-progress tracker keyed by task, chat, and message; the Pyrogram progress callback and watchdog now share the same tracker, and only increasing byte counts refresh the heartbeat.
- Rejected Web commands when the application loop is missing, closed, or stopped, closing rejected coroutines instead of returning a future for work that cannot execute.
- Routed live Web `TaskNode` cancellation and process-local Web registry cleanup through the application owner loop while preserving the existing channel-library cancellation path and task response contract.
- Reclassified unexpected Telegram message-refetch failures as failed downloads without incrementing not-found skip accounting, while retaining explicit skip behavior for the installed Pyrogram version's supported inaccessible-message exceptions.

### Testing

- RED: `.venv/bin/python -m pytest -q tests/module/test_transfer_progress.py` failed at collection with `ModuleNotFoundError: module.transfer_progress`.
- RED: `.venv/bin/python -m pytest -q tests/module/test_web_commands.py::test_submit_rejects_open_but_stopped_loop` failed because no `RuntimeError` was raised and a pending task was left on the stopped loop.
- RED: `.venv/bin/python -m pytest -q tests/test_web_cancel_task.py::test_cancel_active_web_task_mutates_node_on_owner_loop` failed with different request-thread and owner-thread identifiers.
- RED: `.venv/bin/python -m pytest -q tests/module/test_package_download.py::test_unexpected_refetch_error_is_failed_not_skipped` exposed both the skip misclassification and the installed Pyrogram version's missing generic `errors.NotFound` attribute.
- `.venv/bin/python -m pytest -q tests/module/test_transfer_progress.py tests/module/test_web_commands.py tests/test_web_cancel_task.py tests/test_web_prescan_retention.py tests/module/test_download_lifecycle.py tests/module/test_package_download.py tests/module/test_web.py tests/test_media_downloader.py`: `97 passed`.
- `.venv/bin/python -m pytest -q`: `671 passed, 1 skipped`.
- `.venv/bin/python check_imports.py`: both supported import probes passed.
- `.venv/bin/python -m compileall -q module tests`: passed.
- `.venv/bin/python -m pip check`: no broken requirements.
- `make style_check PYTHON=.venv/bin/python`: blocking mypy and Pylint checks passed.
- `.venv/bin/python -m mypy module/transfer_progress.py --ignore-missing-imports --follow-imports=silent`: passed.
- `.venv/bin/python -m pylint module/transfer_progress.py module/download_transfer.py -rn -sn --errors-only --rcfile=pylintrc`: passed.
- Expanded non-blocking mypy probe of `module/download_transfer.py` still reports its pre-existing optional FloodWait conversion warning at line 138; the planned Phase 8 touched-module static-boundary work owns that cleanup.
- `git diff --check`: passed.

### Notes

Changed files:
- `module/transfer_progress.py`, `module/download_stat.py`, `module/download_transfer.py`, `module/download_entry.py`: Added the shared transfer identity/tracker, integrated callback/watchdog state, and corrected refetch classification.
- `module/web_commands.py`, `module/web.py`: Enforced running-loop command admission and owner-loop live-task cancellation.
- `tests/module/test_transfer_progress.py`, `tests/module/test_web_commands.py`, `tests/module/test_package_download.py`, `tests/module/test_web.py`, `tests/test_web_cancel_task.py`, `tests/test_web_prescan_retention.py`: Added and adapted regression coverage for the repaired ownership and failure contracts.
- `docs/web-control-console.md`, `docs/superpowers/plans/2026-07-30-architecture-hardening-follow-up.md`: Documented the runtime behavior and marked Phase 5 complete.
- `progress.md`: Recorded Phase 5 red-green and verification evidence.

Rollback:
- Revert the Phase 5 commit. No database schema, persisted task migration, configuration, dependency, service, or production state change is introduced.

## 2026-07-30 - Task: Phase 6 persistent state and configuration ownership

### What was done

- Removed task-database creation, recovery, pruning, and loading from module import; the application lifecycle now initializes the process store after `pre_run` and before Web, channel, Bot, or worker startup, while tests install an explicit in-memory store.
- Made task readers return deep-copy snapshots, added a command-only workflow update, and removed Web mutations of returned workflow objects so callers cannot bypass the store lock or race dashboard serialization.
- Hardened `web_tasks.sqlite3` with explicit five-second connections, `busy_timeout=5000`, WAL, and POSIX mode `0600` before schema work.
- Added locked atomic YAML persistence using owner-only same-directory temporary files, flush, file `fsync`, `os.replace`, and directory `fsync`; configuration serialization failures leave the previous file intact.
- Split Web settings into active and configured values. Hot-safe fields apply on the owner loop; `save_path`, worker count, Telegram concurrency, startup timeout, Web binding/enablement, and upload-adapter replacement persist for restart without mutating live dependencies. The API and UI expose exact pending-restart fields.

### Testing

- RED: the subprocess import regression found `web_tasks.sqlite3` created by `import module.task_state`.
- RED: caller mutation changed the stored workflow count from `1` to `99`, and a concurrent file update changed an in-progress serialization from one file to two.
- RED: an existing task database remained mode `0644` instead of `0600`.
- RED: config-persistence tests failed at collection because `module.config_persistence` did not exist.
- RED: Web settings reported only coarse restart fields, changed live restart-only objects, and executed `Application.update_config()` on the Flask request thread instead of the owner loop.
- `.venv/bin/python -m pytest -q tests/module/test_task_state.py tests/module/test_config_persistence.py tests/module/test_app.py tests/module/test_web.py tests/module/test_channel_library_web.py tests/test_web_prescan_retention.py tests/test_runtime_contract.py tests/module/test_bot_manager.py`: `200 passed`.
- First full-suite run exposed one obsolete object-identity assertion for `get_task()`; it was changed to require an equal but independent snapshot.
- `.venv/bin/python -m pytest -q`: `680 passed, 1 skipped`.
- `TMD_TASK_DB_PATH=<temporary>/import.sqlite3 .venv/bin/python check_imports.py` followed by an absence check: both imports passed and no task database was created.
- `.venv/bin/python -m compileall -q module tests`: passed.
- `.venv/bin/python -m pip check`: no broken requirements.
- `make style_check PYTHON=.venv/bin/python`: blocking mypy and Pylint checks passed.
- `.venv/bin/python -m mypy module/config_persistence.py module/task_state.py module/download_runtime.py --ignore-missing-imports --follow-imports=silent`: passed.
- `.venv/bin/python -m pylint module/config_persistence.py module/task_state.py module/download_runtime.py -rn -sn --errors-only --rcfile=pylintrc`: passed.
- Temporary task-database contract probe: `PRAGMA integrity_check=ok`, `journal_mode=wal`, `busy_timeout=5000`, and POSIX mode `0600`.
- `git diff --check`: passed.

### Notes

Changed files:
- `module/task_state.py`, `module/download_runtime.py`, `module/download_entry.py`, `tests/conftest.py`: Added explicit store ownership, immutable reads, workflow commands, connection hardening, lifecycle wiring, and isolated test installation.
- `module/config_persistence.py`, `module/app.py`: Added locked, atomic, owner-only YAML persistence and preserved configured restart values across later shutdown writes.
- `module/web.py`, `module/templates/index.html`: Added owner-loop settings application, active/configured responses, exact restart fields, and pending-restart UI feedback.
- `tests/module/test_task_state.py`, `tests/module/test_config_persistence.py`, `tests/module/test_app.py`, `tests/module/test_web.py`, `tests/module/test_bot_manager.py`, `tests/test_channel_library_download.py`: Added red-green ownership, concurrency, persistence, lifecycle, and compatibility regressions.
- `docs/web-control-console.md`, `docs/superpowers/plans/2026-07-30-architecture-hardening-follow-up.md`: Documented and marked the Phase 6 contracts complete.
- `progress.md`: Recorded Phase 6 implementation and verification evidence.

Rollback:
- Revert the Phase 6 commit. The task database schema remains version 1 and no persisted row migration is introduced; rollback restores import-time initialization and the prior Web settings behavior, so stop the service before rollback and preserve current configuration files.

## 2026-07-30 - Task: Phase 7 authentication, adapter, and shutdown lifecycle

### What was done

- Replaced reusable Web password plaintext with a Werkzeug verifier, migrated existing plaintext auth files without changing the accepted credential, retained generated bootstrap plaintext only until first successful login, and enforced atomic owner-only auth-file persistence.
- Added bounded per-client login failures, a twelve-hour non-sliding permanent session, an explicit secure-cookie setting, and a one-MiB request-body limit while preserving generic login failure responses.
- Corrected Aligo execution so the application executor receives a callable, the generic async adapter offloads blocking work, and selecting Aligo without its optional package fails startup with an actionable configuration error.
- Replaced unmanaged Flask threads with an owned Werkzeug server whose bind failure is observable and whose stop path shuts down and joins the non-daemon thread.
- Unified SIGINT and SIGTERM on one shutdown request; stopped Web, channel, Bot, and Telegram services in order; cancelled and awaited tracked and residual owner-loop tasks; isolated configuration-flush failures; and shut down the executor and event loop exactly once.
- Updated English, Chinese, and operations documentation for credential migration/recovery/rollback, HTTPS cookies, optional Aligo installation, restart-only adapter activation, and process shutdown.

### Testing

- RED Web auth/login tests: plaintext migration, bootstrap removal, configured-secret non-persistence, file mode, rate-limit threshold/expiry/reset, permanent session, secure cookie, and request limit initially failed against the plaintext in-memory login implementation; focused green runs reached `6 passed, 31 deselected` and then `10 passed, 31 deselected`.
- RED Aligo: `.venv/bin/python -m pytest tests/module/test_app.py::test_aligo_upload_passes_callable_to_application_executor tests/module/test_cloud_drive.py::test_async_aligo_upload_runs_blocking_adapter_in_thread tests/module/test_cloud_drive.py::test_aligo_missing_optional_dependency_has_clear_startup_error -q` reproduced the boolean-as-callable and raw missing-module failures (`2 failed, 1 passed`); the tightened thread-offload assertion separately failed (`1 failed`); green rerun: `3 passed`.
- RED Web server: `.venv/bin/python -m pytest tests/module/test_web_server.py -q` failed collection with `ModuleNotFoundError: module.web_server`; green rerun: `4 passed`.
- RED shutdown: executor/loop ownership, worker finalizers, shared SIGTERM/SIGINT, and Web-before-loop tests failed (`4 failed`); green rerun: `5 passed`. A separate config-flush failure regression failed because cleanup aborted before resource close, then passed after cleanup stages were isolated.
- Phase-focused Web auth, Web routes, CloudDrive, Web server, Application, Bot, and channel-library tests: `180 passed`; final security-contract selection: `77 passed`.
- The first full-suite run exposed test-fixture reuse of the now-correctly closed global loop plus two CSRF tests coupled to the removed plaintext map (`11 failed, 689 passed, 1 skipped`). Test isolation and verifier injection were repaired; final complete suite: `700 passed, 1 skipped`.
- `TMD_TASK_DB_PATH=<temporary>/import.sqlite3 .venv/bin/python check_imports.py`: both supported import probes passed and no task database was created.
- `.venv/bin/python -m compileall -q module tests` and `.venv/bin/python -m pip check`: passed with no broken requirements.
- `make style_check PYTHON=.venv/bin/python`: existing blocking mypy/Pylint boundary passed.
- Expanded stable boundary covering CloudDrive, config persistence, download runtime, transfer progress, Web auth, and Web server: mypy `Success: no issues found in 6 source files`; Pylint error-only passed.
- A non-blocking full touched-file mypy probe reported `66` historical dynamic/implicit-Optional errors only in `module/app.py`, `module/web.py`, and `module/download_entry.py`; Pylint likewise reported the existing dynamic `media_downloader` export inference errors in Web code. These were recorded rather than suppressed or expanded into unrelated legacy refactoring; Phase 8 owns the bounded enforceable boundary.
- Black/isort checks passed for the new and fully rewritten modules, and `git diff --check` passed.

### Notes

Changed files:
- `module/web_auth.py`, `module/web.py`, `config.example.yaml`: Added verifier/bootstrap persistence, login limiting, bounded sessions, secure-cookie configuration, and verifier-based login.
- `module/cloud_drive.py`, `module/app.py`: Added explicit optional-Aligo validation, callable executor submission, async thread offload, and idempotent runtime-resource ownership.
- `module/web_server.py`, `module/download_runtime.py`, `module/download_entry.py`: Added the owned Werkzeug listener, shared signal request, awaited task drainage, resilient cleanup, and one-time executor/loop closure.
- `tests/module/test_web_auth.py`, `tests/module/test_web.py`, `tests/module/test_cloud_drive.py`, `tests/module/test_web_server.py`, `tests/module/test_app.py`, `tests/module/test_bot_manager.py`, `tests/test_media_downloader.py`, `tests/test_web_csrf_contract.py`: Added authentication, adapter, server, signal, shutdown, finalizer, cleanup-failure, test-isolation, and CSRF compatibility regressions.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`, `docs/superpowers/plans/2026-07-30-architecture-hardening-follow-up.md`: Documented the Phase 7 operational contracts and marked the phase complete.
- `progress.md`: Recorded Phase 7 red-green, regression, static-boundary, and rollback evidence.

Rollback:
- Revert the Phase 7 commit. No database schema or persisted task migration is introduced. If the new authentication code has already migrated a real auth file, stop the service, preserve that file as evidence, set an explicit `web_login_secret`, and then roll back because older code cannot authenticate from the password-hash field alone.

## 2026-07-30 - Task: Phase 8 bounded module, static, and container cleanup

### What was done

- Expanded the blocking mypy/Pylint boundary from nine to fifteen stable modules, adding configuration persistence, download runtime/transfer, transfer progress, Web authentication, and owned Web serving without pulling legacy dynamic application files into the gate.
- Added a public minimal `GET /healthz` readiness endpoint while preserving authentication on operational metrics, and wired matching Dockerfile and Compose health checks.
- Pinned the Python 3.11.9 Alpine multi-architecture base to reviewed digest `sha256:f9ce6fe33d9a5499e35c976df16d24ae80f6ef0a28be5433140236c2ca482686`; pinned GCC, musl development headers, and Rclone package versions; and verified active Python requirements are exact-version or SHA-256 pinned.
- Added a default UID/GID 10001 non-root runtime user plus Compose `TMD_UID`/`TMD_GID` overrides. Moved Docker configuration/data paths into the whole `state/` directory mount so atomic YAML replacement remains valid, changed Rclone configuration to a project-local mount, and excluded that credential directory from the build context.
- Documented first-install and stopped-service migration steps, ownership changes, health prerequisites, backup requirements, and rollback boundaries in English, Chinese, and operations guidance.

### Testing

- RED static boundary: `tests/test_runtime_contract.py::test_architecture_hardening_modules_are_in_blocking_static_boundary` failed because the new modules were absent from Makefile/hooks; the expanded mypy probe also exposed one real optional FloodWait conversion error in `module/download_transfer.py`. Green: contract `1 passed`; `make style_check` passed with mypy `Success: no issues found in 15 source files` and Pylint error-only clean.
- RED health: public health and Docker health contracts produced `2 failed, 1 passed` because `/healthz` and container checks did not exist. Green rerun: `3 passed`; the operational `/api/system` route remained login-protected.
- RED container inputs/migration: pinned-base, non-root/mount, and runtime config-path contracts produced `3 failed, 1 passed`. Green rerun: `4 passed`. The new project-local Rclone credential directory separately failed the build-context exclusion test, then passed after adding `rclone/` to `.dockerignore`.
- Docker/runtime/dependency/health contract groups passed at `18 passed`, then `23 passed`; the final focused container, dependency, runtime, health, CSRF, Web server, and Web auth selection passed `33 passed`.
- Registry verification confirmed the reviewed base digest exposes `linux/386`, `linux/amd64`, `linux/arm/v6`, `linux/arm/v7`, `linux/arm64/v8`, and `linux/ppc64le`, matching the publishing workflow. Alpine 3.20 indexes confirmed `gcc=13.2.1_git20240309-r1`, `musl-dev=1.2.5-r3`, and `rclone=1.66.0-r5` for all six target architectures.
- `TMD_UID=10001 TMD_GID=10001 docker compose -f docker-compose.yaml config`: passed and resolved the expected non-root user, state paths, health command, and directory mounts.
- First all-files pre-commit run changed only Black formatting in `tests/test_web_system_api.py`; the second run passed trailing whitespace, end-of-file, Black, isort, mypy, and Pylint.
- `TMD_TASK_DB_PATH=<temporary>/import.sqlite3 .venv/bin/python check_imports.py`: both import probes passed and created no task database.
- `.venv/bin/python -m compileall -q module tests`, `.venv/bin/python -m pip check`, `make style_check PYTHON=.venv/bin/python`, and `git diff --check`: passed.
- Complete suite: `708 passed, 1 skipped`.
- Image build was attempted with `docker build --target runtime-image -t telegram-media-downloader:phase8-check .` and was blocked before build by the unavailable Colima Docker socket. No image or smoke-test success is claimed; a successful CI multi-platform build is required before production deployment.

### Notes

Changed files:
- `Makefile`, `.pre-commit-config.yaml`, `module/download_transfer.py`, `tests/test_runtime_contract.py`: Expanded the enforceable static boundary and corrected the one current-scope type error.
- `module/web.py`, `Dockerfile`, `docker-compose.yaml`, `tests/test_web_system_api.py`, `tests/test_docker_contract.py`: Added minimal readiness, container health, immutable inputs, non-root execution, and writable mount contracts.
- `module/download_entry.py`, `.dockerignore`, `tests/test_dependency_contract.py`: Added environment-selectable config/data paths, protected project-local Rclone credentials, and enforced pinned Python requirements.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`, `docs/superpowers/plans/2026-07-30-architecture-hardening-follow-up.md`: Documented the non-root directory migration, health prerequisite, immutable inputs, static boundary, and Phase 8 completion.
- `progress.md`: Recorded Phase 8 red-green, architecture/package verification, Docker environment gap, and rollback evidence.

Rollback:
- Revert the Phase 8 commit. No database schema or row migration is introduced. If the container migration has been applied, stop the container, retain the migrated `state/` directory and database backups, restore the pre-migration Compose file and directory snapshot, and restore the prior ownership before starting the old image.

## 2026-07-30 - Task: First-principles remediation implementation plan

### What was done

- Converted the first-principles audit findings into seven independently testable and reversible implementation phases covering runtime state ownership, truthful readiness, verified artifact publication, durable state contracts, bootstrap boundaries, final adversarial review, and backed-up production deployment.
- Defined exact success criteria, required regression style, commit boundaries, verification gates, production preflight requirements, backup contents, fast-forward-only deployment, and rollback evidence.
- Preserved the current single-process application and bounded SQLite architecture; the plan explicitly rejects an unrelated framework, distributed-queue, or database rewrite.

### Testing

- Reviewed the plan against the current `HEAD` `24e71e3`, the two architecture-hardening specifications, the complete first-principles audit findings, and the repository-level execution constraints.
- Confirmed the worktree was clean before this documentation change.
- `git diff --check`: passed after the plan and progress entry were added.

### Notes

Changed files:
- `docs/superpowers/plans/2026-07-30-first-principles-remediation.md`: Added the phased repair, adversarial-review, and deployment plan.
- `progress.md`: Recorded the Phase 0 planning deliverable and verification evidence.

Rollback:
- Revert the Phase 0 planning commit. This phase changes documentation only and does not alter runtime, configuration, databases, dependencies, CI execution, or production state.

## 2026-07-30 - Task: Phase 1 runtime state identity and owner-loop control

### What was done

- Replaced the shared mutable download-result dictionary with a synchronized store that records, snapshots, clears, and removes entries by `(task_id, chat_id, message_id)`.
- Migrated retry cleanup, file-lifecycle cleanup, queue timing, performance timing, Bot reporting, and Web file-list rendering to the complete transfer identity so one task cannot overwrite or remove another task processing the same Telegram message.
- Routed Web pause/resume mutations through the application owner loop with bounded `503` failure behavior when the loop is unavailable or does not answer in time.
- Changed cancellation of a persisted active task with no live runtime handle to return `409 runtime_handle_missing` without changing durable task state.
- Documented the live-transfer identity, owner-loop mutation, and cancellation-conflict contracts.

### Testing

- RED: the new runtime-state regression module initially failed collection because `DownloadResultStore` did not exist; the cancellation regression also captured the prior false-success path for an active persisted task with no runtime handle.
- Focused Phase 1 regressions and directly affected lifecycle/package tests: `13 passed`.
- Expanded Web, cancellation, CSRF, admission, download lifecycle, package, prescan, system, and upload-progress selection: `119 passed`.
- One attempted expanded command named a nonexistent `tests/module/test_download_queue.py` and exited before test execution; the corrected selection above used the repository's actual test inventory.
- Complete suite after implementation and again after Black formatting: `714 passed, 1 skipped`.
- `.venv/bin/pre-commit run --all-files`: first run reformatted only `module/download_stat.py`; second run passed trailing-whitespace, end-of-file, Black, isort, mypy, and Pylint hooks.
- `TMD_TASK_DB_PATH=<temporary>/import.sqlite3 .venv/bin/python check_imports.py`: both supported import probes passed and no task database was created.
- `.venv/bin/python -m compileall -q module tests`, `.venv/bin/python -m pip check`, `make style_check PYTHON=.venv/bin/python`, and `git diff --check`: passed; the blocking static boundary reported no mypy issues across 15 modules and no Pylint errors.

### Notes

Changed files:
- `module/download_stat.py`, `module/download_transfer.py`, `module/download_lifecycle.py`, `module/download_queue.py`, `module/download_entry.py`, `module/pyrogram_extension.py`: Added synchronized transfer snapshots/commands and propagated the three-part identity through progress, timing, reporting, retry, and cleanup paths.
- `module/web.py`: Applied pause/resume on the owner loop, rendered the new transfer snapshot shape, and refused false-success cancellation without a runtime handle.
- `tests/module/test_download_runtime_state.py`, `tests/module/test_download_lifecycle.py`, `tests/module/test_package_download.py`, `tests/module/test_web.py`, `tests/test_web_cancel_task.py`, `tests/test_web_clear_download_list.py`: Added isolation, ownership-thread, cancellation, snapshot, timing, and cache-clear regressions and migrated fixtures away from mutable internals.
- `docs/web-control-console.md`: Documented the Phase 1 identity, owner-loop, Web response, and cancellation contracts.
- `progress.md`: Recorded Phase 1 red-green, full-suite, static, import, and rollback evidence.

Rollback:
- Revert the Phase 1 commit. No database schema, persisted row, configuration format, deployment path, or authentication contract changes; rollback restores the prior in-process dictionary identity and Web mutation behavior.

## 2026-07-30 - Task: Phase 2 truthful startup, readiness, and container health

### What was done

- Added an explicit process lifecycle state with `starting`, `ready`, `stopping`, and `failed` phases; readiness is published only after Telegram, the required channel service, configured Bots, and worker tasks have started.
- Made public Web readiness return `503 not_ready` before startup completion and after shutdown begins, while retaining the minimal authenticated-data-free `200 {"status":"ok"}` response only for a ready process.
- Replaced the Web-port-dependent Docker probe with an atomic runtime-health marker carrying the process ID and Linux process-start token, so container health works when `enable_web=false` and rejects stale markers after process replacement.
- Stopped swallowing fatal startup failures: Telegram, required service, and other runtime startup errors now remain `failed`, complete cleanup, propagate through `main`, and produce a non-zero process exit; invalid CLI configuration also exits non-zero.
- Changed channel-library initialization failure from an optional `None` result into a fatal startup error and attempts partial-service cleanup before propagation.
- Expanded the blocking static boundary to include the new runtime-health module and documented the new readiness and container contracts in English, Chinese, and operations guidance.

### Testing

- RED: the Phase 2 focused selection initially failed collection with `ModuleNotFoundError: module.runtime_health`; the pre-existing runtime also swallowed service/startup errors, always returned Web health `200`, and Docker contracts still required the Web listener.
- Focused startup/readiness/container regressions: `10 passed`.
- Expanded runtime, Bot, channel-library, CLI, Web, Docker, and static-contract selection: `225 passed`.
- Live probe smoke test: a separate ready process produced health exit `0`; after that process exited, the unchanged marker produced exit `1`.
- `TMD_UID=10001 TMD_GID=10001 docker compose -f docker-compose.yaml config`: passed with the runtime-health environment path and `python -m module.runtime_health` probe while retaining all expected non-root mounts.
- The first complete-suite run found one over-broad new test assertion that confused the valid shutdown configuration-success log with the forbidden startup-success log (`1 failed, 718 passed, 1 skipped`); the assertion was narrowed to the exact startup message.
- Final complete suite: `719 passed, 1 skipped`.
- `.venv/bin/pre-commit run --all-files`: passed trailing-whitespace, end-of-file, Black, isort, mypy, and Pylint hooks.
- `TMD_TASK_DB_PATH=<temporary>/import.sqlite3 .venv/bin/python check_imports.py`: both supported import probes passed and no task database was created.
- `.venv/bin/python -m compileall -q module tests`, `.venv/bin/python -m pip check`, `make style_check PYTHON=.venv/bin/python`, and `git diff --check`: passed; the blocking static boundary reported no mypy issues across 16 modules and no Pylint errors.
- A supplemental whole-file Black check reported historical formatting drift in six touched legacy files that are intentionally outside the current Black boundary; no broad formatting rewrite was applied. The new runtime-health module and files inside the enforced formatting boundary passed.

### Notes

Changed files:
- `module/runtime_health.py`, `module/app.py`, `module/download_runtime.py`: Added lifecycle state ownership, optional atomic marker persistence, stale-process rejection, truthful ready/stopping/failed transitions, and fatal startup propagation.
- `module/download_entry.py`, `media_downloader.py`: Made required channel-service initialization and invalid configuration terminate startup instead of returning false success.
- `module/web.py`, `Dockerfile`, `docker-compose.yaml`: Made Web readiness state-aware and container health independent of the optional Web listener.
- `Makefile`, `.pre-commit-config.yaml`, `tests/test_runtime_contract.py`: Added runtime health to the blocking mypy/Pylint and formatting contract.
- `tests/module/test_runtime_health.py`, `tests/module/test_bot_manager.py`, `tests/module/test_channel_library_web.py`, `tests/test_media_downloader.py`, `tests/test_web_system_api.py`, `tests/test_docker_contract.py`: Added lifecycle transition, partial-startup, fatal-failure, CLI exit, Web readiness, channel cleanup, and no-Web container regressions.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`: Documented readiness status codes, the atomic marker, the new environment path, and `enable_web=false` container health.
- `progress.md`: Recorded Phase 2 red-green, live probe, full-suite, static, import, container, and rollback evidence.

Rollback:
- Revert the Phase 2 commit. No database schema or persisted task/configuration format changes are introduced. If rolling back a container deployment, remove the now-unused `TMD_RUNTIME_HEALTH_PATH` setting and restore the prior Web-based health check only if `enable_web=true`; otherwise the older image has no valid container health probe.

## 2026-07-30 - Task: Phase 3 verified artifact publication and packaging contract

### What was done

- Added a release-source verification Job to the Docker publication workflow and made the multi-platform push depend on it in the same GitHub Actions dependency graph.
- Required the release gate to run the complete pytest suite, side-effect-free import probes, compileall, `pip check`, the blocking static boundary, all pre-commit hooks, and Docker Compose rendering before registry login/build/push becomes reachable.
- Replaced unconditional `latest`/ref-name tags with Docker metadata that always publishes a long commit-addressable `sha-<40-character-git-sha>` tag, preserves explicit release tags, and emits `latest` only for a verified default-branch event.
- Replaced the incomplete single-module distutils wheel with a setuptools package containing the CLI facade, all `module` and `utils` Python packages, and the Flask templates/static assets required at runtime.
- Added an exact pinned wheel build dependency and documented the release gate, image traceability, promotion rule, and wheel contents.

### Testing

- RED: `.venv/bin/python -m pytest -q tests/test_release_contract.py` produced `3 failed`: the workflow had no `verify` Job, no Docker metadata step, and the built wheel omitted every runtime package and Web asset.
- Focused release, Docker, and development-tool contract selection after implementation: `5 passed`; final release/Docker/runtime-contract selection: `11 passed`.
- The wheel regression builds a real wheel in an isolated temporary source copy and verifies `media_downloader.py`, representative `module`/`utils` modules, both Web templates, and all current static asset directories are present.
- Complete suite: `722 passed, 1 skipped`.
- `.venv/bin/pre-commit run --all-files`: passed trailing-whitespace, end-of-file, Black, isort, mypy, and Pylint hooks after adding the release workflow and packaging test to the enforced file boundary.
- `TMD_TASK_DB_PATH=<temporary>/import.sqlite3 .venv/bin/python check_imports.py`: both supported import probes passed and no task database was created.
- `.venv/bin/python -m compileall -q module tests`, `.venv/bin/python -m pip check`, `make style_check PYTHON=.venv/bin/python`, `TMD_UID=10001 TMD_GID=10001 docker compose -f docker-compose.yaml config`, and `git diff --check`: passed.
- No registry push or multi-platform remote build was performed in this phase. The final pre-deployment gate still requires the committed workflow to complete successfully for the reviewed commit before production deployment.

### Notes

Changed files:
- `.github/workflows/docker-publish.yml`: Added the in-graph release verification Job, publish dependency, long-SHA/release/default-branch metadata tags, and a single verified multi-platform runtime-image push.
- `setup.py`, `dev-requirements.txt`: Packaged the runtime Python namespaces and Web assets with setuptools and pinned the wheel builder.
- `tests/test_release_contract.py`, `tests/test_runtime_contract.py`: Added executable wheel-content, workflow reachability/tagging, and development-tool contract regressions.
- `.pre-commit-config.yaml`: Added the release workflow and packaging test to formatting and repository hygiene coverage.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`: Documented the release verification graph, immutable image identity, guarded `latest`, and complete wheel contents.
- `progress.md`: Recorded Phase 3 red-green, package build, full-suite, static, import, Compose, and rollback evidence.

Rollback:
- Revert the Phase 3 commit. This does not change runtime databases, configuration, authentication, or deployment paths. Rolling back restores the prior incomplete wheel and ungated image publication, so do not publish or deploy from the rolled-back workflow without an independent verified artifact gate.

## 2026-07-31 - Task: Phase 4 explicit durable state contracts

### What was done

- Added an explicit task-status transition contract, dedicated retry and reconciliation transitions, and detached snapshots from every public task-store method so callers cannot mutate store-owned memory or SQLite state.
- Prevented ordinary updates and repeated creation from reviving terminal tasks; migrated retained-upload retry and durable channel-batch reconciliation to the explicit recovery entry points.
- Replaced independent `config.yaml`/`data.yaml` writes with a recoverable paired generation: both staged files and a mode-`0600` SHA-256 journal are made durable before replacement, and startup completes or rejects an interrupted commit before reading either YAML file.
- Added strict whole-request Web settings validation before any active/configured mutation or persistence. Invalid date directives, trailing `%`, bool-as-int values, ranges, list members, and nested objects now return `400 invalid_settings` with the rejected field and zero side effects.
- Documented the task lifecycle, settings validation, paired persistence, startup recovery, and failure contracts in English, Chinese, and the Web operations guide.

### Testing

- RED Phase 4 selection: `7 failed`, proving mutable return leakage, implicit terminal revival, missing retry/reconcile APIs, missing paired recovery, and partial Web settings mutation. The first system-`pytest` attempt was blocked by a missing `loguru`; the recorded RED result used the repository `.venv`.
- Focused state, persistence, application, Web, channel-library, cancellation, prescan, and upload-progress regression: `304 passed`.
- Simulated a stop after the first YAML replacement and verified deterministic recovery; separately verified that second-value serialization failure leaves both prior files unchanged and that missing staged data plus a target hash mismatch fails without guessing.
- Complete suite: `730 passed, 1 skipped`.
- `make style_check PYTHON=.venv/bin/python`: passed with mypy reporting no issues across 16 modules and Pylint error-only clean.
- `.venv/bin/python -m compileall -q module tests`, `.venv/bin/python -m pip check`, `TMD_TASK_DB_PATH=<temporary>/import.sqlite3 .venv/bin/python check_imports.py`, `TMD_UID=10001 TMD_GID=10001 docker compose -f docker-compose.yaml config`, and `git diff --check`: passed; the import probe created no task database.
- `SKIP=black .venv/bin/pre-commit run --all-files` passed repository hygiene, isort, mypy, and Pylint; `.venv/bin/pre-commit run black --files module/config_persistence.py` passed the Phase 4 Black boundary. Full-repository Black alone would reformat the unrelated pre-existing `tests/test_release_contract.py`; that out-of-scope change was restored and is not included.

### Notes

Changed files:
- `module/task_state.py`, `module/channel_library_service.py`: Added valid transitions, explicit retry/reconcile ownership, terminal-state protection, detached snapshots, and migrated durable recovery callers.
- `module/config_persistence.py`, `module/app.py`: Added paired YAML staging/journaling/recovery and invoked recovery before configuration parsing.
- `module/web.py`: Added complete payload validation and mutation only after successful normalization.
- `tests/module/test_task_state.py`, `tests/module/test_config_persistence.py`, `tests/module/test_app.py`, `tests/module/test_web.py`: Added lifecycle, snapshot isolation, crash recovery, serialization failure, mismatch refusal, persistence integration, and zero-side-effect validation regressions.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`: Documented the new state and configuration contracts.
- `progress.md`: Recorded Phase 4 red-green, recovery, regression, static, operational, and rollback evidence.

Rollback:
- Revert the Phase 4 commit. No SQLite schema or row migration is introduced. Before rollback, stop the service and ensure no paired YAML journal remains; if one exists, run the Phase 4 recovery path or restore both YAML files from the same backup generation. Older code cannot interpret or finish the new journal safely.

## 2026-07-31 - Task: Phase 5 explicit application bootstrap and dependency boundaries

### What was done

- Replaced import-time construction of the production `Application`, event loop, executor, and download queue with an explicit process bootstrap plus lazy compatibility proxies.
- Kept `media_downloader.py` as a distinct compatibility facade without replacing the interpreter module registry, while preserving legacy attribute access and patch restoration behavior.
- Added an injected `DownloadOperations` contract and passed it through runtime startup to Web, Bot, and channel-library adapters; removed every reverse `from media_downloader import ...` dependency from those services.
- Moved process logging setup to explicit bootstrap and expanded the blocking static boundary with the bootstrap/operations modules plus Pylint correctness checks for the repaired facade and orchestration modules.
- Documented the import-safety, bootstrap ownership, operation-injection, and static-boundary contracts in English, Chinese, and the operations guide.

### Testing

- RED Phase 5 contract selection: `4 failed`, proving import-time event-loop/executor/queue creation, facade/implementation module aliasing, reverse service imports, missing factories, and missing static-boundary coverage.
- Focused runtime, Bot, Web, channel-library, downloader, and guided-workflow regressions: `403 passed`; an intermediate compatibility run exposed six proxy cleanup failures, and the focused six-test rerun passed after restoring symmetric delegated attribute deletion.
- Complete suite: `732 passed, 1 skipped`.
- `make style_check PYTHON=.venv/bin/python`: passed; mypy reported no issues across 18 modules and Pylint error-only passed across the expanded facade/Web/Bot/channel/CLI boundary.
- `.venv/bin/pre-commit run black --files media_downloader.py module/application_bootstrap.py module/download_operations.py module/download_runtime.py tests/test_runtime_contract.py`: passed before and after isort; `SKIP=black .venv/bin/pre-commit run --all-files` passed repository hygiene, isort, mypy, and Pylint without broad legacy formatting changes.
- `.venv/bin/python -m compileall -q media_downloader.py module tests`, `.venv/bin/python -m pip check`, a temporary-path `check_imports.py` probe with confirmation that no task database was created, `TMD_UID=10001 TMD_GID=10001 docker compose -f docker-compose.yaml config`, and `git diff --check`: passed.

### Notes

Changed files:
- `module/application_bootstrap.py`, `module/download_entry.py`, `media_downloader.py`: Added explicit resource construction, lazy compatibility access, deferred logging, independent CLI facade delegation, and non-zero configuration-failure cleanup.
- `module/download_operations.py`, `module/download_runtime.py`, `module/web.py`, `module/bot.py`, `module/channel_library_service.py`: Added the operation contract, propagated it through startup, and removed reverse imports from runtime adapters.
- `Makefile`, `.pre-commit-config.yaml`, `tests/test_runtime_contract.py`, `tests/module/test_bot_manager.py`: Added import/resource/facade/dependency regressions and expanded static/formatting gates.
- `README.md`, `README_CN.md`, `docs/web-control-console.md`: Documented explicit bootstrap, import safety, injected operations, and the enlarged correctness boundary.
- `progress.md`: Recorded Phase 5 red-green, compatibility, full-suite, static, import, and Compose evidence.

Rollback:
- Revert the Phase 5 commit. No database schema, persisted row, configuration format, authentication format, dependency, CI workflow, or deployment path changes are introduced; rollback restores import-time runtime resource creation and the former facade/reverse-import behavior.

## 2026-07-31 - Task: Phase 6 complete adversarial review

### What was done

- Re-reviewed task/file invariants, duplicate callbacks, concurrent transfer identity, pause/cancellation/timeout/shutdown paths, restart recovery, SQLite contracts, readiness, Web authentication/CSRF/request bounds, paired configuration recovery, packaging, CI reachability, container mounts/health, and import/dependency boundaries.
- Confirmed one local gate defect: the required unskipped `pre-commit run --all-files` could not pass because `tests/test_release_contract.py` was inside the enforced Black boundary but retained pre-existing formatting drift.
- Accepted only Black's minimal mechanical rewrite of that controlled release-contract expression; no runtime, schema, configuration, dependency, workflow, authentication, deployment, or production behavior changed.
- Kept production deployment blocked pending a pushed reviewed commit and a successful real multi-platform CI image build.

### Testing

- Focused adversarial regression groups: `63 passed` for lifecycle/concurrency/state invariants, `307 passed` for persistence/recovery/readiness/auth/Web/channel/resource boundaries, and `21 passed` for dependency/Docker/release/runtime contracts.
- RED final gate: `.venv/bin/pre-commit run --all-files` failed because Black reformatted only `tests/test_release_contract.py`; the second unskipped run passed trailing-whitespace, end-of-file, Black, isort, mypy, and Pylint.
- Complete suite after the correction: `732 passed, 1 skipped`.
- Fresh SQLite probes initialized all three stores and verified `PRAGMA integrity_check == 'ok'`, WAL mode, synchronous level `2`, `busy_timeout=5000`, mode `0600`, and schema versions task `1`, channel `8`, resource `3`; channel/resource connections also enforced foreign keys.
- A temporary Web-auth probe verified mode `0600`, password-hash verification, no configured plaintext in the file, and a persisted session secret.
- `make style_check PYTHON=.venv/bin/python`: passed with mypy clean across 18 modules and Pylint error-only clean across the expanded orchestration boundary.
- `.venv/bin/python -m compileall -q media_downloader.py module tests`, `.venv/bin/python -m pip check`, a temporary-path `check_imports.py` probe with no task database creation, `TMD_UID=10001 TMD_GID=10001 docker compose -f docker-compose.yaml config`, and `git diff --check`: passed.
- Local Docker image construction was not claimed: `docker info` could not reach `/Users/wangyichuan/.colima/default/docker.sock`. The required successful multi-platform CI build remains a hard pre-deployment gate for Phase 7.

### Notes

Changed files:
- `tests/test_release_contract.py`: Applied the exact Black formatting required for the already-enforced release-contract boundary so the mandatory unskipped full pre-commit gate passes cleanly.
- `progress.md`: Recorded the complete Phase 6 review inventory, focused/full gates, SQLite/auth probes, local Docker limitation, and remaining remote CI deployment gate.

Rollback:
- Revert the Phase 6 commit. This reintroduces only the known full-pre-commit formatting failure; no runtime data, schema, configuration, authentication, release workflow, image, or production state is affected.

## 2026-07-31 - Task: Deploy first-principles remediation to production

### What was done

- Confirmed the production service does not use Docker: `tg-downloader.service` directly runs `run_downloader.sh`, which activates the repository virtual environment and executes `python3 media_downloader.py`; Docker is inactive and no container is involved in the production path.
- Reclassified the failed optional Docker image publication as unrelated to this deployment, confirmed local `master` was already pushed at `3032781d4681f19bc2646e417f776408a3b83c3e`, and used the actual systemd/Python deployment path.
- Verified all download, scan, channel-batch, and resource-delivery queues were empty before stopping the service. Preserved the production worktree's existing untracked `backups/`, `d`, `sessions/`, and `web_tasks.sqlite3.bak-20260717-085320` entries without cleanup or overwrite.
- Stopped only `tg-downloader.service` and created the mode-`0700` rollback point `backups/deploy-20260730-220645` containing the pre-deployment commit/status, `config.yaml`, `data.yaml`, `.web_auth.json`, sessions, all three SQLite databases, checksums, and the pre-deployment virtual-environment package list.
- Fast-forwarded production from `efa7391958503afa439b6319b063f35ccf18c77b` to `3032781d4681f19bc2646e417f776408a3b83c3e`, synchronized the existing `.venv` to the committed requirements, and restarted the systemd service.

### Testing

- Pre-deployment: `tg-downloader.service` was active with no warning-or-higher journal entries in the preceding 30 minutes; the root filesystem had 14 GB free; task, scan, batch, and resource-delivery status counts contained terminal rows only.
- Backup: each database was copied with `sqlite3.Connection.backup()` and its backup passed `PRAGMA integrity_check == 'ok'`; the resulting rollback directory contained 19 files before the package manifest was added and occupied approximately 186 MB.
- Update: `git pull --ff-only origin master` completed as a clean fast-forward to `3032781`; tracked files remained clean and all pre-existing untracked runtime/backup paths remained present.
- Startup gate: the production `.venv` passed module compilation, explicit facade/bootstrap/runtime/auth imports, YAML configuration parsing, `pip check`, and rollback-point SHA-256 verification. Runtime versions resolved to Pyrogram `2.1.22`, aiohttp `3.9.3`, and psutil `5.9.8`.
- Post-deployment: systemd reached `active/running`; `/healthz` returned HTTP `200` with `{"status":"ok"}` after 11 seconds; the process listened on port 80 and the Web root returned the expected login redirect (`302`).
- Post-deployment database probes: all three live databases passed `PRAGMA quick_check == 'ok'`; task, scan, channel-batch, and resource-delivery tables still contained no active or queued work. The new service start produced no warning-or-higher journal entries.

### Notes

Changed files:
- `progress.md`: Recorded the verified non-Docker production path, preflight, rollback point, fast-forward update, dependency synchronization, readiness, database, queue, and journal evidence.

Rollback:
- Stop `tg-downloader.service`, preserve any state created after this deployment, switch the repository to `efa7391958503afa439b6319b063f35ccf18c77b`, restore the prior virtual-environment packages from `backups/deploy-20260730-220645/installed_packages_before.txt`, and restart the service. The same backup directory contains verified copies of configuration, authentication, sessions, and all three databases if a state rollback is also required.

## 2026-07-31 - Task: Repair concurrent task phases and add failed-download retry

### What was done

- Corrected the task transition contract so a live multi-file or multi-package task may move from uploading back to queued/downloading while other files or the next package still require download work; terminal tasks remain protected from ordinary reactivation.
- Added a durable channel-batch download retry path that requeues only package attempts ending in `completed_with_errors`, `failed`, or `not_found`, retains completed package attempts, refuses a retry when another active batch owns one of the same packages, and reuses the original immutable batch snapshot.
- Extended `POST /api/tasks/<task_id>/retry` to preserve upload-only retry priority for retained upload failures and otherwise schedule failed package downloads.
- Added a “重试失败项” action to failed or partially failed channel-library tasks in both the task list and detail header. Successful local files inside a partially failed package follow the existing verified-size skip path instead of being downloaded or uploaded twice.
- Updated the Web console and channel download outbox documentation with the active-phase and retry contracts.

### Testing

- RED: the five initial regressions failed with the production `uploading -> downloading` and `uploading -> queued` transition errors, missing download-retry service method, upload-only Web routing, and missing UI action.
- Focused red-green selection: `7 passed`, covering mixed download/upload phases, next-package queuing, failed-package-only retry, competing active-batch rejection, upload-only priority, failed-download routing, and the retry button contract.
- Adjacent task, lifecycle, channel-library, Web, UI, cancellation, and clear-history regression selection: `291 passed`.
- Complete suite: `740 passed, 1 skipped`.
- `.venv/bin/pre-commit run --all-files`: passed trailing-whitespace, end-of-file, Black, isort, mypy, and Pylint hooks.
- `make style_check PYTHON=.venv/bin/python`: mypy reported no issues across 18 modules and Pylint error-only passed.
- `.venv/bin/python -m compileall -q media_downloader.py module tests`, `.venv/bin/python -m pip check`, a temporary-path `check_imports.py` probe with confirmation that no task database was created, and `git diff --check`: passed.

### Notes

Changed files:
- `module/task_state.py`: Allowed legitimate active-phase cycling while retaining terminal-state protection.
- `module/channel_library_store.py`, `module/channel_library_service.py`: Added persisted failed-package retry, ownership conflict prevention, task reactivation, and owner-loop scheduling.
- `module/web.py`, `module/templates/index.html`: Routed upload/download retries correctly and exposed the failed-task retry action.
- `tests/module/test_task_state.py`, `tests/test_channel_library_download.py`, `tests/module/test_web.py`, `tests/module/test_task_page_ui.py`: Added state, persistence, service, API, and UI regressions.
- `docs/web-control-console.md`, `docs/channel-library-download-outbox.md`: Documented active-phase interleaving and failed-download retry behavior.
- `progress.md`: Recorded the production regression, red-green evidence, full gates, and rollback boundary.

Rollback:
- Revert this task's commit and redeploy the prior release. No database schema or configuration format changes are introduced. Existing retried batch rows use only statuses already understood by the prior release; stop the service before rollback so no retry is active.

## 2026-07-31 - Task: Deploy concurrent-phase and failed-retry repair to production

### What was done

- Pushed commit `402c40e5ec426378e753714f9681d7bb9a270355` to `origin/master` and deployed it to `/root/telegram_media_downloader` with `git pull --ff-only origin master`.
- Confirmed all Web, channel scan, channel download, package attempt, and resource delivery queues were inactive before stopping `tg-downloader.service`.
- Created the restricted rollback point `backups/deploy-20260730-224158` on the EDT-configured production server, preserving configuration/runtime state and verified backups of all three SQLite databases.
- Restarted the non-Docker systemd deployment and left the eight existing partially failed Web tasks terminal so retries remain an explicit user action through “重试失败项”.

### Testing

- Before deployment, all active-queue checks returned zero and `PRAGMA quick_check` returned `ok` for `web_tasks.sqlite3`, `channel_library.sqlite3`, and `resource_bot.sqlite3`.
- Each SQLite backup passed `PRAGMA integrity_check`.
- Production `.venv/bin/python check_imports.py`, compileall, `pip check`, `git diff --check`, and the retry-button template contract passed before service startup.
- After startup, `tg-downloader.service` was `active/running`, port 80 was owned by the service process, `/healthz` returned HTTP 200 with `{"status":"ok"}`, `/` returned the expected HTTP 302 login redirect, and the deployed template contained “重试失败项”.
- Post-start database quick checks remained `ok`, active queues remained zero, the tracked production worktree remained clean, and the startup journal contained no traceback, exception, error, critical, or failed entries.

### Notes

Changed files:
- `progress.md`: Recorded the production commit, verified backup point, deployment path, and post-start evidence.

Rollback:
- Stop `tg-downloader.service`, deploy prior code commit `6e954fc55362d5b2cc3064eadfb3a02dccce99f9`, and restart the service. Preserve current databases by default; `backups/deploy-20260730-224158` contains integrity-verified pre-deployment copies if a confirmed state rollback is also required.

## 2026-08-09 - Task: Deploy bounded keyword-monitor queue and progress visibility

### What was done

- Pushed and deployed `38e9ead124b9f4646f9fab1d8c3fd55cd0300159`, adding keyword-monitor batch admission bounded by the configured four download workers, durable aggregate progress, global queue positions, safe failure reasons, and group-level failed-item retry.
- Production preflight found `179` persisted keyword-monitor batches queued, no downloading/uploading batches, a healthy service, approximately `13 GB` free disk, clean tracked files, and `PRAGMA quick_check == 'ok'` for all three SQLite databases.
- Stopped the service and created mode-`0700` rollback point `backups/deploy-20260809-222911`; all three SQLite backups passed `PRAGMA integrity_check` and the backup occupied approximately `179 MB`.
- Detected that the prior graceful-shutdown path had converted the 179 queued batches to cancelled while stopping the old process. Identified the exact affected set as keyword-monitor batches cancelled during `2026-08-10T02:29:11Z` through `02:29:16Z`; the set contained 179 distinct tasks and single-package batches with no file rows. The 11 older cancelled histories were outside this set.
- Added and deployed `0a13c3af420840b7aca8413027e2948195a0178a`, preserving queued/admitted work during service shutdown while retaining explicit user cancellation semantics. Created second mode-`0700` rollback point `backups/requeue-repair-20260809-223503` before state repair.
- Requeued exactly those 179 deployment-cancelled batch, package, channel-package, and Web-task rows in one attached SQLite transaction. Stored the exact target IDs in `backups/requeue-repair-20260809-223503/requeue-targets.json`.

### Testing

- Local complete suite after queue/progress implementation: `745 passed, 1 skipped`; after shutdown recovery repair and new regressions: `747 passed, 1 skipped`.
- Black, `git diff --check`, Python compilation, JavaScript syntax, import probes, and `pip check` passed. Production tracked files remained clean after both fast-forward-only updates.
- Production startup reached `active/running`; `/healthz` returned HTTP `200` with `{"status":"ok"}`, `/` returned the expected HTTP `302`, and all three databases continued to pass `PRAGMA quick_check`.
- Post-repair queue state was `2 downloading + 177 queued`, with active task timestamps advancing and no new bulk cancellation. This is within the configured four-batch admission ceiling; two admitted tasks were waiting for disk reservations.
- Startup and observation journals contained no warning, traceback, exception, critical, failed, or error entries. Root filesystem retained approximately `13 GB` free.

### Notes

Changed files:
- `module/channel_library_service.py`, `module/channel_library_store.py`, `module/web.py`: Added bounded admission, shutdown-safe recovery, durable summaries/queue positions, and bulk failed-item retry.
- `module/templates/index.html`, `module/static/css/index.css`: Added compact monitor progress, queue position, failure reason, and retry controls.
- `tests/test_channel_library_download.py`, `tests/module/test_channel_library_web.py`: Added admission, shutdown, summary, queue, retry, API, and UI regressions.
- `progress.md`: Recorded production deployment, the shutdown-state incident, exact repair set, rollback points, and final health evidence.

Rollback:
- Stop `tg-downloader.service`, preserve the current live databases, and deploy code commit `946e3b30de5a3556674a121410ad4ab80c0b0caa` to remove both queue changes. Restore database files only if state rollback is explicitly required: `backups/deploy-20260809-222911` preserves the post-shutdown cancelled state, while `backups/requeue-repair-20260809-223503` preserves the same state immediately before the exact 179-row requeue transaction. The preferred rollback keeps current databases because both code changes introduce no schema migration.

## 2026-08-10 - Task: Deploy disk-window reservation for oversized packages

### What was done

- Diagnosed the production stall: 176 Web tasks `queued`, zero `downloading`. All four
  batch slots were held by batches whose first package waited forever in the FIFO disk
  admission queue for space that can never exist (25.7/21.3 GiB packages on a 24 GiB
  disk with ~13 GiB free and 3 GiB minimum-free).
- Deployed `bc6917e` + `84cb344`: packages whose reservation can never fit are failed
  immediately with `package_exceeds_disk_capacity` instead of blocking the FIFO (and
  every download slot) forever; the batch continues to its next package.
- Verified the fix: previously-stuck batches resumed downloading; the two oversized
  packages were skipped with the capacity error; queue drains normally.
- Deployed `f9c92a5` (this task): reservation window. A package no longer reserves its
  full known total size. With cloud upload enabled, local deletion after upload, no
  zipping, and no Telegram forwarding, each worker holds at most one file on disk at a
  time (download -> upload -> delete is serial per worker), so the reservation is
  `min(known_total_size, max_download_task * largest_item_size)`. Packages whose total
  size exceeds the disk now download file by file within the bounded window.

### Testing

- Local complete suite: `747 passed, 1 skipped`.
- Production preflight: service active, ~13 GB free, three SQLite databases
  `PRAGMA quick_check == 'ok'`, tracked files clean.
- After deployment and restart: `tg-downloader.service` active; downloads resumed
  immediately; package summaries now include `max_item_size` via a join; queue
  continues draining with several batches downloading concurrently.
- Window math verified against live data: a 20.8 GiB package (largest file 1.36 GiB)
  now reserves 5.4 GiB and downloads; a 25.5 GiB package (largest file 2.59 GiB)
  reserves 10.3 GiB and still cannot fit with the 3 GiB minimum-free margin.

### Notes

Changed files:
- `module/channel_library_service.py`: fail-fast capacity check, `max_item_size`
  descriptors, `_package_reservation_bytes` window helper.
- `module/channel_library_store.py`: package summaries include `max_item_size`;
  preserve `package_exceeds_disk_capacity` error code.
- `module/package_download.py`: skip-download finalization for rejected packages.
- `progress.md`: recorded the stall diagnosis and both deployments.

Known boundary:
- If cloud uploads persistently fail, files are retained for the manual upload retry
  and can accumulate beyond the reservation window on a small disk; downloads then
  fail with disk-full errors rather than silently corrupting. Upload retry semantics
  are unchanged (retry re-uploads the retained local file).
- A package whose single largest file itself exceeds free disk minus the
  minimum-free margin still fails with `package_exceeds_disk_capacity`; lowering
  `channel_library.min_free_disk_bytes` (e.g. to 2 GiB) admits marginally-over
  packages such as the 25.5 GiB one above.

Rollback:
- Stop `tg-downloader.service` and deploy code commit `84cb344` to remove the window
  reservation while keeping the fail-fast capacity fix. No database schema or
  configuration format changes are introduced.

## 2026-08-18 - Task: Fix multi-package batch finalized between packages (spurious download failures)

### What was done

- Diagnosed a production bot batch task (task id 2, channel -1001638138979) that reported 7 downloads success + 5 failures (messages 24, 26, 29, 30, 31) while every failed message actually never downloaded: all five enqueue attempts raised
  `TaskTransitionError: invalid_task_transition: 'completed' -> 'queued'` in `module/task_state.py:transition_file`.
- Root cause: a multi-package prescan batch (`run_packages` → `download_prepared_messages`) runs several packages on one parent task. After the first package's files all completed, `snapshot_node` persisted the task as `completed` (terminal) because `_status_from_node` finalized as soon as `success + failed + skipped >= total`. Every later package then failed to enqueue on the same task, surfacing as bogus "Download Failed" rows.
- Fix (`module/task_state.py`): `_status_from_node` now mirrors `TaskNode.is_finish()` and refuses to finalize while `prescan_batch_in_progress` is set, so intermediate package completion keeps the task in `downloading` and later packages can still enqueue. The final snapshot after the whole batch still reaches its true terminal status (`completed` / `completed_with_errors`) with all package counts.
- Added regression test `test_snapshot_does_not_finalize_active_prescan_batch` (tests/module/test_task_state.py) covering: package-1-all-done snapshot stays non-terminal, next-package enqueue (`transition_file` to `queued`) succeeds, and the batch-end snapshot reaches `completed_with_errors`.
- Committed `800400f`, pushed to `origin/master`, and deployed to `/root/telegram_media_downloader` (fast-forward pull + `systemctl restart tg-downloader.service`).

### Testing

- Local complete suite: `741 passed, 1 skipped`; the only failures (`7`) are pre-existing and unrelated: five comment/package naming-preview expectations from the save-root layout work and one rclone exec test on this Mac. Verified identical failures on the clean tree before the fix.
- Focused suites: `tests/module/test_task_state.py`, `tests/module/test_task_invariants.py`, `tests/test_channel_library_download.py` → `88 passed`.
- Production preflight before restart: service `active`, no active/queued web tasks or channel batches (all terminal), `PRAGMA quick_check` unchanged, ~13 GB free disk.
- After restart: `tg-downloader.service` `active/running`, deployed commit `800400f`, `/healthz` returned `{"status":"ok"}`, startup log `成功启动(按Ctrl+C停止)`, and the startup journal contained no error/exception/traceback/critical/failed entries.

### Notes

Changed files:
- `module/task_state.py`: `_status_from_node` defers terminal finalization while a prescan batch is in progress.
- `tests/module/test_task_state.py`: added the multi-package batch regression test.
- `progress.md`: recorded this diagnosis, fix, and deployment.

Rollback:
- Stop `tg-downloader.service`, fast-forward the production checkout back to commit `54dbc4a`, and restart. No database schema or configuration format changes are introduced.

## 2026-08-18 - Task: Fix persisted task-id collision and verify batch re-run

### What was done

- After deploying the mid-batch finalization fix, a `/retry_failed` re-run still failed with the same `invalid_task_transition: 'completed' -> 'queued'`. Root cause was a second, independent bug: `DownloadBot.gen_task_id` is an in-memory counter starting at zero every process start, while the task store persists bot task ids across restarts. The first new task after restart therefore reused previously terminal id `1`, so every enqueue on the new node was rejected.
- Fix (`module/bot.py`): `gen_task_id` now skips ids already present in the task store (`get_task_store().get_task(...)`), falling back to the raw counter when the store is not initialized (tests). This covers all bot flows that mint task ids (prescan, retry, comment, package, link download).
- Added regression tests `test_gen_task_id_skips_persisted_task_ids` and `test_gen_task_id_falls_back_to_counter_without_task_store` (tests/module/test_bot_commands.py).
- Committed `1591883`, pushed to `origin/master`, deployed to `/root/telegram_media_downloader` (fast-forward pull + `systemctl restart tg-downloader.service`).

### Verification (production)

- User re-ran `/retry_failed -1001638138979|24 -1001638138979|26 -1001638138979|29 -1001638138979|30 -1001638138979|31` at 11:21 EDT; new task id 3 (skipped persisted 1/2).
- All 5 previously-failed messages downloaded and uploaded successfully: 24 (IMG_5817, 11.1 MB), 26 (IMG_5824, 22.8 MB), 29 (IMG_5932, 50.8 MB), 30 (IMG_5934, 14.8 MB), 31 (IMG_5933, 39.5 MB); `success=5, failed=0, skip=0`, `upload_success_count=5`, zero `invalid_task_transition` errors.
- Files landed under `/data/tg/公主的㊙️㊙️花园/2026_08/` and were removed locally after upload per `after_upload_file_delete`.
- Service healthy after restart: `active`, `/healthz` `{"status":"ok"}`, clean startup journal.

### Notes

Changed files:
- `module/bot.py`: collision-free `gen_task_id`.
- `tests/module/test_bot_commands.py`: persisted-id collision and no-store fallback tests.
- `progress.md`: recorded the second fix and its production verification.

Rollback:
- Stop `tg-downloader.service`, fast-forward the production checkout back to commit `765dd75`, and restart. No database schema or configuration format changes are introduced.

## 2026-08-24 - Task: Design Hermes MCP control layer

### What was done

- Defined a local `stdio` MCP adapter for Hermes that connects to the resident downloader through an authenticated loopback control interface.
- Defined MCP coverage for resource-package search, download submission and control, system status, and keyword-monitor CRUD, history, summaries, and failure retry.
- Defined explicit runtime shutdown of the `resource_delivery` / Resource Bot publishing path while preserving its code and database for rollback.

### Testing

- Reviewed the existing Web routes, `ChannelLibraryStore`, `ChannelLibraryService`, task store, `BotManager`, and resource delivery startup path.
- Ran `git diff --check`; no whitespace errors were reported.
- Performed a placeholder, scope, and consistency review of the design document. No runtime code was changed or executed.

### Notes

Changed files:
- `docs/superpowers/specs/2026-08-24-mcp-hermes-control-design.md`: Added the approved architecture and tool contract for Hermes MCP integration.
- `progress.md`: Recorded the design step and validation evidence.

Rollback:
- Revert the design commit or remove the two documentation-only changes; no runtime behavior, database schema, or configuration was changed.

## 2026-08-24 - Task: Review Hermes MCP control layer design

### What was done

- Reviewed the Hermes MCP control-layer design against the current runtime code and recorded the review as section 10 of the design document.
- Flagged three blocking issues that change the implementation shape: the deployment topology assumption (resident downloader runs on the remote server, not the machine that launches the MCP stdio process), the contradiction between "MCP routes inside the existing Web process" and a separate loopback control port, and the absence of a side-effect-free multi-package download entry point.
- Corrected design claims that do not match the code: idempotency-key scope, package search visibility, pause/resume semantics, task listing filters and retention, cancel outcomes, resource-delivery shutdown impact on the Web console and management Bot commands, and API-key storage in the periodically rewritten config file.
- Revised the acceptance criteria and proposed narrowing the first iteration to the read-only tools plus a single submit entry point.

### Testing

- Read-only review of `module/web.py`, `module/web_auth.py`, `module/web_commands.py`, `module/web_server.py`, `module/channel_library_service.py`, `module/channel_library_store.py`, `module/task_state.py`, `module/bot.py`, `module/app.py`, `module/config_persistence.py`, and `module/templates/index.html`.
- Ran `git diff --check`; no whitespace errors were reported.
- No runtime code was changed or executed; this round is documentation only.

### Notes

Changed files:
- `docs/superpowers/specs/2026-08-24-mcp-hermes-control-design.md`: Appended section 10 with blocking issues, per-item corrections, revised acceptance criteria, and a scope recommendation.
- `progress.md`: Recorded the design review round.

Rollback:
- Remove section 10 from the design document and this progress entry; no runtime behavior, database schema, or configuration was touched.

## 2026-08-24 - Task: Confirm Hermes MCP deployment topology

### What was done

- Verified the real deployment topology and replaced blocking item A1 in the design review with confirmed facts plus three ranked routes.
- Established that Hermes (`ubuntu-wg`) and the downloader (RackNerd) share no private link, that `tgdn.wyichuan.cc` is a Cloudflare proxy rather than a host-side tunnel process, and that the console is reachable directly on the origin IP.
- Recommended running the MCP process on the downloader host and letting Hermes launch it over SSH, which keeps the control interface loopback-only and adds no public listener.

### Testing

- `ssh rn`: confirmed `tg-downloader.service` is active, only `lo` and `eth0` exist (no WireGuard), and the Web process listens on `0.0.0.0:80`.
- `grep` of the server config: `web_host: 0.0.0.0`, `web_port: 80`; no tunnel or reverse-proxy process is running on the server.
- `dig tgdn.wyichuan.cc` returns Cloudflare addresses; `curl http://192.3.85.23/` and `curl https://tgdn.wyichuan.cc/` both return 302.
- `ssh ubuntu-wg` then SSH to RackNerd: failed with host key verification, so that hop still needs one-time setup.
- Read-only checks only; no server state, service, or configuration was changed.

### Notes

Changed files:
- `docs/superpowers/specs/2026-08-24-mcp-hermes-control-design.md`: Rewrote review item A1 with the confirmed topology, the three candidate routes, and the pre-existing origin-exposure caveat.
- `progress.md`: Recorded the topology verification round.

Rollback:
- Restore the previous A1 wording and remove this progress entry; no runtime behavior or configuration was touched.

## 2026-08-24 - Task: Settle Hermes MCP transport route

### What was done

- Recorded the decision to reach the downloader over the public Cloudflare entry with Bearer authentication, and closed blocking review item A1 with the reasoning behind it.
- Rewrote the goal, runtime constraint, architecture, configuration, and acceptance sections around the cross-machine HTTPS route, including JSON 401 behaviour, Cookie/Session rejection, constant-time key comparison, failure rate limiting reusing the existing login limiter, and audit logging without key material.
- Moved API key storage out of the periodically rewritten YAML config to an environment variable or a dedicated 0600 file.
- Removed origin access restriction from this task's scope and recorded it, together with the development-server exposure, as a pre-existing baseline risk in a new section; the MCP security design is now required to hold without assuming either is fixed.

### Testing

- Verified the server runs Python 3.11.2 with no virtualenv and about 349 MB of available memory, which informed the transport comparison.
- Ran `git diff --check` after each documentation edit; no whitespace errors were reported.
- Documentation only; no runtime code, server state, or configuration was changed.

### Notes

Changed files:
- `docs/superpowers/specs/2026-08-24-mcp-hermes-control-design.md`: Rewrote sections 1, 2, 3, 7, 8 for the chosen transport, closed review item A1 with the decision, and added section 11 for out-of-scope pre-existing risks.
- `progress.md`: Recorded the transport decision round.

Rollback:
- Revert this documentation change; no runtime behavior, database schema, or configuration was touched.

## 2026-08-24 - Task: Fold MCP review corrections into spec and write the implementation plan

### What was done

- Merged every review correction into the design document body so sections 1 through 8 are self-consistent, and marked the review section as historical record.
- Recorded the delivery order in the spec: disable the publishing path first, then the read-only MCP tools plus download submission, then the write and keyword-monitor tools.
- Corrected the spec's tool contracts: search now returns the same set the browser sees with an added downloadable flag, submission uses a new selection-free entry point with derived per-library idempotency keys, task listing drops the unbacked time-range promise, cancellation documents both of its success shapes, and pause/resume become explicit idempotent settings rather than a toggle.
- Corrected the publishing-shutdown section to cover the console panel, the error-code location, the management Bot command surface, and the residual token checks.
- Wrote a thirteen-task implementation plan with per-task files, interfaces, failing tests, implementation code, verification commands, and commit messages.

### Testing

- Read the current implementations of the routes, service methods, store queries, task store, Bot manager, and test fixtures that each task touches, so the plan's code and test scaffolding match the real signatures.
- Ran `git diff --check` after each edit; no whitespace errors were reported.
- Verified the plan file contains all thirteen tasks with no duplicated or truncated sections.
- Planning and documentation only; no runtime code was changed or executed.

### Notes

Changed files:
- `docs/superpowers/specs/2026-08-24-mcp-hermes-control-design.md`: Folded the review corrections into the body and annotated the review section as already merged.
- `docs/superpowers/plans/2026-08-24-mcp-hermes-control.md`: Added the thirteen-task implementation plan.
- `progress.md`: Recorded the planning round.

Rollback:
- Delete the plan document and revert the spec edits; no runtime behavior, database schema, or configuration was touched.

## 2026-08-24 - Task: Disable the resource delivery publishing path

### What was done

- Stopped `BotManager` from creating or starting the Resource Bot, `ResourceDeliveryService`, resource store, and resource administration commands.
- Removed the residual requirement that a configured `resource_bot_token` must be paired with a management Bot token.
- Changed runtime startup and shutdown checks to depend only on `bot_token`, so a resource-only configuration cannot start the Bot lifecycle.
- Updated lifecycle tests to lock in the disabled behavior while retaining the legacy resource modules and test coverage.

### Testing

- TDD red: updated lifecycle expectations and added a factory-guard regression test; targeted tests failed against the old startup path.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_bot_manager.py tests/module/test_resource_bot.py tests/module/test_resource_delivery.py -q` → `47 passed`.

### Notes

Changed files:
- `module/bot.py`: disabled Resource Bot and delivery-service startup.
- `module/download_runtime.py`: removed resource-token-only Bot lifecycle branches.
- `tests/module/test_bot_manager.py`: added regression coverage for disabled publishing startup.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to restore the previous Resource Bot and delivery startup branches; no database schema was changed.

## 2026-08-24 - Task: Publish the resource delivery disabled contract

### What was done

- Changed all resource-delivery write paths to return HTTP `410` with `resource_delivery_disabled` when the resource store is not active.
- Changed the delivery history read endpoint to return a stable empty payload with `disabled: true`, allowing the Web console to stop polling cleanly in the next task.

### Testing

- TDD red: `./.venv311/bin/python -m pytest tests/module/test_channel_library_web.py -q -k resource_delivery` → 2 failures (`503` instead of the expected disabled contract).
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_channel_library_web.py -q` → `114 passed`.

### Notes

Changed files:
- `module/web.py`: added the `resource_delivery_disabled` error contract and disabled read payload.
- `tests/module/test_channel_library_web.py`: added read and write contract tests.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to restore the prior `503 service_unavailable` behavior for inactive resource delivery.

## 2026-08-24 - Task: Hide the disabled resource delivery panel

### What was done

- Marked the publishing tab as the resource-delivery panel and added a disabled state to the Web client.
- When the backend returns `disabled: true`, the client hides the panel and clears the publishing poll interval instead of showing repeated read errors.

### Testing

- TDD red: the new static UI contract failed because the template had no disabled handling.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_task_page_ui.py tests/module/test_channel_library_web.py -q` → `121 passed`.

### Notes

Changed files:
- `module/templates/index.html`: added disabled-state rendering and polling shutdown.
- `tests/module/test_task_page_ui.py`: added the disabled-panel contract test.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to restore the publishing tab and its continuous polling behavior.

## 2026-08-24 - Task: Add MCP enablement and API key loading

### What was done

- Added `Application.mcp_enabled`, loaded from the non-secret `mcp.enabled` configuration block.
- Added API Key loading from `TMD_MCP_API_KEY` with an owner-only key-file fallback beside the config file.
- Added constant-time key verification and a secret-free `mcp` section to `config.example.yaml`.

### Testing

- TDD red: `./.venv311/bin/python -m pytest tests/module/test_mcp_auth.py -q` failed during collection because `module.mcp_auth` did not exist.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_mcp_auth.py tests/module/test_app.py -q` → `12 passed`.

### Notes

Changed files:
- `module/mcp_auth.py`: added API Key path, loading, and comparison helpers.
- `module/app.py`: added the MCP feature flag and config loading.
- `config.example.yaml`: documented the MCP enablement switch without a secret.
- `tests/module/test_mcp_auth.py`: added key precedence, permissions, missing-key, and comparison tests.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove MCP configuration loading; no existing configuration file or database is modified by this task.

## 2026-08-24 - Task: Add the Bearer-authenticated MCP route skeleton

### What was done

- Added the `/api/mcp` Flask blueprint with a protected `GET /ping` route.
- Added Bearer API Key authentication, constant-time comparison, per-client failure limiting, JSON error responses, and disabled-feature route registration behavior.
- Registered the MCP blueprint from the existing Web initialization path without changing browser Session/CSRF behavior.

### Testing

- TDD red: `./.venv311/bin/python -m pytest tests/module/test_mcp_control.py -q` failed during collection because `module.mcp_control` did not exist.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_mcp_control.py tests/test_web_csrf_contract.py -q` → `11 passed`.

### Notes

Changed files:
- `module/mcp_control.py`: added the MCP blueprint, authentication decorator, rate limiting, and ping route.
- `module/web.py`: registered the MCP blueprint during Web initialization.
- `tests/module/test_mcp_control.py`: added authentication, disabled-mode, and secret-disclosure regression tests.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove the MCP blueprint registration; the existing Web Session/CSRF routes remain unchanged.

## 2026-08-24 - Task: Expose resource package search and detail over MCP

### What was done

- Added authenticated MCP package search using the existing aggregate filters and keyset cursor semantics.
- Added package detail with bounded media-item pagination.
- Preserved the Web-visible package set, including non-superseded provisional packages, and added an explicit `downloadable` flag based on stable package boundaries.
- Mapped existing Web validation errors into the MCP JSON error contract.

### Testing

- TDD red: after fixing the test fixture's existing three-value library return shape, `./.venv311/bin/python -m pytest tests/module/test_mcp_packages.py -q` failed with the expected missing-route `404` responses.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_mcp_packages.py tests/module/test_mcp_control.py -q` → `10 passed`.

### Notes

Changed files:
- `module/mcp_control.py`: added package filters, search, detail, and package-view helpers.
- `tests/module/test_mcp_packages.py`: added package query and error-contract tests.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove MCP package query routes; the existing Web package APIs remain unchanged.

## 2026-08-24 - Task: Expose MCP system status and task reads

### What was done

- Added a bounded MCP system-status endpoint with runtime phase, download state/speed, disk capacity, and task counts.
- Added bounded recent-task listing with optional status filtering.
- Added task detail lookup by the persisted string task ID, including a channel download-batch header when available.
- Kept sensitive application fields out of all status responses.

### Testing

- Confirmed the existing `TaskStateStore.create_task` signature before writing the fixture calls.
- TDD red: `./.venv311/bin/python -m pytest tests/module/test_mcp_status.py -q` returned the expected missing-route failures.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_mcp_status.py -q` → `3 passed`.

### Notes

Changed files:
- `module/mcp_control.py`: added system, task-list, and task-detail routes.
- `tests/module/test_mcp_status.py`: added bounded-list, status, not-found, and secret-exclusion tests.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove MCP system/task read routes; existing Web task routes remain unchanged.

## 2026-08-24 - Task: Create download batches from explicit package IDs

### What was done

- Added `ChannelLibraryService.create_download_batches_for_packages(...)` for MCP submissions.
- The method validates all requested packages before creation, rejects non-stable packages, groups by library/source chat, derives scoped idempotency keys, and never reads or clears Web selection state.
- Added regression coverage for selection isolation, idempotent replay, and unstable-package rejection.

### Testing

- TDD red: `./.venv311/bin/python -m pytest tests/module/test_channel_library_service.py -q -k explicit_package_batches` first failed with the expected missing-method error; fixture setup was then corrected to mark the test library ready and add media items required by the existing store contract.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_channel_library_service.py -q` → `50 passed`.

### Notes

Changed files:
- `module/channel_library_service.py`: added the explicit package batch creation service method.
- `tests/module/test_channel_library_service.py`: added explicit-batch isolation, idempotency, and validation tests.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove the MCP-specific service entry point; existing selection-based Web download creation remains unchanged.

## 2026-08-24 - Task: Submit explicit downloads over MCP

### What was done

- Added `POST /api/mcp/downloads` with strict payload validation for package IDs, idempotency key, and boolean redownload confirmation.
- Mapped unstable-package, duplicate/replay, missing-key, and redownload errors to stable MCP responses.
- Scheduled persisted batches through the existing channel service and preserved Web selection state.

### Testing

- TDD red: `./.venv311/bin/python -m pytest tests/module/test_mcp_submit.py -q` returned the expected missing-route `404` responses.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_mcp_control.py tests/module/test_mcp_packages.py tests/module/test_mcp_status.py tests/module/test_mcp_submit.py -q` → `18 passed`.

### Notes

Changed files:
- `module/mcp_control.py`: added the explicit download submission route.
- `tests/module/test_mcp_submit.py`: added selection-isolation, idempotency, validation, and conflict tests.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove MCP download submission; the existing Web download paths remain unchanged.

## 2026-08-24 - Task: Add the MCP stdio adapter for Hermes

### What was done

- Added the Hermes-side MCP stdio adapter with a Bearer-authenticated HTTP client for package search/detail, system status, task reads, and explicit download submission.
- Added six MCP tool definitions with JSON input schemas and required download idempotency fields.
- Pinned the adapter dependencies to `mcp==2.0.0` and `requests==2.32.3`.
- Kept the MCP SDK import inside `main()` and restricted adapter logging to stderr.

### Testing

- TDD red: `./.venv311/bin/python -m pytest tests/test_mcp_server.py tests/test_dependency_contract.py -q` failed during collection with the expected missing `mcp_server` module.
- TDD green: `./.venv311/bin/python -m pytest tests/test_mcp_server.py tests/test_dependency_contract.py -q` → `9 passed`.
- Protocol smoke test: launched `mcp_server.py` with `mcp==2.0.0`, exchanged `initialize` and `tools/list`, and verified two valid JSON-RPC stdout frames with six tools and no stderr output.
- `./.venv311/bin/python -m py_compile mcp_server.py` passed.
- `git diff --check` passed.

### Notes

Changed files:
- `mcp_server.py`: added the Hermes-side stdio protocol adapter and HTTP client.
- `mcp-requirements.txt`: pinned MCP adapter dependencies.
- `tests/test_mcp_server.py`: added client, tool-schema, error-mapping, and stderr contract tests.
- `tests/test_dependency_contract.py`: added pinned-dependency coverage for the adapter.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove the stdio adapter; the downloader-side `/api/mcp/` routes remain unchanged.

## 2026-08-24 - Task: Expose explicit pause, resume, and cancel over MCP

### What was done

- Added idempotent MCP pause and resume controls that set the requested download state through the application owner loop.
- Added MCP task cancellation using the same cancellation payload and owner-loop behavior as the Web console.
- Extracted the existing Web cancellation logic into a shared payload helper without changing its response contract.

### Testing

- TDD red: `./.venv311/bin/python -m pytest tests/module/test_mcp_controls.py -q` returned the expected missing-route failures.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_mcp_controls.py tests/test_web_cancel_task.py -q` → `9 passed`.
- MCP regression: `./.venv311/bin/python -m pytest tests/module/test_mcp_controls.py tests/test_web_cancel_task.py tests/module/test_mcp_control.py tests/module/test_mcp_packages.py tests/module/test_mcp_status.py tests/module/test_mcp_submit.py -q` → `27 passed`.
- `./.venv311/bin/python -m black --check module/mcp_control.py module/web.py tests/module/test_mcp_controls.py` passed.
- `git diff --check` passed.
- The repository's existing isort layout check reports pre-existing import-layout differences in `module/mcp_control.py` and `module/web.py`; no broad import reformatting was applied.

### Notes

Changed files:
- `module/mcp_control.py`: added explicit pause, resume, and cancel MCP routes.
- `module/web.py`: extracted the shared cancellation response helper.
- `tests/module/test_mcp_controls.py`: added owner-loop-bound control tests.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove MCP task controls; the Web cancellation endpoint remains available with its existing authentication and CSRF behavior.

## 2026-08-24 - Task: Manage keyword monitors over MCP

### What was done

- Added MCP keyword-monitor list, detail, create, update, delete, history, and recoverable-failure retry endpoints.
- Reused the Web keyword validation and normalization rules, including the required match-keyword rule.
- Preserved immediate monitor triggering after create and update, and routed bulk retry through the channel service owner loop.
- Exposed monitor totals and enabled/disabled counts, plus history progress and durable summaries.

### Testing

- TDD red: `./.venv311/bin/python -m pytest tests/module/test_mcp_keyword_monitors.py -q` returned the expected missing-route failures.
- TDD green: `./.venv311/bin/python -m pytest tests/module/test_mcp_keyword_monitors.py -q` → `4 passed`.
- MCP and Web regression: `./.venv311/bin/python -m pytest tests/module/test_mcp_keyword_monitors.py tests/module/test_channel_library_web.py tests/module/test_mcp_control.py tests/module/test_mcp_packages.py tests/module/test_mcp_status.py tests/module/test_mcp_submit.py tests/module/test_mcp_controls.py tests/test_web_cancel_task.py -q` → `145 passed`.
- `./.venv311/bin/python -m black --check module/mcp_control.py tests/module/test_mcp_keyword_monitors.py` passed.
- `git diff --check` passed.

### Notes

Changed files:
- `module/mcp_control.py`: added keyword-monitor management, history, and retry routes.
- `tests/module/test_mcp_keyword_monitors.py`: added CRUD and retry conflict coverage with a running owner loop.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove MCP keyword-monitor controls; existing Web keyword-monitor routes remain unchanged.

## 2026-08-24 - Task: Document MCP operations and complete acceptance checks

### What was done

- Added `docs/mcp-control.md` with the cross-machine topology, protected Key setup, Hermes stdio configuration, tool/error contracts, resource-delivery rollback path, manual checks, and known deployment risks.
- Added a README_CN entry for Hermes MCP and corrected the resource Bot description to reflect the disabled publishing path.
- Extended the Hermes stdio adapter from the initial six tools to all 16 planned controls, including explicit pause/resume/cancel and complete keyword-monitor operations.
- Added per-monitor progress summaries to MCP list/detail responses so Hermes can see total, enabled/disabled, and queued/downloading/completed/failed/cancelled state.
- Updated the legacy resource-delivery read test to the approved `disabled: true` / HTTP 200 contract.

### Testing

- TDD red for the adapter extension: `./.venv311/bin/python -m pytest tests/test_mcp_server.py -q` failed on the missing control methods and tool definitions.
- TDD green: `./.venv311/bin/python -m pytest tests/test_mcp_server.py tests/test_dependency_contract.py -q` → `10 passed`.
- MCP stdio protocol smoke test with `mcp==2.0.0`: exchanged `initialize` and `tools/list`, verified two valid JSON-RPC stdout frames, 16 advertised tools, and zero stderr bytes.
- TDD red/green for monitor summaries: the new list/detail summary assertion first failed with `KeyError: summary`, then `./.venv311/bin/python -m pytest tests/module/test_mcp_keyword_monitors.py -q` → `4 passed` after the minimal response fix.
- Final full suite: `./.venv311/bin/python -m pytest tests -q` → `787 passed, 1 skipped, 7 failed`.
- The seven remaining failures are pre-existing rclone-argument and comment/package naming-preview expectations; none touch the MCP, Web cancellation, resource-delivery, or keyword-monitor changes.
- `./.venv311/bin/python -m black --check mcp_server.py tests/test_mcp_server.py module/mcp_control.py tests/module/test_mcp_keyword_monitors.py` passed.
- `git diff --check` passed.

### Notes

Changed files:
- `docs/mcp-control.md`: added deployment and operational guidance.
- `README_CN.md`: linked the MCP guide and documented the disabled publishing path.
- `mcp_server.py`: added stdio client methods, dispatch entries, and 10 control/monitor tool schemas.
- `tests/test_mcp_server.py`: added control request and full-tool-set contract coverage.
- `module/mcp_control.py`: added per-monitor status summaries.
- `tests/module/test_mcp_keyword_monitors.py`: asserted list/detail status summaries.
- `tests/module/test_web.py`: synchronized the approved disabled resource-delivery read contract.
- `progress.md`: recorded this task and verification.

Rollback:
- Revert the task commit to remove the MCP documentation and stdio control-tool expansion; the downloader-side routes remain independently revertible by their earlier task commits.

## 2026-08-24 - Deployment: Hermes MCP control to RackNerd

### What was done

- Pushed `codex/hermes-mcp-control` to `origin` and fast-forwarded `origin/master` to commit `e647d6dd3716fd3b936949a85cccf904c8d6bed`.
- Stopped `tg-downloader.service`, created a protected pre-deploy backup, fast-forwarded the RackNerd checkout, enabled `mcp.enabled: true`, generated the missing `/root/telegram_media_downloader/mcp_api_key`, set its mode to `0600`, and restarted the service.
- Kept the existing Web login/session behavior unchanged; MCP uses the independent Bearer Key.

### Testing

- RackNerd service: `active`.
- RackNerd source-local MCP probe: unauthenticated `401`, authenticated `200`.
- Public MCP probe: unauthenticated `401`, authenticated `200`.
- Public package probe returned JSON with `boundary_status` and `downloadable`.
- No key material was printed, logged, or added to the repository.

### Notes

Changed files:
- `/root/telegram_media_downloader`: fast-forwarded to `e647d6dd3716fd3b936949a85cccf904c8d6bed`.
- `/root/telegram_media_downloader/config.yaml`: enabled MCP.
- `/root/telegram_media_downloader/mcp_api_key`: generated protected API Key file, mode `0600`.
- `/root/telegram_media_downloader/backups/mcp-deploy-20260824-090022`: pre-deploy backup.
- `progress.md`: recorded deployment evidence.

Rollback:
- Stop `tg-downloader.service`, restore the recorded pre-deploy commit from `/root/telegram_media_downloader/backups/mcp-deploy-20260824-090022/pre-deploy-commit.txt`, restore the backed-up configuration, and start the service. Disable MCP with `mcp.enabled: false` if only the new control layer needs to be withdrawn.

## 2026-08-31 - Task: 修复 bot 配置持久化失效与评论下载失败静默消失

### What was done

- 修好了「通过 bot 设置的下载过滤器每次重启就丢失」的问题。此前 bot 把配置写进一个叫 `d` 的垃圾文件，启动时却从 `bot.yaml` 读取，于是设置永远存不住，还会在运行目录里堆垃圾文件；`/add_filter` 命令更是把过滤器写进一个根本没人读的属性，用户却收到「设置成功」的回复。现在过滤器能正常存盘并在重启后自动生效。
- 修好了「评论下载失败时任务凭空消失」的问题。此前遇到坏链接、没有权限等扫描失败，程序会一声不响地返回，任务节点永远留在活跃列表里，用户的回复消息一直停在「进行中」直到重启整个服务。现在失败会正常上报状态并释放任务。
- 清理了仓库分支：本地 master 同步到线上，删掉 9 个已完全并入主线的历史分支和 4 个遗留工作目录，仓库只剩 master 与待评估的 `arch-review-remediation`。
- 出具了 2026-07-07 架构评审 27 条整改的主线现状核对清单（`docs/arch-review-followup-2026-08-31.md`）：10 条主线已独立修复，3 条修了一半，本轮修掉 2 条，剩 5 条待排期。

### Testing

- 新增 4 个回归测试，全部走完整 TDD：先确认测试为正确原因失败，再修复至通过。
  - `.venv/bin/python -m pytest tests/module/test_bot_commands.py tests/module/test_download_comments_errors.py -q` → 9 passed。
- 全量测试：`.venv/bin/python -m pytest tests/ -q` → 791 passed, 1 skipped, 7 failed。
- 那 7 个失败为主线既有问题，与本轮无关：已在 stash 掉本轮改动后的干净 master 上复现出完全相同的 7 个，清单记录在 `docs/arch-review-followup-2026-08-31.md` 第七节，待单独排查。
- 未做运行时实测：本地不启动下载服务（需要真实 Telegram 客户端）。

### Notes

Changed files:
- `module/bot.py`: 配置写回 `self.config_path` 而不是字面量文件 `d`；`/add_filter` 写入 `_bot.download_filter` 而不是黑洞属性 `_bot.app.down`。
- `module/download_entry.py`: 删除 `download_comments` 内层吞掉扫描失败的两个 except，让失败落到已有的清理分支。
- `tests/module/test_bot_commands.py`: 新增 2 个测试，覆盖配置存盘路径与 `/add_filter` 的重启往返。
- `tests/module/test_download_comments_errors.py`: 新增文件，覆盖扫描失败必须上报状态并释放 TaskNode。
- `docs/arch-review-followup-2026-08-31.md`: 新增，架构评审 27 条整改的主线现状核对清单。
- `progress.md`: 本条记录。

Rollback:
- 回滚本轮代码：`git revert <本次 commit>`，或 `git checkout f36b828 -- module/bot.py module/download_entry.py`。
- 本轮只改了 3 行源码，不涉及数据格式、接口和部署配置，回滚无副作用。
- 已删除的 9 个历史分支无需回滚：其每一个提交都已在 `f36b828` 中（删除时用的 `git branch -d`，git 会拒绝删除未合并的分支）。

## 2026-08-31 - Task: 部署 bot 配置与评论失败修复到 RackNerd

### What was done

- 把本轮两条修复部署到了线上服务器，服务已重启并正常运行，网站入口可正常访问。
- 部署前确认服务器近 30 分钟没有正在进行的下载，重启没有打断任何任务。
- 部署过程中观察到旧代码在关停瞬间又写了一次垃圾文件 `d`（内容为空过滤器 `download_filter: []`），正好实证了这个 bug：过滤器设置从来没有真正存住过。新代码起来后会改写 `bot.yaml`，`d` 文件不会再产生。

### Testing

- 部署提交：`f36b828` → `308a7b5`（fast-forward）。
- 服务状态：`systemctl is-active tg-downloader.service` → `active`。
- 公网入口：`curl https://tgdn.wyichuan.cc/` → `HTTP 302` 跳转 `/login?next=%2F`。
- 启动日志无 error/traceback（排除掉扫描器打到 web 端口的 400 噪音）。
- 线上代码复核：`module/bot.py:255` 写 `self.config_path`、`module/bot.py:766` 写 `_bot.download_filter`，`download_comments` 内层吞异常的 except 已消失。
- 未做端到端实测：验证 bot 配置往返需要在 Telegram 里实际发 `/add_filter` 并重启服务，本轮以单元测试 + 线上代码复核为准。

### Notes

Changed files:
- `/root/telegram_media_downloader`: fast-forward 到 `308a7b5`。
- `progress.md`: 本条记录。

遗留（未处理，等确认）：
- `/root/telegram_media_downloader/d`：旧代码留下的垃圾文件，内容为空过滤器，全库无任何读取方。可安全删除，本轮未删。

Rollback:
- `ssh rn 'cd /root/telegram_media_downloader && git reset --hard f36b828 && systemctl restart tg-downloader.service'`
- 本轮仅 3 行源码改动，不涉及数据格式、接口和部署配置，回滚无副作用。

## 2026-08-31 - Task: 清理线上垃圾文件并查明 7 个失败测试的根因

### What was done

- 删除了线上服务器遗留的垃圾文件 `d`（内容为空过滤器），删除前已确认内容无价值、全库无任何读取方，修复后也不会再生成。
- 查清了主线上 7 个失败测试的根因：**全部是过期测试，产品代码没有任何问题**。
  - 其中 6 个是「资源包下载直接存到 根目录/资源包名/文件」这个改动造成的。这是 2026-08-16 有意做的功能调整，目的就是去掉频道名和日期那两层前缀目录，但当时没有同步更新测试里写死的期望路径。
  - 剩下 1 个是 rclone 上传加了并发参数后，测试里的期望命令行没跟上。
- 订正了核对清单文档里「需单独排查」的说法，补上完整证据和处理建议。

### Testing

- 二分法定量验证：在 `b4ebf98` 的父提交 `8e827e3` 上跑 `tests/module/test_comment_workflow.py` 与 `tests/test_media_downloader.py` → 144 passed, 0 failed；在 `b4ebf98` 上跑同样两个文件 → 2 failed, 142 passed。证明失败起点就是这次有意的功能调整。
- 逐条比对失败断言：前 3 个用例期望里多出频道名前缀 `zhyseseb/`，后 3 个多出 `Private/2026_06/`，均为该改动有意去掉的层级。
- rclone 用例：实际 argv 比期望多出 `--transfers <n>`，对应 `module/cloud_drive.py` 已支持的 `rclone_transfers` 配置。
- 线上确认：`d` 文件已不存在。
- 本轮未改动任何产品代码，故未重跑全量测试。

### Notes

Changed files:
- `/root/telegram_media_downloader/d`: 已删除（线上垃圾文件）。
- `docs/arch-review-followup-2026-08-31.md`: 第七节改写，从「需单独排查」改为完整根因说明与处理建议。
- `progress.md`: 本条记录。

Rollback:
- 文档改动可用 `git revert <本次 commit>` 撤销。
- `d` 文件无需恢复：内容为 `download_filter: []`，旧代码从不读取它，新代码改用 `bot.yaml`。

## 2026-08-31 - Task: 清理死代码预览构建器，并用多代理审计过期测试

### What was done

- 删掉了两段生产环境根本用不到的代码：评论和资源包的「四选项命名预览」构建器。这套东西早在 2026-06-09 就从界面上撤掉了（现在只保留推荐方案 C），但底层代码和一堆测试一直留着。删掉后代码少了 78 行，测试少了 5 个用例。
- 用 14 个子代理做了一轮过期测试全面审计，每个失败用例都在各自独立的工作区里用二分法定位到底是哪次改动让它开始报红。结论：**当前 7 个报红全部是过期测试，产品代码一个真实缺陷都没有**；另外还查出 1 个被整段注释掉、根本不参与运行的隐藏失效测试。合计 8 个。
- 审计推翻了上一轮的一个判断，这是本轮最有价值的产出：原以为「命名策略 A/B/D」整套都是死代码可以一起删，实际上**枚举成员本身仍在生产运行时被真实使用**——用户 Telegram 聊天记录里那些旧版本发出的按钮永久有效，点一下就会走到这段代码，随后被守卫拒绝。如果按原判断删掉，会悄悄削弱针对陈旧/伪造按钮的防线，还会打掉两条现役回归测试。因此只删了确实零调用的预览构建器，枚举和守卫原样保留。
- 订正了核对清单文档里那条错误判断，并把完整审计结果写进文档第八节，包括剩余 4 个报红各自的确切改法。

### Testing

- 删除前记录基线：`tests/module/test_comment_workflow.py` → 3 failed, 103 passed。
- 删除后该文件：**101 passed, 0 failed**。
- 全量测试：从 7 failed / 791 passed 变为 **4 failed / 789 passed**，无任何新增失败。
- 专门复核审计特别警告的两条防线测试（伪造非推荐策略的回调必须被拒绝）：`-k forged` → 2 passed，未受影响。
- 全仓库检索确认无残留引用：`grep build_naming_previews|build_package_naming_previews` 仅命中 `build_recommended_*` 版本。
- 施工过程中第一次删除脚本的边界判断出错（把类里最后一个方法之后的内容一起切掉），已当场回滚测试文件并改用带尺寸校验的行级切分重做；产品代码那 78 行删除不受影响。

### Notes

Changed files:
- `module/comment_workflow.py`: 删除 `build_naming_previews`、`build_package_naming_previews` 两个零生产调用者的函数（共 78 行）。
- `tests/module/test_comment_workflow.py`: 删除 5 个用例（3 个原本就报红 + 2 个仅服务于被删函数），其余夹具调用切到生产在用的 `build_recommended_*` 版本；5126 行 → 4978 行。
- `docs/arch-review-followup-2026-08-31.md`: 第五节订正「A/B/D 在生产不可达」的错误判断；第七节同步订正；新增第八节记录完整审计结果与剩余 4 个报红的改法。
- `progress.md`: 本条记录。

未处理（有意保留）：
- `NamingStrategy` 的 AUTHOR/CAPTION/MONTH_CAPTION 三个成员，以及 `module/bot.py` 两处 RECOMMENDED 守卫——审计证明仍在生产路径上，不可删。
- `module/comment_workflow.py` 的 `month_for_comment`：既有死代码，与本轮无关，仅在文档中标注。
- 剩余 4 个报红的断言更新：改法已写进文档第八节，等确认后单独一轮做。

Rollback:
- `git revert <本次 commit>`，或 `git checkout b88c10f -- module/comment_workflow.py tests/module/test_comment_workflow.py`。
- 本轮只删代码不改行为，产品逻辑零变更，回滚无副作用。

## 2026-08-31 - Task: 部署死代码清理，并补上 bot 配置修复的端到端验证

### What was done

- 把死代码清理部署到线上，服务重启正常，网站入口可访问。本次改动不含任何行为变更，纯删除无人调用的代码。
- **补上了之前缺的端到端验证**：这次重启的关停流程跑的已经是修复后的代码，线上实际产物证明修复生效——不再生成垃圾文件 `d`，配置正确写进了 `bot.yaml`。之前那条「未做端到端实测」的缺口就此关闭。

### Testing

- 部署提交：`b88c10f` → `76b9e28`（fast-forward）。部署前确认服务器近 20 分钟无下载活动。
- 服务状态：`active`；公网入口 `curl https://tgdn.wyichuan.cc/` → `HTTP 302` 跳转 `/login?next=%2F`。
- 端到端验证 P0-4（bot 配置持久化）：重启后线上 `ls d` → 不存在；`ls -la bot.yaml` → 存在，时间戳为本次关停时刻，内容为 `download_filter: []`。即配置已按修复后的路径正确落盘。

### Notes

Changed files:
- `/root/telegram_media_downloader`: fast-forward 到 `76b9e28`。
- `/root/telegram_media_downloader/bot.yaml`: 由修复后的代码在关停时自动生成（预期行为）。
- `progress.md`: 本条记录。

Rollback:
- `ssh rn 'cd /root/telegram_media_downloader && git reset --hard b88c10f && systemctl restart tg-downloader.service'`
- 本次部署无行为变更，回滚无实际影响。

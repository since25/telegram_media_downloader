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

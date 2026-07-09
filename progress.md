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

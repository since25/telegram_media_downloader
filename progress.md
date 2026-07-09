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

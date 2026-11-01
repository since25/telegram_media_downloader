## What was done

- Added project-level deployment guidance limiting RackNerd `.bak` files and backup directories to two.
- Recorded the required download-file lifecycle invariants for `temp/` and completed files under `save_path`.
- Audited the current cleanup paths: resource delivery removes per-group files and its job directory in `finally`; channel-library cleanup removes failed/cancelled sources, while upload-success cleanup depends on `after_upload_file_delete` and does not provide a startup sweep for orphaned completed files.
- Fixed the terminal download cleanup gap: the final failed or externally cancelled transfer now removes its own temporary path, preventing the last retry's partial file from remaining under `temp/`.
- Added startup reconciliation that empties the idle temp root and removes only persisted `uploaded` sources inside `save_path` when deletion is enabled; failed or unknown files remain available for inspection/retry.
- Changed cloud upload lifecycle handling to defer local deletion until the successful upload state has been persisted, so restart reconciliation can finish cleanup after a process interruption.
- Added `scripts/deploy_rn.sh` and `docs/deployment-rn.md` for RN backup rotation, SQLite integrity checks, service restart, post-deploy checks, and rollback. The script retains at most two `*.bak` backups and requires explicit `TMD_CONFIRM_DEPLOY=YES`.
- Added bounded storage metrics to the Web and MCP system status endpoints: temp/save_path bytes and file counts plus scan failures, cached for 15 seconds.
- Displayed the temp and save_path storage details in the existing Web system monitor card.

## Testing

- Read-only inspection of `module/resource_delivery.py`, `module/channel_library_service.py`, `module/download_transfer.py`, `module/cloud_drive.py`, deployment documentation, and cleanup tests.
- `./.venv/bin/python -m pytest tests/module/test_package_download.py tests/module/test_media_session_recovery.py -q` → 13 passed.
- `bash -n scripts/deploy_rn.sh` passed.
- `./scripts/deploy_rn.sh` without `TMD_CONFIRM_DEPLOY=YES` exited with code 2 and made no changes.
- `./.venv/bin/python -m pytest tests/module/test_file_cleanup.py tests/module/test_upload_deletion_boundary.py tests/module/test_cloud_drive.py tests/module/test_package_download.py tests/module/test_media_session_recovery.py -q` → 23 passed.
- `./.venv/bin/python -m pytest tests/module/test_resource_delivery.py tests/test_channel_library_download.py tests/module/test_download_lifecycle.py tests/module/test_app.py tests/module/test_web.py -q` → 116 passed.
- `./.venv/bin/python -m pytest tests/ -q` → 858 passed, 1 skipped.
- `./.venv/bin/python -m pytest tests/module/test_task_page_ui.py tests/test_web_system_api.py tests/module/test_mcp_status.py -q` → 13 passed.
- Mypy for the four changed runtime modules (`file_cleanup`, `download_runtime`, `cloud_drive`, `download_lifecycle`) passed. The broader command including the pre-existing `channel_library_service.py` reports 20 existing typing errors in that file; none are on the new cleanup lines.
- Mypy including `web.py`/`mcp_control.py` reports the repository's existing Web typing errors; the new storage metric code adds no reported error in `file_cleanup.py`.
- `git diff --check` passed.

## Notes

Changed files:
- `AGENTS.md`
- `README_CN.md`
- `docs/deployment-rn.md`
- `scripts/deploy_rn.sh`
- `module/file_cleanup.py`
- `module/download_runtime.py`
- `module/cloud_drive.py`
- `module/download_lifecycle.py`
- `module/channel_library_service.py`
- `tests/module/test_file_cleanup.py`
- `tests/module/test_upload_deletion_boundary.py`
- `tests/module/test_mcp_status.py`
- `tests/test_web_system_api.py`
- `module/templates/index.html`
- `module/download_transfer.py`
- `tests/module/test_package_download.py`
- `progress/2026-11-01-disk-retention-audit.md`

Rollback:
- Remove the added `AGENTS.md` and this progress entry/file.

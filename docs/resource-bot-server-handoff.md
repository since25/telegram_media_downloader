# Resource Bot Server Handoff

This checklist begins after the reviewed code is present on the production server. It
does not contain the real Bot token and was not executed during local implementation.

## Configuration delta

Keep the existing management Bot token and add exactly one sibling setting to the
production `config.yaml`:

```yaml
bot_token: existing_management_bot_token
resource_bot_token: new_resource_bot_token
```

Do not copy `.env.new` to the server or make the application load it. Read the value
locally and enter it directly into the protected production `config.yaml`. Do not paste
the token into shell history, logs, tests, commits, or this document.

The two Telegram accounts have different roles:

- Management Bot: existing download/administration commands plus
  `/create_resource_key` and `/revoke_resource_user`.
- Resource Bot: `/activate`, `/status`, `/bind`, `/channel`, `/unbind`, and `/search`.

Both are owned by the existing single application service. The resource Bot cannot be
configured without the management Bot.

## Pre-deployment backup

Run from the production checkout. Confirm the directory and service name before
continuing:

```bash
cd /root/telegram_media_downloader
pwd
systemctl status tg-downloader.service --no-pager
git status --short --branch
```

Stop the service before backing up mutable state:

```bash
systemctl stop tg-downloader.service
systemctl is-active tg-downloader.service
```

Create a restricted release backup directory. Replace the timestamp if necessary:

```bash
install -d -m 700 backups/resource-bot-20260729
cp -a config.yaml backups/resource-bot-20260729/config.yaml
cp -a sessions backups/resource-bot-20260729/sessions
git rev-parse HEAD > backups/resource-bot-20260729/pre-deploy-commit.txt
chmod 600 backups/resource-bot-20260729/config.yaml
```

Back up each existing SQLite database with the SQLite backup API:

```bash
.venv/bin/python - <<'PY'
import sqlite3
from pathlib import Path

root = Path("/root/telegram_media_downloader")
backup = root / "backups" / "resource-bot-20260729"
for name in ("channel_library.sqlite3", "web_tasks.sqlite3", "resource_bot.sqlite3"):
    source = root / name
    if not source.exists():
        continue
    target = backup / name
    with sqlite3.connect(source) as source_db, sqlite3.connect(target) as target_db:
        source_db.backup(target_db)
    target.chmod(0o600)
    with sqlite3.connect(target) as check_db:
        result = check_db.execute("PRAGMA integrity_check").fetchone()[0]
    print(name, result)
PY
```

Every printed integrity result must be `ok`. Do not continue from an unclean worktree or
an unverified backup.

## Code and configuration preflight

Update the checkout to the reviewed commit using the normal release procedure, then
verify Python imports and dependencies:

```bash
.venv/bin/python check_imports.py
.venv/bin/python -m py_compile \
  module/app.py module/bot.py module/download_runtime.py \
  module/resource_bot_store.py module/resource_bot.py module/resource_delivery.py
.venv/bin/pip check
```

Edit `config.yaml` with a protected editor and add `resource_bot_token`. Then verify only
that both keys exist and are non-empty without printing either value:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from ruamel.yaml import YAML

config = YAML(typ="safe").load(Path("config.yaml").read_text(encoding="utf-8"))
for key in ("bot_token", "resource_bot_token"):
    value = str(config.get(key) or "")
    print(key, "configured" if value else "missing")
PY
```

Initialize and validate the independent resource database before the service starts:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from module.resource_bot_store import ResourceBotStore

store = ResourceBotStore(Path("resource_bot.sqlite3"))
store.initialize()
with store.connect() as connection:
    print("schema", connection.execute("PRAGMA user_version").fetchone()[0])
    print("integrity", connection.execute("PRAGMA integrity_check").fetchone()[0])
PY
stat -c '%A %n' resource_bot.sqlite3 2>/dev/null || stat -f '%Sp %N' resource_bot.sqlite3
```

Expected values are schema `2`, integrity `ok`, and owner-only file permissions.

## Start and service checks

```bash
systemctl start tg-downloader.service
systemctl is-active tg-downloader.service
systemctl status tg-downloader.service --no-pager
journalctl -u tg-downloader.service --since "10 minutes ago" --no-pager
```

The service must be `active`. The journal must show both Bot clients and the delivery
worker starting without traceback, authentication failure, duplicate session, database,
or Handler errors. Confirm the existing Web login and channel-library pages still work
before creating a live resource delivery.

## Live Telegram acceptance

Perform these steps with a disposable activation key and a controlled target channel:

1. In the management Bot private chat, run `/create_resource_key`.
2. In the resource Bot private chat, run `/activate <key>`.
3. Run `/status`; confirm the user is activated and no channel is bound.
4. Run `/bind`.
5. Add only the resource Bot to the controlled target channel. Make it an administrator
   with permission to publish messages. The backend main account does not need to join.
6. Confirm the resource Bot privately reports the successful channel binding. Run
   `/channel` and verify the title/ID.
7. Run `/search <known keyword>` and confirm only stable indexed packages appear, five
   per page, with source, date, media count, size, and publish buttons.
8. Publish a one-file package. Confirm the task is queued, the main account downloads the
   source, and the resource Bot uploads it to the target channel.
9. Publish a known photo/video album. Confirm ordering and album grouping are preserved.
10. Click one publish button twice. Confirm only one persistent delivery job is created.
11. Temporarily remove the resource Bot's publish permission. Confirm publishing is
    refused and the binding becomes permission-lost; restore permission and bind again.
12. Run `/revoke_resource_user <telegram_user_id>` in the management Bot and confirm new
    searches/publishes are rejected.

Inspect state without exposing activation hashes or tokens:

```bash
.venv/bin/python - <<'PY'
import sqlite3

with sqlite3.connect("resource_bot.sqlite3") as db:
    print("integrity", db.execute("PRAGMA integrity_check").fetchone()[0])
    print(
        "jobs",
        db.execute(
            "SELECT status, COUNT(*) FROM resource_delivery_jobs GROUP BY status"
        ).fetchall(),
    )
PY
```

If a delivery fails after one or more items were uploaded, treat it as a partial
publication. Do not retry automatically; inspect the target channel and choose a manual
cleanup/republication action to avoid duplicates.

## Rollback

For a code/configuration rollback:

1. Stop `tg-downloader.service`.
2. Preserve the current `resource_bot.sqlite3`, `channel_library.sqlite3`,
   `web_tasks.sqlite3`, `config.yaml`, and sessions as a new rollback point.
3. Return the checkout to the recorded pre-deploy commit using the normal non-destructive
   release procedure.
4. Restore the backed-up `config.yaml`, or remove only `resource_bot_token` while keeping
   the existing `bot_token`.
5. Restart the service and verify the original management Bot and Web/channel-library
   flows.

The prior code does not use `resource_bot.sqlite3`, so it can remain preserved on disk.
Do not delete it during an ordinary rollback. Restore a database backup only for
confirmed corruption or an incompatible schema problem, with the service stopped and the
current files retained first.

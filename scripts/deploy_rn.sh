#!/usr/bin/env bash
set -Eeuo pipefail

# Run this script from the production checkout on RN after the reviewed commit
# has been pulled. It deliberately does not pull code or print configuration.

ROOT_DIR="${TMD_ROOT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
SERVICE_NAME="${TMD_SERVICE_NAME:-tg-downloader.service}"
BACKUP_ROOT="${TMD_BACKUP_ROOT:-${ROOT_DIR}/backups}"
MAX_BACKUPS=2

if [[ "${TMD_CONFIRM_DEPLOY:-}" != "YES" ]]; then
  echo "Refusing deployment: set TMD_CONFIRM_DEPLOY=YES after checking "
  echo "the checkout and service."
  exit 2
fi

cd "${ROOT_DIR}"
if [[ ! -f config.yaml ]]; then
  echo "Missing config.yaml in ${ROOT_DIR}" >&2
  exit 1
fi

git status --short --branch
install -d -m 700 "${BACKUP_ROOT}"

backup_name="deploy-$(date -u +%Y%m%dT%H%M%SZ)-$(git rev-parse --short HEAD).bak"
backup_dir="${BACKUP_ROOT}/${backup_name}"
service_started=0

cleanup_on_error() {
  if [[ "${service_started}" -eq 0 ]]; then
    systemctl start "${SERVICE_NAME}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_on_error ERR

systemctl stop "${SERVICE_NAME}"
if systemctl is-active --quiet "${SERVICE_NAME}"; then
  echo "Service did not stop: ${SERVICE_NAME}" >&2
  exit 1
fi

install -d -m 700 "${backup_dir}"
cp -a config.yaml "${backup_dir}/config.yaml"
if [[ -d sessions ]]; then
  cp -a sessions "${backup_dir}/sessions"
fi
git rev-parse HEAD > "${backup_dir}/pre-deploy-commit.txt"
chmod 600 "${backup_dir}/config.yaml" "${backup_dir}/pre-deploy-commit.txt"

BACKUP_DIR="${backup_dir}" ROOT_DIR="${ROOT_DIR}" \
  .venv/bin/python - <<'PY'
import os
import sqlite3
from pathlib import Path

root = Path(os.environ["ROOT_DIR"])
backup = Path(os.environ["BACKUP_DIR"])
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
    if result != "ok":
        raise SystemExit(f"{name}: integrity_check={result}")
    print(f"{name}: integrity_check=ok")
PY

mapfile -t backups < <(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 \
  \( -type f -o -type d \) -name '*.bak' -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-)
if (( ${#backups[@]} > MAX_BACKUPS )); then
  for old_backup in "${backups[@]:MAX_BACKUPS}"; do
    rm -rf -- "${old_backup}"
  done
fi

remaining_count=$(find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 \
  \( -type f -o -type d \) -name '*.bak' -print | wc -l | tr -d ' ')
if (( remaining_count > MAX_BACKUPS )); then
  echo "Backup rotation failed: ${remaining_count} backups remain" >&2
  exit 1
fi

systemctl start "${SERVICE_NAME}"
service_started=1
systemctl is-active --quiet "${SERVICE_NAME}"
trap - ERR
echo "Deployment checks passed; retained backups: ${remaining_count}"

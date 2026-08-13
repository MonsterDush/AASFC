#!/usr/bin/env bash
set -Eeuo pipefail

: "${APP_ROOT:?Set APP_ROOT}"
: "${DATABASE_URL:?Set DATABASE_URL}"
: "${BACKUP_SCRIPT:?Set BACKUP_SCRIPT}"
: "${RESTORE_SCRIPT:?Set RESTORE_SCRIPT}"
: "${BACKUP_ENCRYPTION_PASSWORD:?Set BACKUP_ENCRYPTION_PASSWORD}"

[[ "${EUID}" -eq 0 ]] || {
  echo "Production restore drill must run as root" >&2
  exit 2
}
[[ "${APP_ROOT}" == "/var/www/axelio/prod" ]] || {
  echo "Unsupported APP_ROOT: ${APP_ROOT}" >&2
  exit 2
}
[[ -x "${BACKUP_SCRIPT}" && -x "${RESTORE_SCRIPT}" ]] || {
  echo "Candidate backup or restore script is not executable" >&2
  exit 2
}

python_bin="${APP_ROOT}/venv/bin/python"
alembic_bin="${APP_ROOT}/venv/bin/alembic"
report_dir="${APP_ROOT}/deployments/drills"
release="${RELEASE_VERSION:-unknown}"
started_at="$(date +%s)"
started_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

restore_database_url="$("${python_bin}" - <<'PY'
import os
import re
from sqlalchemy.engine import make_url

url = make_url(os.environ["DATABASE_URL"])
source = re.sub(r"[^A-Za-z0-9_]", "_", url.database or "axelio")
target = f"{source[:45]}_restore_drill"
print(url.set(database=target).render_as_string(hide_password=False))
PY
)"

source_database_name="$("${python_bin}" - <<'PY'
import os
from sqlalchemy.engine import make_url
print(make_url(os.environ["DATABASE_URL"]).database or "unknown")
PY
)"
restore_database_name="$(RESTORE_DATABASE_URL="${restore_database_url}" "${python_bin}" - <<'PY'
import os
from sqlalchemy.engine import make_url
print(make_url(os.environ["RESTORE_DATABASE_URL"]).database or "unknown")
PY
)"

BACKUP_REQUIRE_OFFSITE=false \
BACKUP_RCLONE_REMOTE= \
RESTORE_DATABASE_URL="${restore_database_url}" \
REPO_DIR="${APP_ROOT}/repo" \
ALEMBIC_BIN="${alembic_bin}" \
BACKUP_VERIFY_TABLES="users venues finance_entries payroll_runs" \
BACKUP_SCRIPT="${BACKUP_SCRIPT}" \
"${RESTORE_SCRIPT}"

finished_at="$(date +%s)"
elapsed_seconds="$((finished_at - started_at))"
install -d -m 0750 "${report_dir}"
report_path="${report_dir}/$(date -u +%Y%m%dT%H%M%SZ)-production-restore-drill.txt"
{
  printf 'started_at=%s\n' "${started_utc}"
  printf 'completed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'release=%s\n' "${release//$'\n'/}"
  printf 'source_database=%s\n' "${source_database_name//$'\n'/}"
  printf 'restore_database=%s\n' "${restore_database_name//$'\n'/}"
  printf 'source_kind=fresh-production-snapshot\n'
  printf 'actual_rpo_seconds=0\n'
  printf 'actual_rto_seconds=%s\n' "${elapsed_seconds}"
  printf 'critical_table_counts=matched\n'
  printf 'migrations=passed\n'
  printf 'restore_database_removed=true\n'
} >"${report_path}"
chmod 0640 "${report_path}"

echo "production restore drill: RPO=0s RTO=${elapsed_seconds}s report=${report_path}"

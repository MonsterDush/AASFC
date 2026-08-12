#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?Set DATABASE_URL}"
: "${RESTORE_DATABASE_URL:?Set RESTORE_DATABASE_URL}"
: "${BACKUP_ENCRYPTION_PASSWORD:?Set BACKUP_ENCRYPTION_PASSWORD}"

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
backup_script="${BACKUP_SCRIPT:-${repo_dir}/ops/backup/postgres-backup.sh}"
if [[ -n "${ALEMBIC_BIN:-}" ]]; then
  alembic_bin="${ALEMBIC_BIN}"
elif [[ -x "${repo_dir}/backend/.venv/bin/alembic" ]]; then
  alembic_bin="${repo_dir}/backend/.venv/bin/alembic"
elif command -v alembic >/dev/null 2>&1; then
  alembic_bin="$(command -v alembic)"
else
  alembic_bin=""
fi
keep_restore_database="${KEEP_RESTORE_DATABASE:-false}"
verify_tables="${BACKUP_VERIFY_TABLES:-users venues finance_entries payroll_runs}"
source_database_url="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
source_database_url="${source_database_url/postgresql+psycopg2:/postgresql:}"
restore_database_url="${RESTORE_DATABASE_URL/postgresql+psycopg:/postgresql:}"
restore_database_url="${restore_database_url/postgresql+psycopg2:/postgresql:}"

for command_name in psql pg_restore openssl; do
  command -v "${command_name}" >/dev/null || {
    echo "Missing restore dependency: ${command_name}" >&2
    exit 2
  }
done

if command -v sha256sum >/dev/null; then
  checksum_check() { sha256sum --check "$1"; }
elif command -v shasum >/dev/null; then
  checksum_check() { shasum -a 256 -c "$1"; }
else
  echo "Missing restore dependency: sha256sum or shasum" >&2
  exit 2
fi

restore_without_query="${restore_database_url%%\?*}"
restore_query=""
if [[ "${restore_database_url}" == *\?* ]]; then
  restore_query="?${restore_database_url#*\?}"
fi
restore_database_name="${restore_without_query##*/}"
restore_admin_url="${restore_without_query%/*}/postgres${restore_query}"
source_without_query="${source_database_url%%\?*}"
source_name="${source_without_query##*/}"

if [[ ! "${restore_database_name}" =~ ^[A-Za-z_][A-Za-z0-9_]*_restore_drill$ ]]; then
  echo "RESTORE_DATABASE_URL database name must end with _restore_drill" >&2
  exit 2
fi
if [[ "${source_name}" == "${restore_database_name}" ]]; then
  echo "Restore drill target must differ from source database" >&2
  exit 2
fi

tmp_dir="$(mktemp -d /tmp/axelio-restore-drill.XXXXXX)"
started_at="$(date +%s)"
database_created=0

cleanup() {
  if [[ "${database_created}" == "1" && "${keep_restore_database}" != "true" ]]; then
    psql "${restore_admin_url}" -v ON_ERROR_STOP=1 -v db_name="${restore_database_name}" <<'SQL' >/dev/null
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'db_name' AND pid <> pg_backend_pid();
SELECT format('DROP DATABASE IF EXISTS %I', :'db_name') \gexec
SQL
  fi
  rm -rf -- "${tmp_dir}"
}
trap cleanup EXIT

encrypted_path="$(BACKUP_DIR="${tmp_dir}/backups" \
  BACKUP_REQUIRE_OFFSITE=false \
  BACKUP_RCLONE_REMOTE= \
  "${backup_script}")"

checksum_check "${encrypted_path}.sha256"
archive_path="${tmp_dir}/restore.dump"
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -pass env:BACKUP_ENCRYPTION_PASSWORD \
  -in "${encrypted_path}" \
  -out "${archive_path}"
pg_restore --list "${archive_path}" >/dev/null

psql "${restore_admin_url}" -v ON_ERROR_STOP=1 -v db_name="${restore_database_name}" <<'SQL' >/dev/null
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :'db_name' AND pid <> pg_backend_pid();
SELECT format('DROP DATABASE IF EXISTS %I', :'db_name') \gexec
SELECT format('CREATE DATABASE %I', :'db_name') \gexec
SQL
database_created=1

pg_restore \
  --exit-on-error \
  --no-owner \
  --no-privileges \
  --dbname="${restore_database_url}" \
  "${archive_path}"
  
(
  cd "${repo_dir}/backend"

  if [[ -n "${alembic_bin}" ]]; then
    echo "Restore drill Alembic: ${alembic_bin}"
    "${alembic_bin}" --version
    DATABASE_URL="${RESTORE_DATABASE_URL}" "${alembic_bin}" upgrade head
  else
    echo "Restore drill Alembic: python -m alembic"
    python -m alembic --version
    DATABASE_URL="${RESTORE_DATABASE_URL}" python -m alembic upgrade head
  fi
)

for table in ${verify_tables}; do
  [[ "${table}" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || {
    echo "Unsafe table name in BACKUP_VERIFY_TABLES: ${table}" >&2
    exit 2
  }
  source_count="$(psql "${source_database_url}" -Atqc "SELECT count(*) FROM \"${table}\"")"
  restored_count="$(psql "${restore_database_url}" -Atqc "SELECT count(*) FROM \"${table}\"")"
  if [[ "${source_count}" != "${restored_count}" ]]; then
    echo "Restore mismatch for ${table}: source=${source_count}, restored=${restored_count}" >&2
    exit 1
  fi
done

elapsed_seconds="$(( $(date +%s) - started_at ))"
echo "restore drill: ${restore_database_name} verified in ${elapsed_seconds}s"

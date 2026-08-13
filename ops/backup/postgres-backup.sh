#!/usr/bin/env bash
set -euo pipefail

: "${DATABASE_URL:?Set DATABASE_URL}"
: "${BACKUP_ENCRYPTION_PASSWORD:?Set BACKUP_ENCRYPTION_PASSWORD}"
: "${BACKUP_DIR:?Set BACKUP_DIR}"

backup_dir="${BACKUP_DIR%/}"
require_offsite="${BACKUP_REQUIRE_OFFSITE:-true}"
rclone_remote="${BACKUP_RCLONE_REMOTE:-}"
release="${RELEASE_VERSION:-unknown}"
monitoring_state_dir="${MONITORING_STATE_DIR:-}"
database_url="${DATABASE_URL/postgresql+psycopg:/postgresql:}"
database_url="${database_url/postgresql+psycopg2:/postgresql:}"

case "${backup_dir}" in
  /var/backups/axelio/* | /tmp/axelio-*) ;;
  *)
    echo "BACKUP_DIR must be a dedicated Axelio path, got: ${backup_dir}" >&2
    exit 2
    ;;
esac

for command_name in pg_dump pg_restore openssl; do
  command -v "${command_name}" >/dev/null || {
    echo "Missing backup dependency: ${command_name}" >&2
    exit 2
  }
done

if command -v sha256sum >/dev/null; then
  checksum_write() { sha256sum "$1"; }
elif command -v shasum >/dev/null; then
  checksum_write() { shasum -a 256 "$1"; }
else
  echo "Missing backup dependency: sha256sum or shasum" >&2
  exit 2
fi

if [[ "${require_offsite}" == "true" ]]; then
  [[ -n "${rclone_remote}" ]] || {
    echo "BACKUP_RCLONE_REMOTE is required for offsite production backups" >&2
    exit 2
  }
  command -v rclone >/dev/null || {
    echo "rclone is required for offsite production backups" >&2
    exit 2
  }
fi

umask 077
daily_dir="${backup_dir}/daily"
weekly_dir="${backup_dir}/weekly"
mkdir -p "${daily_dir}" "${weekly_dir}"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
safe_release="$(printf '%s' "${release}" | tr -cd 'A-Za-z0-9._-' | cut -c1-48)"
safe_release="${safe_release:-unknown}"
base_name="axelio-${timestamp}-${safe_release}.dump.enc"
encrypted_path="${daily_dir}/${base_name}"
archive_path="$(mktemp "${backup_dir}/.axelio-backup.XXXXXX.dump")"
encrypted_tmp="$(mktemp "${backup_dir}/.axelio-encrypted.XXXXXX")"
verify_path="$(mktemp "${backup_dir}/.axelio-verify.XXXXXX.dump")"

cleanup() {
  rm -f -- "${archive_path}" "${encrypted_tmp}" "${verify_path}"
}
trap cleanup EXIT

pg_dump \
  --format=custom \
  --compress=6 \
  --no-owner \
  --no-privileges \
  --file="${archive_path}" \
  "${database_url}"
pg_restore --list "${archive_path}" >/dev/null

openssl enc -aes-256-cbc -salt -pbkdf2 -iter 200000 \
  -pass env:BACKUP_ENCRYPTION_PASSWORD \
  -in "${archive_path}" \
  -out "${encrypted_tmp}"
mv "${encrypted_tmp}" "${encrypted_path}"

checksum_write "${encrypted_path}" >"${encrypted_path}.sha256"
{
  printf 'created_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'release=%s\n' "${release//$'\n'/}"
  printf 'encrypted_file=%s\n' "${base_name}"
  printf 'format=postgres-custom+openssl-aes-256-cbc-pbkdf2\n'
} >"${encrypted_path}.metadata"

openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 \
  -pass env:BACKUP_ENCRYPTION_PASSWORD \
  -in "${encrypted_path}" \
  -out "${verify_path}"
pg_restore --list "${verify_path}" >/dev/null

if [[ "$(date -u +%u)" == "7" ]]; then
  cp "${encrypted_path}" "${weekly_dir}/${base_name}"
  cp "${encrypted_path}.sha256" "${weekly_dir}/${base_name}.sha256"
  cp "${encrypted_path}.metadata" "${weekly_dir}/${base_name}.metadata"
fi

if [[ -n "${rclone_remote}" ]]; then
  remote_base="${rclone_remote%/}"
  rclone copyto "${encrypted_path}" "${remote_base}/daily/${base_name}"
  rclone copyto "${encrypted_path}.sha256" "${remote_base}/daily/${base_name}.sha256"
  rclone copyto "${encrypted_path}.metadata" "${remote_base}/daily/${base_name}.metadata"
  rclone check "${encrypted_path}" "${remote_base}/daily/${base_name}" --one-way
  if [[ "$(date -u +%u)" == "7" ]]; then
    rclone copyto "${weekly_dir}/${base_name}" "${remote_base}/weekly/${base_name}"
    rclone copyto "${weekly_dir}/${base_name}.sha256" "${remote_base}/weekly/${base_name}.sha256"
    rclone copyto "${weekly_dir}/${base_name}.metadata" "${remote_base}/weekly/${base_name}.metadata"
  fi
fi

find "${daily_dir}" -type f -mtime +7 -delete
find "${weekly_dir}" -type f -mtime +28 -delete

if [[ -n "${monitoring_state_dir}" ]]; then
  case "${monitoring_state_dir}" in
    /var/lib/axelio-monitoring | /tmp/axelio-monitoring-*) ;;
    *)
      echo "Unsupported MONITORING_STATE_DIR: ${monitoring_state_dir}" >&2
      exit 2
      ;;
  esac
  install -d -m 0755 "${monitoring_state_dir}"
  timestamp_tmp="$(mktemp "${monitoring_state_dir}/.backup-success.XXXXXX")"
  printf '%s\n' "$(date +%s)" >"${timestamp_tmp}"
  chmod 0644 "${timestamp_tmp}"
  mv "${timestamp_tmp}" "${monitoring_state_dir}/backup-last-success.timestamp"
fi

printf '%s\n' "${encrypted_path}"

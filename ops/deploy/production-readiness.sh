#!/usr/bin/env bash
set -euo pipefail

: "${PROD_APP_ROOT:?Set PROD_APP_ROOT}"
: "${RELEASE_SHA:?Set RELEASE_SHA}"
: "${BACKUP_SCRIPT:?Set BACKUP_SCRIPT}"

[[ "${EUID}" == "0" ]] || {
  echo "Production readiness must run as root" >&2
  exit 2
}
[[ "${PROD_APP_ROOT}" == "/var/www/axelio/prod" ]] || {
  echo "Unsupported production root: ${PROD_APP_ROOT}" >&2
  exit 2
}
[[ "${RELEASE_SHA}" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Expected a full release SHA" >&2
  exit 2
}
[[ -x "${BACKUP_SCRIPT}" ]] || {
  echo "Candidate backup script is not executable: ${BACKUP_SCRIPT}" >&2
  exit 2
}

backend_env="${PROD_APP_ROOT}/repo/backend/.env"
backup_env="/etc/axelio/backup-prod.env"
backup_dir="/var/backups/axelio/prod"

for env_path in "${backend_env}" "${backup_env}"; do
  [[ -f "${env_path}" ]] || {
    echo "Missing production configuration: ${env_path}" >&2
    exit 1
  }
done

backup_mode="$(stat -c '%a' "${backup_env}")"
if (( (8#${backup_mode}) & 8#077 )); then
  echo "${backup_env} must not be readable by group or others" >&2
  exit 1
fi

has_nonempty_setting() {
  local env_path="$1"
  local key="$2"
  awk -v key="${key}" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" {
      value = $0
      sub("^[[:space:]]*" key "[[:space:]]*=[[:space:]]*", "", value)
      sub(/[[:space:]]+$/, "", value)
      if (value != "" && value != "\"\"" && value != "\047\047") found = 1
    }
    END { exit(found ? 0 : 1) }
  ' "${env_path}"
}

has_nonempty_setting "${backend_env}" SENTRY_DSN || {
  echo "SENTRY_DSN is missing from the production backend environment" >&2
  exit 1
}
has_nonempty_setting "${backend_env}" BOT_SERVICE_URL || {
  echo "BOT_SERVICE_URL is missing from the production backend environment" >&2
  exit 1
}
has_nonempty_setting "${backend_env}" BOT_SERVICE_SECRET || {
  echo "BOT_SERVICE_SECRET is missing from the production backend environment" >&2
  exit 1
}
if ! has_nonempty_setting "${backend_env}" AXELIO_ALERT_TG_CHAT_IDS && \
   ! has_nonempty_setting "${backend_env}" SUPER_ADMIN_TG_USER_IDS; then
  echo "AXELIO_ALERT_TG_CHAT_IDS or SUPER_ADMIN_TG_USER_IDS is required for production alerts" >&2
  exit 1
fi
has_nonempty_setting "${backup_env}" BACKUP_ENCRYPTION_PASSWORD || {
  echo "BACKUP_ENCRYPTION_PASSWORD is missing from the production backup environment" >&2
  exit 1
}
has_nonempty_setting "${backup_env}" BACKUP_RCLONE_REMOTE || {
  echo "BACKUP_RCLONE_REMOTE is missing from the production backup environment" >&2
  exit 1
}

for command_name in systemd-run pg_dump pg_restore openssl rclone; do
  command -v "${command_name}" >/dev/null || {
    echo "Missing production backup dependency: ${command_name}" >&2
    exit 1
  }
done

install -d -m 0700 "${backup_dir}"
unit_name="axelio-prod-readiness-${RELEASE_SHA:0:12}"
systemd-run \
  --unit="${unit_name}" \
  --wait \
  --collect \
  --pipe \
  --property=Type=oneshot \
  --property="WorkingDirectory=${PROD_APP_ROOT}/repo" \
  --property="EnvironmentFile=${backend_env}" \
  --property="EnvironmentFile=${backup_env}" \
  --property="Environment=BACKUP_DIR=${backup_dir}" \
  --property=Environment=BACKUP_REQUIRE_OFFSITE=true \
  --property="Environment=RELEASE_VERSION=${RELEASE_SHA}" \
  "${BACKUP_SCRIPT}"

echo "Production readiness passed for ${RELEASE_SHA}: Sentry configured and encrypted offsite backup verified"

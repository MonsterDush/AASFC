#!/usr/bin/env bash
set -Eeuo pipefail

: "${PROD_APP_ROOT:?Set PROD_APP_ROOT}"
: "${RELEASE_SHA:?Set RELEASE_SHA}"
: "${DRILL_TOOL_DIR:?Set DRILL_TOOL_DIR}"

mode="${DRILL_MODE:-all}"
phase="${1:-orchestrate}"

[[ "${EUID}" -eq 0 ]] || {
  echo "Production assurance drill must run as root" >&2
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
[[ "${mode}" == "all" || "${mode}" == "restore" || "${mode}" == "observability" ]] || {
  echo "DRILL_MODE must be all, restore or observability" >&2
  exit 2
}

if [[ "${phase}" == "orchestrate" ]]; then
  unit_name="axelio-prod-assurance-${RELEASE_SHA:0:12}-$(date +%s)"
  exec systemd-run \
    --unit="${unit_name}" \
    --wait \
    --collect \
    --pipe \
    --property=Type=oneshot \
    --property="WorkingDirectory=${PROD_APP_ROOT}/repo" \
    --property="EnvironmentFile=${PROD_APP_ROOT}/repo/backend/.env" \
    --property=EnvironmentFile=/etc/axelio/backup-prod.env \
    --property="Environment=PROD_APP_ROOT=${PROD_APP_ROOT}" \
    --property="Environment=RELEASE_SHA=${RELEASE_SHA}" \
    --property="Environment=DRILL_TOOL_DIR=${DRILL_TOOL_DIR}" \
    --property="Environment=DRILL_MODE=${mode}" \
    --property="Environment=APP_ROOT=${PROD_APP_ROOT}" \
    --property=Environment=API_BASE_URL=https://api.axelio.ru \
    --property=Environment=API_SERVICE=axelio-api-prod \
    "${DRILL_TOOL_DIR}/production-assurance-drill.sh" execute
fi

[[ "${phase}" == "execute" ]] || {
  echo "Unknown drill phase: ${phase}" >&2
  exit 2
}

if [[ "${mode}" == "all" || "${mode}" == "restore" ]]; then
  APP_ROOT="${PROD_APP_ROOT}" \
    BACKUP_SCRIPT="${DRILL_TOOL_DIR}/postgres-backup.sh" \
    RESTORE_SCRIPT="${DRILL_TOOL_DIR}/restore-drill.sh" \
    "${DRILL_TOOL_DIR}/production-restore-drill.sh"
fi

if [[ "${mode}" == "all" || "${mode}" == "observability" ]]; then
  APP_ROOT="${PROD_APP_ROOT}" \
    API_BASE_URL=https://api.axelio.ru \
    API_SERVICE=axelio-api-prod \
    "${DRILL_TOOL_DIR}/observability-drill.sh"
fi

echo "production assurance drill completed: mode=${mode} release=${RELEASE_SHA}"

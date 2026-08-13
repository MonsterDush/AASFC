#!/usr/bin/env bash
set -euo pipefail

: "${APP_ROOT:?Set APP_ROOT}"
: "${API_BASE_URL:?Set API_BASE_URL}"
: "${API_SERVICE:?Set API_SERVICE}"
: "${BOT_SERVICE:?Set BOT_SERVICE}"
: "${SHIFT_TIMER:?Set SHIFT_TIMER}"
: "${NOTIFY_TIMER:?Set NOTIFY_TIMER}"
: "${TG_BOT_TOKEN:?Set TG_BOT_TOKEN}"

state_dir="${MONITORING_STATE_DIR:-/var/lib/axelio-monitoring}"
backup_dir="${BACKUP_DIR:-/var/backups/axelio/prod}"
max_backup_age="${BACKUP_MAX_AGE_SECONDS:-93600}"
max_latency_seconds="${API_ALERT_LATENCY_SECONDS:-2.5}"
failed_payment_threshold="${BILLING_ALERT_FAILED_THRESHOLD_24H:-5}"
chat_ids="${AXELIO_ALERT_TG_CHAT_IDS:-${SUPER_ADMIN_TG_USER_IDS:-}}"
python_bin="${APP_ROOT}/venv/bin/python"
repo_dir="${APP_ROOT}/repo"

[[ "${APP_ROOT}" == "/var/www/axelio/prod" || "${APP_ROOT}" == /tmp/axelio-monitor-* ]] || {
  echo "Unsupported APP_ROOT: ${APP_ROOT}" >&2
  exit 2
}
[[ "${state_dir}" == "/var/lib/axelio-monitoring" || "${state_dir}" == /tmp/axelio-monitoring-* ]] || {
  echo "Unsupported MONITORING_STATE_DIR: ${state_dir}" >&2
  exit 2
}

install -d -m 0755 "${state_dir}"
failures=()

check_active() {
  local unit="$1"
  if ! systemctl is-active --quiet "${unit}"; then
    failures+=("systemd unit is inactive: ${unit}")
  fi
}

check_active "${API_SERVICE}"
check_active "${BOT_SERVICE}"
check_active "${SHIFT_TIMER}"
check_active "${NOTIFY_TIMER}"
check_active "axelio-backup-prod.timer"

health_body="$(mktemp)"
health_meta=""
cleanup() { rm -f -- "${health_body}"; }
trap cleanup EXIT
if health_meta="$(curl --fail --silent --show-error --max-time 15 \
  --output "${health_body}" \
  --write-out '%{http_code} %{time_total}' \
  "${API_BASE_URL%/}/health/ready")"; then
  health_status="${health_meta%% *}"
  health_latency="${health_meta##* }"
  if [[ "${health_status}" != "200" ]]; then
    failures+=("API readiness returned HTTP ${health_status}")
  fi
  if ! "${python_bin}" - "${health_body}" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
if payload.get("status") != "ready" or payload.get("database") != "ok":
    raise SystemExit(1)
PY
  then
    failures+=("API readiness payload or database status is invalid")
  fi
  if ! awk -v actual="${health_latency}" -v maximum="${max_latency_seconds}" 'BEGIN { exit !(actual > maximum) }'; then
    :
  else
    failures+=("API readiness latency ${health_latency}s exceeds ${max_latency_seconds}s")
  fi
else
  failures+=("API readiness is unavailable")
fi

newest_backup="$(find "${backup_dir}/daily" -maxdepth 1 -type f -name '*.dump.enc' -print 2>/dev/null | sort | tail -n 1)"
if [[ -z "${newest_backup}" ]]; then
  failures+=("production backup is missing")
else
  backup_age="$(( $(date +%s) - $(stat -c '%Y' "${newest_backup}") ))"
  if (( backup_age > max_backup_age )); then
    failures+=("production backup is stale: ${backup_age}s")
  fi
  [[ -f "${newest_backup}.sha256" && -f "${newest_backup}.metadata" ]] || \
    failures+=("production backup checksum or metadata is missing")
fi

if snapshot="$(cd "${repo_dir}/backend" && "${python_bin}" -m app.scripts.operational_snapshot)"; then
  read -r failed_payments open_reconciliation failed_jobs stale_jobs < <(
    "${python_bin}" - "${snapshot}" <<'PY'
import json, sys
value = json.loads(sys.argv[1])
print(value["failed_payments_24h"], value["open_reconciliation_high"], value["failed_notification_jobs"], value["stale_notification_jobs"])
PY
  )
  (( failed_payments < failed_payment_threshold )) || failures+=("failed payments in 24h: ${failed_payments}")
  (( open_reconciliation == 0 )) || failures+=("open high reconciliation issues: ${open_reconciliation}")
  (( failed_jobs == 0 )) || failures+=("failed notification jobs: ${failed_jobs}")
  (( stale_jobs == 0 )) || failures+=("stale notification jobs: ${stale_jobs}")
else
  failures+=("operational database snapshot failed")
fi

failure_text="$(printf '%s\n' "${failures[@]:-}" | sed '/^$/d')"
failure_hash="$(printf '%s' "${failure_text}" | sha256sum | awk '{print $1}')"
previous_hash="$(cat "${state_dir}/last-alert.hash" 2>/dev/null || true)"

send_alert() {
  local message="$1"
  local normalized_ids
  normalized_ids="$(printf '%s' "${chat_ids}" | tr ',;' '  ')"
  [[ -n "${normalized_ids// /}" ]] || {
    echo "No AXELIO_ALERT_TG_CHAT_IDS or SUPER_ADMIN_TG_USER_IDS configured" >&2
    return 1
  }
  for chat_id in ${normalized_ids}; do
    curl --fail --silent --show-error --max-time 15 \
      --request POST \
      --data-urlencode "chat_id=${chat_id}" \
      --data-urlencode "text=${message}" \
      "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" >/dev/null
  done
}

if [[ -n "${failure_text}" ]]; then
  if [[ "${failure_hash}" != "${previous_hash}" ]]; then
    send_alert "$(printf 'Axelio production alert:\n%s' "${failure_text}")" || true
  fi
  printf '%s\n' "${failure_hash}" >"${state_dir}/last-alert.hash"
  printf '%s\n' "${failure_text}" >"${state_dir}/last-alert.txt"
  exit 1
fi

if [[ -n "${previous_hash}" ]]; then
  send_alert "Axelio production recovered: all automated health checks are green." || true
fi
rm -f -- "${state_dir}/last-alert.hash" "${state_dir}/last-alert.txt"
printf '%s\n' "$(date +%s)" >"${state_dir}/monitor-last-success.timestamp"
echo "Axelio production monitoring checks passed"

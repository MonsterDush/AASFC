#!/usr/bin/env bash
set -Eeuo pipefail

: "${APP_ROOT:?Set APP_ROOT}"
: "${API_BASE_URL:?Set API_BASE_URL}"
: "${API_SERVICE:?Set API_SERVICE}"
: "${TG_BOT_TOKEN:?Set TG_BOT_TOKEN}"

[[ "${EUID}" -eq 0 ]] || {
  echo "Observability drill must run as root" >&2
  exit 2
}
[[ "${APP_ROOT}" == "/var/www/axelio/prod" ]] || {
  echo "Unsupported APP_ROOT: ${APP_ROOT}" >&2
  exit 2
}
[[ "${API_SERVICE}" == "axelio-api-prod" ]] || {
  echo "Unsupported API_SERVICE: ${API_SERVICE}" >&2
  exit 2
}

env_file="${APP_ROOT}/repo/backend/.env"
state_dir="${MONITORING_STATE_DIR:-/var/lib/axelio-monitoring}"
chat_ids="${AXELIO_ALERT_TG_CHAT_IDS:-${SUPER_ADMIN_TG_USER_IDS:-}}"
metrics_token="${METRICS_TOKEN:-}"

[[ -f "${env_file}" ]] || {
  echo "Missing production environment: ${env_file}" >&2
  exit 1
}
[[ -n "${chat_ids//[[:space:],;]/}" ]] || {
  echo "No production Telegram alert recipient configured" >&2
  exit 1
}

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${env_file}"; then
    sed -i "s|^${key}=.*|${key}=${value}|" "${env_file}"
  else
    printf '\n%s=%s\n' "${key}" "${value}" >>"${env_file}"
  fi
}

if [[ -z "${metrics_token}" ]]; then
  metrics_token="$(openssl rand -hex 32)"
  set_env_value METRICS_TOKEN "${metrics_token}"
  systemctl restart "${API_SERVICE}"
fi

for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 10 \
    "${API_BASE_URL%/}/health/ready" >/dev/null; then
    break
  fi
  if [[ "${attempt}" == "30" ]]; then
    echo "Production API did not become ready during observability drill" >&2
    exit 1
  fi
  sleep 1
done

metrics_snapshot="$(mktemp)"
cleanup() { rm -f -- "${metrics_snapshot}"; }
trap cleanup EXIT
curl --fail --silent --show-error --max-time 20 \
  --header "Authorization: Bearer ${metrics_token}" \
  "${API_BASE_URL%/}/metrics" >"${metrics_snapshot}"
grep -q '^axelio_build_info' "${metrics_snapshot}" || {
  echo "Authorized production metrics response is missing axelio_build_info" >&2
  exit 1
}

if ! systemctl start axelio-monitor-prod.service; then
  echo "Production monitor failed during observability drill" >&2
  if [[ -s "${state_dir}/last-alert.txt" ]]; then
    echo "Production monitor guardrails:" >&2
    sed 's/^/  - /' "${state_dir}/last-alert.txt" >&2
  fi
  (
    cd "${APP_ROOT}/repo/backend"
    "${APP_ROOT}/venv/bin/python" - <<'PY'
import json

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import NotificationJob

with SessionLocal() as db:
    jobs = db.execute(
        select(NotificationJob)
        .where(NotificationJob.status == "failed")
        .order_by(NotificationJob.updated_at.desc(), NotificationJob.id.desc())
        .limit(20)
    ).scalars().all()

print("Failed notification job diagnostics (payload and recipients omitted):")
for job in jobs:
    print(json.dumps({
        "id": int(job.id),
        "job_type": str(job.job_type),
        "attempts": int(job.attempts or 0),
        "max_attempts": int(job.max_attempts or 0),
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "last_error": str(job.last_error or "")[:500],
    }, ensure_ascii=True, sort_keys=True))
PY
  ) >&2 || true
  systemctl status axelio-monitor-prod.service --no-pager >&2 || true
  journalctl -u axelio-monitor-prod.service -n 100 --no-pager >&2 || true
  exit 1
fi
systemctl is-active --quiet axelio-monitor-prod.timer

send_message() {
  local message="$1"
  local normalized_ids
  normalized_ids="$(printf '%s' "${chat_ids}" | tr ',;' '  ')"
  for chat_id in ${normalized_ids}; do
    curl --fail --silent --show-error --max-time 15 \
      --request POST \
      --data-urlencode "chat_id=${chat_id}" \
      --data-urlencode "text=${message}" \
      "https://api.telegram.org/bot${TG_BOT_TOKEN}/sendMessage" >/dev/null
  done
}

release="${RELEASE_VERSION:-unknown}"
send_message "Axelio production monitoring test alert. Release: ${release}. No service failure was induced."
send_message "Axelio production recovered: test alert delivery confirmed. Release: ${release}."

install -d -m 0755 "${state_dir}"
timestamp_tmp="$(mktemp "${state_dir}/.observability-drill.XXXXXX")"
printf '%s\n' "$(date +%s)" >"${timestamp_tmp}"
chmod 0644 "${timestamp_tmp}"
mv "${timestamp_tmp}" "${state_dir}/observability-drill-last-success.timestamp"

echo "observability drill: metrics, monitor, Telegram alert and recovery verified"

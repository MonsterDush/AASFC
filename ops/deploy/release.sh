#!/usr/bin/env bash
set -Eeuo pipefail

mode="${1:-}"
if [[ "${mode}" != "deploy" && "${mode}" != "rollback" ]]; then
  echo "Usage: release.sh {deploy|rollback} [target_sha]" >&2
  exit 2
fi

: "${APP_ROOT:?Set APP_ROOT}"
: "${BRANCH:?Set BRANCH}"
: "${ENV_NAME:?Set ENV_NAME}"
: "${API_SERVICE:?Set API_SERVICE}"
: "${BOT_SERVICE:?Set BOT_SERVICE}"
: "${NOTIFY_TIMER:?Set NOTIFY_TIMER}"
: "${API_BASE_URL:?Set API_BASE_URL}"
: "${FRONTEND_BASE_URL:?Set FRONTEND_BASE_URL}"

repo_dir="${APP_ROOT}/repo"
backend_dir="${repo_dir}/backend"
venv_bin="${APP_ROOT}/venv/bin"
env_file="${backend_dir}/.env"
state_dir="${APP_ROOT}/deployments"
smoke_script="${SMOKE_SCRIPT:-${repo_dir}/ops/deploy/post-deploy-smoke.sh}"
release_sha="${RELEASE_SHA:-${2:-}}"
ci_actor="${CI_ACTOR:-manual}"
ci_run_url="${CI_RUN_URL:-manual}"
activation_started=0
previous_sha=""
release_started_epoch="$(date +%s)"

validate_inputs() {
  [[ "${APP_ROOT}" == /var/www/axelio/dev || "${APP_ROOT}" == /var/www/axelio/prod ]] || {
    echo "Unsupported APP_ROOT: ${APP_ROOT}" >&2
    exit 2
  }
  [[ "${BRANCH}" == "develop" || "${BRANCH}" == "main" ]] || {
    echo "Unsupported BRANCH: ${BRANCH}" >&2
    exit 2
  }
  [[ "${ENV_NAME}" == "dev" || "${ENV_NAME}" == "prod" ]] || {
    echo "Unsupported ENV_NAME: ${ENV_NAME}" >&2
    exit 2
  }
  [[ "${API_SERVICE}" =~ ^axelio-api-(dev|prod)$ ]]
  [[ "${BOT_SERVICE}" =~ ^axelio-bot-(dev|prod)$ ]]
  [[ "${NOTIFY_TIMER}" =~ ^axelio-notification-jobs-(dev|prod)\.timer$ ]]
  [[ -d "${repo_dir}/.git" ]] || {
    echo "Missing repository: ${repo_dir}" >&2
    exit 2
  }
  [[ -x "${venv_bin}/python" && -x "${venv_bin}/pip" && -x "${venv_bin}/alembic" ]] || {
    echo "Incomplete virtualenv: ${venv_bin}" >&2
    exit 2
  }
  [[ -f "${env_file}" ]] || {
    echo "Missing backend env: ${env_file}" >&2
    exit 2
  }
  [[ -x "${smoke_script}" ]] || {
    echo "Missing smoke script: ${smoke_script}" >&2
    exit 2
  }
}

validate_sha() {
  local value="$1"
  [[ "${value}" =~ ^[0-9a-f]{40}$ ]] || {
    echo "Expected a full commit SHA, got: ${value:-empty}" >&2
    exit 2
  }
  git -C "${repo_dir}" cat-file -e "${value}^{commit}"
  git -C "${repo_dir}" merge-base --is-ancestor "${value}" "origin/${BRANCH}" || {
    echo "Release ${value} is not part of origin/${BRANCH}" >&2
    exit 2
  }
}

set_env_value() {
  local key="$1"
  local value="$2"
  if grep -q "^${key}=" "${env_file}"; then
    sudo sed -i "s|^${key}=.*|${key}=${value}|" "${env_file}"
  else
    printf '\n%s=%s\n' "${key}" "${value}" | sudo tee -a "${env_file}" >/dev/null
  fi
}

configure_release_env() {
  local target_sha="$1"
  set_env_value RELEASE_VERSION "${target_sha}"
  if [[ "${ENV_NAME}" == "prod" ]]; then
    set_env_value APP_ENV production
    set_env_value COOKIE_SECURE true
    set_env_value PHONE_AUTH_DEBUG_REVEAL_CODE false
  else
    set_env_value APP_ENV development
  fi
}

configure_frontend_runtime() {
  local runtime_config="${repo_dir}/frontend/runtime-config.json"
  "${venv_bin}/python" - "${env_file}" "${runtime_config}" "${ENV_NAME}" <<'PY'
import json
import os
import sys

from dotenv import dotenv_values

env_path, output_path, environment = sys.argv[1:]
values = dotenv_values(env_path)
release = str(values.get("RELEASE_VERSION") or os.environ.get("RELEASE_SHA") or "local")
dsn = str(values.get("SENTRY_BROWSER_DSN") or values.get("SENTRY_DSN") or "")
try:
    sample_rate = float(values.get("SENTRY_BROWSER_TRACES_SAMPLE_RATE") or 0)
except (TypeError, ValueError):
    sample_rate = 0.0
sample_rate = sample_rate if 0.0 <= sample_rate <= 1.0 else 0.0
payload = {
    "environment": "production" if environment == "prod" else "development",
    "release": release,
    "sentryBrowserDsn": dsn,
    "sentryBrowserTracesSampleRate": sample_rate,
}
temporary = f"{output_path}.tmp"
with open(temporary, "w", encoding="utf-8") as target:
    json.dump(payload, target, ensure_ascii=False, separators=(",", ":"))
    target.write("\n")
os.replace(temporary, output_path)
PY
}

install_backup_units() {
  [[ "${ENV_NAME}" == "prod" ]] || return 0
  sudo install -D -m 0644 \
    "${repo_dir}/ops/systemd/axelio-backup-prod.service" \
    /etc/systemd/system/axelio-backup-prod.service
  sudo install -D -m 0644 \
    "${repo_dir}/ops/systemd/axelio-backup-prod.timer" \
    /etc/systemd/system/axelio-backup-prod.timer
  sudo install -d -m 0700 /var/backups/axelio/prod
  # ReadWritePaths targets must exist before systemd builds the service sandbox.
  sudo install -d -m 0755 /var/lib/axelio-monitoring
  sudo systemctl daemon-reload
  if [[ ! -f /etc/axelio/backup-prod.env ]]; then
    echo "Missing /etc/axelio/backup-prod.env; production deploy requires encrypted offsite backup" >&2
    exit 1
  fi
  if ! sudo systemctl start axelio-backup-prod.service; then
    sudo systemctl status axelio-backup-prod.service --no-pager || true
    sudo journalctl -u axelio-backup-prod.service -n 100 --no-pager || true
    return 1
  fi
  sudo systemctl enable --now axelio-backup-prod.timer
}

has_monitoring_sources() {
  [[ -f "${repo_dir}/ops/monitoring/health-check.sh" && \
     -f "${repo_dir}/ops/systemd/axelio-monitor-prod.service" && \
     -f "${repo_dir}/ops/systemd/axelio-monitor-prod.timer" ]]
}

install_monitoring_units() {
  [[ "${ENV_NAME}" == "prod" ]] || return 0
  has_monitoring_sources || return 0
  sudo install -D -m 0644 \
    "${repo_dir}/ops/systemd/axelio-monitor-prod.service" \
    /etc/systemd/system/axelio-monitor-prod.service
  sudo install -D -m 0644 \
    "${repo_dir}/ops/systemd/axelio-monitor-prod.timer" \
    /etc/systemd/system/axelio-monitor-prod.timer
  sudo install -d -m 0755 /var/lib/axelio-monitoring
}

activate_nginx_performance() {
  local activator="${repo_dir}/ops/nginx/activate-performance.sh"
  local nginx_scope="development"
  [[ -x "${activator}" ]] || return 0
  if [[ "${ENV_NAME}" == "prod" ]]; then
    nginx_scope="production"
  fi
  sudo env AXELIO_NGINX_SCOPE="${nginx_scope}" "${activator}"
}

checkout_release() {
  local target_sha="$1"
  git -C "${repo_dir}" checkout "${BRANCH}"
  git -C "${repo_dir}" reset --hard "${target_sha}"
  git -C "${repo_dir}" clean -fd
  configure_release_env "${target_sha}"
  configure_frontend_runtime
}

install_dependencies() {
  "${venv_bin}/pip" install -r "${backend_dir}/requirements.txt"
  if [[ "${ENV_NAME}" == "prod" ]]; then
    (
      cd "${backend_dir}"
      "${venv_bin}/python" -c \
        'from app.core.config import settings; assert settings.is_production(), "APP_ENV=production is required"'
    )
  fi
}

run_migrations() {
  (
    cd "${backend_dir}"
    "${venv_bin}/alembic" upgrade head
    "${venv_bin}/python" -m app.core.sync_permissions
    "${venv_bin}/python" -m app.scripts.seed_position_permission_templates
  )
}

notification_runner_owns_shift_reminders() {
  grep -Eq '^OWNS_SHIFT_REMINDERS[[:space:]]*=[[:space:]]*True$' \
    "${backend_dir}/app/scripts/process_notification_jobs.py"
}

configure_notification_timers() {
  local legacy_shift_timer="axelio-shift-reminders-${ENV_NAME}.timer"

  sudo systemctl restart "${NOTIFY_TIMER}"
  if notification_runner_owns_shift_reminders; then
    # Shift reminders are part of process_notification_jobs. Keeping the old
    # timer active would create a second scheduler for the same delivery window.
    sudo systemctl disable --now "${legacy_shift_timer}" >/dev/null 2>&1 || true
  else
    # Preserve rollback compatibility for releases from before the scheduler
    # consolidation. The current release always takes the branch above.
    sudo systemctl enable --now "${legacy_shift_timer}"
  fi
}

has_quickresto_sources() {
  local service_name="axelio-quickresto-sync-${ENV_NAME}.service"
  local timer_name="axelio-quickresto-sync-${ENV_NAME}.timer"
  [[ -f "${repo_dir}/ops/systemd/${service_name}" && -f "${repo_dir}/ops/systemd/${timer_name}" ]]
}

install_quickresto_units() {
  local service_name="axelio-quickresto-sync-${ENV_NAME}.service"
  local timer_name="axelio-quickresto-sync-${ENV_NAME}.timer"
  if ! has_quickresto_sources; then
    # A rollback to a release from before this integration must also stop its scheduler.
    sudo systemctl disable --now "${timer_name}" >/dev/null 2>&1 || true
    sudo rm -f "/etc/systemd/system/${service_name}" "/etc/systemd/system/${timer_name}"
    return 0
  fi
  sudo install -D -m 0644 "${repo_dir}/ops/systemd/${service_name}" "/etc/systemd/system/${service_name}"
  sudo install -D -m 0644 "${repo_dir}/ops/systemd/${timer_name}" "/etc/systemd/system/${timer_name}"
}

restart_services() {
  sudo install -D -m 0644 \
    "${repo_dir}/ops/nginx/axelio-security-headers.conf" \
    /etc/nginx/snippets/axelio-security-headers.conf
  if [[ -f "${repo_dir}/ops/nginx/axelio-performance.conf" ]]; then
    sudo install -D -m 0644 \
      "${repo_dir}/ops/nginx/axelio-performance.conf" \
      /etc/nginx/snippets/axelio-performance.conf
  fi
  if [[ -f "${repo_dir}/ops/nginx/axelio-cache-map.conf" ]]; then
    sudo install -D -m 0644 \
      "${repo_dir}/ops/nginx/axelio-cache-map.conf" \
      /etc/nginx/conf.d/axelio-cache-map.conf
  fi
  activate_nginx_performance
  install_monitoring_units
  install_quickresto_units
  sudo nginx -t
  sudo systemctl daemon-reload
  sudo systemctl restart "${API_SERVICE}"
  sudo systemctl restart "${BOT_SERVICE}"
  configure_notification_timers
  if has_quickresto_sources; then
    sudo systemctl enable --now "axelio-quickresto-sync-${ENV_NAME}.timer"
  fi
  if [[ "${ENV_NAME}" == "prod" ]]; then
    if has_monitoring_sources; then
      sudo systemctl enable --now axelio-monitor-prod.timer
    else
      sudo systemctl disable --now axelio-monitor-prod.timer >/dev/null 2>&1 || true
    fi
  fi
  sudo systemctl reload nginx
  sudo systemctl is-active --quiet "${API_SERVICE}"
  sudo systemctl is-active --quiet "${BOT_SERVICE}"
  sudo systemctl is-active --quiet "${NOTIFY_TIMER}"
  if has_quickresto_sources; then
    sudo systemctl is-active --quiet "axelio-quickresto-sync-${ENV_NAME}.timer"
  fi
  if [[ "${ENV_NAME}" == "prod" ]] && has_monitoring_sources; then
    sudo systemctl is-active --quiet axelio-monitor-prod.timer
  fi
}

smoke_release() {
  local target_sha="$1"
  local allow_legacy="${2:-false}"
  API_BASE_URL="${API_BASE_URL}" \
    FRONTEND_BASE_URL="${FRONTEND_BASE_URL}" \
    EXPECTED_RELEASE="${target_sha}" \
    PYTHON_BIN="${venv_bin}/python" \
    ALLOW_LEGACY_HEALTH="${allow_legacy}" \
    "${smoke_script}"
  if [[ "${ENV_NAME}" == "prod" ]]; then
    sudo install -d -m 0755 /var/lib/axelio-monitoring
    printf '%s\n' "$(date +%s)" | sudo tee /var/lib/axelio-monitoring/deploy-smoke-last-success.timestamp >/dev/null
    sudo chmod 0644 /var/lib/axelio-monitoring/deploy-smoke-last-success.timestamp
  fi
}

write_release_metadata() {
  local target_sha="$1"
  local prior_sha="$2"
  local action="$3"
  local migration_head
  local elapsed_seconds

  # During an application-only rollback the database can intentionally remain
  # on a newer, backwards-compatible migration. In that case the checked-out
  # Alembic tree cannot resolve the database revision, so read the revision
  # table directly instead of failing after a successful smoke check.
  if ! migration_head="$(
    cd "${backend_dir}"
    "${venv_bin}/alembic" current 2>/dev/null | awk 'NR == 1 {print $1}'
  )" || [[ -z "${migration_head}" ]]; then
    migration_head="$(
      cd "${backend_dir}"
      "${venv_bin}/python" - <<'PY'
from sqlalchemy import create_engine, text

from app.core.config import settings

engine = create_engine(settings.database_url)
try:
    with engine.connect() as connection:
        revisions = connection.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).scalars()
        print(",".join(str(revision) for revision in revisions))
finally:
    engine.dispose()
PY
    )"
  fi
  [[ -n "${migration_head}" ]] || migration_head="unknown"
  elapsed_seconds="$(( $(date +%s) - release_started_epoch ))"
  mkdir -p "${state_dir}"
  {
    printf 'release=%s\n' "${target_sha}"
    printf 'previous_release=%s\n' "${prior_sha}"
    printf 'branch=%s\n' "${BRANCH}"
    printf 'environment=%s\n' "${ENV_NAME}"
    printf 'action=%s\n' "${action}"
    printf 'deployed_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'initiator=%s\n' "${ci_actor//$'\n'/}"
    printf 'ci_run=%s\n' "${ci_run_url//$'\n'/}"
    printf 'migration_head=%s\n' "${migration_head}"
    printf 'duration_seconds=%s\n' "${elapsed_seconds}"
  } >"${state_dir}/${target_sha}.metadata"
  printf '%s\n' "${prior_sha}" >"${state_dir}/previous.sha"
  printf '%s\n' "${target_sha}" >"${state_dir}/current.sha"
}

activate_release() {
  local target_sha="$1"
  local apply_migrations="$2"
  local allow_legacy="${3:-false}"
  checkout_release "${target_sha}"
  install_dependencies
  if [[ "${apply_migrations}" == "true" ]]; then
    install_backup_units
    run_migrations
  fi
  restart_services
  smoke_release "${target_sha}" "${allow_legacy}"
}

handle_failure() {
  local exit_code="$?"
  trap - ERR
  if [[ "${mode}" == "deploy" && "${activation_started}" == "1" && -n "${previous_sha}" ]]; then
    echo "Deployment failed; rolling application back to ${previous_sha}" >&2
    set +e
    activate_release "${previous_sha}" false true
    rollback_code="$?"
    set -e
    if [[ "${rollback_code}" == "0" ]]; then
      mkdir -p "${state_dir}"
      printf '%s\n' "${release_sha}" >"${state_dir}/failed.sha"
      write_release_metadata "${previous_sha}" "${release_sha}" automatic-rollback
      echo "Automatic application rollback completed" >&2
    else
      echo "Automatic application rollback failed" >&2
    fi
  fi
  exit "${exit_code}"
}
trap handle_failure ERR

validate_inputs
git -C "${repo_dir}" fetch --prune origin
mkdir -p "${state_dir}"

if [[ "${mode}" == "deploy" ]]; then
  [[ -n "${release_sha}" ]] || {
    echo "Set RELEASE_SHA for deploy" >&2
    exit 2
  }
  remote_sha="$(git -C "${repo_dir}" rev-parse "origin/${BRANCH}")"
  if [[ "${remote_sha}" != "${release_sha}" ]]; then
    echo "Skipping stale deployment ${release_sha}; origin/${BRANCH} is ${remote_sha}"
    exit 0
  fi
  validate_sha "${release_sha}"
  previous_sha="$(git -C "${repo_dir}" rev-parse HEAD)"
  activation_started=1
  activate_release "${release_sha}" true false
  write_release_metadata "${release_sha}" "${previous_sha}" deploy
  echo "Deployed ${BRANCH} ${release_sha} -> ${ENV_NAME} in $(( $(date +%s) - release_started_epoch ))s"
else
  target_sha="${release_sha:-${2:-}}"
  if [[ -z "${target_sha}" && -f "${state_dir}/previous.sha" ]]; then
    target_sha="$(tr -d '[:space:]' <"${state_dir}/previous.sha")"
  fi
  [[ -n "${target_sha}" ]] || {
    echo "No rollback target provided and ${state_dir}/previous.sha is missing" >&2
    exit 2
  }
  validate_sha "${target_sha}"
  previous_sha="$(git -C "${repo_dir}" rev-parse HEAD)"
  activate_release "${target_sha}" false true
  write_release_metadata "${target_sha}" "${previous_sha}" manual-rollback
  echo "Rolled ${ENV_NAME} back from ${previous_sha} to ${target_sha} in $(( $(date +%s) - release_started_epoch ))s"
fi

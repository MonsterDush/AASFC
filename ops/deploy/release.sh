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
: "${SHIFT_TIMER:?Set SHIFT_TIMER}"
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
  [[ "${SHIFT_TIMER}" =~ ^axelio-shift-reminders-(dev|prod)\.timer$ ]]
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

checkout_release() {
  local target_sha="$1"
  git -C "${repo_dir}" checkout "${BRANCH}"
  git -C "${repo_dir}" reset --hard "${target_sha}"
  git -C "${repo_dir}" clean -fd
  configure_release_env "${target_sha}"
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

restart_services() {
  sudo install -D -m 0644 \
    "${repo_dir}/ops/nginx/axelio-security-headers.conf" \
    /etc/nginx/snippets/axelio-security-headers.conf
  if [[ -f "${repo_dir}/ops/nginx/axelio-performance.conf" ]]; then
    sudo install -D -m 0644 \
      "${repo_dir}/ops/nginx/axelio-performance.conf" \
      /etc/nginx/snippets/axelio-performance.conf
  fi
  install_monitoring_units
  sudo nginx -t
  sudo systemctl daemon-reload
  sudo systemctl restart "${API_SERVICE}"
  sudo systemctl restart "${BOT_SERVICE}"
  sudo systemctl restart "${SHIFT_TIMER}"
  sudo systemctl restart "${NOTIFY_TIMER}"
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
  sudo systemctl is-active --quiet "${SHIFT_TIMER}"
  sudo systemctl is-active --quiet "${NOTIFY_TIMER}"
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
  migration_head="$(cd "${backend_dir}" && "${venv_bin}/alembic" current | awk 'NR == 1 {print $1}')"
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
  echo "Deployed ${BRANCH} ${release_sha} -> ${ENV_NAME}"
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
  echo "Rolled ${ENV_NAME} back from ${previous_sha} to ${target_sha}"
fi

#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="${AXELIO_E2E_ENV_FILE:-${repo_dir}/.env.e2e}"
compose_file="${repo_dir}/docker-compose.e2e.yml"

if [[ ! -f "${env_file}" ]]; then
  echo "Missing ${env_file}. Copy .env.e2e.example to .env.e2e first." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "${env_file}"
set +a

compose=(docker compose --env-file "${env_file}" -f "${compose_file}")

migrate() {
  (
    cd "${repo_dir}/backend"
    .venv/bin/alembic upgrade head
  )
}

seed() {
  (
    cd "${repo_dir}/backend"
    .venv/bin/python -m app.scripts.bootstrap_e2e_data
  )
}

verify_night_shift() {
  (
    cd "${repo_dir}/backend"
    .venv/bin/python -m app.scripts.verify_night_shift_e2e
  )
}

verify_browser() {
  (
    cd "${repo_dir}"
    pnpm test:browser
  )
}

case "${1:-}" in
  up)
    "${compose[@]}" up -d --wait
    migrate
    seed
    ;;
  reset)
    migrate
    seed
    ;;
  verify-night)
    migrate
    seed
    verify_night_shift
    ;;
  migration-smoke)
    "${repo_dir}/tools/migration-smoke.sh"
    ;;
  browser)
    verify_browser
    ;;
  status)
    "${compose[@]}" ps
    ;;
  backend)
    cd "${repo_dir}/backend"
    exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 9001
    ;;
  frontend)
    cd "${repo_dir}"
    exec backend/.venv/bin/python -m http.server 8765 --bind 127.0.0.1 --directory frontend
    ;;
  down)
    "${compose[@]}" down
    ;;
  *)
    echo "Usage: $0 {up|reset|verify-night|migration-smoke|backend|frontend|browser|status|down}" >&2
    exit 2
    ;;
esac

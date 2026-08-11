#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
backend_dir="${repo_dir}/backend"
alembic_bin="${ALEMBIC_BIN:-${backend_dir}/.venv/bin/alembic}"

cd "${backend_dir}"

head_count="$(${alembic_bin} heads | wc -l | tr -d ' ')"
if [[ "${head_count}" != "1" ]]; then
  echo "Expected exactly one Alembic head, got ${head_count}" >&2
  exit 1
fi

expected_head="$(${alembic_bin} heads | awk '{print $1}')"

assert_current_head() {
  local current
  current="$(${alembic_bin} current | awk 'NR == 1 {print $1}')"
  if [[ "${current}" != "${expected_head}" ]]; then
    echo "Expected Alembic revision ${expected_head}, got ${current:-empty}" >&2
    exit 1
  fi
}

${alembic_bin} upgrade head
assert_current_head

# Every new head must support a one-step rollback and re-application on PostgreSQL.
${alembic_bin} downgrade -1
${alembic_bin} upgrade head
assert_current_head

echo "migration smoke: ${expected_head} upgrade/downgrade/upgrade passed"

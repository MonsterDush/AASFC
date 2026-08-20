#!/usr/bin/env bash
set -euo pipefail

: "${API_BASE_URL:?Set API_BASE_URL}"
: "${FRONTEND_BASE_URL:?Set FRONTEND_BASE_URL}"
: "${EXPECTED_RELEASE:?Set EXPECTED_RELEASE}"

attempts="${SMOKE_ATTEMPTS:-12}"
delay_seconds="${SMOKE_DELAY_SECONDS:-5}"
python_bin="${PYTHON_BIN:-python3}"
allow_legacy_health="${ALLOW_LEGACY_HEALTH:-false}"

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf -- "${tmp_dir}"
}
trap cleanup EXIT

api_base="${API_BASE_URL%/}"
frontend_base="${FRONTEND_BASE_URL%/}"

check_release_payload() {
  local payload_path="$1"
  "${python_bin}" - "${payload_path}" "${EXPECTED_RELEASE}" <<'PY'
import json
import sys

path, expected_release = sys.argv[1:]
with open(path, encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("status") not in {"ok", "ready"}:
    raise SystemExit(f"unexpected health status: {payload!r}")
if payload.get("database") not in {None, "ok"}:
    raise SystemExit(f"database is not ready: {payload!r}")
actual_release = str(payload.get("release") or "")
if actual_release != expected_release:
    raise SystemExit(f"release mismatch: expected {expected_release}, got {actual_release or 'empty'}")
PY
}

check_legacy_payload() {
  local payload_path="$1"
  "${python_bin}" - "${payload_path}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    payload = json.load(source)
if payload.get("status") != "ok":
    raise SystemExit(f"unexpected legacy health status: {payload!r}")
PY
}

for attempt in $(seq 1 "${attempts}"); do
  headers_path="${tmp_dir}/headers"
  body_path="${tmp_dir}/body"
  if curl --fail --silent --show-error --max-time 10 \
    --dump-header "${headers_path}" \
    --output "${body_path}" \
    "${api_base}/health/ready" && \
    check_release_payload "${body_path}" && \
    grep -qi '^x-request-id:' "${headers_path}" && \
    curl --fail --silent --show-error --max-time 10 \
      --output /dev/null "${frontend_base}/auth.html" && \
    curl --fail --silent --show-error --max-time 10 \
      --dump-header "${headers_path}" \
      --output /dev/null "${frontend_base}/page-loader.js?v=${EXPECTED_RELEASE}" && \
    grep -Eqi '^cache-control:[[:space:]]*public, max-age=31536000, immutable' "${headers_path}" && \
    curl --fail --silent --show-error --max-time 10 \
      --dump-header "${headers_path}" \
      --output /dev/null "${frontend_base}/runtime-config.json" && \
    grep -Eqi '^cache-control:[[:space:]]*no-store' "${headers_path}"; then
    echo "post-deploy smoke: release ${EXPECTED_RELEASE} is ready"
    exit 0
  fi

  if [[ "${allow_legacy_health}" == "true" ]] && \
    curl --fail --silent --show-error --max-time 10 \
      --output "${body_path}" "${api_base}/health" && \
    check_legacy_payload "${body_path}" && \
    curl --fail --silent --show-error --max-time 10 \
      --output /dev/null "${frontend_base}/auth.html"; then
    echo "post-deploy smoke: legacy release ${EXPECTED_RELEASE} is reachable"
    exit 0
  fi

  if [[ "${attempt}" != "${attempts}" ]]; then
    sleep "${delay_seconds}"
  fi
done

echo "Post-deploy smoke failed for release ${EXPECTED_RELEASE}" >&2
exit 1

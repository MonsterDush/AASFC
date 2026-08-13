#!/usr/bin/env bash
set -Eeuo pipefail

sites_root="${NGINX_SITES_ROOT:-/etc/nginx/sites-enabled}"
allowed_root="${NGINX_ALLOWED_ROOT:-/etc/nginx}"
security_include="${AXELIO_SECURITY_INCLUDE:-/etc/nginx/snippets/axelio-security-headers.conf}"
performance_include="${AXELIO_PERFORMANCE_INCLUDE:-/etc/nginx/snippets/axelio-performance.conf}"
backup_root="${NGINX_BACKUP_ROOT:-/var/backups/axelio/nginx}"
nginx_bin="${NGINX_BIN:-nginx}"
dry_run="${NGINX_ACTIVATE_DRY_RUN:-false}"
nginx_scope="${AXELIO_NGINX_SCOPE:-production}"

resolve_path() {
  if command -v realpath >/dev/null 2>&1; then
    realpath "$1"
  else
    readlink -f "$1"
  fi
}

count_include() {
  local target="$1"
  local include_path="$2"
  awk -v wanted="${include_path}" '
    {
      line = $0
      sub(/#.*/, "", line)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      gsub(/[[:space:]]+/, " ", line)
      if (line == "include " wanted ";") count++
    }
    END { print count + 0 }
  ' "${target}"
}

[[ -d "${sites_root}" ]] || {
  echo "Missing Nginx sites directory: ${sites_root}" >&2
  exit 1
}
[[ -f "${performance_include}" ]] || {
  echo "Missing Axelio performance snippet: ${performance_include}" >&2
  exit 1
}
command -v "${nginx_bin}" >/dev/null 2>&1 || {
  echo "Missing Nginx executable: ${nginx_bin}" >&2
  exit 1
}
[[ "${dry_run}" == "true" || "${dry_run}" == "false" ]] || {
  echo "NGINX_ACTIVATE_DRY_RUN must be true or false" >&2
  exit 2
}
case "${nginx_scope}" in
  production) domain_pattern='(app|api)\.axelio\.ru' ;;
  development) domain_pattern='(app|api)-dev\.axelio\.ru' ;;
  *)
    echo "AXELIO_NGINX_SCOPE must be production or development" >&2
    exit 2
    ;;
esac

allowed_root="$(resolve_path "${allowed_root}")"
targets=()
target_count=0
while IFS= read -r -d '' candidate; do
  target="$(resolve_path "${candidate}" 2>/dev/null || true)"
  [[ -n "${target}" && -f "${target}" ]] || continue
  case "${target}" in
    "${allowed_root}"/*) ;;
    *)
      echo "Refusing Nginx config outside ${allowed_root}: ${target}" >&2
      exit 1
      ;;
  esac
  grep -Eq "server_name[[:space:]][^;]*${domain_pattern}([[:space:]]|;)" "${target}" || continue
  [[ "$(count_include "${target}" "${security_include}")" -gt 0 ]] || continue

  duplicate=false
  if [[ "${target_count}" -gt 0 ]]; then
    for ((index = 0; index < target_count; index++)); do
      if [[ "${targets[index]}" == "${target}" ]]; then
        duplicate=true
        break
      fi
    done
  fi
  if [[ "${duplicate}" != "true" ]]; then
    targets[target_count]="${target}"
    target_count=$((target_count + 1))
  fi
done < <(find "${sites_root}" -maxdepth 1 \( -type f -o -type l \) -print0)

[[ "${target_count}" -gt 0 ]] || {
  echo "No active ${nginx_scope} Axelio Nginx config with the security snippet was found" >&2
  exit 1
}

pending_targets=()
pending_count=0
for ((index = 0; index < target_count; index++)); do
  target="${targets[index]}"
  security_count="$(count_include "${target}" "${security_include}")"
  performance_count="$(count_include "${target}" "${performance_include}")"
  if [[ "${performance_count}" -eq "${security_count}" ]]; then
    continue
  fi
  if [[ "${performance_count}" -ne 0 ]]; then
    echo "Partial performance activation in ${target}: ${performance_count}/${security_count}; review manually" >&2
    exit 1
  fi
  pending_targets[pending_count]="${target}"
  pending_count=$((pending_count + 1))
done

if [[ "${pending_count}" -eq 0 ]]; then
  "${nginx_bin}" -t
  echo "Axelio Nginx performance snippet is already active"
  exit 0
fi

if [[ "${dry_run}" == "true" ]]; then
  "${nginx_bin}" -t
  echo "Axelio Nginx performance activation is ready for ${pending_count} config file(s)"
  exit 0
fi

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup_dir="${backup_root%/}/${timestamp}-$$"
mkdir -p "${backup_dir}"
chmod 0700 "${backup_dir}"

modified_targets=()
backup_paths=()
modified_count=0
completed=false

restore_on_failure() {
  local exit_code="$?"
  trap - EXIT
  if [[ "${completed}" != "true" ]]; then
    for ((index = 0; index < modified_count; index++)); do
      cp -p -- "${backup_paths[index]}" "${modified_targets[index]}" || true
    done
    "${nginx_bin}" -t || true
    echo "Nginx activation failed; original configuration restored from ${backup_dir}" >&2
  fi
  exit "${exit_code}"
}
trap restore_on_failure EXIT

for ((index = 0; index < pending_count; index++)); do
  target="${pending_targets[index]}"
  backup_path="${backup_dir}/config-${index}.conf"
  cp -p -- "${target}" "${backup_path}"
  printf '%s\n' "${target}" >>"${backup_dir}/manifest.txt"

  temporary="$(mktemp "${target}.axelio-performance.XXXXXX")"
  awk -v security="${security_include}" -v performance="${performance_include}" '
    {
      print
      line = $0
      sub(/#.*/, "", line)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", line)
      gsub(/[[:space:]]+/, " ", line)
      if (line == "include " security ";") {
        match($0, /^[[:space:]]*/)
        indent = substr($0, RSTART, RLENGTH)
        print indent "include " performance ";"
      }
    }
  ' "${target}" >"${temporary}"

  if stat -c '%a' "${target}" >/dev/null 2>&1; then
    chmod "$(stat -c '%a' "${target}")" "${temporary}"
  else
    chmod "$(stat -f '%Lp' "${target}")" "${temporary}"
  fi
  if [[ "${EUID}" -eq 0 ]]; then
    if stat -c '%u' "${target}" >/dev/null 2>&1; then
      chown "$(stat -c '%u:%g' "${target}")" "${temporary}"
    else
      chown "$(stat -f '%u:%g' "${target}")" "${temporary}"
    fi
  fi
  mv -- "${temporary}" "${target}"
  modified_targets[modified_count]="${target}"
  backup_paths[modified_count]="${backup_path}"
  modified_count=$((modified_count + 1))
done

"${nginx_bin}" -t
completed=true
trap - EXIT
echo "Activated Axelio Nginx performance snippet; backup: ${backup_dir}"

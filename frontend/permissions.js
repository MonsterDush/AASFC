// permissions.js — helpers for permission gating in UI (ES module)

export function normalizePermList(permsResp) {
  const raw = Array.isArray(permsResp)
    ? permsResp
    : (Array.isArray(permsResp?.permissions) ? permsResp.permissions
      : (Array.isArray(permsResp?.codes) ? permsResp.codes : []));

  if (!Array.isArray(raw)) return [];

  return raw
    .map((x) => {
      if (!x) return "";
      if (typeof x === "string") return x.trim().toUpperCase();
      if (typeof x === "object") {
        const v = x.code || x.permission_code || x.permission || "";
        return String(v || "").trim().toUpperCase();
      }
      return String(x).trim().toUpperCase();
    })
    .filter(Boolean);
}

export function permSetFromResponse(permsResp) {
  return new Set(normalizePermList(permsResp));
}

export function roleUpper(permsResp) {
  const r = (permsResp?.role || permsResp?.venue_role || permsResp?.my_role || permsResp?.system_role || "").toString();
  return r.trim().toUpperCase();
}

export function hasPerm(permSet, code) {
  if (!permSet || !code) return false;
  return permSet.has(String(code).trim().toUpperCase());
}

export function hasAnyPerm(permSet, codes) {
  if (!permSet || !Array.isArray(codes)) return false;
  return codes.some((c) => hasPerm(permSet, c));
}

export function hasPermPrefix(permSet, prefix) {
  if (!permSet || !prefix) return false;
  const p = String(prefix).trim().toUpperCase();
  for (const c of permSet) {
    if (String(c).startsWith(p)) return true;
  }
  return false;
}


// --- convenience helpers (report access / system roles) ---

export function isSysAdminRole(sysRoleUpper) {
  const r = String(sysRoleUpper || "").trim().toUpperCase();
  return r === "SUPER_ADMIN" || r === "MODERATOR";
}

export function isOwnerRole(venueRoleUpper) {
  const r = String(venueRoleUpper || "").trim().toUpperCase();
  return r === "OWNER" || r === "VENUE_OWNER";
}

/**
 * Report access means user can open report pages / see report sections.
 * We keep it permissive: any SHIFT_REPORT_* / REPORTS_* implies access.
 */
export function canViewReports(permSet, venueRoleUpper, systemRoleUpper) {
  const role = String(venueRoleUpper || "").trim().toUpperCase();
  const sys = String(systemRoleUpper || "").trim().toUpperCase();

  if (isOwnerRole(role)) return true;
  if (isSysAdminRole(sys)) return true;

  return (
    hasPermPrefix(permSet, "SHIFT_REPORT_") ||
    hasPermPrefix(permSet, "REPORTS_") ||
    hasAnyPerm(permSet, [
      "SHIFT_REPORT_VIEW",
      "SHIFT_REPORT_CLOSE",
      "SHIFT_REPORT_EDIT",
      "SHIFT_REPORT_REOPEN",
      "REPORTS_VIEW_DAILY",
      "REPORTS_VIEW_MONTHLY",
      "REPORTS_VIEW_PNL",
    ])
  );
}

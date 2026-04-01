// permissions.js — shared permission helpers for UI gating (ES module)

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

export function isSysAdminRole(sysRoleUpper) {
  const r = String(sysRoleUpper || "").trim().toUpperCase();
  return r === "SUPER_ADMIN" || r === "MODERATOR";
}

export function isOwnerRole(venueRoleUpper) {
  const r = String(venueRoleUpper || "").trim().toUpperCase();
  return r === "OWNER" || r === "VENUE_OWNER";
}

export function hasReportAccess(permSet, venueRoleUpper, systemRoleUpper) {
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

// Backward-compatible export name used by older pages.
export const canViewReports = hasReportAccess;

export function canManageAdjustments(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "ADJUSTMENTS_MANAGE");
}

export function canViewAdjustments(permSet, venueRoleUpper, systemRoleUpper) {
  return canManageAdjustments(permSet, venueRoleUpper, systemRoleUpper) || hasPerm(permSet, "ADJUSTMENTS_VIEW");
}

export function canViewRevenue(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "REVENUE_VIEW");
}


export function readBillingState(payload) {
  const src = payload && typeof payload === "object" ? payload : {};
  return {
    billing_status: String(src.billing_status || "ACTIVE").trim().toUpperCase() || "ACTIVE",
    billing_access_mode: String(src.billing_access_mode || "FULL").trim().toUpperCase() || "FULL",
    billing_restricted_reason: src.billing_restricted_reason || null,
    paid_until: src.paid_until || null,
    grace_until: src.grace_until || null,
  };
}

export function isBillingReadonly(payload) {
  return readBillingState(payload).billing_access_mode === "BILLING_READONLY";
}

export function isBillingDenied(payload) {
  return readBillingState(payload).billing_access_mode === "DENIED";
}

export function isBillingFull(payload) {
  return readBillingState(payload).billing_access_mode === "FULL";
}

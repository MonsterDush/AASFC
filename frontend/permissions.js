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

export function getBillingStatus(resp) {
  return String(resp?.billing_status || "ACTIVE").trim().toUpperCase() || "ACTIVE";
}

export function getBillingAccessMode(resp) {
  return String(resp?.billing_access_mode || "FULL").trim().toUpperCase() || "FULL";
}

export function getBillingState(resp) {
  return {
    status: getBillingStatus(resp),
    accessMode: getBillingAccessMode(resp),
    paidUntil: resp?.paid_until || null,
    graceUntil: resp?.grace_until || null,
    restrictedReason: resp?.billing_restricted_reason || null,
  };
}

export function isBillingReadonly(resp) {
  return getBillingAccessMode(resp) === "BILLING_READONLY";
}

export function isBillingDenied(resp) {
  return getBillingAccessMode(resp) === "DENIED";
}

export function isBillingRestricted(resp) {
  const mode = getBillingAccessMode(resp);
  return mode === "BILLING_READONLY" || mode === "DENIED";
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


export function isDemoMode(resp) {
  return !!resp?.demo_mode;
}

export function getDemoAccessMode(resp) {
  return String(resp?.demo_access_mode || "FULL").trim().toUpperCase() || "FULL";
}

export function getDemoPersona(resp) {
  return String(resp?.demo_persona || "OWNER").trim().toUpperCase() || "OWNER";
}

export function getDemoReference(resp) {
  return {
    year: resp?.demo_reference_year ?? null,
    month: resp?.demo_reference_month ?? null,
  };
}

export function getDemoState(resp) {
  return {
    isDemo: !!resp?.is_demo,
    demoMode: isDemoMode(resp),
    accessMode: getDemoAccessMode(resp),
    persona: getDemoPersona(resp),
    venueId: resp?.demo_venue_id ?? null,
    referenceYear: resp?.demo_reference_year ?? null,
    referenceMonth: resp?.demo_reference_month ?? null,
    restrictedReason: resp?.demo_restricted_reason || null,
  };
}

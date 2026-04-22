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
    billingKind: resp?.billing_kind || null,
    isTrial: !!resp?.is_trial,
    trialUntil: resp?.trial_until || null,
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




export function hasExpenseViewAccess(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "EXPENSE_VIEW") || hasPerm(permSet, "EXPENSE_ADD");
}

export function hasPayrollViewAccess(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "PAYROLL_VIEW") || hasPerm(permSet, "PAYROLL_CALCULATE");
}

export function hasFinanceLedgerViewAccess(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "FINANCE_LEDGER_VIEW") || hasPerm(permSet, "REVENUE_VIEW") || hasPerm(permSet, "EXPENSE_VIEW");
}

export function hasPayProfilesViewAccess(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "PAY_PROFILES_VIEW") || hasPerm(permSet, "PAY_PROFILES_MANAGE");
}

export function hasVenuePageAccess(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "VENUE_VIEW") || hasPerm(permSet, "VENUE_SETTINGS_EDIT");
}

export function hasPositionsViewAccess(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasAnyPerm(permSet, ["POSITIONS_VIEW", "POSITIONS_MANAGE", "POSITIONS_ASSIGN", "POSITION_PERMISSIONS_MANAGE"]);
}

export function hasIntervalsViewAccess(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "SHIFTS_MANAGE");
}

export function hasExpenseCatalogsViewAccess(permSet, venueRoleUpper, systemRoleUpper) {
  return isOwnerRole(venueRoleUpper) || isSysAdminRole(systemRoleUpper) || hasPerm(permSet, "EXPENSE_CATEGORIES_MANAGE");
}

export function buildStaffDashboardItems(permSet, venueRoleUpper, systemRoleUpper, venueId = "") {
  const role = String(venueRoleUpper || "").trim().toUpperCase();
  const sys = String(systemRoleUpper || "").trim().toUpperCase();
  const qs = venueId ? `?venue_id=${encodeURIComponent(String(venueId))}` : "";

  const canViewReports = hasReportAccess(permSet, role, sys);
  const canManageAdj = canManageAdjustments(permSet, role, sys);
  const canViewAdj = canViewAdjustments(permSet, role, sys);
  const canViewSummary =
    isOwnerRole(role) ||
    isSysAdminRole(sys) ||
    hasPerm(permSet, "MONTHLY_SUMMARY_VIEW") ||
    hasExpenseViewAccess(permSet, role, sys) ||
    hasPayrollViewAccess(permSet, role, sys) ||
    hasPerm(permSet, "REVENUE_VIEW");
  const canViewRevenuePage = canViewRevenue(permSet, role, sys);
  const canViewExpensesPage = hasExpenseViewAccess(permSet, role, sys);
  const canViewPayrollPage = hasPayrollViewAccess(permSet, role, sys);
  const canViewLedgerPage = hasFinanceLedgerViewAccess(permSet, role, sys);
  const canViewDayEconomicsPage = canViewRevenuePage || canViewExpensesPage;
  const canViewDepartmentsPage = isOwnerRole(role) || isSysAdminRole(sys) || hasPerm(permSet, "DEPARTMENTS_VIEW");
  const canViewPaymentMethodsPage = isOwnerRole(role) || isSysAdminRole(sys) || hasPerm(permSet, "PAYMENT_METHODS_VIEW");
  const canViewKpiPage = isOwnerRole(role) || isSysAdminRole(sys) || hasPerm(permSet, "KPI_METRICS_VIEW");
  const canViewPayProfilesPage = hasPayProfilesViewAccess(permSet, role, sys);
  const canViewVenuePage = hasVenuePageAccess(permSet, role, sys);
  const canViewPositionsPage = hasPositionsViewAccess(permSet, role, sys);
  const canViewIntervalsPage = hasIntervalsViewAccess(permSet, role, sys);
  const canViewExpenseCatalogsPage = hasExpenseCatalogsViewAccess(permSet, role, sys);
  const canViewRecurringExpensesPage = isOwnerRole(role) || isSysAdminRole(sys) || hasPerm(permSet, "RECURRING_EXPENSES_VIEW") || hasPerm(permSet, "EXPENSE_VIEW") || hasPerm(permSet, "EXPENSE_ADD");

  const items = [
    {
      key: "shifts",
      title: "График",
      hint: "Календарь смен и детали дня.",
      href: `/staff-shifts.html${qs}`,
      isExtra: false,
    },
    {
      key: "salary",
      title: "Зарплата",
      hint: "Начисления по сменам и месяцам.",
      href: `/staff-salary.html${qs}`,
      isExtra: false,
    },
  ];

  if (canViewAdj) {
    items.push({
      key: "adjustments",
      title: "Штрафы / Премии",
      hint: canManageAdj ? "Управление корректировками и история по дням." : "История штрафов, списаний и премий.",
      href: `${canManageAdj ? "/app-adjustments.html" : "/staff-adjustments.html"}${qs}`,
      isExtra: false,
    });
  }

  if (canViewReports) {
    items.push({
      key: "report",
      title: "Отчёты",
      hint: "Отчёт за смену и закрытие дня.",
      href: `/staff-report.html${qs}`,
      isExtra: false,
    });
  }

  if (canViewSummary) {
    items.push({
      key: "summary",
      title: "Сводка",
      hint: "Общая картина по выручке, расходам и фонду оплаты.",
      href: `/owner-summary.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewRevenuePage) {
    items.push({
      key: "revenue",
      title: "Выручка",
      hint: "Доходы по оплатам и периодам.",
      href: `/owner-turnover.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewExpensesPage) {
    items.push({
      key: "expenses",
      title: "Расходы",
      hint: "Список расходов, фильтры и детализация.",
      href: `/owner-expenses.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewPayrollPage) {
    items.push({
      key: "payroll",
      title: "Начисления",
      hint: "Расчёты по сотрудникам и детализация компонентов.",
      href: `/owner-payroll.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewLedgerPage) {
    items.push({
      key: "ledger",
      title: "Движение денег",
      hint: "Доходы и расходы по оплатам и операциям.",
      href: `/owner-finance-ledger.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewDayEconomicsPage) {
    items.push({
      key: "day-economics",
      title: "Экономика дня",
      hint: "Снимок дня по доходам, расходам и прибыли.",
      href: `/owner-day-economics.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewVenuePage) {
    items.push({
      key: "venue",
      title: "Заведение",
      hint: "Карточка заведения и быстрые переходы.",
      href: `/app-venue.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewPositionsPage) {
    items.push({
      key: "positions",
      title: "Должности",
      hint: "Должности, назначения и права.",
      href: `/positions.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewIntervalsPage) {
    items.push({
      key: "intervals",
      title: "Интервалы",
      hint: "Справочник интервалов и времени смен.",
      href: `/shift-intervals.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewDepartmentsPage) {
    items.push({
      key: "departments",
      title: "Департаменты",
      hint: "Структура выручки и департаментов.",
      href: `/owner-departments.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewPaymentMethodsPage) {
    items.push({
      key: "payment-methods",
      title: "Способы оплат",
      hint: "Наличные, безнал и другие оплаты.",
      href: `/owner-payment-methods.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewKpiPage) {
    items.push({
      key: "kpi",
      title: "KPI и планы",
      hint: "Метрики, допродажи и планы.",
      href: `/owner-kpi.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewPayProfilesPage) {
    items.push({
      key: "pay-profiles",
      title: "Профили зарплаты",
      hint: "Профили и компоненты начислений.",
      href: `/owner-pay-profiles.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewRecurringExpensesPage) {
    items.push({
      key: "recurring-expenses",
      title: "Регулярные расходы",
      hint: "Постоянные расходы по месяцам.",
      href: `/owner-recurring-expenses.html${qs}`,
      isExtra: true,
    });
  }

  if (canViewExpenseCatalogsPage) {
    items.push({
      key: "expense-categories",
      title: "Статьи расходов",
      hint: "Категории расходов и их структура.",
      href: `/owner-expense-categories.html${qs}`,
      isExtra: true,
    });
    items.push({
      key: "suppliers",
      title: "Поставщики",
      hint: "Справочник поставщиков и контрагентов.",
      href: `/owner-suppliers.html${qs}`,
      isExtra: true,
    });
  }

  return items;
}

export function hasStaffDashboardExtras(permSet, venueRoleUpper, systemRoleUpper) {
  return buildStaffDashboardItems(permSet, venueRoleUpper, systemRoleUpper).some((item) => item.isExtra);
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


export function getSetupStatus(resp) {
  return String(resp?.setup_status || resp?.status || "NOT_STARTED").trim().toUpperCase() || "NOT_STARTED";
}

export function getSetupPhase(resp) {
  return String(resp?.setup_phase || resp?.phase || "PREPARE").trim().toUpperCase() || "PREPARE";
}

export function getSetupResumeStep(resp) {
  return String(resp?.setup_resume_step || resp?.resume_step || "").trim();
}

export function getSetupProgress(resp) {
  return {
    total: Number(resp?.setup_progress_total ?? resp?.progress_total ?? 0) || 0,
    done: Number(resp?.setup_progress_done ?? resp?.progress_done ?? 0) || 0,
    resolved: Number(resp?.setup_progress_resolved ?? resp?.progress_resolved ?? 0) || 0,
  };
}

export function isSetupPrepareDone(resp) {
  return !!(resp?.setup_prepare_done ?? resp?.prepare_done);
}

export function isSetupExtraDone(resp) {
  return !!(resp?.setup_extra_done ?? resp?.extra_done);
}

export function isSetupDone(resp) {
  return getSetupStatus(resp) === "DONE";
}

export function needsPrepareSetup(resp) {
  return !isSetupPrepareDone(resp);
}

export function needsExtraSetup(resp) {
  return isSetupPrepareDone(resp) && !isSetupDone(resp);
}

export function getSetupActionLabel(resp) {
  if (needsPrepareSetup(resp)) {
    return getSetupStatus(resp) === "NOT_STARTED" ? "Начать настройку" : "Продолжить настройку";
  }
  if (needsExtraSetup(resp)) return "Доп. настройка";
  return "Мастер настройки";
}

export function hasPendingSetup(resp) {
  const status = getSetupStatus(resp);
  return !["PREPARE_DONE", "DONE"].includes(status);
}

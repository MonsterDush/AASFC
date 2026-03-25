import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  getMyVenuePermissions,
  api,
  API_BASE,
  toast,
} from "/app.js";
import { canViewRevenue, isOwnerRole, permSetFromResponse, roleUpper, hasPerm } from "/permissions.js?v=20260321-miniappfix1";

function fmtMoneyMinor(minor) {
  const kopecks = Number(minor || 0);
  const rub = kopecks / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return rub.toFixed(2) + " ₽";
  }
}

function fmtPercentBps(bps) {
  if (bps === null || bps === undefined) return "—";
  const pct = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(pct) + "%";
  } catch {
    return pct.toFixed(2) + "%";
  }
}

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

let state = {
  period: "month",
  month: currentMonth(),
  from: todayISO(),
  to: todayISO(),
};

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function showBlock(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? "" : "none";
}

function normalizeRange() {
  if (!state.from) state.from = todayISO();
  if (!state.to) state.to = state.from;
  if (state.from > state.to) {
    const tmp = state.from;
    state.from = state.to;
    state.to = tmp;
  }
}

function setActiveSeg(containerId, dataKey, value) {
  document.querySelectorAll(`#${containerId} button`).forEach((btn) => {
    if (btn.dataset[dataKey] === value) btn.classList.add("active");
    else btn.classList.remove("active");
  });
}

function syncPickers() {
  const monthPick = document.getElementById("summaryMonthPick");
  const rangePick = document.getElementById("summaryRangePick");
  if (monthPick) monthPick.style.display = state.period === "month" ? "" : "none";
  if (rangePick) rangePick.style.display = state.period === "range" ? "flex" : "none";
}

function buildSummaryQuery() {
  const qp = new URLSearchParams();
  qp.set("period", state.period);
  if (state.period === "month") {
    qp.set("month", state.month || currentMonth());
  } else {
    normalizeRange();
    qp.set("date_from", state.from || todayISO());
    qp.set("date_to", state.to || todayISO());
  }
  return qp;
}

function syncUrl() {
  const qp = buildSummaryQuery();
  const venueId = getActiveVenueId();
  if (venueId) qp.set("venue_id", String(venueId));
  history.replaceState(null, "", `${location.pathname}?${qp.toString()}`);
}

function statePeriodText() {
  if (state.period === "month") return state.month || currentMonth();
  normalizeRange();
  return `${state.from} — ${state.to}`;
}

function withTimeout(promise, ms, label = "REQUEST_TIMEOUT") {
  let timer = null;
  return new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      const err = new Error(label);
      err.code = "TIMEOUT";
      reject(err);
    }, ms);
    Promise.resolve(promise).then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); },
    );
  });
}

async function startupApi(path, timeoutMs = 10000, label = "STARTUP_TIMEOUT") {
  return withTimeout(api(path), timeoutMs, label);
}

async function openExportLink(path) {
  const data = await api(path);
  const url = data?.export_link || (data?.export_path ? `${API_BASE}${data.export_path}` : "");
  if (!url) throw new Error("export link missing");
  const tg = window.Telegram?.WebApp;
  try {
    if (tg?.openLink) {
      tg.openLink(url, { try_instant_view: false });
      return;
    }
  } catch {}
  window.location.href = url;
}

let financeAccess = {
  canViewRevenue: false,
  canViewExpenses: false,
  canViewPayroll: false,
  canCalculatePayroll: false,
};

async function loadFinanceAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return financeAccess;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isOwner = isOwnerRole(role);
    financeAccess = {
      canViewRevenue: canViewRevenue(pset, role, ""),
      canViewExpenses: isOwner || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD"),
      canViewPayroll: isOwner || hasPerm(pset, "PAYROLL_VIEW") || hasPerm(pset, "PAYROLL_CALCULATE"),
      canCalculatePayroll: isOwner || hasPerm(pset, "PAYROLL_CALCULATE"),
    };
  } catch {
    financeAccess = { canViewRevenue: false, canViewExpenses: false, canViewPayroll: false, canCalculatePayroll: false };
  }
  return financeAccess;
}

function syncActions() {
  const venueId = getActiveVenueId();
  const exportSummaryBtn = document.getElementById("exportSummaryBtn");
  const revenueBtn = document.getElementById("openRevenueBtn");
  const expensesBtn = document.getElementById("openExpensesBtn");
  const payrollBtn = document.getElementById("openPayrollBtn");
  const economicsBtn = document.getElementById("openEconomicsBtn");

  if (exportSummaryBtn) {
    exportSummaryBtn.style.display = financeAccess.canViewRevenue ? "" : "none";
    exportSummaryBtn.onclick = async () => {
      try {
        await openExportLink(`/venues/${encodeURIComponent(venueId)}/summary/monthly/export-link?${buildSummaryQuery().toString()}`);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось начать экспорт", "err");
      }
    };
  }

  if (revenueBtn) {
    revenueBtn.style.display = financeAccess.canViewRevenue ? "" : "none";
    revenueBtn.onclick = () => {
      const qp = buildSummaryQuery();
      qp.set("venue_id", String(venueId));
      qp.set("mode", "PAYMENTS");
      location.href = `/owner-turnover.html?${qp.toString()}`;
    };
  }

  if (expensesBtn) {
    expensesBtn.style.display = financeAccess.canViewExpenses ? "" : "none";
    expensesBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("month", state.month || currentMonth());
      location.href = `/owner-expenses.html?${qp.toString()}`;
    };
  }

  if (payrollBtn) {
    payrollBtn.style.display = financeAccess.canViewPayroll ? "" : "none";
    payrollBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("month", state.month || currentMonth());
      location.href = `/owner-payroll.html?${qp.toString()}`;
    };
  }

  if (economicsBtn) {
    economicsBtn.style.display = financeAccess.canViewRevenue ? "" : "none";
    economicsBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("date", state.period === "month" ? `${state.month || currentMonth()}-01` : (state.to || state.from || todayISO()));
      location.href = `/owner-day-economics.html?${qp.toString()}`;
    };
  }
}

async function loadSummary() {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  normalizeRange();
  syncPickers();
  syncUrl();
  await loadFinanceAccess();
  syncActions();

  showBlock("revenueCard", financeAccess.canViewRevenue);
  showBlock("profitCard", financeAccess.canViewRevenue);
  showBlock("marginCard", financeAccess.canViewRevenue);
  showBlock("expensesCard", financeAccess.canViewExpenses);
  showBlock("payrollCard", financeAccess.canViewPayroll);
  showBlock("totalCostCard", financeAccess.canViewExpenses || financeAccess.canViewPayroll);
  showBlock("adjustmentsCard", financeAccess.canViewRevenue);
  showBlock("refundsCard", financeAccess.canViewRevenue);
  showBlock("expenseRatioCard", financeAccess.canViewRevenue && financeAccess.canViewExpenses);
  showBlock("payrollRatioCard", financeAccess.canViewRevenue && financeAccess.canViewPayroll);
  showBlock("totalCostRatioCard", financeAccess.canViewRevenue && (financeAccess.canViewExpenses || financeAccess.canViewPayroll));

  if (!financeAccess.canViewRevenue && !financeAccess.canViewExpenses && !financeAccess.canViewPayroll) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
    setText("summaryPayroll", "—");
    setText("summaryTotalCost", "—");
    setText("summaryProfit", "—");
    setText("summaryMargin", "—");
    setText("summaryAdjustments", "—");
    setText("summaryRefunds", "—");
    setText("summaryExpenseRatio", "—");
    setText("summaryPayrollRatio", "—");
    setText("summaryTotalCostRatio", "—");
    setText("summaryHint", "Нет прав на финансовую сводку");
    return;
  }

  try {
    let summary;
    const qs = buildSummaryQuery().toString();
    try {
      summary = await startupApi(`/venues/${encodeURIComponent(venueId)}/finance/summary?${qs}`, 10000, "OWNER_SUMMARY_TIMEOUT");
    } catch {
      summary = await startupApi(`/venues/${encodeURIComponent(venueId)}/summary/monthly?${qs}&income_mode=PAYMENTS`, 10000, "OWNER_SUMMARY_TIMEOUT");
      summary = {
        ...summary,
        expense_without_payroll_minor: summary?.expense_without_payroll_minor ?? summary?.expense_minor,
        total_cost_minor: summary?.total_cost_minor ?? ((Number(summary?.expense_minor || 0)) + (Number(summary?.payroll_minor || 0))),
      };
    }
    setText("summaryRevenue", fmtMoneyMinor(summary?.revenue_minor));
    setText("summaryExpenses", fmtMoneyMinor(summary?.expense_without_payroll_minor ?? summary?.expense_minor));
    setText("summaryPayroll", fmtMoneyMinor(summary?.payroll_minor));
    setText("summaryTotalCost", fmtMoneyMinor(summary?.total_cost_minor ?? ((Number(summary?.expense_minor || 0)) + (Number(summary?.payroll_minor || 0)))));
    setText("summaryProfit", fmtMoneyMinor(summary?.profit_minor));
    setText("summaryMargin", fmtPercentBps(summary?.margin_bps));
    setText("summaryAdjustments", fmtMoneyMinor(summary?.adjustments_minor));
    setText("summaryRefunds", fmtMoneyMinor(summary?.refunds_minor));
    setText("summaryExpenseRatio", fmtPercentBps(summary?.expense_ratio_bps));
    setText("summaryPayrollRatio", fmtPercentBps(summary?.payroll_ratio_bps));
    setText("summaryTotalCostRatio", fmtPercentBps(summary?.total_cost_ratio_bps));
    setText("summaryPeriodText", summary?.period_start && summary?.period_end ? `${summary.period_start} — ${summary.period_end}` : statePeriodText());
    setText("summaryHint", `Главный экран оставляет только ключевые метрики. Детальные разделы ниже открываются отдельно.`);
  } catch (e) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
    setText("summaryPayroll", "—");
    setText("summaryTotalCost", "—");
    setText("summaryProfit", "—");
    setText("summaryMargin", "—");
    setText("summaryAdjustments", "—");
    setText("summaryRefunds", "—");
    setText("summaryExpenseRatio", "—");
    setText("summaryPayrollRatio", "—");
    setText("summaryTotalCostRatio", "—");
    setText("summaryHint", e?.data?.detail || e.message || "Ошибка загрузки");
    toast("Не удалось загрузить финансовую сводку", "err");
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);

  await mountNav({ activeTab: "summary" });

  try {
    const venues = await getMyVenues();
    const v = venues.find((x) => String(x.id) === String(getActiveVenueId()));
    if (v) {
      const subtitle = document.getElementById("subtitle");
      if (subtitle) subtitle.textContent = v.name || "";
    }
  } catch {}

  state.period = params.get("period") || (params.get("date_from") && params.get("date_to") ? "range" : "month");
  state.month = (params.get("month") || currentMonth()).slice(0, 7);
  state.from = params.get("date_from") || todayISO();
  state.to = params.get("date_to") || state.from;
  normalizeRange();

  const monthPick = document.getElementById("summaryMonthPick");
  const fromPick = document.getElementById("summaryFromPick");
  const toPick = document.getElementById("summaryToPick");
  const rangeApplyBtn = document.getElementById("summaryRangeApplyBtn");

  if (monthPick) {
    monthPick.value = state.month;
    monthPick.onchange = (e) => {
      state.month = (e.target.value || currentMonth()).slice(0, 7);
      state.period = "month";
      setActiveSeg("summaryPeriodSeg", "period", "month");
      loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
    };
  }
  if (fromPick) {
    fromPick.value = state.from;
    fromPick.onchange = (e) => {
      state.from = e.target.value || todayISO();
    };
  }
  if (toPick) {
    toPick.value = state.to;
    toPick.onchange = (e) => {
      state.to = e.target.value || state.from || todayISO();
    };
  }
  if (rangeApplyBtn) {
    rangeApplyBtn.onclick = () => {
      state.period = "range";
      setActiveSeg("summaryPeriodSeg", "period", "range");
      loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
    };
  }

  document.querySelectorAll(`#summaryPeriodSeg button`).forEach((btn) => {
    btn.onclick = () => {
      const nextPeriod = btn.dataset.period || "month";
      state.period = nextPeriod;
      setActiveSeg("summaryPeriodSeg", "period", nextPeriod);
      if (nextPeriod === "month") {
        loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
      } else {
        syncPickers();
        syncUrl();
      }
    };
  });

  setActiveSeg("summaryPeriodSeg", "period", state.period);
  syncPickers();
  await loadSummary();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

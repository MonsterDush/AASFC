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
} from "/app.js?v=20260321-miniappfix1";
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

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function showBlock(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? "" : "none";
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

function syncActions(month) {
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
        await openExportLink(`/venues/${encodeURIComponent(venueId)}/summary/monthly/export-link?month=${encodeURIComponent(month)}`);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось начать экспорт", "err");
      }
    };
  }

  if (revenueBtn) {
    revenueBtn.style.display = financeAccess.canViewRevenue ? "" : "none";
    revenueBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("month", month);
      qp.set("mode", "PAYMENTS");
      qp.set("period", "month");
      location.href = `/owner-turnover.html?${qp.toString()}`;
    };
  }

  if (expensesBtn) {
    expensesBtn.style.display = financeAccess.canViewExpenses ? "" : "none";
    expensesBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("month", month);
      location.href = `/owner-expenses.html?${qp.toString()}`;
    };
  }

  if (payrollBtn) {
    payrollBtn.style.display = financeAccess.canViewPayroll ? "" : "none";
    payrollBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("month", month);
      location.href = `/owner-payroll.html?${qp.toString()}`;
    };
  }

  if (economicsBtn) {
    economicsBtn.style.display = financeAccess.canViewRevenue ? "" : "none";
    economicsBtn.onclick = () => {
      const params = new URLSearchParams(location.search);
      const targetDate = params.get("date") || `${month}-01` || todayISO();
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("date", targetDate);
      location.href = `/owner-day-economics.html?${qp.toString()}`;
    };
  }
}

async function loadSummary(monthYYYYMM) {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  await loadFinanceAccess();
  syncActions(monthYYYYMM);

  showBlock("revenueCard", financeAccess.canViewRevenue);
  showBlock("expensesCard", financeAccess.canViewExpenses);
  showBlock("payrollCard", financeAccess.canViewPayroll);
  showBlock("totalCostCard", financeAccess.canViewExpenses || financeAccess.canViewPayroll);

  if (!financeAccess.canViewRevenue && !financeAccess.canViewExpenses && !financeAccess.canViewPayroll) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
    setText("summaryPayroll", "—");
    setText("summaryTotalCost", "—");
    setText("summaryProfit", "—");
    setText("summaryMargin", "—");
    setText("summaryHint", "Нет прав на финансовую сводку");
    return;
  }

  try {
    let summary;
    try {
      summary = await startupApi(`/venues/${encodeURIComponent(venueId)}/finance/summary?month=${encodeURIComponent(monthYYYYMM)}`, 10000, "OWNER_SUMMARY_TIMEOUT");
    } catch (primaryError) {
      summary = await startupApi(`/venues/${encodeURIComponent(venueId)}/summary/monthly?month=${encodeURIComponent(monthYYYYMM)}&income_mode=PAYMENTS`, 10000, "OWNER_SUMMARY_TIMEOUT");
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
    setText("summaryPeriodText", `${summary?.period_start || monthYYYYMM} — ${summary?.period_end || monthYYYYMM}`);
    setText("summaryHint", `Доли от выручки: расходы ${fmtPercentBps(summary?.expense_ratio_bps)} · ФОТ ${fmtPercentBps(summary?.payroll_ratio_bps)} · всего затрат ${fmtPercentBps(summary?.total_cost_ratio_bps)} · корректировки ${fmtMoneyMinor(summary?.adjustments_minor)} · возвраты ${fmtMoneyMinor(summary?.refunds_minor)}`);
  } catch (e) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
    setText("summaryPayroll", "—");
    setText("summaryTotalCost", "—");
    setText("summaryProfit", "—");
    setText("summaryMargin", "—");
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
    const v = venues.find(x => String(x.id) === String(getActiveVenueId()));
    if (v) {
      const subtitle = document.getElementById("subtitle");
      if (subtitle) subtitle.textContent = v.name || "";
    }
  } catch {}

  const monthPick = document.getElementById("summaryMonthPick");
  const month = params.get("month") || currentMonth();
  if (monthPick) {
    monthPick.value = month;
    monthPick.onchange = (e) => loadSummary(e.target.value || currentMonth());
  }

  await loadSummary(month);
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

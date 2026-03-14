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
  toast,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

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

let financeAccess = {
  canViewRevenue: false,
  canViewExpenses: false,
};

async function loadFinanceAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return financeAccess;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    financeAccess = {
      canViewRevenue: isOwner || hasPerm(pset, "REVENUE_VIEW"),
      canViewExpenses: isOwner || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD"),
    };
  } catch {
    financeAccess = { canViewRevenue: false, canViewExpenses: false };
  }
  return financeAccess;
}

function syncActions(month) {
  const venueId = getActiveVenueId();
  const revenueBtn = document.getElementById("openRevenueBtn");
  const expensesBtn = document.getElementById("openExpensesBtn");
  const economicsBtn = document.getElementById("openEconomicsBtn");

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

  if (!financeAccess.canViewRevenue && !financeAccess.canViewExpenses) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
    setText("summaryProfit", "—");
    setText("summaryMargin", "—");
    setText("summaryHint", "Нет прав на финансовую сводку");
    return;
  }

  try {
    const summary = await api(`/venues/${encodeURIComponent(venueId)}/finance/summary?month=${encodeURIComponent(monthYYYYMM)}`);
    setText("summaryRevenue", fmtMoneyMinor(summary?.revenue_minor));
    setText("summaryExpenses", fmtMoneyMinor(summary?.expense_minor));
    setText("summaryProfit", fmtMoneyMinor(summary?.profit_minor));
    setText("summaryMargin", fmtPercentBps(summary?.margin_bps));
    setText("summaryPeriodText", `${summary?.period_start || monthYYYYMM} — ${summary?.period_end || monthYYYYMM}`);
    setText("summaryHint", `ФОТ: ${fmtMoneyMinor(summary?.payroll_minor)} · Корректировки: ${fmtMoneyMinor(summary?.adjustments_minor)} · Возвраты: ${fmtMoneyMinor(summary?.refunds_minor)}`);
  } catch (e) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
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

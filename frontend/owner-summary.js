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

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function showBlock(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? "" : "none";
}

function renderList(id, rows, emptyText) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!Array.isArray(rows) || !rows.length) {
    el.innerHTML = `<div class="muted">${esc(emptyText)}</div>`;
    return;
  }
  el.innerHTML = rows.map((row) => `
    <div class="row" style="justify-content:space-between; gap:12px; align-items:flex-start; padding:8px 0; border-bottom:1px solid rgba(255,255,255,.06);">
      <div>
        <div><b>${esc(row.title || row.code || "—")}</b></div>
        ${row.code ? `<div class="muted mt-6">${esc(row.code)}</div>` : ""}
      </div>
      <div style="text-align:right; white-space:nowrap;">${esc(fmtMoneyMinor(row.amount_minor || 0))}</div>
    </div>
  `).join("");
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
}

async function loadSummary(monthYYYYMM, incomeMode) {
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
    renderList("summaryRevenueBreakdown", [], "Нет доступа");
    renderList("summaryExpenseBreakdown", [], "Нет доступа");
    return;
  }

  try {
    const summary = await api(`/venues/${encodeURIComponent(venueId)}/summary/monthly?month=${encodeURIComponent(monthYYYYMM)}&income_mode=${encodeURIComponent(incomeMode)}`);
    setText("summaryRevenue", fmtMoneyMinor(summary?.revenue_minor));
    setText("summaryExpenses", fmtMoneyMinor(summary?.expense_minor));
    setText("summaryProfit", fmtMoneyMinor(summary?.profit_minor));
    setText("summaryMargin", fmtPercentBps(summary?.margin_bps));
    setText("summaryPeriodText", `${summary?.period_start || monthYYYYMM} — ${summary?.period_end || monthYYYYMM}`);
    setText("summaryHint", `ФОТ: ${fmtMoneyMinor(summary?.payroll_minor)} · Корректировки: ${fmtMoneyMinor(summary?.adjustments_minor)} · Возвраты: ${fmtMoneyMinor(summary?.refunds_minor)}`);
    setText("summaryIncomeModeText", String(summary?.income_mode || incomeMode).toUpperCase() === "DEPARTMENTS" ? "Доходы по департаментам" : "Доходы по типам оплат");
    renderList("summaryRevenueBreakdown", summary?.revenue_breakdown || [], "Нет данных по доходам за период");
    renderList("summaryExpenseBreakdown", summary?.expense_categories || [], "Нет признанных расходов за период");
  } catch (e) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
    setText("summaryProfit", "—");
    setText("summaryMargin", "—");
    setText("summaryHint", e?.data?.detail || e.message || "Ошибка загрузки");
    renderList("summaryRevenueBreakdown", [], "Не удалось загрузить");
    renderList("summaryExpenseBreakdown", [], "Не удалось загрузить");
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
  const modePick = document.getElementById("summaryIncomeMode");
  const month = params.get("month") || currentMonth();
  const incomeMode = (params.get("income_mode") || "PAYMENTS").toUpperCase();
  if (monthPick) monthPick.value = month;
  if (modePick) modePick.value = incomeMode;

  const reload = async () => {
    const m = monthPick?.value || currentMonth();
    const mode = (modePick?.value || "PAYMENTS").toUpperCase();
    await loadSummary(m, mode);
  };

  if (monthPick) monthPick.onchange = reload;
  if (modePick) modePick.onchange = reload;

  await reload();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

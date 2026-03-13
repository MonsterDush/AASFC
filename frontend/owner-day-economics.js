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

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function formatDateRu(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "long", year: "numeric" });
}

function formatDateTimeRu(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return String(iso);
  return d.toLocaleString("ru-RU", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderList(id, rows, emptyText, valueFormatter = null) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!Array.isArray(rows) || !rows.length) {
    el.innerHTML = `<div class="muted">${esc(emptyText)}</div>`;
    return;
  }
  el.innerHTML = rows.map((row) => {
    const value = valueFormatter
      ? valueFormatter(row)
      : (row.amount_minor !== undefined ? fmtMoneyMinor(row.amount_minor || 0) : String(row.value_numeric ?? "—"));
    const subtitle = row.subtitle || row.code || row.unit || "";
    return `
      <div class="row" style="justify-content:space-between; gap:12px; align-items:flex-start; padding:8px 0; border-bottom:1px solid rgba(255,255,255,.06);">
        <div>
          <div><b>${esc(row.title || "—")}</b></div>
          ${subtitle ? `<div class="muted mt-6">${esc(subtitle)}</div>` : ""}
        </div>
        <div style="text-align:right; white-space:nowrap;">${esc(value)}</div>
      </div>
    `;
  }).join("");
}

function renderPaymentBalances(rows) {
  renderList("economicsPaymentBalances", rows, "Нет движения по оплатам за день", (row) => {
    const inflow = fmtMoneyMinor(row.inflow_minor || 0);
    const outflow = fmtMoneyMinor(row.outflow_minor || 0);
    const balance = fmtMoneyMinor(row.balance_minor || 0);
    return `${balance} · +${inflow} / -${outflow}`;
  });
}

function buildDraftExpensesLink() {
  const venueId = getActiveVenueId();
  const qp = new URLSearchParams();
  if (venueId) qp.set("venue_id", String(venueId));
  qp.set("month", String((state.date || todayISO()).slice(0, 7)));
  qp.set("statuses", "DRAFT");
  return `/owner-expenses.html?${qp.toString()}`;
}

function buildSummaryLink() {
  const venueId = getActiveVenueId();
  const qp = new URLSearchParams();
  if (venueId) qp.set("venue_id", String(venueId));
  qp.set("period_mode", "DAY");
  qp.set("date", String(state.date || todayISO()));
  qp.set("income_mode", "PAYMENTS");
  return `/owner-summary.html?${qp.toString()}`;
}

const state = {
  date: todayISO(),
  economics: null,
};

const access = {
  canView: false,
};

async function loadAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  try {
    const resp = await getMyVenuePermissions(venueId);
    const role = roleUpper(resp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    const pset = permSetFromResponse(resp);
    access.canView = isOwner || hasPerm(pset, "REVENUE_VIEW") || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD");
  } catch {
    access.canView = false;
  }
}

function renderStatus(econ) {
  const report = econ?.report || {};
  const metrics = econ?.metrics || {};
  const summary = econ?.summary || {};
  const resultStatus = String(metrics.result_status || "BREAKEVEN").toUpperCase();
  const reportStatus = String(report.status || "MISSING").toUpperCase();

  const resultLabel = resultStatus === "PROFIT" ? "Прибыльный день" : resultStatus === "LOSS" ? "Убыточный день" : "День в ноль";
  const reportLabel = reportStatus === "CLOSED" ? "Отчёт закрыт" : reportStatus === "DRAFT" ? "Отчёт в черновике" : "Отчёта нет";
  setText("economicsStatusTitle", `${resultLabel} · ${fmtMoneyMinor(summary.profit_minor || 0)}`);

  let statusHint = reportStatus === "CLOSED"
    ? `Отчёт закрыт ${formatDateTimeRu(report.closed_at)}. Доходы считаются по закрытому дню.`
    : reportStatus === "DRAFT"
      ? "Отчёт за день существует, но ещё не закрыт. Часть управленческих данных может быть неполной."
      : "Закрытого отчёта за день нет. Экономика дня построится только по доступным подтверждённым движениям.";
  if ((report.comment || "").trim()) {
    statusHint += ` Комментарий: ${String(report.comment).trim()}`;
  }
  setText("economicsStatusHint", statusHint);
  setText("economicsResultBadge", resultLabel);
  setText("economicsReportBadge", reportLabel);

  const draftCount = Number(summary.draft_expense_count || 0);
  const draftTotal = Number(summary.draft_expense_total_minor || 0);
  const card = document.getElementById("economicsDraftCard");
  const hint = document.getElementById("economicsDraftHint");
  if (card && hint) {
    if (draftCount > 0) {
      card.style.display = "";
      hint.textContent = `${draftCount} черновик(ов) на сумму ${fmtMoneyMinor(draftTotal)}. Они не участвуют в прибыли дня, пока не подтверждены.`;
    } else {
      card.style.display = "none";
      hint.textContent = "—";
    }
  }
}

function renderEconomics(econ) {
  const summary = econ?.summary || {};
  const report = econ?.report || {};
  const team = econ?.team || {};
  const metrics = econ?.metrics || {};

  renderStatus(econ);
  setText("economicsRevenue", fmtMoneyMinor(summary.revenue_minor || 0));
  setText("economicsExpenses", fmtMoneyMinor(summary.expense_minor || 0));
  setText("economicsProfit", fmtMoneyMinor(summary.profit_minor || 0));
  setText("economicsMargin", fmtPercentBps(summary.margin_bps));
  setText("economicsAssignedUsers", String(team.assigned_user_count || 0));
  setText("economicsRevenuePerAssigned", metrics.revenue_per_assigned_minor == null ? "—" : fmtMoneyMinor(metrics.revenue_per_assigned_minor));
  setText("economicsTipsPerAssigned", metrics.tips_per_assigned_minor == null ? "—" : fmtMoneyMinor(metrics.tips_per_assigned_minor));
  setText("economicsTips", fmtMoneyMinor(report.tips_total_minor || 0));
  setText("economicsExpenseRatio", fmtPercentBps(metrics.expense_ratio_bps));
  setText("economicsPointExpenseRatio", fmtPercentBps(metrics.point_expense_ratio_bps));
  setText("economicsRecurringExpenseRatio", fmtPercentBps(metrics.recurring_expense_ratio_bps));
  setText("economicsPayrollRatio", fmtPercentBps(metrics.payroll_ratio_bps));
  setText("economicsPeriodText", formatDateRu(econ?.date || state.date));
  setText(
    "economicsMetaHint",
    `Команда: ${team.assigned_user_count || 0} сотрудников в ${team.assigned_shift_count || 0} сменах · Чаевые: ${fmtMoneyMinor(report.tips_total_minor || 0)} · Разовые: ${fmtMoneyMinor(summary.point_expense_minor || 0)} · Регулярные: ${fmtMoneyMinor(summary.recurring_expense_minor || 0)}`
  );

  renderList("economicsPaymentRevenueBreakdown", econ?.payment_revenue_breakdown || [], "Нет закрытого денежного прихода за день");
  renderList("economicsDepartmentRevenueBreakdown", econ?.department_revenue_breakdown || [], "Нет аналитических доходов по департаментам за день");
  renderList("economicsPointExpenses", summary?.point_expenses || [], "Нет точечных расходов за день");
  renderList("economicsRecurringExpenses", summary?.recurring_expenses || [], "Нет регулярных расходов на день");
  renderPaymentBalances(summary?.payment_method_balances || []);
  renderList("economicsKpiBreakdown", econ?.kpi_breakdown || [], "Нет KPI-факта за день", (row) => `${Number(row.value_numeric || 0).toLocaleString("ru-RU")} ${row.unit === "PERCENT" ? "%" : row.unit === "MONEY" ? "₽" : ""}`.trim());
}

async function loadEconomics() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  if (!access.canView) {
    toast("Нет прав на экономику дня", "err");
    return;
  }
  try {
    const econ = await api(`/venues/${encodeURIComponent(venueId)}/economics/day?date=${encodeURIComponent(state.date)}`);
    state.economics = econ;
    renderEconomics(econ);
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось загрузить экономику дня", "err");
    setText("economicsStatusTitle", "Не удалось загрузить данные дня");
    setText("economicsStatusHint", err?.data?.detail || err.message || "Ошибка запроса");
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin();
  const venues = await getMyVenues();
  if (!getActiveVenueId() && Array.isArray(venues) && venues.length) setActiveVenueId(venues[0].id);
  await mountNav({ activeTab: "summary" });
  await loadAccess();

  const params = new URLSearchParams(location.search);
  state.date = params.get("date") || todayISO();
  const datePick = document.getElementById("economicsDatePick");
  if (datePick) {
    datePick.value = state.date;
    datePick.onchange = async (e) => {
      state.date = e.target.value || todayISO();
      await loadEconomics();
    };
  }

  const openSummaryBtn = document.getElementById("openSummaryBtn");
  if (openSummaryBtn) openSummaryBtn.onclick = () => { location.href = buildSummaryLink(); };
  const openDraftBtn = document.getElementById("openEconomicsDraftExpensesBtn");
  if (openDraftBtn) openDraftBtn.onclick = () => { location.href = buildDraftExpensesLink(); };
  const refreshBtn = document.getElementById("refreshEconomicsBtn");
  if (refreshBtn) refreshBtn.onclick = async () => { await loadEconomics(); };

  await loadEconomics();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

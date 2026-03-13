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
  if (minor === null || minor === undefined) return "—";
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

function parseMoneyInputToMinor(value) {
  const raw = String(value ?? "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!raw) return null;
  const num = Number(raw);
  if (!Number.isFinite(num)) throw new Error("Неверный денежный формат");
  return Math.round(num * 100);
}

function parsePercentInputToBps(value) {
  const raw = String(value ?? "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!raw) return null;
  const num = Number(raw);
  if (!Number.isFinite(num)) throw new Error("Неверный процентный формат");
  return Math.round(num * 100);
}

function fillValue(form, name, value) {
  const el = form?.elements?.namedItem(name);
  if (!el) return;
  if (el.type === "checkbox") {
    el.checked = Boolean(value);
    return;
  }
  el.value = value ?? "";
}

function fmtDeltaMinor(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value || 0);
  const sign = n > 0 ? "+" : "";
  return `${sign}${fmtMoneyMinor(n)}`;
}

function fmtDeltaInt(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value || 0);
  return `${n > 0 ? "+" : ""}${n}`;
}

const state = {
  date: todayISO(),
  economics: null,
};

const access = {
  canView: false,
  canManage: false,
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
    access.canManage = isOwner;
  } catch {
    access.canView = false;
    access.canManage = false;
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
  if ((report.comment || "").trim()) statusHint += ` Комментарий: ${String(report.comment).trim()}`;
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

function renderAlerts(alerts) {
  const el = document.getElementById("economicsAlerts");
  if (!el) return;
  if (!Array.isArray(alerts) || !alerts.length) {
    el.innerHTML = `<div class="muted">Проблемных сигналов по дню нет.</div>`;
    return;
  }
  el.innerHTML = alerts.map((a) => {
    const sev = String(a.severity || "INFO").toUpperCase();
    const label = sev === "CRITICAL" ? "Критично" : sev === "WARN" ? "Внимание" : "Инфо";
    return `
      <div class="itemcard mt-8">
        <div class="row" style="justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap;">
          <div>
            <b>${esc(a.title || a.code || "Сигнал")}</b>
            <div class="muted mt-6">${esc(a.detail || "")}</div>
          </div>
          <span class="badge">${esc(label)}</span>
        </div>
      </div>
    `;
  }).join("");
}

function renderPlanFact(econ) {
  const plan = econ?.plan || {};
  const pf = econ?.plan_fact || {};
  setText("economicsPlanRevenue", fmtMoneyMinor(plan.revenue_plan_minor));
  setText("economicsPlanRevenueDelta", fmtDeltaMinor(pf.revenue_delta_minor));
  setText("economicsPlanProfit", fmtMoneyMinor(plan.profit_plan_minor));
  setText("economicsPlanProfitDelta", fmtDeltaMinor(pf.profit_delta_minor));
  setText("economicsPlanPerAssigned", fmtMoneyMinor(plan.revenue_per_assigned_plan_minor));
  setText("economicsPlanPerAssignedDelta", fmtDeltaMinor(pf.revenue_per_assigned_delta_minor));
  setText("economicsPlanAssignedTarget", plan.assigned_user_target == null ? "—" : String(plan.assigned_user_target));
  setText("economicsPlanAssignedDelta", fmtDeltaInt(pf.assigned_user_delta));
  setText("economicsPlanNotesView", plan.notes || "План на день не заполнен.");

  const form = document.getElementById("economicsPlanForm");
  if (form) {
    fillValue(form, "revenue_plan", plan.revenue_plan_minor != null ? (Number(plan.revenue_plan_minor) / 100).toFixed(2) : "");
    fillValue(form, "profit_plan", plan.profit_plan_minor != null ? (Number(plan.profit_plan_minor) / 100).toFixed(2) : "");
    fillValue(form, "revenue_per_assigned_plan", plan.revenue_per_assigned_plan_minor != null ? (Number(plan.revenue_per_assigned_plan_minor) / 100).toFixed(2) : "");
    fillValue(form, "assigned_user_target", plan.assigned_user_target ?? "");
    fillValue(form, "notes", plan.notes || "");
  }
}

function renderRules(econ) {
  const rules = econ?.rules || {};
  const form = document.getElementById("economicsRulesForm");
  if (!form) return;
  fillValue(form, "max_expense_ratio_pct", rules.max_expense_ratio_bps != null ? (Number(rules.max_expense_ratio_bps) / 100).toFixed(2) : "");
  fillValue(form, "max_payroll_ratio_pct", rules.max_payroll_ratio_bps != null ? (Number(rules.max_payroll_ratio_bps) / 100).toFixed(2) : "");
  fillValue(form, "min_revenue_per_assigned", rules.min_revenue_per_assigned_minor != null ? (Number(rules.min_revenue_per_assigned_minor) / 100).toFixed(2) : "");
  fillValue(form, "min_assigned_shift_coverage_pct", rules.min_assigned_shift_coverage_bps != null ? (Number(rules.min_assigned_shift_coverage_bps) / 100).toFixed(2) : "");
  fillValue(form, "min_profit", rules.min_profit_minor != null ? (Number(rules.min_profit_minor) / 100).toFixed(2) : "");
  fillValue(form, "warn_on_draft_expenses", rules.warn_on_draft_expenses !== false);
}

function renderRollup(econ) {
  const r = econ?.rollup || {};
  setText("economicsRollupClosedDays", r.closed_day_count == null ? "—" : `${r.closed_day_count} / ${r.days_in_period || 0}`);
  setText("economicsRollupProfitDays", r.profitable_day_count == null ? "—" : String(r.profitable_day_count));
  setText("economicsRollupLossDays", r.loss_day_count == null ? "—" : String(r.loss_day_count));
  setText("economicsRollupProfitTotal", fmtMoneyMinor(r.profit_total_minor));
  setText("economicsRollupAvgProfit", fmtMoneyMinor(r.avg_profit_minor));
  setText("economicsRollupAvgRevenuePerAssigned", fmtMoneyMinor(r.avg_revenue_per_assigned_minor));
  setText(
    "economicsRollupBestDay",
    r.best_day ? `${formatDateRu(r.best_day.date)} · ${fmtMoneyMinor(r.best_day.profit_minor)}` : "—"
  );
  setText(
    "economicsRollupWorstDay",
    r.worst_day ? `${formatDateRu(r.worst_day.date)} · ${fmtMoneyMinor(r.worst_day.profit_minor)}` : "—"
  );
}

function renderEconomics(econ) {
  const summary = econ?.summary || {};
  const report = econ?.report || {};
  const team = econ?.team || {};
  const metrics = econ?.metrics || {};

  renderStatus(econ);
  renderAlerts(econ?.alerts || []);
  renderPlanFact(econ);
  renderRules(econ);
  renderRollup(econ);

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
  renderList(
    "economicsKpiBreakdown",
    econ?.kpi_breakdown || [],
    "Нет KPI-факта за день",
    (row) => `${Number(row.value_numeric || 0).toLocaleString("ru-RU")} ${row.unit === "PERCENT" ? "%" : row.unit === "MONEY" ? "₽" : ""}`.trim()
  );
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

async function savePlan(event) {
  event.preventDefault();
  const venueId = getActiveVenueId();
  if (!venueId || !access.canManage) return;
  try {
    const fd = new FormData(event.currentTarget);
    await api(`/venues/${encodeURIComponent(venueId)}/economics/plan?date=${encodeURIComponent(state.date)}`, {
      method: "PUT",
      body: {
        revenue_plan_minor: parseMoneyInputToMinor(fd.get("revenue_plan")),
        profit_plan_minor: parseMoneyInputToMinor(fd.get("profit_plan")),
        revenue_per_assigned_plan_minor: parseMoneyInputToMinor(fd.get("revenue_per_assigned_plan")),
        assigned_user_target: fd.get("assigned_user_target") ? Number(fd.get("assigned_user_target")) : null,
        notes: String(fd.get("notes") || "").trim() || null,
      },
    });
    toast("План дня сохранён", "ok");
    await loadEconomics();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось сохранить план дня", "err");
  }
}

async function saveRules(event) {
  event.preventDefault();
  const venueId = getActiveVenueId();
  if (!venueId || !access.canManage) return;
  try {
    const fd = new FormData(event.currentTarget);
    await api(`/venues/${encodeURIComponent(venueId)}/economics/rules`, {
      method: "PUT",
      body: {
        max_expense_ratio_bps: parsePercentInputToBps(fd.get("max_expense_ratio_pct")),
        max_payroll_ratio_bps: parsePercentInputToBps(fd.get("max_payroll_ratio_pct")),
        min_revenue_per_assigned_minor: parseMoneyInputToMinor(fd.get("min_revenue_per_assigned")),
        min_assigned_shift_coverage_bps: parsePercentInputToBps(fd.get("min_assigned_shift_coverage_pct")),
        min_profit_minor: parseMoneyInputToMinor(fd.get("min_profit")),
        warn_on_draft_expenses: fd.get("warn_on_draft_expenses") === "on",
      },
    });
    toast("Нормативы сохранены", "ok");
    await loadEconomics();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось сохранить нормативы", "err");
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

  const manageBlock = document.getElementById("economicsManageBlock");
  if (manageBlock) manageBlock.style.display = access.canManage ? "" : "none";

  const openSummaryBtn = document.getElementById("openSummaryBtn");
  if (openSummaryBtn) openSummaryBtn.onclick = () => { location.href = buildSummaryLink(); };
  const openDraftBtn = document.getElementById("openEconomicsDraftExpensesBtn");
  if (openDraftBtn) openDraftBtn.onclick = () => { location.href = buildDraftExpensesLink(); };
  const refreshBtn = document.getElementById("refreshEconomicsBtn");
  if (refreshBtn) refreshBtn.onclick = async () => { await loadEconomics(); };
  const planForm = document.getElementById("economicsPlanForm");
  if (planForm) planForm.addEventListener("submit", savePlan);
  const rulesForm = document.getElementById("economicsRulesForm");
  if (rulesForm) rulesForm.addEventListener("submit", saveRules);

  await loadEconomics();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

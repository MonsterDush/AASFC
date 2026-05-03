import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  getMyVenuePermissions,
  getVenueSettings,
  api,
  toast,
  coerceDemoDate,
  applyDemoReadonlyCaps,
  getStoredDemoUiState,
  isDemoUiMode,
  getDemoMonthLabel,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js";

let financialValuesHidden = false;


const DEMO_OWNER_DAY_ECONOMICS_INTRO_DISMISSED_KEY = "axelio.demo_intro.owner_day_economics.dismissed";
const LS_DAY_ECONOMICS_SHIFT_SLOT = "axelio.dayEconomics.shiftSlot";

function normalizeEconomicsShiftSlot(value) {
  const slot = String(value || "TOTAL").trim().toUpperCase();
  if (slot === "DAY" || slot === "NIGHT") return slot;
  return "TOTAL";
}

function economicsShiftSlotLabel(slot = state.shiftSlot) {
  const normalized = normalizeEconomicsShiftSlot(slot);
  if (normalized === "DAY") return "День";
  if (normalized === "NIGHT") return "Ночь";
  return "Итого";
}

function updateEconomicsSlotUrl() {
  try {
    const q = new URLSearchParams(location.search);
    q.set("date", String(state.date || todayISO()));
    if (state.nightShiftsEnabled && normalizeEconomicsShiftSlot(state.shiftSlot) !== "TOTAL") {
      q.set("shift_slot", normalizeEconomicsShiftSlot(state.shiftSlot));
    } else {
      q.delete("shift_slot");
    }
    const next = `${location.pathname}?${q.toString()}${location.hash || ""}`;
    history.replaceState(null, "", next);
  } catch {}
}

function renderEconomicsSlotToggle() {
  const box = document.getElementById("economicsSlotToggle");
  if (!box) return;
  const shouldShow = !!state.nightShiftsEnabled;
  box.classList.toggle("hidden", !shouldShow);
  if (!shouldShow) state.shiftSlot = "TOTAL";

  document.getElementById("economicsSlotTotal")?.classList.toggle("active", state.shiftSlot === "TOTAL");
  document.getElementById("economicsSlotDay")?.classList.toggle("active", state.shiftSlot === "DAY");
  document.getElementById("economicsSlotNight")?.classList.toggle("active", state.shiftSlot === "NIGHT");
}

async function switchEconomicsShiftSlot(slot) {
  const next = normalizeEconomicsShiftSlot(slot);
  if (!state.nightShiftsEnabled && next !== "TOTAL") return;
  if (next === state.shiftSlot) return;
  state.shiftSlot = next;
  try { localStorage.setItem(LS_DAY_ECONOMICS_SHIFT_SLOT, state.shiftSlot); } catch {}
  renderEconomicsSlotToggle();
  updateEconomicsSlotUrl();
  await loadEconomics();
}

function setupDemoDayEconomicsIntro() {
  const intro = document.getElementById("demoOwnerDayEconomicsIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) { intro.classList.add("hidden"); return; }
  try {
    if (sessionStorage.getItem(DEMO_OWNER_DAY_ECONOMICS_INTRO_DISMISSED_KEY) === "1") {
      intro.classList.add("hidden");
      return;
    }
  } catch {}
  const textEl = document.getElementById("demoOwnerDayEconomicsIntroText");
  if (textEl) textEl.textContent = `Экономика дня показывает управленческий срез внутри ${getDemoMonthLabel(demoState) || 'DEMO-месяца'}: план/факт, сигналы и rollup месяца к выбранной дате.`;
  document.getElementById("demoOwnerDayEconomicsGoSummary")?.addEventListener("click", () => { location.href = buildSummaryLink(); });
  document.getElementById("demoOwnerDayEconomicsGoRevenue")?.addEventListener("click", () => { const venueId = getActiveVenueId(); if (venueId) location.href = `/owner-turnover.html?venue_id=${encodeURIComponent(String(venueId))}&month=${encodeURIComponent(String((state.date || todayISO()).slice(0,7)))}`; });
  document.getElementById("demoOwnerDayEconomicsIntroClose")?.addEventListener("click", () => {
    intro.classList.add("hidden");
    try { sessionStorage.setItem(DEMO_OWNER_DAY_ECONOMICS_INTRO_DISMISSED_KEY, "1"); } catch {}
  });
  intro.classList.remove("hidden");
}

function fmtMoneyMinor(minor) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
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
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
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
  return coerceDemoDate(`${y}-${m}-${day}`, { notify: false, context: "owner-day-economics" });
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

function buildPlansPageLink() {
  const venueId = getActiveVenueId();
  const qp = new URLSearchParams();
  if (venueId) qp.set("venue_id", String(venueId));
  qp.set("date", String(state.date || todayISO()));
  return `/owner-economics-plans.html?${qp.toString()}`;
}

function buildRulesPageLink() {
  const venueId = getActiveVenueId();
  const qp = new URLSearchParams();
  if (venueId) qp.set("venue_id", String(venueId));
  return `/owner-economics-rules.html?${qp.toString()}`;
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

function dayKindLabel(kind) {
  const key = String(kind || '').toUpperCase();
  if (key === 'HOLIDAY') return 'Праздник';
  if (key === 'SPECIAL') return 'Спец-день';
  return '';
}

const state = {
  date: todayISO(),
  shiftSlot: "TOTAL",
  nightShiftsEnabled: false,
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
    financialValuesHidden = isFinancialValuesHidden(resp);
    const role = roleUpper(resp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    const pset = permSetFromResponse(resp);
    Object.assign(access, applyDemoReadonlyCaps({
      canView: isOwner || hasPerm(pset, "REVENUE_VIEW") || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD"),
      canManage: isOwner,
    }, { source: resp }));
  } catch {
    access.canView = false;
    access.canManage = false;
  }
}

async function loadVenueEconomicsSettings() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  try {
    const settings = await getVenueSettings(venueId);
    state.nightShiftsEnabled = !!settings?.night_shifts_enabled;
  } catch {
    state.nightShiftsEnabled = false;
  }
  if (!state.nightShiftsEnabled) state.shiftSlot = "TOTAL";
  renderEconomicsSlotToggle();
  updateEconomicsSlotUrl();
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
      hint.textContent = `${draftCount} неподтверждённых расходов на сумму ${fmtMoneyMinor(draftTotal)}. Они не участвуют в прибыли дня, пока не подтверждены.`;
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

  const source = String(plan.source || "NONE").toUpperCase();
  const kind = dayKindLabel(plan?.day_kind);
  const title = String(plan?.title || "").trim();

  const planNotes = [kind, title, plan.notes].filter(Boolean).join(" · ");
  setText("economicsPlanNotesView", planNotes || "План на день не заполнен.");

  let sourceText = "План не задан";
  if (source === "DATE_OVERRIDE") {
    sourceText = `Используется отдельный план на дату ${formatDateRu(plan.date)}${kind ? ` · ${kind}` : ""}${title ? ` · ${title}` : ""}`;
  } else if (source === "MONTH_TEMPLATE") {
    sourceText = `Используется план на месяц ${plan.template_month_title || plan.template_month || "месяц"}`;
  } else if (source === "WEEKDAY_TEMPLATE") {
    sourceText = `Используется шаблон: ${plan.template_weekday_title || "день недели"}`;
  }

  setText("economicsPlanSourceHint", sourceText);
}


function renderRules(econ) {
  const rules = econ?.rules || {};
  const parts = [];
  if (rules.max_expense_ratio_bps != null) parts.push(`расходы ≤ ${fmtPercentBps(rules.max_expense_ratio_bps)}`);
  if (rules.max_payroll_ratio_bps != null) parts.push(`ФОТ ≤ ${fmtPercentBps(rules.max_payroll_ratio_bps)}`);
  if (rules.min_revenue_per_assigned_minor != null) parts.push(`выручка/сотрудник ≥ ${fmtMoneyMinor(rules.min_revenue_per_assigned_minor)}`);
  if (rules.min_assigned_shift_coverage_bps != null) parts.push(`покрытие смен ≥ ${fmtPercentBps(rules.min_assigned_shift_coverage_bps)}`);
  if (rules.min_profit_minor != null) parts.push(`прибыль ≥ ${fmtMoneyMinor(rules.min_profit_minor)}`);
  if (rules.warn_on_draft_expenses) parts.push(`предупреждать о неподтверждённых расходах`);
  setText("economicsRulesHint", parts.length ? parts.join(" · ") : "Нормативы ещё не заданы.");
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

  setText("title", `Экономика дня · ${economicsShiftSlotLabel(econ?.shift_slot || state.shiftSlot)}`);
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
  setText("economicsPeriodText", `${formatDateRu(econ?.date || state.date)} · ${economicsShiftSlotLabel(econ?.shift_slot || state.shiftSlot)}`);
  const slotCostsHint = summary.slot_costs_available === false
    ? " · Расходы и ФОТ по слотам пока не распределяются, смотри «Итого»"
    : "";
  setText(
    "economicsMetaHint",
    `Команда: ${team.assigned_user_count || 0} сотрудников в ${team.assigned_shift_count || 0} сменах · Чаевые: ${fmtMoneyMinor(report.tips_total_minor || 0)} · Разовые: ${fmtMoneyMinor(summary.point_expense_minor || 0)} · Регулярные: ${fmtMoneyMinor(summary.recurring_expense_minor || 0)}${slotCostsHint}`
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
    const econ = await api(`/venues/${encodeURIComponent(venueId)}/economics/day?date=${encodeURIComponent(state.date)}&shift_slot=${encodeURIComponent(normalizeEconomicsShiftSlot(state.shiftSlot))}`);
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
  setupDemoDayEconomicsIntro();

  const params = new URLSearchParams(location.search);
  state.date = coerceDemoDate(params.get("date") || todayISO(), { notify: false, context: "owner-day-economics" });
  state.shiftSlot = normalizeEconomicsShiftSlot(params.get("shift_slot") || localStorage.getItem(LS_DAY_ECONOMICS_SHIFT_SLOT) || "TOTAL");
  await loadVenueEconomicsSettings();

  const datePick = document.getElementById("economicsDatePick");
  if (datePick) {
    datePick.value = state.date;
    datePick.onchange = async (e) => {
      state.date = coerceDemoDate(e.target.value || todayISO(), { context: "owner-day-economics" });
      updateEconomicsSlotUrl();
      await loadEconomics();
    };
  }

  const manageBlock = document.getElementById("economicsManageBlock");
  if (manageBlock) manageBlock.style.display = access.canManage ? "" : "none";

  const openSummaryBtn = document.getElementById("openSummaryBtn");
  if (openSummaryBtn) openSummaryBtn.onclick = () => { location.href = buildSummaryLink(); };
  const openDraftBtn = document.getElementById("openEconomicsDraftExpensesBtn");
  if (openDraftBtn) openDraftBtn.onclick = () => { location.href = buildDraftExpensesLink(); };
  const openPlansBtn = document.getElementById("openPlanTemplatesBtn");
  if (openPlansBtn) openPlansBtn.onclick = () => { location.href = buildPlansPageLink(); };
  const openPlansBtnCard = document.getElementById("openPlanTemplatesBtnCard");
  if (openPlansBtnCard) openPlansBtnCard.onclick = () => { location.href = buildPlansPageLink(); };
  const openRulesBtn = document.getElementById("openEconomicsRulesBtn");
  if (openRulesBtn) openRulesBtn.onclick = () => { location.href = buildRulesPageLink(); };
  const openRulesBtnCard = document.getElementById("openEconomicsRulesBtnCard");
  if (openRulesBtnCard) openRulesBtnCard.onclick = () => { location.href = buildRulesPageLink(); };
  document.getElementById("economicsSlotTotal")?.addEventListener("click", () => { switchEconomicsShiftSlot("TOTAL"); });
  document.getElementById("economicsSlotDay")?.addEventListener("click", () => { switchEconomicsShiftSlot("DAY"); });
  document.getElementById("economicsSlotNight")?.addEventListener("click", () => { switchEconomicsShiftSlot("NIGHT"); });

  const refreshBtn = document.getElementById("refreshEconomicsBtn");
  if (refreshBtn) refreshBtn.onclick = async () => { await loadEconomics(); };

  await loadEconomics();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

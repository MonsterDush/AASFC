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
} from "/app.js?v=20260726-navmore1";
import { permSetFromResponse, roleUpper, hasPerm, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js";
import {
  formatComparisonRange,
  resolveAutoComparison,
  resolveComparisonRange,
} from "/app/period-comparison.js?v=20260802-financeux2";

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

function economicsProfitAvailable(econ) {
  return econ?.summary?.slot_profit_available !== false;
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
    q.set("compare_mode", state.compareMode);
    if (state.compareMode === "custom" && state.compareDate) {
      q.set("compare_date", state.compareDate);
    } else {
      q.delete("compare_date");
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

function setEconomicsLoading(isLoading) {
  document.body.classList.toggle("is-loading", !!isLoading);
  document.getElementById("economicsContent")?.setAttribute("aria-busy", isLoading ? "true" : "false");
}

function showEconomicsPageState(kind, title, detail, { hideContent = false } = {}) {
  const stateEl = document.getElementById("economicsPageState");
  const content = document.getElementById("economicsContent");
  if (stateEl) {
    stateEl.className = `finance-page-state finance-page-state--${kind}`;
    stateEl.innerHTML = `<b>${esc(title)}</b><span>${esc(detail)}</span>`;
  }
  content?.classList.toggle("hidden", hideContent);
}

function hideEconomicsPageState() {
  document.getElementById("economicsPageState")?.classList.add("hidden");
  document.getElementById("economicsContent")?.classList.remove("hidden");
}

function renderList(id, rows, emptyText, valueFormatter = null) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!Array.isArray(rows) || !rows.length) {
    el.innerHTML = `<div class="economics-state">${esc(emptyText)}</div>`;
    return;
  }
  el.innerHTML = rows.map((row) => {
    const value = valueFormatter
      ? valueFormatter(row)
      : (row.amount_minor !== undefined ? fmtMoneyMinor(row.amount_minor || 0) : String(row.value_numeric ?? "—"));
    const subtitle = row.subtitle || row.code || row.unit || "";
    return `
      <div class="row row--between gap-12 ai-start summary-list-row">
        <div>
          <div><b>${esc(row.title || "—")}</b></div>
          ${subtitle ? `<div class="muted mt-6">${esc(subtitle)}</div>` : ""}
        </div>
        <div class="summary-list-value">${esc(value)}</div>
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

function buildLedgerLink() {
  const venueId = getActiveVenueId();
  const qp = new URLSearchParams();
  if (venueId) qp.set("venue_id", String(venueId));
  qp.set("month", String((state.date || todayISO()).slice(0, 7)));
  return `/owner-finance-ledger.html?${qp.toString()}`;
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
  comparisonEconomics: null,
  comparisonError: null,
  compareMode: "auto",
  compareDate: "",
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
  const profitAvailable = economicsProfitAvailable(econ);
  const slotSpecific = normalizeEconomicsShiftSlot(econ?.shift_slot || state.shiftSlot) !== "TOTAL";

  const resultLabel = profitAvailable
    ? (
      resultStatus === "PROFIT"
        ? (slotSpecific ? "Прибыльная смена" : "Прибыльный день")
        : resultStatus === "LOSS"
          ? (slotSpecific ? "Убыточная смена" : "Убыточный день")
          : `${slotSpecific ? "Смена" : "День"} в ноль`
    )
    : "Доход выбранного слота";
  const reportLabel = reportStatus === "CLOSED" ? "Отчёт закрыт" : reportStatus === "DRAFT" ? "Отчёт в черновике" : "Отчёта нет";
  setText(
    "economicsStatusTitle",
    `${resultLabel} · ${fmtMoneyMinor(profitAvailable ? summary.profit_minor : summary.revenue_minor)}`
  );

  let statusHint = reportStatus === "CLOSED"
    ? `Отчёт закрыт ${formatDateTimeRu(report.closed_at)}. Доходы считаются по закрытому дню.`
    : reportStatus === "DRAFT"
      ? "Отчёт за день существует, но ещё не закрыт. Часть управленческих данных может быть неполной."
      : "Закрытого отчёта за день нет. Экономика дня построится только по доступным подтверждённым движениям.";
  if (!profitAvailable) {
    statusHint += " Прибыль и расходы доступны в режиме «Итого», поскольку затраты пока не распределяются между слотами.";
  }
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
      card.classList.remove("hidden");
      hint.textContent = `${draftCount} неподтверждённых расходов на сумму ${fmtMoneyMinor(draftTotal)}. Они не участвуют в прибыли дня, пока не подтверждены.`;
    } else {
      card.classList.add("hidden");
      hint.textContent = "—";
    }
  }
}

function renderAlerts(alerts) {
  const el = document.getElementById("economicsAlerts");
  if (!el) return;
  if (!Array.isArray(alerts) || !alerts.length) {
    el.innerHTML = `<div class="economics-state">Проблемных сигналов по дню нет.</div>`;
    return;
  }
  el.innerHTML = alerts.map((a) => {
    const sev = String(a.severity || "INFO").toUpperCase();
    const label = sev === "CRITICAL" ? "Критично" : sev === "WARN" ? "Внимание" : "Инфо";
    return `
      <div class="itemcard economics-alert">
        <div class="row row--between gap-12 ai-center wrap">
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
  const comparisonAvailable = pf.comparison_available !== false;

  setText("economicsPlanRevenue", fmtMoneyMinor(plan.revenue_plan_minor));
  setText("economicsPlanRevenueDelta", comparisonAvailable ? fmtDeltaMinor(pf.revenue_delta_minor) : "—");
  setText("economicsPlanProfit", fmtMoneyMinor(plan.profit_plan_minor));
  setText("economicsPlanProfitDelta", comparisonAvailable ? fmtDeltaMinor(pf.profit_delta_minor) : "—");
  setText("economicsPlanPerAssigned", fmtMoneyMinor(plan.revenue_per_assigned_plan_minor));
  setText("economicsPlanPerAssignedDelta", comparisonAvailable ? fmtDeltaMinor(pf.revenue_per_assigned_delta_minor) : "—");
  setText("economicsPlanAssignedTarget", plan.assigned_user_target == null ? "—" : String(plan.assigned_user_target));
  setText("economicsPlanAssignedDelta", comparisonAvailable ? fmtDeltaInt(pf.assigned_user_delta) : "—");

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
  if (!comparisonAvailable) {
    sourceText += " · План задан на дату целиком, сравнение отдельного слота отключено";
  } else if (plan.allocated_from_total) {
    sourceText += " · Общий план даты распределён между дневной и ночной сменами";
  }

  setText("economicsPlanSourceHint", sourceText);
}


function renderRules(econ) {
  const rules = econ?.rules || {};
  const parts = [];
  const profitAvailable = economicsProfitAvailable(econ);
  if (profitAvailable && rules.max_expense_ratio_bps != null) parts.push(`Расходы ≤ ${fmtPercentBps(rules.max_expense_ratio_bps)}`);
  if (profitAvailable && rules.max_payroll_ratio_bps != null) parts.push(`ФОТ ≤ ${fmtPercentBps(rules.max_payroll_ratio_bps)}`);
  if (profitAvailable && rules.min_revenue_per_assigned_minor != null) parts.push(`Выручка/сотрудник ≥ ${fmtMoneyMinor(rules.min_revenue_per_assigned_minor)}`);
  if (rules.min_assigned_shift_coverage_bps != null) parts.push(`Покрытие смен ≥ ${fmtPercentBps(rules.min_assigned_shift_coverage_bps)}`);
  if (profitAvailable && rules.min_profit_minor != null) parts.push(`Прибыль ≥ ${fmtMoneyMinor(rules.min_profit_minor)}`);
  if (profitAvailable && rules.warn_on_draft_expenses) parts.push(`Предупреждать о неподтверждённых расходах`);
  if (!profitAvailable) parts.push("Финансовые нормативы применяются в «Итого»");
  setText("economicsRulesHint", parts.length ? parts.join(" · ") : "Нормативы ещё не заданы.");
}


function renderRollup(econ) {
  const r = econ?.rollup || {};
  const profitAvailable = r.profit_available !== false;
  setText("economicsRollupClosedDays", r.closed_day_count == null ? "—" : `${r.closed_day_count} / ${r.days_in_period || 0}`);
  setText("economicsRollupProfitDays", profitAvailable && r.profitable_day_count != null ? String(r.profitable_day_count) : "—");
  setText("economicsRollupLossDays", profitAvailable && r.loss_day_count != null ? String(r.loss_day_count) : "—");
  setText("economicsRollupProfitTotal", profitAvailable ? fmtMoneyMinor(r.profit_total_minor) : "—");
  setText("economicsRollupAvgProfit", profitAvailable ? fmtMoneyMinor(r.avg_profit_minor) : "—");
  setText("economicsRollupAvgRevenuePerAssigned", fmtMoneyMinor(r.avg_revenue_per_assigned_minor));
  setText(
    "economicsRollupBestDay",
    profitAvailable && r.best_day ? `${formatDateRu(r.best_day.date)} · ${fmtMoneyMinor(r.best_day.profit_minor)}` : "—"
  );
  setText(
    "economicsRollupWorstDay",
    profitAvailable && r.worst_day ? `${formatDateRu(r.worst_day.date)} · ${fmtMoneyMinor(r.worst_day.profit_minor)}` : "—"
  );
}

function renderEconomics(econ) {
  const summary = econ?.summary || {};
  const report = econ?.report || {};
  const team = econ?.team || {};
  const metrics = econ?.metrics || {};
  const profitAvailable = economicsProfitAvailable(econ);

  renderStatus(econ);
  renderAlerts(econ?.alerts || []);
  renderPlanFact(econ);
  renderRules(econ);
  renderRollup(econ);

  setText("title", `Экономика дня · ${economicsShiftSlotLabel(econ?.shift_slot || state.shiftSlot)}`);
  setText("economicsRevenue", fmtMoneyMinor(summary.revenue_minor || 0));
  setText("economicsExpenses", profitAvailable ? fmtMoneyMinor(summary.expense_minor || 0) : "—");
  setText("economicsProfit", profitAvailable ? fmtMoneyMinor(summary.profit_minor || 0) : "—");
  setText("economicsMargin", profitAvailable ? fmtPercentBps(summary.margin_bps) : "—");
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

function currentComparison() {
  return resolveComparisonRange({
    compareMode: state.compareMode,
    compareFrom: state.compareDate,
    compareTo: state.compareDate,
    period: "day",
    day: state.date,
  });
}

function syncComparisonControls() {
  const comparison = currentComparison();
  const custom = state.compareMode === "custom";
  const disabled = state.compareMode === "none";
  document.getElementById("economicsCompareControls")?.classList.toggle("hidden", !custom);
  document.querySelectorAll("#economicsCompareSeg button").forEach((button) => {
    button.classList.toggle("active", button.dataset.compare === state.compareMode);
  });
  setText("economicsComparePeriodText", disabled ? "Сравнение отключено" : formatComparisonRange(comparison));
  setText("economicsCompareHint", disabled ? "Дополнительный день не загружается." : (comparison?.caption || "Выбери день сравнения"));
  const picker = document.getElementById("economicsCompareDatePick");
  if (custom && picker) picker.value = comparison?.from || state.compareDate || "";
}

function signedMinor(minor) {
  const amount = Number(minor || 0);
  const sign = amount > 0 ? "+" : amount < 0 ? "−" : "";
  return `${sign}${fmtMoneyMinor(Math.abs(amount))}`;
}

function economicsDeltaView(currentValue, previousValue, { type = "money", goodWhen = "neutral" } = {}) {
  if (previousValue === null || previousValue === undefined) return null;
  const current = Number(currentValue || 0);
  const previous = Number(previousValue || 0);
  const delta = current - previous;
  const good = (goodWhen === "up" && delta > 0) || (goodWhen === "down" && delta < 0);
  const bad = (goodWhen === "up" && delta < 0) || (goodWhen === "down" && delta > 0);
  const tone = good ? "is-good" : bad ? "is-bad" : "is-neutral";
  if (type === "bps") {
    const points = delta / 100;
    const sign = points > 0 ? "+" : points < 0 ? "−" : "";
    return {
      text: `${sign}${Math.abs(points).toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} п.п.`,
      tone,
    };
  }
  const absolute = type === "count"
    ? `${delta > 0 ? "+" : ""}${delta.toLocaleString("ru-RU")}`
    : signedMinor(delta);
  if (previous === 0) {
    return { text: current === 0 ? "Без изменений" : `Нет базы · ${absolute}`, tone };
  }
  const percent = delta / Math.abs(previous) * 100;
  const sign = percent > 0 ? "+" : percent < 0 ? "−" : "";
  return {
    text: `${sign}${Math.abs(percent).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% · ${absolute}`,
    tone,
  };
}

function renderEconomicsMetricDelta(id, currentValue, previousValue, options = {}) {
  const element = document.getElementById(id);
  if (!element) return;
  element.classList.remove("is-good", "is-bad", "is-neutral");
  if (financialValuesHidden || !state.comparisonEconomics) {
    element.textContent = state.comparisonError ? "Сравнение недоступно" : "—";
    element.classList.add("is-neutral");
    return;
  }
  const view = economicsDeltaView(currentValue, previousValue, options);
  element.textContent = view ? `${view.text} ${currentComparison()?.caption || ""}`.trim() : "—";
  element.classList.add(view?.tone || "is-neutral");
}

function renderEconomicsComparison(econ, comparison) {
  const summary = econ?.summary || {};
  const previousSummary = comparison?.summary || {};
  const metrics = econ?.metrics || {};
  const previousMetrics = comparison?.metrics || {};
  const report = econ?.report || {};
  const previousReport = comparison?.report || {};
  const team = econ?.team || {};
  const previousTeam = comparison?.team || {};
  const profitComparable = economicsProfitAvailable(econ) && economicsProfitAvailable(comparison);

  renderEconomicsMetricDelta("economicsRevenueDelta", summary.revenue_minor, previousSummary.revenue_minor, { goodWhen: "up" });
  renderEconomicsMetricDelta("economicsExpensesDelta", profitComparable ? summary.expense_minor : null, profitComparable ? previousSummary.expense_minor : null, { goodWhen: "down" });
  renderEconomicsMetricDelta("economicsProfitDelta", profitComparable ? summary.profit_minor : null, profitComparable ? previousSummary.profit_minor : null, { goodWhen: "up" });
  renderEconomicsMetricDelta("economicsMarginDelta", profitComparable ? summary.margin_bps : null, profitComparable ? previousSummary.margin_bps : null, { type: "bps", goodWhen: "up" });
  renderEconomicsMetricDelta("economicsAssignedUsersDelta", team.assigned_user_count, previousTeam.assigned_user_count, { type: "count" });
  renderEconomicsMetricDelta("economicsRevenuePerAssignedDelta", metrics.revenue_per_assigned_minor, previousMetrics.revenue_per_assigned_minor, { goodWhen: "up" });
  renderEconomicsMetricDelta("economicsTipsPerAssignedDelta", metrics.tips_per_assigned_minor, previousMetrics.tips_per_assigned_minor, { goodWhen: "up" });
  renderEconomicsMetricDelta("economicsTipsDelta", report.tips_total_minor, previousReport.tips_total_minor, { goodWhen: "up" });
  renderEconomicsMetricDelta("economicsExpenseRatioDelta", profitComparable ? metrics.expense_ratio_bps : null, profitComparable ? previousMetrics.expense_ratio_bps : null, { type: "bps", goodWhen: "down" });
  renderEconomicsMetricDelta("economicsPointExpenseRatioDelta", profitComparable ? metrics.point_expense_ratio_bps : null, profitComparable ? previousMetrics.point_expense_ratio_bps : null, { type: "bps", goodWhen: "down" });
  renderEconomicsMetricDelta("economicsRecurringExpenseRatioDelta", profitComparable ? metrics.recurring_expense_ratio_bps : null, profitComparable ? previousMetrics.recurring_expense_ratio_bps : null, { type: "bps", goodWhen: "down" });
  renderEconomicsMetricDelta("economicsPayrollRatioDelta", profitComparable ? metrics.payroll_ratio_bps : null, profitComparable ? previousMetrics.payroll_ratio_bps : null, { type: "bps", goodWhen: "down" });
}

async function loadEconomics() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  if (!access.canView) {
    setEconomicsLoading(false);
    showEconomicsPageState(
      "denied",
      "Нет доступа к экономике дня",
      "Обратитесь к владельцу заведения, чтобы получить право просмотра финансовых данных.",
      { hideContent: true },
    );
    return;
  }
  setEconomicsLoading(true);
  hideEconomicsPageState();
  syncComparisonControls();
  updateEconomicsSlotUrl();
  try {
    const comparison = currentComparison();
    const primaryPromise = api(`/venues/${encodeURIComponent(venueId)}/economics/day?date=${encodeURIComponent(state.date)}&shift_slot=${encodeURIComponent(normalizeEconomicsShiftSlot(state.shiftSlot))}`);
    const comparisonPromise = comparison
      ? api(`/venues/${encodeURIComponent(venueId)}/economics/day?date=${encodeURIComponent(comparison.from)}&shift_slot=${encodeURIComponent(normalizeEconomicsShiftSlot(state.shiftSlot))}`)
          .then((value) => ({ value }))
          .catch((error) => ({ error }))
      : Promise.resolve({ value: null });
    const [econ, comparisonResult] = await Promise.all([primaryPromise, comparisonPromise]);
    state.economics = econ;
    state.comparisonEconomics = comparisonResult.value || null;
    state.comparisonError = comparisonResult.error || null;
    renderEconomics(econ);
    renderEconomicsComparison(econ, state.comparisonEconomics);
    hideEconomicsPageState();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось загрузить экономику дня", "err");
    setText("economicsStatusTitle", "Не удалось загрузить данные дня");
    setText("economicsStatusHint", err?.data?.detail || err.message || "Ошибка запроса");
    showEconomicsPageState(
      "error",
      "Не удалось обновить экономику дня",
      err?.data?.detail || err.message || "Повторите попытку позже.",
    );
  } finally {
    setEconomicsLoading(false);
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
  if (!access.canView) {
    setEconomicsLoading(false);
    showEconomicsPageState(
      "denied",
      "Нет доступа к экономике дня",
      "Обратитесь к владельцу заведения, чтобы получить право просмотра финансовых данных.",
      { hideContent: true },
    );
    return;
  }
  setupDemoDayEconomicsIntro();

  const params = new URLSearchParams(location.search);
  state.date = coerceDemoDate(params.get("date") || todayISO(), { notify: false, context: "owner-day-economics" });
  state.shiftSlot = normalizeEconomicsShiftSlot(params.get("shift_slot") || localStorage.getItem(LS_DAY_ECONOMICS_SHIFT_SLOT) || "TOTAL");
  state.compareMode = ["auto", "custom", "none"].includes(params.get("compare_mode")) ? params.get("compare_mode") : "auto";
  state.compareDate = params.get("compare_date") || "";
  await loadVenueEconomicsSettings();
  if (!state.compareDate) {
    state.compareDate = resolveAutoComparison({ period: "day", day: state.date })?.from || state.date;
  }
  syncComparisonControls();

  const datePick = document.getElementById("economicsDatePick");
  if (datePick) {
    datePick.value = state.date;
    datePick.onchange = async (e) => {
      state.date = coerceDemoDate(e.target.value || todayISO(), { context: "owner-day-economics" });
      const ledgerLink = document.getElementById("openLedgerBtn");
      if (ledgerLink) ledgerLink.href = buildLedgerLink();
      updateEconomicsSlotUrl();
      await loadEconomics();
    };
  }

  const manageBlock = document.getElementById("economicsManageBlock");
  manageBlock?.classList.toggle("hidden", !access.canManage);

  const openSummaryBtn = document.getElementById("openSummaryBtn");
  if (openSummaryBtn) openSummaryBtn.onclick = () => { location.href = buildSummaryLink(); };
  const openLedgerBtn = document.getElementById("openLedgerBtn");
  if (openLedgerBtn) openLedgerBtn.href = buildLedgerLink();
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

  document.querySelectorAll("#economicsCompareSeg button").forEach((button) => {
    button.addEventListener("click", async () => {
      const requestedMode = button.dataset.compare;
      const mode = ["auto", "custom", "none"].includes(requestedMode) ? requestedMode : "auto";
      if (mode === "custom" && state.compareMode !== "custom") {
        state.compareDate = resolveAutoComparison({ period: "day", day: state.date })?.from || state.date;
      }
      state.compareMode = mode;
      syncComparisonControls();
      updateEconomicsSlotUrl();
      if (mode !== "custom") await loadEconomics();
    });
  });
  document.getElementById("economicsCompareDatePick")?.addEventListener("change", (event) => {
    state.compareDate = event.target.value || state.compareDate;
  });
  document.getElementById("economicsCompareApply")?.addEventListener("click", async () => {
    const value = String(state.compareDate || "");
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) {
      toast("Выбери день сравнения", "err");
      return;
    }
    updateEconomicsSlotUrl();
    await loadEconomics();
  });

  const refreshBtn = document.getElementById("refreshEconomicsBtn");
  if (refreshBtn) refreshBtn.onclick = async () => { await loadEconomics(); };

  await loadEconomics();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

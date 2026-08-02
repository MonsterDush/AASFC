import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenuePermissions,
  getPaymentMethods,
  API_BASE,
  api,
  toast,
  getStoredDemoUiState,
  isDemoUiMode,
  getDemoMonthLabel,
} from "/app.js?v=20260726-navmore1";
import { permSetFromResponse, roleUpper, hasPerm, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js";
import {
  formatComparisonRange,
  monthRange,
  normalizeIsoRange,
  resolveComparisonRange,
} from "/app/period-comparison.js?v=20260802-financeux2";
import {
  buildLedgerSourceDrilldown,
  buildLedgerDailySeries,
  buildLedgerStructure,
  ledgerKindLabel,
} from "/app/finance-ledger-analytics.js?v=20260802-financeux2";

let financialValuesHidden = false;

function fmtMoneyMinor(minor) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  const rub = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return rub.toFixed(2) + " ₽";
  }
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setVisible(element, visible) {
  element?.classList.toggle("hidden", !visible);
}

function parseMoneyToMinor(value) {
  const raw = String(value || "").trim().replace(/\s+/g, "").replace(/,/g, ".");
  if (!raw) throw new Error("Введите сумму");
  if (!/^\d+(\.\d{1,2})?$/.test(raw)) throw new Error("Сумма должна быть числом, например 1200.50");
  const [rubStr, fracStr = ""] = raw.split(".");
  return (Number(rubStr || 0) * 100) + Number((fracStr + "00").slice(0, 2));
}

function parseSignedMoneyToMinor(value) {
  const raw = String(value || "").trim().replace(/\s+/g, "").replace(/,/g, ".");
  if (!raw) throw new Error("Введите сумму корректировки");
  if (!/^[+-]?\d+(\.\d{1,2})?$/.test(raw)) throw new Error("Используйте сумму со знаком, например -1500 или 2500.50");
  const negative = raw.startsWith("-");
  const unsigned = raw.replace(/^[+-]/, "");
  const [rubStr, fracStr = ""] = unsigned.split(".");
  const amount = (Number(rubStr || 0) * 100) + Number((fracStr + "00").slice(0, 2));
  if (!amount) throw new Error("Сумма корректировки не может быть нулевой");
  return negative ? -amount : amount;
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function statusLabel(status) {
  const norm = String(status || "DRAFT").toUpperCase();
  if (norm === "CONFIRMED") return "Подтверждён";
  if (norm === "CANCELLED") return "Отменён";
  return "Черновик";
}

function openHtmlModal(title, html) {
  const m = document.getElementById("modal");
  if (!m) return;
  const head = m.querySelector(".modal__title");
  const body = m.querySelector(".modal__body");
  if (head) head.textContent = title;
  if (body) body.innerHTML = html;
  m.classList.add("open");
}

function closeModal() {
  document.getElementById("modal")?.classList.remove("open");
}


const DEMO_OWNER_LEDGER_INTRO_DISMISSED_KEY = "axelio.demo_intro.owner_ledger.dismissed";

function setupDemoLedgerIntro() {
  const intro = document.getElementById("demoOwnerLedgerIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) { intro.classList.add("hidden"); return; }
  try {
    if (sessionStorage.getItem(DEMO_OWNER_LEDGER_INTRO_DISMISSED_KEY) === "1") {
      intro.classList.add("hidden");
      return;
    }
  } catch {}
  const textEl = document.getElementById("demoOwnerLedgerIntroText");
  if (textEl) textEl.textContent = `Здесь видно подтверждённые финансовые движения за ${getDemoMonthLabel(demoState) || 'DEMO-месяц'}: выручку, расходы и переводы между оплатами.`;
  const venueId = getActiveVenueId();
  document.getElementById("demoOwnerLedgerGoSummary")?.addEventListener("click", () => { if (venueId) location.href = `/owner-summary.html?venue_id=${encodeURIComponent(String(venueId))}`; });
  document.getElementById("demoOwnerLedgerGoRevenue")?.addEventListener("click", () => { if (venueId) location.href = `/owner-turnover.html?venue_id=${encodeURIComponent(String(venueId))}&month=${encodeURIComponent(state.month || currentMonth())}`; });
  document.getElementById("demoOwnerLedgerIntroClose")?.addEventListener("click", () => {
    intro.classList.add("hidden");
    try { sessionStorage.setItem(DEMO_OWNER_LEDGER_INTRO_DISMISSED_KEY, "1"); } catch {}
  });
  intro.classList.remove("hidden");
}

let access = {
  canView: false,
  canManageTransfers: false,
  canManageAdjustments: false,
  canViewSummary: false,
  canViewRevenue: false,
  canViewExpenses: false,
  canViewPayroll: false,
  canViewReports: false,
  canViewReconciliation: false,
};

const state = {
  periodMode: "month",
  month: currentMonth(),
  dateFrom: monthRange(currentMonth())?.from || todayISO(),
  dateTo: monthRange(currentMonth())?.to || todayISO(),
  paymentMethods: [],
  analytics: null,
  comparisonAnalytics: null,
  entries: [],
  comparisonError: null,
  compareMode: "auto",
  compareFrom: "",
  compareTo: "",
  transfers: [],
  adjustments: [],
  reconciliation: null,
  reconciliationError: null,
  focusTransferId: null,
  focusAdjustmentId: null,
  sourceTargetFocused: false,
  operationsLoaded: false,
  operationsLoading: false,
  operationsHasMore: false,
  operationsOffset: 0,
  operationsDay: null,
};

const OPERATIONS_PAGE_SIZE = 50;

function syncFinanceLinks() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  const financeQuery = new URLSearchParams();
  financeQuery.set("venue_id", String(venueId));
  financeQuery.set("month", state.month || currentMonth());
  const summaryLink = document.getElementById("openSummaryBtn");
  const revenueLink = document.getElementById("openRevenueBtn");
  const expensesLink = document.getElementById("openExpensesBtn");
  setVisible(summaryLink, access.canViewSummary);
  setVisible(revenueLink, access.canViewRevenue);
  setVisible(expensesLink, access.canViewExpenses);
  if (summaryLink) summaryLink.href = `/owner-summary.html?${financeQuery.toString()}`;
  if (revenueLink) revenueLink.href = `/owner-turnover.html?${financeQuery.toString()}`;
  if (expensesLink) expensesLink.href = `/owner-expenses.html?${financeQuery.toString()}`;
  setVisible(
    document.getElementById("ledgerFinanceShortcuts"),
    access.canViewSummary || access.canViewRevenue || access.canViewExpenses,
  );
}

async function loadAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return access;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    financialValuesHidden = isFinancialValuesHidden(permsResp);
    const role = roleUpper(permsResp);
    const systemRole = String(permsResp?.system_role || "").trim().toUpperCase();
    const pset = permSetFromResponse(permsResp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    const isAdmin = ["SUPER_ADMIN", "MODERATOR"].includes(systemRole) || ["SUPER_ADMIN", "MODERATOR"].includes(role);
    const canViewRevenue = isOwner || isAdmin || hasPerm(pset, "REVENUE_VIEW");
    const canViewExpenses = isOwner || isAdmin || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD");
    const canViewPayroll = isOwner || isAdmin || hasPerm(pset, "PAYROLL_VIEW") || hasPerm(pset, "PAYROLL_CALCULATE");
    const canViewReports = isOwner || isAdmin || ["SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_REOPEN"]
      .some((code) => hasPerm(pset, code));
    const canViewReconciliation = isOwner || isAdmin
      || hasPerm(pset, "REPORTS_VIEW_PNL")
      || hasPerm(pset, "MONTHLY_SUMMARY_VIEW")
      || (
        hasPerm(pset, "REVENUE_VIEW")
        && hasPerm(pset, "EXPENSE_VIEW")
        && hasPerm(pset, "PAYROLL_VIEW")
      );
    access = {
      canView: isOwner || isAdmin || hasPerm(pset, "FINANCE_LEDGER_VIEW") || hasPerm(pset, "REVENUE_VIEW") || hasPerm(pset, "EXPENSE_VIEW"),
      canManageTransfers: isOwner || isAdmin || hasPerm(pset, "PAYMENT_TRANSFERS_MANAGE") || hasPerm(pset, "EXPENSE_ADD"),
      canManageAdjustments: isOwner || isAdmin || hasPerm(pset, "EXPENSE_ADD"),
      canViewSummary: canViewRevenue || canViewExpenses || canViewPayroll || hasPerm(pset, "REPORTS_VIEW_PNL") || hasPerm(pset, "MONTHLY_SUMMARY_VIEW"),
      canViewRevenue,
      canViewExpenses,
      canViewPayroll,
      canViewReports,
      canViewReconciliation,
    };
  } catch {
    access = {
      canView: false,
      canManageTransfers: false,
      canManageAdjustments: false,
      canViewSummary: false,
      canViewRevenue: false,
      canViewExpenses: false,
      canViewPayroll: false,
      canViewReports: false,
      canViewReconciliation: false,
    };
  }
  return access;
}

function renderPaymentMethodOptions() {
  const pick = document.getElementById("ledgerPaymentMethodPick");
  if (!pick) return;
  const current = pick.value || "";
  pick.innerHTML = `<option value="">Все оплаты</option>` + state.paymentMethods.map((pm) => `<option value="${pm.id}">${esc(pm.title)}</option>`).join("");
  pick.value = current;
}

function currentComparison() {
  if (state.compareMode === "none") return null;
  return resolveComparisonRange({
    compareMode: state.compareMode,
    compareFrom: state.compareFrom,
    compareTo: state.compareTo,
    period: state.periodMode,
    month: state.month,
    from: state.dateFrom,
    to: state.dateTo,
  });
}

function primaryRange() {
  return state.periodMode === "range"
    ? normalizeIsoRange(state.dateFrom, state.dateTo)
    : monthRange(state.month);
}

function primaryPeriodLabel() {
  return formatComparisonRange(primaryRange());
}

function appendPrimaryPeriod(query) {
  if (state.periodMode === "range") {
    const range = primaryRange();
    if (range?.from) query.set("date_from", range.from);
    if (range?.to) query.set("date_to", range.to);
  } else {
    query.set("month", state.month || currentMonth());
  }
  return query;
}

function appendLedgerFilters(query) {
  const paymentMethodId = document.getElementById("ledgerPaymentMethodPick")?.value || "";
  const kind = document.getElementById("ledgerKindPick")?.value || "";
  const direction = document.getElementById("ledgerDirectionPick")?.value || "";
  const sourceType = document.getElementById("ledgerSourcePick")?.value || "";
  if (paymentMethodId) query.set("payment_method_id", paymentMethodId);
  if (kind) query.set("kind", kind);
  if (direction) query.set("direction", direction);
  if (sourceType) query.set("source_type", sourceType);
  return query;
}

function currentLedgerQuery() {
  return appendLedgerFilters(appendPrimaryPeriod(new URLSearchParams()));
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

function defaultLedgerDate() {
  const range = primaryRange();
  const today = todayISO();
  if (range && today >= range.from && today <= range.to) return today;
  return range?.to || today;
}

function syncUrl() {
  const qp = new URLSearchParams(location.search);
  qp.set("venue_id", String(getActiveVenueId() || ""));
  qp.set("period_mode", state.periodMode);
  if (state.periodMode === "range") {
    qp.delete("month");
    qp.set("date_from", state.dateFrom);
    qp.set("date_to", state.dateTo);
  } else {
    qp.set("month", state.month);
    qp.delete("date_from");
    qp.delete("date_to");
  }
  qp.set("compare_mode", state.compareMode);
  const paymentMethodId = document.getElementById("ledgerPaymentMethodPick")?.value || "";
  const kind = document.getElementById("ledgerKindPick")?.value || "";
  const direction = document.getElementById("ledgerDirectionPick")?.value || "";
  const sourceType = document.getElementById("ledgerSourcePick")?.value || "";
  paymentMethodId ? qp.set("payment_method_id", paymentMethodId) : qp.delete("payment_method_id");
  kind ? qp.set("kind", kind) : qp.delete("kind");
  direction ? qp.set("direction", direction) : qp.delete("direction");
  sourceType ? qp.set("source_type", sourceType) : qp.delete("source_type");
  if (state.compareMode === "custom") {
    const comparison = currentComparison();
    if (comparison?.from) qp.set("compare_from", comparison.from);
    if (comparison?.to) qp.set("compare_to", comparison.to);
  } else {
    qp.delete("compare_from");
    qp.delete("compare_to");
  }
  history.replaceState(null, "", `${location.pathname}?${qp.toString()}`);
}

function syncPeriodUi() {
  const rangeMode = state.periodMode === "range";
  document.querySelectorAll("#ledgerPeriodSeg [data-period]").forEach((button) => {
    button.classList.toggle("active", button.dataset.period === state.periodMode);
  });
  setVisible(document.getElementById("ledgerMonthWrap"), !rangeMode);
  setVisible(document.getElementById("ledgerDateRange"), rangeMode);
  const monthPick = document.getElementById("ledgerMonthPick");
  const from = document.getElementById("ledgerDateFrom");
  const to = document.getElementById("ledgerDateTo");
  if (monthPick) monthPick.value = state.month;
  if (from) from.value = state.dateFrom;
  if (to) to.value = state.dateTo;
}

function syncComparisonUi() {
  const comparison = currentComparison();
  const custom = state.compareMode === "custom";
  const disabled = state.compareMode === "none";
  document.querySelectorAll("#ledgerCompareSeg [data-compare]").forEach((button) => {
    button.classList.toggle("active", button.dataset.compare === state.compareMode);
  });
  document.getElementById("ledgerCompareRange")?.classList.toggle("hidden", !custom);
  setText("ledgerComparePeriodText", disabled ? "Сравнение отключено" : formatComparisonRange(comparison));
  setText("ledgerCompareHint", disabled ? "Дополнительный период не загружается." : (comparison?.caption || "Выбери корректный период сравнения."));
  if (custom) {
    const from = document.getElementById("ledgerCompareFrom");
    const to = document.getElementById("ledgerCompareTo");
    if (from) from.value = comparison?.from || state.compareFrom || "";
    if (to) to.value = comparison?.to || state.compareTo || "";
  }
}

function fmtSignedMoneyMinor(value) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  const amount = Number(value || 0);
  const sign = amount > 0 ? "+" : amount < 0 ? "−" : "";
  return `${sign}${fmtMoneyMinor(Math.abs(amount))}`;
}

function fmtCompactMoneyMinor(value) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  const rub = Number(value || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { notation: "compact", maximumFractionDigits: 1 }).format(rub) + " ₽";
  } catch {
    return fmtMoneyMinor(value);
  }
}

function renderMetricDelta(id, currentValue, previousValue, { type = "money", goodWhen = "neutral" } = {}) {
  const element = document.getElementById(id);
  if (!element) return;
  element.classList.remove("is-good", "is-bad", "is-neutral");
  if (financialValuesHidden || state.comparisonError || previousValue === null || previousValue === undefined) {
    element.textContent = state.comparisonError ? "Сравнение недоступно" : "—";
    element.classList.add("is-neutral");
    return;
  }
  const current = Number(currentValue || 0);
  const previous = Number(previousValue || 0);
  const delta = current - previous;
  const caption = currentComparison()?.caption || "";
  const good = (goodWhen === "up" && delta > 0) || (goodWhen === "down" && delta < 0);
  const bad = (goodWhen === "up" && delta < 0) || (goodWhen === "down" && delta > 0);
  element.classList.add(good ? "is-good" : bad ? "is-bad" : "is-neutral");
  if (previous === 0) {
    const deltaLabel = type === "money" ? fmtSignedMoneyMinor(delta) : `${delta > 0 ? "+" : ""}${delta}`;
    element.textContent = current === 0 ? `Без изменений ${caption}`.trim() : `Нет базы · ${deltaLabel} ${caption}`.trim();
    return;
  }
  const percent = (delta / Math.abs(previous)) * 100;
  const percentLabel = `${percent > 0 ? "+" : percent < 0 ? "−" : ""}${Math.abs(percent).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}%`;
  const deltaLabel = type === "money" ? ` · ${fmtSignedMoneyMinor(delta)}` : "";
  element.textContent = `${percentLabel}${deltaLabel} ${caption}`.trim();
}

function renderMetrics() {
  const current = normalizeAnalyticsMetrics(state.analytics);
  const previous = state.compareMode === "none" || state.comparisonError
    ? null
    : normalizeAnalyticsMetrics(state.comparisonAnalytics);
  setText("ledgerIncomeTotal", fmtMoneyMinor(current.incomeMinor));
  setText("ledgerExpenseTotal", fmtMoneyMinor(current.expenseMinor));
  setText("ledgerNetTotal", fmtMoneyMinor(current.netMinor));
  setText("ledgerCount", String(current.count));
  renderMetricDelta("ledgerIncomeDelta", current.incomeMinor, previous?.incomeMinor, { goodWhen: "up" });
  renderMetricDelta("ledgerExpenseDelta", current.expenseMinor, previous?.expenseMinor, { goodWhen: "down" });
  renderMetricDelta("ledgerNetDelta", current.netMinor, previous?.netMinor, { goodWhen: "up" });
  renderMetricDelta("ledgerCountDelta", current.count, previous?.count, { type: "count" });
}

function normalizeAnalyticsMetrics(payload) {
  const metrics = payload?.metrics || {};
  return {
    incomeMinor: Number(metrics.income_minor || 0),
    expenseMinor: Number(metrics.expense_minor || 0),
    netMinor: Number(metrics.net_minor || 0),
    count: Number(metrics.count || 0),
  };
}

function analyticsDailySeries(payload) {
  const entries = [];
  (Array.isArray(payload?.daily_series) ? payload.daily_series : []).forEach((point) => {
    if (Number(point?.income_minor || 0) > 0) entries.push({
      entry_date: point.date,
      direction: "INCOME",
      amount_minor: Number(point.income_minor || 0),
    });
    if (Number(point?.expense_minor || 0) > 0) entries.push({
      entry_date: point.date,
      direction: "EXPENSE",
      amount_minor: Number(point.expense_minor || 0),
    });
  });
  return buildLedgerDailySeries(entries, primaryRange());
}

function analyticsStructure(payload) {
  const entries = (Array.isArray(payload?.structure) ? payload.structure : []).map((row) => ({
    direction: row.direction,
    kind: row.kind,
    amount_minor: Number(row.amount_minor || 0),
  }));
  return buildLedgerStructure(entries);
}

function formatEntryDate(value) {
  const parts = String(value || "").split("-").map(Number);
  if (parts.length !== 3 || parts.some((part) => !Number.isFinite(part))) return String(value || "—");
  try {
    return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
      .format(new Date(Date.UTC(parts[0], parts[1] - 1, parts[2])));
  } catch {
    return String(value || "—");
  }
}

function formatMonthLabel(value) {
  const match = /^(\d{4})-(\d{2})$/.exec(String(value || ""));
  if (!match) return String(value || "—");
  try {
    return new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric", timeZone: "UTC" })
      .format(new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1)));
  } catch {
    return String(value || "—");
  }
}

function renderChartContext() {
  const paymentMethod = document.getElementById("ledgerPaymentMethodPick")?.selectedOptions?.[0]?.textContent?.trim() || "Все оплаты";
  const kind = document.getElementById("ledgerKindPick")?.selectedOptions?.[0]?.textContent?.trim() || "Все типы";
  const direction = document.getElementById("ledgerDirectionPick")?.selectedOptions?.[0]?.textContent?.trim() || "Приход и списание";
  const source = document.getElementById("ledgerSourcePick")?.selectedOptions?.[0]?.textContent?.trim() || "Все источники";
  const period = state.periodMode === "month" ? formatMonthLabel(state.month) : primaryPeriodLabel();
  const context = `${period} · ${paymentMethod} · ${kind} · ${direction} · ${source}`;
  setText("ledgerTrendSubtitle", context);
  setText("ledgerStructureSubtitle", `Объём по видам операций · ${context}`);
}

function renderTrendFocus(point) {
  const element = document.getElementById("ledgerTrendFocus");
  if (!element || !point) return;
  element.innerHTML = `<b>${esc(formatEntryDate(point.date))}</b> · приход ${esc(fmtMoneyMinor(point.incomeMinor))} · списание ${esc(fmtMoneyMinor(point.expenseMinor))} · чистый поток ${esc(fmtSignedMoneyMinor(point.netMinor))}`;
}

function renderTrendChart() {
  const element = document.getElementById("ledgerTrendChart");
  if (!element) return;
  if (financialValuesHidden) {
    element.innerHTML = `<div class="ledger-chart-empty">${esc(FINANCIAL_VALUES_HIDDEN_LABEL)}</div>`;
    setText("ledgerTrendFocus", FINANCIAL_VALUES_HIDDEN_LABEL);
    return;
  }
  const points = analyticsDailySeries(state.analytics);
  const maxValue = Math.max(0, ...points.flatMap((point) => [point.incomeMinor, point.expenseMinor]));
  if (!points.length || maxValue <= 0) {
    element.innerHTML = `<div class="ledger-chart-empty">За выбранный фильтр нет движений для графика.</div>`;
    setText("ledgerTrendFocus", "Нет данных за выбранный период");
    return;
  }
  const peak = points.reduce((best, point) => (
    Math.max(point.incomeMinor, point.expenseMinor) > Math.max(best.incomeMinor, best.expenseMinor) ? point : best
  ), points[0]);
  const tickStep = Math.max(1, Math.ceil(points.length / 8));
  const bars = points.map((point, index) => {
    const chartWidth = 620;
    const chartHeight = 180;
    const bandWidth = chartWidth / points.length;
    const barWidth = Math.max(2, bandWidth * 0.32);
    const gap = Math.max(1, bandWidth * 0.06);
    const groupWidth = (barWidth * 2) + gap;
    const startX = (index * bandWidth) + ((bandWidth - groupWidth) / 2);
    const incomeHeight = point.incomeMinor > 0 ? Math.max(2, (point.incomeMinor / maxValue) * chartHeight) : 0;
    const expenseHeight = point.expenseMinor > 0 ? Math.max(2, (point.expenseMinor / maxValue) * chartHeight) : 0;
    const showTick = index === 0 || index === points.length - 1 || index % tickStep === 0;
    const aria = `${formatEntryDate(point.date)}. Приход ${fmtMoneyMinor(point.incomeMinor)}. Списание ${fmtMoneyMinor(point.expenseMinor)}. Чистый поток ${fmtSignedMoneyMinor(point.netMinor)}.`;
    return {
      svg: `<g class="ledger-day-group${point.date === state.operationsDay ? " is-active" : ""}" data-ledger-day="${esc(point.date)}" role="button" tabindex="0" aria-label="${esc(`${aria} Открыть операции за этот день.`)}">
        <title>${esc(aria)}</title>
        <rect class="ledger-day__hit" x="${(index * bandWidth).toFixed(2)}" y="0" width="${bandWidth.toFixed(2)}" height="180" rx="3"></rect>
        <rect class="ledger-day__bar ledger-day__bar--income" x="${startX.toFixed(2)}" y="${(chartHeight - incomeHeight).toFixed(2)}" width="${barWidth.toFixed(2)}" height="${incomeHeight.toFixed(2)}" rx="2"></rect>
        <rect class="ledger-day__bar ledger-day__bar--expense" x="${(startX + barWidth + gap).toFixed(2)}" y="${(chartHeight - expenseHeight).toFixed(2)}" width="${barWidth.toFixed(2)}" height="${expenseHeight.toFixed(2)}" rx="2"></rect>
      </g>`,
      tick: `<span>${showTick ? point.day : ""}</span>`,
    };
  });
  element.innerHTML = `<div class="ledger-trend-scale" aria-hidden="true"><span>${esc(fmtCompactMoneyMinor(maxValue))}</span><span>0</span></div>
    <div class="ledger-trend-visual">
      <svg class="ledger-trend-svg" viewBox="0 0 620 180" preserveAspectRatio="none" role="group" aria-label="Дневные значения прихода и списания">
        <line class="ledger-trend-gridline" x1="0" y1="0" x2="620" y2="0"></line>
        <line class="ledger-trend-gridline" x1="0" y1="60" x2="620" y2="60"></line>
        <line class="ledger-trend-gridline" x1="0" y1="120" x2="620" y2="120"></line>
        <line class="ledger-trend-gridline" x1="0" y1="180" x2="620" y2="180"></line>
        ${bars.map((item) => item.svg).join("")}
      </svg>
      <div class="ledger-trend-ticks" aria-hidden="true">${bars.map((item) => item.tick).join("")}</div>
    </div>`;
  renderTrendFocus(points.find((point) => point.date === state.operationsDay) || peak);
  element.querySelectorAll("[data-ledger-day]").forEach((button) => {
    const previewPoint = () => {
      renderTrendFocus(points.find((point) => point.date === button.dataset.ledgerDay));
    };
    const filterPoint = async () => {
      state.operationsDay = button.dataset.ledgerDay || null;
      renderOperationsSummary();
      element.querySelectorAll("[data-ledger-day]").forEach((item) => item.classList.toggle("is-active", item === button));
      previewPoint();
      const disclosure = document.getElementById("ledgerOperations");
      if (disclosure) disclosure.open = true;
      await loadOperations({ reset: true });
      disclosure?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    button.addEventListener("click", filterPoint);
    button.addEventListener("focus", previewPoint);
    button.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      filterPoint();
    });
  });
}

function structureLabel(item) {
  if (item.kind === "OTHER") return "Остальные операции";
  const direction = item.direction === "INCOME" ? "приход" : "списание";
  return `${ledgerKindLabel(item.kind)} · ${direction}`;
}

function renderStructureChart() {
  const element = document.getElementById("ledgerStructureChart");
  if (!element) return;
  if (financialValuesHidden) {
    element.innerHTML = `<div class="ledger-chart-empty">${esc(FINANCIAL_VALUES_HIDDEN_LABEL)}</div>`;
    return;
  }
  const groups = analyticsStructure(state.analytics);
  const maxValue = Math.max(0, ...groups.map((item) => item.amountMinor));
  if (!groups.length || maxValue <= 0) {
    element.innerHTML = `<div class="ledger-chart-empty">Нет операций для структуры.</div>`;
    return;
  }
  element.innerHTML = groups.map((item) => {
    const width = Math.max(2, (item.amountMinor / maxValue) * 100);
    const rowClass = item.direction === "EXPENSE" ? " ledger-structure-row--expense" : item.direction === "MIXED" ? " ledger-structure-row--mixed" : "";
    return `<div class="ledger-structure-row${rowClass}">
      <div class="ledger-structure-head">
        <span class="ledger-structure-label">${esc(structureLabel(item))}</span>
        <span class="ledger-structure-value">${esc(fmtMoneyMinor(item.amountMinor))}</span>
      </div>
      <svg class="ledger-structure-svg" viewBox="0 0 100 9" preserveAspectRatio="none" role="img" aria-label="${esc(`${structureLabel(item)}: ${fmtMoneyMinor(item.amountMinor)}`)}">
        <rect class="ledger-structure-track" x="0" y="0" width="100" height="9" rx="4.5"></rect>
        <rect class="ledger-structure-fill" x="0" y="0" width="${width.toFixed(2)}" height="9" rx="4.5"></rect>
      </svg>
    </div>`;
  }).join("");
}

function reconciliationSourceLabel(sourceType) {
  const labels = {
    daily_report: "отчёт смены",
    expense: "расход",
    payroll_run: "расчёт начислений",
    payment_method_transfer: "перевод",
    balance_adjustment: "корректировка баланса",
  };
  return labels[String(sourceType || "").toLowerCase()] || String(sourceType || "источник");
}

function renderReconciliation() {
  const card = document.getElementById("ledgerReconciliation");
  const checksElement = document.getElementById("ledgerReconciliationChecks");
  const issuesElement = document.getElementById("ledgerReconciliationIssues");
  const statusElement = document.getElementById("ledgerReconciliationStatus");
  if (!card || !checksElement || !issuesElement || !statusElement) return;
  setVisible(card, access.canViewReconciliation);
  if (!access.canViewReconciliation) return;

  statusElement.classList.remove("is-ok", "is-warning", "is-neutral");
  if (state.reconciliationError || !state.reconciliation) {
    statusElement.textContent = "Недоступна";
    statusElement.classList.add("is-neutral");
    setText("ledgerReconciliationHint", "Не удалось выполнить сверку. Остальная страница продолжает работать.");
    checksElement.innerHTML = `<div class="muted">${esc(state.reconciliationError?.data?.detail || state.reconciliationError?.message || "Повтори загрузку позже.")}</div>`;
    issuesElement.classList.add("hidden");
    issuesElement.innerHTML = "";
    return;
  }

  const payload = state.reconciliation;
  const warning = String(payload.status || "OK").toUpperCase() === "WARNING";
  statusElement.textContent = warning ? `Есть расхождения: ${Number(payload.warning_count || 0)}` : "Всё сходится";
  statusElement.classList.add(warning ? "is-warning" : "is-ok");
  setText(
    "ledgerReconciliationHint",
    warning
      ? "Найдены расхождения за весь выбранный период. Фильтры операций на результат сверки не влияют."
      : "Сводка и связанные проводки проверены за весь выбранный период, без фильтров операций.",
  );

  checksElement.innerHTML = (payload.checks || []).map((check) => {
    const checkStatus = String(check.status || "INFO").toUpperCase();
    const statusLabel = checkStatus === "WARNING" ? "Расхождение" : checkStatus === "OK" ? "Сходится" : "Справочно";
    const metric = check.comparable_to_summary
      ? `Сводка: ${fmtMoneyMinor(check.summary_minor)} · журнал: ${fmtMoneyMinor(check.ledger_minor)} · разница: ${fmtSignedMoneyMinor(check.delta_minor)}`
      : `В сводке: ${fmtMoneyMinor(check.summary_minor)} · по источникам журнала: ${fmtMoneyMinor(check.source_ledger_minor)}`;
    return `<div class="ledger-reconciliation-check ${checkStatus === "WARNING" ? "is-warning" : checkStatus === "OK" ? "is-ok" : "is-info"}">
      <div class="ledger-reconciliation-check__head">
        <b>${esc(check.title || check.key || "Проверка")}</b>
        <span>${esc(statusLabel)}</span>
      </div>
      <div class="ledger-reconciliation-check__metric">${esc(metric)}</div>
      <div class="muted">${esc(check.note || "")}</div>
    </div>`;
  }).join("");

  const issues = Array.isArray(payload.issues) ? payload.issues : [];
  if (!issues.length) {
    issuesElement.classList.add("hidden");
    issuesElement.innerHTML = "";
    return;
  }
  const reasonLabels = {
    MISSING_LEDGER_ENTRY: "нет проводки",
    EXTRA_LEDGER_ENTRY: "лишняя проводка",
    AMOUNT_MISMATCH: "не совпадает сумма",
  };
  issuesElement.classList.remove("hidden");
  issuesElement.innerHTML = `<div class="ledger-reconciliation-issues__title">Проблемные источники</div>${issues.map((issue) => {
    const sourceId = issue.source_id ? ` #${issue.source_id}` : "";
    const sourceDate = issue.source_date ? ` · ${formatEntryDate(issue.source_date)}` : "";
    return `<div class="ledger-reconciliation-issue">
      <div class="ledger-reconciliation-issue__main">
        <b>${esc(reconciliationSourceLabel(issue.source_type))}${esc(sourceId)}</b>
        <div class="muted">${esc(reasonLabels[issue.reason] || issue.reason || "расхождение")}${esc(sourceDate)}</div>
        <div class="ledger-reconciliation-issue__amounts">Ожидалось ${esc(fmtMoneyMinor(issue.expected_minor))} · в журнале ${esc(fmtMoneyMinor(issue.ledger_minor))} · разница ${esc(fmtSignedMoneyMinor(issue.delta_minor))}</div>
      </div>
      <button class="btn ghost small" type="button" data-reconciliation-filter="1" data-kind="${esc(issue.kind || "")}" data-direction="${esc(issue.direction || "")}" data-source-type="${esc(issue.source_type || "")}">Показать проводки</button>
    </div>`;
  }).join("")}${payload.issues_truncated ? `<div class="muted mt-8">Показаны первые 50 источников с наибольшим расхождением.</div>` : ""}`;

  issuesElement.querySelectorAll("[data-reconciliation-filter]").forEach((button) => {
    button.onclick = async () => {
      document.getElementById("ledgerPaymentMethodPick").value = "";
      document.getElementById("ledgerKindPick").value = String(button.dataset.kind || "").toUpperCase();
      document.getElementById("ledgerDirectionPick").value = String(button.dataset.direction || "").toUpperCase();
      const sourcePick = document.getElementById("ledgerSourcePick");
      const sourceType = String(button.dataset.sourceType || "").toLowerCase();
      if (sourcePick) {
        sourcePick.value = Array.from(sourcePick.options).some((option) => option.value === sourceType) ? sourceType : "";
      }
      const operations = document.getElementById("ledgerOperations");
      if (operations) operations.open = true;
      await reload();
      operations?.scrollIntoView({ behavior: "smooth", block: "start" });
    };
  });
}

function renderEntries() {
  const el = document.getElementById("ledgerEntriesList");
  if (!el) return;
  const dayLabel = state.operationsDay ? formatEntryDate(state.operationsDay) : "";
  const scopeLabel = dayLabel ? `за ${dayLabel}` : `за ${primaryPeriodLabel()}`;
  const dayFilter = document.getElementById("ledgerOperationsDayFilter");
  setVisible(dayFilter, Boolean(state.operationsDay));
  setText("ledgerOperationsDayText", dayLabel ? `Фильтр по графику: ${dayLabel}` : "—");
  setText(
    "ledgerHint",
    state.operationsLoaded
      ? `${scopeLabel} · загружено ${state.entries.length}${state.operationsHasMore ? "+" : ""}`
      : "Открой раздел, чтобы загрузить операции.",
  );

  const moreButton = document.getElementById("ledgerOperationsMore");
  setVisible(moreButton, state.operationsLoaded && state.operationsHasMore);
  if (moreButton) moreButton.disabled = state.operationsLoading;

  if (!state.operationsLoaded) {
    el.innerHTML = `<div class="muted">Операции пока не загружены.</div>`;
    return;
  }

  if (!state.entries.length) {
    el.innerHTML = `<div class="muted">Нет финансовых записей ${esc(scopeLabel)}.</div>`;
    return;
  }

  el.innerHTML = state.entries.map((item) => {
    const directionText = item.direction === "INCOME" ? "Приход" : "Списание";
    const source = buildLedgerSourceDrilldown(item, {
      venueId: getActiveVenueId(),
      month: state.month,
    });
    const scope = item.payment_method?.title || item.department?.title || source.sourceLabel || "—";
    const canOpenSource = source.sourceType === "expense"
      ? access.canViewExpenses
      : source.sourceType === "payroll_run"
        ? access.canViewPayroll
        : source.sourceType === "daily_report"
          ? access.canViewReports
          : access.canView;
    const sourceAction = canOpenSource
      ? (source.href
          ? `<a class="btn ghost small ledger-source-action" href="${esc(source.href)}">${esc(source.actionLabel)}</a>`
          : `<button class="btn ghost small ledger-source-action" type="button" data-source-details="${esc(item.id)}">${esc(source.actionLabel)}</button>`)
      : "";
    return `
      <div class="expense-row ledger-entry-row" data-ledger-entry-id="${esc(item.id)}">
        <div class="expense-row__main">
          <div class="row gap-8">
            <div class="expense-row__title">${esc(ledgerKindLabel(item.kind))}</div>
            <span class="badge">${esc(directionText)}</span>
            <span class="badge">${esc(scope)}</span>
          </div>
          <div class="muted mt-6">${esc(formatEntryDate(item.entry_date))}</div>
          <div class="ledger-source-meta mt-8"><span>Источник: ${esc(source.sourceLabel)}</span>${source.sourceId ? `<span class="mono">#${esc(source.sourceId)}</span>` : ""}</div>
        </div>
        <div class="expense-row__side">
          <div class="expense-row__amount">${esc(fmtMoneyMinor(item.amount_minor || 0))}</div>
          ${sourceAction}
        </div>
      </div>
    `;
  }).join("");

  el.querySelectorAll("[data-source-details]").forEach((button) => {
    button.onclick = () => {
      const entry = state.entries.find((item) => String(item.id) === String(button.getAttribute("data-source-details")));
      if (entry) openLedgerSourceDetails(entry);
    };
  });
}

function operationsQuery() {
  const query = appendLedgerFilters(new URLSearchParams());
  if (state.operationsDay) {
    query.set("date_from", state.operationsDay);
    query.set("date_to", state.operationsDay);
  } else {
    appendPrimaryPeriod(query);
  }
  query.set("limit", String(OPERATIONS_PAGE_SIZE + 1));
  query.set("offset", String(state.operationsOffset));
  return query;
}

function renderOperationsSummary() {
  const total = normalizeAnalyticsMetrics(state.analytics).count;
  const dayPoint = (Array.isArray(state.analytics?.daily_series) ? state.analytics.daily_series : [])
    .find((point) => point?.date === state.operationsDay);
  const visibleTotal = state.operationsDay ? Number(dayPoint?.count || 0) : total;
  setText("ledgerOperationsCount", visibleTotal ? `${visibleTotal.toLocaleString("ru-RU")} записей` : "Показать");
}

async function loadOperations({ reset = false } = {}) {
  if (!access.canView || state.operationsLoading) return;
  if (reset) {
    state.entries = [];
    state.operationsOffset = 0;
    state.operationsHasMore = false;
    state.operationsLoaded = false;
  }
  state.operationsLoading = true;
  const list = document.getElementById("ledgerEntriesList");
  const moreButton = document.getElementById("ledgerOperationsMore");
  if (moreButton) moreButton.disabled = true;
  if (list && !state.entries.length) {
    list.innerHTML = '<div class="ledger-operations__loading"><span class="skeleton"></span><span class="skeleton"></span></div>';
    list.setAttribute("aria-busy", "true");
  }
  try {
    const venueId = getActiveVenueId();
    const rows = await api(`/venues/${encodeURIComponent(venueId)}/finance/entries?${operationsQuery().toString()}`);
    const page = Array.isArray(rows) ? rows : [];
    state.operationsHasMore = page.length > OPERATIONS_PAGE_SIZE;
    const visibleRows = page.slice(0, OPERATIONS_PAGE_SIZE);
    state.entries = reset ? visibleRows : [...state.entries, ...visibleRows];
    state.operationsOffset = state.entries.length;
    state.operationsLoaded = true;
    renderEntries();
  } catch (error) {
    state.operationsLoaded = true;
    if (list) list.innerHTML = `<div class="muted">${esc(error?.data?.detail || error?.message || "Не удалось загрузить операции")}</div>`;
    toast("Не удалось загрузить операции", "err");
  } finally {
    state.operationsLoading = false;
    list?.setAttribute("aria-busy", "false");
    if (moreButton) moreButton.disabled = false;
  }
}

function sourceDetailRow(label, value) {
  if (value === null || value === undefined || String(value).trim() === "") return "";
  return `<div class="finance-kv-row"><span class="muted">${esc(label)}</span><b>${esc(value)}</b></div>`;
}

function openLedgerSourceDetails(entry) {
  const source = buildLedgerSourceDrilldown(entry, { venueId: getActiveVenueId(), month: state.month });
  const meta = entry?.meta_json && typeof entry.meta_json === "object" ? entry.meta_json : {};
  const rows = [
    sourceDetailRow("Источник", `${source.sourceLabel}${source.sourceId ? ` #${source.sourceId}` : ""}`),
    sourceDetailRow("Дата движения", formatEntryDate(entry.entry_date)),
    sourceDetailRow("Сумма", fmtMoneyMinor(entry.amount_minor || 0)),
    sourceDetailRow("Тип", ledgerKindLabel(entry.kind)),
    sourceDetailRow("Дата документа", meta.adjustment_date || meta.transfer_date || meta.expense_date || meta.report_date),
    sourceDetailRow("Смена", String(meta.shift_slot || "").toUpperCase() === "NIGHT" ? "Ночь" : (meta.shift_slot ? "День" : "")),
    sourceDetailRow("Период начисления", meta.period_month),
    sourceDetailRow("Причина", meta.reason),
    sourceDetailRow("Комментарий", meta.comment),
  ].filter(Boolean).join("");
  openHtmlModal(source.sourceLabel, `<div class="finance-kv-list">${rows}</div>`);
}

function renderAdjustments() {
  const el = document.getElementById("adjustmentList");
  if (!el) return;
  setText("adjustmentHint", state.adjustments.length
    ? `${primaryPeriodLabel()} · записей: ${state.adjustments.length}`
    : `${primaryPeriodLabel()} · корректировок нет`);
  if (!state.adjustments.length) {
    el.innerHTML = `<div class="muted">Нет корректировок баланса за выбранный период.</div>`;
    return;
  }

  el.innerHTML = state.adjustments.map((item) => {
    const status = String(item.status || "CONFIRMED").toUpperCase();
    const delta = Number(item.delta_minor || 0);
    const amountClass = delta > 0 ? "is-positive" : "is-negative";
    const actions = access.canManageAdjustments ? `
      <div class="row row--end gap-8 mt-10">
        ${status !== "CONFIRMED" ? `<button class="btn small" data-adjustment-status="CONFIRMED" data-adjustment-id="${item.id}">Подтвердить</button>` : ""}
        ${status !== "DRAFT" ? `<button class="btn ghost small" data-adjustment-status="DRAFT" data-adjustment-id="${item.id}">В черновик</button>` : ""}
        ${status !== "CANCELLED" ? `<button class="btn ghost small" data-adjustment-status="CANCELLED" data-adjustment-id="${item.id}">Отменить</button>` : ""}
        <button class="btn small" data-adjustment-edit="${item.id}">Изменить</button>
        <button class="btn danger small" data-adjustment-del="${item.id}">Удалить</button>
      </div>` : "";
    return `
      <div class="expense-row ledger-source-target" id="adjustment-${esc(item.id)}" data-adjustment-row="${esc(item.id)}">
        <div class="expense-row__main">
          <div class="row gap-8">
            <div class="expense-row__title">${esc(item.reason || "Корректировка баланса")}</div>
            <span class="badge">${esc(statusLabel(status))}</span>
            ${item.payment_method?.title ? `<span class="badge">${esc(item.payment_method.title)}</span>` : ""}
          </div>
          <div class="muted mt-6">${esc(formatEntryDate(item.adjustment_date))}</div>
          ${item.comment ? `<div class="mt-8">${esc(item.comment)}</div>` : ""}
        </div>
        <div class="expense-row__side">
          <div class="expense-row__amount ledger-adjustment-amount ${amountClass}">${esc(fmtSignedMoneyMinor(delta))}</div>
          ${actions}
        </div>
      </div>`;
  }).join("");

  el.querySelectorAll("[data-adjustment-edit]").forEach((button) => {
    button.onclick = () => openAdjustmentForm(Number(button.getAttribute("data-adjustment-edit")));
  });
  el.querySelectorAll("[data-adjustment-del]").forEach((button) => {
    button.onclick = () => deleteAdjustment(Number(button.getAttribute("data-adjustment-del")));
  });
  el.querySelectorAll("[data-adjustment-status]").forEach((button) => {
    button.onclick = () => updateAdjustment(
      Number(button.getAttribute("data-adjustment-id")),
      { status: String(button.getAttribute("data-adjustment-status") || "DRAFT") },
    );
  });
  focusLinkedAdjustment();
}

function buildAdjustmentForm(item = null) {
  const paymentOptions = state.paymentMethods.map((paymentMethod) => `
    <option value="${paymentMethod.id}" ${String(item?.payment_method_id || "") === String(paymentMethod.id) ? "selected" : ""}>${esc(paymentMethod.title)}</option>
  `).join("");
  const amount = item ? (Number(item.delta_minor || 0) / 100).toFixed(2) : "";
  const status = String(item?.status || "CONFIRMED").toUpperCase();
  return `
    <form id="adjustmentForm" class="finance-form">
      <label>Тип оплаты<select name="payment_method_id" required>${paymentOptions}</select></label>
      <label>Изменение остатка, ₽<input name="amount" type="text" inputmode="decimal" placeholder="-1500 или 2500.50" value="${esc(amount)}" required /></label>
      <div class="form-note form-note--info">Положительная сумма увеличит остаток, отрицательная — уменьшит.</div>
      <label>Дата<input name="adjustment_date" type="date" value="${esc(item?.adjustment_date || defaultLedgerDate())}" required /></label>
      <label>Статус
        <select name="status">
          <option value="DRAFT" ${status === "DRAFT" ? "selected" : ""}>Черновик</option>
          <option value="CONFIRMED" ${status === "CONFIRMED" ? "selected" : ""}>Подтверждён</option>
          <option value="CANCELLED" ${status === "CANCELLED" ? "selected" : ""}>Отменён</option>
        </select>
      </label>
      <label>Причина<input name="reason" type="text" maxlength="255" placeholder="Например, пересчёт кассы" value="${esc(item?.reason || "")}" required /></label>
      <label>Комментарий<textarea name="comment" rows="4" maxlength="1000" placeholder="Подробности и основание корректировки">${esc(item?.comment || "")}</textarea></label>
      <div class="row gap-8 mt-12">
        <button class="btn" type="submit">${item ? "Сохранить" : "Добавить"}</button>
        <button class="btn ghost" type="button" id="adjustmentCancel">Отмена</button>
      </div>
    </form>`;
}

function openAdjustmentForm(adjustmentId = null) {
  if (!access.canManageAdjustments) return;
  if (!state.paymentMethods.length) {
    toast("Сначала добавьте тип оплаты", "warn");
    return;
  }
  const item = adjustmentId ? state.adjustments.find((row) => Number(row.id) === Number(adjustmentId)) : null;
  openHtmlModal(item ? "Изменить корректировку" : "Новая корректировка баланса", buildAdjustmentForm(item));
  document.getElementById("adjustmentCancel")?.addEventListener("click", closeModal);
  const form = document.getElementById("adjustmentForm");
  if (!form) return;
  form.onsubmit = async (event) => {
    event.preventDefault();
    try {
      const data = new FormData(form);
      const payload = {
        payment_method_id: Number(data.get("payment_method_id") || 0),
        adjustment_date: String(data.get("adjustment_date") || ""),
        delta_minor: parseSignedMoneyToMinor(data.get("amount")),
        status: String(data.get("status") || "CONFIRMED"),
        reason: String(data.get("reason") || "").trim(),
        comment: String(data.get("comment") || "").trim(),
      };
      const venueId = getActiveVenueId();
      if (item) {
        await api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments/${encodeURIComponent(item.id)}`, { method: "PATCH", body: payload });
      } else {
        await api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments`, { method: "POST", body: payload });
      }
      closeModal();
      toast(item ? "Корректировка обновлена" : "Корректировка создана", "ok");
      await reload();
    } catch (error) {
      toast(error?.data?.detail || error?.message || "Не удалось сохранить корректировку", "err");
    }
  };
}

async function updateAdjustment(id, payload) {
  try {
    const venueId = getActiveVenueId();
    await api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments/${encodeURIComponent(id)}`, { method: "PATCH", body: payload });
    toast("Корректировка обновлена", "ok");
    await reload();
  } catch (error) {
    toast(error?.data?.detail || error?.message || "Не удалось обновить корректировку", "err");
  }
}

async function deleteAdjustment(id) {
  if (!access.canManageAdjustments || !confirm("Удалить корректировку баланса?")) return;
  try {
    const venueId = getActiveVenueId();
    await api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments/${encodeURIComponent(id)}`, { method: "DELETE" });
    toast("Корректировка удалена", "ok");
    await reload();
  } catch (error) {
    toast(error?.data?.detail || error?.message || "Не удалось удалить корректировку", "err");
  }
}

function focusLinkedAdjustment() {
  if (state.sourceTargetFocused || !state.focusAdjustmentId) return;
  const target = document.querySelector(`[data-adjustment-row="${state.focusAdjustmentId}"]`);
  if (!target) return;
  state.sourceTargetFocused = true;
  target.classList.add("is-source-target");
  target.setAttribute("tabindex", "-1");
  requestAnimationFrame(() => {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.focus({ preventScroll: true });
  });
}

function renderTransfers() {
  const el = document.getElementById("transferList");
  if (!el) return;
  setText("transferHint", state.transfers.length ? `${primaryPeriodLabel()} · записей: ${state.transfers.length}` : `За ${primaryPeriodLabel()} переводов нет`);
  if (!state.transfers.length) {
    el.innerHTML = `<div class="muted">Нет переводов за выбранный период.</div>`;
    return;
  }
  el.innerHTML = state.transfers.map((item) => {
    const status = String(item.status || "CONFIRMED").toUpperCase();
    const actions = access.canManageTransfers ? `
      <div class="row row--end gap-8 mt-10">
        ${status !== "CONFIRMED" ? `<button class="btn small" data-transfer-status="CONFIRMED" data-transfer-id="${item.id}">Подтвердить</button>` : ""}
        ${status !== "DRAFT" ? `<button class="btn ghost small" data-transfer-status="DRAFT" data-transfer-id="${item.id}">В черновик</button>` : ""}
        ${status !== "CANCELLED" ? `<button class="btn ghost small" data-transfer-status="CANCELLED" data-transfer-id="${item.id}">Отменить</button>` : ""}
        <button class="btn small" data-transfer-edit="${item.id}">Изменить</button>
        <button class="btn danger small" data-transfer-del="${item.id}">Удалить</button>
      </div>` : "";
    return `
      <div class="expense-row ledger-source-target" id="transfer-${esc(item.id)}" data-transfer-row="${esc(item.id)}">
        <div class="expense-row__main">
          <div class="row gap-8">
            <div class="expense-row__title">${esc(item.from_payment_method?.title || "—")} → ${esc(item.to_payment_method?.title || "—")}</div>
            <span class="badge">${esc(statusLabel(status))}</span>
          </div>
          <div class="muted mt-6">${esc(item.transfer_date || "—")}</div>
          ${item.comment ? `<div class="mt-8">${esc(item.comment)}</div>` : ""}
        </div>
        <div class="expense-row__side">
          <div class="expense-row__amount">${esc(fmtMoneyMinor(item.amount_minor || 0))}</div>
          ${actions}
        </div>
      </div>
    `;
  }).join("");

  el.querySelectorAll("[data-transfer-edit]").forEach((btn) => {
    btn.onclick = () => openTransferForm(Number(btn.getAttribute("data-transfer-edit")));
  });
  el.querySelectorAll("[data-transfer-del]").forEach((btn) => {
    btn.onclick = () => deleteTransfer(Number(btn.getAttribute("data-transfer-del")));
  });
  el.querySelectorAll("[data-transfer-status]").forEach((btn) => {
    btn.onclick = () => updateTransfer(Number(btn.getAttribute("data-transfer-id")), { status: String(btn.getAttribute("data-transfer-status") || "DRAFT") });
  });
  focusLinkedTransfer();
}

function focusLinkedTransfer() {
  if (state.sourceTargetFocused || !state.focusTransferId) return;
  const target = document.querySelector(`[data-transfer-row="${state.focusTransferId}"]`);
  if (!target) return;
  state.sourceTargetFocused = true;
  target.classList.add("is-source-target");
  target.setAttribute("tabindex", "-1");
  requestAnimationFrame(() => {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.focus({ preventScroll: true });
  });
}

function buildTransferForm(item = null) {
  const fromOptions = state.paymentMethods.map((pm) => `<option value="${pm.id}" ${String(item?.from_payment_method_id || "") === String(pm.id) ? "selected" : ""}>${esc(pm.title)}</option>`).join("");
  const toOptions = state.paymentMethods.map((pm) => `<option value="${pm.id}" ${String(item?.to_payment_method_id || "") === String(pm.id) ? "selected" : ""}>${esc(pm.title)}</option>`).join("");
  const amount = item ? (Number(item.amount_minor || 0) / 100).toFixed(2) : "";
  const status = String(item?.status || "CONFIRMED").toUpperCase();
  return `
    <form id="transferForm" class="finance-form">
      <label>Из оплаты<select name="from_payment_method_id" required>${fromOptions}</select></label>
      <label>В оплату<select name="to_payment_method_id" required>${toOptions}</select></label>
      <label>Сумма, ₽<input name="amount" type="text" placeholder="1500.00" value="${esc(amount)}" required /></label>
      <label>Дата<input name="transfer_date" type="date" value="${esc(item?.transfer_date || defaultLedgerDate())}" required /></label>
      <label>Статус
        <select name="status">
          <option value="DRAFT" ${status === "DRAFT" ? "selected" : ""}>Черновик</option>
          <option value="CONFIRMED" ${status === "CONFIRMED" ? "selected" : ""}>Подтверждён</option>
          <option value="CANCELLED" ${status === "CANCELLED" ? "selected" : ""}>Отменён</option>
        </select>
      </label>
      <label>Комментарий<textarea name="comment" rows="4" placeholder="Комментарий">${esc(item?.comment || "")}</textarea></label>
      <div class="row gap-8 mt-12">
        <button class="btn" type="submit">${item ? "Сохранить" : "Добавить"}</button>
        <button class="btn ghost" type="button" id="transferCancel">Отмена</button>
      </div>
    </form>
  `;
}

function openTransferForm(transferId = null) {
  if (!access.canManageTransfers) return;
  if (state.paymentMethods.length < 2) {
    toast("Нужно минимум два типа оплаты", "warn");
    return;
  }
  const item = transferId ? state.transfers.find((x) => Number(x.id) === Number(transferId)) : null;
  openHtmlModal(item ? "Изменить перевод" : "Новый перевод", buildTransferForm(item));
  const form = document.getElementById("transferForm");
  document.getElementById("transferCancel")?.addEventListener("click", closeModal);
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const fd = new FormData(form);
      const payload = {
        from_payment_method_id: Number(fd.get("from_payment_method_id") || 0),
        to_payment_method_id: Number(fd.get("to_payment_method_id") || 0),
        amount_minor: parseMoneyToMinor(fd.get("amount")),
        transfer_date: String(fd.get("transfer_date") || ""),
        status: String(fd.get("status") || "CONFIRMED"),
        comment: String(fd.get("comment") || "").trim() || null,
      };
      if (payload.from_payment_method_id === payload.to_payment_method_id) throw new Error("Типы оплат должны отличаться");
      const venueId = getActiveVenueId();
      if (item) {
        await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers/${encodeURIComponent(item.id)}`, { method: "PATCH", body: payload });
      } else {
        await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers`, { method: "POST", body: payload });
      }
      closeModal();
      toast(item ? "Перевод обновлён" : "Перевод создан", "ok");
      await reload();
    } catch (err) {
      toast(err?.data?.detail || err.message || "Не удалось сохранить перевод", "err");
    }
  };
}

async function updateTransfer(id, payload) {
  const venueId = getActiveVenueId();
  await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers/${encodeURIComponent(id)}`, { method: "PATCH", body: payload });
  toast("Перевод обновлён", "ok");
  await reload();
}

async function deleteTransfer(id) {
  const venueId = getActiveVenueId();
  if (!confirm("Удалить перевод?")) return;
  await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers/${encodeURIComponent(id)}`, { method: "DELETE" });
  toast("Перевод удалён", "ok");
  await reload();
}

async function reload() {
  const venueId = getActiveVenueId();
  const month = document.getElementById("ledgerMonthPick")?.value || state.month || currentMonth();
  if (state.periodMode === "month") state.month = month;
  const visibleRange = primaryRange();
  if (state.operationsDay && visibleRange && (state.operationsDay < visibleRange.from || state.operationsDay > visibleRange.to)) {
    state.operationsDay = null;
  }
  syncFinanceLinks();
  syncComparisonUi();

  const periodQp = appendPrimaryPeriod(new URLSearchParams());
  const qp = appendLedgerFilters(new URLSearchParams(periodQp));

  const comparison = currentComparison();
  const compareQp = new URLSearchParams();
  if (comparison?.from) compareQp.set("date_from", comparison.from);
  if (comparison?.to) compareQp.set("date_to", comparison.to);
  appendLedgerFilters(compareQp);

  const analyticsPromise = access.canView
    ? api(`/venues/${encodeURIComponent(venueId)}/finance/entries/analytics?${qp.toString()}`)
    : Promise.resolve(null);
  const comparisonPromise = access.canView && comparison
    ? api(`/venues/${encodeURIComponent(venueId)}/finance/entries/analytics?${compareQp.toString()}`).then((value) => ({ value })).catch((error) => ({ error }))
    : Promise.resolve({ value: null });
  const transfersPromise = access.canView
    ? api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers?${periodQp.toString()}`)
    : Promise.resolve([]);
  const adjustmentsPromise = access.canView
    ? api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments?${periodQp.toString()}`)
    : Promise.resolve([]);
  const reconciliationPromise = access.canViewReconciliation
    ? api(`/venues/${encodeURIComponent(venueId)}/finance/reconciliation?${periodQp.toString()}`).then((value) => ({ value })).catch((error) => ({ error }))
    : Promise.resolve({ value: null });
  const [analytics, comparisonResult, transfers, adjustments, reconciliationResult] = await Promise.all([
    analyticsPromise,
    comparisonPromise,
    transfersPromise,
    adjustmentsPromise,
    reconciliationPromise,
  ]);
  state.analytics = analytics || null;
  state.comparisonAnalytics = comparisonResult.value || null;
  state.comparisonError = comparisonResult.error || null;
  state.transfers = Array.isArray(transfers) ? transfers : [];
  state.adjustments = Array.isArray(adjustments) ? adjustments : [];
  state.reconciliation = reconciliationResult.value || null;
  state.reconciliationError = reconciliationResult.error || null;
  syncUrl();
  renderChartContext();
  renderMetrics();
  renderTrendChart();
  renderStructureChart();
  renderReconciliation();
  renderOperationsSummary();
  renderAdjustments();
  renderTransfers();
  const operations = document.getElementById("ledgerOperations");
  if (operations?.open) await loadOperations({ reset: true });
  else {
    state.entries = [];
    state.operationsLoaded = false;
    state.operationsOffset = 0;
    state.operationsHasMore = false;
    renderEntries();
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("venue");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId() || "";
  if (!venueId) {
    toast("Сначала выбери заведение", "err");
    return;
  }
  setActiveVenueId(venueId);
  await mountNav({ activeTab: "venue", requireVenue: true });
  await loadAccess();
  setupDemoLedgerIntro();

  state.paymentMethods = await getPaymentMethods(venueId, { includeArchived: false });
  renderPaymentMethodOptions();
  state.month = params.get("month") || currentMonth();
  const linkedRange = normalizeIsoRange(params.get("date_from") || "", params.get("date_to") || "");
  state.periodMode = params.get("period_mode") === "range" && linkedRange ? "range" : "month";
  const fallbackRange = monthRange(state.month) || monthRange(currentMonth());
  state.dateFrom = linkedRange?.from || fallbackRange?.from || todayISO();
  state.dateTo = linkedRange?.to || fallbackRange?.to || state.dateFrom;
  if (state.periodMode === "range") state.month = state.dateFrom.slice(0, 7);
  syncPeriodUi();
  document.getElementById("ledgerPaymentMethodPick").value = params.get("payment_method_id") || "";
  document.getElementById("ledgerKindPick").value = (params.get("kind") || "").toUpperCase();
  document.getElementById("ledgerDirectionPick").value = (params.get("direction") || "").toUpperCase();
  document.getElementById("ledgerSourcePick").value = (params.get("source_type") || "").toLowerCase();
  state.focusTransferId = Number(params.get("transfer_id") || 0) || null;
  state.focusAdjustmentId = Number(params.get("adjustment_id") || 0) || null;
  syncFinanceLinks();
  state.compareMode = ["auto", "custom", "none"].includes(params.get("compare_mode")) ? params.get("compare_mode") : "auto";
  state.compareFrom = params.get("compare_from") || "";
  state.compareTo = params.get("compare_to") || "";
  if (state.compareMode === "custom" && !normalizeIsoRange(state.compareFrom, state.compareTo)) {
    const automatic = resolveComparisonRange({
      period: state.periodMode,
      month: state.month,
      from: state.dateFrom,
      to: state.dateTo,
    });
    state.compareFrom = automatic?.from || primaryRange()?.from || todayISO();
    state.compareTo = automatic?.to || state.compareFrom;
  }
  syncComparisonUi();
  document.querySelectorAll("#ledgerPeriodSeg [data-period]").forEach((button) => {
    button.onclick = async () => {
      const nextMode = button.dataset.period === "range" ? "range" : "month";
      if (nextMode === state.periodMode) return;
      state.periodMode = nextMode;
      if (nextMode === "range") {
        const range = monthRange(state.month);
        state.dateFrom = range?.from || state.dateFrom;
        state.dateTo = range?.to || state.dateTo;
      }
      syncPeriodUi();
      syncComparisonUi();
      await reload();
    };
  });
  document.getElementById("ledgerMonthPick").onchange = async (event) => {
    state.month = event.target.value || currentMonth();
    const range = monthRange(state.month);
    state.dateFrom = range?.from || state.dateFrom;
    state.dateTo = range?.to || state.dateTo;
    await reload();
  };
  document.getElementById("ledgerDateFrom").onchange = (event) => { state.dateFrom = event.target.value || state.dateFrom; };
  document.getElementById("ledgerDateTo").onchange = (event) => { state.dateTo = event.target.value || state.dateTo; };
  document.getElementById("ledgerDateApply").onclick = async () => {
    const normalized = normalizeIsoRange(state.dateFrom, state.dateTo);
    if (!normalized) {
      toast("Выбери обе даты периода", "warn");
      return;
    }
    state.dateFrom = normalized.from;
    state.dateTo = normalized.to;
    state.month = normalized.from.slice(0, 7);
    syncPeriodUi();
    await reload();
  };
  document.getElementById("ledgerPaymentMethodPick").onchange = reload;
  document.getElementById("ledgerKindPick").onchange = reload;
  document.getElementById("ledgerDirectionPick").onchange = reload;
  document.getElementById("ledgerSourcePick").onchange = reload;
  document.getElementById("ledgerFiltersReset").onclick = async () => {
    document.getElementById("ledgerPaymentMethodPick").value = "";
    document.getElementById("ledgerKindPick").value = "";
    document.getElementById("ledgerDirectionPick").value = "";
    document.getElementById("ledgerSourcePick").value = "";
    await reload();
  };
  const exportLedgerBtn = document.getElementById("exportLedgerBtn");
  setVisible(exportLedgerBtn, access.canView && !financialValuesHidden);
  exportLedgerBtn.onclick = async () => {
    exportLedgerBtn.disabled = true;
    try {
      const query = currentLedgerQuery();
      await openExportLink(`/venues/${encodeURIComponent(venueId)}/finance/entries/export-link?${query.toString()}`);
    } catch (error) {
      toast(error?.data?.detail || error?.message || "Не удалось сформировать XLSX", "err");
    } finally {
      exportLedgerBtn.disabled = false;
    }
  };
  const addAdjustmentBtn = document.getElementById("addAdjustmentBtn");
  setVisible(addAdjustmentBtn, access.canManageAdjustments);
  addAdjustmentBtn.onclick = () => openAdjustmentForm();
  const addTransferBtn = document.getElementById("addTransferBtn");
  setVisible(addTransferBtn, access.canManageTransfers);
  addTransferBtn.onclick = () => openTransferForm();
  document.querySelectorAll("#ledgerCompareSeg [data-compare]").forEach((button) => {
    button.onclick = async () => {
      const requestedMode = button.dataset.compare;
      const nextMode = ["auto", "custom", "none"].includes(requestedMode) ? requestedMode : "auto";
      if (nextMode === "custom" && state.compareMode !== "custom") {
        const automatic = currentComparison();
        state.compareFrom = automatic?.from || primaryRange()?.from || todayISO();
        state.compareTo = automatic?.to || state.compareFrom;
      }
      state.compareMode = nextMode;
      syncComparisonUi();
      await reload();
    };
  });
  document.getElementById("ledgerCompareFrom").onchange = (event) => { state.compareFrom = event.target.value || state.compareFrom; };
  document.getElementById("ledgerCompareTo").onchange = (event) => { state.compareTo = event.target.value || state.compareTo; };
  document.getElementById("ledgerCompareApply").onclick = async () => {
    const normalized = normalizeIsoRange(state.compareFrom, state.compareTo);
    if (!normalized) {
      toast("Выбери обе даты периода сравнения", "warn");
      return;
    }
    state.compareFrom = normalized.from;
    state.compareTo = normalized.to;
    await reload();
  };
  const operations = document.getElementById("ledgerOperations");
  operations?.addEventListener("toggle", () => {
    if (operations.open && !state.operationsLoaded) loadOperations({ reset: true });
  });
  document.getElementById("ledgerOperationsMore")?.addEventListener("click", () => loadOperations());
  document.getElementById("ledgerOperationsDayReset")?.addEventListener("click", async () => {
    state.operationsDay = null;
    renderOperationsSummary();
    renderTrendChart();
    await loadOperations({ reset: true });
  });
  document.querySelectorAll("[data-close], .modal__backdrop").forEach((el) => el.addEventListener("click", closeModal));

  await reload();
}

document.addEventListener("DOMContentLoaded", boot);

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
  coerceDemoMonth,
  coerceDemoRange,
  isDemoUiMode,
  getStoredDemoUiState,
  getDemoMonthLabel,
  mountDemoPageTour,
  trackDemoEvent,
} from "/app.js?v=20260726-navmore1";
import { canViewRevenue, hasFinanceLedgerViewAccess, isOwnerRole, permSetFromResponse, roleUpper, hasPerm, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js?v=20260503-finprivacy1";
import { normalizeIsoRange, resolveAutoComparison } from "/app/period-comparison.js?v=20260802-financeux2";
import {
  buildFinanceCostStructure,
  buildFinancePeriodComparisonGeometry,
  normalizeFinanceDailySeries,
} from "/app/finance-summary-analytics.js?v=20260802-summarycompare1";

let financialValuesHidden = false;

function fmtMoneyMinor(minor) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
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

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function fmtCompactMoneyMinor(minor) {
  const rubles = Number(minor || 0) / 100;
  const absolute = Math.abs(rubles);
  const format = (value, suffix) => `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: value >= 10 ? 0 : 1 }).format(value)}${suffix}`;
  if (absolute >= 1_000_000) return `${rubles < 0 ? "−" : ""}${format(absolute / 1_000_000, " млн")}`;
  if (absolute >= 1_000) return `${rubles < 0 ? "−" : ""}${format(absolute / 1_000, " тыс")}`;
  return `${new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(rubles)}`;
}

function fmtShortDate(value) {
  const [year, month, day] = String(value || "").split("-");
  return year && month && day ? `${day}.${month}` : String(value || "");
}

function fmtLongDate(value) {
  const [year, month, day] = String(value || "").split("-");
  if (!year || !month || !day) return String(value || "");
  try {
    return new Intl.DateTimeFormat("ru-RU", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" })
      .format(new Date(Date.UTC(Number(year), Number(month) - 1, Number(day))));
  } catch {
    return `${day}.${month}.${year}`;
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
  return coerceDemoMonth(`${y}-${m}`, { notify: false, context: "owner-summary" });
}

let state = {
  period: "month",
  month: currentMonth(),
  day: todayISO(),
  from: todayISO(),
  to: todayISO(),
  compareMode: "auto",
  compareFrom: "",
  compareTo: "",
  trendMetric: "revenue",
  summaryData: null,
  comparisonSummaryData: null,
};


const DEMO_OWNER_INTRO_DISMISSED_KEY = "axelio.demo_intro.owner_summary.dismissed";

function renderDemoOwnerIntro() {
  const intro = document.getElementById("demoSummaryIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) {
    intro.classList.add("hidden");
    return;
  }
  try {
    if (sessionStorage.getItem(DEMO_OWNER_INTRO_DISMISSED_KEY) === "1") {
      intro.classList.add("hidden");
      return;
    }
  } catch {}
  const monthLabel = getDemoMonthLabel(demoState) || "подготовленный период";
  const introText = document.getElementById("demoSummaryIntroText");
  if (introText) introText.textContent = `Подготовленные данные за ${monthLabel}. Начни со сводки, затем посмотри расходы и начисления команды.`;
  document.getElementById("demoGoExpenses")?.addEventListener("click", () => {
    const venueId = getActiveVenueId();
    if (venueId) window.location.href = `/owner-expenses.html?venue_id=${encodeURIComponent(String(venueId))}`;
  });
  document.getElementById("demoGoPayroll")?.addEventListener("click", () => {
    const venueId = getActiveVenueId();
    if (venueId) window.location.href = `/owner-payroll.html?venue_id=${encodeURIComponent(String(venueId))}`;
  });
  document.getElementById("demoGoVenue")?.addEventListener("click", () => {
    const venueId = getActiveVenueId();
    if (venueId) window.location.href = `/app-venue.html?venue_id=${encodeURIComponent(String(venueId))}`;
  });
  document.getElementById("demoSummaryIntroClose")?.addEventListener("click", () => {
    intro.classList.add("hidden");
    try { sessionStorage.setItem(DEMO_OWNER_INTRO_DISMISSED_KEY, "1"); } catch {}
  });
  intro.classList.remove("hidden");
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
    el.classList.remove("is-loading");
    el.removeAttribute("aria-busy");
  }
}

function showBlock(id, visible) {
  const el = document.getElementById(id);
  el?.classList.toggle("hidden", !visible);
}

function setVisible(element, visible) {
  element?.classList.toggle("hidden", !visible);
}

function setSummaryState(title = "", text = "") {
  const stateCard = document.getElementById("summaryState");
  const visible = Boolean(title || text);
  setText("summaryStateTitle", title);
  setText("summaryStateText", text);
  setVisible(stateCard, visible);
}

function normalizeRange() {
  const demoRange = coerceDemoRange(state.from, state.to, { notify: false, context: "owner-summary" });
  if (demoRange.from && demoRange.to) {
    state.from = demoRange.from;
    state.to = demoRange.to;
    return;
  }
  if (!state.from) state.from = todayISO();
  if (!state.to) state.to = state.from;
  if (state.from > state.to) {
    const tmp = state.from;
    state.from = state.to;
    state.to = tmp;
  }
}

function normalizeCompareRange() {
  const normalized = normalizeIsoRange(state.compareFrom, state.compareTo);
  if (normalized) {
    state.compareFrom = normalized.from;
    state.compareTo = normalized.to;
    return normalized;
  }
  const automatic = resolveAutoComparison(state);
  state.compareFrom = automatic?.from || state.day || todayISO();
  state.compareTo = automatic?.to || state.compareFrom;
  return { from: state.compareFrom, to: state.compareTo };
}

function setActiveSeg(containerId, dataKey, value) {
  document.querySelectorAll(`#${containerId} button`).forEach((btn) => {
    if (btn.dataset[dataKey] === value) btn.classList.add("active");
    else btn.classList.remove("active");
  });
}

function syncPickers() {
  showBlock("summaryMonthPick", state.period === "month");
  showBlock("summaryDayPick", state.period === "day");
  showBlock("summaryRangePick", state.period === "range");
}

function currentComparison() {
  if (state.compareMode === "none") return null;
  if (state.compareMode === "custom") {
    const range = normalizeCompareRange();
    return { ...range, caption: "к выбранному периоду" };
  }
  return resolveAutoComparison(state);
}

function syncComparisonControls() {
  const custom = state.compareMode === "custom";
  const disabled = state.compareMode === "none";
  showBlock("summaryCompareRangePick", custom);
  setActiveSeg("summaryCompareSeg", "compare", state.compareMode);
  const comparison = currentComparison();
  const fromPick = document.getElementById("summaryCompareFromPick");
  const toPick = document.getElementById("summaryCompareToPick");
  if (custom && fromPick) fromPick.value = comparison?.from || "";
  if (custom && toPick) toPick.value = comparison?.to || "";
  setText(
    "summaryComparePeriodText",
    disabled ? "Сравнение отключено" : (comparison?.from && comparison?.to ? `${comparison.from} — ${comparison.to}` : "Период не определён"),
  );
  setText(
    "summaryCompareHint",
    disabled ? "Дополнительный период не загружается." : (comparison?.caption || "Автоматический период сравнения зависит от выбранного режима."),
  );
}

function buildSummaryQuery() {
  const qp = new URLSearchParams();
  qp.set("period", state.period);
  if (state.period === "month") {
    qp.set("month", state.month || currentMonth());
  } else if (state.period === "day") {
    const day = state.day || todayISO();
    qp.set("day", day);
    qp.set("date_from", day);
    qp.set("date_to", day);
  } else {
    normalizeRange();
    qp.set("date_from", state.from || todayISO());
    qp.set("date_to", state.to || todayISO());
  }
  return qp;
}

function buildComparisonQuery() {
  const comparison = currentComparison();
  const qp = new URLSearchParams();
  qp.set("period", "range");
  qp.set("date_from", comparison?.from || todayISO());
  qp.set("date_to", comparison?.to || comparison?.from || todayISO());
  return qp;
}

function syncUrl() {
  const qp = buildSummaryQuery();
  qp.set("compare_mode", state.compareMode);
  if (state.compareMode === "custom") {
    const comparison = currentComparison();
    if (comparison?.from) qp.set("compare_from", comparison.from);
    if (comparison?.to) qp.set("compare_to", comparison.to);
  }
  const venueId = getActiveVenueId();
  if (venueId) qp.set("venue_id", String(venueId));
  history.replaceState(null, "", `${location.pathname}?${qp.toString()}`);
}

function statePeriodText() {
  if (state.period === "month") return state.month || currentMonth();
  if (state.period === "day") return state.day || todayISO();
  normalizeRange();
  return `${state.from} — ${state.to}`;
}

function fmtSignedMoneyMinor(value) {
  const amount = Number(value || 0);
  const sign = amount > 0 ? "+" : amount < 0 ? "−" : "";
  return `${sign}${fmtMoneyMinor(Math.abs(amount))}`;
}

function fmtSignedNumber(value, digits = 1) {
  const number = Number(value || 0);
  const sign = number > 0 ? "+" : number < 0 ? "−" : "";
  return `${sign}${Math.abs(number).toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function renderMetricDelta(id, currentValue, previousValue, { type = "money", caption = "", goodWhen = "neutral" } = {}) {
  const element = document.getElementById(id);
  if (!element) return;
  element.classList.remove("is-up", "is-down", "is-neutral");
  if (financialValuesHidden || currentValue === null || currentValue === undefined || previousValue === null || previousValue === undefined) {
    element.textContent = "—";
    element.classList.add("is-neutral");
    return;
  }

  const current = Number(currentValue || 0);
  const previous = Number(previousValue || 0);
  const delta = current - previous;
  const positiveResult = (goodWhen === "up" && delta > 0) || (goodWhen === "down" && delta < 0);
  const negativeResult = (goodWhen === "up" && delta < 0) || (goodWhen === "down" && delta > 0);
  element.classList.add(positiveResult ? "is-up" : negativeResult ? "is-down" : "is-neutral");

  if (type === "bps") {
    element.textContent = `${fmtSignedNumber(delta / 100, 2)} п.п. ${caption}`.trim();
    return;
  }
  if (previous === 0) {
    element.textContent = current === 0 ? `Без изменений ${caption}`.trim() : `Нет базы: ${fmtSignedMoneyMinor(delta)} ${caption}`.trim();
    return;
  }
  const percent = (delta / Math.abs(previous)) * 100;
  element.textContent = `${fmtSignedNumber(percent, 1)}% (${fmtSignedMoneyMinor(delta)}) ${caption}`.trim();
}

function renderComparison(summary, comparisonSummary) {
  const caption = currentComparison()?.caption || "";
  const currentExpense = summary?.expense_without_payroll_minor ?? summary?.expense_minor;
  const previousExpense = comparisonSummary?.expense_without_payroll_minor ?? comparisonSummary?.expense_minor;
  const currentTotalCost = summary?.total_cost_minor ?? (Number(summary?.expense_minor || 0) + Number(summary?.payroll_minor || 0));
  const previousTotalCost = comparisonSummary?.total_cost_minor ?? (Number(comparisonSummary?.expense_minor || 0) + Number(comparisonSummary?.payroll_minor || 0));
  [
    ["summaryRevenueDelta", summary?.revenue_minor, comparisonSummary?.revenue_minor, "money", "up"],
    ["summaryProfitDelta", summary?.profit_minor, comparisonSummary?.profit_minor, "money", "up"],
    ["summaryMarginDelta", summary?.margin_bps, comparisonSummary?.margin_bps, "bps", "up"],
    ["summaryExpensesDelta", currentExpense, previousExpense, "money", "down"],
    ["summaryPayrollDelta", summary?.payroll_minor, comparisonSummary?.payroll_minor, "money", "down"],
    ["summaryTotalCostDelta", currentTotalCost, previousTotalCost, "money", "down"],
    ["summaryAdjustmentsDelta", summary?.adjustments_minor, comparisonSummary?.adjustments_minor, "money", "neutral"],
    ["summaryRefundsDelta", summary?.refunds_minor, comparisonSummary?.refunds_minor, "money", "neutral"],
    ["summaryExpenseRatioDelta", summary?.expense_ratio_bps, comparisonSummary?.expense_ratio_bps, "bps", "down"],
    ["summaryPayrollRatioDelta", summary?.payroll_ratio_bps, comparisonSummary?.payroll_ratio_bps, "bps", "down"],
    ["summaryTotalCostRatioDelta", summary?.total_cost_ratio_bps, comparisonSummary?.total_cost_ratio_bps, "bps", "down"],
  ].forEach(([id, current, previous, type, goodWhen]) => renderMetricDelta(id, current, previous, { type, caption, goodWhen }));
}

function resetComparisonDeltas(text = "—") {
  [
    "summaryRevenueDelta",
    "summaryProfitDelta",
    "summaryMarginDelta",
    "summaryExpensesDelta",
    "summaryPayrollDelta",
    "summaryTotalCostDelta",
    "summaryAdjustmentsDelta",
    "summaryRefundsDelta",
    "summaryExpenseRatioDelta",
    "summaryPayrollRatioDelta",
    "summaryTotalCostRatioDelta",
  ].forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;
    element.textContent = text;
    element.classList.remove("is-up", "is-down");
    element.classList.add("is-neutral");
  });
}

function syncAnalyticsAccess() {
  const grid = document.getElementById("summaryAnalyticsGrid");
  const trendVisible = financeAccess.canViewRevenue || financeAccess.canViewExpenses || financeAccess.canViewPayroll;
  const structureVisible = financeAccess.canViewExpenses || financeAccess.canViewPayroll;
  showBlock("summaryTrendCard", trendVisible);
  showBlock("summaryStructureCard", structureVisible);
  showBlock("summaryAnalyticsGrid", trendVisible || structureVisible);
  grid?.classList.toggle("summary-analytics-grid--single", trendVisible !== structureVisible);
}

function syncSummaryMetricAccess() {
  showBlock("summaryPrimaryKpis", financeAccess.canViewRevenue || financeAccess.canViewProfit);
  showBlock("summarySecondaryKpis", financeAccess.canViewRevenue || financeAccess.canViewExpenses || financeAccess.canViewPayroll);
  showBlock(
    "summaryRatioKpis",
    (financeAccess.canViewRevenue && financeAccess.canViewExpenses)
      || (financeAccess.canViewRevenue && financeAccess.canViewPayroll),
  );
  showBlock("revenueCard", financeAccess.canViewRevenue);
  showBlock("profitCard", financeAccess.canViewProfit);
  showBlock("marginCard", financeAccess.canViewProfit);
  showBlock("expensesCard", financeAccess.canViewExpenses);
  showBlock("payrollCard", financeAccess.canViewPayroll);
  showBlock("totalCostCard", financeAccess.canViewExpenses && financeAccess.canViewPayroll);
  showBlock("adjustmentsCard", financeAccess.canViewRevenue);
  showBlock("refundsCard", financeAccess.canViewRevenue);
  showBlock("expenseRatioCard", financeAccess.canViewRevenue && financeAccess.canViewExpenses);
  showBlock("payrollRatioCard", financeAccess.canViewRevenue && financeAccess.canViewPayroll);
  showBlock("totalCostRatioCard", financeAccess.canViewProfit);
}

function visibleTrendPoints(summary) {
  return normalizeFinanceDailySeries(summary?.daily_series).map((point) => {
    const visibleExpense = financeAccess.canViewExpenses ? Number(point.expenseMinor || 0) : 0;
    const visiblePayroll = financeAccess.canViewPayroll ? Number(point.payrollMinor || 0) : 0;
    return {
      ...point,
      revenueMinor: financeAccess.canViewRevenue ? point.revenueMinor : null,
      totalCostMinor: (financeAccess.canViewExpenses || financeAccess.canViewPayroll)
        ? visibleExpense + visiblePayroll
        : null,
      profitMinor: financeAccess.canViewProfit ? point.profitMinor : null,
    };
  });
}

function availableTrendMetrics() {
  return [
    ...(financeAccess.canViewRevenue ? ["revenue"] : []),
    ...(financeAccess.canViewExpenses || financeAccess.canViewPayroll ? ["cost"] : []),
    ...(financeAccess.canViewProfit ? ["profit"] : []),
  ];
}

function trendMetricTitle(metric) {
  if (metric === "profit") return "Прибыль";
  if (metric === "cost") {
    if (financeAccess.canViewExpenses && financeAccess.canViewPayroll) return "Затраты";
    return financeAccess.canViewExpenses ? "Расходы" : "ФОТ";
  }
  return "Выручка";
}

function syncTrendMetricControls() {
  const available = availableTrendMetrics();
  if (!available.includes(state.trendMetric)) state.trendMetric = available[0] || "revenue";
  document.querySelectorAll("#summaryTrendMetricSeg [data-trend-metric]").forEach((button) => {
    const metric = button.dataset.trendMetric;
    setVisible(button, available.includes(metric));
    button.classList.toggle("active", metric === state.trendMetric);
    button.setAttribute("aria-pressed", metric === state.trendMetric ? "true" : "false");
    button.onclick = () => {
      state.trendMetric = metric;
      renderSummaryTrend(state.summaryData, state.comparisonSummaryData);
    };
  });
}

function buildDayEconomicsDrilldown(currentPoint, comparisonPoint) {
  if (!currentPoint?.date || (!financeAccess.canViewRevenue && !financeAccess.canViewExpenses)) return "";
  const qp = new URLSearchParams();
  const venueId = getActiveVenueId();
  if (venueId) qp.set("venue_id", String(venueId));
  qp.set("date", currentPoint.date);
  if (comparisonPoint?.date) {
    qp.set("compare_mode", "custom");
    qp.set("compare_date", comparisonPoint.date);
  }
  return `/owner-day-economics.html?${qp.toString()}`;
}

function renderSummaryTrendFocus(currentPoint, comparisonPoint, metric) {
  const focus = document.getElementById("summaryTrendFocus");
  if (!focus) return;
  if ((!currentPoint && !comparisonPoint) || financialValuesHidden) {
    focus.textContent = financialValuesHidden ? FINANCIAL_VALUES_HIDDEN_LABEL : "Выбери день на графике";
    return;
  }
  const field = { revenue: "revenueMinor", cost: "totalCostMinor", profit: "profitMinor" }[metric] || "revenueMinor";
  const values = [];
  if (currentPoint) {
    values.push(`<span class="summary-chart-focus__value">Текущий: <b>${escapeHtml(fmtLongDate(currentPoint.date))}</b><span aria-hidden="true">—</span>${escapeHtml(fmtMoneyMinor(currentPoint[field]))}</span>`);
  }
  if (comparisonPoint) {
    values.push(`<span class="summary-chart-focus__value">Сравнение: <b>${escapeHtml(fmtLongDate(comparisonPoint.date))}</b><span aria-hidden="true">—</span>${escapeHtml(fmtMoneyMinor(comparisonPoint[field]))}</span>`);
  }
  const detailUrl = buildDayEconomicsDrilldown(currentPoint, comparisonPoint);
  const detailLink = detailUrl
    ? `<a class="summary-chart-focus__action" href="${escapeHtml(detailUrl)}">Открыть экономику дня</a>`
    : "";
  focus.innerHTML = `<span class="summary-chart-focus__values">${values.join("")}</span>${detailLink}`;
}

function renderSummaryTrend(summary, comparisonSummary = null) {
  const chart = document.getElementById("summaryTrendChart");
  const legend = document.getElementById("summaryTrendLegend");
  const subtitle = document.getElementById("summaryTrendSubtitle");
  const title = document.getElementById("summaryTrendTitle");
  if (!chart || !legend || !subtitle || !title) return;

  syncTrendMetricControls();
  const metric = state.trendMetric;
  const metricTitle = trendMetricTitle(metric);
  const points = visibleTrendPoints(summary);
  const comparisonPoints = visibleTrendPoints(comparisonSummary);
  const periodText = summary?.period_start && summary?.period_end
    ? `${summary.period_start} — ${summary.period_end}`
    : statePeriodText();
  const comparisonText = comparisonSummary?.period_start && comparisonSummary?.period_end
    ? `${comparisonSummary.period_start} — ${comparisonSummary.period_end}`
    : "";
  title.textContent = `Динамика: ${metricTitle.toLowerCase()}`;
  subtitle.textContent = comparisonPoints.length
    ? `${periodText} против ${comparisonText} — сопоставление по порядковому дню`
    : `${periodText} — по дням`;
  legend.innerHTML = [
    `<span><i class="summary-legend-swatch" aria-hidden="true"></i>Текущий период</span>`,
    ...(comparisonPoints.length ? [`<span><i class="summary-legend-swatch summary-legend-swatch--comparison" aria-hidden="true"></i>Сравниваемый период</span>`] : []),
  ].join("");

  if (financialValuesHidden) {
    chart.innerHTML = `<div class="summary-chart-empty">${escapeHtml(FINANCIAL_VALUES_HIDDEN_LABEL)}</div>`;
    renderSummaryTrendFocus(null, null, metric);
    return;
  }
  const geometry = buildFinancePeriodComparisonGeometry(points, comparisonPoints, { metric, width: 720, height: 200 });
  if (!geometry || geometry.pointCount < 2) {
    chart.innerHTML = `<div class="summary-chart-empty">${geometry?.pointCount
      ? "Для одного дня динамика не строится — точные значения уже показаны в KPI."
      : "За выбранный период нет дневных данных для графика."}</div>`;
    renderSummaryTrendFocus(points[0] || null, comparisonPoints[0] || null, metric);
    return;
  }

  const denseClass = geometry.pointCount > 45 ? " is-dense" : "";
  const gridLines = [0, 50, 100, 150, 200]
    .map((y) => `<line class="summary-trend-gridline" x1="0" y1="${y}" x2="720" y2="${y}"></line>`)
    .join("");
  const zeroLine = geometry.zeroY > 1 && geometry.zeroY < geometry.height - 1
    ? `<line class="summary-trend-zero" x1="0" y1="${geometry.zeroY.toFixed(2)}" x2="720" y2="${geometry.zeroY.toFixed(2)}"></line>`
    : "";
  let marks = "";
  if (geometry.mode === "lines") {
    marks += `<path class="summary-trend-line summary-trend-line--current" d="${geometry.currentPath}"></path>`;
    if (geometry.comparisonPath) marks += `<path class="summary-trend-line summary-trend-line--comparison" d="${geometry.comparisonPath}"></path>`;
    marks += geometry.current.filter(Boolean).map((point) => `<circle class="summary-trend-marker summary-trend-marker--current" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="3"></circle>`).join("");
    marks += geometry.comparison.filter(Boolean).map((point) => `<circle class="summary-trend-marker summary-trend-marker--comparison" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="3"></circle>`).join("");
  } else {
    const barWidth = Math.max(5, Math.min(28, geometry.bandWidth * (comparisonPoints.length ? 0.28 : 0.44)));
    marks += Array.from({ length: geometry.pointCount }, (_, index) => {
      const currentPoint = geometry.current[index];
      const comparisonPoint = geometry.comparison[index];
      const centerX = (index + 0.5) * geometry.bandWidth;
      return [
        currentPoint ? `<rect class="summary-trend-bar--current" x="${(centerX - barWidth - 2).toFixed(2)}" y="${currentPoint.barY.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${currentPoint.barHeight.toFixed(2)}" rx="2"></rect>` : "",
        comparisonPoint ? `<rect class="summary-trend-bar--comparison" x="${(centerX + 2).toFixed(2)}" y="${comparisonPoint.barY.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${comparisonPoint.barHeight.toFixed(2)}" rx="2"></rect>` : "",
      ].join("");
    }).join("");
  }
  const hitTargets = Array.from({ length: geometry.pointCount }, (_, index) => (
    `<g class="summary-trend-hit-group" data-summary-point="${index}" role="button" tabindex="0" aria-label="Порядковый день ${index + 1}">`
      + `<rect class="summary-trend-hit" x="${(index * geometry.bandWidth).toFixed(2)}" y="0" width="${geometry.bandWidth.toFixed(2)}" height="200"></rect>`
      + "</g>"
  )).join("");
  const tickCount = Math.min(7, geometry.pointCount);
  const tickIndexes = [...new Set(Array.from({ length: tickCount }, (_, index) => (
    Math.round((index * (geometry.pointCount - 1)) / Math.max(1, tickCount - 1))
  )))];
  const ticks = tickIndexes.map((index) => {
    const point = points[index] || comparisonPoints[index];
    const label = comparisonPoints.length ? String(index + 1) : fmtShortDate(point?.date);
    return `<span>${escapeHtml(label)}</span>`;
  }).join("");
  chart.innerHTML = `
    <div class="summary-trend-scale" aria-hidden="true">
      <span>${escapeHtml(fmtCompactMoneyMinor(geometry.maxValue))}</span>
      <span>${escapeHtml(fmtCompactMoneyMinor(geometry.minValue))}</span>
    </div>
    <div class="summary-trend-visual">
      <svg class="summary-trend-svg${denseClass}" viewBox="0 0 720 200" preserveAspectRatio="none" role="img" aria-label="${escapeHtml(comparisonPoints.length
        ? `${metricTitle} по порядковым дням текущего и сравниваемого периода`
        : `${metricTitle} по дням выбранного периода`)}">
        ${gridLines}${zeroLine}${marks}${hitTargets}
      </svg>
      <div class="summary-trend-ticks" aria-hidden="true">${ticks}</div>
    </div>`;

  let defaultIndex = geometry.pointCount - 1;
  for (let index = geometry.pointCount - 1; index >= 0; index -= 1) {
    if (geometry.current[index] || geometry.comparison[index]) {
      defaultIndex = index;
      break;
    }
  }
  const activatePoint = (index) => {
    chart.querySelectorAll("[data-summary-point]").forEach((target) => {
      const active = Number(target.dataset.summaryPoint) === index;
      target.classList.toggle("is-active", active);
      target.setAttribute("aria-pressed", active ? "true" : "false");
    });
    renderSummaryTrendFocus(points[index] || null, comparisonPoints[index] || null, metric);
  };
  chart.querySelectorAll("[data-summary-point]").forEach((target) => {
    const index = Number(target.dataset.summaryPoint);
    target.addEventListener("click", () => activatePoint(index));
    target.addEventListener("focus", () => activatePoint(index));
    target.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      activatePoint(index);
    });
  });
  activatePoint(defaultIndex);
}

function renderSummaryCostStructure(summary) {
  const container = document.getElementById("summaryCostStructure");
  const subtitle = document.getElementById("summaryStructureSubtitle");
  if (!container || !subtitle) return;
  const sourceRows = (Array.isArray(summary?.cost_structure) ? summary.cost_structure : []).filter((row) => (
    String(row?.key || "") === "payroll" ? financeAccess.canViewPayroll : financeAccess.canViewExpenses
  ));
  const visibleTotal = sourceRows.reduce((sum, row) => sum + Math.max(0, Number(row?.amount_minor || 0)), 0);
  const rows = buildFinanceCostStructure(sourceRows, visibleTotal, 6);
  const periodText = summary?.period_start && summary?.period_end
    ? `${summary.period_start} — ${summary.period_end}`
    : statePeriodText();
  subtitle.textContent = `${periodText} · подтверждённые расходы и распределённый ФОТ`;
  if (financialValuesHidden) {
    container.innerHTML = `<div class="summary-chart-empty">${escapeHtml(FINANCIAL_VALUES_HIDDEN_LABEL)}</div>`;
    return;
  }
  if (!rows.length) {
    container.innerHTML = '<div class="summary-chart-empty">За выбранный период подтверждённых затрат нет.</div>';
    return;
  }
  const buildDrilldown = (row) => {
    const qp = new URLSearchParams();
    const venueId = getActiveVenueId();
    if (venueId) qp.set("venue_id", String(venueId));
    qp.set("compare_mode", state.compareMode);
    const comparison = currentComparison();
    if (state.compareMode === "custom" && comparison?.from && comparison?.to) {
      qp.set("compare_from", comparison.from);
      qp.set("compare_to", comparison.to);
    }
    if (row.key === "payroll") {
      if (summary?.period_start) qp.set("date_from", summary.period_start);
      if (summary?.period_end) qp.set("date_to", summary.period_end);
      return `/owner-payroll.html?${qp.toString()}`;
    }
    const categoryMatch = /^expense:(\d+)$/.exec(String(row.key || ""));
    if (!categoryMatch) return "";
    qp.set("category_id", categoryMatch[1]);
    qp.set("month", String(summary?.period_start || state.month || currentMonth()).slice(0, 7));
    return `/owner-expenses.html?${qp.toString()}`;
  };
  container.innerHTML = rows.map((row) => {
    const sharePercent = Math.max(0, Math.min(100, row.shareBps / 100));
    const fillWidth = row.amountMinor > 0 ? Math.max(1.5, sharePercent) : 0;
    const rowClass = row.key === "payroll" ? " summary-cost-row--payroll" : "";
    const drilldown = buildDrilldown(row);
    const tag = drilldown ? "a" : "div";
    const href = drilldown ? ` href="${escapeHtml(drilldown)}" aria-label="Открыть детализацию: ${escapeHtml(row.title)}"` : "";
    return `<${tag} class="summary-cost-row${rowClass}"${href}>
      <div class="summary-cost-head">
        <span class="summary-cost-label">${escapeHtml(row.title)}</span>
        <span class="summary-cost-value">${escapeHtml(fmtMoneyMinor(row.amountMinor))} · ${escapeHtml(fmtPercentBps(row.shareBps))}</span>
      </div>
      <svg class="summary-cost-svg" viewBox="0 0 100 9" preserveAspectRatio="none" aria-hidden="true">
        <rect class="summary-cost-track" x="0" y="0" width="100" height="9" rx="4.5"></rect>
        <rect class="summary-cost-fill" x="0" y="0" width="${fillWidth.toFixed(2)}" height="9" rx="4.5"></rect>
      </svg>
    </${tag}>`;
  }).join("");
}

function renderSummaryAnalytics(summary, comparisonSummary = null) {
  state.summaryData = summary || null;
  state.comparisonSummaryData = comparisonSummary || null;
  syncAnalyticsAccess();
  if (financeAccess.canViewRevenue || financeAccess.canViewExpenses || financeAccess.canViewPayroll) {
    renderSummaryTrend(summary, comparisonSummary);
  }
  if (financeAccess.canViewExpenses || financeAccess.canViewPayroll) renderSummaryCostStructure(summary);
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

async function loadFinanceSummaryForQuery(venueId, query, timeoutLabel) {
  const qs = query.toString();
  return startupApi(`/venues/${encodeURIComponent(venueId)}/finance/summary?${qs}`, 10000, timeoutLabel);
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
  canViewLedger: false,
  canViewProfit: false,
  canCalculatePayroll: false,
};

async function loadFinanceAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return financeAccess;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    financialValuesHidden = isFinancialValuesHidden(permsResp);
    const role = roleUpper(permsResp);
    const systemRole = String(permsResp?.system_role || "").trim().toUpperCase();
    const pset = permSetFromResponse(permsResp);
    const isOwner = isOwnerRole(role);
    const hasFullSummary = isOwner
      || ["SUPER_ADMIN", "MODERATOR"].includes(systemRole)
      || hasPerm(pset, "REPORTS_VIEW_PNL")
      || hasPerm(pset, "MONTHLY_SUMMARY_VIEW");
    const canViewRevenueValue = hasFullSummary || canViewRevenue(pset, role, systemRole);
    const canViewExpensesValue = hasFullSummary || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD");
    const canViewPayrollValue = hasFullSummary || hasPerm(pset, "PAYROLL_VIEW") || hasPerm(pset, "PAYROLL_CALCULATE");
    const canViewLedgerValue = hasFinanceLedgerViewAccess(pset, role, systemRole);
    financeAccess = {
      canViewRevenue: canViewRevenueValue,
      canViewExpenses: canViewExpensesValue,
      canViewPayroll: canViewPayrollValue,
      canViewLedger: canViewLedgerValue,
      canViewProfit: canViewRevenueValue && canViewExpensesValue && canViewPayrollValue,
      canCalculatePayroll: hasFullSummary || hasPerm(pset, "PAYROLL_CALCULATE"),
    };
  } catch {
    financeAccess = { canViewRevenue: false, canViewExpenses: false, canViewPayroll: false, canViewLedger: false, canViewProfit: false, canCalculatePayroll: false };
  }
  return financeAccess;
}

function applyServerFinanceAccess(summary) {
  if (!summary || typeof summary !== "object") return;
  if (typeof summary.can_view_revenue === "boolean") {
    financeAccess.canViewRevenue = financeAccess.canViewRevenue && summary.can_view_revenue;
  }
  if (typeof summary.can_view_expenses === "boolean") {
    financeAccess.canViewExpenses = financeAccess.canViewExpenses && summary.can_view_expenses;
  }
  if (typeof summary.can_view_payroll === "boolean") {
    financeAccess.canViewPayroll = financeAccess.canViewPayroll && summary.can_view_payroll;
  }
  financeAccess.canViewProfit = financeAccess.canViewRevenue
    && financeAccess.canViewExpenses
    && financeAccess.canViewPayroll
    && summary.can_view_profit !== false;
}

function syncActions() {
  const venueId = getActiveVenueId();
  const exportSummaryBtn = document.getElementById("exportSummaryBtn");
  const revenueBtn = document.getElementById("openRevenueBtn");
  const expensesBtn = document.getElementById("openExpensesBtn");
  const payrollBtn = document.getElementById("openPayrollBtn");
  const ledgerBtn = document.getElementById("openLedgerBtn");
  const economicsBtn = document.getElementById("openEconomicsBtn");
  const selectedMonth = state.period === "month"
    ? state.month
    : (state.period === "day" ? state.day : state.to || state.from || todayISO()).slice(0, 7);

  if (exportSummaryBtn) {
    setVisible(exportSummaryBtn, financeAccess.canViewRevenue);
    exportSummaryBtn.onclick = async () => {
      try {
        await openExportLink(`/venues/${encodeURIComponent(venueId)}/summary/monthly/export-link?${buildSummaryQuery().toString()}`);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось начать экспорт", "err");
      }
    };
  }

  if (revenueBtn) {
    setVisible(revenueBtn, financeAccess.canViewRevenue);
    revenueBtn.onclick = () => {
      const qp = buildSummaryQuery();
      qp.set("venue_id", String(venueId));
      qp.set("mode", "PAYMENTS");
      location.href = `/owner-turnover.html?${qp.toString()}`;
    };
  }

  if (expensesBtn) {
    setVisible(expensesBtn, financeAccess.canViewExpenses);
    expensesBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("month", selectedMonth || currentMonth());
      location.href = `/owner-expenses.html?${qp.toString()}`;
    };
  }

  if (payrollBtn) {
    setVisible(payrollBtn, financeAccess.canViewPayroll);
    payrollBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      qp.set("month", selectedMonth || currentMonth());
      location.href = `/owner-payroll.html?${qp.toString()}`;
    };
  }

  if (ledgerBtn) {
    setVisible(ledgerBtn, financeAccess.canViewLedger);
    const qp = new URLSearchParams();
    qp.set("venue_id", String(venueId));
    qp.set("month", selectedMonth || currentMonth());
    ledgerBtn.href = `/owner-finance-ledger.html?${qp.toString()}`;
  }

  if (economicsBtn) {
    setVisible(economicsBtn, financeAccess.canViewRevenue);
    economicsBtn.onclick = () => {
      const qp = new URLSearchParams();
      qp.set("venue_id", String(venueId));
      const selectedDate = state.period === "month"
        ? `${state.month || currentMonth()}-01`
        : state.period === "day"
          ? state.day || todayISO()
          : state.to || state.from || todayISO();
      qp.set("date", selectedDate);
      location.href = `/owner-day-economics.html?${qp.toString()}`;
    };
  }
}

async function loadSummary() {
  const venueId = getActiveVenueId();
  if (!venueId) {
    setSummaryState("Заведение не выбрано", "Вернитесь к списку заведений и выберите нужное заведение.");
    ["summaryPrimaryKpis", "summaryAnalyticsGrid", "summarySecondaryKpis", "summaryRatioKpis", "summaryDetailsCard"].forEach((id) => showBlock(id, false));
    return;
  }

  normalizeRange();
  syncPickers();
  syncComparisonControls();
  syncUrl();
  await loadFinanceAccess();
  renderDemoOwnerIntro();
  syncActions();
  syncAnalyticsAccess();
  setSummaryState();
  ["summaryPrimaryKpis", "summarySecondaryKpis", "summaryRatioKpis", "summaryDetailsCard"].forEach((id) => showBlock(id, true));
  syncSummaryMetricAccess();

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
    setSummaryState("Финансовая сводка недоступна", "Для этой страницы не выданы права на выручку, расходы или начисления.");
    ["summaryPrimaryKpis", "summaryAnalyticsGrid", "summarySecondaryKpis", "summaryRatioKpis", "summaryDetailsCard"].forEach((id) => showBlock(id, false));
    return;
  }

  try {
    const primaryQuery = buildSummaryQuery();
    primaryQuery.set("include_series", "1");
    const primaryPromise = loadFinanceSummaryForQuery(venueId, primaryQuery, "OWNER_SUMMARY_TIMEOUT");
    const comparison = currentComparison();
    const comparisonPromise = comparison
      ? (() => {
          const comparisonQuery = buildComparisonQuery();
          comparisonQuery.set("include_series", "1");
          return loadFinanceSummaryForQuery(venueId, comparisonQuery, "OWNER_SUMMARY_COMPARISON_TIMEOUT");
        })()
      : Promise.resolve(null);
    const [summary, comparisonResult] = await Promise.all([
      primaryPromise,
      comparisonPromise.then((value) => ({ value })).catch((error) => ({ error })),
    ]);
    applyServerFinanceAccess(summary);
    syncAnalyticsAccess();
    syncSummaryMetricAccess();
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
    renderSummaryAnalytics(summary, comparisonResult.value || null);
    if (comparisonResult.value) {
      renderComparison(summary, comparisonResult.value);
    } else {
      resetComparisonDeltas(state.compareMode === "none" ? "Без сравнения" : "Сравнение недоступно");
      if (state.compareMode !== "none") setText("summaryCompareHint", comparisonResult.error?.data?.detail || comparisonResult.error?.message || "Не удалось загрузить период сравнения");
    }
    setSummaryState();
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
    resetComparisonDeltas();
    setSummaryState("Не удалось загрузить финансовую сводку", e?.data?.detail || e.message || "Попробуйте повторить загрузку позже.");
    ["summaryPrimaryKpis", "summaryAnalyticsGrid", "summarySecondaryKpis", "summaryRatioKpis"].forEach((id) => showBlock(id, false));
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
  if (!["month", "day", "range"].includes(state.period)) state.period = "month";
  state.month = coerceDemoMonth((params.get("month") || currentMonth()).slice(0, 7), { notify: false, context: "owner-summary" });
  state.day = params.get("day") || params.get("date_from") || todayISO();
  const demoRange = coerceDemoRange(params.get("date_from") || todayISO(), params.get("date_to") || (params.get("date_from") || todayISO()), { notify: false, context: "owner-summary" });
  state.from = demoRange.from || params.get("date_from") || todayISO();
  state.to = demoRange.to || params.get("date_to") || state.from;
  state.compareMode = ["auto", "custom", "none"].includes(params.get("compare_mode")) ? params.get("compare_mode") : "auto";
  state.compareFrom = params.get("compare_from") || "";
  state.compareTo = params.get("compare_to") || "";
  if (isDemoUiMode()) state.period = "month";
  normalizeRange();

  const monthPick = document.getElementById("summaryMonthPick");
  const dayPick = document.getElementById("summaryDayPick");
  const fromPick = document.getElementById("summaryFromPick");
  const toPick = document.getElementById("summaryToPick");
  const rangeApplyBtn = document.getElementById("summaryRangeApplyBtn");

  if (monthPick) {
    monthPick.value = state.month;
    monthPick.onchange = (e) => {
      state.month = coerceDemoMonth((e.target.value || currentMonth()).slice(0, 7), { context: "owner-summary" });
      state.period = "month";
      setActiveSeg("summaryPeriodSeg", "period", "month");
      loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
    };
  }
  if (dayPick) {
    dayPick.value = state.day;
    dayPick.onchange = (e) => {
      state.day = e.target.value || todayISO();
      state.period = "day";
      setActiveSeg("summaryPeriodSeg", "period", "day");
      loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
    };
  }
  if (fromPick) {
    fromPick.value = state.from;
    fromPick.onchange = (e) => {
      state.from = coerceDemoRange(e.target.value || todayISO(), state.to || e.target.value || todayISO(), { context: "owner-summary" }).from;
    };
  }
  if (toPick) {
    toPick.value = state.to;
    toPick.onchange = (e) => {
      state.to = coerceDemoRange(state.from || todayISO(), e.target.value || state.from || todayISO(), { context: "owner-summary" }).to;
    };
  }
  if (rangeApplyBtn) {
    rangeApplyBtn.onclick = () => {
      if (isDemoUiMode()) {
        const demoRange = coerceDemoRange(state.from, state.to, { context: "owner-summary" });
        state.from = demoRange.from;
        state.to = demoRange.to;
        state.period = "month";
        setActiveSeg("summaryPeriodSeg", "period", "month");
      } else {
        state.period = "range";
        setActiveSeg("summaryPeriodSeg", "period", "range");
      }
      loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
    };
  }

  document.querySelectorAll(`#summaryPeriodSeg button`).forEach((btn) => {
    btn.onclick = () => {
      const nextPeriod = btn.dataset.period || "month";
      state.period = (isDemoUiMode() && nextPeriod !== "month") ? "month" : nextPeriod;
      setActiveSeg("summaryPeriodSeg", "period", nextPeriod);
      if (nextPeriod === "month" || nextPeriod === "day") {
        loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
      } else {
        syncPickers();
        syncComparisonControls();
        syncUrl();
      }
    };
  });

  document.querySelectorAll(`#summaryCompareSeg button`).forEach((btn) => {
    btn.onclick = () => {
      const requestedMode = btn.dataset.compare;
      const nextMode = ["auto", "custom", "none"].includes(requestedMode) ? requestedMode : "auto";
      if (nextMode === "custom" && state.compareMode !== "custom") {
        const automatic = resolveAutoComparison(state);
        state.compareFrom = automatic?.from || state.day || todayISO();
        state.compareTo = automatic?.to || state.compareFrom;
      }
      state.compareMode = nextMode;
      syncComparisonControls();
      if (nextMode !== "custom") {
        loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
      } else {
        syncUrl();
      }
    };
  });

  const compareFromPick = document.getElementById("summaryCompareFromPick");
  const compareToPick = document.getElementById("summaryCompareToPick");
  if (compareFromPick) {
    compareFromPick.onchange = (event) => {
      state.compareFrom = event.target.value || state.compareFrom;
    };
  }
  if (compareToPick) {
    compareToPick.onchange = (event) => {
      state.compareTo = event.target.value || state.compareTo;
    };
  }
  document.getElementById("summaryCompareApplyBtn")?.addEventListener("click", () => {
    normalizeCompareRange();
    loadSummary().catch((err) => toast(err?.message || "Ошибка загрузки", "err"));
  });

  if (isDemoUiMode()) {
    setVisible(document.querySelector(`#summaryPeriodSeg button[data-period="day"]`), false);
    setVisible(document.querySelector(`#summaryPeriodSeg button[data-period="range"]`), false);
    showBlock("summaryDayPick", false);
    showBlock("summaryRangePick", false);
  }
  setActiveSeg("summaryPeriodSeg", "period", state.period);
  syncPickers();
  syncComparisonControls();
  await loadSummary();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });


function mountDemoFlowTour() {
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) return;
  const venue = getActiveVenueId();
  const q = venue ? `?venue_id=${encodeURIComponent(String(venue))}` : "";
  mountDemoPageTour({
    tourId: "demo-owner-flow",
    step: 1,
    total: 4,
    title: "Быстрый тур для владельца",
    text: "Пройди по главным экранам: сводка → расходы → начисления → карточка заведения.",
    nextPath: `/owner-expenses.html${q}`,
    finishPath: `/owner-summary.html${q}`,
  });
}

try { mountDemoFlowTour(); } catch {}

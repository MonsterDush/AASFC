// Canonical revenue page for owners. Legacy route: /owner-revenue.html -> redirect.
import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  api,
  API_BASE,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  getStoredDemoUiState,
  isDemoUiMode,
  getDemoMonthLabel,
} from "/app.js?v=20260820-i18nmetrika1";
import { permSetFromResponse, roleUpper, hasPerm, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js";
import {
  formatComparisonRange,
  normalizeIsoRange,
  resolveAutoComparison,
  resolveComparisonRange,
} from "/app/period-comparison.js?v=20260802-financeux2";
import { buildFinancePeriodComparisonGeometry } from "/app/finance-summary-analytics.js?v=20260802-summarycompare1";
import { buildRevenueStructure, normalizeRevenueDailySeries } from "/app/revenue-analytics.js?v=20260802-revenueanalytics1";

let financialValuesHidden = false;


const DEMO_OWNER_REVENUE_INTRO_DISMISSED_KEY = "axelio.demo_intro.owner_revenue.dismissed";

function setupDemoRevenueIntro() {
  const intro = $("demoOwnerRevenueIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) { intro.classList.add("hidden"); return; }
  try {
    if (sessionStorage.getItem(DEMO_OWNER_REVENUE_INTRO_DISMISSED_KEY) === "1") {
      intro.classList.add("hidden");
      return;
    }
  } catch {}
  const textEl = $("demoOwnerRevenueIntroText");
  if (textEl) textEl.textContent = `Здесь удобно оценить структуру выручки за ${getDemoMonthLabel(demoState) || 'DEMO-месяц'}: сначала департаменты, затем оплаты и переход к финансовым движениям.`;
  const venueId = getActiveVenueId();
  $("demoOwnerRevenueGoSummary")?.addEventListener("click", () => { if (venueId) location.href = `/owner-summary.html?venue_id=${encodeURIComponent(String(venueId))}`; });
  $("demoOwnerRevenueGoLedger")?.addEventListener("click", () => { if (venueId) location.href = `/owner-finance-ledger.html?venue_id=${encodeURIComponent(String(venueId))}&month=${encodeURIComponent(state.month || currentMonth())}`; });
  $("demoOwnerRevenueGoEconomics")?.addEventListener("click", () => { if (venueId) location.href = `/owner-day-economics.html?venue_id=${encodeURIComponent(String(venueId))}`; });
  $("demoOwnerRevenueIntroClose")?.addEventListener("click", () => {
    intro.classList.add("hidden");
    try { sessionStorage.setItem(DEMO_OWNER_REVENUE_INTRO_DISMISSED_KEY, "1"); } catch {}
  });
  intro.classList.remove("hidden");
}

let state = {
  period: "month",
  mode: "DEPARTMENTS",
  month: null,
  day: null,
  from: null,
  to: null,
  canView: true,
  canExport: true,
  compareMode: "auto",
  compareFrom: null,
  compareTo: null,
};

function $(id) { return document.getElementById(id); }

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setVisible(element, visible) {
  element?.classList.toggle("hidden", !visible);
}

function fmtMoney(n) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  const x = Math.round(Number(n || 0));
  try { return new Intl.NumberFormat((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU")).format(x) + " ₽"; } catch { return String(x) + " ₽"; }
}

function fmtMoneyMinor(minor) {
  return fmtMoney(Number(minor || 0) / 100);
}

function fmtCompactMoneyMinor(minor) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  const value = Number(minor || 0) / 100;
  const absolute = Math.abs(value);
  if (absolute >= 1_000_000) return `${(value / 1_000_000).toLocaleString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { maximumFractionDigits: 1 })} млн`;
  if (absolute >= 1_000) return `${(value / 1_000).toLocaleString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { maximumFractionDigits: 0 })} тыс.`;
  return fmtMoney(value);
}

function fmtPercentBps(bps) {
  return `${(Number(bps || 0) / 100).toLocaleString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { maximumFractionDigits: 1 })}%`;
}

function fmtShortDate(iso) {
  const parts = String(iso || "").split("-");
  return parts.length === 3 ? `${parts[2]}.${parts[1]}` : String(iso || "—");
}

function fmtLongDate(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(iso || ""))) return String(iso || "—");
  try {
    return new Date(`${iso}T00:00:00`).toLocaleDateString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { day: "numeric", month: "long", year: "numeric" });
  } catch {
    return String(iso);
  }
}

function fmtSignedMoney(value) {
  const amount = Number(value || 0);
  const sign = amount > 0 ? "+" : amount < 0 ? "−" : "";
  return `${sign}${fmtMoney(Math.abs(amount))}`;
}

function relativeDelta(currentValue, previousValue, { goodWhen = "up" } = {}) {
  const current = Number(currentValue || 0);
  const previous = Number(previousValue || 0);
  const delta = current - previous;
  const good = (goodWhen === "up" && delta > 0) || (goodWhen === "down" && delta < 0);
  const bad = (goodWhen === "up" && delta < 0) || (goodWhen === "down" && delta > 0);
  const tone = good ? "is-good" : bad ? "is-bad" : "is-neutral";
  if (previous === 0) {
    return {
      text: current === 0 ? "Без изменений" : `Нет базы · ${fmtSignedMoney(delta)}`,
      tone,
    };
  }
  const percent = delta / Math.abs(previous) * 100;
  const sign = percent > 0 ? "+" : percent < 0 ? "−" : "";
  return {
    text: `${sign}${Math.abs(percent).toLocaleString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { maximumFractionDigits: 1 })}% · ${fmtSignedMoney(delta)}`,
    tone,
  };
}

function startOfWeekISO(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const day = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - day);
  return d.toISOString().slice(0, 10);
}

function addDaysISO(dateStr, days) {
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function normalizeRange() {
  if (!state.from) state.from = todayISO();
  if (!state.to) state.to = state.from;
  if (state.from > state.to) {
    const x = state.from;
    state.from = state.to;
    state.to = x;
  }
}

function syncPickers() {
  const monthPick = $("monthPick");
  const dayPick = $("dayPick");
  const rangePick = $("rangePick");

  setVisible(monthPick, state.period === "month");
  setVisible(dayPick, state.period === "day" || state.period === "week");
  setVisible(rangePick, state.period === "range");
}

function currentComparison() {
  return resolveComparisonRange({
    compareMode: state.compareMode,
    compareFrom: state.compareFrom,
    compareTo: state.compareTo,
    period: state.period,
    month: state.month,
    day: state.day,
    from: state.from,
    to: state.to,
  });
}

function syncComparisonControls() {
  const comparison = currentComparison();
  const custom = state.compareMode === "custom";
  const disabled = state.compareMode === "none";
  setVisible($("revenueCompareRange"), custom);
  setActiveSeg("revenueCompareSeg", "compare", state.compareMode);
  $("revenueComparePeriodText").textContent = disabled ? "Сравнение отключено" : formatComparisonRange(comparison);
  $("revenueCompareHint").textContent = disabled ? "Дополнительный период не загружается." : (comparison?.caption || "Выбери период сравнения");
  if (custom) {
    $("revenueCompareFrom").value = comparison?.from || state.compareFrom || "";
    $("revenueCompareTo").value = comparison?.to || state.compareTo || "";
  }
}

function periodLabel() {
  if (state.period === "month") return `За ${state.month || currentMonth()}`;
  if (state.period === "day") return `За ${state.day || todayISO()}`;
  if (state.period === "week") {
    const start = startOfWeekISO(state.day || todayISO());
    return `Неделя ${start} — ${addDaysISO(start, 6)}`;
  }
  normalizeRange();
  return `Период ${state.from} — ${state.to}`;
}

function syncCaption() {
  const el = $("periodCaption");
  if (el) el.textContent = periodLabel();
}

function buildQuery() {
  const qp = new URLSearchParams();
  qp.set("mode", state.mode);
  qp.set("period", state.period);

  if (state.period === "month") {
    qp.set("month", state.month || currentMonth());
  } else if (state.period === "day") {
    qp.set("day", state.day || todayISO());
    qp.set("date_from", state.day || todayISO());
    qp.set("date_to", state.day || todayISO());
  } else if (state.period === "week") {
    const baseDay = state.day || todayISO();
    const monday = startOfWeekISO(baseDay);
    qp.set("day", baseDay);
    qp.set("date_from", monday);
    qp.set("date_to", addDaysISO(monday, 6));
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
  qp.set("mode", state.mode);
  qp.set("period", "range");
  qp.set("date_from", comparison?.from || todayISO());
  qp.set("date_to", comparison?.to || comparison?.from || todayISO());
  return qp;
}

function syncUrl() {
  const qp = buildQuery();
  qp.set("compare_mode", state.compareMode);
  if (state.compareMode === "custom") {
    const comparison = currentComparison();
    if (comparison?.from) qp.set("compare_from", comparison.from);
    if (comparison?.to) qp.set("compare_to", comparison.to);
  }
  const venueId = getActiveVenueId();
  if (venueId) qp.set("venue_id", venueId);
  const ledgerLink = $("openLedgerBtn");
  if (ledgerLink && venueId) {
    const ledgerQuery = new URLSearchParams();
    ledgerQuery.set("venue_id", String(venueId));
    const selectedMonth = state.period === "month"
      ? state.month
      : (state.period === "range" ? state.to || state.from : state.day || todayISO()).slice(0, 7);
    ledgerQuery.set("month", selectedMonth || currentMonth());
    ledgerLink.href = `/owner-finance-ledger.html?${ledgerQuery.toString()}`;
  }
  const target = `${location.pathname}?${qp.toString()}`;
  history.replaceState(null, "", target);
}

function renderRevenueTrendFocus(currentPoint, comparisonPoint) {
  const focus = $("revenueTrendFocus");
  if (!focus) return;
  if (financialValuesHidden) {
    focus.textContent = FINANCIAL_VALUES_HIDDEN_LABEL;
    return;
  }
  if (!currentPoint && !comparisonPoint) {
    focus.textContent = "Выбери день на графике";
    return;
  }
  const parts = [];
  if (currentPoint) parts.push(`<span>Текущий: <b>${esc(fmtLongDate(currentPoint.date))}</b> · ${esc(fmtMoneyMinor(currentPoint.revenueMinor))}</span>`);
  if (comparisonPoint) parts.push(`<span>Сравнение: <b>${esc(fmtLongDate(comparisonPoint.date))}</b> · ${esc(fmtMoneyMinor(comparisonPoint.revenueMinor))}</span>`);
  focus.innerHTML = parts.join(" · ");
}

function renderRevenueTrend(summary, comparisonSummary, error = null) {
  const chart = $("revenueTrendChart");
  const subtitle = $("revenueTrendSubtitle");
  const legend = $("revenueTrendLegend");
  if (!chart || !subtitle || !legend) return;
  const points = normalizeRevenueDailySeries(summary?.daily_series);
  const comparisonPoints = normalizeRevenueDailySeries(comparisonSummary?.daily_series);
  const periodText = summary?.period_start && summary?.period_end
    ? `${summary.period_start} — ${summary.period_end}`
    : periodLabel();
  const comparisonText = comparisonSummary?.period_start && comparisonSummary?.period_end
    ? `${comparisonSummary.period_start} — ${comparisonSummary.period_end}`
    : "";
  subtitle.textContent = comparisonPoints.length
    ? `${periodText} против ${comparisonText} · сопоставление по порядковому дню, ₽`
    : `${periodText} · по дням, ₽`;
  legend.innerHTML = [
    '<span><i class="revenue-trend-swatch" aria-hidden="true"></i>Текущий период</span>',
    ...(comparisonPoints.length ? ['<span><i class="revenue-trend-swatch revenue-trend-swatch--comparison" aria-hidden="true"></i>Сравниваемый период</span>'] : []),
  ].join("");
  if (financialValuesHidden) {
    chart.innerHTML = `<div class="finance-chart-empty">${esc(FINANCIAL_VALUES_HIDDEN_LABEL)}</div>`;
    renderRevenueTrendFocus(null, null);
    return;
  }
  if (!summary) {
    chart.innerHTML = `<div class="finance-chart-empty">${esc(error?.data?.detail || error?.message || "Динамика временно недоступна")}</div>`;
    renderRevenueTrendFocus(null, null);
    return;
  }
  const geometry = buildFinancePeriodComparisonGeometry(points, comparisonPoints, { metric: "revenue", width: 720, height: 200 });
  if (!geometry || geometry.pointCount < 2) {
    chart.innerHTML = `<div class="finance-chart-empty">${geometry?.pointCount
      ? "Для одного дня график не строится — точные значения показаны ниже."
      : "За выбранный период нет дневных данных для графика."}</div>`;
    renderRevenueTrendFocus(points[0] || null, comparisonPoints[0] || null);
    return;
  }
  const gridLines = [0, 50, 100, 150, 200]
    .map((y) => `<line class="revenue-trend-gridline" x1="0" y1="${y}" x2="720" y2="${y}"></line>`)
    .join("");
  let marks = "";
  if (geometry.mode === "lines") {
    marks += `<path class="revenue-trend-line revenue-trend-line--current" d="${geometry.currentPath}"></path>`;
    if (geometry.comparisonPath) marks += `<path class="revenue-trend-line revenue-trend-line--comparison" d="${geometry.comparisonPath}"></path>`;
    if (geometry.pointCount <= 45) {
      marks += geometry.current.filter(Boolean).map((point) => `<circle class="revenue-trend-marker revenue-trend-marker--current" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="3"></circle>`).join("");
      marks += geometry.comparison.filter(Boolean).map((point) => `<circle class="revenue-trend-marker revenue-trend-marker--comparison" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="3"></circle>`).join("");
    }
  } else {
    const hasComparison = comparisonPoints.length > 0;
    const barWidth = Math.max(5, Math.min(28, geometry.bandWidth * (hasComparison ? 0.28 : 0.48)));
    marks += Array.from({ length: geometry.pointCount }, (_, index) => {
      const currentPoint = geometry.current[index];
      const comparisonPoint = geometry.comparison[index];
      const centerX = (index + 0.5) * geometry.bandWidth;
      const currentX = hasComparison ? centerX - barWidth - 2 : centerX - barWidth / 2;
      return [
        currentPoint ? `<rect class="revenue-trend-bar revenue-trend-bar--current" x="${currentX.toFixed(2)}" y="${currentPoint.barY.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${currentPoint.barHeight.toFixed(2)}" rx="2"></rect>` : "",
        comparisonPoint ? `<rect class="revenue-trend-bar revenue-trend-bar--comparison" x="${(centerX + 2).toFixed(2)}" y="${comparisonPoint.barY.toFixed(2)}" width="${barWidth.toFixed(2)}" height="${comparisonPoint.barHeight.toFixed(2)}" rx="2"></rect>` : "",
      ].join("");
    }).join("");
  }
  const hitTargets = Array.from({ length: geometry.pointCount }, (_, index) => (
    `<g class="revenue-trend-hit-group" data-revenue-point="${index}" role="button" tabindex="0" aria-label="Порядковый день ${index + 1}">`
      + `<rect class="revenue-trend-hit" x="${(index * geometry.bandWidth).toFixed(2)}" y="0" width="${geometry.bandWidth.toFixed(2)}" height="200"></rect>`
      + "</g>"
  )).join("");
  const tickCount = Math.min(7, geometry.pointCount);
  const tickIndexes = [...new Set(Array.from({ length: tickCount }, (_, index) => (
    Math.round((index * (geometry.pointCount - 1)) / Math.max(1, tickCount - 1))
  )))];
  const ticks = tickIndexes.map((index) => {
    const point = points[index] || comparisonPoints[index];
    return `<span>${esc(comparisonPoints.length ? String(index + 1) : fmtShortDate(point?.date))}</span>`;
  }).join("");
  chart.innerHTML = `
    <div class="revenue-trend-scale" aria-hidden="true">
      <span>${esc(fmtCompactMoneyMinor(geometry.maxValue))}</span>
      <span>${esc(fmtCompactMoneyMinor(geometry.minValue))}</span>
    </div>
    <div class="revenue-trend-visual">
      <svg class="revenue-trend-svg" viewBox="0 0 720 200" preserveAspectRatio="none" role="img" aria-label="Выручка по дням текущего и сравниваемого периода">
        ${gridLines}${marks}${hitTargets}
      </svg>
      <div class="revenue-trend-ticks" aria-hidden="true">${ticks}</div>
    </div>`;
  let defaultIndex = geometry.pointCount - 1;
  for (let index = geometry.pointCount - 1; index >= 0; index -= 1) {
    if (geometry.current[index] || geometry.comparison[index]) {
      defaultIndex = index;
      break;
    }
  }
  const activatePoint = (index) => {
    chart.querySelectorAll("[data-revenue-point]").forEach((target) => {
      const active = Number(target.dataset.revenuePoint) === index;
      target.classList.toggle("is-active", active);
      target.setAttribute("aria-pressed", active ? "true" : "false");
    });
    renderRevenueTrendFocus(points[index] || null, comparisonPoints[index] || null);
  };
  chart.querySelectorAll("[data-revenue-point]").forEach((target) => {
    const index = Number(target.dataset.revenuePoint);
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

function renderRevenueStructure(data, comparisonData) {
  const rowsEl = $("rows");
  if (!rowsEl) return;
  const structure = buildRevenueStructure(data?.rows, data?.total);
  const modeTitle = state.mode === "PAYMENTS" ? "типам оплат" : "департаментам";
  $("revenueRowsTitle").textContent = `Структура по ${modeTitle}`;
  $("revenueRowsSubtitle").textContent = `${Number(data?.closed_reports || 0)} закрытых отчётов · доля, сумма и изменение относительно периода сравнения.`;
  if (!structure.length) {
    rowsEl.innerHTML = '<div class="finance-table-empty">Нет данных за выбранный период</div>';
    return;
  }
  const comparisonRows = new Map(
    (Array.isArray(comparisonData?.rows) ? comparisonData.rows : []).map((row) => [
      String(row?.ref_id ?? row?.id ?? row?.code ?? row?.title ?? row?.name ?? ""),
      row,
    ]),
  );
  rowsEl.innerHTML = structure.map((entry) => {
    const comparisonRow = comparisonRows.get(entry.key);
    const rowDelta = comparisonRow && !financialValuesHidden
      ? relativeDelta(entry.amount, comparisonRow?.amount, { goodWhen: "up" })
      : null;
    return `<article class="revenue-structure-row" aria-label="${esc(entry.title)}: ${esc(fmtMoney(entry.amount))}, ${esc(fmtPercentBps(entry.shareBps))} выручки">
      <div class="revenue-structure-head">
        <div>
          <div class="revenue-structure-title">${esc(entry.title)}</div>
          <div class="revenue-structure-share">${esc(fmtPercentBps(entry.shareBps))} общей выручки</div>
        </div>
        <div class="revenue-structure-value">
          <b>${esc(fmtMoney(entry.amount))}</b>
          ${rowDelta ? `<span class="finance-row-delta ${rowDelta.tone}">${esc(rowDelta.text)}</span>` : ""}
        </div>
      </div>
      <svg class="revenue-structure-bar" viewBox="0 0 100 9" preserveAspectRatio="none" aria-hidden="true">
        <rect class="revenue-structure-track" x="0" y="0" width="100" height="9" rx="4.5"></rect>
        <rect class="revenue-structure-fill" x="0" y="0" width="${entry.relativeWidthPercent.toFixed(2)}" height="9" rx="4.5"></rect>
      </svg>
    </article>`;
  }).join("");
}

async function load() {
  const venueId = getActiveVenueId();
  if (!venueId || !state.canView) return;

  normalizeRange();
  syncCaption();
  syncComparisonControls();
  syncUrl();

  const primaryQuery = buildQuery();
  primaryQuery.set("include_series", "1");
  const primaryPromise = api(`/venues/${encodeURIComponent(venueId)}/revenue?${primaryQuery.toString()}`);
  const comparisonPromise = state.compareMode === "none"
    ? Promise.resolve({ value: null })
    : (() => {
        const comparisonQuery = buildComparisonQuery();
        comparisonQuery.set("include_series", "1");
        return api(`/venues/${encodeURIComponent(venueId)}/revenue?${comparisonQuery.toString()}`)
          .then((value) => ({ value }))
          .catch((error) => ({ error }));
      })();
  const [data, comparisonResult] = await Promise.all([
    primaryPromise,
    comparisonPromise,
  ]);
  const comparisonData = comparisonResult.value || null;

  $("total").textContent = fmtMoney(data?.total || 0);
  const totalDelta = $("revenueTotalDelta");
  totalDelta.classList.remove("is-good", "is-bad", "is-neutral");
  if (comparisonData && !financialValuesHidden) {
    const view = relativeDelta(data?.total, comparisonData?.total, { goodWhen: "up" });
    totalDelta.textContent = `${view.text} ${currentComparison()?.caption || ""}`.trim();
    totalDelta.classList.add(view.tone);
  } else {
    totalDelta.textContent = comparisonResult.error ? "Сравнение недоступно" : "—";
    totalDelta.classList.add("is-neutral");
  }
  renderRevenueTrend(data, comparisonData, comparisonResult.error);
  renderRevenueStructure(data, comparisonData);
}

function setActiveSeg(containerId, dataKey, value) {
  document.querySelectorAll(`#${containerId} button`).forEach((b) => {
    if (b.dataset[dataKey] === value) b.classList.add("active");
    else b.classList.remove("active");
  });
}

function applySeg(containerId, key) {
  document.querySelectorAll(`#${containerId} button`).forEach((btn) => {
    btn.onclick = () => {
      const val = btn.dataset[key];
      if (!val) return;
      state[key] = val;
      setActiveSeg(containerId, key, val);
      syncPickers();
      load().catch((e) => toast("Ошибка: " + (e?.message || e), "err"));
    };
  });
}

function initFromQuery() {
  const q = new URLSearchParams(location.search);
  const nowMonth = currentMonth();
  const today = todayISO();

  state.mode = q.get("mode") || "DEPARTMENTS";
  state.period = q.get("period") || (q.get("month") ? "month" : (q.get("date_from") && q.get("date_to") ? "range" : "month"));

  state.month = (q.get("month") || nowMonth).slice(0,7);
  state.day = q.get("day") || q.get("date_from") || today;
  state.from = q.get("date_from") || today;
  state.to = q.get("date_to") || today;
  state.compareMode = ["auto", "custom", "none"].includes(q.get("compare_mode")) ? q.get("compare_mode") : "auto";
  state.compareFrom = q.get("compare_from") || null;
  state.compareTo = q.get("compare_to") || null;
  normalizeRange();

  $("monthPick").value = state.month || currentMonth();
  $("dayPick").value = state.day;
  $("fromPick").value = state.from;
  $("toPick").value = state.to;

  setActiveSeg("modeSeg", "mode", state.mode);
  setActiveSeg("periodSeg", "period", state.period);
  syncCaption();
  syncComparisonControls();
}

function bindPickers() {
  $("monthPick").onchange = (e) => { state.month = e.target.value || currentMonth(); load().catch(console.error); };
  $("dayPick").onchange = (e) => { state.day = e.target.value || todayISO(); load().catch(console.error); };
  $("fromPick").onchange = (e) => { state.from = e.target.value || todayISO(); load().catch(console.error); };
  $("toPick").onchange = (e) => { state.to = e.target.value || todayISO(); load().catch(console.error); };

  document.querySelectorAll("#revenueCompareSeg button").forEach((button) => {
    button.onclick = () => {
      const requestedMode = button.dataset.compare;
      const mode = ["auto", "custom", "none"].includes(requestedMode) ? requestedMode : "auto";
      if (mode === "custom" && state.compareMode !== "custom") {
        const automatic = resolveAutoComparison(state);
        state.compareFrom = automatic?.from || state.day || todayISO();
        state.compareTo = automatic?.to || state.compareFrom;
      }
      state.compareMode = mode;
      syncComparisonControls();
      if (mode !== "custom") load().catch(console.error);
      else syncUrl();
    };
  });
  $("revenueCompareFrom").onchange = (event) => { state.compareFrom = event.target.value || state.compareFrom; };
  $("revenueCompareTo").onchange = (event) => { state.compareTo = event.target.value || state.compareTo; };
  $("revenueCompareApply").onclick = () => {
    const normalized = normalizeIsoRange(state.compareFrom, state.compareTo);
    if (!normalized) {
      toast("Выбери даты сравнения", "err");
      return;
    }
    state.compareFrom = normalized.from;
    state.compareTo = normalized.to;
    load().catch(console.error);
  };

  $("exportBtn").onclick = async () => {
    const venueId = getActiveVenueId();
    if (!venueId || !state.canExport) return;

    const qs = buildQuery().toString();
    try {
      const data = await api(`/venues/${encodeURIComponent(venueId)}/revenue/export-link?${qs}&fmt=xlsx`);
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
    } catch (e) {
      console.error(e);
      toast("Не удалось начать экспорт");
    }
  };
}

async function resolveRevenueAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  try {
    const permsResp = await api(`/me/venues/${encodeURIComponent(venueId)}/permissions`);
    financialValuesHidden = isFinancialValuesHidden(permsResp);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isPrivileged = role === "OWNER" || role === "VENUE_OWNER" || role === "SUPER_ADMIN" || role === "MODERATOR";

    state.canView = isPrivileged || hasPerm(pset, "REVENUE_VIEW");
    state.canExport = isPrivileged || hasPerm(pset, "REVENUE_EXPORT");
  } catch {
    state.canView = true;
    state.canExport = true;
  }

  const exportBtn = $("exportBtn");
  setVisible(exportBtn, state.canExport);

  if (!state.canView) {
    toast("Нет доступа к выручке", "err");
    const venue = getActiveVenueId();
    const qp = venue ? `?venue_id=${encodeURIComponent(venue)}` : "";
    setTimeout(() => { location.replace(`/owner-summary.html${qp}`); }, 150);
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
    if (v) $("subtitle").textContent = v.name || "";
  } catch {}

  initFromQuery();
  syncPickers();
  syncComparisonControls();
  applySeg("modeSeg", "mode");
  applySeg("periodSeg", "period");
  bindPickers();
  await resolveRevenueAccess();
  if (!state.canView) return;
  setupDemoRevenueIntro();
  await load();
}

document.addEventListener("DOMContentLoaded", () => {
  boot().catch((e) => toast("Ошибка: " + (e?.message || e), "err"));
});

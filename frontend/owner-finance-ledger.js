import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenuePermissions,
  getPaymentMethods,
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
} from "/app/period-comparison.js?v=20260729-compare2";
import {
  buildLedgerSourceDrilldown,
  buildLedgerDailySeries,
  buildLedgerStructure,
  calculateLedgerMetrics,
  ledgerKindLabel,
} from "/app/finance-ledger-analytics.js?v=20260802-ledgerdrill1";

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
  canViewSummary: false,
  canViewRevenue: false,
  canViewExpenses: false,
  canViewPayroll: false,
  canViewReports: false,
};

const state = {
  month: currentMonth(),
  paymentMethods: [],
  entries: [],
  comparisonEntries: [],
  comparisonError: null,
  compareMode: "auto",
  compareFrom: "",
  compareTo: "",
  transfers: [],
  focusTransferId: null,
  sourceTargetFocused: false,
};

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
    access = {
      canView: isOwner || isAdmin || hasPerm(pset, "FINANCE_LEDGER_VIEW") || hasPerm(pset, "REVENUE_VIEW") || hasPerm(pset, "EXPENSE_VIEW"),
      canManageTransfers: isOwner || isAdmin || hasPerm(pset, "PAYMENT_TRANSFERS_MANAGE") || hasPerm(pset, "EXPENSE_ADD"),
      canViewSummary: canViewRevenue || canViewExpenses || canViewPayroll || hasPerm(pset, "REPORTS_VIEW_PNL") || hasPerm(pset, "MONTHLY_SUMMARY_VIEW"),
      canViewRevenue,
      canViewExpenses,
      canViewPayroll,
      canViewReports,
    };
  } catch {
    access = {
      canView: false,
      canManageTransfers: false,
      canViewSummary: false,
      canViewRevenue: false,
      canViewExpenses: false,
      canViewPayroll: false,
      canViewReports: false,
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
  return resolveComparisonRange({
    compareMode: state.compareMode,
    compareFrom: state.compareFrom,
    compareTo: state.compareTo,
    period: "month",
    month: state.month,
  });
}

function syncUrl() {
  const qp = new URLSearchParams(location.search);
  qp.set("venue_id", String(getActiveVenueId() || ""));
  qp.set("month", state.month);
  qp.set("compare_mode", state.compareMode);
  const paymentMethodId = document.getElementById("ledgerPaymentMethodPick")?.value || "";
  const kind = document.getElementById("ledgerKindPick")?.value || "";
  paymentMethodId ? qp.set("payment_method_id", paymentMethodId) : qp.delete("payment_method_id");
  kind ? qp.set("kind", kind) : qp.delete("kind");
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

function syncComparisonUi() {
  const comparison = currentComparison();
  const custom = state.compareMode === "custom";
  document.querySelectorAll("#ledgerCompareSeg [data-compare]").forEach((button) => {
    button.classList.toggle("active", button.dataset.compare === state.compareMode);
  });
  document.getElementById("ledgerCompareRange")?.classList.toggle("hidden", !custom);
  setText("ledgerComparePeriodText", formatComparisonRange(comparison));
  setText("ledgerCompareHint", comparison?.caption || "Выбери корректный период сравнения.");
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
  const current = calculateLedgerMetrics(state.entries);
  const previous = state.comparisonError ? null : calculateLedgerMetrics(state.comparisonEntries);
  setText("ledgerIncomeTotal", fmtMoneyMinor(current.incomeMinor));
  setText("ledgerExpenseTotal", fmtMoneyMinor(current.expenseMinor));
  setText("ledgerNetTotal", fmtMoneyMinor(current.netMinor));
  setText("ledgerCount", String(current.count));
  renderMetricDelta("ledgerIncomeDelta", current.incomeMinor, previous?.incomeMinor, { goodWhen: "up" });
  renderMetricDelta("ledgerExpenseDelta", current.expenseMinor, previous?.expenseMinor, { goodWhen: "down" });
  renderMetricDelta("ledgerNetDelta", current.netMinor, previous?.netMinor, { goodWhen: "up" });
  renderMetricDelta("ledgerCountDelta", current.count, previous?.count, { type: "count" });
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
  const context = `${formatMonthLabel(state.month)} · ${paymentMethod} · ${kind}`;
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
  const points = buildLedgerDailySeries(state.entries, monthRange(state.month));
  const maxValue = Math.max(0, ...points.flatMap((point) => [point.incomeMinor, point.expenseMinor]));
  if (!points.length || maxValue <= 0) {
    element.innerHTML = `<div class="ledger-chart-empty">За выбранный фильтр нет движений для графика.</div>`;
    setText("ledgerTrendFocus", "Нет данных за выбранный месяц");
    return;
  }
  const peak = points.reduce((best, point) => (
    Math.max(point.incomeMinor, point.expenseMinor) > Math.max(best.incomeMinor, best.expenseMinor) ? point : best
  ), points[0]);
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
    const showTick = point.day === 1 || point.day % 5 === 0 || index === points.length - 1;
    const aria = `${formatEntryDate(point.date)}. Приход ${fmtMoneyMinor(point.incomeMinor)}. Списание ${fmtMoneyMinor(point.expenseMinor)}. Чистый поток ${fmtSignedMoneyMinor(point.netMinor)}.`;
    return {
      svg: `<g class="ledger-day-group${point.date === peak.date ? " is-active" : ""}" data-ledger-day="${esc(point.date)}" role="button" tabindex="0" aria-label="${esc(aria)}">
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
      <div class="ledger-trend-ticks ledger-trend-ticks--${points.length}" aria-hidden="true">${bars.map((item) => item.tick).join("")}</div>
    </div>`;
  renderTrendFocus(peak);
  element.querySelectorAll("[data-ledger-day]").forEach((button) => {
    const selectPoint = () => {
      element.querySelectorAll("[data-ledger-day]").forEach((item) => item.classList.toggle("is-active", item === button));
      renderTrendFocus(points.find((point) => point.date === button.dataset.ledgerDay));
    };
    button.addEventListener("click", selectPoint);
    button.addEventListener("focus", selectPoint);
    button.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      selectPoint();
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
  const groups = buildLedgerStructure(state.entries);
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

function renderEntries() {
  const el = document.getElementById("ledgerEntriesList");
  if (!el) return;
  setText("ledgerHint", state.entries.length ? `Период ${state.month}` : `За ${state.month} записей нет`);

  if (!state.entries.length) {
    el.innerHTML = `<div class="muted">Нет финансовых записей за выбранный период.</div>`;
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

function renderTransfers() {
  const el = document.getElementById("transferList");
  if (!el) return;
  setText("transferHint", state.transfers.length ? `Записей: ${state.transfers.length}` : `За ${state.month} переводов нет`);
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
      <label>Дата<input name="transfer_date" type="date" value="${esc(item?.transfer_date || todayISO())}" required /></label>
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
  const month = document.getElementById("ledgerMonthPick")?.value || currentMonth();
  const paymentMethodId = document.getElementById("ledgerPaymentMethodPick")?.value || "";
  const kind = document.getElementById("ledgerKindPick")?.value || "";
  state.month = month;
  syncFinanceLinks();
  syncComparisonUi();

  const qp = new URLSearchParams({ month });
  if (paymentMethodId) qp.set("payment_method_id", paymentMethodId);
  if (kind) qp.set("kind", kind);

  const comparison = currentComparison();
  const compareQp = new URLSearchParams();
  if (comparison?.from) compareQp.set("date_from", comparison.from);
  if (comparison?.to) compareQp.set("date_to", comparison.to);
  if (paymentMethodId) compareQp.set("payment_method_id", paymentMethodId);
  if (kind) compareQp.set("kind", kind);

  const entriesPromise = access.canView ? api(`/venues/${encodeURIComponent(venueId)}/finance/entries?${qp.toString()}`) : Promise.resolve([]);
  const comparisonPromise = access.canView && comparison
    ? api(`/venues/${encodeURIComponent(venueId)}/finance/entries?${compareQp.toString()}`).then((value) => ({ value })).catch((error) => ({ error }))
    : Promise.resolve({ value: [] });
  const transfersPromise = access.canView
    ? api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers?month=${encodeURIComponent(month)}`)
    : Promise.resolve([]);
  const [entries, comparisonResult, transfers] = await Promise.all([entriesPromise, comparisonPromise, transfersPromise]);
  state.entries = Array.isArray(entries) ? entries : [];
  state.comparisonEntries = Array.isArray(comparisonResult.value) ? comparisonResult.value : [];
  state.comparisonError = comparisonResult.error || null;
  state.transfers = Array.isArray(transfers) ? transfers : [];
  syncUrl();
  renderChartContext();
  renderMetrics();
  renderTrendChart();
  renderStructureChart();
  renderEntries();
  renderTransfers();
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
  document.getElementById("ledgerMonthPick").value = params.get("month") || currentMonth();
  document.getElementById("ledgerPaymentMethodPick").value = params.get("payment_method_id") || "";
  document.getElementById("ledgerKindPick").value = (params.get("kind") || "").toUpperCase();
  state.month = document.getElementById("ledgerMonthPick").value;
  state.focusTransferId = Number(params.get("transfer_id") || 0) || null;
  syncFinanceLinks();
  state.compareMode = params.get("compare_mode") === "custom" ? "custom" : "auto";
  state.compareFrom = params.get("compare_from") || "";
  state.compareTo = params.get("compare_to") || "";
  if (state.compareMode === "custom" && !normalizeIsoRange(state.compareFrom, state.compareTo)) {
    const automatic = resolveComparisonRange({ period: "month", month: state.month });
    state.compareFrom = automatic?.from || `${state.month}-01`;
    state.compareTo = automatic?.to || state.compareFrom;
  }
  syncComparisonUi();
  document.getElementById("ledgerMonthPick").onchange = reload;
  document.getElementById("ledgerPaymentMethodPick").onchange = reload;
  document.getElementById("ledgerKindPick").onchange = reload;
  const addTransferBtn = document.getElementById("addTransferBtn");
  setVisible(addTransferBtn, access.canManageTransfers);
  addTransferBtn.onclick = () => openTransferForm();
  document.querySelectorAll("#ledgerCompareSeg [data-compare]").forEach((button) => {
    button.onclick = async () => {
      const nextMode = button.dataset.compare === "custom" ? "custom" : "auto";
      if (nextMode === "custom" && state.compareMode !== "custom") {
        const automatic = resolveComparisonRange({ period: "month", month: state.month });
        state.compareFrom = automatic?.from || `${state.month}-01`;
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
  document.querySelectorAll("[data-close], .modal__backdrop").forEach((el) => el.addEventListener("click", closeModal));

  await reload();
}

document.addEventListener("DOMContentLoaded", boot);

import {
  applyTelegramTheme, mountCommonUI, ensureLogin, mountNav, getActiveVenueId, setActiveVenueId,
  getMyVenues, getMyVenuePermissions, getMe, api, toast, coerceDemoMonth,
} from "/app.js?v=20260930-ui5";
import { hasOwnerDashboardAccess, permSetFromResponse, roleUpper, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js?v=20260924-dashboardaccess1";
import {
  DASHBOARD_ACTION_IDS, applyDashboardPreset, dashboardDeviceKind, loadDashboardLayout,
  moveDashboardAction, moveDashboardWidget, reorderDashboardWidget, resetDashboardLayout,
  saveDashboardLayout, setDashboardWidgetSize, toggleDashboardAction, toggleDashboardWidget,
} from "/owner-dashboard-config.js?v=20260924-owner-dashboard2";
import { dashboardDateLabel, dashboardReferenceDate } from "/owner-dashboard-period.js?v=20260928-period1";

const WIDGETS = Object.freeze({
  revenue_today: { title: "Выручка сегодня", target: "turnover", direction: "up" },
  revenue_month: { title: "Выручка за месяц", target: "turnover", direction: "up" },
  profit_month: { title: "Прибыль за месяц", target: "summary", direction: "up" },
  expenses_month: { title: "Расходы за месяц", target: "expenses", direction: "down" },
  payroll_month: { title: "ФОТ за месяц", target: "payroll", direction: "down" },
  margin_month: { title: "Маржинальность", target: "summary", direction: "up" },
  revenue_plan: { title: "Выполнение плана", target: "plans", direction: "up" },
  profit_forecast: { title: "Прогноз прибыли", target: "summary", direction: "up" },
  shifts_today: { title: "Смены сегодня", target: "schedule", direction: "neutral" },
  top_department: { title: "Лидер по выручке", target: "day", direction: "neutral" },
  integration_health: { title: "Проблемы интеграций", target: "integrations", direction: "down" },
});

const ACTIONS = Object.freeze({
  add_expense: { title: "Добавить расход", icon: "+", target: "expenses", primary: true, action: "add" },
  expenses: { title: "Расходы", icon: "₽", target: "expenses" },
  summary: { title: "Полная сводка", icon: "∑", target: "summary" },
  turnover: { title: "Выручка", icon: "↗", target: "turnover" },
  payroll: { title: "Начисления", icon: "◎", target: "payroll" },
  report: { title: "Отчёт дня", icon: "✓", target: "report" },
  schedule: { title: "График", icon: "▦", target: "schedule" },
  integrations: { title: "Интеграции", icon: "⇄", target: "integrations" },
  venue: { title: "Заведение", icon: "⌂", target: "venue" },
});

const state = {
  venueId: "", month: "", scope: "venue", trendMetric: "revenue", layout: null, undoLayout: null,
  deviceKind: dashboardDeviceKind(), ownerVenues: [], monthData: null, previousData: null, dayData: null,
  economics: null, monthPlan: null, departmentPlan: null, payroll: null, reports: [], integrations: [],
  integrationQuality: [], networkRows: [], financialValuesHidden: false, sourceErrors: [], loadRevision: 0,
  referenceDate: "",
};

function todayISO() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function currentMonth() {
  return coerceDemoMonth(todayISO().slice(0, 7), { notify: false, context: "owner-dashboard" });
}

function previousMonth(month) {
  const [year, monthNumber] = String(month || currentMonth()).split("-").map(Number);
  const date = new Date(Date.UTC(year, monthNumber - 2, 1));
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function daysInMonth(month) {
  const [year, monthNumber] = String(month).split("-").map(Number);
  return new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
}

function elapsedDays(month) {
  if (month < currentMonth()) return daysInMonth(month);
  if (month > currentMonth()) return 0;
  return Math.min(new Date().getDate(), daysInMonth(month));
}

function localeTag() {
  return globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU";
}

function formatMoneyMinor(value) {
  if (state.financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  if (value === null || value === undefined) return "Недоступно";
  return `${new Intl.NumberFormat(localeTag(), { maximumFractionDigits: 0 }).format(Number(value || 0) / 100)} ₽`;
}

function formatPercentBps(value) {
  if (state.financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  if (value === null || value === undefined) return "Недоступно";
  return `${new Intl.NumberFormat(localeTag(), { maximumFractionDigits: 1 }).format(Number(value || 0) / 100)}%`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat(localeTag(), { maximumFractionDigits: 1 }).format(Number(value || 0));
}

function monthLabel(month) {
  const [year, monthNumber] = String(month || "").split("-").map(Number);
  if (!year || !monthNumber) return "Текущий месяц";
  const value = new Intl.DateTimeFormat(localeTag(), { month: "long", year: "numeric", timeZone: "UTC" })
    .format(new Date(Date.UTC(year, monthNumber - 1, 1)));
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function hrefFor(target, venueId = state.venueId) {
  const query = new URLSearchParams({ venue_id: String(venueId), month: state.month });
  const paths = {
    turnover: "/owner-turnover.html", summary: "/owner-summary.html", expenses: "/owner-expenses.html",
    payroll: "/owner-payroll.html", report: "/staff-report.html", schedule: "/staff-shifts.html",
    integrations: "/owner-integrations.html", plans: "/owner-economics-plans.html",
    day: "/owner-day-economics.html", venue: "/app-venue.html",
  };
  if (target === "day" || target === "report") query.set("date", state.referenceDate || todayISO());
  return `${paths[target] || paths.summary}?${query.toString()}`;
}

function percentDelta(current, previous) {
  if (current === null || current === undefined || previous === null || previous === undefined) return null;
  const delta = Number(current) - Number(previous);
  if (Number(previous) === 0) return { delta, percent: null };
  return { delta, percent: delta / Math.abs(Number(previous)) * 100 };
}

function deltaView(current, previous, { money = true, direction = "up" } = {}) {
  const delta = percentDelta(current, previous);
  if (!delta || state.financialValuesHidden) return { text: "Нет сравнения", tone: "is-neutral" };
  const sign = delta.delta > 0 ? "+" : delta.delta < 0 ? "−" : "";
  const percent = delta.percent === null ? "нет базы" : `${sign}${Math.abs(delta.percent).toLocaleString(localeTag(), { maximumFractionDigits: 1 })}%`;
  const absolute = money ? ` · ${sign}${formatMoneyMinor(Math.abs(delta.delta))}` : "";
  const good = (direction === "up" && delta.delta > 0) || (direction === "down" && delta.delta < 0);
  const bad = (direction === "up" && delta.delta < 0) || (direction === "down" && delta.delta > 0);
  return { text: `${percent}${absolute}`, tone: good ? "is-good" : bad ? "is-bad" : "is-neutral" };
}

function dailySeries(field) {
  return Array.isArray(state.monthData?.daily_series)
    ? state.monthData.daily_series.map((row) => Number(row?.[field] || 0))
    : [];
}

function financeDataAvailable(summary) {
  if (state.financialValuesHidden) return true;
  if (!summary) return false;
  const fields = [
    "revenue_minor", "expense_minor", "expense_without_payroll_minor", "payroll_minor",
    "total_cost_minor", "adjustments_minor", "refunds_minor", "profit_minor",
  ];
  if (fields.some((field) => Number(summary?.[field] || 0) !== 0)) return true;
  if ((summary.cost_structure || []).some((row) => Number(row?.amount_minor || 0) !== 0)) return true;
  return (summary.daily_series || []).some((row) => fields.some((field) => Number(row?.[field] || 0) !== 0));
}

function emptyFinanceWidget(hint = "За выбранный период нет финансовых операций") {
  return {
    value: "Данных пока нет",
    hint,
    delta: { text: "Выберите другой период", tone: "is-neutral" },
    series: [],
    empty: true,
  };
}

function widgetView(widgetId) {
  const month = state.monthData || {};
  const previous = state.previousData || {};
  const economics = state.economics || {};
  const plan = state.monthPlan || {};
  const dayContext = state.month === currentMonth() ? "Сегодня" : dashboardDateLabel(state.referenceDate, localeTag());
  const hasMonthData = financeDataAvailable(month);
  if (widgetId === "revenue_today") return financeDataAvailable(state.dayData)
    ? { value: formatMoneyMinor(state.dayData?.revenue_minor), hint: "По закрытым отчётам за день", delta: { text: dayContext, tone: "is-neutral" }, series: [] }
    : emptyFinanceWidget("За сегодня ещё нет закрытых отчётов");
  if (widgetId === "revenue_month") return hasMonthData
    ? { value: formatMoneyMinor(month.revenue_minor), hint: "С начала выбранного месяца", delta: deltaView(month.revenue_minor, previous.revenue_minor), series: dailySeries("revenue_minor") }
    : emptyFinanceWidget();
  if (widgetId === "profit_month") return hasMonthData
    ? { value: formatMoneyMinor(month.profit_minor), hint: "После расходов и ФОТ", delta: deltaView(month.profit_minor, previous.profit_minor), series: dailySeries("profit_minor") }
    : emptyFinanceWidget();
  if (widgetId === "expenses_month") return hasMonthData
    ? { value: formatMoneyMinor(month.expense_without_payroll_minor), hint: "Подтверждённые, без ФОТ", delta: deltaView(month.expense_without_payroll_minor, previous.expense_without_payroll_minor, { direction: "down" }), series: dailySeries("expense_minor") }
    : emptyFinanceWidget();
  if (widgetId === "payroll_month") return hasMonthData
    ? { value: formatMoneyMinor(month.payroll_minor), hint: "Начисления команды", delta: deltaView(month.payroll_minor, previous.payroll_minor, { direction: "down" }), series: dailySeries("payroll_minor") }
    : emptyFinanceWidget();
  if (widgetId === "margin_month") return hasMonthData
    ? { value: formatPercentBps(month.margin_bps), hint: "Доля прибыли от выручки", delta: deltaView(month.margin_bps, previous.margin_bps, { money: false }), series: dailySeries("profit_minor") }
    : emptyFinanceWidget();
  if (widgetId === "revenue_plan") {
    const target = Number(plan.revenue_plan_minor || 0);
    const actual = Number(month.revenue_minor || 0);
    const progress = target > 0 ? Math.round(actual / target * 10000) : null;
    return { value: progress === null ? "План не задан" : formatPercentBps(progress), hint: target > 0 ? `${formatMoneyMinor(actual)} из ${formatMoneyMinor(target)}` : "Задайте план на месяц", delta: { text: target > 0 && actual >= target ? "План выполнен" : "План / факт", tone: actual >= target && target > 0 ? "is-good" : "is-neutral" }, series: dailySeries("revenue_minor") };
  }
  if (widgetId === "profit_forecast") {
    if (!hasMonthData) return emptyFinanceWidget("Для прогноза нужны данные выбранного месяца");
    const elapsed = elapsedDays(state.month);
    const forecast = elapsed > 0 ? Math.round(Number(month.profit_minor || 0) / elapsed * daysInMonth(state.month)) : null;
    return { value: formatMoneyMinor(forecast), hint: state.month === currentMonth() ? `По темпу за ${elapsed} дн.` : "Фактический результат месяца", delta: deltaView(forecast, plan.profit_plan_minor), series: dailySeries("profit_minor") };
  }
  if (widgetId === "shifts_today") return { value: formatNumber(economics.team?.total_shift_count), hint: `${formatNumber(economics.team?.assigned_user_count)} сотрудник(ов) назначено`, delta: { text: economics.team?.unassigned_shift_count ? `${economics.team.unassigned_shift_count} без сотрудников` : "Смены укомплектованы", tone: economics.team?.unassigned_shift_count ? "is-bad" : "is-good" }, series: [] };
  if (widgetId === "top_department") return { value: economics.metrics?.top_department_title || "Нет данных", hint: economics.metrics?.top_department_share_bps != null ? `${formatPercentBps(economics.metrics.top_department_share_bps)} выручки дня` : "Из отчёта дня", delta: { text: dayContext, tone: "is-neutral" }, series: [] };
  const issueCount = state.integrationQuality.reduce((sum, item) => sum + Number(item.active_issue_count || 0), 0);
  const failed = state.integrationQuality.some((item) => item.health === "FAILED");
  const syncDates = state.integrations.map((item) => item.last_successful_sync_at || item.last_sync_at).filter(Boolean).map((value) => new Date(value)).filter((value) => !Number.isNaN(value.getTime()));
  const latestSync = syncDates.length ? new Date(Math.max(...syncDates.map((value) => value.getTime()))) : null;
  const syncHint = latestSync ? `Последняя синхронизация ${latestSync.toLocaleString(localeTag(), { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}` : state.integrations.length ? "Синхронизация ещё не завершалась" : "POS не подключён";
  return { value: formatNumber(issueCount), hint: syncHint, delta: { text: failed ? "Есть критические ошибки" : issueCount ? "Нужно проверить" : "Синхронизация в норме", tone: failed ? "is-bad" : issueCount ? "is-neutral" : "is-good" }, series: [] };
}

function createSparkline(values) {
  if (!Array.isArray(values) || values.length < 2) return null;
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("owner-dashboard-widget__sparkline");
  svg.setAttribute("viewBox", "0 0 160 38");
  svg.setAttribute("aria-hidden", "true");
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const points = values.map((value, index) => `${index / (values.length - 1) * 158 + 1},${36 - (value - min) / range * 32}`).join(" ");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", `M ${points.replaceAll(" ", " L ")}`);
  svg.append(path);
  return svg;
}

function createWidgetCard(widgetId) {
  const definition = WIDGETS[widgetId];
  const view = widgetView(widgetId);
  const size = state.layout.sizes[widgetId] || "normal";
  const card = document.createElement("a");
  card.className = `itemcard owner-dashboard-widget owner-dashboard-widget--${size}`;
  card.classList.toggle("is-empty", Boolean(view.empty));
  card.href = hrefFor(definition.target);
  card.dataset.widgetId = widgetId;
  const label = document.createElement("div");
  label.className = "owner-dashboard-widget__label";
  const historicalDay = state.month !== currentMonth()
    && ["revenue_today", "shifts_today", "top_department"].includes(widgetId);
  label.textContent = historicalDay
    ? definition.title.replace("сегодня", `за ${dashboardDateLabel(state.referenceDate, localeTag())}`)
    : definition.title;
  const labelRow = document.createElement("div");
  labelRow.className = "block-title-with-info";
  const info = document.createElement("span");
  info.className = "info-button";
  info.setAttribute("role", "button");
  info.setAttribute("tabindex", "0");
  info.setAttribute("aria-label", `О показателе «${definition.title}»`);
  info.setAttribute("aria-expanded", "false");
  info.dataset.info = view.hint;
  info.textContent = "i";
  labelRow.append(label, info);
  const value = document.createElement("div");
  value.className = "owner-dashboard-widget__value";
  value.textContent = view.value;
  const sparkline = createSparkline(view.series);
  const visual = document.createElement("div");
  visual.className = "owner-dashboard-widget__visual";
  if (sparkline && size === "wide") visual.append(sparkline);
  const delta = document.createElement("div");
  delta.className = `owner-dashboard-widget__delta ${view.delta.tone}`;
  delta.textContent = view.delta.text;
  const meta = document.createElement("div");
  meta.className = "owner-dashboard-widget__meta";
  const arrow = document.createElement("span");
  arrow.className = "owner-dashboard-widget__arrow";
  arrow.textContent = "→";
  meta.append(arrow);
  card.append(labelRow, value, delta, visual, meta);
  return card;
}

function renderWidgets() {
  const grid = document.getElementById("dashboardWidgetGrid");
  if (!grid || !state.layout) return;
  const hidden = new Set(state.layout.hidden);
  grid.replaceChildren(...state.layout.order.filter((id) => !hidden.has(id)).map(createWidgetCard));
  grid.setAttribute("aria-busy", "false");
}

function moveButtons(id, index, count, kind) {
  const controls = document.createElement("div");
  controls.className = "owner-dashboard-config__move";
  for (const [direction, text] of [["up", "↑"], ["down", "↓"]]) {
    const button = document.createElement("button");
    button.className = "btn sm subtle";
    button.type = "button";
    button.textContent = text;
    button.dataset.configMove = id;
    button.dataset.configKind = kind;
    button.dataset.direction = direction;
    button.disabled = direction === "up" ? index === 0 : index === count - 1;
    controls.append(button);
  }
  return controls;
}

function configToggle(id, title, checked, kind) {
  const label = document.createElement("label");
  label.className = "owner-dashboard-config__toggle";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = checked;
  input.dataset.configToggle = id;
  input.dataset.configKind = kind;
  const text = document.createElement("span");
  text.textContent = title;
  label.append(input, text);
  return label;
}

function renderConfig() {
  const list = document.getElementById("dashboardConfigList");
  const actionList = document.getElementById("dashboardActionConfigList");
  if (!list || !actionList || !state.layout) return;
  document.getElementById("dashboardConfigHint").textContent = `Настраивается раскладка: ${state.deviceKind === "mobile" ? "телефон" : "компьютер"}. Изменения сохраняются на этом устройстве.`;
  const hidden = new Set(state.layout.hidden);
  list.replaceChildren(...state.layout.order.map((widgetId, index) => {
    const row = document.createElement("div");
    row.className = "owner-dashboard-config__row";
    row.draggable = true;
    row.dataset.dragWidget = widgetId;
    const select = document.createElement("select");
    select.className = "finance-control owner-dashboard-config__size";
    select.dataset.widgetSize = widgetId;
    for (const [value, label] of [["compact", "Компактный"], ["normal", "Обычный"], ["wide", "Широкий"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = state.layout.sizes[widgetId] === value;
      select.append(option);
    }
    row.append(configToggle(widgetId, WIDGETS[widgetId].title, !hidden.has(widgetId), "widget"), select, moveButtons(widgetId, index, state.layout.order.length, "widget"));
    return row;
  }));
  const hiddenActions = new Set(state.layout.hiddenActions);
  actionList.replaceChildren(...state.layout.actionOrder.map((actionId, index) => {
    const row = document.createElement("div");
    row.className = "owner-dashboard-config__row";
    row.append(configToggle(actionId, ACTIONS[actionId].title, !hiddenActions.has(actionId), "action"), moveButtons(actionId, index, state.layout.actionOrder.length, "action"));
    return row;
  }));
}

function persistAndRender(layout) {
  state.layout = saveDashboardLayout(state.venueId, layout, globalThis.localStorage, state.deviceKind);
  renderWidgets();
  renderConfig();
  renderQuickActions();
}

function renderQuickActions() {
  const container = document.getElementById("dashboardActions");
  if (!container || !state.layout) return;
  const hidden = new Set(state.layout.hiddenActions);
  container.replaceChildren(...state.layout.actionOrder.filter((id) => !hidden.has(id)).map((actionId) => {
    const item = ACTIONS[actionId];
    const link = document.createElement("a");
    link.className = `owner-dashboard-action${item.primary ? " owner-dashboard-action--primary" : ""}`;
    const url = new URL(hrefFor(item.target), location.origin);
    if (item.action) url.searchParams.set("action", item.action);
    link.href = `${url.pathname}${url.search}`;
    const icon = document.createElement("span");
    icon.className = "owner-dashboard-action__icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = item.icon;
    const title = document.createElement("span");
    title.textContent = item.title;
    link.append(icon, title);
    return link;
  }));
}

function alertTarget(code) {
  if (code.includes("REPORT")) return "report";
  if (code.includes("EXPENSE")) return "expenses";
  if (code.includes("SHIFT") || code.includes("ASSIGNED")) return "schedule";
  if (code.includes("PAYROLL")) return "payroll";
  if (code.includes("INTEGRATION")) return "integrations";
  return "day";
}

function dashboardAlerts() {
  const alerts = (state.economics?.alerts || []).map((item) => ({ ...item, target: alertTarget(String(item.code || "")) }));
  const unassigned = Number(state.economics?.team?.unassigned_shift_count || 0);
  if (unassigned > 0 && !alerts.some((item) => item.code === "SHIFT_COVERAGE_LOW")) alerts.push({ severity: "WARN", code: "UNASSIGNED_SHIFTS", title: "Есть смены без сотрудников", detail: `${unassigned} смен(ы) сегодня требуют назначения.`, target: "schedule" });
  const closedReports = state.reports.filter((item) => String(item.status || "").toUpperCase() === "CLOSED").length;
  if (closedReports > 0 && !state.payroll?.run) alerts.push({ severity: "INFO", code: "PAYROLL_NOT_CALCULATED", title: "Начисления не рассчитаны", detail: "Есть закрытые отчёты, но расчёт ФОТ за месяц ещё не запускался.", target: "payroll" });
  for (const quality of state.integrationQuality) {
    if (quality.health === "HEALTHY") continue;
    const connection = state.integrations.find((item) => Number(item.id) === Number(quality.connection_id));
    alerts.push({ severity: quality.health === "FAILED" ? "CRITICAL" : "WARN", code: `INTEGRATION_${quality.connection_id}`, title: `${String(connection?.provider || "POS").toUpperCase()}: требуется проверка`, detail: `${Number(quality.active_issue_count || 0)} активных проблем, ${Number(quality.stale_capability_count || 0)} устаревших источников.`, target: "integrations" });
  }
  return alerts;
}

function renderAttention() {
  const section = document.getElementById("dashboardAttention");
  const list = document.getElementById("dashboardAttentionList");
  const count = document.getElementById("dashboardAttentionCount");
  const alerts = dashboardAlerts();
  if (count) count.textContent = String(alerts.length);
  section?.classList.toggle("hidden", !alerts.length);
  if (!list) return;
  if (!alerts.length) {
    list.replaceChildren();
    return;
  }
  list.replaceChildren(...alerts.map((item) => {
    const link = document.createElement("a");
    link.className = `owner-dashboard-alert owner-dashboard-alert--${String(item.severity || "INFO").toLowerCase()}`;
    link.href = hrefFor(item.target || "day");
    const marker = document.createElement("span");
    marker.className = "owner-dashboard-alert__marker";
    const content = document.createElement("span");
    content.className = "owner-dashboard-alert__content";
    const title = document.createElement("b");
    title.textContent = item.title || "Требуется проверка";
    const detail = document.createElement("span");
    detail.className = "owner-dashboard-alert__detail";
    detail.textContent = item.detail || "Откройте раздел для деталей.";
    content.append(title, detail);
    const arrow = document.createElement("span");
    arrow.className = "owner-dashboard-widget__arrow";
    arrow.textContent = "→";
    link.append(marker, content, arrow);
    return link;
  }));
}

function trendField() {
  return state.trendMetric === "profit" ? "profit_minor" : state.trendMetric === "cost" ? "total_cost_minor" : "revenue_minor";
}

function renderTrend() {
  const container = document.getElementById("dashboardTrendChart");
  const legend = document.getElementById("dashboardTrendLegend");
  if (!container || !legend) return;
  const rows = Array.isArray(state.monthData?.daily_series) ? state.monthData.daily_series : [];
  const values = rows.map((row) => Number(row?.[trendField()] || 0));
  if (!rows.length || !financeDataAvailable(state.monthData)) {
    const empty = document.createElement("div");
    empty.className = "owner-dashboard-empty";
    empty.textContent = "Для графика пока нет закрытых отчётов за выбранный месяц.";
    container.replaceChildren(empty);
    legend.textContent = "";
    return;
  }
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 800 230");
  const left = 22, top = 14, width = 756, height = 180;
  const min = Math.min(0, ...values), max = Math.max(...values), range = max - min || 1;
  const coordinates = values.map((value, index) => ({ x: left + index / Math.max(1, values.length - 1) * width, y: top + height - (value - min) / range * height }));
  for (let index = 0; index < 4; index += 1) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
    const y = top + index * height / 3;
    line.setAttribute("x1", String(left)); line.setAttribute("x2", String(left + width)); line.setAttribute("y1", String(y)); line.setAttribute("y2", String(y));
    line.classList.add("owner-dashboard-trend__grid"); svg.append(line);
  }
  const area = document.createElementNS("http://www.w3.org/2000/svg", "path");
  area.classList.add("owner-dashboard-trend__area");
  area.setAttribute("d", `M ${left} ${top + height} L ${coordinates.map((point) => `${point.x} ${point.y}`).join(" L ")} L ${left + width} ${top + height} Z`);
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.classList.add("owner-dashboard-trend__line");
  path.setAttribute("d", `M ${coordinates.map((point) => `${point.x} ${point.y}`).join(" L ")}`);
  svg.append(area, path);
  coordinates.forEach((point, index) => {
    if (coordinates.length > 18 && index % 3 !== 0 && index !== coordinates.length - 1) return;
    const dot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    dot.classList.add("owner-dashboard-trend__dot"); dot.setAttribute("cx", String(point.x)); dot.setAttribute("cy", String(point.y)); dot.setAttribute("r", "3.5");
    const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
    title.textContent = `${rows[index]?.date || ""}: ${formatMoneyMinor(values[index])}`;
    dot.append(title); svg.append(dot);
  });
  container.replaceChildren(svg);
  const total = values.reduce((sum, value) => sum + value, 0);
  const average = values.length ? Math.round(total / values.length) : 0;
  legend.textContent = `Всего: ${formatMoneyMinor(total)} · Среднее за день: ${formatMoneyMinor(average)} · Точек: ${values.length}`;
}

function operationItems() {
  const economics = state.economics || {};
  const metrics = economics.metrics || {};
  const items = [
    [state.month === currentMonth() ? "Смен сегодня" : `Смен за ${dashboardDateLabel(state.referenceDate, localeTag())}`, economics.team?.total_shift_count], ["Сотрудников назначено", economics.team?.assigned_user_count],
    ["Смен без сотрудников", economics.team?.unassigned_shift_count], ["Закрытых отчётов в месяце", state.reports.filter((row) => String(row.status).toUpperCase() === "CLOSED").length],
    ["Выручка на сотрудника", metrics.revenue_per_assigned_minor, "money"], ["Покрытие смен", metrics.assigned_shift_coverage_bps, "percent"],
  ];
  for (const metric of (economics.kpi_breakdown || []).slice(0, 3)) {
    const unit = String(metric.unit || "QTY").toUpperCase();
    items.push([metric.title, unit === "RUB" ? Number(metric.value_numeric || 0) * 100 : metric.value_numeric, unit === "RUB" ? "money" : unit === "PERCENT" ? "plain-percent" : "number"]);
  }
  return items;
}

function renderOperations() {
  const grid = document.getElementById("dashboardOperationsGrid");
  const link = document.getElementById("dashboardOperationsLink");
  if (link) link.href = hrefFor("day");
  const title = document.getElementById("dashboardOperationsTitle");
  if (title) title.textContent = state.month === currentMonth()
    ? "Операционка сегодня"
    : `Операционка за ${dashboardDateLabel(state.referenceDate, localeTag())}`;
  if (!grid) return;
  if (!state.economics) {
    const empty = document.createElement("div"); empty.className = "owner-dashboard-empty"; empty.textContent = "Операционные показатели пока недоступны."; grid.replaceChildren(empty); return;
  }
  grid.replaceChildren(...operationItems().map(([labelText, rawValue, format]) => {
    const card = document.createElement("div"); card.className = "owner-dashboard-operation";
    const label = document.createElement("div"); label.className = "owner-dashboard-operation__label"; label.textContent = labelText;
    const value = document.createElement("div"); value.className = "owner-dashboard-operation__value";
    value.textContent = format === "money" ? formatMoneyMinor(rawValue) : format === "percent" ? formatPercentBps(rawValue) : format === "plain-percent" ? `${formatNumber(rawValue)}%` : formatNumber(rawValue);
    card.append(label, value); return card;
  }));
}

function renderNetwork() {
  const section = document.getElementById("dashboardNetwork");
  const list = document.getElementById("dashboardNetworkList");
  const networkMode = state.scope === "network";
  section?.classList.toggle("hidden", !networkMode);
  document.getElementById("dashboardOperations")?.classList.toggle("hidden", networkMode);
  if (!networkMode || !list) return;
  const sorted = [...state.networkRows].sort((a, b) => Number(b.summary?.revenue_minor || 0) - Number(a.summary?.revenue_minor || 0));
  list.replaceChildren(...sorted.map((row, index) => {
    const card = document.createElement("div"); card.className = "owner-dashboard-network-row";
    const name = document.createElement("div"); name.className = "owner-dashboard-network-row__name";
    const title = document.createElement("b"); title.textContent = `${index + 1}. ${row.venue.name || `Заведение #${row.venue.id}`}`;
    const status = document.createElement("span"); status.className = "muted"; status.textContent = row.error ? "Данные недоступны" : `Обновлено ${new Date().toLocaleTimeString(localeTag(), { hour: "2-digit", minute: "2-digit" })}`;
    name.append(title, status); card.append(name);
    for (const [labelText, field] of [["Выручка", "revenue_minor"], ["Прибыль", "profit_minor"], ["Маржа", "margin_bps"]]) {
      const metric = document.createElement("div"); metric.className = "owner-dashboard-network-row__metric";
      const label = document.createElement("span"); label.textContent = labelText;
      const value = document.createElement("b"); value.textContent = field === "margin_bps" ? formatPercentBps(row.summary?.[field]) : formatMoneyMinor(row.summary?.[field]);
      metric.append(label, value); card.append(metric);
    }
    const health = document.createElement("span"); health.className = `owner-dashboard-network-row__health${row.error ? " is-error" : row.issueCount ? " is-warning" : ""}`; health.title = row.error ? "Ошибка загрузки" : row.issueCount ? `${row.issueCount} проблем` : "Данные в норме";
    const open = document.createElement("a"); open.className = "btn sm subtle"; open.href = hrefFor("summary", row.venue.id); open.textContent = "Открыть";
    card.append(health, open); return card;
  }));
}

function setDashboardState(title = "", text = "") {
  const card = document.getElementById("dashboardState");
  const visible = Boolean(title || text); card?.classList.toggle("hidden", !visible);
  if (document.getElementById("dashboardStateTitle")) document.getElementById("dashboardStateTitle").textContent = title;
  if (document.getElementById("dashboardStateText")) document.getElementById("dashboardStateText").textContent = text;
}

async function optional(path, label) {
  try { return await api(path); } catch (error) { state.sourceErrors.push({ label, error }); return null; }
}

function aggregateFinance(rows) {
  const fields = ["revenue_minor", "expense_minor", "expense_without_payroll_minor", "payroll_minor", "total_cost_minor", "profit_minor"];
  const aggregate = { daily_series: [] };
  for (const field of fields) aggregate[field] = rows.reduce((sum, row) => sum + Number(row?.[field] || 0), 0);
  aggregate.margin_bps = aggregate.revenue_minor ? Math.round(aggregate.profit_minor / aggregate.revenue_minor * 10000) : null;
  const byDate = new Map();
  for (const row of rows) for (const point of (row?.daily_series || [])) {
    const target = byDate.get(point.date) || { date: point.date };
    for (const field of fields) target[field] = Number(target[field] || 0) + Number(point?.[field] || 0);
    byDate.set(point.date, target);
  }
  aggregate.daily_series = Array.from(byDate.values()).sort((a, b) => String(a.date).localeCompare(String(b.date)));
  return aggregate;
}

async function loadIntegrationQuality(connections) {
  const quality = await Promise.all((connections || []).map((connection) => optional(`/pos-integrations/${encodeURIComponent(connection.id)}/quality-summary`, `integration-${connection.id}`)));
  return quality.filter(Boolean);
}

async function loadVenueDashboard(revision) {
  const venueId = state.venueId;
  const previous = previousMonth(state.month);
  const [monthData, previousData, monthPlan, departmentPlan, payroll, reports, integrations] = await Promise.all([
    api(`/venues/${encodeURIComponent(venueId)}/finance/summary?month=${encodeURIComponent(state.month)}&include_series=true`),
    api(`/venues/${encodeURIComponent(venueId)}/finance/summary?month=${encodeURIComponent(previous)}&include_series=true`),
    optional(`/venues/${encodeURIComponent(venueId)}/economics/plan-month?month=${encodeURIComponent(state.month)}`, "month-plan"),
    optional(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-month?month=${encodeURIComponent(state.month)}`, "department-plan"),
    optional(`/venues/${encodeURIComponent(venueId)}/payroll?month=${encodeURIComponent(state.month)}`, "payroll"),
    optional(`/venues/${encodeURIComponent(venueId)}/reports?month=${encodeURIComponent(state.month)}&shift_slot=DAY`, "reports"),
    optional(`/venues/${encodeURIComponent(venueId)}/pos-integrations`, "integrations"),
  ]);
  if (revision !== state.loadRevision) return;
  const day = dashboardReferenceDate(state.month, {
    today: todayISO(),
    dailySeries: monthData?.daily_series,
    reports: Array.isArray(reports) ? reports : [],
  });
  const [dayData, economics] = await Promise.all([
    api(`/venues/${encodeURIComponent(venueId)}/finance/summary?date_from=${encodeURIComponent(day)}&date_to=${encodeURIComponent(day)}`),
    optional(`/venues/${encodeURIComponent(venueId)}/economics/day?date=${encodeURIComponent(day)}`, "economics"),
  ]);
  if (revision !== state.loadRevision) return;
  state.referenceDate = day;
  state.monthData = monthData; state.previousData = previousData; state.dayData = dayData; state.economics = economics;
  state.monthPlan = monthPlan; state.departmentPlan = departmentPlan; state.payroll = payroll;
  state.reports = Array.isArray(reports) ? reports : []; state.integrations = Array.isArray(integrations) ? integrations : [];
  state.integrationQuality = await loadIntegrationQuality(state.integrations);
}

async function loadNetworkDashboard(revision) {
  const previous = previousMonth(state.month);
  const day = dashboardReferenceDate(state.month, { today: todayISO() });
  state.referenceDate = day;
  const rows = await Promise.all(state.ownerVenues.map(async (venue) => {
    try {
      const [summary, previousSummary, daySummary, plan, integrations] = await Promise.all([
        api(`/venues/${encodeURIComponent(venue.id)}/finance/summary?month=${encodeURIComponent(state.month)}&include_series=true`),
        api(`/venues/${encodeURIComponent(venue.id)}/finance/summary?month=${encodeURIComponent(previous)}&include_series=true`),
        api(`/venues/${encodeURIComponent(venue.id)}/finance/summary?date_from=${encodeURIComponent(day)}&date_to=${encodeURIComponent(day)}`),
        optional(`/venues/${encodeURIComponent(venue.id)}/economics/plan-month?month=${encodeURIComponent(state.month)}`, `plan-${venue.id}`),
        optional(`/venues/${encodeURIComponent(venue.id)}/pos-integrations`, `integrations-${venue.id}`),
      ]);
      const quality = await loadIntegrationQuality(Array.isArray(integrations) ? integrations : []);
      return { venue, summary, previousSummary, daySummary, plan, integrations: integrations || [], quality, issueCount: quality.reduce((sum, item) => sum + Number(item.active_issue_count || 0), 0) };
    } catch (error) { return { venue, error }; }
  }));
  if (revision !== state.loadRevision) return;
  state.networkRows = rows;
  const successful = rows.filter((row) => row.summary);
  state.monthData = aggregateFinance(successful.map((row) => row.summary));
  state.previousData = aggregateFinance(successful.map((row) => row.previousSummary));
  state.dayData = aggregateFinance(successful.map((row) => row.daySummary));
  state.monthPlan = {
    revenue_plan_minor: successful.reduce((sum, row) => sum + Number(row.plan?.revenue_plan_minor || 0), 0),
    profit_plan_minor: successful.reduce((sum, row) => sum + Number(row.plan?.profit_plan_minor || 0), 0),
  };
  state.integrations = successful.flatMap((row) => row.integrations || []);
  state.integrationQuality = successful.flatMap((row) => row.quality || []);
  state.economics = null; state.payroll = null; state.reports = [];
}

function renderAll() {
  renderWidgets(); renderAttention(); renderTrend(); renderOperations(); renderNetwork(); renderQuickActions();
}

async function loadDashboard() {
  const revision = ++state.loadRevision;
  state.sourceErrors = [];
  document.getElementById("dashboardWidgetGrid")?.setAttribute("aria-busy", "true");
  setDashboardState();
  try {
    if (state.scope === "network") await loadNetworkDashboard(revision);
    else await loadVenueDashboard(revision);
    if (revision !== state.loadRevision) return;
    state.financialValuesHidden = state.financialValuesHidden || isFinancialValuesHidden(state.monthData);
    renderAll();
  } catch (error) {
    if (revision !== state.loadRevision) return;
    document.getElementById("dashboardWidgetGrid")?.setAttribute("aria-busy", "false");
    setDashboardState("Не удалось загрузить показатели", error?.data?.detail || error?.message || "Попробуйте обновить страницу.");
  }
}

function bindConfigEvents() {
  const config = document.getElementById("dashboardConfig");
  const button = document.getElementById("configureDashboardBtn");
  button?.addEventListener("click", () => {
    const willOpen = config?.classList.contains("hidden");
    config?.classList.toggle("hidden", !willOpen); button.setAttribute("aria-expanded", String(Boolean(willOpen))); button.textContent = willOpen ? "Готово" : "Настроить";
  });
  config?.addEventListener("change", (event) => {
    const toggle = event.target.closest("[data-config-toggle]");
    if (toggle) {
      const next = toggle.dataset.configKind === "action" ? toggleDashboardAction(state.layout, toggle.dataset.configToggle, toggle.checked) : toggleDashboardWidget(state.layout, toggle.dataset.configToggle, toggle.checked);
      if (JSON.stringify(next) === JSON.stringify(state.layout)) { toggle.checked = true; toast("Оставьте хотя бы один элемент", "err"); return; }
      persistAndRender(next); return;
    }
    const size = event.target.closest("[data-widget-size]");
    if (size) persistAndRender(setDashboardWidgetSize(state.layout, size.dataset.widgetSize, size.value));
  });
  config?.addEventListener("click", (event) => {
    const move = event.target.closest("[data-config-move]");
    if (move) {
      const next = move.dataset.configKind === "action" ? moveDashboardAction(state.layout, move.dataset.configMove, move.dataset.direction) : moveDashboardWidget(state.layout, move.dataset.configMove, move.dataset.direction);
      persistAndRender(next); return;
    }
    const preset = event.target.closest("[data-dashboard-preset]");
    if (preset) { state.undoLayout = state.layout; persistAndRender(applyDashboardPreset(state.layout, preset.dataset.dashboardPreset)); document.getElementById("undoDashboardBtn")?.classList.remove("hidden"); }
  });
  let draggedWidget = "";
  config?.addEventListener("dragstart", (event) => { const row = event.target.closest("[data-drag-widget]"); if (!row) return; draggedWidget = row.dataset.dragWidget; row.classList.add("is-dragging"); });
  config?.addEventListener("dragend", (event) => { event.target.closest("[data-drag-widget]")?.classList.remove("is-dragging"); draggedWidget = ""; });
  config?.addEventListener("dragover", (event) => { if (draggedWidget && event.target.closest("[data-drag-widget]")) event.preventDefault(); });
  config?.addEventListener("drop", (event) => { const target = event.target.closest("[data-drag-widget]"); if (!target || !draggedWidget) return; event.preventDefault(); persistAndRender(reorderDashboardWidget(state.layout, draggedWidget, target.dataset.dragWidget)); });
  document.getElementById("resetDashboardBtn")?.addEventListener("click", () => { state.undoLayout = state.layout; persistAndRender(resetDashboardLayout()); document.getElementById("undoDashboardBtn")?.classList.remove("hidden"); toast("Виджеты возвращены к исходному виду"); });
  document.getElementById("undoDashboardBtn")?.addEventListener("click", () => { if (!state.undoLayout) return; persistAndRender(state.undoLayout); state.undoLayout = null; document.getElementById("undoDashboardBtn")?.classList.add("hidden"); });
}

function bindDashboardControls() {
  bindConfigEvents();
  const periodPicker = document.getElementById("dashboardPeriodPicker");
  if (periodPicker) {
    periodPicker.dataset.periodValue = state.month === currentMonth()
      ? "this_month"
      : (state.month === previousMonth(currentMonth()) ? "previous_month" : "custom");
    periodPicker.addEventListener("axelio:period-change", async (event) => {
      const detail = event.detail || {};
      state.month = coerceDemoMonth(detail.month || String(detail.from || state.month || currentMonth()).slice(0, 7), { context: "owner-dashboard" });
      const label = periodPicker.querySelector("[data-period-label]");
      if (label) label.textContent = monthLabel(state.month);
      renderQuickActions();
      await loadDashboard();
    });
  }
  const scope = document.getElementById("dashboardScope");
  scope?.addEventListener("change", async (event) => { state.scope = event.target.value === "network" ? "network" : "venue"; await loadDashboard(); });
  document.getElementById("dashboardTrendSwitch")?.addEventListener("click", (event) => { const button = event.target.closest("[data-trend]"); if (!button) return; state.trendMetric = button.dataset.trend; document.querySelectorAll("#dashboardTrendSwitch button").forEach((item) => item.classList.toggle("active", item === button)); renderTrend(); });
}

async function boot() {
  applyTelegramTheme(); mountCommonUI("dashboard"); await ensureLogin({ silent: true });
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (!venueId) { location.replace("/app-venues.html"); return; }
  state.venueId = String(venueId); setActiveVenueId(state.venueId);
  state.month = coerceDemoMonth(params.get("month") || currentMonth(), { notify: false, context: "owner-dashboard" });
  state.layout = loadDashboardLayout(state.venueId, globalThis.localStorage, state.deviceKind);
  await mountNav({ activeTab: "dashboard", requireVenue: true });
  try {
    const [permissions, venues, me] = await Promise.all([getMyVenuePermissions(state.venueId), getMyVenues(), getMe()]);
    const role = roleUpper(permissions);
    if (!hasOwnerDashboardAccess(permSetFromResponse(permissions), role, String(me?.system_role || ""))) { location.replace(`/app-dashboard.html?venue_id=${encodeURIComponent(state.venueId)}`); return; }
    state.financialValuesHidden = isFinancialValuesHidden(permissions);
    state.ownerVenues = venues.filter((item) => String(item.my_role || item.role || "").toUpperCase().includes("OWNER"));
    const venue = venues.find((item) => String(item.id) === state.venueId);
    if (venue) document.getElementById("subtitle").textContent = venue.name || "главное по заведению";
    const scope = document.getElementById("dashboardScope");
    if (scope && state.ownerVenues.length > 1) scope.classList.remove("hidden");
  } catch (error) { setDashboardState("Нет доступа к дашборду", error?.data?.detail || error?.message || "Проверьте доступ к заведению."); return; }
  document.getElementById("dashboardPeriodLabel").textContent = monthLabel(state.month);
  renderConfig(); renderQuickActions(); bindDashboardControls(); await loadDashboard();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

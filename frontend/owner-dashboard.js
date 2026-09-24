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
  coerceDemoMonth,
} from "/app.js?v=20260820-i18nmetrika1";
import { isOwnerRole, roleUpper, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js?v=20260503-finprivacy1";
import {
  loadDashboardLayout,
  saveDashboardLayout,
  toggleDashboardWidget,
  moveDashboardWidget,
  resetDashboardLayout,
} from "/owner-dashboard-config.js?v=20260924-owner-dashboard1";

const WIDGETS = Object.freeze({
  revenue_today: { title: "Выручка сегодня", hint: "По закрытым отчётам за день", source: "day", field: "revenue_minor", format: "money", target: "turnover" },
  revenue_month: { title: "Выручка за месяц", hint: "С начала выбранного месяца", source: "month", field: "revenue_minor", format: "money", target: "turnover" },
  profit_month: { title: "Прибыль за месяц", hint: "После расходов и ФОТ", source: "month", field: "profit_minor", format: "money", target: "summary" },
  expenses_month: { title: "Расходы за месяц", hint: "Подтверждённые, без ФОТ", source: "month", field: "expense_without_payroll_minor", format: "money", target: "expenses" },
  payroll_month: { title: "ФОТ за месяц", hint: "Начисления команды", source: "month", field: "payroll_minor", format: "money", target: "payroll" },
  margin_month: { title: "Маржинальность", hint: "Доля прибыли от выручки", source: "month", field: "margin_bps", format: "percent", target: "summary" },
});

const state = {
  venueId: "",
  month: "",
  layout: null,
  monthData: null,
  dayData: null,
  financialValuesHidden: false,
};

function todayISO() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

function currentMonth() {
  return coerceDemoMonth(todayISO().slice(0, 7), { notify: false, context: "owner-dashboard" });
}

function formatMoneyMinor(value) {
  if (state.financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  if (value === null || value === undefined) return "Недоступно";
  const rubles = Number(value || 0) / 100;
  try {
    return `${new Intl.NumberFormat(globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU", { maximumFractionDigits: 0 }).format(rubles)} ₽`;
  } catch {
    return `${Math.round(rubles)} ₽`;
  }
}

function formatPercentBps(value) {
  if (state.financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  if (value === null || value === undefined) return "Недоступно";
  try {
    return `${new Intl.NumberFormat(globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU", { maximumFractionDigits: 1 }).format(Number(value || 0) / 100)}%`;
  } catch {
    return `${(Number(value || 0) / 100).toFixed(1)}%`;
  }
}

function monthLabel(month) {
  const [year, monthNumber] = String(month || "").split("-").map(Number);
  if (!year || !monthNumber) return "Текущий месяц";
  try {
    const value = new Intl.DateTimeFormat(globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU", { month: "long", year: "numeric", timeZone: "UTC" })
      .format(new Date(Date.UTC(year, monthNumber - 1, 1)));
    return value.charAt(0).toUpperCase() + value.slice(1);
  } catch {
    return String(month);
  }
}

function hrefFor(target) {
  const query = new URLSearchParams({ venue_id: state.venueId, month: state.month });
  const paths = {
    turnover: "/owner-turnover.html",
    summary: "/owner-summary.html",
    expenses: "/owner-expenses.html",
    payroll: "/owner-payroll.html",
    report: "/staff-report.html",
    venue: "/app-venue.html",
  };
  return `${paths[target] || paths.summary}?${query.toString()}`;
}

function createWidgetCard(widgetId) {
  const definition = WIDGETS[widgetId];
  const data = definition.source === "day" ? state.dayData : state.monthData;
  const rawValue = data?.[definition.field];
  const formatted = definition.format === "percent" ? formatPercentBps(rawValue) : formatMoneyMinor(rawValue);
  const card = document.createElement("a");
  card.className = "itemcard owner-dashboard-widget";
  card.href = hrefFor(definition.target);
  card.dataset.widgetId = widgetId;

  const label = document.createElement("div");
  label.className = "owner-dashboard-widget__label";
  label.textContent = definition.title;
  const value = document.createElement("div");
  value.className = "owner-dashboard-widget__value";
  value.textContent = formatted;
  const meta = document.createElement("div");
  meta.className = "owner-dashboard-widget__meta";
  const hint = document.createElement("span");
  hint.textContent = definition.hint;
  const arrow = document.createElement("span");
  arrow.className = "owner-dashboard-widget__arrow";
  arrow.textContent = "→";
  meta.append(hint, arrow);
  card.append(label, value, meta);
  return card;
}

function renderWidgets() {
  const grid = document.getElementById("dashboardWidgetGrid");
  if (!grid || !state.layout) return;
  const hidden = new Set(state.layout.hidden);
  grid.replaceChildren(...state.layout.order.filter((widgetId) => !hidden.has(widgetId)).map(createWidgetCard));
  grid.setAttribute("aria-busy", "false");
}

function renderConfig() {
  const list = document.getElementById("dashboardConfigList");
  if (!list || !state.layout) return;
  const hidden = new Set(state.layout.hidden);
  list.replaceChildren();

  state.layout.order.forEach((widgetId, index) => {
    const definition = WIDGETS[widgetId];
    const row = document.createElement("div");
    row.className = "owner-dashboard-config__row";
    const label = document.createElement("label");
    label.className = "owner-dashboard-config__toggle";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = !hidden.has(widgetId);
    checkbox.dataset.widgetToggle = widgetId;
    const text = document.createElement("span");
    text.textContent = definition.title;
    label.append(checkbox, text);

    const controls = document.createElement("div");
    controls.className = "owner-dashboard-config__move";
    const up = document.createElement("button");
    up.className = "btn sm subtle";
    up.type = "button";
    up.textContent = "↑";
    up.title = "Поднять виджет";
    up.setAttribute("aria-label", `Поднять: ${definition.title}`);
    up.dataset.widgetMove = widgetId;
    up.dataset.direction = "up";
    up.disabled = index === 0;
    const down = document.createElement("button");
    down.className = "btn sm subtle";
    down.type = "button";
    down.textContent = "↓";
    down.title = "Опустить виджет";
    down.setAttribute("aria-label", `Опустить: ${definition.title}`);
    down.dataset.widgetMove = widgetId;
    down.dataset.direction = "down";
    down.disabled = index === state.layout.order.length - 1;
    controls.append(up, down);
    row.append(label, controls);
    list.append(row);
  });
}

function persistAndRender(layout) {
  state.layout = saveDashboardLayout(state.venueId, layout);
  renderWidgets();
  renderConfig();
}

function renderQuickActions() {
  const container = document.getElementById("dashboardActions");
  if (!container) return;
  const items = [
    { title: "Добавить расход", icon: "+", target: "expenses", primary: true, action: "add" },
    { title: "Расходы", icon: "₽", target: "expenses" },
    { title: "Полная сводка", icon: "∑", target: "summary" },
    { title: "Выручка", icon: "↗", target: "turnover" },
    { title: "Начисления", icon: "◎", target: "payroll" },
    { title: "Отчёт дня", icon: "✓", target: "report" },
    { title: "Заведение", icon: "⌂", target: "venue" },
  ];
  container.replaceChildren(...items.map((item) => {
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

function setDashboardState(title = "", text = "") {
  const card = document.getElementById("dashboardState");
  const visible = Boolean(title || text);
  card?.classList.toggle("hidden", !visible);
  const titleNode = document.getElementById("dashboardStateTitle");
  const textNode = document.getElementById("dashboardStateText");
  if (titleNode) titleNode.textContent = title;
  if (textNode) textNode.textContent = text;
}

async function loadDashboard() {
  const grid = document.getElementById("dashboardWidgetGrid");
  grid?.setAttribute("aria-busy", "true");
  setDashboardState();
  const day = todayISO();
  try {
    const [monthData, dayData] = await Promise.all([
      api(`/venues/${encodeURIComponent(state.venueId)}/finance/summary?month=${encodeURIComponent(state.month)}`),
      api(`/venues/${encodeURIComponent(state.venueId)}/finance/summary?date_from=${encodeURIComponent(day)}&date_to=${encodeURIComponent(day)}`),
    ]);
    state.monthData = monthData;
    state.dayData = dayData;
    state.financialValuesHidden = state.financialValuesHidden || isFinancialValuesHidden(monthData) || isFinancialValuesHidden(dayData);
    renderWidgets();
  } catch (error) {
    grid?.setAttribute("aria-busy", "false");
    setDashboardState("Не удалось загрузить показатели", error?.data?.detail || error?.message || "Попробуйте обновить страницу.");
  }
}

function bindControls() {
  const configureButton = document.getElementById("configureDashboardBtn");
  const config = document.getElementById("dashboardConfig");
  configureButton?.addEventListener("click", () => {
    const willOpen = config?.classList.contains("hidden");
    config?.classList.toggle("hidden", !willOpen);
    configureButton.setAttribute("aria-expanded", String(Boolean(willOpen)));
    configureButton.textContent = willOpen ? "Готово" : "Настроить";
  });

  document.getElementById("dashboardConfigList")?.addEventListener("change", (event) => {
    const input = event.target.closest("[data-widget-toggle]");
    if (!input) return;
    const next = toggleDashboardWidget(state.layout, input.dataset.widgetToggle, input.checked);
    if (JSON.stringify(next) === JSON.stringify(state.layout)) {
      input.checked = true;
      toast("Оставьте хотя бы один показатель", "err");
      return;
    }
    persistAndRender(next);
  });

  document.getElementById("dashboardConfigList")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-widget-move]");
    if (!button) return;
    persistAndRender(moveDashboardWidget(state.layout, button.dataset.widgetMove, button.dataset.direction));
  });

  document.getElementById("resetDashboardBtn")?.addEventListener("click", () => {
    persistAndRender(resetDashboardLayout());
    toast("Виджеты возвращены к исходному виду");
  });

  const monthPick = document.getElementById("dashboardMonthPick");
  if (monthPick) {
    monthPick.value = state.month;
    monthPick.addEventListener("change", async (event) => {
      state.month = coerceDemoMonth(event.target.value || currentMonth(), { context: "owner-dashboard" });
      event.target.value = state.month;
      document.getElementById("dashboardPeriodLabel").textContent = monthLabel(state.month);
      renderQuickActions();
      await loadDashboard();
    });
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("dashboard");
  await ensureLogin({ silent: true });
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (!venueId) {
    location.replace("/app-venues.html");
    return;
  }
  state.venueId = String(venueId);
  setActiveVenueId(state.venueId);
  state.month = coerceDemoMonth(params.get("month") || currentMonth(), { notify: false, context: "owner-dashboard" });
  state.layout = loadDashboardLayout(state.venueId);

  await mountNav({ activeTab: "dashboard", requireVenue: true });
  try {
    const [permissions, venues] = await Promise.all([getMyVenuePermissions(state.venueId), getMyVenues()]);
    if (!isOwnerRole(roleUpper(permissions))) {
      location.replace(`/app-dashboard.html?venue_id=${encodeURIComponent(state.venueId)}`);
      return;
    }
    state.financialValuesHidden = isFinancialValuesHidden(permissions);
    const venue = venues.find((item) => String(item.id) === state.venueId);
    if (venue) document.getElementById("subtitle").textContent = venue.name || "главное по заведению";
  } catch (error) {
    setDashboardState("Нет доступа к дашборду", error?.data?.detail || error?.message || "Проверьте доступ к заведению.");
    return;
  }

  document.getElementById("dashboardPeriodLabel").textContent = monthLabel(state.month);
  renderWidgets();
  renderConfig();
  renderQuickActions();
  bindControls();
  await loadDashboard();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

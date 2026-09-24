export const DASHBOARD_LAYOUT_VERSION = 2;

export const DASHBOARD_WIDGET_IDS = Object.freeze([
  "revenue_today", "revenue_month", "profit_month", "expenses_month", "payroll_month", "margin_month",
  "revenue_plan", "profit_forecast", "shifts_today", "top_department", "integration_health",
]);

export const DASHBOARD_ACTION_IDS = Object.freeze([
  "add_expense", "expenses", "summary", "turnover", "payroll", "report", "schedule", "integrations", "venue",
]);

const DEFAULT_VISIBLE_WIDGETS = Object.freeze([
  "revenue_today", "revenue_month", "profit_month", "expenses_month", "payroll_month", "margin_month",
  "revenue_plan", "profit_forecast",
]);
const DEFAULT_VISIBLE_ACTIONS = Object.freeze([
  "add_expense", "expenses", "summary", "turnover", "payroll", "report", "venue",
]);

export const DEFAULT_DASHBOARD_LAYOUT = Object.freeze({
  order: Object.freeze([...DASHBOARD_WIDGET_IDS]),
  hidden: Object.freeze(DASHBOARD_WIDGET_IDS.filter((id) => !DEFAULT_VISIBLE_WIDGETS.includes(id))),
  sizes: Object.freeze({ revenue_month: "wide", revenue_plan: "wide" }),
  actionOrder: Object.freeze([...DASHBOARD_ACTION_IDS]),
  hiddenActions: Object.freeze(DASHBOARD_ACTION_IDS.filter((id) => !DEFAULT_VISIBLE_ACTIONS.includes(id))),
});

export const DASHBOARD_PRESETS = Object.freeze({
  finance: Object.freeze({
    visible: Object.freeze(["revenue_today", "revenue_month", "profit_month", "expenses_month", "payroll_month", "margin_month", "revenue_plan", "profit_forecast"]),
    sizes: Object.freeze({ revenue_month: "wide", revenue_plan: "wide" }),
  }),
  operations: Object.freeze({
    visible: Object.freeze(["revenue_today", "shifts_today", "top_department", "expenses_month", "payroll_month", "revenue_plan"]),
    sizes: Object.freeze({ revenue_today: "wide", shifts_today: "compact" }),
  }),
  integrations: Object.freeze({
    visible: Object.freeze(["revenue_today", "revenue_month", "integration_health", "top_department", "profit_month"]),
    sizes: Object.freeze({ integration_health: "wide", revenue_month: "wide" }),
  }),
});

function uniqueKnownIds(values, knownValues) {
  const known = new Set(knownValues);
  return Array.from(new Set(Array.isArray(values) ? values : []))
    .map((value) => String(value || "").trim())
    .filter((value) => known.has(value));
}

function completeOrder(values, knownValues) {
  const order = uniqueKnownIds(values, knownValues);
  for (const id of knownValues) if (!order.includes(id)) order.push(id);
  return order;
}

function normalizedHidden(values, order) {
  const requested = new Set(uniqueKnownIds(values, order));
  const hidden = order.filter((id) => requested.has(id));
  if (hidden.length >= order.length) hidden.pop();
  return hidden;
}

function normalizeSizes(value) {
  const sizes = {};
  for (const widgetId of DASHBOARD_WIDGET_IDS) {
    const requested = String(value?.[widgetId] || DEFAULT_DASHBOARD_LAYOUT.sizes?.[widgetId] || "normal");
    sizes[widgetId] = ["compact", "normal", "wide"].includes(requested) ? requested : "normal";
  }
  return sizes;
}

export function normalizeDashboardLayout(value) {
  const order = completeOrder(value?.order, DASHBOARD_WIDGET_IDS);
  const actionOrder = completeOrder(value?.actionOrder, DASHBOARD_ACTION_IDS);
  return {
    order,
    hidden: normalizedHidden(value?.hidden, order),
    sizes: normalizeSizes(value?.sizes),
    actionOrder,
    hiddenActions: normalizedHidden(value?.hiddenActions, actionOrder),
  };
}

export function dashboardDeviceKind(width = globalThis.innerWidth) {
  return Number(width || 0) <= 760 ? "mobile" : "desktop";
}

export function dashboardLayoutStorageKey(venueId, deviceKind = dashboardDeviceKind()) {
  return `axelio.owner_dashboard.v${DASHBOARD_LAYOUT_VERSION}.${String(venueId || "default")}.${deviceKind}`;
}

function legacyStorageKey(venueId) {
  return `axelio.owner_dashboard.v1.${String(venueId || "default")}`;
}

export function loadDashboardLayout(venueId, storage = globalThis.localStorage, deviceKind = dashboardDeviceKind()) {
  try {
    const key = dashboardLayoutStorageKey(venueId, deviceKind);
    const raw = storage?.getItem?.(key);
    if (raw) return normalizeDashboardLayout(JSON.parse(raw));
    const legacyRaw = storage?.getItem?.(legacyStorageKey(venueId));
    const migrated = normalizeDashboardLayout(legacyRaw ? JSON.parse(legacyRaw) : DEFAULT_DASHBOARD_LAYOUT);
    storage?.setItem?.(key, JSON.stringify(migrated));
    return migrated;
  } catch {
    return normalizeDashboardLayout(DEFAULT_DASHBOARD_LAYOUT);
  }
}

export function saveDashboardLayout(venueId, layout, storage = globalThis.localStorage, deviceKind = dashboardDeviceKind()) {
  const normalized = normalizeDashboardLayout(layout);
  try { storage?.setItem?.(dashboardLayoutStorageKey(venueId, deviceKind), JSON.stringify(normalized)); } catch {}
  return normalized;
}

function toggleItem(layout, id, visible, hiddenKey, knownValues) {
  const normalized = normalizeDashboardLayout(layout);
  if (!knownValues.includes(id)) return normalized;
  const hidden = new Set(normalized[hiddenKey]);
  if (visible) hidden.delete(id);
  else hidden.add(id);
  if (hidden.size >= knownValues.length) return normalized;
  return normalizeDashboardLayout({ ...normalized, [hiddenKey]: Array.from(hidden) });
}

export function toggleDashboardWidget(layout, widgetId, visible) {
  return toggleItem(layout, String(widgetId || ""), visible, "hidden", DASHBOARD_WIDGET_IDS);
}

export function toggleDashboardAction(layout, actionId, visible) {
  return toggleItem(layout, String(actionId || ""), visible, "hiddenActions", DASHBOARD_ACTION_IDS);
}

function moveItem(layout, id, direction, orderKey) {
  const normalized = normalizeDashboardLayout(layout);
  const order = [...normalized[orderKey]];
  const currentIndex = order.indexOf(String(id || ""));
  const offset = direction === "up" ? -1 : direction === "down" ? 1 : 0;
  const nextIndex = currentIndex + offset;
  if (currentIndex < 0 || offset === 0 || nextIndex < 0 || nextIndex >= order.length) return normalized;
  [order[currentIndex], order[nextIndex]] = [order[nextIndex], order[currentIndex]];
  return normalizeDashboardLayout({ ...normalized, [orderKey]: order });
}

export function moveDashboardWidget(layout, widgetId, direction) {
  return moveItem(layout, widgetId, direction, "order");
}

export function moveDashboardAction(layout, actionId, direction) {
  return moveItem(layout, actionId, direction, "actionOrder");
}

export function reorderDashboardWidget(layout, widgetId, targetWidgetId) {
  const normalized = normalizeDashboardLayout(layout);
  const sourceIndex = normalized.order.indexOf(widgetId);
  const targetIndex = normalized.order.indexOf(targetWidgetId);
  if (!DASHBOARD_WIDGET_IDS.includes(widgetId) || sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return normalized;
  const order = normalized.order.filter((id) => id !== widgetId);
  order.splice(targetIndex, 0, widgetId);
  return normalizeDashboardLayout({ ...normalized, order });
}

export function setDashboardWidgetSize(layout, widgetId, size) {
  const normalized = normalizeDashboardLayout(layout);
  if (!DASHBOARD_WIDGET_IDS.includes(widgetId) || !["compact", "normal", "wide"].includes(size)) return normalized;
  return normalizeDashboardLayout({ ...normalized, sizes: { ...normalized.sizes, [widgetId]: size } });
}

export function applyDashboardPreset(layout, presetId) {
  const preset = DASHBOARD_PRESETS[presetId];
  if (!preset) return normalizeDashboardLayout(layout);
  return normalizeDashboardLayout({
    ...layout,
    hidden: DASHBOARD_WIDGET_IDS.filter((id) => !preset.visible.includes(id)),
    sizes: { ...DEFAULT_DASHBOARD_LAYOUT.sizes, ...preset.sizes },
  });
}

export function resetDashboardLayout() {
  return normalizeDashboardLayout(DEFAULT_DASHBOARD_LAYOUT);
}

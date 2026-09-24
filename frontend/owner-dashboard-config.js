export const DASHBOARD_LAYOUT_VERSION = 1;

export const DASHBOARD_WIDGET_IDS = Object.freeze([
  "revenue_today",
  "revenue_month",
  "profit_month",
  "expenses_month",
  "payroll_month",
  "margin_month",
]);

export const DEFAULT_DASHBOARD_LAYOUT = Object.freeze({
  order: Object.freeze([...DASHBOARD_WIDGET_IDS]),
  hidden: Object.freeze([]),
});

function uniqueKnownWidgetIds(values) {
  const known = new Set(DASHBOARD_WIDGET_IDS);
  return Array.from(new Set(Array.isArray(values) ? values : []))
    .map((value) => String(value || "").trim())
    .filter((value) => known.has(value));
}

export function normalizeDashboardLayout(value) {
  const order = uniqueKnownWidgetIds(value?.order);
  for (const widgetId of DASHBOARD_WIDGET_IDS) {
    if (!order.includes(widgetId)) order.push(widgetId);
  }

  const requestedHidden = new Set(uniqueKnownWidgetIds(value?.hidden));
  const hidden = order.filter((widgetId) => requestedHidden.has(widgetId));
  if (hidden.length >= order.length) hidden.pop();
  return { order, hidden };
}

export function dashboardLayoutStorageKey(venueId) {
  return `axelio.owner_dashboard.v${DASHBOARD_LAYOUT_VERSION}.${String(venueId || "default")}`;
}

export function loadDashboardLayout(venueId, storage = globalThis.localStorage) {
  try {
    const raw = storage?.getItem?.(dashboardLayoutStorageKey(venueId));
    return normalizeDashboardLayout(raw ? JSON.parse(raw) : DEFAULT_DASHBOARD_LAYOUT);
  } catch {
    return normalizeDashboardLayout(DEFAULT_DASHBOARD_LAYOUT);
  }
}

export function saveDashboardLayout(venueId, layout, storage = globalThis.localStorage) {
  const normalized = normalizeDashboardLayout(layout);
  try { storage?.setItem?.(dashboardLayoutStorageKey(venueId), JSON.stringify(normalized)); } catch {}
  return normalized;
}

export function toggleDashboardWidget(layout, widgetId, visible) {
  const normalized = normalizeDashboardLayout(layout);
  const id = String(widgetId || "");
  if (!DASHBOARD_WIDGET_IDS.includes(id)) return normalized;
  const hidden = new Set(normalized.hidden);
  if (visible) hidden.delete(id);
  else hidden.add(id);
  if (hidden.size >= DASHBOARD_WIDGET_IDS.length) return normalized;
  return normalizeDashboardLayout({ ...normalized, hidden: Array.from(hidden) });
}

export function moveDashboardWidget(layout, widgetId, direction) {
  const normalized = normalizeDashboardLayout(layout);
  const order = [...normalized.order];
  const currentIndex = order.indexOf(String(widgetId || ""));
  const offset = direction === "up" ? -1 : direction === "down" ? 1 : 0;
  const nextIndex = currentIndex + offset;
  if (currentIndex < 0 || offset === 0 || nextIndex < 0 || nextIndex >= order.length) return normalized;
  [order[currentIndex], order[nextIndex]] = [order[nextIndex], order[currentIndex]];
  return normalizeDashboardLayout({ ...normalized, order });
}

export function resetDashboardLayout() {
  return normalizeDashboardLayout(DEFAULT_DASHBOARD_LAYOUT);
}

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  DASHBOARD_WIDGET_IDS,
  DASHBOARD_ACTION_IDS,
  DEFAULT_DASHBOARD_LAYOUT,
  applyDashboardPreset,
  dashboardLayoutStorageKey,
  loadDashboardLayout,
  moveDashboardWidget,
  normalizeDashboardLayout,
  reorderDashboardWidget,
  saveDashboardLayout,
  setDashboardWidgetSize,
  toggleDashboardAction,
  toggleDashboardWidget,
} from "./owner-dashboard-config.js";
import { hasOwnerDashboardAccess } from "./permissions.js";
import { createUiPreferences } from "./app/ui-preferences.js";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const read = (fileName) => fs.readFileSync(path.join(frontendDir, fileName), "utf8");

assert.equal(DASHBOARD_WIDGET_IDS.length, 11);
assert.equal(DASHBOARD_ACTION_IDS.length, 9);
assert.deepEqual(normalizeDashboardLayout({ order: ["profit_month", "unknown", "profit_month"], hidden: ["unknown"] }).order, [
  "profit_month", "revenue_today", "revenue_month", "expenses_month", "payroll_month", "margin_month",
  "revenue_plan", "profit_forecast", "shifts_today", "top_department", "integration_health",
]);
assert.equal(toggleDashboardWidget(DEFAULT_DASHBOARD_LAYOUT, "revenue_today", false).hidden.includes("revenue_today"), true);
let layout = DEFAULT_DASHBOARD_LAYOUT;
for (const widgetId of DASHBOARD_WIDGET_IDS) layout = toggleDashboardWidget(layout, widgetId, false);
assert.equal(layout.hidden.length, DASHBOARD_WIDGET_IDS.length - 1, "dashboard must keep at least one visible widget");
assert.equal(moveDashboardWidget(DEFAULT_DASHBOARD_LAYOUT, "revenue_month", "up").order[0], "revenue_month");
assert.equal(reorderDashboardWidget(DEFAULT_DASHBOARD_LAYOUT, "margin_month", "revenue_today").order[0], "margin_month");
assert.equal(reorderDashboardWidget(DEFAULT_DASHBOARD_LAYOUT, "revenue_today", "revenue_month").order[1], "revenue_today");
assert.equal(setDashboardWidgetSize(DEFAULT_DASHBOARD_LAYOUT, "revenue_today", "wide").sizes.revenue_today, "wide");
assert.equal(applyDashboardPreset(DEFAULT_DASHBOARD_LAYOUT, "operations").hidden.includes("shifts_today"), false);
assert.equal(toggleDashboardAction(DEFAULT_DASHBOARD_LAYOUT, "schedule", true).hiddenActions.includes("schedule"), false);
assert.equal(hasOwnerDashboardAccess(new Set(), "OWNER", ""), true);
assert.equal(hasOwnerDashboardAccess(new Set(["REVENUE_VIEW"]), "STAFF", ""), true);
assert.equal(hasOwnerDashboardAccess(new Set(["EXPENSE_VIEW"]), "STAFF", ""), true);
assert.equal(hasOwnerDashboardAccess(new Set(["PAYROLL_VIEW"]), "STAFF", ""), true);
assert.equal(hasOwnerDashboardAccess(new Set(["EXPENSE_ADD"]), "STAFF", ""), false);
assert.equal(hasOwnerDashboardAccess(new Set(["REPORTS_VIEW_DAILY"]), "STAFF", ""), false);
globalThis.window = { AxelioI18n: { getLocale: () => "ru" } };
const uiPreferences = createUiPreferences();
assert.equal(uiPreferences.t("dashboard"), "Дашборд");
globalThis.window.AxelioI18n.getLocale = () => "en";
assert.equal(uiPreferences.t("dashboard"), "Dashboard");
delete globalThis.window;

const memoryStorage = new Map();
const storage = { getItem: (key) => memoryStorage.get(key) || null, setItem: (key, value) => memoryStorage.set(key, value) };
saveDashboardLayout(21, { order: ["margin_month"], hidden: ["payroll_month"] }, storage, "mobile");
assert.equal(loadDashboardLayout(21, storage, "mobile").order[0], "margin_month");
assert.ok(memoryStorage.has(dashboardLayoutStorageKey(21, "mobile")));

const html = read("owner-dashboard.html");
const script = read("owner-dashboard.js");
const app = read("app.js");
const navigation = read("app/navigation.js");
const preferences = read("app/ui-preferences.js");
const index = read("index.html");
const expenses = read("owner-expenses.js");
const venue = read("app-venue.html");
assert.match(html, /id="dashboardWidgetGrid"/);
assert.match(html, /<main class="card owner-dashboard-content">/);
assert.match(html, /id="dashboardConfigList"/);
assert.match(html, /id="dashboardAttentionList"/);
assert.match(html, /id="dashboardTrendChart"/);
assert.match(html, /id="dashboardNetworkList"/);
assert.match(script, /finance\/summary\?month=/);
assert.match(script, /action", item\.action/);
assert.match(script, /quality-summary/);
assert.match(script, /economics\/day/);
assert.match(script, /hasOwnerDashboardAccess\(permSetFromResponse\(permissions\), role/);
assert.match(html, /owner-dashboard\.js\?v=20260924-dashboardi18n1/);
assert.match(script, /app\.js\?v=20260924-dashboardi18n1/);
assert.match(app, /app\/navigation\.js\?v=20260924-dashboardi18n1/);
assert.match(app, /app\/ui-preferences\.js\?v=20260924-dashboardi18n1/);
assert.match(navigation, /title: t\("dashboard"\).*owner-dashboard\.html/s);
assert.doesNotMatch(navigation, /owner-summary\.html/);
assert.match(preferences, /dashboard: "Дашборд"/);
assert.match(preferences, /dashboard: "Dashboard"/);
assert.match(index, /owner-dashboard\.html/);
assert.match(expenses, /params\.get\("action"\) === "add"/);
assert.match(venue, /id="openDashboard"/);
assert.match(venue, /openDashboard\.href = `\/owner-dashboard\.html\?venue_id=/);
assert.match(venue, /setVisible\(openDashboard, canViewDashboard\)/);

console.log("owner dashboard contract checks passed");

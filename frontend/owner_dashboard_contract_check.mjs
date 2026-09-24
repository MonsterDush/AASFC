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

const memoryStorage = new Map();
const storage = { getItem: (key) => memoryStorage.get(key) || null, setItem: (key, value) => memoryStorage.set(key, value) };
saveDashboardLayout(21, { order: ["margin_month"], hidden: ["payroll_month"] }, storage, "mobile");
assert.equal(loadDashboardLayout(21, storage, "mobile").order[0], "margin_month");
assert.ok(memoryStorage.has(dashboardLayoutStorageKey(21, "mobile")));

const html = read("owner-dashboard.html");
const script = read("owner-dashboard.js");
const app = read("app.js");
const navigation = read("app/navigation.js");
const index = read("index.html");
const expenses = read("owner-expenses.js");
assert.match(html, /id="dashboardWidgetGrid"/);
assert.match(html, /id="dashboardConfigList"/);
assert.match(html, /id="dashboardAttentionList"/);
assert.match(html, /id="dashboardTrendChart"/);
assert.match(html, /id="dashboardNetworkList"/);
assert.match(script, /finance\/summary\?month=/);
assert.match(script, /action", item\.action/);
assert.match(script, /quality-summary/);
assert.match(script, /economics\/day/);
assert.match(html, /owner-dashboard\.js\?v=20260924-dashboardnav1/);
assert.match(script, /app\.js\?v=20260924-dashboardnav1/);
assert.match(app, /app\/navigation\.js\?v=20260924-dashboardnav1/);
assert.match(navigation, /title: t\("dashboard"\).*owner-dashboard\.html/s);
assert.doesNotMatch(navigation, /owner-summary\.html/);
assert.match(index, /owner-dashboard\.html/);
assert.match(expenses, /params\.get\("action"\) === "add"/);

console.log("owner dashboard contract checks passed");

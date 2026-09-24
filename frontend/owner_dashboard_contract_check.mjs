import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  DASHBOARD_WIDGET_IDS,
  DEFAULT_DASHBOARD_LAYOUT,
  dashboardLayoutStorageKey,
  loadDashboardLayout,
  moveDashboardWidget,
  normalizeDashboardLayout,
  saveDashboardLayout,
  toggleDashboardWidget,
} from "./owner-dashboard-config.js";

const frontendDir = path.dirname(fileURLToPath(import.meta.url));
const read = (fileName) => fs.readFileSync(path.join(frontendDir, fileName), "utf8");

assert.equal(DASHBOARD_WIDGET_IDS.length, 6);
assert.deepEqual(normalizeDashboardLayout({ order: ["profit_month", "unknown", "profit_month"], hidden: ["unknown"] }).order, [
  "profit_month", "revenue_today", "revenue_month", "expenses_month", "payroll_month", "margin_month",
]);
assert.equal(toggleDashboardWidget(DEFAULT_DASHBOARD_LAYOUT, "revenue_today", false).hidden.includes("revenue_today"), true);
let layout = DEFAULT_DASHBOARD_LAYOUT;
for (const widgetId of DASHBOARD_WIDGET_IDS) layout = toggleDashboardWidget(layout, widgetId, false);
assert.equal(layout.hidden.length, DASHBOARD_WIDGET_IDS.length - 1, "dashboard must keep at least one visible widget");
assert.equal(moveDashboardWidget(DEFAULT_DASHBOARD_LAYOUT, "revenue_month", "up").order[0], "revenue_month");

const memoryStorage = new Map();
const storage = { getItem: (key) => memoryStorage.get(key) || null, setItem: (key, value) => memoryStorage.set(key, value) };
saveDashboardLayout(21, { order: ["margin_month"], hidden: ["payroll_month"] }, storage);
assert.equal(loadDashboardLayout(21, storage).order[0], "margin_month");
assert.ok(memoryStorage.has(dashboardLayoutStorageKey(21)));

const html = read("owner-dashboard.html");
const script = read("owner-dashboard.js");
const navigation = read("app/navigation.js");
const index = read("index.html");
const expenses = read("owner-expenses.js");
assert.match(html, /id="dashboardWidgetGrid"/);
assert.match(html, /id="dashboardConfigList"/);
assert.match(script, /finance\/summary\?month=/);
assert.match(script, /action", item\.action/);
assert.match(navigation, /owner-dashboard\.html/);
assert.match(index, /owner-dashboard\.html/);
assert.match(expenses, /params\.get\("action"\) === "add"/);

console.log("owner dashboard contract checks passed");

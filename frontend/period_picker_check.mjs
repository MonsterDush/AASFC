import assert from "node:assert/strict";
import fs from "node:fs";

import { periodPresetLabel, resolvePeriodPreset } from "./app/period-picker.js";

const now = new Date(2026, 8, 30, 12);

assert.deepEqual(resolvePeriodPreset("today", now), {
  preset: "today",
  mode: "day",
  day: "2026-09-30",
  from: "2026-09-30",
  to: "2026-09-30",
});
assert.deepEqual(resolvePeriodPreset("previous_week", now), {
  preset: "previous_week",
  mode: "range",
  from: "2026-09-21",
  to: "2026-09-27",
});
assert.deepEqual(resolvePeriodPreset("previous_month", now), {
  preset: "previous_month",
  mode: "month",
  from: "2026-08-01",
  to: "2026-08-31",
  month: "2026-08",
});
assert.deepEqual(resolvePeriodPreset("last_30", now), {
  preset: "last_30",
  mode: "range",
  from: "2026-09-01",
  to: "2026-09-30",
});
assert.equal(periodPresetLabel("this_month", "ru"), "Этот месяц");
assert.equal(periodPresetLabel("last_365", "en"), "Last 365 days");

const helpSource = fs.readFileSync(new URL("./app/context-help.js", import.meta.url), "utf8");
assert.match(helpSource, /Math\.min\(10000, Math\.max\(5000,/);
assert.match(helpSource, /data-info/);
assert.match(helpSource, /promoteContextDescriptions/);
for (const selector of ["[data-context-description]", ".toggle__desc", ".card > p.muted"]) {
  assert.ok(helpSource.includes(selector), `context help lost ${selector}`);
}

for (const file of [
  "app-adjustments.html",
  "staff-adjustments.html",
  "staff-report.html",
  "staff-shifts.html",
]) {
  const source = fs.readFileSync(new URL(`./${file}`, import.meta.url), "utf8");
  assert.match(source, /data-period-picker/, `${file} must use the shared period picker`);
  assert.match(source, /data-period-stepper="month"/, `${file} must keep month arrows around the period picker`);
}

for (const file of ["staff-salary.html", "admin-demo-analytics.html"]) {
  const source = fs.readFileSync(new URL(`./${file}`, import.meta.url), "utf8");
  assert.match(source, /data-period-picker/, `${file} must use the shared period picker`);
}

const dayEconomics = fs.readFileSync(new URL("./owner-day-economics.html", import.meta.url), "utf8");
assert.match(dayEconomics, /id="economicsDatePicker" type="date"/);
assert.match(dayEconomics, /id="economicsPreviousDay"/);
assert.match(dayEconomics, /id="economicsNextDay"/);

const cssFiles = fs.readdirSync(new URL("./styles/core/", import.meta.url))
  .filter((file) => file.endsWith(".css"))
  .concat(fs.readdirSync(new URL("./styles/pages/", import.meta.url)).filter((file) => file.endsWith(".css")).map((file) => `../pages/${file}`));
for (const file of cssFiles) {
  const base = file.startsWith("../") ? new URL(`./styles/core/${file}`, import.meta.url) : new URL(`./styles/core/${file}`, import.meta.url);
  const source = fs.readFileSync(base, "utf8");
  assert.doesNotMatch(source, /font-weight:\s*(?:6[1-9]\d|[7-9]\d\d)/, `${file} contains a font weight above 600`);
}

console.log("period picker and contextual help checks passed");

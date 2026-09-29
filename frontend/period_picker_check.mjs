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

console.log("period picker and contextual help checks passed");

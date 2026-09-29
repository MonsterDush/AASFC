import assert from "node:assert/strict";

import {
  dashboardDateLabel,
  dashboardReferenceDate,
} from "./owner-dashboard-period.js";

assert.equal(
  dashboardReferenceDate("2026-08", {
    today: "2026-09-28",
    dailySeries: [{ date: "2026-08-03" }],
    reports: [{ date: "2026-08-07" }],
  }),
  "2026-08-07",
);
assert.equal(
  dashboardReferenceDate("2026-08", { today: "2026-09-28" }),
  "2026-08-31",
);
assert.equal(
  dashboardReferenceDate("2026-09", {
    today: "2026-09-28",
    reports: [{ date: "2026-09-01" }],
  }),
  "2026-09-28",
);
assert.match(dashboardDateLabel("2026-08-07"), /7/);

console.log("owner dashboard period contract: ok");

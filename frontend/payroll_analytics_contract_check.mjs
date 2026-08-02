import assert from "node:assert/strict";
import { buildPayrollTeamAnalytics, payrollLineShiftMetrics } from "./app/payroll-analytics.js";

const lines = [
  { member_user_id: 1, amount_minor: 10_000_000, breakdown: { metrics: { shifts_count: 10 } } },
  { member_user_id: 2, amount_minor: 7_800_000, breakdown: { metrics: { shifts_count: 10 } } },
  { member_user_id: 3, amount_minor: 1_500_000, breakdown: { metrics: { shifts_count: 1 } } },
  { member_user_id: 4, amount_minor: 2_000_000, breakdown: { metrics: { shifts_count: 0 } } },
];

assert.deepEqual(payrollLineShiftMetrics(lines[0]), {
  shiftsCount: 10,
  amountMinor: 10_000_000,
  averagePerShiftMinor: 1_000_000,
});

const analytics = buildPayrollTeamAnalytics(lines, { minimumShifts: 3, maxRows: 6 });
assert.equal(analytics.totalShifts, 21);
assert.equal(analytics.comparableEmployeesCount, 3);
assert.equal(analytics.excludedSmallSampleCount, 1);
assert.equal(analytics.noShiftCount, 1);
assert.equal(analytics.eligibleCount, 2);
assert.deepEqual(analytics.rows.map((row) => row.memberKey), ["1", "2"]);
assert.equal(analytics.rows[0].averagePerShiftMinor, 1_000_000);
assert.equal(analytics.rows[1].averagePerShiftMinor, 780_000);
assert.equal(analytics.rows[0].relativeWidthPercent, 100);
assert.equal(analytics.rows[1].relativeWidthPercent, 78);
assert.equal(analytics.teamAveragePerShiftMinor, Math.round(19_300_000 / 21));

console.log("payroll analytics contract: ok");

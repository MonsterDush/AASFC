import assert from "node:assert/strict";
import {
  buildFinanceCostStructure,
  buildFinancePeriodComparisonGeometry,
  buildFinanceTrendGeometry,
  financeTrendMode,
  normalizeFinanceDailySeries,
} from "./app/finance-summary-analytics.js";
import { resolveComparisonRange } from "./app/period-comparison.js";

assert.equal(resolveComparisonRange({ compareMode: "none", period: "month", month: "2026-07" }), null);

const rows = normalizeFinanceDailySeries([
  { date: "2026-07-02", revenue_minor: 120_000, expense_minor: 30_000, payroll_minor: 20_000, total_cost_minor: 50_000, adjustments_minor: 0, refunds_minor: 0, profit_minor: 70_000 },
  { date: "2026-07-01", revenue_minor: 100_000, expense_minor: 25_000, payroll_minor: 15_000, total_cost_minor: 40_000, adjustments_minor: -5_000, refunds_minor: 0, profit_minor: 55_000 },
]);

assert.equal(rows[0].date, "2026-07-01");
assert.equal(financeTrendMode(rows), "bars");
assert.equal(financeTrendMode([...rows, ...rows, ...rows, ...rows]), "lines");

const redactedRows = normalizeFinanceDailySeries([
  { date: "2026-07-01", revenue_minor: null, expense_minor: 25_000, payroll_minor: null, total_cost_minor: null, profit_minor: null },
]);
assert.equal(redactedRows[0].revenueMinor, null);
assert.equal(redactedRows[0].expenseMinor, 25_000);
assert.equal(redactedRows[0].profitMinor, null);

const geometry = buildFinanceTrendGeometry(rows, { width: 200, height: 100 });
assert.equal(geometry.mode, "bars");
assert.equal(geometry.points.length, 2);
assert.equal(geometry.zeroY, 100);
assert.equal(geometry.points[1].revenueHeight, 100);

const comparisonGeometry = buildFinancePeriodComparisonGeometry(
  rows,
  normalizeFinanceDailySeries([
    { date: "2026-06-01", revenue_minor: 80_000, total_cost_minor: 35_000, profit_minor: 45_000 },
    { date: "2026-06-02", revenue_minor: 110_000, total_cost_minor: 45_000, profit_minor: 65_000 },
    { date: "2026-06-03", revenue_minor: 90_000, total_cost_minor: 50_000, profit_minor: 40_000 },
  ]),
  { metric: "revenue", width: 300, height: 100 },
);
assert.equal(comparisonGeometry.mode, "bars");
assert.equal(comparisonGeometry.pointCount, 3);
assert.equal(comparisonGeometry.current.length, 2);
assert.equal(comparisonGeometry.comparison.length, 3);
assert.equal(comparisonGeometry.comparison[2].date, "2026-06-03");

const structure = buildFinanceCostStructure([
  { key: "rent", title: "Аренда", amount_minor: 60_000 },
  { key: "payroll", title: "ФОТ", amount_minor: 40_000 },
], 100_000);
assert.deepEqual(structure.map((row) => row.shareBps), [6000, 4000]);

console.log("finance summary contract: ok");

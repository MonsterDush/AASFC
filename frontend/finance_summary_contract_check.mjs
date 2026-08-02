import assert from "node:assert/strict";
import {
  buildFinanceCostStructure,
  buildFinanceTrendGeometry,
  financeTrendMode,
  normalizeFinanceDailySeries,
} from "./app/finance-summary-analytics.js";

const rows = normalizeFinanceDailySeries([
  { date: "2026-07-02", revenue_minor: 120_000, expense_minor: 30_000, payroll_minor: 20_000, total_cost_minor: 50_000, adjustments_minor: 0, refunds_minor: 0, profit_minor: 70_000 },
  { date: "2026-07-01", revenue_minor: 100_000, expense_minor: 25_000, payroll_minor: 15_000, total_cost_minor: 40_000, adjustments_minor: -5_000, refunds_minor: 0, profit_minor: 55_000 },
]);

assert.equal(rows[0].date, "2026-07-01");
assert.equal(financeTrendMode(rows), "bars");
assert.equal(financeTrendMode([...rows, ...rows, ...rows, ...rows]), "lines");

const geometry = buildFinanceTrendGeometry(rows, { width: 200, height: 100 });
assert.equal(geometry.mode, "bars");
assert.equal(geometry.points.length, 2);
assert.equal(geometry.zeroY, 100);
assert.equal(geometry.points[1].revenueHeight, 100);

const structure = buildFinanceCostStructure([
  { key: "rent", title: "Аренда", amount_minor: 60_000 },
  { key: "payroll", title: "ФОТ", amount_minor: 40_000 },
], 100_000);
assert.deepEqual(structure.map((row) => row.shareBps), [6000, 4000]);

console.log("finance summary contract: ok");

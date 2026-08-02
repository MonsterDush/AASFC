import assert from "node:assert/strict";
import {
  buildLedgerSourceDrilldown,
  buildLedgerDailySeries,
  buildLedgerStructure,
  calculateLedgerMetrics,
  ledgerKindLabel,
} from "./app/finance-ledger-analytics.js";

const entries = [
  { entry_date: "2026-07-01", direction: "INCOME", kind: "REVENUE", amount_minor: 100_000 },
  { entry_date: "2026-07-01", direction: "EXPENSE", kind: "EXPENSE", amount_minor: 25_000 },
  { entry_date: "2026-07-03", direction: "INCOME", kind: "TRANSFER", amount_minor: 10_000 },
  { entry_date: "2026-07-03", direction: "EXPENSE", kind: "TRANSFER", amount_minor: 10_000 },
];

assert.deepEqual(calculateLedgerMetrics(entries), {
  incomeMinor: 110_000,
  expenseMinor: 35_000,
  netMinor: 75_000,
  count: 4,
});

assert.deepEqual(buildLedgerDailySeries(entries, { from: "2026-07-01", to: "2026-07-03" }), [
  { date: "2026-07-01", day: 1, incomeMinor: 100_000, expenseMinor: 25_000, netMinor: 75_000 },
  { date: "2026-07-02", day: 2, incomeMinor: 0, expenseMinor: 0, netMinor: 0 },
  { date: "2026-07-03", day: 3, incomeMinor: 10_000, expenseMinor: 10_000, netMinor: 0 },
]);

const structure = buildLedgerStructure(entries, 3);
assert.equal(structure.length, 3);
assert.deepEqual(structure[0], { direction: "INCOME", kind: "REVENUE", amountMinor: 100_000, count: 1 });
assert.deepEqual(structure[2], { direction: "MIXED", kind: "OTHER", amountMinor: 20_000, count: 2 });
assert.equal(ledgerKindLabel("BALANCE_ADJUSTMENT"), "Баланс");

assert.deepEqual(
  buildLedgerSourceDrilldown({
    venue_id: 5,
    entry_date: "2026-07-18",
    source_type: "daily_report",
    source_id: 71,
    meta_json: { report_date: "2026-07-18", shift_slot: "NIGHT" },
  }),
  {
    sourceType: "daily_report",
    sourceId: 71,
    sourceLabel: "Отчёт смены",
    actionLabel: "Открыть отчёт",
    href: "/staff-report.html?venue_id=5&report_date=2026-07-18&shift_slot=NIGHT",
  },
);

assert.equal(
  buildLedgerSourceDrilldown({
    entry_date: "2026-07-03",
    source_type: "expense",
    source_id: 42,
  }, { venueId: 5, month: "2026-07" }).href,
  "/owner-expenses.html?venue_id=5&month=2026-07&expense_id=42",
);

assert.equal(
  buildLedgerSourceDrilldown({
    entry_date: "2026-07-01",
    source_type: "payroll_run",
    source_id: 9,
    meta_json: { period_month: "2026-07", member_user_id: 12, payroll_line_id: 88 },
  }, { venueId: 5 }).href,
  "/owner-payroll.html?venue_id=5&month=2026-07&member_user_id=12&payroll_line_id=88",
);

assert.equal(
  buildLedgerSourceDrilldown({
    entry_date: "2026-07-15",
    source_type: "payment_method_transfer",
    source_id: 19,
  }, { venueId: 5, month: "2026-07" }).href,
  "/owner-finance-ledger.html?venue_id=5&month=2026-07&transfer_id=19#transfers",
);

assert.equal(
  buildLedgerSourceDrilldown({
    entry_date: "2026-07-16",
    source_type: "balance_adjustment",
    source_id: 23,
  }, { venueId: 5, month: "2026-07" }).href,
  "/owner-finance-ledger.html?venue_id=5&month=2026-07&adjustment_id=23#balance-adjustments",
);

console.log("finance ledger contract: ok");

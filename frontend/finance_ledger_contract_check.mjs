import assert from "node:assert/strict";
import {
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

console.log("finance ledger contract: ok");

import assert from "node:assert/strict";
import { buildRevenueStructure, normalizeRevenueDailySeries } from "./app/revenue-analytics.js";

const series = normalizeRevenueDailySeries([
  { date: "2026-08-02", amount: 2_500 },
  { date: "bad-date", amount: 999 },
  { date: "2026-02-30", amount: 999 },
  { date: "2026-08-01", amount: 1_000 },
]);

assert.deepEqual(series.map((point) => point.date), ["2026-08-01", "2026-08-02"]);
assert.deepEqual(series.map((point) => point.revenueMinor), [100_000, 250_000]);

const structure = buildRevenueStructure([
  { ref_id: 2, title: "VIP-комната", amount: 300_000 },
  { ref_id: 1, title: "Основной зал", amount: 600_000 },
  { ref_id: 3, title: "Терраса", amount: 100_000 },
  { ref_id: 4, title: "Не использовалось", amount: 0 },
], 1_000_000);

assert.deepEqual(structure.map((entry) => entry.key), ["1", "2", "3"]);
assert.deepEqual(structure.map((entry) => entry.shareBps), [6000, 3000, 1000]);
assert.equal(structure[0].relativeWidthPercent, 100);
assert.equal(structure[1].relativeWidthPercent, 50);
assert.equal(Math.round(structure[2].relativeWidthPercent * 100), 1667);

console.log("revenue analytics contract: ok");

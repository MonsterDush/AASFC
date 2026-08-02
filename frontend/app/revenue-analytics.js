function finiteAmount(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? Math.max(0, Math.round(number)) : 0;
}

function validIsoDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return false;
  const parsed = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return !Number.isNaN(parsed.getTime()) && [
    String(parsed.getUTCFullYear()).padStart(4, "0"),
    String(parsed.getUTCMonth() + 1).padStart(2, "0"),
    String(parsed.getUTCDate()).padStart(2, "0"),
  ].join("-") === String(value);
}

export function normalizeRevenueDailySeries(rows) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => validIsoDate(row?.date))
    .map((row) => ({
      date: String(row.date),
      revenueMinor: finiteAmount(row.amount) * 100,
      expenseMinor: null,
      payrollMinor: null,
      totalCostMinor: null,
      adjustmentsMinor: null,
      refundsMinor: null,
      profitMinor: null,
    }))
    .sort((left, right) => left.date.localeCompare(right.date));
}

export function buildRevenueStructure(rows, totalAmount) {
  const normalized = (Array.isArray(rows) ? rows : [])
    .map((row, sourceIndex) => ({
      row,
      sourceIndex,
      key: String(row?.ref_id ?? row?.id ?? row?.code ?? row?.title ?? row?.name ?? sourceIndex),
      title: String(row?.title || row?.name || row?.code || "Без названия"),
      amount: finiteAmount(row?.amount),
    }))
    .filter((entry) => entry.amount > 0)
    .sort((left, right) => right.amount - left.amount || left.sourceIndex - right.sourceIndex);
  const rowsTotal = normalized.reduce((sum, entry) => sum + entry.amount, 0);
  const denominator = finiteAmount(totalAmount) || rowsTotal;
  const maximumAmount = normalized.reduce((maximum, entry) => Math.max(maximum, entry.amount), 0);
  return normalized.map((entry, index) => ({
    ...entry,
    rank: index + 1,
    shareBps: denominator > 0 ? Math.round((entry.amount * 10_000) / denominator) : 0,
    relativeWidthPercent: maximumAmount > 0 ? (entry.amount * 100) / maximumAmount : 0,
  }));
}

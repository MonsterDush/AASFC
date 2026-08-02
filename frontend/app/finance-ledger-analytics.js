const KIND_LABELS = {
  REVENUE: "Выручка",
  EXPENSE: "Расходы",
  PAYROLL: "ФОТ",
  ADJUSTMENT: "Корректировки",
  REFUND: "Возвраты",
  BALANCE_ADJUSTMENT: "Баланс",
  TRANSFER: "Переводы",
};

function amountOf(entry) {
  const value = Number(entry?.amount_minor || 0);
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

function parseIsoDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return null;
  const parsed = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(parsed.getTime()) || isoDate(parsed) !== String(value) ? null : parsed;
}

function isoDate(value) {
  return [
    String(value.getUTCFullYear()).padStart(4, "0"),
    String(value.getUTCMonth() + 1).padStart(2, "0"),
    String(value.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

export function ledgerKindLabel(kind) {
  const normalized = String(kind || "").trim().toUpperCase();
  return KIND_LABELS[normalized] || normalized || "Без типа";
}

export function calculateLedgerMetrics(entries) {
  const rows = Array.isArray(entries) ? entries : [];
  let incomeMinor = 0;
  let expenseMinor = 0;
  rows.forEach((entry) => {
    if (String(entry?.direction || "").toUpperCase() === "INCOME") incomeMinor += amountOf(entry);
    if (String(entry?.direction || "").toUpperCase() === "EXPENSE") expenseMinor += amountOf(entry);
  });
  return {
    incomeMinor,
    expenseMinor,
    netMinor: incomeMinor - expenseMinor,
    count: rows.length,
  };
}

export function buildLedgerDailySeries(entries, range) {
  const from = parseIsoDate(range?.from);
  const to = parseIsoDate(range?.to);
  if (!from || !to || from.getTime() > to.getTime()) return [];

  const byDate = new Map();
  (Array.isArray(entries) ? entries : []).forEach((entry) => {
    const entryDate = String(entry?.entry_date || "");
    if (!parseIsoDate(entryDate)) return;
    const current = byDate.get(entryDate) || { incomeMinor: 0, expenseMinor: 0 };
    const direction = String(entry?.direction || "").toUpperCase();
    if (direction === "INCOME") current.incomeMinor += amountOf(entry);
    if (direction === "EXPENSE") current.expenseMinor += amountOf(entry);
    byDate.set(entryDate, current);
  });

  const points = [];
  const cursor = new Date(from.getTime());
  while (cursor.getTime() <= to.getTime()) {
    const date = isoDate(cursor);
    const totals = byDate.get(date) || { incomeMinor: 0, expenseMinor: 0 };
    points.push({
      date,
      day: cursor.getUTCDate(),
      incomeMinor: totals.incomeMinor,
      expenseMinor: totals.expenseMinor,
      netMinor: totals.incomeMinor - totals.expenseMinor,
    });
    cursor.setUTCDate(cursor.getUTCDate() + 1);
  }
  return points;
}

export function buildLedgerStructure(entries, maxGroups = 7) {
  const grouped = new Map();
  (Array.isArray(entries) ? entries : []).forEach((entry) => {
    const direction = String(entry?.direction || "").toUpperCase();
    if (!['INCOME', 'EXPENSE'].includes(direction)) return;
    const kind = String(entry?.kind || "").toUpperCase() || "UNKNOWN";
    const key = `${direction}:${kind}`;
    const current = grouped.get(key) || { direction, kind, amountMinor: 0, count: 0 };
    current.amountMinor += amountOf(entry);
    current.count += 1;
    grouped.set(key, current);
  });

  const sorted = [...grouped.values()].sort((left, right) => (
    right.amountMinor - left.amountMinor || left.kind.localeCompare(right.kind, "ru")
  ));
  const limit = Math.max(2, Number(maxGroups || 7));
  if (sorted.length <= limit) return sorted;
  const visible = sorted.slice(0, limit - 1);
  const rest = sorted.slice(limit - 1).reduce((acc, item) => ({
    direction: "MIXED",
    kind: "OTHER",
    amountMinor: acc.amountMinor + item.amountMinor,
    count: acc.count + item.count,
  }), { amountMinor: 0, count: 0 });
  return [...visible, rest];
}

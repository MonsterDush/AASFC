const KIND_LABELS = {
  REVENUE: "Выручка",
  EXPENSE: "Расходы",
  PAYROLL: "ФОТ",
  ADJUSTMENT: "Корректировки",
  REFUND: "Возвраты",
  BALANCE_ADJUSTMENT: "Баланс",
  TRANSFER: "Переводы",
};

const SOURCE_LABELS = {
  daily_report: "Отчёт смены",
  expense: "Расход",
  payroll_run: "Расчёт начислений",
  payment_method_transfer: "Перевод между оплатами",
  balance_adjustment: "Корректировка баланса",
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

function positiveId(value) {
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function normalizedMonth(value, fallbackDate = "") {
  const raw = String(value || "").trim();
  if (/^\d{4}-\d{2}$/.test(raw)) return raw;
  const date = String(fallbackDate || "").trim();
  return parseIsoDate(date) ? date.slice(0, 7) : "";
}

function buildQuery(values) {
  const query = new URLSearchParams();
  Object.entries(values).forEach(([key, value]) => {
    if (value !== null && value !== undefined && String(value) !== "") query.set(key, String(value));
  });
  return query.toString();
}

export function ledgerKindLabel(kind) {
  const normalized = String(kind || "").trim().toUpperCase();
  return KIND_LABELS[normalized] || normalized || "Без типа";
}

export function ledgerSourceLabel(sourceType) {
  const normalized = String(sourceType || "").trim().toLowerCase();
  return SOURCE_LABELS[normalized] || normalized || "Системная операция";
}

export function buildLedgerSourceDrilldown(entry, { venueId, month } = {}) {
  const sourceType = String(entry?.source_type || "").trim().toLowerCase();
  const sourceId = positiveId(entry?.source_id);
  const normalizedVenueId = positiveId(venueId ?? entry?.venue_id);
  const meta = entry?.meta_json && typeof entry.meta_json === "object" ? entry.meta_json : {};
  const entryDate = parseIsoDate(entry?.entry_date) ? String(entry.entry_date) : "";
  const periodMonth = normalizedMonth(month, entryDate);
  const result = {
    sourceType,
    sourceId,
    sourceLabel: ledgerSourceLabel(sourceType),
    actionLabel: "Показать детали",
    href: null,
  };

  if (!normalizedVenueId || !sourceId) return result;

  if (sourceType === "expense") {
    const expenseDate = parseIsoDate(meta.expense_date) ? String(meta.expense_date) : entryDate;
    result.actionLabel = "Открыть расход";
    result.href = `/owner-expenses.html?${buildQuery({
      venue_id: normalizedVenueId,
      month: normalizedMonth(periodMonth, expenseDate),
      expense_id: sourceId,
    })}`;
    return result;
  }

  if (sourceType === "daily_report") {
    const reportDate = parseIsoDate(meta.report_date) ? String(meta.report_date) : entryDate;
    const shiftSlot = ["DAY", "NIGHT"].includes(String(meta.shift_slot || "").toUpperCase())
      ? String(meta.shift_slot).toUpperCase()
      : "";
    result.actionLabel = "Открыть отчёт";
    result.href = reportDate ? `/staff-report.html?${buildQuery({
      venue_id: normalizedVenueId,
      report_date: reportDate,
      shift_slot: shiftSlot,
    })}` : null;
    return result;
  }

  if (sourceType === "payroll_run") {
    const payrollMonth = normalizedMonth(meta.period_month, entryDate) || periodMonth;
    result.actionLabel = "Открыть начисление";
    result.href = `/owner-payroll.html?${buildQuery({
      venue_id: normalizedVenueId,
      month: payrollMonth,
      member_user_id: positiveId(meta.member_user_id),
      payroll_line_id: positiveId(meta.payroll_line_id),
    })}`;
    return result;
  }

  if (sourceType === "payment_method_transfer") {
    result.actionLabel = "Показать перевод";
    result.href = `/owner-finance-ledger.html?${buildQuery({
      venue_id: normalizedVenueId,
      month: periodMonth,
      transfer_id: sourceId,
    })}#transfers`;
  }

  if (sourceType === "balance_adjustment") {
    result.actionLabel = "Показать корректировку";
    result.href = `/owner-finance-ledger.html?${buildQuery({
      venue_id: normalizedVenueId,
      month: periodMonth,
      adjustment_id: sourceId,
    })}#balance-adjustments`;
  }

  return result;
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

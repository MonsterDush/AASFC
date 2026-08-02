function amount(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number : 0;
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

export function normalizeFinanceDailySeries(rows) {
  return (Array.isArray(rows) ? rows : [])
    .filter((row) => validIsoDate(row?.date))
    .map((row) => ({
      date: String(row.date),
      revenueMinor: amount(row.revenue_minor),
      expenseMinor: amount(row.expense_minor),
      payrollMinor: amount(row.payroll_minor),
      totalCostMinor: amount(row.total_cost_minor),
      adjustmentsMinor: amount(row.adjustments_minor),
      refundsMinor: amount(row.refunds_minor),
      profitMinor: amount(row.profit_minor),
    }))
    .sort((left, right) => left.date.localeCompare(right.date));
}

export function financeTrendMode(points) {
  const count = Array.isArray(points) ? points.length : 0;
  if (count < 2) return "single";
  return count < 8 ? "bars" : "lines";
}

export function buildFinanceTrendGeometry(points, { width = 720, height = 220 } = {}) {
  const rows = Array.isArray(points) ? points : [];
  if (!rows.length) return null;
  const mode = financeTrendMode(rows);
  const values = rows.flatMap((row) => mode === "lines"
    ? [row.revenueMinor, row.totalCostMinor, row.profitMinor]
    : [row.revenueMinor, row.totalCostMinor]);
  let minValue = mode === "lines" ? Math.min(0, ...values) : 0;
  let maxValue = Math.max(0, ...values);
  if (minValue === maxValue) maxValue = minValue + 1;
  if (mode === "lines") {
    const padding = Math.max(1, (maxValue - minValue) * 0.06);
    maxValue += padding;
    if (minValue < 0) minValue -= padding;
  }
  const range = maxValue - minValue || 1;
  const y = (value) => height - (((amount(value) - minValue) / range) * height);
  const bandWidth = width / rows.length;
  const coordinates = rows.map((row, index) => ({
    ...row,
    x: mode === "lines" ? (rows.length === 1 ? width / 2 : (index / (rows.length - 1)) * width) : (index + 0.5) * bandWidth,
    hitX: index * bandWidth,
    hitWidth: bandWidth,
    revenueY: y(row.revenueMinor),
    totalCostY: y(row.totalCostMinor),
    profitY: y(row.profitMinor),
    revenueHeight: Math.max(0, height - y(row.revenueMinor)),
    totalCostHeight: Math.max(0, height - y(row.totalCostMinor)),
  }));
  const pathFor = (field) => coordinates.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)},${point[field].toFixed(2)}`).join(" ");
  return {
    mode,
    width,
    height,
    minValue,
    maxValue,
    zeroY: y(0),
    points: coordinates,
    revenuePath: mode === "lines" ? pathFor("revenueY") : "",
    totalCostPath: mode === "lines" ? pathFor("totalCostY") : "",
    profitPath: mode === "lines" ? pathFor("profitY") : "",
  };
}

export function buildFinanceCostStructure(rows, totalCostMinor, maxRows = 6) {
  const sorted = (Array.isArray(rows) ? rows : [])
    .map((row) => ({
      key: String(row?.key || row?.title || "other"),
      title: String(row?.title || "Прочие расходы"),
      amountMinor: Math.max(0, amount(row?.amount_minor)),
    }))
    .filter((row) => row.amountMinor > 0)
    .sort((left, right) => right.amountMinor - left.amountMinor || left.title.localeCompare(right.title, "ru"));
  const limit = Math.max(2, Number(maxRows || 6));
  let visible = sorted;
  if (sorted.length > limit) {
    const rest = sorted.slice(limit - 1).reduce((acc, row) => ({
      key: "other",
      title: "Остальное",
      amountMinor: acc.amountMinor + row.amountMinor,
    }), { amountMinor: 0 });
    visible = [...sorted.slice(0, limit - 1), rest];
  }
  const fallbackTotal = visible.reduce((sum, row) => sum + row.amountMinor, 0);
  const denominator = Math.max(0, amount(totalCostMinor)) || fallbackTotal;
  return visible.map((row) => ({
    ...row,
    shareBps: denominator > 0 ? Math.round((row.amountMinor * 10000) / denominator) : 0,
  }));
}

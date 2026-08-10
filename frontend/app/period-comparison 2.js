function parseIsoDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ""));
  if (!match) return null;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3])));
  return Number.isNaN(date.getTime()) ? null : date;
}

function isoDate(date) {
  return [
    String(date.getUTCFullYear()).padStart(4, "0"),
    String(date.getUTCMonth() + 1).padStart(2, "0"),
    String(date.getUTCDate()).padStart(2, "0"),
  ].join("-");
}

export function addIsoDays(value, days) {
  const date = parseIsoDate(value);
  if (!date) return "";
  date.setUTCDate(date.getUTCDate() + Number(days || 0));
  return isoDate(date);
}

export function monthRange(month) {
  const match = /^(\d{4})-(\d{2})$/.exec(String(month || ""));
  if (!match) return null;
  const year = Number(match[1]);
  const monthIndex = Number(match[2]) - 1;
  const from = new Date(Date.UTC(year, monthIndex, 1));
  const to = new Date(Date.UTC(year, monthIndex + 1, 0));
  return { from: isoDate(from), to: isoDate(to) };
}

export function previousMonthRange(month) {
  const current = monthRange(month);
  if (!current) return null;
  const start = parseIsoDate(current.from);
  start.setUTCMonth(start.getUTCMonth() - 1);
  return monthRange(`${start.getUTCFullYear()}-${String(start.getUTCMonth() + 1).padStart(2, "0")}`);
}

export function normalizeIsoRange(from, to) {
  const fromDate = parseIsoDate(from);
  const toDate = parseIsoDate(to);
  if (!fromDate || !toDate) return null;
  if (fromDate.getTime() <= toDate.getTime()) return { from: isoDate(fromDate), to: isoDate(toDate) };
  return { from: isoDate(toDate), to: isoDate(fromDate) };
}

export function previousEqualRange(from, to) {
  const current = normalizeIsoRange(from, to);
  if (!current) return null;
  const fromDate = parseIsoDate(current.from);
  const toDate = parseIsoDate(current.to);
  const daysInclusive = Math.round((toDate.getTime() - fromDate.getTime()) / 86400000) + 1;
  const compareTo = addIsoDays(current.from, -1);
  return {
    from: addIsoDays(compareTo, -(daysInclusive - 1)),
    to: compareTo,
  };
}

export function weekRange(day) {
  const target = parseIsoDate(day);
  if (!target) return null;
  const weekdayFromMonday = (target.getUTCDay() + 6) % 7;
  const from = addIsoDays(isoDate(target), -weekdayFromMonday);
  return { from, to: addIsoDays(from, 6) };
}

export function resolveComparisonRange({
  compareMode = "auto",
  compareFrom = "",
  compareTo = "",
  ...periodState
}) {
  if (String(compareMode).toLowerCase() === "none") return null;
  if (String(compareMode).toLowerCase() === "custom") {
    const range = normalizeIsoRange(compareFrom, compareTo);
    return range ? { ...range, caption: "к выбранному периоду" } : null;
  }
  return resolveAutoComparison(periodState);
}

export function formatComparisonRange(range) {
  if (!range?.from || !range?.to) return "Период не определён";
  return range.from === range.to ? range.from : `${range.from} — ${range.to}`;
}

export function resolveAutoComparison({ period, month, day, from, to }) {
  const mode = String(period || "month").toLowerCase();
  if (mode === "day") {
    const target = String(day || from || to || "");
    const compareDay = addIsoDays(target, -7);
    return compareDay ? {
      from: compareDay,
      to: compareDay,
      caption: "к прошлому такому же дню недели",
    } : null;
  }
  if (mode === "week") {
    const current = weekRange(day || from || to);
    if (!current) return null;
    const previous = previousEqualRange(current.from, current.to);
    return previous ? { ...previous, caption: "к предыдущей неделе" } : null;
  }
  if (mode === "range") {
    const range = previousEqualRange(from, to);
    return range ? { ...range, caption: "к предыдущему периоду такой же длины" } : null;
  }
  const range = previousMonthRange(month);
  return range ? { ...range, caption: "к прошлому месяцу" } : null;
}

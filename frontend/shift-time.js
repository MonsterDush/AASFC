const SHIFT_TIME_RE = /^([01]\d|2[0-3]):([0-5]\d)(?::[0-5]\d)?$/;

function normalizedTime(value) {
  const match = SHIFT_TIME_RE.exec(String(value || "").trim());
  return match ? `${match[1]}:${match[2]}` : "";
}

function minutesFromMidnight(value) {
  const normalized = normalizedTime(value);
  if (!normalized) return null;
  const [hours, minutes] = normalized.split(":").map(Number);
  return (hours * 60) + minutes;
}

export function shiftIntervalEndsNextDay(startTime, endTime) {
  const startMinutes = minutesFromMidnight(startTime);
  const endMinutes = minutesFromMidnight(endTime);
  return startMinutes !== null && endMinutes !== null && endMinutes <= startMinutes;
}

export function formatShiftIntervalRange(
  startTime,
  endTime,
  { separator = "–", fallback = "?" } = {},
) {
  const start = normalizedTime(startTime);
  const end = normalizedTime(endTime);
  if (!start && !end) return fallback;
  if (!start) return `${fallback}${separator}${end}`;
  if (!end) return start;
  const nextDay = shiftIntervalEndsNextDay(start, end) ? " (+1 день)" : "";
  return `${start}${separator}${end}${nextDay}`;
}

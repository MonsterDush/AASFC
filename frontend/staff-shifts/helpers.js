export const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

export function toHHMM(timeStr) {
  if (!timeStr) return "";
  return String(timeStr).slice(0, 5);
}

export function shortNameOrLogin(user) {
  const first = (user?.first_name || "").trim();
  const last = (user?.last_name || "").trim();
  const name = `${first} ${last}`.trim();
  const login = (user?.tg_username || user?.username || "").trim();
  return name || (login ? `@${login.replace(/^@/, "")}` : "Без имени");
}

export function pad2(value) {
  return String(value).padStart(2, "0");
}

export function ym(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}`;
}

export function ymd(date) {
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}`;
}

export function addDays(date, days) {
  const result = new Date(date);
  result.setHours(0, 0, 0, 0);
  result.setDate(result.getDate() + days);
  return result;
}

export function startOfWeek(date) {
  const result = new Date(date);
  result.setHours(0, 0, 0, 0);
  result.setDate(result.getDate() - ((result.getDay() + 6) % 7));
  return result;
}

export function weekTitle(weekStart) {
  const weekEnd = addDays(weekStart, 6);
  const from = `${pad2(weekStart.getDate())}.${pad2(weekStart.getMonth() + 1)}`;
  const to = `${pad2(weekEnd.getDate())}.${pad2(weekEnd.getMonth() + 1)}.${weekEnd.getFullYear()}`;
  return `${from}–${to}`;
}

export function isoInRange(iso, fromISO, toISO) {
  return String(iso) >= String(fromISO) && String(iso) <= String(toISO);
}

function dateOnly(value) {
  const result = new Date(value);
  result.setHours(0, 0, 0, 0);
  return result;
}

export function cmpDateStr(dateStr) {
  const today = dateOnly(new Date());
  const date = dateOnly(new Date(dateStr));
  if (date.getTime() === today.getTime()) return 0;
  return date.getTime() < today.getTime() ? -1 : 1;
}

export function isPastDay(isoDate) {
  return cmpDateStr(isoDate) === -1;
}

export function timeToMinutes(hhmm) {
  const match = String(hhmm || "").match(/^(\d{2}):(\d{2})/);
  if (!match) return 9999;
  return (Number(match[1]) * 60) + Number(match[2]);
}

export function intervalSortKey(interval) {
  return [
    timeToMinutes(interval?.start_time || ""),
    timeToMinutes(interval?.end_time || ""),
    String(interval?.id ?? ""),
  ].join("|");
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[character]));
}

export function pickShortName(value) {
  const shortName = (value?.short_name || value?.member?.short_name || value?.user?.short_name || "").trim();
  if (shortName) return shortName;
  const fullName = (value?.full_name || value?.member?.full_name || value?.user?.full_name || "").trim();
  if (fullName) return fullName.split(/\s+/)[0];
  const username = (value?.tg_username || value?.member_username || value?.user_username || value?.user?.tg_username || value?.username || "").trim();
  if (username) return username.replace(/^@/, "");
  const userId = value?.member_user_id ?? value?.user_id ?? value?.user?.id;
  return userId ? "Сотрудник" : "—";
}

export function fioInitials(fullName) {
  const value = (fullName || "").trim();
  if (!value) return "";
  const parts = value.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0];
  const initials = parts.slice(1).map((part) => part[0] ? `${part[0].toUpperCase()}.` : "").join("");
  return `${parts[0]} ${initials}`.trim();
}

export function displayPerson(value) {
  const fullName = (value?.full_name || value?.member?.full_name || "").trim();
  const initials = fioInitials(fullName);
  if (initials) return initials;
  const shortName = (value?.short_name || value?.member?.short_name || "").trim();
  if (shortName) return shortName;
  const username = (value?.tg_username || value?.member?.tg_username || "").trim();
  if (username) return username.startsWith("@") ? username : `@${username}`;
  const userId = value?.member_user_id ?? value?.user_id ?? value?.user?.id;
  return userId ? "Сотрудник" : "—";
}

export function normalizeList(value) {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  for (const key of ["items", "data", "results", "intervals", "positions", "shifts"]) {
    if (Array.isArray(value[key])) return value[key];
  }
  return [];
}

export function timeToMin(hhmm) {
  const match = /^([0-2]\d):([0-5]\d)$/.exec(String(hhmm || "").trim());
  if (!match) return 1e9;
  return (parseInt(match[1], 10) * 60) + parseInt(match[2], 10);
}

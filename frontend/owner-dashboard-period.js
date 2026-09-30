function lastDayOfMonth(month) {
  const [year, monthNumber] = String(month || '').split('-').map(Number);
  const day = new Date(Date.UTC(year, monthNumber, 0)).getUTCDate();
  return `${year}-${String(monthNumber).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

export function dashboardReferenceDate(month, { today, dailySeries = [], reports = [] } = {}) {
  const currentDate = String(today || '').slice(0, 10);
  if (String(month || '') === currentDate.slice(0, 7)) return currentDate;
  const candidates = [...dailySeries, ...reports]
    .map((item) => String(item?.date || '').slice(0, 10))
    .filter((value) => value.startsWith(`${month}-`))
    .sort();
  return candidates.at(-1) || lastDayOfMonth(month);
}

export function dashboardDateLabel(value, locale = 'ru-RU') {
  const [year, month, day] = String(value || '').split('-').map(Number);
  if (!year || !month || !day) return 'выбранный день';
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long', timeZone: 'UTC' })
    .format(new Date(Date.UTC(year, month - 1, day)));
}

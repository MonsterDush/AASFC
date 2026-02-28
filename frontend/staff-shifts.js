import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMe,
  getMyVenues,
  getMyVenuePermissions,
  getVenuePositions,
} from "/app.js";

window.onerror = function (msg, src, line, col, err) {
  const text = `JS ошибка: ${msg}\n${src || ""}:${line || 0}:${col || 0}`;
  try { toast(text, "err"); } catch {}
  alert(text);
  if (err) console.error(err);
};
window.onunhandledrejection = function (e) {
  const reason = e?.reason?.message || String(e?.reason || e);
  const text = `Promise ошибка: ${reason}`;
  try { toast(text, "err"); } catch {}
  alert(text);
  console.error(e);
};

applyTelegramTheme();
mountCommonUI("shifts");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();

if (!venueId) toast("Сначала выбери заведение в «Настройках»", "warn");
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "shifts", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  grid: document.getElementById("calGrid"),
  dayPanel: document.getElementById("dayPanel"),
  btnLegend: document.getElementById("btnLegend"),
  legendModal: document.getElementById("legendModal"),
  legendBody: document.getElementById("legendBody"),
};

// DayPanel удалён: у нас есть отдельная страница/экран для графика
if (el.dayPanel) {
  try { el.dayPanel.remove(); } catch {}
  el.dayPanel = null;
}


const mode = {
  box: document.getElementById("calendarMode"),
  all: document.getElementById("modeAll"),
  mine: document.getElementById("modeMine"),
  global: document.getElementById("modeGlobal"),
};
const view = {
  box: document.getElementById("calendarView"),
  month: document.getElementById("viewMonth"),
  week: document.getElementById("viewWeek"),
};

const LS_VIEW = "axelio.shifts.view"; // 'month' | 'week'
const LS_WEEK_START = "axelio.shifts.weekStart"; // YYYY-MM-DD (Monday)
let calendarView = (params.get("view") || localStorage.getItem(LS_VIEW) || "month");
if (calendarView !== "week") calendarView = "month";

let curWeekStart = null; // Date (Monday)

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitleEl = document.getElementById("modalSubtitle");

function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);

function openModal(title, subtitle, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Смены";
  if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle || "";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}


// ----- Legend (interval colors) -----
function closeLegendModal() { el.legendModal?.classList.remove("open"); }
el.legendModal?.querySelectorAll("[data-close-legend]")?.forEach((btn) => btn.addEventListener("click", closeLegendModal));
el.legendModal?.querySelector(".modal__backdrop")?.addEventListener("click", closeLegendModal);

function openLegendModal() {
  if (!el.legendModal || !el.legendBody) return;
  const list = (Array.isArray(intervals) ? intervals : [])
    .filter(x => x && x.id !== undefined && x.id !== null)
    .slice()
    .sort((a,b) => intervalSortKey(a).localeCompare(intervalSortKey(b)));

  if (!list.length) {
    el.legendBody.innerHTML = `<div class="muted">Интервалы не найдены</div>`;
    el.legendModal.classList.add("open");
    return;
  }

  const rows = list.map((i) => {
    const title = i.title || i.name || `${i.start_time || "?"}–${i.end_time || "?"}`;
    const sub = `${i.start_time || "?"}–${i.end_time || "?"}`;
    const c = colorForInterval(i.id);
    return `
      <div class="legend__row">
        <div class="legend__swatch" style="background:${escapeHtml(c)}"></div>
        <div class="legend__text">
          <div class="legend__title">${escapeHtml(title)}</div>
          <div class="legend__sub">${escapeHtml(sub)}</div>
        </div>
      </div>
    `;
  }).join("");

  el.legendBody.innerHTML = `<div class="legend">${rows}</div>`;
  el.legendModal.classList.add("open");
}

el.btnLegend?.addEventListener("click", openLegendModal);


function toHHMM(timeStr) {
  if (!timeStr) return "";
  const s = String(timeStr);
  return s.slice(0, 5);
}

function shortNameOrLogin(u) {
  const first = (u?.first_name || "").trim();
  const last = (u?.last_name || "").trim();
  const name = (first + " " + last).trim();
  const login = (u?.tg_username || u?.username || "").trim();
  return name || (login ? "@" + login.replace(/^@/, "") : "Без имени");
}

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
function ymd(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }
function addDays(d, days) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  x.setDate(x.getDate() + days);
  return x;
}

function startOfWeek(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  const jsDow = x.getDay(); // 0..6 (Sun..Sat)
  const mondayBased = (jsDow + 6) % 7; // 0..6 (Mon..Sun)
  x.setDate(x.getDate() - mondayBased);
  return x;
}

function weekTitle(ws) {
  const we = addDays(ws, 6);
  const a = `${pad2(ws.getDate())}.${pad2(ws.getMonth() + 1)}`;
  const b = `${pad2(we.getDate())}.${pad2(we.getMonth() + 1)}.${we.getFullYear()}`;
  return `${a}–${b}`;
}

function isoInRange(iso, fromISO, toISO) {
  // for YYYY-MM-DD (lexicographic works)
  return String(iso) >= String(fromISO) && String(iso) <= String(toISO);
}

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

function dateOnly(d) {
  const x = new Date(d);
  x.setHours(0,0,0,0);
  return x;
}
function cmpDateStr(dateStr) {
  const today = dateOnly(new Date());
  const d = dateOnly(new Date(dateStr));
  if (d.getTime() === today.getTime()) return 0;
  return d.getTime() < today.getTime() ? -1 : 1;
}
function isPastDay(isoDate) {
  return cmpDateStr(isoDate) === -1;
}

// ------------------------------
// Interval colors (Theme G)
// One interval -> one stable color (per venue), persisted in localStorage.
// Past days: all dots use --dotPast.
// ------------------------------
const INTERVAL_COLORS = [
  "#22C55E",
  "#F97316",
  "#A855F7",
  "#06B6D4",
  "#EF4444",
  "#EAB308",
  "#3B82F6",
  "#F43F5E",
  "#14B8A6",
  "#84CC16",
  "#FB7185",
  "#94A3B8",
];

let intervalColorMap = {}; // intervalId -> hex

function timeToMinutes(hhmm) {
  const m = String(hhmm || "").match(/^(\d{2}):(\d{2})/);
  if (!m) return 9999;
  return (Number(m[1]) * 60) + Number(m[2]);
}

function intervalSortKey(i) {
  const st = i?.start_time || "";
  const et = i?.end_time || "";
  return [timeToMinutes(st), timeToMinutes(et), String(i?.id ?? "")].join("|");
}

function buildIntervalColorMap() {
  if (!venueId) return;
  const key = `axelio.intervalColorMap.${venueId}`;
  let stored = {};
  try {
    stored = JSON.parse(localStorage.getItem(key) || "{}");
  } catch {
    stored = {};
  }

  const list = (Array.isArray(intervals) ? intervals : [])
    .filter(x => x && x.id !== undefined && x.id !== null)
    .slice()
    .sort((a, b) => intervalSortKey(a).localeCompare(intervalSortKey(b)));

  const used = new Set();
  const nextStored = {};

  // keep only current intervals, dedupe indexes
  for (const i of list) {
    const id = String(i.id);
    const idx = stored?.[id];
    if (Number.isInteger(idx) && idx >= 0 && idx < INTERVAL_COLORS.length && !used.has(idx)) {
      nextStored[id] = idx;
      used.add(idx);
    }
  }

  // assign colors for new/invalid intervals
  const pickFree = () => {
    for (let k = 0; k < INTERVAL_COLORS.length; k++) {
      if (!used.has(k)) return k;
    }
    // fallback: reuse (still deterministic)
    return used.size % INTERVAL_COLORS.length;
  };

  for (const i of list) {
    const id = String(i.id);
    if (nextStored[id] !== undefined) continue;
    const idx = pickFree();
    nextStored[id] = idx;
    used.add(idx);
  }

  try { localStorage.setItem(key, JSON.stringify(nextStored)); } catch {}

  intervalColorMap = {};
  for (const [id, idx] of Object.entries(nextStored)) {
    intervalColorMap[id] = INTERVAL_COLORS[idx % INTERVAL_COLORS.length];
  }
}

function colorForInterval(intervalId) {
  const id = String(intervalId ?? "");
  return intervalColorMap[id] || INTERVAL_COLORS[Math.abs(id.split("").reduce((a, c) => (a * 31 + c.charCodeAt(0)) | 0, 7)) % INTERVAL_COLORS.length];
}

function dotStyleForShift(shift, dateStr, { empty = false } = {}) {
  const c = isPastDay(dateStr) ? "var(--dotPast)" : colorForInterval(shiftIntervalId(shift));
  if (empty) return `background:transparent;border:1px solid ${c};box-shadow:none;`;
  return `background:${c};`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function pickShortName(obj) {
  const sn = (obj?.short_name || obj?.member?.short_name || obj?.user?.short_name || "").trim();
  if (sn) return sn;
  const fn = (obj?.full_name || obj?.member?.full_name || obj?.user?.full_name || "").trim();
  if (fn) return fn.split(/\s+/)[0];
  const un = (obj?.tg_username || obj?.member_username || obj?.user_username || obj?.user?.tg_username || obj?.username || "").trim();
  if (un) return un.replace(/^@/, "");
  const uid = obj?.member_user_id ?? obj?.user_id ?? obj?.user?.id;
  return uid ? `user#${uid}` : "—";
}

function fioInitials(fullName) {
  const s = (fullName || "").trim();
  if (!s) return "";
  const p = s.split(/\s+/).filter(Boolean);
  if (p.length === 1) return p[0];
  const surname = p[0];
  const initials = p.slice(1).map(x => x[0] ? x[0].toUpperCase() + "." : "").join("");
  return `${surname} ${initials}`.trim();
}

function displayPerson(obj) {
  const fn = (obj?.full_name || obj?.member?.full_name || "").trim();
  const fi = fioInitials(fn);
  if (fi) return fi;
  const sn = (obj?.short_name || obj?.member?.short_name || "").trim();
  if (sn) return sn;
  const un = (obj?.tg_username || obj?.member?.tg_username || "").trim();
  if (un) return un.startsWith("@") ? un : `@${un}`;
  const uid = obj?.member_user_id ?? obj?.user_id ?? obj?.user?.id;
  return uid ? `user#${uid}` : "—";
}

function normalizeList(out) {
  if (!out) return [];
  if (Array.isArray(out)) return out;
  for (const k of ["items", "data", "results", "intervals", "positions", "shifts"]) {
    if (Array.isArray(out[k])) return out[k];
  }
  return [];
}

let me = null;
let perms = null;
let myRole = null;
let canEdit = false;

// позже сделаем отдельное право, сейчас привязка к can_make_reports
let canViewRevenue = false;

const LS_SHOW_ALL = "axelio.shifts.showAll";
const LS_SCOPE = "axelio.shifts.scope"; // 'venue' | 'global'
let showAllOnCalendar = false;
let calendarScope = localStorage.getItem(LS_SCOPE) === "global" ? "global" : "venue";
let isMultiVenue = false;

let curMonth = new Date();
let selectedDate = null;
curMonth.setDate(1);

// init week start (Monday) from query/localStorage
try {
  const qWeek = params.get("week");
  const s = (qWeek && /^\d{4}-\d{2}-\d{2}$/.test(qWeek)) ? qWeek : localStorage.getItem(LS_WEEK_START);
  if (s && /^\d{4}-\d{2}-\d{2}$/.test(s)) {
    curWeekStart = startOfWeek(new Date(s + "T00:00:00"));
  }
} catch {}


let intervals = [];
let positions = [];
let shifts = [];
let globalShifts = [];
let shiftsByDate = new Map();
let salaryByDate = new Map(); // dateISO -> total my_salary for the day (only when report exists)

function shiftIntervalTitle(s) {
  const i = s.interval || s.shift_interval || {};
  return i.title || s.interval_title || "Смена";
}
function shiftIntervalId(s) {
  return (s.interval?.id ?? s.shift_interval?.id ?? s.interval_id ?? s.intervalId ?? "x");
}
function shiftTimeLabel(s) {
  const i = s.interval || s.shift_interval || {};
  const st = i.start_time || s.start_time || "";
  const et = i.end_time || s.end_time || "";
  return (st && et) ? `${st}-${et}` : (st || "");
}
function shiftStartHHMM(s) {
  const i = s.interval || s.shift_interval || {};
  const st = i.start_time || s.start_time || s.start || s.time_start || "";
  return toHHMM(st);
}

function timeToMin(hhmm) {
  const s = String(hhmm || "").trim();
  const m = /^([0-2]\d):([0-5]\d)$/.exec(s);
  if (!m) return 1e9;
  return (parseInt(m[1], 10) * 60) + parseInt(m[2], 10);
}

function shiftStartMinutes(s) {
  const t = shiftStartHHMM(s) || (s?.interval?.start_time ? String(s.interval.start_time).slice(0, 5) : "");
  return timeToMin(t);
}

function shiftStableNumId(s) {
  const raw = s?.id ?? s?.shift_id ?? s?.shiftId ?? 0;
  const n = Number(raw);
  return Number.isFinite(n) ? n : 0;
}

function sortShiftsForBadges(list) {
  const arr = Array.isArray(list) ? [...list] : [];
  arr.sort((a, b) => {
    const ta = shiftStartMinutes(a);
    const tb = shiftStartMinutes(b);
    if (ta !== tb) return ta - tb;
    return shiftStableNumId(a) - shiftStableNumId(b);
  });
  return arr;
}

// --- toggle ---
function renderModeToggle() {
  if (!mode.box) return;

  // показываем переключатель:
  // - редактор расписания (canEdit) => "Все/Только мои"
  // - сотрудник с 2+ заведениями => добавляется "Общий"
  if (!canEdit && !isMultiVenue) {
    mode.box.classList.add("hidden");
    mode.box.style.display = "none";
    return;
  }

  // В Sprint-2 версии блок мог быть скрыт классом .hidden (display:none!important).
  // Убираем этот класс при показе, иначе переключатель не появится.
  mode.box.classList.remove("hidden");
  mode.box.style.display = "inline-flex";

  // видимость кнопок
  if (mode.all) mode.all.style.display = canEdit ? "" : "none";
  if (mode.mine) mode.mine.style.display = "";
  if (mode.global) mode.global.style.display = isMultiVenue ? "" : "none";

  const setActive = () => {
    // editor toggle
    mode.all?.classList.toggle("active", canEdit && calendarScope === "venue" && !!showAllOnCalendar);
    mode.mine?.classList.toggle("active", calendarScope === "venue" && (!canEdit || !showAllOnCalendar));
    mode.global?.classList.toggle("active", calendarScope === "global");
  };

  const setScope = (scope) => {
    calendarScope = scope;
    localStorage.setItem(LS_SCOPE, scope);
    setActive();
    reloadCurrentView();
  };

  setActive();

  mode.all && (mode.all.onclick = () => {
    showAllOnCalendar = true;
    localStorage.setItem(LS_SHOW_ALL, "1");
    setScope("venue");
  });

  mode.mine && (mode.mine.onclick = () => {
    showAllOnCalendar = false;
    localStorage.setItem(LS_SHOW_ALL, "0");
    setScope("venue");
  });

  mode.global && (mode.global.onclick = () => {
    setScope("global");
  });
}

function syncUrl() {
  try {
    const p = new URLSearchParams(location.search);
    if (venueId) p.set("venue_id", String(venueId));
    p.set("view", calendarView);

    if (calendarView === "week") {
      const ws = curWeekStart ? ymd(curWeekStart) : "";
      if (ws) p.set("week", ws);
      p.delete("month");
    } else {
      p.set("month", ym(curMonth));
      p.delete("week");
    }

    history.replaceState({}, "", `${location.pathname}?${p.toString()}`);
  } catch {}
}

function renderViewToggle() {
  if (!view.box) return;

  const setActive = () => {
    view.month?.classList.toggle("active", calendarView === "month");
    view.week?.classList.toggle("active", calendarView === "week");
  };

  const goMonth = async () => {
    calendarView = "month";
    localStorage.setItem(LS_VIEW, "month");
    setActive();

    // align month to selectedDate if possible
    if (selectedDate) {
      const d = new Date(String(selectedDate) + "T00:00:00");
      if (!isNaN(d.getTime())) curMonth = new Date(d.getFullYear(), d.getMonth(), 1);
    }
    await reloadCurrentView();
  };

  const goWeek = async () => {
    calendarView = "week";
    localStorage.setItem(LS_VIEW, "week");
    setActive();

    const base = selectedDate ? new Date(String(selectedDate) + "T00:00:00") : new Date();
    curWeekStart = startOfWeek(base);

    try { localStorage.setItem(LS_WEEK_START, ymd(curWeekStart)); } catch {}
    await loadWeek();
  };

  view.month && (view.month.onclick = goMonth);
  view.week && (view.week.onclick = goWeek);

  setActive();
}

async function reloadCurrentView() {
  return (calendarView === "week") ? loadWeek() : loadMonth();
}


async function loadContext() {
  if (!venueId) return;

  me = await getMe().catch(() => null);
  const venuesList = await getMyVenues().catch(() => []);
  isMultiVenue = Array.isArray(venuesList) && venuesList.length >= 2;

  perms = await getMyVenuePermissions(venueId).catch(() => null);

  myRole = perms?.role || perms?.venue_role || perms?.my_role || null;
  const flags = perms?.position_flags || {};
  const posObj = perms?.position || {};

  canEdit =
    myRole === "OWNER" ||
    myRole === "SUPER_ADMIN" ||
    !!flags.can_edit_schedule ||
    !!posObj.can_edit_schedule;

  canViewRevenue = !!flags.can_make_reports || !!posObj.can_make_reports;

  // default: editor sees all
  showAllOnCalendar = canEdit ? true : false;
  const saved = localStorage.getItem(LS_SHOW_ALL);
  if (saved !== null) showAllOnCalendar = saved === "1";

  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/shift-intervals`);
    intervals = normalizeList(out).filter(x => x && (x.is_active === undefined || x.is_active));
  } catch { intervals = []; }

  buildIntervalColorMap();

  try {
    const out = await getVenuePositions(venueId);
    positions = normalizeList(out).filter(p => p && (p.is_active === undefined || p.is_active));
  } catch { positions = []; }
}


// ----- Общий календарь (multi-venue) -----
function isPastDateISO(dateISO) {
  const d = new Date(dateISO.length === 10 ? dateISO + "T00:00:00" : dateISO);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  d.setHours(0, 0, 0, 0);
  return d < today;
}

function fmtMoney(n) {
  if (n === null || n === undefined) return "—";
  const v = Math.round(Number(n));
  if (!isFinite(v)) return "—";
  return v.toLocaleString("ru-RU");
}

function formatGlobalLine(item) {
  const venueName = item?.venue?.name || "Заведение";
  const t = shiftStartHHMM(item) || (item?.interval?.start_time ? String(item.interval.start_time).slice(0, 5) : "");

  // Прошедшие: показываем зарплату, а если её нет (ещё нет отчёта) — показываем "Заведение • Время".
  if (isPastDateISO(item.date)) {
    const sal = Number(item?.my_salary);
    if (Number.isFinite(sal)) return fmtMoney(sal);
    return t ? `${venueName} • ${t}` : `${venueName}`;
  }

  // Будущие: "Заведение • Время"
  return t ? `${venueName} • ${t}` : `${venueName}`;
}

async function loadMyGlobalShifts(monthStr) {
  const out = await api(`/me/shifts?month=${encodeURIComponent(monthStr)}`).catch(() => []);
  return Array.isArray(out) ? out : [];
}

async function loadMonth() {
  if (!venueId) return;

  const m = ym(curMonth);
  syncUrl();
  el.grid.classList.remove("is-week");
  try {
    if (calendarScope === "global") {
      const out = await loadMyGlobalShifts(m);
      globalShifts = normalizeList(out).map(x => ({ ...x, id: x.id ?? x.shift_id }));
      shifts = [];
    } else {
      const out = await api(`/venues/${encodeURIComponent(venueId)}/shifts?month=${encodeURIComponent(m)}`);
      shifts = normalizeList(out);
      globalShifts = [];
    }
  } catch (e) {
    shifts = [];
    globalShifts = [];
    toast(e?.message || "Не удалось загрузить смены", "err");
  }

  buildIndex();
  renderMonth();

  // Keep a selected day panel (graph) on screen
  const monthPrefix = ym(curMonth);
  if (!selectedDate || !String(selectedDate).startsWith(monthPrefix)) {
    selectedDate = defaultSelectedDateForMonth();
  }
  selectDate(selectedDate, { noExpand: true });
}


async function loadWeek() {
  if (!venueId) return;

  // init current week if missing
  if (!curWeekStart) {
    const base = selectedDate ? new Date(String(selectedDate) + "T00:00:00") : new Date();
    curWeekStart = startOfWeek(base);
  }

  const ws = new Date(curWeekStart);
  const we = addDays(ws, 6);

  el.monthLabel.textContent = weekTitle(ws);
  el.grid.classList.add("is-week");

  const fromISO = ymd(ws);
  const toISO = ymd(we);

  syncUrl();

  try {
    if (calendarScope === "global") {
      // global endpoint is month-based, so fetch 1-2 months and filter
      const m1 = ym(ws);
      const m2 = ym(we);
      const a1 = await loadMyGlobalShifts(m1);
      const a2 = (m2 === m1) ? [] : await loadMyGlobalShifts(m2);

      globalShifts = normalizeList(a1)
        .concat(normalizeList(a2))
        .map(x => ({ ...x, id: x.id ?? x.shift_id }))
        .filter(s => s?.date && isoInRange(s.date, fromISO, toISO));

      shifts = [];
    } else {
      // venue scope: prefer date_from/date_to; fallback to month+filter
      try {
        const out = await api(`/venues/${encodeURIComponent(venueId)}/shifts?date_from=${encodeURIComponent(fromISO)}&date_to=${encodeURIComponent(toISO)}`);
        shifts = normalizeList(out).filter(s => s?.date && isoInRange(s.date, fromISO, toISO));
      } catch (e1) {
        const m1 = ym(ws);
        const m2 = ym(we);
        const out1 = await api(`/venues/${encodeURIComponent(venueId)}/shifts?month=${encodeURIComponent(m1)}`);
        const out2 = (m2 === m1) ? [] : await api(`/venues/${encodeURIComponent(venueId)}/shifts?month=${encodeURIComponent(m2)}`);
        shifts = normalizeList(out1).concat(normalizeList(out2))
          .filter(s => s?.date && isoInRange(s.date, fromISO, toISO));
      }
      globalShifts = [];
    }
  } catch (e) {
    shifts = [];
    globalShifts = [];
    toast(e?.message || "Не удалось загрузить смены (неделя)", "err");
  }

  buildIndex();
  renderWeek(ws);

  const today = ymd(new Date());
  if (!selectedDate || !isoInRange(selectedDate, fromISO, toISO)) {
    selectedDate = isoInRange(today, fromISO, toISO) ? today : fromISO;
  }
  selectDate(selectedDate, { noExpand: true });

  try { localStorage.setItem(LS_WEEK_START, fromISO); } catch {}
}

function updateBadgesCols(box) {
  // v6: hard 2 columns are controlled by CSS (#calGrid.is-week .cal-badges)
  // leaving this as no-op to avoid accidental 1-col overrides.
  return;
}

let _colsRaf = 0;
function scheduleColsUpdate() {
  if (_colsRaf) cancelAnimationFrame(_colsRaf);
  _colsRaf = requestAnimationFrame(() => {
    _colsRaf = 0;
    document.querySelectorAll(".cal.is-week .cal-badges").forEach(updateBadgesCols);
  });
}
window.addEventListener("resize", scheduleColsUpdate);
window.addEventListener("orientationchange", scheduleColsUpdate);

function renderWeek(ws) {
  try {
    // No month "expand" mechanics in week view
    collapseExpanded();

    wireGlobalCollapse();
    el.grid.innerHTML = "";

    const body = document.createElement("div");
    body.className = "cal-body";

    const todayStr = ymd(new Date());

    for (let i = 0; i < 7; i++) {
      const d = addDays(ws, i);
      const dateStr = ymd(d);

      const cell = document.createElement("button");
      cell.type = "button";
      cell.className =
        "cal-cell" +
        (dateStr === todayStr ? " cal-cell--today" : "") +
        (dateStr === selectedDate ? " cal-cell--selected" : "");
      cell.setAttribute("data-date", dateStr);

      // Ideal header: weekday + date + meta
      const top = document.createElement("div");
      top.className = "cal-weektop";

      const left = document.createElement("div");
      left.className = "minw-0";
      left.innerHTML = `
        <div class="cal-weekname">${escapeHtml(WEEKDAYS[i])}</div>
        <div class="cal-weekdate">${pad2(d.getDate())}.${pad2(d.getMonth()+1)}</div>
      `;

      const meta = document.createElement("div");
      meta.className = "cal-daymeta";
      const dayList = filterForCalendar(shiftsByDate.get(dateStr) || [], dateStr);
      const sal = salaryByDate.get(dateStr);
      if (isPastDay(dateStr) && Number.isFinite(Number(sal))) meta.textContent = fmtMoney(sal);
      else if (dayList.length) meta.textContent = `${dayList.length} смен`;
      else meta.textContent = "";

      top.appendChild(left);
      top.appendChild(meta);

      cell.appendChild(top);

      const box = document.createElement("div");
      box.className = "cal-badges";
      const _r = renderCellBadges(dateStr, box, { isWeek: true });
      cell.classList.toggle('is-empty', !!(_r && _r.isEmpty));
      cell.appendChild(box);

      // Week is already readable: click opens day immediately
      cell.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        selectDate(dateStr, { noExpand: true });
        openDay(dateStr);
      });

      body.appendChild(cell);
    }

    el.grid.appendChild(body);
    scheduleColsUpdate();
  }
  catch (e) {
    console.error(e);
    toast("Ошибка в renderWeek: " + (e?.message || e), "err");
    throw e;
  }
}


function buildIndex() {
  shiftsByDate = new Map();
  salaryByDate = new Map();

  const list = (calendarScope === "global") ? globalShifts : shifts;

  const sorted = sortShiftsForBadges(list);

    for (const s of sorted) {
    const date = s.date || s.shift_date || s.day;
    if (!date) continue;

    if (!shiftsByDate.has(date)) shiftsByDate.set(date, []);
    shiftsByDate.get(date).push(s);

    // salaryByDate: суммируем только если my_salary есть (backend выдаёт только при наличии отчёта)
    const sal = Number(s.my_salary);
    if (Number.isFinite(sal)) {
      salaryByDate.set(date, (salaryByDate.get(date) || 0) + sal);
    }
  }

  for (const [d, arr] of shiftsByDate.entries()) {
    arr.sort((a, b) => {
      const at = (a.interval?.start_time || a.shift_interval?.start_time || a.start_time || "");
      const bt = (b.interval?.start_time || b.shift_interval?.start_time || b.start_time || "");
      return String(at).localeCompare(String(bt));
    });
  }
}

function defaultSelectedDateForMonth() {
  const monthPrefix = ym(curMonth);
  const today = ymd(new Date());
  if (String(today).startsWith(monthPrefix)) return today;

  // first day with shifts in this month
  const keys = Array.from(shiftsByDate.keys()).filter(k => String(k).startsWith(monthPrefix)).sort();
  if (keys.length) return keys[0];

  return `${monthPrefix}-01`;
}

function selectDate(dateStr, { noExpand = false } = {}) {
  if (!dateStr) return;
  selectedDate = dateStr;

  // update selected style
  document.querySelectorAll('.cal-cell--selected').forEach(x => x.classList.remove('cal-cell--selected'));
  const esc = (window.CSS && CSS.escape) ? CSS.escape(String(dateStr)) : String(dateStr).replace(/"/g, "\"");
  const cell = document.querySelector(`.cal-cell[data-date="${esc}"]`);
  if (cell) cell.classList.add('cal-cell--selected');


  // optionally expand the cell on desktop for readability
  if (!noExpand && cell) {
    if (expandedDate !== dateStr) expandCell(cell, dateStr);
  }
}

function uniqAssignedPeopleCount(shiftsList) {
  const set = new Set();
  for (const s of (shiftsList || [])) {
    const assigns = (s.assignments || s.shift_assignments || []);
    for (const a of assigns) {
      const id = a.member_user_id ?? a.user_id ?? a.id;
      if (id != null) set.add(String(id));
    }
  }
  return set.size;
}

function countAssignments(shiftsList) {
  let n = 0;
  for (const s of (shiftsList || [])) {
    const assigns = (s.assignments || s.shift_assignments || []);
    n += (assigns?.length || 0);
  }
  return n;
}

function sumMySalary(shiftsList) {
  let total = 0;
  let has = false;
  for (const s of (shiftsList || [])) {
    const sal = Number(s?.my_salary);
    if (Number.isFinite(sal)) { total += sal; has = true; }
  }
  return has ? total : null;
}

function hhmmToMin(hhmm) {
  const s = toHHMM(hhmm);
  if (!/^\d{2}:\d{2}$/.test(s)) return null;
  const h = Number(s.slice(0,2));
  const m = Number(s.slice(3,5));
  if (!Number.isFinite(h) || !Number.isFinite(m)) return null;
  return h*60 + m;
}

function timelineRowLabel(s) {
  // In "global" scope: Venue • HH:MM
  if (calendarScope === 'global') {
    const venueName = s?.venue?.name || 'Заведение';
    const t = shiftStartHHMM(s);
    return t ? `${venueName} • ${t}` : venueName;
  }
  // In venue scope: HH:MM
  return shiftStartHHMM(s);
}

function renderDayTimeline(shiftsList) {
  if (!shiftsList || !shiftsList.length) return '';

  // group by interval (and by venue in global scope)
  const groups = new Map();
  for (const s of shiftsList) {
    const intervalId = shiftIntervalId(s);
    const venueKey = (calendarScope === 'global') ? String(s?.venue_id ?? s?.venue?.id ?? 'v') : 'v';
    const key = `${venueKey}:${intervalId}`;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(s);
  }

  const items = [];
  for (const arr of groups.values()) {
    const s0 = arr[0] || {};
    const i = s0.interval || s0.shift_interval || {};
    const st = toHHMM(i.start_time || s0.start_time || '');
    const et = toHHMM(i.end_time || s0.end_time || '');
    const stMin = hhmmToMin(st);
    const etMin = hhmmToMin(et);

    const c = colorForInterval(shiftIntervalId(s0));
    const rgb = hexToRgbTriplet(c);

    let leftPct = 0;
    let widthPct = 100;
    if (stMin != null && etMin != null && etMin >= stMin) {
      leftPct = (stMin / 1440) * 100;
      widthPct = Math.max(2, ((etMin - stMin) / 1440) * 100);
    }

    const assigns = (calendarScope === 'global') ? null : countAssignments(arr);
    const people = (calendarScope === 'global') ? null : uniqAssignedPeopleCount(arr);
    const sal = sumMySalary(arr);

    let meta = '';
    if (sal != null) meta = `${fmtMoney(sal)}`;
    else if (people != null && people > 0) meta = `${people} чел.`;
    else if (assigns != null && assigns > 0) meta = `${assigns} назнач.`;

    const label = (st && et) ? `${st}–${et}` : (st || timelineRowLabel(s0) || '');

    items.push({ stMin: stMin ?? 9999, leftPct, widthPct, rgb, label, meta });
  }

  items.sort((a, b) => a.stMin - b.stMin);

  const rows = items.map(it => `
    <div class="timeline__row">
      <div class="timeline__time">${escapeHtml(it.label)}</div>
      <div class="timeline__track">
        <div class="timeline__seg" style="--left:${it.leftPct}%;--w:${it.widthPct}%;--line-rgb:${it.rgb}"></div>
      </div>
      <div class="timeline__meta">${escapeHtml(it.meta || '')}</div>
    </div>
  `).join('');

  return `
    <div class="timeline">
      <div class="timeline__axis">
        <div>00</div><div>06</div><div>12</div><div>18</div><div>24</div>
      </div>
      <div class="timeline__rows">${rows}</div>
    </div>
  `;
}

function renderDayPanel(dateStr) {
  if (!el.dayPanel) return;

  const listAll = shiftsByDate.get(dateStr) || [];
  const list = filterForCalendar(listAll, dateStr);
  const allowEdit = canEditDay(dateStr);

  const scopeLabel = (calendarScope === 'global') ? 'Общий' : (showAllOnCalendar ? 'Все' : 'Мои');

  if (!list.length) {
    el.dayPanel.innerHTML = `
      <div class="card daypanel-card">
        <div class="daypanel__head">
          <div class="daypanel__title">
            <b>${escapeHtml(formatDateRuNoG(dateStr))}</b>
            <div class="muted">Режим: ${escapeHtml(scopeLabel)}</div>
          </div>
        </div>
        <div class="daypanel__empty muted">На этот день нет смен в выбранном режиме.</div>
      </div>
    `;
    return;
  }

  const shiftsCount = list.length;
  const people = (calendarScope === 'global') ? null : uniqAssignedPeopleCount(list);
  const assigns = (calendarScope === 'global') ? null : countAssignments(list);
  const total = sumMySalary(list);

  const kpis = [
    `<div class="kpi">Смен: <span class="muted">${shiftsCount}</span></div>`,
  ];
  if (people != null) kpis.push(`<div class="kpi">Людей: <span class="muted">${people}</span></div>`);
  if (assigns != null) kpis.push(`<div class="kpi">Назначений: <span class="muted">${assigns}</span></div>`);
  if (total != null) kpis.push(`<div class="kpi">Итого: <span class="muted">${fmtMoney(total)}</span></div>`);

  el.dayPanel.innerHTML = `
    <div class="card daypanel-card">
      <div class="daypanel__head">
        <div class="daypanel__title">
          <b>${escapeHtml(formatDateRuNoG(dateStr))}</b>
          <div class="muted">Режим: ${escapeHtml(scopeLabel)}</div>
        </div>
        <div class="daypanel__actions">
          <button class="btn" id="btnDayOpen">Открыть</button>
          ${allowEdit ? `<button class="btn primary" id="btnDayEdit">Редактировать</button>` : ``}
        </div>
      </div>
      <div class="kpirow">${kpis.join('')}</div>
      ${renderDayTimeline(list)}
      <div class="daypanel__hint muted">Клик по дню в календаре обновляет график. Повторный клик открывает детали.</div>
    </div>
  `;

  document.getElementById('btnDayOpen')?.addEventListener('click', () => openDay(dateStr));
  document.getElementById('btnDayEdit')?.addEventListener('click', () => openDay(dateStr));
}

function monthTitle(d) {
  const dt = new Date(d);
  const month = dt.toLocaleString("ru-RU", { month: "long" });
  const year = dt.getFullYear();
  const s = `${month} ${year}`;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatDateRuNoG(iso) {
  const x = String(iso);
  const dt = new Date(x.length === 10 ? x + "T00:00:00" : x);
  const dd = String(dt.getDate()).padStart(2, "0");
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const yyyy = dt.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

function filterForCalendar(listAll, dateStr) {
  if (calendarScope === "global") return listAll;
  const myId = me?.id ?? null;

  // staff w/o edit -> only mine
  if (!canEdit && myId) {
    return listAll
      .map(s => {
        const assigns = (s.assignments || s.shift_assignments || []).filter(a => (a.member_user_id ?? a.user_id) === myId);
        if (!assigns.length) return null;
        return { ...s, assignments: assigns };
      })
      .filter(Boolean);
  }

  // editor toggle -> mine
  if (canEdit && !showAllOnCalendar && myId) {
    return listAll
      .map(s => {
        const assigns = (s.assignments || s.shift_assignments || []).filter(a => (a.member_user_id ?? a.user_id) === myId);
        if (!assigns.length) return null;
        return { ...s, assignments: assigns };
      })
      .filter(Boolean);
  }

  return listAll;
}

// Формат строки для ALL-режима: "Имя/логин — HH:MM"
function formatAllModeLine(shift, assignment) {
  const who = assignment ? displayPerson(assignment) : pickShortName(shift);
  const t = shiftStartHHMM(shift);
  return t ? `${who} — ${t}` : `${who}`;
}


function hexToRgbTriplet(hex) {
  const h = String(hex || "").replace("#", "");
  if (h.length !== 6) return "0 0 0";
  const r = parseInt(h.slice(0,2), 16);
  const g = parseInt(h.slice(2,4), 16);
  const b = parseInt(h.slice(4,6), 16);
  return `${r} ${g} ${b}`;
}

function makeCalLine(text, shift) {
  const line = document.createElement("div");
  line.className = "cal-line";

  const span = document.createElement("span");
  span.className = "cal-line__text";
  span.textContent = text;
  line.appendChild(span);

  // Tooltip on desktop (helps when ellipsis kicks in)
  try { line.title = text; } catch {}

  // colorize by interval
  const c = colorForInterval(shiftIntervalId(shift));
  line.dataset.icolor = "1";
  line.style.setProperty("--line-rgb", hexToRgbTriplet(c));
  return line;
}
function shiftHasAssignees(shift) {
  const assigns = shift?.assignments || shift?.shift_assignments || [];
  if (Array.isArray(assigns) && assigns.length) return true;
  const c1 = Number(shift?.assigned_count);
  const c2 = Number(shift?.assignees_count);
  const c3 = Number(shift?.members_count);
  return (Number.isFinite(c1) && c1 > 0) || (Number.isFinite(c2) && c2 > 0) || (Number.isFinite(c3) && c3 > 0);
}

function makeCalDot({ color, filled = false, label = "", title = "" } = {}) {
  const dot = document.createElement("div");
  dot.className = "cal-dot" + (filled ? " is-filled" : "");
  dot.style.setProperty("--dot", color || "var(--muted)");
  if (label) {
    dot.classList.add("is-more");
    dot.textContent = label;
  }
  if (title) {
    try { dot.title = title; } catch {}
    dot.setAttribute("aria-label", title);
  }
  return dot;
}


// dotrow removed: calendar uses only text labels (cal-line)

let expandedDate = null;
let expandWired = false;

function collapseExpanded() {
  if (!expandedDate) return;
  const prev = document.querySelector(`.cal-cell[data-date="${expandedDate}"]`);
  if (prev) {
    prev.classList.remove("is-expanded");
    prev.style.gridColumn = "";
    prev.style.gridRow = "";
  }
  expandedDate = null;
}

function expandCell(cell, dateISO) {
  collapseExpanded();
  expandedDate = dateISO;  
  cell.style.gridColumn = "span 3";
  cell.style.gridRow = "span 2";
  requestAnimationFrame(() => {
    cell.classList.add("is-expanded");
  });
}

function wireGlobalCollapse() {
  if (expandWired) return;
  expandWired = true;

  document.addEventListener("click", (e) => {
    const inCell = e.target.closest?.(".cal-cell");
    const inModal = e.target.closest?.(".modal__panel");
    if (!inCell && !inModal) collapseExpanded();
  });
}

function renderCellBadges(dateStr, box, { isWeek = false } = {}) {
  const listAll = shiftsByDate.get(dateStr) || [];
  const list = filterForCalendar(listAll, dateStr);
  const pastDay = isPastDay(dateStr);

  // limits per view
  const maxMine = isWeek ? 10 : 3;
  const maxAll = isWeek ? 12 : 2;
// MONTH + ALL: show interval dots (no text), 4 max
if (showAllOnCalendar && !isWeek) {
  box.classList.add("cal-badges--dots");

  const sorted = sortShiftsForBadges(list);

  // unique by interval, preserve time order
  const byInterval = new Map(); // intervalId -> {shift, assigned}
  for (const s of sorted) {
    const iidRaw = shiftIntervalId(s);
    const iid = (iidRaw === undefined || iidRaw === null) ? "" : String(iidRaw);
    if (!iid) continue;

    const assigned = shiftHasAssignees(s);
    if (!byInterval.has(iid)) byInterval.set(iid, { shift: s, assigned });
    else byInterval.get(iid).assigned = byInterval.get(iid).assigned || assigned;
  }

  const arr = Array.from(byInterval.values());
  const total = arr.length;

  const maxDots = 4;

  if (total <= maxDots) {
    for (const it of arr) {
      const color = colorForInterval(shiftIntervalId(it.shift));
      box.appendChild(makeCalDot({ color, filled: !!it.assigned }));
    }
    return;
  }

  // show first 3, 4th = "+N"/"…"
  for (let i = 0; i < 3; i++) {
    const it = arr[i];
    const color = colorForInterval(shiftIntervalId(it.shift));
    box.appendChild(makeCalDot({ color, filled: !!it.assigned }));
  }

  const more = total - 3;
  const label = (more <= 9) ? `+${more}` : "…";
  box.appendChild(makeCalDot({ color: "var(--muted)", filled: false, label, title: `+${more}` }));
  return;
}


  if (!showAllOnCalendar) {
    let shown = 0;
    const sorted = sortShiftsForBadges(list);

    for (const s of sorted) {
      let txt = "";

      if (calendarScope === "global") {
        const venueName = s?.venue?.name || "Заведение";
        const t = shiftStartHHMM(s) || (s?.interval?.start_time ? String(s.interval.start_time).slice(0, 5) : "");

        if (pastDay) {
          const sal = Number(s?.my_salary);
          txt = Number.isFinite(sal) ? fmtMoney(sal) : (t ? `${venueName} • ${t}` : `${venueName}`);
        } else {
          txt = t ? `${venueName} • ${t}` : `${venueName}`;
        }
      } else {
        if (pastDay) {
          const sal = Number(s?.my_salary);
          txt = Number.isFinite(sal) ? fmtMoney(sal) : shiftStartHHMM(s);
        } else {
          txt = shiftStartHHMM(s);
        }
      }

      if (txt && txt !== "—") {
        box.appendChild(makeCalLine(txt, s));
        shown++;
      }
      if (shown >= maxMine) break;
    }

    if (shown > 0 && list.length > shown) {
      const more = document.createElement("div");
      more.className = "cal-line muted cal-line--more";
      more.textContent = `+${list.length - shown}`;
      box.appendChild(more);
    }
    return;
  }

  // ALL mode
  const lines = [];

  const sorted2 = sortShiftsForBadges(list);

  for (const s of sorted2) {
    if (calendarScope === "global") {
      lines.push({ text: formatGlobalLine(s), shift: s });
      if (lines.length >= maxAll) break;
      continue;
    }

    const assigns = (s.assignments || s.shift_assignments || []);
    if (assigns.length) {
      for (const a of assigns) {
        lines.push({ text: formatAllModeLine(s, a), shift: s });
        if (lines.length >= maxAll) break;
      }
    } else {
      lines.push({ text: formatAllModeLine(s, null), shift: s });
    }

    if (lines.length >= maxAll) break;
  }

  for (const item of lines) box.appendChild(makeCalLine(item.text, item.shift));

  const totalLines = list.reduce((acc, s) => {
    const assigns = (s.assignments || s.shift_assignments || []);
    return acc + Math.max(1, assigns.length);
  }, 0);

  if (lines.length > 0 && totalLines > maxAll) {
    const more = document.createElement("div");
    more.className = "cal-line muted cal-line--more";
    more.textContent = `+${totalLines - maxAll}`;
    box.appendChild(more);
  }
}

function renderMonth() {
  try {
  wireGlobalCollapse();

  el.grid.classList.remove("is-week");

  el.monthLabel.textContent = monthTitle(curMonth);
  el.grid.innerHTML = "";

  const head = document.createElement("div");
  head.className = "cal-head";
  for (const wd of WEEKDAYS) {
    const c = document.createElement("div");
    c.className = "cal-hcell";
    c.textContent = wd;
    head.appendChild(c);
  }
  el.grid.appendChild(head);

  const body = document.createElement("div");
  body.className = "cal-body";

  const first = new Date(curMonth);
  const jsDow = first.getDay();
  const mondayBased = (jsDow + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayBased);

  const todayStr = ymd(new Date());

  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const inMonth = d.getMonth() === curMonth.getMonth();
    const dateStr = ymd(d);

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className =
      "cal-cell" +
      (inMonth ? "" : " cal-cell--out") +
      (dateStr === todayStr ? " cal-cell--today" : "") +
      (dateStr === selectedDate ? " cal-cell--selected" : "");
    cell.setAttribute("data-date", dateStr);

    const top = document.createElement("div");
    top.className = "cal-daynum";
    top.textContent = String(d.getDate());
    cell.appendChild(top);

    const box = document.createElement("div");
    box.className = "cal-badges";

    renderCellBadges(dateStr, box, { isWeek: false });

    cell.appendChild(box);

    // 1-й клик: expand, 2-й клик: modal
    cell.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();

      selectDate(dateStr, { noExpand: true });

      if (expandedDate !== dateStr) {
        expandCell(cell, dateStr);
        return;
      }

      collapseExpanded();
      openDay(dateStr);
    });

    body.appendChild(cell);
  }

  el.grid.appendChild(body);
} catch (e) {
    console.error(e);
    toast("Ошибка в renderMonth: " + (e?.message || e), "err");
    throw e;
  }
}

function renderShiftCard(s, allowEdit) {
  const title = shiftIntervalTitle(s);
  const time = shiftTimeLabel(s).replace("-", "–");
  const shiftId = (s.id ?? s.shift_id);
  const intColor = colorForInterval(shiftIntervalId(s));
  const canComment = calendarScope !== "global";

  const assignments = s.assignments || s.shift_assignments || [];
  let peopleHtml = "";
  if (!assignments.length) {
    peopleHtml = `<div class="muted" style="margin-top:8px">Пока никто не назначен</div>`;
  } else {
    peopleHtml =
      `<div class="list" style="margin-top:8px">` +
      assignments.map((a) => {
        const label = displayPerson(a);
        const uname = (a.tg_username || a.member_username || "").trim();
        const unameTxt = uname ? (uname.startsWith("@") ? uname : "@"+uname) : "";
        return `
          <div class="list__row">
            <div class="row" style="justify-content:space-between; align-items:center">
              <div class="list__main">
                <div><b>${escapeHtml(label)}</b>${unameTxt ? `<span class="muted"> · ${escapeHtml(unameTxt)}</span>` : ""}</div>
              </div>
              ${allowEdit ? `<button class="btn danger sm" data-unassign data-shift="${shiftId}" data-user="${a.member_user_id}">Удалить</button>` : ""}
            </div>
          </div>
        `;
      }).join("") +
      `</div>`;
  }

  let editorHtml = "";
  if (allowEdit) {
    editorHtml = `
      <div class="row" style="gap:10px; flex-wrap:wrap">
        <select class="input" data-posselect data-shift="${shiftId}" style="flex:1; min-width:240px"></select>
        <button class="btn primary" data-assign data-shift="${shiftId}">Назначить</button>
      </div>
    `;
  }

  const commentsHtml = canComment
    ? `
      <div class="comments">
        <div class="comments__head">
          <b>Комментарии</b>
          <span class="muted small" data-comments-status="${shiftId}"></span>
        </div>
        <div data-comments-list="${shiftId}" class="commentlist"><div class="muted small">Загрузка…</div></div>
        <div class="commentform">
          <textarea class="commentform__input" data-comments-input="${shiftId}" placeholder="Написать комментарий…"></textarea>
          <button class="btn commentform__send" data-comments-send="${shiftId}">Отправить</button>
        </div>
      </div>
    `
    : `
      <div class="comments">
        <div class="comments__head"><b>Комментарии</b></div>
        <div class="muted small" style="margin-top:6px">Комментарии доступны в режимах «Все» или «Только мои».</div>
      </div>
    `;

  return `
    <div class="card shiftcard" data-shiftcard="${shiftId}">
      <div class="shiftcard__head">
        <div class="shiftcard__title">
          <div class="shiftcard__line1"><span class="intchip" style="background:${intColor}"></span><b>${escapeHtml(title)}</b></div>
          ${time ? `<div class="shiftcard__meta muted">${escapeHtml(time)}</div>` : ``}
        </div>
      </div>
      ${peopleHtml}
      ${editorHtml ? `<div class="shiftcard__editor">${editorHtml}</div>` : ``}
      ${commentsHtml}
    </div>
  `;
}


async function loadShiftComments(shiftId) {
  const out = await api(`/venues/${encodeURIComponent(venueId)}/shifts/${encodeURIComponent(shiftId)}/comments`).catch(() => []);
  return Array.isArray(out) ? out : [];
}

function formatCommentAuthor(u) {
  if (!u) return "—";
  return u.short_name || u.full_name || (u.tg_username ? "@" + u.tg_username : ("#" + (u.id ?? "")));
}

function renderCommentsInto(shiftId, comments) {
  const box = document.querySelector(`[data-comments-list="${shiftId}"]`);
  if (!box) return;
  if (!comments || !comments.length) {
    box.innerHTML = '<div class="muted small">Нет комментариев</div>';
    return;
  }
  box.innerHTML = "";
  for (const c of comments) {
    const who = formatCommentAuthor(c.author);
    const dt = c.created_at ? new Date(c.created_at) : null;
    const when = dt ? dt.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";

    const item = document.createElement("div");
    item.className = "comment";
    item.innerHTML = `
      <div class="comment__head">
        <div class="comment__author">${escapeHtml(who)}</div>
        ${when ? `<div class="comment__when">${escapeHtml(when)}</div>` : `<div class="comment__when"></div>`}
      </div>
      <div class="comment__text">${escapeHtml(c.text || "")}</div>
    `;
    box.appendChild(item);
  }
}

async function wireShiftComments(shiftId) {
  const btn = document.querySelector(`[data-comments-send="${shiftId}"]`);
  const inp = document.querySelector(`[data-comments-input="${shiftId}"]`);
  if (!btn || !inp) return;

  const syncBtn = () => {
    const hasText = String(inp.value || "").trim().length > 0;
    if (!btn.dataset.sending) btn.disabled = !hasText;
  };

  inp.addEventListener("input", syncBtn);
  inp.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
      e.preventDefault();
      btn.click();
    }
  });

  const refresh = async () => {
    const comments = await loadShiftComments(shiftId);
    renderCommentsInto(shiftId, comments);
  };

  // initial load
  refresh();

  syncBtn();

  btn.onclick = async () => {
    const text = String(inp.value || "").trim();
    if (!text) return;
    btn.dataset.sending = "1";
    btn.disabled = true;
    try {
      await api(`/venues/${encodeURIComponent(venueId)}/shifts/${encodeURIComponent(shiftId)}/comments`, {
        method: "POST",
        body: { text },
      });
      inp.value = "";
      await refresh();
    } catch (e) {
      toast(e?.message || "Не удалось отправить комментарий", "err");
    } finally {
      delete btn.dataset.sending;
      syncBtn();
    }
  };
}

function wireShiftEditor(dateStr, shift, allowEdit) {
  if (!allowEdit) return;

  const shiftId = (shift.id ?? shift.shift_id);
  const card = document.querySelector(`[data-shiftcard="${shiftId}"]`);
  if (!card) return;

  const sel = card.querySelector(`[data-posselect][data-shift="${shiftId}"]`);
  const btnAssign = card.querySelector(`[data-assign][data-shift="${shiftId}"]`);

  if (sel) {
    sel.innerHTML = "";
    if (!positions.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Нет должностей (создай в «Должности»)";
      sel.appendChild(opt);
      sel.disabled = true;
      if (btnAssign) btnAssign.disabled = true;
    } else {
      for (const p of positions) {
        const opt = document.createElement("option");
        opt.value = p.id;
        const mem = p.member || {};
        const name = fioInitials(mem.full_name) || mem.short_name || (mem.tg_username ? mem.tg_username.replace(/^@/, "") : "");
        opt.textContent = `${p.title} · ${name || "—"}`;
        sel.appendChild(opt);
      }
      sel.disabled = false;
      if (btnAssign) btnAssign.disabled = false;
    }
  }

  if (btnAssign) {
    btnAssign.onclick = async () => {
      const posId = Number(sel?.value || 0);
      if (!posId) return toast("Выбери должность", "warn");
      try {
        await api(`/venues/${encodeURIComponent(venueId)}/shifts/${encodeURIComponent(shiftId)}/assignments`, {
          method: "POST",
          body: { venue_position_id: posId },
        });
        toast("Назначено", "ok");
        await reloadCurrentView();
        openDay(dateStr);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось назначить", "err");
      }
    };
  }

  card.querySelectorAll("[data-unassign]").forEach((btn) => {
    btn.onclick = async () => {
      const uid = btn.getAttribute("data-user");
      if (!uid) return;
      try {
        await api(`/venues/${encodeURIComponent(venueId)}/shifts/${encodeURIComponent(shiftId)}/assignments/${encodeURIComponent(uid)}`, {
          method: "DELETE",
        });
        toast("Удалено", "ok");
        await reloadCurrentView();
        openDay(dateStr);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось удалить", "err");
      }
    };
  });
}

function canEditDay(dateStr) {
  if (!canEdit) return false;
  if (myRole === "OWNER" || myRole === "SUPER_ADMIN") return true;
  // прошедшие дни — только owner/superadmin
  return !isPastDay(dateStr);
}

function openDay(dateStr) {
  const listAll = shiftsByDate.get(dateStr) || [];
  const list = listAll; // в модалке показываем всех

  const allowEdit = canEditDay(dateStr);

  const title = formatDateRuNoG(dateStr);
  const subtitle = allowEdit ? "Редактирование" : "Просмотр";

  let html = `
    <div class="row" style="justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
      <div>
        ${(!allowEdit && canEdit && isPastDay(dateStr)) ? `<div class="muted" style="margin-top:4px">Прошедшие дни может редактировать только владелец</div>` : ``}
      </div>
      ${allowEdit ? `<button class="btn primary" id="btnAddShift" style="margin-top:6px">+ Добавить смену</button>` : ``}
    </div>
  `;

  if (!list.length) {
    html += `<div class="card" style="margin-top:12px"><div class="muted">На этот день смен нет</div></div>`;
  } else {
    html += `<div class="stack" style="margin-top:12px">`;
    for (const s of list) html += renderShiftCard(s, allowEdit);
    html += `</div>`;
  }

  if (allowEdit) {
    html += `
      <div class="card" style="margin-top:12px; display:none" id="addShiftCard">
        <b>Новая смена</b>
        <div class="muted" style="margin-top:6px">Выбери промежуток и создай смену на этот день</div>

        <div class="row" style="margin-top:10px; gap:10px; flex-wrap:wrap">
          <select class="input" id="intervalSelect" style="flex:1; min-width:220px"></select>
          <button class="btn primary" id="createShiftBtn">Создать смену</button>
        </div>

        <div id="createIntervalBox" class="card" style="margin-top:10px; display:none; background: var(--surface2)">
          <b>Новый промежуток</b>
          <div class="grid2" style="margin-top:10px">
            <input class="input" id="newIntTitle" placeholder="Название (например, Бар)" />
            <div class="row" style="margin-top:10px">
              <input class="input" id="newIntStart" placeholder="Начало (HH:MM)" />
              <input class="input" id="newIntEnd" placeholder="Конец (HH:MM)" />
            </div>
          </div>
          <div class="row" style="margin-top:10px; gap:10px; justify-content:flex-end">
            <button class="btn" id="cancelCreateInterval">Отмена</button>
            <button class="btn primary" id="createIntervalBtn">Создать промежуток</button>
          </div>
        </div>
      </div>
    `;
  }

  openModal(title, subtitle, html);
  document.getElementById("btnOpenAdjustments")?.addEventListener("click", () => {
    const vid = getActiveVenueId();
    if (!vid) return toast("Не выбрано заведение", "err");
    window.location.href = `/staff-adjustments.html?venue_id=${encodeURIComponent(vid)}&date=${encodeURIComponent(dateStr)}`;
  });


  if (allowEdit) {

  const btn = document.getElementById("btnAddShift");
  const card = document.getElementById("addShiftCard");
  const sel = document.getElementById("intervalSelect");
  const createBtn = document.getElementById("createShiftBtn");

  if (btn && card) {
    btn.onclick = () => {
      card.style.display = card.style.display === "none" ? "block" : "none";
    };
  }

  if (sel) {
    sel.innerHTML = "";

    for (const i of intervals) {
      const opt = document.createElement("option");
      opt.value = String(i.id);
      opt.textContent = `${i.title} · ${i.start_time}-${i.end_time}`;
      sel.appendChild(opt);
    }

    const optCreate = document.createElement("option");
    optCreate.value = "__create__";
    optCreate.textContent = "Создать промежуток…";
    sel.appendChild(optCreate);

    if (!intervals.length) sel.value = "__create__";

    const box = document.getElementById("createIntervalBox");
    const btnCancel = document.getElementById("cancelCreateInterval");
    const btnCreateInt = document.getElementById("createIntervalBtn");

    const syncBox = () => {
      const isCreate = sel.value === "__create__";
      if (box) box.style.display = isCreate ? "block" : "none";
      if (createBtn) createBtn.disabled = isCreate;
    };

    sel.onchange = syncBox;
    syncBox();

    if (btnCancel) {
      btnCancel.onclick = () => {
        if (intervals.length) sel.value = String(intervals[0].id);
        syncBox();
      };
    }

    if (btnCreateInt) {
      btnCreateInt.onclick = async () => {
        const title = document.getElementById("newIntTitle")?.value?.trim();
        const start = document.getElementById("newIntStart")?.value?.trim();
        const end = document.getElementById("newIntEnd")?.value?.trim();

        if (!title) return toast("Укажи название", "warn");
        if (!/^\d{2}:\d{2}$/.test(start || "")) return toast("Начало в формате HH:MM", "warn");
        if (!/^\d{2}:\d{2}$/.test(end || "")) return toast("Конец в формате HH:MM", "warn");

        try {
          await api(`/venues/${encodeURIComponent(venueId)}/shift-intervals`, {
            method: "POST",
            body: { title, start_time: start, end_time: end }
          });
          toast("Промежуток создан", "ok");
          await loadContext();
          await reloadCurrentView();
          openDay(dateStr);
        } catch (e) {
          toast(e?.data?.detail || e?.message || "Не удалось создать промежуток", "err");
        }
      };
    }
  }

  if (createBtn) {
    createBtn.onclick = async () => {
      const intervalId = document.getElementById("intervalSelect")?.value;
      if (!intervalId) return toast("Выбери промежуток", "warn");
      if (intervalId === "__create__") return toast("Сначала создай промежуток", "warn");

      try {
        await api(`/venues/${encodeURIComponent(venueId)}/shifts`, {
          method: "POST",
          body: { date: dateStr, interval_id: Number(intervalId) },
        });
        toast("Смена создана", "ok");
        await reloadCurrentView();
        openDay(dateStr);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось создать смену", "err");
      }
    };
  }
  }

  // wire cards (comments must work even on past days; comments disabled in global mode)
  for (const s of list) {
    wireShiftEditor(dateStr, s, allowEdit);
    if (calendarScope !== "global") wireShiftComments((s.id ?? s.shift_id));
  }

}

// navigation (month/week)
el.prev.onclick = async () => {
  if (calendarView === "week") {
    if (!curWeekStart) curWeekStart = startOfWeek(new Date());
    curWeekStart = addDays(curWeekStart, -7);
    await loadWeek();
    return;
  }
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonth();
};

el.next.onclick = async () => {
  if (calendarView === "week") {
    if (!curWeekStart) curWeekStart = startOfWeek(new Date());
    curWeekStart = addDays(curWeekStart, 7);
    await loadWeek();
    return;
  }
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonth();
};

// boot
await loadContext();
renderModeToggle();
renderViewToggle();

// initial load
if (calendarView === "week") {
  if (!curWeekStart) curWeekStart = startOfWeek(new Date());
  await loadWeek();
} else {
  await loadMonth();
}

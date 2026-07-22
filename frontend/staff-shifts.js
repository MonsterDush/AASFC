import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  confirmModal,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMe,
  getMyVenues,
  getMyVenuePermissions,
  getVenueSettings,
  getVenuePositions,
  isDemoUiMode,
  getStoredDemoUiState,
  getDemoMonthLabel,
  mountDemoPageTour,
} from "/app.js?v=20260722-dynamic1";

import { permSetFromResponse, roleUpper, hasPerm, hasAnyPerm, hasPermPrefix } from "/permissions.js?v=20260321-miniappfix1";

import { createStaffShiftExportController } from "/staff-shifts/export-controller.js?v=20260719-split1";
import { createStaffShiftCalendarController } from "/staff-shifts/calendar-controller.js?v=20260720-unified6";

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


function withTimeout(promise, ms, label = "REQUEST_TIMEOUT") {
  let timer = null;
  return new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      const err = new Error(label);
      err.code = "TIMEOUT";
      reject(err);
    }, ms);
    Promise.resolve(promise).then(
      (value) => { clearTimeout(timer); resolve(value); },
      (error) => { clearTimeout(timer); reject(error); },
    );
  });
}

async function startupApi(path, timeoutMs = 10000, label = "STARTUP_TIMEOUT") {
  return withTimeout(api(path), timeoutMs, label);
}
applyTelegramTheme();
mountCommonUI("shifts");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
const DEMO_STAFF_INTRO_DISMISSED_KEY = "axelio.demo_intro.staff_shifts.dismissed";
const DEMO_MODE = isDemoUiMode(getStoredDemoUiState());

function shouldShowDemoSalaryValue(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return false;
  if (!DEMO_MODE) return true;
  return num > 0;
}

function renderDemoStaffIntro() {
  const intro = document.getElementById("demoStaffIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) { intro.classList.add("hidden"); return; }
  try { if (sessionStorage.getItem(DEMO_STAFF_INTRO_DISMISSED_KEY) === "1") { intro.classList.add("hidden"); return; } } catch {}
  const introText = document.getElementById("demoStaffIntroText");
  if (introText) introText.textContent = `Подготовленный график за ${getDemoMonthLabel(demoState) || "DEMO-месяц"}. Здесь смотри индикаторы смен и затем переходи к начислениям.`;
  document.getElementById("demoOpenStaffSalary")?.addEventListener("click", () => { const v = venueId || getActiveVenueId(); if (v) location.href = `/staff-salary.html?venue_id=${encodeURIComponent(String(v))}`; });
  document.getElementById("demoStaffIntroClose")?.addEventListener("click", () => { intro.classList.add("hidden"); try { sessionStorage.setItem(DEMO_STAFF_INTRO_DISMISSED_KEY, "1"); } catch {} });
  intro.classList.remove("hidden");
}

function mountDemoFlowTour() {
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) return;
  const v = venueId || getActiveVenueId();
  const q = v ? `?venue_id=${encodeURIComponent(String(v))}` : "";
  mountDemoPageTour({
    tourId: "demo-staff-flow",
    step: 1,
    total: 2,
    title: "Быстрый тур для персонала",
    text: "Сначала посмотри график и индикаторы смен, затем открой начисления за подготовленный месяц.",
    nextPath: `/staff-salary.html${q}`,
    finishPath: `/staff-shifts.html${q}`,
  });
}

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
  btnIntervals: document.getElementById("btnIntervals"),
  legendModal: document.getElementById("legendModal"),
  legendBody: document.getElementById("legendBody"),
  scheduleFilters: document.getElementById("scheduleFilters"),
  scheduleIntervalList: document.getElementById("scheduleIntervalList"),
  scheduleFilterMenu: document.getElementById("scheduleFilterMenu"),
  scheduleFilterScopeNote: document.getElementById("scheduleFilterScopeNote"),
  btnScheduleFiltersToggle: document.getElementById("btnScheduleFiltersToggle"),
  btnResetScheduleFilters: document.getElementById("btnResetScheduleFilters"),
  btnUnstaffedOnly: document.getElementById("btnUnstaffedOnly"),
  btnExportImage: document.getElementById("btnExportImage"),
  exportModal: document.getElementById("exportModal"),
  exportStatus: document.getElementById("exportStatus"),
  exportPreviewImage: document.getElementById("exportPreviewImage"),
  exportModalSubtitle: document.getElementById("exportModalSubtitle"),
  shiftSlotToggle: document.getElementById("shiftSlotToggle"),
  slotDay: document.getElementById("slotDay"),
  slotNight: document.getElementById("slotNight"),
  btnExportShare: document.getElementById("btnExportShare"),
  btnExportTelegram: document.getElementById("btnExportTelegram"),
  btnExportDownload: document.getElementById("btnExportDownload"),
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
const LS_FILTERS_PREFIX = "axelio.shifts.filters";
let calendarView = (params.get("view") || localStorage.getItem(LS_VIEW) || "month");
if (calendarView !== "week") calendarView = "month";

let curWeekStart = null; // Date (Monday)
let selectedIntervalIds = new Set();
let unstaffedOnly = false;
loadScheduleFilters();

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
        <div class="legend__swatch" style="--interval-color:${escapeHtml(c)}"></div>
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

function filtersStorageKey() {
  return `${LS_FILTERS_PREFIX}.${venueId || "unknown"}`;
}

function parseIntervalIdsRaw(raw) {
  if (!raw) return [];
  return String(raw)
    .split(",")
    .map((x) => Number(String(x).trim()))
    .filter((x) => Number.isInteger(x) && x > 0);
}

function loadScheduleFilters() {
  let ids = [];
  let unstaffed = false;
  const urlIntervals = parseIntervalIdsRaw(params.get("intervals"));
  const hasUrlIntervals = params.has("intervals");
  const hasUrlUnstaffed = params.has("unstaffed");
  if (hasUrlIntervals || hasUrlUnstaffed) {
    ids = urlIntervals;
    unstaffed = ["1", "true", "yes", "on"].includes(String(params.get("unstaffed") || "").toLowerCase());
  } else {
    try {
      const raw = JSON.parse(localStorage.getItem(filtersStorageKey()) || "{}");
      ids = parseIntervalIdsRaw(raw?.interval_ids || "");
      unstaffed = !!raw?.unstaffed_only;
    } catch {}
  }
  selectedIntervalIds = new Set(ids.map((x) => String(x)));
  unstaffedOnly = !!unstaffed;
}

function persistScheduleFilters() {
  const ids = Array.from(selectedIntervalIds)
    .map((x) => Number(x))
    .filter((x) => Number.isInteger(x) && x > 0)
    .sort((a, b) => a - b);
  try {
    localStorage.setItem(filtersStorageKey(), JSON.stringify({ interval_ids: ids.join(","), unstaffed_only: !!unstaffedOnly }));
  } catch {}
}

function pruneSelectedIntervalsAgainstActiveList() {
  const allowed = new Set((Array.isArray(intervals) ? intervals : []).map((it) => String(it?.id ?? "")).filter(Boolean));
  const next = new Set();
  for (const id of selectedIntervalIds) {
    if (allowed.has(String(id))) next.add(String(id));
  }
  selectedIntervalIds = next;
}

function venueShiftFiltersQuery() {
  const p = new URLSearchParams();
  const ids = Array.from(selectedIntervalIds)
    .map((x) => Number(x))
    .filter((x) => Number.isInteger(x) && x > 0)
    .sort((a, b) => a - b);
  for (const id of ids) p.append("interval_ids", String(id));
  if (unstaffedOnly) p.set("staffing_state", "unstaffed");
  if (nightShiftsEnabled) p.set("shift_slot", selectedShiftSlot);
  return p;
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
  return uid ? "Сотрудник" : "—";
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
  return uid ? "Сотрудник" : "—";
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

// отображение денег/выручки завязано на правах просмотра отчётов (SHIFT_REPORT_*/REPORTS_*)
let canViewRevenue = false;

const LS_SHOW_ALL = "axelio.shifts.showAll";
const LS_SCOPE = "axelio.shifts.scope"; // 'venue' | 'global'
const LS_SHIFT_SLOT = "axelio.staff_shifts.shift_slot";
let nightShiftsEnabled = false;
function normalizeShiftSlot(value) {
  return String(value || "DAY").trim().toUpperCase() === "NIGHT" ? "NIGHT" : "DAY";
}
function shiftSlotLabel(slot = selectedShiftSlot) {
  return normalizeShiftSlot(slot) === "NIGHT" ? "Ночь" : "День";
}
const NIGHT_FROM_RU = ["понедельника", "вторника", "среды", "четверга", "пятницы", "субботы", "воскресенья"];
const NIGHT_TO_RU = ["вторник", "среду", "четверг", "пятницу", "субботу", "воскресенье", "понедельник"];
function shiftSlotContextLabel(dateISO, slot = selectedShiftSlot) {
  if (normalizeShiftSlot(slot) !== "NIGHT") return "День";
  try {
    const d = new Date(String(dateISO || "") + "T00:00:00");
    if (!Number.isNaN(d.getTime())) {
      const idx = (d.getDay() + 6) % 7;
      return `Ночь с ${NIGHT_FROM_RU[idx]} на ${NIGHT_TO_RU[idx]}`;
    }
  } catch {}
  return "Ночь";
}
let selectedShiftSlot = normalizeShiftSlot(params.get("shift_slot") || localStorage.getItem(LS_SHIFT_SLOT) || localStorage.getItem("axelio.shift_slot") || "DAY");
let showAllOnCalendar = false;
let calendarScope = localStorage.getItem(LS_SCOPE) === "global" ? "global" : "venue";
let isMultiVenue = false;

let curMonth = new Date();
let selectedDate = null;
curMonth.setDate(1);
const __demoState = getStoredDemoUiState();
if (isDemoUiMode(__demoState) && !params.get("month")) {
  const demoYear = Number(__demoState?.demo_reference_year || 0);
  const demoMonth = Number(__demoState?.demo_reference_month || 0);
  if (demoYear >= 2000 && demoMonth >= 1 && demoMonth <= 12) {
    curMonth = new Date(demoYear, demoMonth - 1, 1);
    const p = new URLSearchParams(location.search);
    p.set("month", ym(curMonth));
    history.replaceState({}, "", `${location.pathname}?${p.toString()}`);
  }
}

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
let currentVenueName = "";
let currentVenues = [];
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

  const demoMode = isDemoUiMode();
  const canUseAllMode = canEdit || demoMode;

  // показываем переключатель:
  // - редактор расписания (canEdit) => "Все/Только мои"
  // - DEMO => всегда "Все/Только мои"
  // - сотрудник с 2+ заведениями => добавляется "Общий"
  if (!canUseAllMode && !isMultiVenue) {
    mode.box.classList.add("hidden");
    return;
  }

  // В Sprint-2 версии блок мог быть скрыт классом .hidden (display:none!important).
  // Убираем этот класс при показе, иначе переключатель не появится.
  mode.box.classList.remove("hidden");

  // видимость кнопок
  mode.all?.classList.toggle("hidden", !canUseAllMode);
  mode.mine?.classList.remove("hidden");
  mode.global?.classList.toggle("hidden", !isMultiVenue);

  const setActive = () => {
    // editor toggle
    mode.all?.classList.toggle("active", canUseAllMode && calendarScope === "venue" && !!showAllOnCalendar);
    mode.mine?.classList.toggle("active", calendarScope === "venue" && !showAllOnCalendar);
    mode.global?.classList.toggle("active", calendarScope === "global");
  };

  const setScope = (scope) => {
  calendarScope = scope;
  localStorage.setItem(LS_SCOPE, scope);

  // When switching away from venue scope, "All" is not applicable.
  if (scope !== "venue") {
    showAllOnCalendar = false;
    localStorage.setItem(LS_SHOW_ALL, "0");
  }

  setActive();
  renderShiftSlotToggle();
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
    showAllOnCalendar = false;
    localStorage.setItem(LS_SHOW_ALL, "0");
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

    p.delete("intervals");
    p.delete("unstaffed");
    const ids = Array.from(selectedIntervalIds)
      .map((x) => Number(x))
      .filter((x) => Number.isInteger(x) && x > 0)
      .sort((a, b) => a - b);
    if (ids.length) p.set("intervals", ids.join(","));
    if (unstaffedOnly) p.set("unstaffed", "1");
    if (nightShiftsEnabled) p.set("shift_slot", selectedShiftSlot);
    else p.delete("shift_slot");

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

function renderShiftSlotToggle() {
  const box = el.shiftSlotToggle;
  if (!box) return;
  const shouldShow = !!nightShiftsEnabled && calendarScope !== "global";
  box.classList.toggle("hidden", !shouldShow);
  if (!nightShiftsEnabled) selectedShiftSlot = "DAY";
  el.slotDay?.classList.toggle("active", selectedShiftSlot === "DAY");
  el.slotNight?.classList.toggle("active", selectedShiftSlot === "NIGHT");
}

async function switchShiftSlot(slot) {
  const next = normalizeShiftSlot(slot);
  if (!nightShiftsEnabled && next === "NIGHT") return;
  if (next === selectedShiftSlot) return;
  selectedShiftSlot = next;
  try {
    localStorage.setItem(LS_SHIFT_SLOT, selectedShiftSlot);
    localStorage.setItem("axelio.shift_slot", selectedShiftSlot);
  } catch {}
  renderShiftSlotToggle();
  syncUrl();
  await reloadCurrentView();
}

el.slotDay?.addEventListener("click", () => switchShiftSlot("DAY"));
el.slotNight?.addEventListener("click", () => switchShiftSlot("NIGHT"));

async function reloadCurrentView() {
  return (calendarView === "week") ? loadWeek() : loadMonth();
}

function renderScheduleFilters() {
  const listEl = el.scheduleIntervalList;
  const noteEl = el.scheduleFilterScopeNote;
  if (!listEl) return;

  const isGlobal = calendarScope === "global";
  const hasActiveFilters = !!unstaffedOnly || selectedIntervalIds.size > 0;
  el.scheduleFilters?.classList.toggle("hidden", false);
  el.scheduleFilters?.classList.toggle("has-active", hasActiveFilters);
  el.btnScheduleFiltersToggle?.classList.toggle("active", hasActiveFilters);
  noteEl?.classList.toggle("hidden", !isGlobal);
  listEl.innerHTML = "";
  el.btnUnstaffedOnly?.classList.toggle("active", !!unstaffedOnly);
  el.btnUnstaffedOnly && (el.btnUnstaffedOnly.disabled = isGlobal);
  el.btnResetScheduleFilters && (el.btnResetScheduleFilters.disabled = isGlobal);

  const items = Array.isArray(intervals) ? intervals.slice().sort((a, b) => intervalSortKey(a).localeCompare(intervalSortKey(b))) : [];
  if (!isGlobal) {
    for (const it of items) {
      const id = String(it?.id ?? "");
      if (!id) continue;
      const label = document.createElement("label");
      label.className = "schedule-check";
      label.innerHTML = `
        <input type="checkbox" ${selectedIntervalIds.has(id) ? "checked" : ""} />
        <span class="schedule-check__text">
          <span class="schedule-check__title">${escapeHtml(it.title || "Интервал")}</span>
          <span class="schedule-check__meta">${escapeHtml(it.start_time || "?")}-${escapeHtml(it.end_time || "?")}</span>
        </span>
      `;
      const input = label.querySelector("input");
      input?.addEventListener("change", async () => {
        if (input.checked) selectedIntervalIds.add(id);
        else selectedIntervalIds.delete(id);
        persistScheduleFilters();
        renderScheduleFilters();
        await reloadCurrentView();
      });
      listEl.appendChild(label);
    }
  }
}

function hasAssignments(shift) {
  return ((shift?.assignments || shift?.shift_assignments || []).length || 0) > 0;
}


let scheduleFilterMenuOpen = false;

function positionScheduleFilterMenu() {
  const menu = el.scheduleFilterMenu;
  const trigger = el.btnScheduleFiltersToggle;
  if (!menu || !trigger || menu.classList.contains("hidden")) return;

  const pad = 12;
  const triggerRect = trigger.getBoundingClientRect();
  const menuWidth = Math.min(360, Math.max(280, window.innerWidth - pad * 2));

  menu.style.setProperty("--filter-menu-width", `${menuWidth}px`);
  menu.style.setProperty("--filter-menu-max-width", `${Math.max(240, window.innerWidth - pad * 2)}px`);

  const menuRect = menu.getBoundingClientRect();
  let left = triggerRect.left + (triggerRect.width / 2) - (menuRect.width / 2);
  left = Math.max(pad, Math.min(left, window.innerWidth - pad - menuRect.width));

  let top = triggerRect.bottom + 8;
  const fitsBelow = top + menuRect.height <= window.innerHeight - pad;
  const fitsAbove = triggerRect.top - 8 - menuRect.height >= pad;
  if (!fitsBelow && fitsAbove) top = triggerRect.top - 8 - menuRect.height;
  else if (!fitsBelow) top = Math.max(pad, window.innerHeight - pad - menuRect.height);

  menu.style.setProperty("--filter-menu-left", `${Math.round(left)}px`);
  menu.style.setProperty("--filter-menu-top", `${Math.round(top)}px`);
}

function setScheduleFilterMenuOpen(open) {
  scheduleFilterMenuOpen = !!open;
  el.scheduleFilters?.classList.toggle("open", scheduleFilterMenuOpen);
  el.scheduleFilterMenu?.classList.toggle("hidden", !scheduleFilterMenuOpen);
  if (el.btnScheduleFiltersToggle) el.btnScheduleFiltersToggle.setAttribute("aria-expanded", scheduleFilterMenuOpen ? "true" : "false");
  if (scheduleFilterMenuOpen) requestAnimationFrame(positionScheduleFilterMenu);
}

el.btnScheduleFiltersToggle?.addEventListener("click", (ev) => {
  ev.preventDefault();
  ev.stopPropagation();
  setScheduleFilterMenuOpen(!scheduleFilterMenuOpen);
});

document.addEventListener("click", (ev) => {
  if (!scheduleFilterMenuOpen) return;
  if (el.scheduleFilters?.contains(ev.target)) return;
  setScheduleFilterMenuOpen(false);
});

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && scheduleFilterMenuOpen) setScheduleFilterMenuOpen(false);
});

window.addEventListener("resize", () => {
  if (scheduleFilterMenuOpen) positionScheduleFilterMenu();
});

window.addEventListener("scroll", () => {
  if (scheduleFilterMenuOpen) positionScheduleFilterMenu();
}, true);

el.btnResetScheduleFilters?.addEventListener("click", async () => {
  selectedIntervalIds = new Set();
  unstaffedOnly = false;
  persistScheduleFilters();
  renderScheduleFilters();
  await reloadCurrentView();
});

el.btnUnstaffedOnly?.addEventListener("click", async () => {
  if (calendarScope === "global") return;
  unstaffedOnly = !unstaffedOnly;
  persistScheduleFilters();
  renderScheduleFilters();
  await reloadCurrentView();
});


async function loadContext() {
  if (!venueId) return;

  me = await getMe().catch(() => null);
  const venuesList = await getMyVenues().catch(() => []);
  currentVenues = Array.isArray(venuesList) ? venuesList : [];
  currentVenueName = currentVenues.find((v) => String(v?.id ?? "") === String(venueId))?.name || currentVenueName || "Заведение";
  isMultiVenue = Array.isArray(venuesList) && venuesList.length >= 2;

  perms = await getMyVenuePermissions(venueId).catch(() => null);

  try {
    const settings = await getVenueSettings(venueId);
    nightShiftsEnabled = !!settings?.night_shifts_enabled;
  } catch {
    nightShiftsEnabled = false;
  }
  if (!nightShiftsEnabled) selectedShiftSlot = "DAY";
  try {
    localStorage.setItem(LS_SHIFT_SLOT, selectedShiftSlot);
    localStorage.setItem("axelio.shift_slot", selectedShiftSlot);
  } catch {}

  myRole = roleUpper(perms) || null;

  const pset = permSetFromResponse(perms);

  const sys = String(me?.system_role || "").toUpperCase();
  const isAdmin = sys === "SUPER_ADMIN" || sys === "MODERATOR";
  const isOwner = myRole === "OWNER" || myRole === "VENUE_OWNER";

  canEdit = isOwner || isAdmin || hasPerm(pset, "SHIFTS_MANAGE");

  // numbers on calendar (salary / revenue) should be shown only to report viewers
  canViewRevenue =
    hasPermPrefix(pset, "SHIFT_REPORT_") ||
    hasPermPrefix(pset, "REPORTS_") ||
    hasAnyPerm(pset, ["SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_REOPEN"]);

  // default: editor and DEMO see all
  showAllOnCalendar = (canEdit || DEMO_MODE) ? true : false;
  const saved = localStorage.getItem(LS_SHOW_ALL);
  if (!DEMO_MODE && saved !== null) showAllOnCalendar = saved === "1";

  try {
    const out = await startupApi(`/venues/${encodeURIComponent(venueId)}/shift-intervals`, 10000, "SHIFT_INTERVALS_TIMEOUT");
    intervals = normalizeList(out).filter(x => x && (x.is_active === undefined || x.is_active));
  } catch { intervals = []; }

  pruneSelectedIntervalsAgainstActiveList();
  persistScheduleFilters();

  buildIntervalColorMap();

  try {
    const out = await getVenuePositions(venueId);
    positions = normalizeList(out).filter(p => p && (p.is_active === undefined || p.is_active));
  } catch { positions = []; }

  el.btnIntervals?.classList.toggle("hidden", !canEdit);
  if (el.btnIntervals && canEdit) {
    el.btnIntervals.onclick = () => {
      location.href = `/shift-intervals.html?venue_id=${encodeURIComponent(venueId)}`;
    };
  }

  renderShiftSlotToggle();
  renderScheduleFilters();
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

function shiftDonePrefix(item) {
  return shiftIsClosed(item) ? "✓ " : "";
}

function formatGlobalLine(item) {
  const venueName = item?.venue?.name || "Заведение";
  const t = shiftStartHHMM(item) || (item?.interval?.start_time ? String(item.interval.start_time).slice(0, 5) : "");
  const base = t ? `${venueName} • ${t}` : `${venueName}`;
  return `${shiftDonePrefix(item)}${base}`;
}

async function loadMyGlobalShifts(monthStr) {
  const out = await startupApi(`/me/shifts?month=${encodeURIComponent(monthStr)}`, 10000, "MY_SHIFTS_TIMEOUT").catch(() => []);
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
      const q = venueShiftFiltersQuery();
      q.set("month", m);
      const out = await startupApi(`/venues/${encodeURIComponent(venueId)}/shifts?${q.toString()}`, 10000, "VENUE_SHIFTS_MONTH_TIMEOUT");
      shifts = normalizeList(out);
      globalShifts = [];
    }
  } catch (e) {
    shifts = [];
    globalShifts = [];
    toast(e?.message || "Не удалось загрузить смены", "err");
  }

  buildIndex();
  renderScheduleFilters();
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

  el.monthLabel.textContent = nightShiftsEnabled ? `${weekTitle(ws)} · ${shiftSlotLabel(selectedShiftSlot)}` : weekTitle(ws);
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
        const q = venueShiftFiltersQuery();
        q.set("date_from", fromISO);
        q.set("date_to", toISO);
        const out = await startupApi(`/venues/${encodeURIComponent(venueId)}/shifts?${q.toString()}`, 10000, "VENUE_SHIFTS_RANGE_TIMEOUT");
        shifts = normalizeList(out).filter(s => s?.date && isoInRange(s.date, fromISO, toISO));
      } catch (e1) {
        const m1 = ym(ws);
        const m2 = ym(we);
        const q1 = venueShiftFiltersQuery();
        q1.set("month", m1);
        const q2 = venueShiftFiltersQuery();
        q2.set("month", m2);
        const out1 = await startupApi(`/venues/${encodeURIComponent(venueId)}/shifts?${q1.toString()}`, 10000, "VENUE_SHIFTS_MONTH_TIMEOUT");
        const out2 = (m2 === m1) ? [] : await startupApi(`/venues/${encodeURIComponent(venueId)}/shifts?${q2.toString()}`, 10000, "VENUE_SHIFTS_MONTH_TIMEOUT");
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
  renderScheduleFilters();
  renderWeek(ws);

  const today = ymd(new Date());
  if (!selectedDate || !isoInRange(selectedDate, fromISO, toISO)) {
    selectedDate = isoInRange(today, fromISO, toISO) ? today : fromISO;
  }
  selectDate(selectedDate, { noExpand: true });

  try { localStorage.setItem(LS_WEEK_START, fromISO); } catch {}
}

const staffShiftCalendarRuntime = {
  get selectedDate() { return selectedDate; },
  set selectedDate(value) { selectedDate = value; },
  get shiftsByDate() { return shiftsByDate; },
  set shiftsByDate(value) { shiftsByDate = value; },
  get salaryByDate() { return salaryByDate; },
  set salaryByDate(value) { salaryByDate = value; },
  get calendarScope() { return calendarScope; },
  set calendarScope(value) { calendarScope = value; },
  get globalShifts() { return globalShifts; },
  set globalShifts(value) { globalShifts = value; },
  get shifts() { return shifts; },
  set shifts(value) { shifts = value; },
  get curMonth() { return curMonth; },
  set curMonth(value) { curMonth = value; },
  get me() { return me; },
  set me(value) { me = value; },
  get canEdit() { return canEdit; },
  set canEdit(value) { canEdit = value; },
  get showAllOnCalendar() { return showAllOnCalendar; },
  set showAllOnCalendar(value) { showAllOnCalendar = value; },
  get nightShiftsEnabled() { return nightShiftsEnabled; },
  set nightShiftsEnabled(value) { nightShiftsEnabled = value; },
  get selectedShiftSlot() { return selectedShiftSlot; },
  set selectedShiftSlot(value) { selectedShiftSlot = value; },
};
const staffShiftCalendar = createStaffShiftCalendarController({
  runtime: staffShiftCalendarRuntime,
  toast,
  DEMO_MODE,
  shouldShowDemoSalaryValue,
  el,
  toHHMM,
  pad2,
  ym,
  ymd,
  addDays,
  WEEKDAYS,
  isPastDay,
  colorForInterval,
  escapeHtml,
  pickShortName,
  displayPerson,
  shiftSlotLabel,
  shiftIntervalId,
  shiftStartHHMM,
  sortShiftsForBadges,
  shiftDonePrefix,
  formatGlobalLine,
  canEditDay,
  openDay,
});
const { renderWeek, buildIndex, defaultSelectedDateForMonth, selectDate, monthTitle, formatDateRuNoG, filterForCalendar, shiftIsClosed, renderMonth } = staffShiftCalendar;
function renderShiftCard(s, allowEdit) {
  const title = shiftIntervalTitle(s);
  const time = shiftTimeLabel(s).replace("-", "–");
  const shiftId = (s.id ?? s.shift_id);
  const intColor = colorForInterval(shiftIntervalId(s));
  const canComment = calendarScope !== "global";

  const assignments = s.assignments || s.shift_assignments || [];
  let peopleHtml = "";
  if (!assignments.length) {
    peopleHtml = `<div class="muted mt-8">Пока никто не назначен</div>`;
  } else {
    peopleHtml =
      `<div class="list mt-8">` +
      assignments.map((a) => {
        const label = displayPerson(a);
        const uname = (a.tg_username || a.member_username || "").trim();
        const unameTxt = uname ? (uname.startsWith("@") ? uname : "@"+uname) : "";
        return `
          <div class="list__row">
            <div class="row row--between ai-center">
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
      <div class="row">
        <select class="input shift-assignee-select" data-posselect data-shift="${shiftId}"></select>
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
        <div class="muted small mt-6">Комментарии доступны в режимах «Все» или «Только мои».</div>
      </div>
    `;

  return `
    <div class="card shiftcard" data-shiftcard="${shiftId}">
      <div class="shiftcard__head">
        <div class="shiftcard__title">
          <div class="shiftcard__line1"><span class="intchip" style="--interval-color:${escapeHtml(intColor)}"></span><b>${escapeHtml(title)}</b>${shiftIsClosed(s) ? `<span class="badge shift-done-badge">✓ закрыта</span>` : ``}</div>
          ${time ? `<div class="shiftcard__meta muted">${escapeHtml(time)}</div>` : ``}
        </div>
        ${allowEdit ? `<button class="btn danger sm" data-delete-shift="${shiftId}" type="button">Удалить смену</button>` : ``}
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
  return u.short_name || u.full_name || (u.tg_username ? "@" + u.tg_username : "Сотрудник");
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

  const btnDeleteShift = card.querySelector(`[data-delete-shift="${shiftId}"]`);
  if (btnDeleteShift) {
    btnDeleteShift.onclick = async () => {
      const assignments = shift.assignments || shift.shift_assignments || [];
      const text = assignments.length
        ? "В этой смене есть назначенные сотрудники. Удалить смену и пересчитать зарплату?"
        : "Удалить этот интервал на выбранный день?";
      const ok = await confirmModal({ title: "Удалить смену?", text, confirmText: "Удалить", danger: true });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(venueId)}/shifts/${encodeURIComponent(shiftId)}`, { method: "DELETE" });
        toast("Смена удалена", "ok");
        await reloadCurrentView();
        openDay(dateStr);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось удалить смену", "err");
      }
    };
  }

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
  const sys = String(me?.system_role || "").toUpperCase();
  const isAdmin = sys === "SUPER_ADMIN" || sys === "MODERATOR";
  const isOwner = myRole === "OWNER" || myRole === "VENUE_OWNER";
  if (isOwner || isAdmin) return true;
  // прошедшие дни — только owner/admin
  return !isPastDay(dateStr);
}

function openDay(dateStr) {
  const listAll = shiftsByDate.get(dateStr) || [];
  const list = listAll; // в модалке показываем всех

  const allowEdit = canEditDay(dateStr);

  const title = nightShiftsEnabled ? `${formatDateRuNoG(dateStr)} · ${shiftSlotContextLabel(dateStr, selectedShiftSlot)}` : formatDateRuNoG(dateStr);
  const subtitle = allowEdit ? "Редактирование" : "Просмотр";

  let html = `
    <div class="row row--between ai-start gap-12">
      <div>
        ${(!allowEdit && canEdit && isPastDay(dateStr)) ? `<div class="muted mt-4">Прошедшие дни может редактировать только владелец</div>` : ``}
      </div>
      ${allowEdit ? `<div class="row gap-8 mt-6"><button class="btn" id="btnManageIntervals">Интервалы</button><button class="btn primary" id="btnAddShift">+ Добавить смену</button></div>` : ``}
    </div>
  `;

  if (!list.length) {
    html += `<div class="card mt-12"><div class="muted">На этот день в режиме «${escapeHtml(shiftSlotContextLabel(dateStr, selectedShiftSlot))}» смен нет</div></div>`;
  } else {
    html += `<div class="stack mt-12">`;
    for (const s of list) html += renderShiftCard(s, allowEdit);
    html += `</div>`;
  }

  if (allowEdit) {
    html += `
      <div class="card mt-12 hidden" id="addShiftCard">
        <b>Новая смена</b>
        <div class="muted mt-6">Выбери промежуток и создай смену на этот день${nightShiftsEnabled ? ` · ${escapeHtml(shiftSlotContextLabel(dateStr, selectedShiftSlot))}` : ""}</div>

        <div class="row mt-10">
          <select class="input shift-interval-select" id="intervalSelect"></select>
          <button class="btn primary" id="createShiftBtn">Создать смену</button>
        </div>

        <div id="createIntervalBox" class="card shift-create-interval mt-10 hidden">
          <b>Новый промежуток</b>
          <div class="grid grid2 mt-10">
            <input class="input" id="newIntTitle" placeholder="Название (например, Бар)" />
            <div class="row mt-10">
              <input class="input" id="newIntStart" placeholder="Начало (HH:MM)" />
              <input class="input" id="newIntEnd" placeholder="Конец (HH:MM)" />
            </div>
          </div>
          <div class="row row--end mt-10">
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
  document.getElementById("btnManageIntervals")?.addEventListener("click", () => {
    location.href = `/shift-intervals.html?venue_id=${encodeURIComponent(venueId)}`;
  });

  const btn = document.getElementById("btnAddShift");
  const card = document.getElementById("addShiftCard");
  const sel = document.getElementById("intervalSelect");
  const createBtn = document.getElementById("createShiftBtn");

  if (btn && card) {
    btn.onclick = () => {
      card.classList.toggle("hidden");
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
      box?.classList.toggle("hidden", !isCreate);
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
          toast("Период создан", "ok");
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
          body: { date: dateStr, interval_id: Number(intervalId), shift_slot: selectedShiftSlot },
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



const staffShiftExportRuntime = {
  get me() { return me; },
  get calendarView() { return calendarView; },
  get curWeekStart() { return curWeekStart; },
  get curMonth() { return curMonth; },
  get selectedShiftSlot() { return selectedShiftSlot; },
  get intervals() { return intervals; },
  get selectedIntervalIds() { return selectedIntervalIds; },
  get calendarScope() { return calendarScope; },
  get showAllOnCalendar() { return showAllOnCalendar; },
  get unstaffedOnly() { return unstaffedOnly; },
  get currentVenueName() { return currentVenueName; },
  get venueId() { return venueId; },
  get shiftsByDate() { return shiftsByDate; },
};
createStaffShiftExportController({
  runtime: staffShiftExportRuntime,
  api,
  toast,
  el,
  pad2,
  ym,
  ymd,
  addDays,
  startOfWeek,
  weekTitle,
  WEEKDAYS,
  colorForInterval,
  fioInitials,
  displayPerson,
  shiftIntervalTitle,
  shiftIntervalId,
  shiftStartHHMM,
  sortShiftsForBadges,
  hasAssignments,
  monthTitle,
  filterForCalendar,
});
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
renderShiftSlotToggle();

// initial load
if (calendarView === "week") {
  if (!curWeekStart) curWeekStart = startOfWeek(new Date());
  await loadWeek();
} else {
  await loadMonth();
}

try { renderDemoStaffIntro(); } catch {}
try { mountDemoFlowTour(); } catch {}

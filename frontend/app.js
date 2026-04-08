import { normalizePermList, permSetFromResponse, roleUpper, hasPerm, hasAnyPerm, hasPermPrefix } from "/permissions.js?v=20260321-miniappfix1";

function normalizeBaseUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  return raw.replace(/\/+$/, "");
}

function readRuntimeApiBase() {
  if (!isBrowser()) return "";
  try {
    const winValue = normalizeBaseUrl(window.APP_CONFIG?.API_BASE || window.__APP_CONFIG__?.API_BASE || "");
    if (winValue) return winValue;
  } catch {}
  try {
    const metaValue = normalizeBaseUrl(document.querySelector('meta[name="api-base"]')?.content || "");
    if (metaValue) return metaValue;
  } catch {}
  return "";
}

function deriveApiBaseFromLocation() {
  if (!isBrowser()) return "";
  const proto = location.protocol === "http:" ? "http:" : "https:";
  const host = String(location.hostname || "").trim().toLowerCase();
  if (!host) return "";

  if (host === "localhost" || host === "127.0.0.1") {
    return `${proto}//${host}:9001`;
  }

  const parts = host.split(".");
  if (parts[0] === "app") {
    parts[0] = "api";
    return `${proto}//${parts.join(".")}`;
  }
  if (parts[0].startsWith("app-")) {
    parts[0] = parts[0].replace(/^app-/, "api-");
    return `${proto}//${parts.join(".")}`;
  }
  if (parts[0] === "api" || parts[0].startsWith("api-")) {
    return `${proto}//${host}`;
  }

  return `${proto}//${host}`;
}

function resolveApiBase() {
  return normalizeBaseUrl(readRuntimeApiBase() || deriveApiBaseFromLocation());
}

export const API_BASE = resolveApiBase();
export const AUTH_PAGE = "/auth.html";

function isBrowser() {
  return typeof window !== "undefined" && typeof location !== "undefined";
}

export function isAuthPage() {
  return isBrowser() && /\/auth\.html$/i.test(location.pathname || "");
}

export function buildAuthUrl(next = "", reason = "") {
  const url = new URL(AUTH_PAGE, location.origin);
  const normalizedNext = String(next || "").trim();
  if (normalizedNext && !/\/auth\.html(\?|$)/i.test(normalizedNext)) {
    url.searchParams.set("next", normalizedNext);
  }
  const normalizedReason = String(reason || "").trim();
  if (normalizedReason) url.searchParams.set("reason", normalizedReason);
  return url.toString();
}

export function redirectToAuth(next = "", reason = "") {
  if (!isBrowser() || isAuthPage()) return;
  const current = next || `${location.pathname || "/"}${location.search || ""}${location.hash || ""}`;
  location.replace(buildAuthUrl(current, reason));
}

const SS_DEMO_UI_STATE = "axelio.demo_ui_state.v1";

export function getStoredDemoUiState() {
  if (!isBrowser()) return null;
  try {
    const raw = sessionStorage.getItem(SS_DEMO_UI_STATE);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? parsed : null;
  } catch {
    return null;
  }
}

export function readStoredDemoUiState() {
  return getStoredDemoUiState();
}

export function storeDemoUiState(state) {
  if (!isBrowser()) return null;
  const next = state && typeof state === "object" ? state : null;
  try {
    if (next) sessionStorage.setItem(SS_DEMO_UI_STATE, JSON.stringify(next));
    else sessionStorage.removeItem(SS_DEMO_UI_STATE);
  } catch {}
  try { window.dispatchEvent(new CustomEvent("axelio:demo-ui-state", { detail: next })); } catch {}
  return next;
}

export function clearDemoUiState() {
  return storeDemoUiState(null);
}

export function isDemoUiMode(state = null) {
  const st = state && typeof state === "object" ? state : getStoredDemoUiState();
  return !!(st && st.demo_mode);
}

export function getDemoMonthLabel(state = null) {
  const st = state && typeof state === "object" ? state : getStoredDemoUiState();
  const year = Number(st?.demo_reference_year || 0);
  const month = Number(st?.demo_reference_month || 0);
  if (!year || !month || month < 1 || month > 12) return "";
  const months = ["январь","февраль","март","апрель","май","июнь","июль","август","сентябрь","октябрь","ноябрь","декабрь"];
  return `${months[month - 1]} ${year}`;
}

export function coerceDemoMonth(year, month, state = null) {
  const st = state && typeof state === "object" ? state : getStoredDemoUiState();
  if (!st?.demo_mode) return { year, month };
  const y = Number(st.demo_reference_year || year || 0);
  const m = Number(st.demo_reference_month || month || 0);
  return { year: y || year, month: m || month };
}

export function coerceDemoDate(input, state = null) {
  const st = state && typeof state === "object" ? state : getStoredDemoUiState();
  if (!st?.demo_mode) return input;
  const year = Number(st.demo_reference_year || 0);
  const month = Number(st.demo_reference_month || 0);
  if (!year || !month) return input;
  const str = String(input || "");
  const m = str.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return input;
  return `${year}-${String(month).padStart(2, '0')}-${m[3]}`;
}

export function coerceDemoRange(range, state = null) {
  const st = state && typeof state === "object" ? state : getStoredDemoUiState();
  if (!st?.demo_mode || !range || typeof range !== "object") return range;
  return {
    ...range,
    date_from: range.date_from ? coerceDemoDate(range.date_from, st) : range.date_from,
    date_to: range.date_to ? coerceDemoDate(range.date_to, st) : range.date_to,
  };
}

export function applyDemoReadonlyCaps(caps, state = null) {
  const st = state && typeof state === "object" ? state : getStoredDemoUiState();
  if (!st?.demo_mode || !caps || typeof caps !== "object") return caps;
  const out = { ...caps };
  for (const key of Object.keys(out)) {
    if (/(create|edit|update|delete|remove|archive|close|reopen|write|manage|calculate|save|invite|upload)/i.test(key)) out[key] = false;
  }
  return out;
}

function removeDemoBanner() {
  const el = document.getElementById("demoBanner");
  if (el) el.remove();
}

function buildDemoBannerMarkup(state) {
  const label = getDemoMonthLabel(state);
  return `
    <div class="demo-banner__inner">
      <div class="demo-banner__title">Пробный режим Axelio${label ? ` · ${label}` : ""}</div>
      <div class="demo-banner__actions">
        <button type="button" class="demo-banner__btn" data-demo-reopen-tour>Экскурсия</button>
      </div>
    </div>
  `;
}

function mountDemoBanner(state = null) {
  if (!isBrowser() || !document.body) return;
  const st = state && typeof state === "object" ? state : getStoredDemoUiState();
  if (!st?.demo_mode) { removeDemoBanner(); return; }
  let host = document.getElementById("demoBanner");
  if (!host) {
    host = document.createElement("div");
    host.id = "demoBanner";
    host.className = "demo-banner";
    document.body.prepend(host);
  }
  host.innerHTML = buildDemoBannerMarkup(st);
  host.querySelector('[data-demo-reopen-tour]')?.addEventListener('click', () => { try { reopenDemoTour(); } catch {} });
}



const SS_DEMO_TOUR_STATE = "axelio.demo_tour_state.v2";
let __demoTourBootstrapped = false;
let __demoTourOverlayVisible = false;

function currentPageFile() {
  if (!isBrowser()) return "";
  const raw = String(location.pathname || "").split("/").pop() || "";
  return raw.toLowerCase() || "index.html";
}

function getDemoTourRoutes(persona = null) {
  const st = getStoredDemoUiState();
  const p = String(persona || st?.demo_persona || "OWNER").toUpperCase();
  const venueId = st?.demo_venue_id || getActiveVenueId() || "";
  const qp = venueId ? `?venue_id=${encodeURIComponent(venueId)}` : "";
  if (p === "STAFF") {
    return [
      {
        key: "staff-shifts",
        path: `/staff-shifts.html${qp}`,
        page: "staff-shifts.html",
        title: "Шаг 1 из 2 · График",
        text: "Здесь сотрудник смотрит смены, занятость по дням и рабочий ритм месяца.",
      },
      {
        key: "staff-salary",
        path: `/staff-salary.html${qp}`,
        page: "staff-salary.html",
        title: "Шаг 2 из 2 · Зарплата",
        text: "Здесь сотрудник видит начисления и итог по заработку. Это финальная точка экскурсии персонала.",
      },
    ];
  }
  return [
    {
      key: "owner-summary",
      path: `/owner-summary.html${qp}`,
      page: "owner-summary.html",
      title: "Шаг 1 из 4 · Сводка",
      text: "Это главный DEMO-экран владельца: доходы, расходы и итог по месяцу.",
    },
    {
      key: "owner-expenses",
      path: `/owner-expenses.html${qp}`,
      page: "owner-expenses.html",
      title: "Шаг 2 из 4 · Расходы",
      text: "Здесь видно структуру расходов, категории и операционные траты месяца.",
    },
    {
      key: "owner-payroll",
      path: `/owner-payroll.html${qp}`,
      page: "owner-payroll.html",
      title: "Шаг 3 из 4 · Начисления",
      text: "На этом экране владелец понимает, из чего складывается фонд оплаты труда.",
    },
    {
      key: "app-venue",
      path: `/app-venue.html${qp}`,
      page: "app-venue.html",
      title: "Шаг 4 из 4 · Карточка заведения",
      text: "Финальная точка owner-экскурсии: настройки, структура заведения и быстрый доступ к разделам.",
    },
  ];
}

function readDemoTourState() {
  if (!isBrowser()) return {};
  try {
    const raw = sessionStorage.getItem(SS_DEMO_TOUR_STATE);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function writeDemoTourState(next) {
  if (!isBrowser()) return;
  try { sessionStorage.setItem(SS_DEMO_TOUR_STATE, JSON.stringify(next || {})); } catch {}
}

function getPersonaTourState(persona = null) {
  const p = String(persona || getStoredDemoUiState()?.demo_persona || "OWNER").toUpperCase();
  const all = readDemoTourState();
  const current = all[p] && typeof all[p] === "object" ? all[p] : {};
  return {
    persona: p,
    hidden: !!current.hidden,
    completed: !!current.completed,
    index: Number.isFinite(Number(current.index)) ? Math.max(0, Number(current.index)) : 0,
    seenIntro: !!current.seenIntro,
  };
}

function updatePersonaTourState(persona, patch = {}) {
  const p = String(persona || "OWNER").toUpperCase();
  const all = readDemoTourState();
  const prev = all[p] && typeof all[p] === "object" ? all[p] : {};
  const next = { ...prev, ...patch };
  all[p] = next;
  writeDemoTourState(all);
  return next;
}

function getCurrentTourStep(persona = null) {
  const routes = getDemoTourRoutes(persona);
  const page = currentPageFile();
  const st = getPersonaTourState(persona);
  let idx = routes.findIndex((x) => String(x.page || "").toLowerCase() === page);
  if (idx < 0) idx = Math.min(st.index || 0, Math.max(routes.length - 1, 0));
  return { routes, index: idx, step: routes[idx] || null, state: st };
}

async function sendDemoEvent(eventName, extra = {}) {
  try {
    if (!isDemoUiMode()) return;
    await api("/demo/event", {
      method: "POST",
      body: { event_name: eventName, ...extra },
      skipDemoReadonlyToast: true,
    });
  } catch {}
}

function removeDemoTourOverlay() {
  const el = document.getElementById("demoTourOverlay");
  if (el) el.remove();
  __demoTourOverlayVisible = false;
}

function removeDemoTourDock() {
  const el = document.getElementById("demoTourDock");
  if (el) el.remove();
}

function renderDemoTourDock() {
  if (!isBrowser() || !document.body || !isDemoUiMode()) {
    removeDemoTourDock();
    return;
  }
  const { routes, index, state } = getCurrentTourStep();
  if (!routes.length || state.completed) {
    removeDemoTourDock();
    return;
  }
  let host = document.getElementById("demoTourDock");
  if (!host) {
    host = document.createElement("div");
    host.id = "demoTourDock";
    host.className = "demo-tour-dock";
    document.body.appendChild(host);
  }
  host.innerHTML = `
    <div class="demo-tour-dock__bar">
      <button type="button" class="demo-tour-dock__btn" data-demo-tour-prev ${index <= 0 ? "disabled" : ""}>Назад</button>
      <button type="button" class="demo-tour-dock__btn demo-tour-dock__btn--primary" data-demo-tour-next>${index >= routes.length - 1 ? "Готово" : "Вперёд"}</button>
      <button type="button" class="demo-tour-dock__btn" data-demo-tour-hide>Скрыть</button>
    </div>
  `;
  host.querySelector("[data-demo-tour-prev]")?.addEventListener("click", () => moveDemoTour(-1));
  host.querySelector("[data-demo-tour-next]")?.addEventListener("click", () => moveDemoTour(1));
  host.querySelector("[data-demo-tour-hide]")?.addEventListener("click", () => hideDemoTour());
}

function showDemoTourOverlay(force = false) {
  if (!isBrowser() || !document.body || !isDemoUiMode()) return;
  const { routes, index, step, state } = getCurrentTourStep();
  if (!step) return;
  if (!force && state.completed) {
    renderDemoTourDock();
    return;
  }
  removeDemoTourOverlay();
  let host = document.createElement("div");
  host.id = "demoTourOverlay";
  host.className = "demo-tour-overlay";
  host.innerHTML = `
    <div class="demo-tour-overlay__backdrop"></div>
    <div class="demo-tour-overlay__card" role="dialog" aria-modal="true" aria-label="Экскурсия DEMO">
      <div class="demo-tour-overlay__eyebrow">Экскурсия</div>
      <div class="demo-tour-overlay__title">${step.title}</div>
      <div class="demo-tour-overlay__text">${step.text}</div>
      <div class="demo-tour-overlay__actions">
        <button type="button" class="btn subtle" data-demo-tour-hide>Скрыть</button>
        <button type="button" class="btn primary" data-demo-tour-continue>${index >= routes.length - 1 ? "Готово" : "Дальше"}</button>
      </div>
    </div>
  `;
  document.body.appendChild(host);
  __demoTourOverlayVisible = true;

  host.querySelector("[data-demo-tour-hide]")?.addEventListener("click", () => hideDemoTour());
  host.querySelector("[data-demo-tour-continue]")?.addEventListener("click", async () => {
    if (index >= routes.length - 1) {
      const persona = getPersonaTourState().persona;
      updatePersonaTourState(persona, { completed: true, hidden: true, index });
      removeDemoTourOverlay();
      removeDemoTourDock();
      await sendDemoEvent("tour_completed", { page_path: currentPageFile(), persona });
      return;
    }
    const persona = getPersonaTourState().persona;
    updatePersonaTourState(persona, { hidden: true, completed: false, index });
    removeDemoTourOverlay();
    renderDemoTourDock();
  });
}

function moveDemoTour(delta = 1) {
  if (!isBrowser() || !isDemoUiMode()) return;
  const { routes, index, state } = getCurrentTourStep();
  const nextIndex = Math.max(0, Math.min(routes.length - 1, index + delta));
  const step = routes[nextIndex];
  const persona = state.persona;
  if (!step) return;
  if (nextIndex === index && delta > 0 && index >= routes.length - 1) {
    updatePersonaTourState(persona, { completed: true, hidden: true, index });
    removeDemoTourOverlay();
    removeDemoTourDock();
    sendDemoEvent("tour_completed", { page_path: currentPageFile(), persona });
    return;
  }
  updatePersonaTourState(persona, { index: nextIndex, hidden: true, completed: false });
  location.href = step.path;
}

function hideDemoTour() {
  if (!isBrowser() || !isDemoUiMode()) return;
  const st = getPersonaTourState();
  updatePersonaTourState(st.persona, { hidden: true });
  removeDemoTourOverlay();
  renderDemoTourDock();
}

export function reopenDemoTour() {
  if (!isBrowser() || !isDemoUiMode()) return;
  const { routes, index, step, state } = getCurrentTourStep();
  if (!routes.length) return;
  const page = currentPageFile();
  let idx = routes.findIndex((x) => x.page === page);
  if (idx < 0) idx = Math.min(state.index || 0, routes.length - 1);
  updatePersonaTourState(state.persona, { hidden: false, completed: false, index: idx });
  showDemoTourOverlay(true);
  renderDemoTourDock();
}

function maybeStartDemoTour() {
  if (!isBrowser() || !isDemoUiMode()) return;
  const { routes, index, step, state } = getCurrentTourStep();
  if (!routes.length || !step) return;
  const page = currentPageFile();
  const isRoutePage = routes.some((x) => x.page === page);
  if (!isRoutePage) {
    removeDemoTourOverlay();
    removeDemoTourDock();
    return;
  }
  renderDemoTourDock();
  if (!state.seenIntro || (!state.hidden && !state.completed)) {
    updatePersonaTourState(state.persona, { seenIntro: true, hidden: false, completed: false, index });
    showDemoTourOverlay(true);
    sendDemoEvent("tour_started", { page_path: page, persona: state.persona });
    return;
  }
  if (state.completed) {
    removeDemoTourOverlay();
    renderDemoTourDock();
    return;
  }
  if (!state.hidden) showDemoTourOverlay();
}

function bootstrapDemoTour() {
  if (!isBrowser() || __demoTourBootstrapped) return;
  __demoTourBootstrapped = true;
  const run = () => setTimeout(() => maybeStartDemoTour(), 150);
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run, { once: true });
  } else {
    run();
  }
  window.addEventListener("axelio:demo-ui-state", () => {
    setTimeout(() => {
      mountDemoBanner();
      maybeStartDemoTour();
    }, 80);
  });
  window.addEventListener("pageshow", () => setTimeout(() => maybeStartDemoTour(), 50));
}

bootstrapDemoTour();


// ------------------------------
// i18n (RU/EN) MVP
// ------------------------------
const LS_LANG = "axelio.lang";
const DICT = {
  ru: {
    venue: "Заведение",
    manage_venues: "Управление заведениями",
    leave_venue: "Выйти из заведения",
    settings: "Настройки",
    adjustments: "Штрафы",
    shifts: "График",
    salary: "Зарплаты",
    report: "Отчёты",
    finance: "Финансы",
    revenue: "Выручка",
    summary: "Сводка",
    expenses: "Расходы",
    admin_venues: "Заведения",
    admin_invites: "Инвайты",
  },
  en: {
    venue: "Venue",
    manage_venues: "Manage venues",
    leave_venue: "Leave venue",
    settings: "Settings",
    adjustments: "Adjustments",
    shifts: "Schedule",
    salary: "Salary",
    report: "Reports",
    finance: "Finance",
    revenue: "Revenue",
    summary: "Summary",
    expenses: "Expenses",
    admin_venues: "Venues",
    admin_invites: "Invites",
  },
};

export function getLang() {
  try { return localStorage.getItem(LS_LANG) || "ru"; } catch { return "ru"; }
}

export function setLang(lang) {
  try { localStorage.setItem(LS_LANG, lang); } catch {}
}

export function t(key) {
  const lang = getLang();
  return (DICT[lang] && DICT[lang][key]) || (DICT.ru && DICT.ru[key]) || key;
}

export function wa() {
  return window.Telegram?.WebApp || null;
}

export function looksLikeTelegramWebApp() {
  try {
    if (wa()) return true;
    if (typeof window.TelegramWebviewProxy !== "undefined") return true;
    if (typeof window.TelegramGameProxy !== "undefined") return true;
    const raw = `${location.search || ""}&${location.hash || ""}`;
    if (/tgWebApp(Data|Version|Platform|ThemeParams|StartParam|BotInline)/i.test(raw)) return true;
    const ua = String(navigator.userAgent || "");
    if (/Telegram/i.test(ua)) return true;
  } catch {}
  return false;
}

export async function ensureTelegramWebAppLoaded({ timeoutMs = 2500 } = {}) {
  if (wa()) return wa();
  try {
    const loader = window.AxelioTelegramLoader;
    if (loader && typeof loader.load === "function") {
      return await loader.load({ timeoutMs });
    }
  } catch {}

  if (!looksLikeTelegramWebApp()) return null;

  return await new Promise((resolve) => {
    let settled = false;
    let timer = null;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      resolve(value || wa() || null);
    };
    const existing = document.querySelector('script[data-axelio-telegram="external"]');
    if (existing) {
      const poll = () => {
        if (wa()) return finish(wa());
        if (!settled) setTimeout(poll, 60);
      };
      poll();
    } else {
      const s = document.createElement("script");
      s.async = true;
      s.src = "https://telegram.org/js/telegram-web-app.js";
      s.setAttribute("data-axelio-telegram", "external");
      s.onload = () => finish(wa());
      s.onerror = () => finish(null);
      document.head.appendChild(s);
    }
    timer = setTimeout(() => finish(null), Math.max(300, Number(timeoutMs) || 2500));
  });
}

// ------------------------------
// Theme (system / light / dark / hookahplace)
// ------------------------------
const LS_THEME = "axelio.theme"; // 'system' | 'light' | 'dark' | 'hookahplace'
const LS_SYS_ROLE = "axelio.system_role"; // cached from /me (used for gated features)

export function cacheSystemRole(role) {
  const v = String(role || "").toUpperCase();
  try {
    if (v) localStorage.setItem(LS_SYS_ROLE, v);
    else localStorage.removeItem(LS_SYS_ROLE);
  } catch {}
}

export function getCachedSystemRole() {
  try { return String(localStorage.getItem(LS_SYS_ROLE) || "").toUpperCase(); } catch { return ""; }
}

export function isSuperAdminCached() {
  return getCachedSystemRole() === "SUPER_ADMIN";
}

export function getThemePref() {
  try {
    const v = (localStorage.getItem(LS_THEME) || "system").trim();
    const allowed = (v === "light" || v === "dark" || v === "system" || v === "hookahplace");
    if (!allowed) return "system";

    // Gate experimental themes by system role
    if (v === "hookahplace" && !isSuperAdminCached()) return "system";

    return v;
  } catch {
    return "system";
  }
}

export function setThemePref(pref) {
  let v = (pref === "light" || pref === "dark" || pref === "system" || pref === "hookahplace")
    ? pref
    : "system";

  if (v === "hookahplace" && !isSuperAdminCached()) v = "system";

  try { localStorage.setItem(LS_THEME, v); } catch {}
}

function ensureThemeMeta() {
  let m = document.querySelector('meta[name="theme-color"]');
  if (!m) {
    m = document.createElement("meta");
    m.setAttribute("name", "theme-color");
    document.head.appendChild(m);
  }
  return m;
}

function syncThemeColorMeta() {
  try {
    const m = ensureThemeMeta();
    const bg = getComputedStyle(document.documentElement).getPropertyValue("--bg").trim();
    // theme-color expects a solid color. Our themes keep --bg as a color (not a gradient).
    if (bg) m.setAttribute("content", bg);
  } catch {}
}

export function applyTheme() {
  const pref = getThemePref();
  const root = document.documentElement;

  // If user explicitly chose a theme, force it via data-theme.
  // If system: remove override and let CSS media query handle it.
  if (pref === "light" || pref === "dark" || pref === "hookahplace") {
    root.setAttribute("data-theme", pref);
  } else {
    root.removeAttribute("data-theme");
  }

  // keep mobile browser UI in sync (address bar color)
  requestAnimationFrame(syncThemeColorMeta);

  // react to system changes only when pref=system
  try {
    if (!root.__themeMqlBound) {
      const mql = window.matchMedia?.("(prefers-color-scheme: dark)");
      if (mql && typeof mql.addEventListener === "function") {
        mql.addEventListener("change", () => {
          if (getThemePref() === "system") requestAnimationFrame(syncThemeColorMeta);
        });
      }
      root.__themeMqlBound = true;
    }
  } catch {}
}

export function applyTelegramTheme() {
  // Our app theme (system/light/dark). Telegram themeParams are not used here,
  // because we want a stable brand theme + user override.
  applyTheme();

  const w = wa();
  const el = document.querySelector("[data-userpill]");
  if (!w) {
    if (el) el.textContent = "не в Telegram";
    if (looksLikeTelegramWebApp()) {
      ensureTelegramWebAppLoaded({ timeoutMs: 1800 }).then((loaded) => {
        if (!loaded) return;
        try { applyTelegramTheme(); } catch {}
      }).catch(() => {});
    }
    return;
  }

  w.ready();

  const u = w.initDataUnsafe?.user;
  if (el) el.textContent = u ? `@${u.username || "без_username"}` : "неизвестно";
  // userpill is hidden globally for a cleaner, unified topbar.
}

export function toast(msg, type = "info") {
  const box = document.getElementById("toast");
  if (!box) return alert(msg);

  box.className = "toast show " + type;
  box.querySelector(".toast__text").textContent = msg;

  clearTimeout(box._t);
  box._t = setTimeout(() => (box.className = "toast"), 2400);
}

export function openModal(title, jsonOrText) {
  const m = document.getElementById("modal");
  if (!m) return;

  m.querySelector(".modal__title").textContent = title;

  const body = m.querySelector(".modal__body");
  if (!body) return;

  body.textContent = "";
  const pre = document.createElement("pre");
  pre.className = "json";
  pre.textContent =
    typeof jsonOrText === "string"
      ? jsonOrText
      : JSON.stringify(jsonOrText, null, 2);

  body.appendChild(pre);
  m.classList.add("open");
}

export function closeModal() {
  const m = document.getElementById("modal");
  if (m) m.classList.remove("open");
}

export function mountLogo() {
  document.querySelectorAll(".logo").forEach(el => {
    if (el.dataset.logoMounted) return;
    el.dataset.logoMounted = "1";

    // очистим, если там что-то было
    el.innerHTML = "";

    const img = document.createElement("img");
    img.src = "/logo.png"; // или /logo.svg
    img.alt = "Axelio";
    img.style.width = "100%";
    img.style.display = "block";

    el.appendChild(img);
  });
}

export function mountCommonUI(activeTab) {
  document.querySelectorAll("[data-tab]").forEach((a) => {
    if (a.getAttribute("data-tab") === activeTab) a.classList.add("active");
  });

  const modal = document.getElementById("modal");
  if (modal) {
    const closeBtn = modal.querySelector("[data-close]");
    const backdrop = modal.querySelector(".modal__backdrop");
    if (closeBtn) closeBtn.onclick = closeModal;
    if (backdrop) backdrop.onclick = closeModal;
  }
  mountLogo();
  document.querySelectorAll("[data-viewjson]").forEach((btn) => {
    btn.onclick = () =>
      openModal(btn.getAttribute("data-title") || "JSON", window.__lastJson || {});
  });
}

function isPlainObject(v) {
  return (
    v !== null &&
    typeof v === "object" &&
    !(v instanceof FormData) &&
    !(v instanceof Blob) &&
    !(v instanceof ArrayBuffer)
  );
}

function extractErrorMessage(data) {
  if (typeof data === "string") return data;

  // FastAPI часто отдаёт {detail: ...}
  if (data && typeof data === "object") {
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      // pydantic validation errors
      return data.detail.map((x) => x?.msg || JSON.stringify(x)).join("; ");
    }
  }
  try {
    return JSON.stringify(data);
  } catch {
    return String(data);
  }
}

/**
 * api("/path", { method:"POST", body: {a:1} })  // body-объект можно
 * api("/path", { method:"POST", body: JSON.stringify({a:1}) }) // тоже ок
 */
export async function api(path, opts = {}) {
  const url = API_BASE + path;

  // auto-jsonify object body (если передали объект)
  let body = opts.body;
  const isForm = (typeof FormData !== "undefined") && (body instanceof FormData);
  if (isPlainObject(body)) body = JSON.stringify(body);

  const handle401 = opts.handle401 !== false;
  const timeoutMs = Number(opts.timeoutMs || 0) > 0 ? Number(opts.timeoutMs) : 0;
  const externalSignal = opts.signal;
  const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
  let timeoutId = null;
  let signal = externalSignal || undefined;

  if (controller) {
    signal = controller.signal;
    if (externalSignal) {
      if (externalSignal.aborted) {
        controller.abort(externalSignal.reason);
      } else {
        externalSignal.addEventListener("abort", () => controller.abort(externalSignal.reason), { once: true });
      }
    }
    if (timeoutMs > 0) {
      timeoutId = setTimeout(() => controller.abort(new DOMException("Request timed out", "AbortError")), timeoutMs);
    }
  }

  let r;
  try {
    // NOTE: Permission checks rely on fresh /me/* responses.
    // Some browsers may cache credentialed GET requests aggressively in certain flows.
    // Default to no-store, allow overriding via opts.cache when needed.
    r = await fetch(url, {
      cache: "no-store",
      ...opts,
      body,
      signal,
      credentials: "include",
      headers: {
        ...(isForm ? {} : { "Content-Type": "application/json" }),
        // extra cache-busting headers (safe no-op for most backends)
        "Cache-Control": "no-cache",
        Pragma: "no-cache",
        ...(opts.headers || {}),
      },
    });
  } catch (e) {
    if (timeoutId) clearTimeout(timeoutId);
    if (e?.name === "AbortError") {
      const err = new Error(`HTTP TIMEOUT: ${path}`);
      err.code = "TIMEOUT";
      err.url = url;
      throw err;
    }
    throw e;
  }

  if (timeoutId) clearTimeout(timeoutId);

  const text = await r.text();
  let data;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!r.ok) {
    const err = new Error(`HTTP ${r.status} ${r.statusText}: ${extractErrorMessage(data)}`);
    err.status = r.status;
    err.data = data;
    err.url = r.url;

    if (r.status === 401 && handle401) {
      redirectToAuth("", "unauthorized");
    }

    throw err;
  }

  return data;
}

function parseDownloadFilename(contentDisposition, fallback = "download") {
  const header = String(contentDisposition || "");

  const starMatch = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (starMatch?.[1]) {
    try {
      return decodeURIComponent(starMatch[1].trim()).replace(/[\r\n]/g, "") || fallback;
    } catch {}
  }

  const plainMatch = header.match(/filename=\"?([^";]+)\"?/i);
  if (plainMatch?.[1]) {
    return plainMatch[1].trim().replace(/[\r\n]/g, "") || fallback;
  }

  return fallback;
}

export async function downloadFile(path, { filenameFallback = "download", opts = {} } = {}) {
  const url = API_BASE + path;
  const r = await fetch(url, {
    cache: "no-store",
    credentials: "include",
    ...opts,
    headers: {
      "Cache-Control": "no-cache",
      Pragma: "no-cache",
      ...(opts.headers || {}),
    },
  });

  if (!r.ok) {
    let data = null;
    try {
      const text = await r.text();
      try { data = text ? JSON.parse(text) : null; } catch { data = text; }
    } catch {}
    const err = new Error(`HTTP ${r.status} ${r.statusText}: ${extractErrorMessage(data)}`);
    err.status = r.status;
    err.data = data;
    err.url = r.url;
    throw err;
  }

  const blob = await r.blob();
  const filename = parseDownloadFilename(r.headers.get("Content-Disposition"), filenameFallback);
  const objectUrl = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
  }

  return { filename };
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function waitForTelegramInitData({ maxMs = 5000, stepMs = 100 } = {}) {
  if (!wa() && looksLikeTelegramWebApp()) {
    try {
      await ensureTelegramWebAppLoaded({ timeoutMs: Math.min(Math.max(stepMs * 5, 1200), maxMs) });
    } catch {}
  }
  const startedAt = Date.now();
  while (Date.now() - startedAt < maxMs) {
    const value = String(wa()?.initData || "").trim();
    if (value) return value;
    await delay(stepMs);
  }
  return "";
}

export async function ensureLogin({ silent = true, redirectOnFail = false, timeoutMs = 5000, telegramWaitMs = 5000 } = {}) {
  try {
    const me = await api("/me", { handle401: false, timeoutMs });
    return { ok: true, data: me, source: "cookie" };
  } catch (e) {
    if (e?.status && e.status !== 401) {
      if (!silent) toast(e?.message || "Ошибка авторизации", "err");
      return { ok: false, status: e?.status, data: e?.data, message: e?.message };
    }
    if (e?.code === "TIMEOUT") {
      return { ok: false, code: "TIMEOUT", message: "Не удалось связаться с API" };
    }
  }

  const initData = await waitForTelegramInitData({ maxMs: telegramWaitMs, stepMs: 100 });

  if (!initData) {
    if (!silent) toast("Нужна авторизация: Telegram или телефон.", "warn");
    if (redirectOnFail) redirectToAuth();
    return { ok: false, reason: "NO_INITDATA" };
  }

  try {
    const out = await api("/auth/telegram", {
      method: "POST",
      body: { initData },
      handle401: false,
      timeoutMs: Math.max(timeoutMs, 10000),
    });

    if (!silent) toast("Вход выполнен", "ok");
    return { ok: true, data: out, source: "telegram" };
  } catch (e) {
    if (!silent) {
      const msg = e?.message || "Ошибка входа";
      toast(msg, "err");
    }
    if (redirectOnFail) redirectToAuth();
    return {
      ok: false,
      code: e?.code,
      status: e?.status,
      data: e?.data,
      message: e?.message,
    };
  }
}

export async function loginWithTelegramWidget(authData) {
  return api("/auth/telegram/widget", {
    method: "POST",
    body: authData || {},
    handle401: false,
  });
}

export async function startTelegramBrowserLogin(nextPath = "") {
  return api("/auth/telegram/browser/start", {
    method: "POST",
    body: { next_path: nextPath || null },
    handle401: false,
    timeoutMs: 8000,
  });
}

export async function getTelegramBrowserLoginStatus(sessionToken) {
  return api(`/auth/telegram/browser/status/${encodeURIComponent(sessionToken)}`, {
    handle401: false,
    timeoutMs: 8000,
  });
}

export async function finalizeTelegramBrowserLogin(sessionToken) {
  return api("/auth/telegram/browser/finalize", {
    method: "POST",
    body: { session_token: sessionToken },
    handle401: false,
    timeoutMs: 8000,
  });
}

export async function startTelegramBrowserLink(nextPath = "") {
  return api("/auth/link/telegram/browser/start", {
    method: "POST",
    body: { next_path: nextPath || null },
    timeoutMs: 8000,
  });
}

export async function getTelegramBrowserLinkStatus(sessionToken) {
  return api(`/auth/link/telegram/browser/status/${encodeURIComponent(sessionToken)}`, {
    timeoutMs: 8000,
  });
}

export async function finalizeTelegramBrowserLink(sessionToken) {
  return api("/auth/link/telegram/browser/finalize", {
    method: "POST",
    body: { session_token: sessionToken },
    timeoutMs: 8000,
  });
}

export async function getPhoneAuthConfig() {
  return api("/auth/phone/config", {
    handle401: false,
  });
}

export async function requestPhoneCall(phone) {
  return api("/auth/phone/request-call", {
    method: "POST",
    body: { phone },
    handle401: false,
  });
}

export async function getPhoneCallStatus(phone, challengeId) {
  return api(`/auth/phone/call-status/${encodeURIComponent(challengeId)}?phone=${encodeURIComponent(phone)}`, {
    handle401: false,
  });
}

export async function requestPhoneCode(phone) {
  return api("/auth/phone/request-code", {
    method: "POST",
    body: { phone },
    handle401: false,
  });
}

export async function verifyPhoneCode(phone, code = "", challengeId = null) {
  const body = { phone };
  const normalizedCode = String(code || "").trim();
  if (normalizedCode) body.code = normalizedCode;
  if (challengeId != null && challengeId !== "") body.challenge_id = challengeId;
  return api("/auth/phone/verify-code", {
    method: "POST",
    body,
    handle401: false,
  });
}

export async function loginWithPassword(phone, password) {
  return api("/auth/password/login", {
    method: "POST",
    body: { phone, password },
    handle401: false,
  });
}

export async function setPasswordAfterPhoneVerify(phone, code = "", newPassword = "", challengeId = null) {
  const body = { phone, new_password: newPassword };
  const normalizedCode = String(code || "").trim();
  if (normalizedCode) body.code = normalizedCode;
  if (challengeId != null && challengeId !== "") body.challenge_id = challengeId;
  return api("/auth/password/set-after-phone-verify", {
    method: "POST",
    body,
    handle401: false,
  });
}

export async function requestPasswordResetCall(phone) {
  return api("/auth/password/reset/request-call", {
    method: "POST",
    body: { phone },
    handle401: false,
  });
}

export async function requestPasswordResetCode(phone) {
  return api("/auth/password/reset/request-code", {
    method: "POST",
    body: { phone },
    handle401: false,
  });
}

export async function confirmPasswordReset(phone, code = "", newPassword = "", challengeId = null) {
  const body = { phone, new_password: newPassword };
  const normalizedCode = String(code || "").trim();
  if (normalizedCode) body.code = normalizedCode;
  if (challengeId != null && challengeId !== "") body.challenge_id = challengeId;
  return api("/auth/password/reset/confirm", {
    method: "POST",
    body,
    handle401: false,
  });
}

export async function getPasswordState() {
  return api("/auth/password/state");
}

export async function changePassword(currentPassword, newPassword) {
  return api("/auth/password/change", {
    method: "POST",
    body: { current_password: currentPassword, new_password: newPassword },
  });
}

export async function logout() {
  return api("/auth/logout", {
    method: "POST",
    handle401: false,
  });
}

export async function requestLinkPhoneCall(phone) {
  return api("/auth/link/phone/request-call", {
    method: "POST",
    body: { phone },
  });
}

export async function requestLinkPhoneCode(phone) {
  return api("/auth/link/phone/request-code", {
    method: "POST",
    body: { phone },
  });
}

export async function verifyLinkPhoneCode(phone, code = "", newPassword = "", challengeId = null) {
  const body = { phone };
  const normalizedCode = String(code || "").trim();
  const normalizedPassword = String(newPassword || "").trim();
  if (normalizedCode) body.code = normalizedCode;
  if (challengeId != null && challengeId !== "") body.challenge_id = challengeId;
  if (normalizedPassword) body.new_password = normalizedPassword;
  return api("/auth/link/phone/verify-code", {
    method: "POST",
    body,
  });
}

export async function linkTelegramAccount(initData = "") {
  const value = String(initData || wa()?.initData || "").trim();
  if (!value) throw new Error("Telegram Mini App недоступен для привязки");
  return api("/auth/link/telegram", {
    method: "POST",
    body: { initData: value },
  });
}

export function confirmModal({ title, text, confirmText = "Подтвердить", danger = false }) {
  return new Promise((resolve) => {
    const m = document.getElementById("modal");
    if (!m) return resolve(false);

    const titleEl = m.querySelector(".modal__title");
    const body = m.querySelector(".modal__body");
    if (!titleEl || !body) return resolve(false);

    titleEl.textContent = title;
    body.textContent = "";

    const p = document.createElement("div");
    p.className = "muted";
    p.style.marginTop = "10px";
    p.textContent = text;
    body.appendChild(p);

    const actions = document.createElement("div");
    actions.className = "row";
    actions.style.marginTop = "12px";

    const btnCancel = document.createElement("button");
    btnCancel.className = "btn";
    btnCancel.textContent = "Отмена";

    const btnOk = document.createElement("button");
    btnOk.className = "btn " + (danger ? "danger" : "primary");
    btnOk.textContent = confirmText;

    actions.appendChild(btnCancel);
    actions.appendChild(btnOk);
    body.appendChild(actions);

    const cleanup = (val) => {
      m.classList.remove("open");
      btnCancel.onclick = null;
      btnOk.onclick = null;
      resolve(val);
    };

    btnCancel.onclick = () => cleanup(false);
    btnOk.onclick = () => cleanup(true);

    m.classList.add("open");
  });
}

// ------------------------------
// Venue context + simple routing helpers (frontend MVP)
// ------------------------------
const LS_ACTIVE_VENUE = "axelio.activeVenueId";


function withTimeout(promise, ms, label = "REQUEST_TIMEOUT") {
  let timer = null;
  return new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      const err = new Error(label);
      err.code = "TIMEOUT";
      reject(err);
    }, ms);
    Promise.resolve(promise).then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}


export function getActiveVenueId() {
  try { return localStorage.getItem(LS_ACTIVE_VENUE) || ""; } catch { return ""; }
}

export function setActiveVenueId(id) {
  try {
    if (id === null || id === undefined || String(id).trim() === "") {
      localStorage.removeItem(LS_ACTIVE_VENUE);
      return;
    }
    localStorage.setItem(LS_ACTIVE_VENUE, String(id));
  } catch {}
}

export async function getMe({ timeoutMs = 8000 } = {}) {
  return withTimeout(api("/me"), timeoutMs, "ME_TIMEOUT");
}

export async function getMyVenues({ timeoutMs = 8000, includeArchived = false } = {}) {
  const suffix = includeArchived ? "?include_archived=true" : "";
  return withTimeout(api(`/me/venues${suffix}`), timeoutMs, "MY_VENUES_TIMEOUT");
}

export async function getMyVenuePermissions(venueId, { timeoutMs = 8000 } = {}) {
  if (!venueId) return { venue_id: null, role: null, permissions: [] };
  try {
    return await withTimeout(
      api(`/me/venues/${encodeURIComponent(venueId)}/permissions`),
      timeoutMs,
      "MY_VENUE_PERMISSIONS_TIMEOUT",
    );
  } catch (e) {
    if (e?.code === "TIMEOUT" || /TIMEOUT/i.test(String(e?.message || ""))) {
      return { venue_id: Number(venueId) || venueId, role: null, permissions: [], _timed_out: true };
    }
    throw e;
  }
}

// ------------------------------
// Venues: members + positions
// ------------------------------

export async function getVenueMembers(venueId) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/members`);
}

export async function getVenuePositions(venueId) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/positions`);
}

export async function createVenuePosition(venueId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/positions`, {
    method: "POST",
    body: payload,
  });
}

export async function updateVenuePosition(venueId, positionId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!positionId) throw new Error("NO_POSITION");
  return api(`/venues/${encodeURIComponent(venueId)}/positions/${encodeURIComponent(positionId)}`, {
    method: "PATCH",
    body: payload,
  });
}

export async function deleteVenuePosition(venueId, positionId) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!positionId) throw new Error("NO_POSITION");
  return api(`/venues/${encodeURIComponent(venueId)}/positions/${encodeURIComponent(positionId)}`, {
    method: "DELETE",
  });
}

// ------------------------------
// Venue settings
// ------------------------------

export async function getVenueSettings(venueId) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/settings`);
}

export async function updateVenueSettings(venueId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/settings`, {
    method: "PATCH",
    body: payload,
  });
}

// ------------------------------
// Invites (pending)
// ------------------------------

/**
 * Sets default position preset for a pending invite.
 * Backend endpoint: PATCH /venues/{venue_id}/invites/{invite_id}/default_position
 */
export async function patchInviteDefaultPosition(venueId, inviteId, defaultPosition) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!inviteId) throw new Error("NO_INVITE");
  return api(`/venues/${encodeURIComponent(venueId)}/invites/${encodeURIComponent(inviteId)}/default_position`, {
    method: "PATCH",
    body: { default_position: defaultPosition ?? null },
  });
}

// ------------------------------
// Catalogs: departments / payment methods / KPI metrics
// ------------------------------

export async function getDepartments(venueId, { includeArchived = false } = {}) {
  if (!venueId) throw new Error("NO_VENUE");
  const q = includeArchived ? "?include_archived=true" : "";
  return api(`/venues/${encodeURIComponent(venueId)}/departments${q}`);
}

export async function createDepartment(venueId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/departments`, { method: "POST", body: payload });
}

export async function updateDepartment(venueId, departmentId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!departmentId) throw new Error("NO_DEPARTMENT");
  return api(`/venues/${encodeURIComponent(venueId)}/departments/${encodeURIComponent(departmentId)}`, {
    method: "PATCH",
    body: payload,
  });
}

export async function getPaymentMethods(venueId, { includeArchived = false } = {}) {
  if (!venueId) throw new Error("NO_VENUE");
  const q = includeArchived ? "?include_archived=true" : "";
  return api(`/venues/${encodeURIComponent(venueId)}/payment-methods${q}`);
}

export async function createPaymentMethod(venueId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/payment-methods`, { method: "POST", body: payload });
}

export async function updatePaymentMethod(venueId, paymentMethodId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!paymentMethodId) throw new Error("NO_PAYMENT_METHOD");
  return api(`/venues/${encodeURIComponent(venueId)}/payment-methods/${encodeURIComponent(paymentMethodId)}`, {
    method: "PATCH",
    body: payload,
  });
}

export async function getKpiMetrics(venueId, { includeArchived = false } = {}) {
  if (!venueId) throw new Error("NO_VENUE");
  const q = includeArchived ? "?include_archived=true" : "";
  return api(`/venues/${encodeURIComponent(venueId)}/kpi-metrics${q}`);
}

export async function createKpiMetric(venueId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/kpi-metrics`, { method: "POST", body: payload });
}

export async function updateKpiMetric(venueId, kpiMetricId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!kpiMetricId) throw new Error("NO_KPI_METRIC");
  return api(`/venues/${encodeURIComponent(venueId)}/kpi-metrics/${encodeURIComponent(kpiMetricId)}`, {
    method: "PATCH",
    body: payload,
  });
}

/**
 * Boots a page: ensures login (cookie), loads /me,
 * optionally enforces an active venue (from LS or query).
 */


// ------------------------------
// Payroll: profiles / components / assignments / runs
// ------------------------------

export async function getPayProfiles(venueId, { includeInactive = false } = {}) {
  if (!venueId) throw new Error("NO_VENUE");
  const q = includeInactive ? "?include_inactive=true" : "";
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles${q}`);
}

export async function getPayProfile(venueId, profileId) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!profileId) throw new Error("NO_PAY_PROFILE");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}`);
}

export async function createPayProfile(venueId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles`, { method: "POST", body: payload });
}

export async function updatePayProfile(venueId, profileId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!profileId) throw new Error("NO_PAY_PROFILE");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}`, {
    method: "PATCH",
    body: payload,
  });
}

export async function deletePayProfile(venueId, profileId) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!profileId) throw new Error("NO_PAY_PROFILE");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}`, {
    method: "DELETE",
  });
}

export async function createPayProfileAssignment(venueId, profileId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!profileId) throw new Error("NO_PAY_PROFILE");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}/assignments`, {
    method: "POST",
    body: payload,
  });
}

export async function updatePayProfileAssignment(venueId, assignmentId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!assignmentId) throw new Error("NO_ASSIGNMENT");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profile-assignments/${encodeURIComponent(assignmentId)}`, {
    method: "PATCH",
    body: payload,
  });
}

export async function deletePayProfileAssignment(venueId, assignmentId) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!assignmentId) throw new Error("NO_ASSIGNMENT");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profile-assignments/${encodeURIComponent(assignmentId)}`, {
    method: "DELETE",
  });
}

export async function createPayComponent(venueId, profileId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!profileId) throw new Error("NO_PAY_PROFILE");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}/components`, {
    method: "POST",
    body: payload,
  });
}

export async function updatePayComponent(venueId, componentId, payload) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!componentId) throw new Error("NO_COMPONENT");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-components/${encodeURIComponent(componentId)}`, {
    method: "PATCH",
    body: payload,
  });
}

export async function deletePayComponent(venueId, componentId) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!componentId) throw new Error("NO_COMPONENT");
  return api(`/venues/${encodeURIComponent(venueId)}/pay-components/${encodeURIComponent(componentId)}`, {
    method: "DELETE",
  });
}

export async function calculatePayroll(venueId, month) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/payroll/calculate`, {
    method: "POST",
    body: { month },
  });
}

export async function getPayroll(venueId, month) {
  if (!venueId) throw new Error("NO_VENUE");
  if (!month) throw new Error("NO_MONTH");
  return api(`/venues/${encodeURIComponent(venueId)}/payroll?month=${encodeURIComponent(month)}`);
}

export async function bootPage({ requireVenue = false, silentLogin = true } = {}) {
  await ensureLogin({ silent: silentLogin });

  let me = null;
  try {
    me = await getMe();
  } catch (e) {
    return { ok: false, me: null, error: e };
  }

  let venues = null;
  if (requireVenue) {
    try {
      venues = await getMyVenues();
    } catch {
      venues = [];
    }

    let activeVenueId = getActiveVenueId();
    // If user has exactly one venue and none selected — auto-select
    if (!activeVenueId && Array.isArray(venues) && venues.length === 1) {
      activeVenueId = String(venues[0].id);
      setActiveVenueId(activeVenueId);
    }

    // Still no venue — go to venues picker
    if (!activeVenueId) {
      location.href = "/app-venues.html";
      return { ok: false, me, venues, redirected: true };
    }

    return { ok: true, me, venues, activeVenueId };
  }

  return { ok: true, me };
}

function escHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Renders a venue switcher <select> into container (or returns null if 0/1 venues).
 * onChange receives (newVenueId).
 */
export function renderVenueSwitcher({ container, venues, activeVenueId, onChange }) {
  if (!container) return null;
  if (!Array.isArray(venues) || venues.length <= 1) {
    container.innerHTML = "";
    return null;
  }

  container.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.className = "venue-switch";

  const label = document.createElement("span");
  label.className = "venue-switch__label";
  label.textContent = "Venue:";

  const sel = document.createElement("select");
  sel.className = "venue-switch__select";

  venues.forEach((v) => {
    const opt = document.createElement("option");
    opt.value = String(v.id);
    opt.textContent = v.name ? v.name : `Venue #${v.id}`;
    sel.appendChild(opt);
  });

  sel.value = String(activeVenueId || venues[0].id || "");

  sel.onchange = () => {
    const id = sel.value;
    setActiveVenueId(id);
    if (typeof onChange === "function") onChange(id);
  };

  wrap.appendChild(label);
  wrap.appendChild(sel);
  container.appendChild(wrap);

  return sel;
}

/**
 * Convenience: loads /me/venues, renders switcher, and keeps URL in sync via onChange.
 * If current page uses ?venue_id=, we update that param and reload.
 */
export async function mountVenueSwitcher({ containerSelector = "#venueSwitcher", venues = null, onChange = null } = {}) {
  const el = document.querySelector(containerSelector);
  if (!el) return null;

  const v = venues || (await getMyVenues().catch(() => []));
  const active = getActiveVenueId() || (v[0] ? String(v[0].id) : "");

  return renderVenueSwitcher({
    container: el,
    venues: v,
    activeVenueId: active,
    onChange:
      onChange ||
      ((newId) => {
        const url = new URL(location.href);
        if (url.searchParams.has("venue_id")) url.searchParams.set("venue_id", newId);
        location.href = url.pathname + url.search;
      }),
  });
}

export async function getVenueById(venueId) {
  if (!venueId) return null;

  // Берём из "моих заведений" (это доступно OWNER/STAFF)
  const list = await api("/me/venues?include_archived=true");
  const v = (list || []).find(x => String(x.id) === String(venueId));
  return v || null;
}
// ------------------------------
// Permissions + dynamic navigation (A2/A3)
// ------------------------------


export function can(permCode, venuePerms) {
  if (!permCode) return false;
  const list = normalizePermList(venuePerms?.permissions || venuePerms);
  return list.includes(String(permCode));
}


function renderNavLinks({ container, links, activeTab }) {
  if (!container) return;
  container.innerHTML = "";

  links.forEach((l) => {
    const a = document.createElement("a");
    a.href = l.href;
    a.textContent = l.title;
    if (l.className) a.className = l.className;
    a.setAttribute("data-tab", l.tab);
    if (l.tab === activeTab) a.classList.add("active");
    container.appendChild(a);
  });
}

/**
 * Mounts a bottom nav with only allowed items.
 *
 * Rules (MVP):
 * - SUPER_ADMIN: admin pages only
 * - Others: Venues + (if active venue) Venue/Invites
 *
 * Later we'll extend links as we add pages (Shifts/Salary/Adjustments/Reports).
 */
export async function mountNav({ activeTab = "dashboard", containerSelector = "#nav" } = {}) {
  const container = document.querySelector(containerSelector);
  if (!container) return { ok: false, reason: "NO_CONTAINER" };

  // Deep links: if venue_id is in URL, treat it as active venue (prevents missing owner navbar)
  try {
    const qv = new URLSearchParams(location.search).get("venue_id");
    if (qv) setActiveVenueId(qv);
  } catch {}

  await ensureLogin({ silent: true });

  let me = null;
  try { me = await getMe(); } catch {
    container.innerHTML = "";
    return { ok: false, reason: "NO_ME" };
  }

  // cache system role for gated features (themes, admin-only UI)
  cacheSystemRole(me?.system_role);
  // re-apply theme now that role is known (enables SUPER_ADMIN-only themes)
  applyTheme();

  // SUPER_ADMIN bottom nav
  if (me?.system_role === "SUPER_ADMIN") {
    renderNavLinks({
      container,
      links: [
        { title: t("admin_venues"), href: "/admin-venues.html", tab: "admin-venues" },
        { title: "Биллинг", href: "/admin-billing.html", tab: "admin-billing" },
        { title: t("admin_invites"), href: "/admin-invites.html", tab: "admin-invites" },
        { title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" },
      ],
      activeTab,
    });
    return { ok: true, me };
  }

  // Regular users (OWNER/STAFF)
  let venues = [];
  try { venues = await getMyVenues(); } catch { venues = []; }

  let activeVenueId = getActiveVenueId();

  // If user has venues but no active venue chosen yet, pick the first one automatically.
  // This prevents "2-tab navbar" on pages that require a venue context.
  try {
    const page = (location.pathname.split("/").pop() || "").toLowerCase();
    const isVenuePicker = page === "app-venues.html";
    if (!activeVenueId && !isVenuePicker && venues.length >= 1) {
      activeVenueId = String(venues[0].id);
      setActiveVenueId(activeVenueId);
    } else if (!activeVenueId && venues.length === 1) {
      activeVenueId = String(venues[0].id);
      setActiveVenueId(activeVenueId);
    }
  } catch {
    if (!activeVenueId && venues.length === 1) {
      activeVenueId = String(venues[0].id);
      setActiveVenueId(activeVenueId);
    }
  }

// Determine permissions for active venue (best-effort)
let isOwner = false;
let canViewReports = false;

const activeVenue = activeVenueId ? venues.find(v => String(v.id) === String(activeVenueId)) : null;
const roleFromList = String(activeVenue?.role || activeVenue?.venue_role || activeVenue?.my_role || "").toUpperCase();

if (activeVenueId) {
  try {
    const permsResp = await getMyVenuePermissions(activeVenueId);
    const role = roleUpper(permsResp) || roleFromList;
    isOwner = role === "OWNER" || role === "VENUE_OWNER";

    const pset = permSetFromResponse(permsResp);

    // Report access means: user can open report pages / close shift / see report sections.
    canViewReports =
      isOwner ||
      hasPermPrefix(pset, "SHIFT_REPORT_") ||
      hasPermPrefix(pset, "REPORTS_") ||
      hasAnyPerm(pset, [
        "SHIFT_REPORT_VIEW",
        "SHIFT_REPORT_CLOSE",
        "SHIFT_REPORT_EDIT",
        "SHIFT_REPORT_REOPEN",
        "REPORTS_VIEW_DAILY",
        "REPORTS_VIEW_MONTHLY",
        "REPORTS_VIEW_PNL",
      ]);
  } catch {
    isOwner = roleFromList === "OWNER" || roleFromList === "VENUE_OWNER";
    canViewReports = isOwner;
  }
}

const qp = activeVenueId ? `?venue_id=${encodeURIComponent(activeVenueId)}` : "";

  const links = [];

  if (activeVenueId) {
    if (isOwner) {      // Owner bottom nav: Venue / Summary / Expenses
      links.push({ title: t("venue"), href: `/app-venue.html${qp}`, tab: "venue" });      links.push({ title: t("summary"), href: `/owner-summary.html${qp}`, tab: "summary" });
      links.push({ title: t("expenses"), href: `/owner-expenses.html${qp}`, tab: "expenses" });
      links.push({ title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" });
    } else {
      // Staff bottom nav:
// - If NO report access: Schedule + Salaries + Adjustments + Settings
// - If HAS report access: Schedule + Finance + Reports + Settings
links.push({ title: t("shifts"), href: `/staff-shifts.html${qp}`, tab: "shifts" });

if (canViewReports) {
  links.push({ title: t("finance"), href: `/staff-finance.html${qp}`, tab: "finance" });
  links.push({ title: t("report"), href: `/staff-report.html${qp}`, tab: "report" });
} else {
  links.push({ title: t("salary"), href: `/staff-salary.html${qp}`, tab: "salary" });
  links.push({ title: t("adjustments"), href: `/staff-adjustments.html${qp}`, tab: "adjustments" });
}

links.push({ title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" });
    }
  } else {
    // No active venue chosen yet
    links.push({ title: t("manage_venues"), href: "/app-venues.html", tab: "app-venues" });
    links.push({ title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" });
  }

  renderNavLinks({ container, links, activeTab });
  return { ok: true, me, venues, activeVenueId };
}

// ------------------------------
// Venue dropdown menu (topbar)
// ------------------------------
export async function leaveVenue(venueId) {
  if (!venueId) throw new Error("NO_VENUE");
  return api(`/venues/${encodeURIComponent(venueId)}/leave`, { method: "POST" });
}

export async function mountVenueMenu({ containerSelector = "#venueMenu", onVenueChanged = null } = {}) {
  const el = document.querySelector(containerSelector);
  if (!el) return null;

  let venues = [];
  try { venues = await getMyVenues(); } catch { venues = []; }

  // Always show, even if 0/1 venues
  const active = getActiveVenueId() || (venues[0] ? String(venues[0].id) : "");
  if (active) setActiveVenueId(active);

  el.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.className = "venue-switch";

  const label = document.createElement("span");
  label.className = "venue-switch__label";
  label.textContent = t("venue") + ":";

  const sel = document.createElement("select");
  sel.className = "input min-w240";

  if (!venues.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "—";
    sel.appendChild(opt);
  } else {
    for (const v of venues) {
      const opt = document.createElement("option");
      opt.value = String(v.id);
      opt.textContent = v.name ? v.name : `#${v.id}`;
      sel.appendChild(opt);
    }
  }

  // action items
  const optManage = document.createElement("option");
  optManage.value = "__manage__";
  optManage.textContent = "────────";
  optManage.disabled = true;
  sel.appendChild(optManage);

  const optManage2 = document.createElement("option");
  optManage2.value = "__manage2__";
  optManage2.textContent = t("manage_venues");
  sel.appendChild(optManage2);

  sel.value = active || (venues[0] ? String(venues[0].id) : "");

  sel.onchange = async () => {
    const val = sel.value;
    if (val === "__manage2__") {
      location.href = "/app-venues.html";
      return;
    }

    // normal venue switch
    setActiveVenueId(val);
    if (typeof onVenueChanged === "function") onVenueChanged(val);
    else {
      const url = new URL(location.href);
      if (url.searchParams.has("venue_id")) url.searchParams.set("venue_id", val);
      location.href = url.pathname + url.search;
    }
  };

  wrap.appendChild(label);
  wrap.appendChild(sel);
  el.appendChild(wrap);
  return sel;
}

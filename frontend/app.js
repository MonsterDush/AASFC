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

const SS_DEMO_UI_STATE = "axelio.demo_ui_state";
const DEMO_READONLY_ERROR_CODE = "DEMO_READONLY";
let __demoBannerBootstrapped = false;
let __lastToastMeta = { text: "", type: "", at: 0 };

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

function currentAppPath() {
  if (!isBrowser()) return "/";
  return `${location.pathname || "/"}${location.search || ""}${location.hash || ""}`;
}

function formatDemoMonthLabel(year, month) {
  const y = Number(year || 0);
  const m = Number(month || 0);
  if (!Number.isFinite(y) || !Number.isFinite(m) || y <= 0 || m <= 0 || m > 12) return "Демо-данные";
  const date = new Date(Date.UTC(y, m - 1, 1));
  try {
    const label = new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric", timeZone: "UTC" }).format(date);
    return label.charAt(0).toUpperCase() + label.slice(1);
  } catch {
    return `${String(m).padStart(2, "0")}.${y}`;
  }
}

function buildDemoUiState(source) {
  if (!source || !source.demo_mode) return null;
  const banner = source.demo_banner || source.banner || {};
  return {
    demo_mode: true,
    demo_access_mode: String(source.demo_access_mode || "DEMO_READONLY").toUpperCase(),
    demo_persona: String(source.demo_persona || "OWNER").toUpperCase(),
    demo_venue_id: source.demo_venue_id || null,
    demo_reference_year: source.demo_reference_year || null,
    demo_reference_month: source.demo_reference_month || null,
    demo_month_label: formatDemoMonthLabel(source.demo_reference_year, source.demo_reference_month),
    demo_banner: {
      return_url: banner.return_url || "https://axelio.ru",
      primary_cta_url: banner.primary_cta_url || "https://axelio.ru/#contact",
      secondary_cta_url: banner.secondary_cta_url || `${location.origin}${AUTH_PAGE}`,
      primary_cta_label: banner.primary_cta_label || "Оставить заявку",
      secondary_cta_label: banner.secondary_cta_label || "Начать пользоваться",
    },
  };
}

export function getStoredDemoUiState() {
  if (!isBrowser()) return null;
  try {
    const raw = sessionStorage.getItem(SS_DEMO_UI_STATE);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return parsed?.demo_mode ? parsed : null;
  } catch {
    return null;
  }
}


export function readStoredDemoUiState() {
  return getStoredDemoUiState();
}

function storeDemoUiState(source) {
  if (!isBrowser()) return null;
  const state = buildDemoUiState(source);
  try {
    if (state) sessionStorage.setItem(SS_DEMO_UI_STATE, JSON.stringify(state));
    else sessionStorage.removeItem(SS_DEMO_UI_STATE);
  } catch {}
  try {
    window.dispatchEvent(new CustomEvent("axelio:demo-state-changed", { detail: state || null }));
  } catch {}
  return state;
}

function clearDemoUiState() {
  if (!isBrowser()) return;
  try { sessionStorage.removeItem(SS_DEMO_UI_STATE); } catch {}
  try {
    window.dispatchEvent(new CustomEvent("axelio:demo-state-changed", { detail: null }));
  } catch {}
}

export function isDemoReadonlyUi(state = null) {
  const current = state?.demo_mode ? state : getStoredDemoUiState();
  if (!current?.demo_mode) return false;
  return String(current.demo_access_mode || "DEMO_READONLY").toUpperCase() === "DEMO_READONLY";
}

export function getDemoMonthLabel(state = null) {
  const current = state?.demo_mode ? state : getStoredDemoUiState();
  return current?.demo_month_label || formatDemoMonthLabel(current?.demo_reference_year, current?.demo_reference_month);
}


function __demoPad2(value) {
  return String(Number(value || 0)).padStart(2, "0");
}

function __normalizeMonthValue(value) {
  const raw = String(value || "").trim();
  const m = raw.match(/^(\d{4})-(\d{2})/);
  if (!m) return "";
  const year = Number(m[1]);
  const month = Number(m[2]);
  if (!Number.isFinite(year) || year <= 0 || !Number.isFinite(month) || month < 1 || month > 12) return "";
  return `${year}-${__demoPad2(month)}`;
}

function __daysInMonth(year, month) {
  return new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate();
}

function __normalizeDateValue(value) {
  const raw = String(value || "").trim();
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return "";
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  if (!Number.isFinite(year) || year <= 0 || !Number.isFinite(month) || month < 1 || month > 12) return "";
  const maxDay = __daysInMonth(year, month);
  if (!Number.isFinite(day) || day < 1 || day > maxDay) return "";
  return `${year}-${__demoPad2(month)}-${__demoPad2(day)}`;
}

function __getDemoMonthBounds(source = null) {
  const state = source?.demo_mode ? source : getStoredDemoUiState();
  if (!state?.demo_mode) return null;
  const year = Number(state.demo_reference_year || 0);
  const month = Number(state.demo_reference_month || 0);
  if (!Number.isFinite(year) || year <= 0 || !Number.isFinite(month) || month < 1 || month > 12) return null;
  const ym = `${year}-${__demoPad2(month)}`;
  const lastDay = __daysInMonth(year, month);
  return {
    year,
    month,
    ym,
    start: `${ym}-01`,
    end: `${ym}-${__demoPad2(lastDay)}`,
  };
}

function __notifyDemoClamp(bounds, options = {}) {
  if (options?.notify === false || !bounds) return;
  const label = formatDemoMonthLabel(bounds.year, bounds.month);
  toast(`Пробный режим: подготовлены данные за ${label}.`, "warn");
}

export function isDemoUiMode(source = null) {
  if (source?.demo_mode) return true;
  const mode = String(source?.demo_access_mode || "").toUpperCase();
  if (mode === "DEMO_READONLY") return true;
  return isDemoReadonlyUi(source);
}

export function coerceDemoMonth(value, options = {}) {
  const normalized = __normalizeMonthValue(value);
  const bounds = __getDemoMonthBounds(options?.source);
  if (!bounds || !isDemoUiMode(options?.source)) return normalized || String(value || "");
  if (normalized && normalized === bounds.ym) return bounds.ym;
  __notifyDemoClamp(bounds, options);
  return bounds.ym;
}

export function coerceDemoDate(value, options = {}) {
  const normalized = __normalizeDateValue(value);
  const bounds = __getDemoMonthBounds(options?.source);
  if (!bounds || !isDemoUiMode(options?.source)) return normalized || String(value || "");
  if (normalized && normalized.startsWith(`${bounds.ym}-`)) return normalized;
  const fallbackDay = normalized ? Number(normalized.slice(-2)) : 1;
  const safeDay = Math.min(Math.max(fallbackDay || 1, 1), __daysInMonth(bounds.year, bounds.month));
  if (normalized !== `${bounds.ym}-${__demoPad2(safeDay)}`) __notifyDemoClamp(bounds, options);
  return `${bounds.ym}-${__demoPad2(safeDay)}`;
}

export function coerceDemoRange(fromValue, toValue, options = {}) {
  const bounds = __getDemoMonthBounds(options?.source);
  const demoMode = isDemoUiMode(options?.source);
  const normalizedFrom = __normalizeDateValue(fromValue) || "";
  const normalizedTo = __normalizeDateValue(toValue) || "";
  let from = normalizedFrom || normalizedTo || "";
  let to = normalizedTo || normalizedFrom || "";
  if (!demoMode || !bounds) {
    if (from && to && from > to) [from, to] = [to, from];
    return { from, to };
  }
  const coercedFrom = coerceDemoDate(from || bounds.start, { ...options, notify: false, source: options?.source });
  const coercedTo = coerceDemoDate(to || coercedFrom || bounds.end, { ...options, notify: false, source: options?.source });
  let outFrom = coercedFrom || bounds.start;
  let outTo = coercedTo || outFrom || bounds.end;
  if (outFrom > outTo) [outFrom, outTo] = [outTo, outFrom];
  if ((normalizedFrom && normalizedFrom !== outFrom) || (normalizedTo && normalizedTo !== outTo)) {
    __notifyDemoClamp(bounds, options);
  }
  return { from: outFrom, to: outTo };
}

export function applyDemoReadonlyCaps(caps = {}, options = {}) {
  const out = { ...(caps || {}) };
  if (!isDemoUiMode(options?.source)) return out;

  for (const [key, value] of Object.entries(out)) {
    if (typeof value !== "boolean") continue;
    const lower = String(key || "").toLowerCase();
    const allowReadOnly = /(view|read|open|list|show|details?)/.test(lower) && !/(edit|create|delete|archive|manage|add|write|update|remove|close|reopen|invite|calculate|generate|toggle|assign|upload|save|confirm)/.test(lower);
    if (!allowReadOnly) out[key] = false;
  }

  return out;
}

function isStaffOnlyDemoPage(pathname) {
  const page = String(pathname || location.pathname || "").split("/").pop().toLowerCase();
  return page.startsWith("staff-");
}

function isOwnerOnlyDemoPage(pathname) {
  const page = String(pathname || location.pathname || "").split("/").pop().toLowerCase();
  return (
    page.startsWith("owner-") ||
    page === "app-venue.html" ||
    page === "invites.html" ||
    page === "positions.html" ||
    page === "shift-intervals.html"
  );
}

function resolveDemoSwitchNextPath(targetPersona, state = null) {
  if (!isBrowser()) return null;
  const persona = String(targetPersona || "OWNER").toUpperCase();
  const current = currentAppPath();
  const venueId = state?.demo_venue_id || getActiveVenueId() || "";

  if (persona === "STAFF" && isOwnerOnlyDemoPage(location.pathname)) {
    return venueId ? `/staff-shifts.html?venue_id=${encodeURIComponent(venueId)}` : "/staff-shifts.html";
  }
  if (persona === "OWNER" && isStaffOnlyDemoPage(location.pathname)) {
    return venueId ? `/app-venue.html?venue_id=${encodeURIComponent(venueId)}` : "/app-venue.html";
  }
  return current;
}

async function switchDemoPersona(targetPersona, buttonEl = null) {
  const currentState = getStoredDemoUiState();
  const persona = String(targetPersona || "OWNER").toUpperCase();
  const nextPath = resolveDemoSwitchNextPath(persona, currentState);
  if (buttonEl) buttonEl.disabled = true;
  try {
    const out = await api("/auth/demo/switch-persona", {
      method: "POST",
      body: { persona, next_path: nextPath },
      skipDemoReadonlyToast: true,
    });
    storeDemoUiState(out);
    location.href = out?.redirect_url || nextPath || "/";
  } catch (e) {
    toast(e?.data?.detail || e?.message || "Не удалось переключить DEMO-режим", "err");
  } finally {
    if (buttonEl) buttonEl.disabled = false;
  }
}

async function exitDemoMode(buttonEl = null) {
  if (buttonEl) buttonEl.disabled = true;
  try {
    const currentState = getStoredDemoUiState();
    const fallbackReturnUrl = currentState?.demo_banner?.return_url || "https://axelio.ru";
    const out = await api("/auth/demo/exit", { method: "POST", skipDemoReadonlyToast: true });
    clearDemoUiState();
    location.href = out?.redirect_url || fallbackReturnUrl;
  } catch (e) {
    toast(e?.data?.detail || e?.message || "Не удалось выйти из DEMO", "err");
  } finally {
    if (buttonEl) buttonEl.disabled = false;
  }
}

function buildDemoBannerMarkup(state) {
  const persona = String(state?.demo_persona || "OWNER").toUpperCase();
  const banner = state?.demo_banner || {};
  const monthLabel = state?.demo_month_label || formatDemoMonthLabel(state?.demo_reference_year, state?.demo_reference_month);
  return `
    <div class="demo-banner__bar" role="region" aria-label="Пробный режим Axelio">
      <span class="demo-banner__pill demo-banner__pill--brand">Пробный режим Axelio</span>
      <div class="demo-banner__seg" role="tablist" aria-label="Режим просмотра">
        <button type="button" class="demo-banner__segbtn ${persona === "OWNER" ? "is-active" : ""}" data-demo-persona="OWNER">Владелец</button>
        <button type="button" class="demo-banner__segbtn ${persona === "STAFF" ? "is-active" : ""}" data-demo-persona="STAFF">Персонал</button>
      </div>
      <span class="demo-banner__pill demo-banner__pill--muted">${monthLabel}</span>
      <button type="button" class="demo-banner__link" data-demo-tour-open="1">Экскурсия</button>
      <a class="demo-banner__link" href="${String(banner.return_url || "https://axelio.ru")}">На сайт</a>
      <a class="demo-banner__link demo-banner__link--primary" href="${String(banner.primary_cta_url || "https://axelio.ru/#contact")}">${String(banner.primary_cta_label || "Оставить заявку")}</a>
      <a class="demo-banner__link" href="${String(banner.secondary_cta_url || `${location.origin}${AUTH_PAGE}`)}" data-demo-cta="secondary">${String(banner.secondary_cta_label || "Начать пользоваться")}</a>
    </div>`;
}

function removeDemoBanner() {
  const banner = document.getElementById("demoBanner");
  if (banner) banner.remove();
  try { document.body?.classList?.remove("has-demo-banner"); } catch {}
}

function mountDemoBanner(state = null) {
  if (!isBrowser() || !document.body) return;
  const effectiveState = state?.demo_mode ? state : readStoredDemoUiState();
  if (!effectiveState?.demo_mode) {
    removeDemoBanner();
    return;
  }

  let host = document.getElementById("demoBanner");
  if (!host) {
    host = document.createElement("div");
    host.id = "demoBanner";
    host.className = "demo-banner";

    const anchor = document.querySelector(".topbar") || document.body.firstElementChild || null;

    if (anchor && anchor.parentNode) {
      anchor.parentNode.insertBefore(host, anchor);
    } else {
      document.body.prepend(host);
    }
  }

  host.innerHTML = buildDemoBannerMarkup(effectiveState);
  document.body.classList.add("has-demo-banner");

  host.querySelectorAll("[data-demo-persona]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-demo-persona") || "OWNER";
      if (String(effectiveState.demo_persona || "OWNER").toUpperCase() === String(target).toUpperCase()) return;
      switchDemoPersona(target, btn);
    });
  });

  const tourBtn = host.querySelector('[data-demo-tour-open="1"]');
  if (tourBtn) {
    tourBtn.addEventListener("click", () => {
      reopenDemoTour();
    });
  }
}

function bootstrapStoredDemoBanner() {
  if (!isBrowser() || __demoBannerBootstrapped) return;
  __demoBannerBootstrapped = true;
  const run = () => {
    const stored = getStoredDemoUiState();
    if (stored?.demo_mode) mountDemoBanner(stored);
  };
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", run, { once: true });
  } else {
    run();
  }
}

bootstrapStoredDemoBanner();

const SS_DEMO_TOUR_STATE = "axelio.demo_tour_state";
const DEMO_TOUR_STEPS = {
  OWNER: [
    { id: "owner-summary", path: "/owner-summary.html", title: "Сводка", text: "Здесь владелец видит доходы, расходы и общий результат по заведению." },
    { id: "owner-expenses", path: "/owner-expenses.html", title: "Расходы", text: "Здесь можно посмотреть структуру расходов и категории затрат." },
    { id: "owner-payroll", path: "/owner-payroll.html", title: "Начисления", text: "Здесь владелец видит прозрачный расчёт начислений команды." },
    { id: "app-venue", path: "/app-venue.html", title: "Карточка заведения", text: "Здесь собраны ключевые действия и настройки заведения." },
  ],
  STAFF: [
    { id: "staff-shifts", path: "/staff-shifts.html", title: "График", text: "Здесь сотрудник смотрит весь график и свои смены." },
    { id: "staff-salary", path: "/staff-salary.html", title: "Зарплата", text: "Здесь сотрудник видит начисления и детализацию дохода." },
  ],
};

const __demoPageTourConfig = new Map();
let __demoTourRetryTimer = null;
let __demoTourRetryCount = 0;

function __normalizedCurrentPath() {
  if (!isBrowser()) return "";
  try {
    const url = new URL(location.href);
    return String(url.pathname || "");
  } catch {
    return String(location.pathname || "");
  }
}

function __normalizeTourPath(path) {
  const raw = String(path || "").trim();
  if (!raw) return __normalizedCurrentPath();
  try {
    const url = new URL(raw, location.origin);
    return String(url.pathname || "");
  } catch {
    return raw.startsWith("/") ? raw : `/${raw}`;
  }
}

function __pageTourConfigFor(pathname = null) {
  const key = __normalizeTourPath(pathname || __normalizedCurrentPath());
  return __demoPageTourConfig.get(key) || null;
}

let __demoTourMounted = false;
let __demoTourPendingOpen = false;

function ensureDemoTourStyles() {
  if (!isBrowser() || document.getElementById("demoTourRuntimeStyles")) return;
  const style = document.createElement("style");
  style.id = "demoTourRuntimeStyles";
  style.textContent = `
    .demo-tour-overlay{
      position:fixed;
      inset:0;
      z-index:1400;
      display:flex;
      align-items:flex-end;
      justify-content:center;
      padding:16px;
      background:rgba(11,18,32,.16);
      backdrop-filter:blur(4px);
      -webkit-backdrop-filter:blur(4px);
    }
    .demo-tour-card{
      width:min(100%, 420px);
      border-radius:18px;
      border:1px solid var(--border);
      background:var(--card);
      box-shadow:var(--shadow);
      padding:16px;
      color:var(--text);
    }
    .demo-tour-step{
      font-size:12px;
      line-height:1.2;
      font-weight:800;
      color:var(--muted);
      margin-bottom:8px;
      text-transform:uppercase;
      letter-spacing:.04em;
    }
    .demo-tour-title{
      font-size:20px;
      line-height:1.2;
      font-weight:900;
      color:var(--text);
      margin-bottom:8px;
    }
    .demo-tour-text{
      font-size:14px;
      line-height:1.5;
      color:var(--text);
      margin-bottom:16px;
    }
    .demo-tour-actions{
      display:flex;
      gap:8px;
      justify-content:flex-end;
      flex-wrap:wrap;
    }
    .demo-tour-btn{
      appearance:none;
      border:1px solid var(--border);
      border-radius:12px;
      min-height:40px;
      padding:0 14px;
      font-size:14px;
      font-weight:800;
      line-height:1;
      cursor:pointer;
      color:var(--text);
      background:var(--surface2);
      transition:transform .15s ease, opacity .15s ease, background-color .15s ease, border-color .15s ease, box-shadow .15s ease;
    }
    .demo-tour-btn:hover:not(:disabled){
      transform:translateY(-1px);
      border-color:var(--accentSoftBorder);
    }
    .demo-tour-btn:active{transform:translateY(0)}
    .demo-tour-btn:disabled{
      opacity:.45;
      cursor:default;
      transform:none;
    }
    .demo-tour-btn--ghost{
      background:var(--surface2);
      color:var(--text);
    }
    .demo-tour-btn--primary{
      background:var(--accent);
      color:var(--accentText);
      border-color:transparent;
      box-shadow:0 8px 20px var(--accentA18);
    }
    .demo-tour-btn--primary:hover:not(:disabled){
      box-shadow:0 10px 24px var(--accentA22);
    }
    .demo-tour-dock{
      position:fixed;
      left:12px;
      right:12px;
      bottom:calc(82px + env(safe-area-inset-bottom));
      z-index:1390;
      display:flex;
      justify-content:center;
      pointer-events:none;
    }
    .demo-tour-dock__bar{
      width:min(560px,100%);
      display:grid;
      grid-template-columns:repeat(3,minmax(0,1fr));
      gap:8px;
      padding:10px 12px;
      border:1px solid var(--border);
      border-radius:16px;
      background:var(--card);
      box-shadow:var(--shadow);
      pointer-events:auto;
    }
    .demo-tour-dock__btn{
      appearance:none;
      border:1px solid var(--border);
      background:var(--surface2);
      color:var(--text);
      border-radius:999px;
      padding:10px 12px;
      font-weight:800;
      font-size:13px;
      cursor:pointer;
      min-width:0;
      white-space:nowrap;
      overflow:hidden;
      text-overflow:ellipsis;
      transition:transform .15s ease, opacity .15s ease, background-color .15s ease, border-color .15s ease;
    }
    .demo-tour-dock__btn:hover:not(:disabled){
      transform:translateY(-1px);
      border-color:var(--accentSoftBorder);
    }
    .demo-tour-dock__btn:active{transform:translateY(0)}
    .demo-tour-dock__btn[disabled]{
      opacity:.45;
      cursor:default;
      transform:none;
    }
    .demo-tour-dock__btn--primary{
      background:var(--accent);
      color:var(--accentText);
      border-color:transparent;
    }
    @media (max-width:640px){
      .demo-tour-overlay{
        padding:12px;
        align-items:flex-end;
      }
      .demo-tour-card{
        width:100%;
        border-radius:16px;
        padding:14px;
      }
      .demo-tour-title{font-size:18px}
      .demo-tour-text{font-size:13px}
      .demo-tour-actions{
        display:grid;
        grid-template-columns:1fr 1fr 1fr;
        gap:8px;
      }
      .demo-tour-btn{
        width:100%;
        padding:0 10px;
        font-size:13px;
      }
      .demo-tour-dock{
        left:10px;
        right:10px;
        bottom:calc(78px + env(safe-area-inset-bottom));
      }
      .demo-tour-dock__bar{
        padding:8px 10px;
        border-radius:14px;
      }
      .demo-tour-dock__btn{
        padding:10px 8px;
        font-size:12px;
      }
    }

  `;
  document.head.appendChild(style);
}

function defaultTourState(persona = "OWNER") {
  return {
    persona: String(persona || "OWNER").toUpperCase(),
    index: 0,
    hidden: false,
    completed: false,
    started: false,
  };
}

function readDemoTourState(persona = null) {
  const currentState = getStoredDemoUiState();
  const resolvedPersona = String(persona || currentState?.demo_persona || "OWNER").toUpperCase();
  if (!isBrowser()) return defaultTourState(resolvedPersona);
  try {
    const raw = sessionStorage.getItem(`${SS_DEMO_TOUR_STATE}:${resolvedPersona}`);
    if (!raw) return defaultTourState(resolvedPersona);
    const parsed = JSON.parse(raw);
    return { ...defaultTourState(resolvedPersona), ...parsed, persona: resolvedPersona };
  } catch {
    return defaultTourState(resolvedPersona);
  }
}

function writeDemoTourState(state) {
  if (!isBrowser()) return state;
  const normalized = { ...defaultTourState(state?.persona), ...state, persona: String(state?.persona || "OWNER").toUpperCase() };
  try {
    sessionStorage.setItem(`${SS_DEMO_TOUR_STATE}:${normalized.persona}`, JSON.stringify(normalized));
  } catch {}
  return normalized;
}

function currentTourSteps(persona = null) {
  const currentState = getStoredDemoUiState();
  const resolvedPersona = String(persona || currentState?.demo_persona || "OWNER").toUpperCase();
  return DEMO_TOUR_STEPS[resolvedPersona] || DEMO_TOUR_STEPS.OWNER;
}

function currentTourStep(persona = null, index = null) {
  const state = readDemoTourState(persona);
  const steps = currentTourSteps(state.persona);
  const safeIndex = Math.max(0, Math.min(Number(index ?? state.index ?? 0), Math.max(steps.length - 1, 0)));
  return { state, steps, step: steps[safeIndex] || null, index: safeIndex };
}

function currentPageMatchesTourStep(step) {
  if (!isBrowser() || !step?.path) return false;
  return __normalizedCurrentPath().endsWith(__normalizeTourPath(step.path));
}

async function postDemoTelemetry(eventName, payload = {}) {
  try {
    await api("/demo/event", {
      method: "POST",
      body: JSON.stringify({
        event_name: eventName,
        persona: payload.persona || getStoredDemoUiState()?.demo_persona || null,
        page_path: payload.page_path || currentAppPath(),
        cta_code: payload.cta_code || null,
        meta: payload.meta || null,
      }),
      skipDemoReadonlyToast: true,
    });
  } catch {}
}

export async function trackDemoEvent(eventName, payload = {}) {
  return postDemoTelemetry(eventName, payload);
}

export function mountDemoPageTour(config = {}) {
  if (!isBrowser()) return null;
  const currentState = getStoredDemoUiState();
  const persona = String(config?.persona || currentState?.demo_persona || "OWNER").toUpperCase();
  const key = __normalizeTourPath(config?.path || __normalizedCurrentPath());
  const normalized = {
    tourId: String(config?.tourId || `tour:${persona.toLowerCase()}`),
    path: key,
    step: Math.max(1, Number(config?.step || 1)),
    total: Math.max(1, Number(config?.total || 1)),
    title: String(config?.title || ""),
    text: String(config?.text || ""),
    prevPath: config?.prevPath ? routeWithVenue(config.prevPath, currentState?.demo_venue_id) : null,
    nextPath: config?.nextPath ? routeWithVenue(config.nextPath, currentState?.demo_venue_id) : null,
    finishPath: config?.finishPath ? routeWithVenue(config.finishPath, currentState?.demo_venue_id) : null,
    persona,
  };
  __demoPageTourConfig.set(key, normalized);
  setTimeout(() => maybeAutoStartDemoTour(), 0);
  return normalized;
}

function removeDemoTourOverlay() {
  const el = document.getElementById("demoTourOverlay");
  if (el) el.remove();
}

function removeDemoTourDock() {
  const el = document.getElementById("demoTourDock");
  if (el) el.remove();
}

function renderDemoTourDock(persona = null) {
  if (!isBrowser()) return;
  ensureDemoTourStyles();
  const pageCfg = __pageTourConfigFor();
  const { state, steps, index } = currentTourStep(persona);
  if (state.completed && !pageCfg) {
    removeDemoTourDock();
    return;
  }
  const totalSteps = Number(pageCfg?.total || steps.length || 1);
  const currentStepNo = Number(pageCfg?.step || (index + 1) || 1);
  const isFirst = pageCfg ? !pageCfg.prevPath : index <= 0;
  const isLast = pageCfg ? !pageCfg.nextPath : currentStepNo >= totalSteps;
  let dock = document.getElementById("demoTourDock");
  if (!dock) {
    dock = document.createElement("div");
    dock.id = "demoTourDock";
    dock.className = "demo-tour-dock";
    document.body.appendChild(dock);
  }
  dock.innerHTML = `
    <div class="demo-tour-dock__bar">
      <button type="button" class="demo-tour-dock__btn demo-tour-dock__btn--ghost" data-demo-tour-prev ${isFirst ? "disabled" : ""}>Назад</button>
      <button type="button" class="demo-tour-dock__btn demo-tour-dock__btn--primary" data-demo-tour-next>${isLast ? "Готово" : "Вперёд"}</button>
      <button type="button" class="demo-tour-dock__btn demo-tour-dock__btn--ghost" data-demo-tour-hide>Скрыть</button>
    </div>
  `;
  dock.querySelector("[data-demo-tour-prev]")?.addEventListener("click", () => navigateDemoTour(-1));
  dock.querySelector("[data-demo-tour-next]")?.addEventListener("click", () => navigateDemoTour(1));
  dock.querySelector("[data-demo-tour-hide]")?.addEventListener("click", hideDemoTour);
}

function showDemoTourOverlay(persona = null) {
  if (!isBrowser()) return;
  ensureDemoTourStyles();
  const currentState = getStoredDemoUiState();
  if (!currentState?.demo_mode) {
    __demoTourPendingOpen = true;
    return;
  }
  const pageCfg = __pageTourConfigFor();
  const { state, steps, step, index } = currentTourStep(persona);
  const effectiveStep = pageCfg || step;
  const effectiveIndex = pageCfg ? Math.max(0, Number(pageCfg.step || 1) - 1) : index;
  const effectiveTotal = pageCfg ? Math.max(1, Number(pageCfg.total || 1)) : steps.length;
  if (!effectiveStep) return;
  removeDemoTourDock();
  removeDemoTourOverlay();
  const overlay = document.createElement("div");
  overlay.id = "demoTourOverlay";
  overlay.className = "demo-tour-overlay";
  overlay.innerHTML = `
    <div class="demo-tour-card" role="dialog" aria-modal="true" aria-label="Экскурсия по DEMO">
      <div class="demo-tour-step">Шаг ${effectiveIndex + 1} из ${effectiveTotal}</div>
      <div class="demo-tour-title">${effectiveStep.title}</div>
      <div class="demo-tour-text">${effectiveStep.text}</div>
      <div class="demo-tour-actions">
        <button type="button" class="demo-tour-btn demo-tour-btn--ghost" data-demo-tour-hide>Скрыть</button>
        <button type="button" class="demo-tour-btn demo-tour-btn--ghost" data-demo-tour-prev ${(pageCfg ? !pageCfg.prevPath : index <= 0) ? "disabled" : ""}>Назад</button>
        <button type="button" class="demo-tour-btn demo-tour-btn--primary" data-demo-tour-next>${(pageCfg ? !pageCfg.nextPath : effectiveIndex >= steps.length - 1) ? "Готово" : "Дальше"}</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.querySelector("[data-demo-tour-hide]")?.addEventListener("click", hideDemoTour);
  overlay.querySelector("[data-demo-tour-prev]")?.addEventListener("click", () => navigateDemoTour(-1));
  overlay.querySelector("[data-demo-tour-next]")?.addEventListener("click", () => {
    removeDemoTourOverlay();
    renderDemoTourDock(state.persona);
  });

  if (!state.started || pageCfg) {
    writeDemoTourState({ ...state, started: true, hidden: false, completed: false });
    postDemoTelemetry("tour_started", { persona: state.persona, meta: { step_id: effectiveStep.id || pageCfg?.tourId || step?.id || null, steps_total: effectiveTotal } });
  } else {
    writeDemoTourState({ ...state, hidden: false });
  }
}

function hideDemoTour() {
  const currentState = getStoredDemoUiState();
  const persona = currentState?.demo_persona || "OWNER";
  const state = writeDemoTourState({ ...readDemoTourState(persona), hidden: true });
  removeDemoTourOverlay();
  removeDemoTourDock();
  return state;
}

function completeDemoTour(persona = null) {
  const state = writeDemoTourState({ ...readDemoTourState(persona), completed: true, hidden: true });
  removeDemoTourOverlay();
  removeDemoTourDock();
  postDemoTelemetry("tour_completed", { persona: state.persona, meta: { final_step_index: state.index } });
  return state;
}

function routeWithVenue(path, venueId) {
  const url = new URL(path, location.origin);
  const current = getStoredDemoUiState();
  const targetVenueId = venueId || current?.demo_venue_id || new URL(location.href).searchParams.get("venue_id");
  if (targetVenueId) url.searchParams.set("venue_id", String(targetVenueId));
  return `${url.pathname}${url.search}${url.hash}`;
}

function navigateDemoTour(direction = 1) {
  const currentState = getStoredDemoUiState();
  const persona = currentState?.demo_persona || "OWNER";
  const pageCfg = __pageTourConfigFor();
  if (pageCfg) {
    if (Number(direction || 0) < 0) {
      if (pageCfg.prevPath) {
        location.href = routeWithVenue(pageCfg.prevPath, currentState?.demo_venue_id);
      } else {
        removeDemoTourOverlay();
        renderDemoTourDock(persona);
      }
      return;
    }
    if (pageCfg.nextPath) {
      location.href = routeWithVenue(pageCfg.nextPath, currentState?.demo_venue_id);
      return;
    }
    completeDemoTour(persona);
    return;
  }

  const info = currentTourStep(persona);
  const nextIndex = info.index + Number(direction || 0);
  if (nextIndex < 0) {
    const state = writeDemoTourState({ ...info.state, index: 0, hidden: false });
    removeDemoTourDock();
    showDemoTourOverlay(state.persona);
    return;
  }
  if (nextIndex >= info.steps.length) {
    completeDemoTour(persona);
    return;
  }
  const nextStep = info.steps[nextIndex];
  writeDemoTourState({ ...info.state, index: nextIndex, hidden: false, completed: false });
  if (currentPageMatchesTourStep(nextStep)) {
    removeDemoTourDock();
    showDemoTourOverlay(persona);
    return;
  }
  location.href = routeWithVenue(nextStep.path, currentState?.demo_venue_id);
}

export function reopenDemoTour() {
  const currentState = getStoredDemoUiState();
  const persona = currentState?.demo_persona || "OWNER";
  const state = readDemoTourState(persona);
  const resetState = writeDemoTourState({ ...state, hidden: false, completed: false });
  removeDemoTourDock();
  showDemoTourOverlay(resetState.persona);
}

export function resetDemoTour(persona = null) {
  const resolvedPersona = String(persona || getStoredDemoUiState()?.demo_persona || "OWNER").toUpperCase();
  try { sessionStorage.removeItem(`${SS_DEMO_TOUR_STATE}:${resolvedPersona}`); } catch {}
  if (getStoredDemoUiState()?.demo_mode && String(getStoredDemoUiState()?.demo_persona || "OWNER").toUpperCase() === resolvedPersona) {
    reopenDemoTour();
  }
}

function maybeAutoStartDemoTour() {
  if (!isBrowser()) return;
  const currentState = getStoredDemoUiState();
  if (!currentState?.demo_mode) {
    __demoTourPendingOpen = true;
    if (__demoTourRetryCount < 12) {
      __demoTourRetryCount += 1;
      clearTimeout(__demoTourRetryTimer);
      __demoTourRetryTimer = setTimeout(() => maybeAutoStartDemoTour(), 250);
    }
    return;
  }
  __demoTourRetryCount = 0;
  clearTimeout(__demoTourRetryTimer);

  const persona = String(currentState.demo_persona || "OWNER").toUpperCase();
  const state = readDemoTourState(persona);
  const pageCfg = __pageTourConfigFor();
  const info = currentTourStep(persona, state.index);

  if (pageCfg) {
    if (state.hidden) {
      removeDemoTourOverlay();
      renderDemoTourDock(persona);
      return;
    }
    showDemoTourOverlay(persona);
    return;
  }

  if (!info.step) return;
  if (!currentPageMatchesTourStep(info.step)) {
    removeDemoTourOverlay();
    renderDemoTourDock(persona);
    return;
  }
  if (state.hidden) {
    removeDemoTourOverlay();
    renderDemoTourDock(persona);
    return;
  }
  showDemoTourOverlay(persona);
}

function bootstrapDemoTour() {
  if (!isBrowser() || __demoTourMounted) return;
  __demoTourMounted = true;
  const run = () => maybeAutoStartDemoTour();
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", run, { once: true });
  else run();
  window.addEventListener("axelio:demo-state-changed", () => {
    if (__demoTourPendingOpen) {
      __demoTourPendingOpen = false;
      setTimeout(() => maybeAutoStartDemoTour(), 0);
    } else {
      setTimeout(() => maybeAutoStartDemoTour(), 0);
    }
  });
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
  const text = String(msg ?? "").trim();
  const now = Date.now();
  if (text && __lastToastMeta.text === text && __lastToastMeta.type === type && (now - (__lastToastMeta.at || 0)) < 900) {
    return;
  }
  __lastToastMeta = { text, type, at: now };

  const box = document.getElementById("toast");
  if (!box) return alert(text || msg);

  box.className = "toast show " + type;
  box.querySelector(".toast__text").textContent = text || String(msg || "");

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

  mountDemoBanner();

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
    const errorCode = String(data?.error_code || data?.code || "").trim().toUpperCase();
    const err = new Error(errorCode === DEMO_READONLY_ERROR_CODE ? (data?.detail || "Это пробный режим. Изменения здесь недоступны.") : `HTTP ${r.status} ${r.statusText}: ${extractErrorMessage(data)}`);
    err.status = r.status;
    err.data = data;
    err.url = r.url;
    err.code = errorCode || err.code;

    if (errorCode === DEMO_READONLY_ERROR_CODE && !opts.skipDemoReadonlyToast) {
      toast(data?.detail || "Это пробный режим. Изменения здесь недоступны.", "warn");
    }

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
  const me = await withTimeout(api("/me"), timeoutMs, "ME_TIMEOUT");
  const demoState = storeDemoUiState(me);
  if (demoState?.demo_mode) mountDemoBanner(demoState);
  else removeDemoBanner();
  return me;
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
        { title: "DEMO", href: "/admin-demo.html", tab: "admin-demo" },
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

export const API_BASE = "https://api-dev.axelio.ru";

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
    shifts: "Смены",
    salary: "Зарплата",
    report: "Отчёт",
    admin_venues: "Заведения",
    admin_invites: "Инвайты",
  },
  en: {
    venue: "Venue",
    manage_venues: "Manage venues",
    leave_venue: "Leave venue",
    settings: "Settings",
    adjustments: "Adjustments",
    shifts: "Shifts",
    salary: "Salary",
    report: "Report",
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

export function applyTelegramTheme() {
  const w = wa();
  const el = document.querySelector("[data-userpill]");
  if (!w) {
    if (el) el.textContent = "не в Telegram";
    return;
  }

  w.ready();

  const t = w.themeParams || {};
  const set = (k, v) => v && document.documentElement.style.setProperty(k, v);

  set("--bg", t.bg_color);
  set("--card", t.secondary_bg_color);
  set("--text", t.text_color);
  set("--muted", t.hint_color);
  set("--accent", t.button_color);
  set("--accentText", t.button_text_color);

  const u = w.initDataUnsafe?.user;
  if (el) el.textContent = u ? `@${u.username || "без_username"}` : "неизвестно";
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
  if (isPlainObject(body)) body = JSON.stringify(body);

  const r = await fetch(url, {
    ...opts,
    body,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(opts.headers || {}),
    },
  });

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
    throw err;
  }

  return data;
}

export async function ensureLogin({ silent = true } = {}) {
  const w = wa();
  const initData = w?.initData || "";

  if (!initData) {
    if (!silent) toast("Нет initData. Открой через Telegram Mini App.", "warn");
    return { ok: false, reason: "NO_INITDATA" };
  }

  try {
    const out = await api("/auth/telegram", {
      method: "POST",
      body: { initData }, // <-- ключ initData
    });

    if (!silent) toast("Вход выполнен", "ok");
    return { ok: true, data: out };
  } catch (e) {
    if (!silent) {
      const msg = e?.message || "Ошибка входа";
      toast(msg, "err");
    }
    return {
      ok: false,
      status: e?.status,
      data: e?.data,
      message: e?.message,
    };
  }
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

export async function getMe() {
  return api("/me");
}

export async function getMyVenues() {
  return api("/me/venues");
}

export async function getMyVenuePermissions(venueId) {
  if (!venueId) return { venue_id: null, role: null, permissions: [] };
  return api(`/me/venues/${encodeURIComponent(venueId)}/permissions`);
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

/**
 * Boots a page: ensures login (cookie), loads /me,
 * optionally enforces an active venue (from LS or query).
 */
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

// ------------------------------
// Permissions + dynamic navigation (A2/A3)
// ------------------------------

function normalizePermList(permissions) {
  if (!permissions) return [];
  if (Array.isArray(permissions)) {
    // may be ["CODE", ...] or [{code:"CODE"}, ...]
    return permissions
      .map((p) => (typeof p === "string" ? p : p?.code))
      .filter(Boolean)
      .map((s) => String(s));
  }
  // may be {CODE:true} or {permissions:[...]}
  if (permissions && typeof permissions === "object") {
    if (Array.isArray(permissions.permissions)) return normalizePermList(permissions.permissions);
    return Object.keys(permissions).filter((k) => permissions[k]);
  }
  return [];
}

export function can(permCode, venuePerms) {
  if (!permCode) return false;
  const list = normalizePermList(venuePerms?.permissions || venuePerms);
  return list.includes(String(permCode));
}

function setActiveNavTab(activeTab) {
  document.querySelectorAll("[data-tab]").forEach((a) => {
    if (a.getAttribute("data-tab") === activeTab) a.classList.add("active");
    else a.classList.remove("active");
  });
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

  await ensureLogin({ silent: true });

  let me = null;
  try { me = await getMe(); } catch {
    container.innerHTML = "";
    return { ok: false, reason: "NO_ME" };
  }

  // SUPER_ADMIN bottom nav
  if (me?.system_role === "SUPER_ADMIN") {
    renderNavLinks({
      container,
      links: [
        { title: t("admin_venues"), href: "/admin-venues.html", tab: "admin-venues" },
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
  if (!activeVenueId && venues.length === 1) {
    activeVenueId = String(venues[0].id);
    setActiveVenueId(activeVenueId);
  }

  // Determine if report tab should be shown (best-effort)
  let showReport = false;
  if (activeVenueId) {
    try {
      const perms = await getMyVenuePermissions(activeVenueId);
      const has = (code) => Array.isArray(perms?.permissions) ? perms.permissions.includes(code) : false;
      const flags = perms?.position_flags || {};
      const posObj = perms?.position || {};
      showReport =
        perms?.can_make_reports === true ||
        flags.can_make_reports === true ||
        flags.can_view_reports === true ||
        posObj.can_make_reports === true ||
        posObj.can_view_reports === true ||
        has("SHIFT_REPORTS_CREATE") ||
        has("SHIFT_REPORTS_EDIT");
    } catch {
      showReport = false;
    }
  }

  const qp = activeVenueId ? `?venue_id=${encodeURIComponent(activeVenueId)}` : "";
  const links = [];

  if (activeVenueId) {
    links.push({ title: t("adjustments"), href: `/staff-adjustments.html${qp}`, tab: "adjustments" });
    links.push({ title: t("shifts"), href: `/staff-shifts.html${qp}`, tab: "shifts" });
    links.push({ title: t("salary"), href: `/staff-salary.html${qp}`, tab: "salary" });
    if (showReport) links.push({ title: t("report"), href: `/staff-report.html${qp}`, tab: "report" });
  }
  links.push({ title: "⚙️", href: "/settings.html", tab: "settings", className: "icon" });

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
  sel.className = "venue-switch__select";

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

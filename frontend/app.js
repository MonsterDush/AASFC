export const API_BASE = "https://api-dev.axelio.ru";

export function wa() {
  return window.Telegram?.WebApp || null;
}

export function applyTelegramTheme() {
  const w = wa();
  const el = document.querySelector("[data-userpill]");
  if (!w) {
    if (el) el.textContent = "not in Telegram";
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
  if (el) el.textContent = u ? `@${u.username || "no_username"}` : "unknown";
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

    if (!silent) toast("Login OK", "ok");
    return { ok: true, data: out };
  } catch (e) {
    if (!silent) {
      const msg = e?.message || "Login error";
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

export function confirmModal({ title, text, confirmText = "Confirm", danger = false }) {
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
    btnCancel.textContent = "Cancel";

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

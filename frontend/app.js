// app.js — общий код UI + API + telegram theme + toast + modal + auto-login

export const API_BASE = "https://api-dev.axelio.ru";

export function wa() {
  return window.Telegram?.WebApp || null;
}

export function applyTelegramTheme() {
  const w = wa();
  if (!w) return;
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
  const el = document.querySelector("[data-userpill]");
  if (el) {
    el.textContent = u ? `@${u.username || "no_username"}` : "unknown";
  }
}

export function toast(msg, type = "info") {
  const box = document.getElementById("toast");
  if (!box) return alert(msg);

  box.className = "toast show " + type;
  box.querySelector(".toast__text").textContent = msg;
  clearTimeout(box._t);
  box._t = setTimeout(() => box.className = "toast", 2400);
}

export function openModal(title, jsonOrText) {
  const m = document.getElementById("modal");
  if (!m) return;

  m.querySelector(".modal__title").textContent = title;

  const body = m.querySelector(".modal__body");
  body.textContent = "";

  const pre = document.createElement("pre");
  pre.className = "json";
  pre.textContent = typeof jsonOrText === "string"
    ? jsonOrText
    : JSON.stringify(jsonOrText, null, 2);
  body.appendChild(pre);

  m.classList.add("open");
}
export function closeModal() {
  const m = document.getElementById("modal");
  if (m) m.classList.remove("open");
}

export async function api(path, opts = {}) {
  const r = await fetch(API_BASE + path, {
    ...opts,
    credentials: "include",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
  });

  const text = await r.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }

  if (!r.ok) {
    const msg = typeof data === "string" ? data : JSON.stringify(data);
    throw new Error(msg || `HTTP ${r.status}`);
  }
  return data;
}

// auto-login: если cookie нет — просто пробуем логиниться; если уже залогинен — /me пройдёт
export async function ensureLogin({ silent = true } = {}) {
  const w = wa();
  const initData = w?.initData || "";

  if (!initData) {
    if (!silent) toast("Открой через Telegram Mini App (нет initData)", "warn");
    return { ok: false, reason: "no_initData" };
  }

  try {
    await api("/auth/telegram", {
      method: "POST",
      body: JSON.stringify({ initData }),
    });
    if (!silent) toast("Login OK", "ok");
    return { ok: true };
  } catch (e) {
    if (!silent) toast("Login error: " + e.message, "err");
    return { ok: false, reason: e.message };
  }
}

export function mountCommonUI(activeTab) {
  // Навигация подсвечивается по data-tab
  document.querySelectorAll("[data-tab]").forEach(a => {
    if (a.getAttribute("data-tab") === activeTab) a.classList.add("active");
  });

  // modal close
  const modal = document.getElementById("modal");
  if (modal) {
    modal.querySelector("[data-close]").onclick = closeModal;
    modal.querySelector(".modal__backdrop").onclick = closeModal;
  }

  // “View JSON” helper
  document.querySelectorAll("[data-viewjson]").forEach(btn => {
    btn.onclick = () => openModal(btn.getAttribute("data-title") || "JSON", window.__lastJson || {});
  });
}

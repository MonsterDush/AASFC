// Canonical revenue page for owners. Legacy route: /owner-revenue.html -> redirect.
import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  api,
  API_BASE,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
} from "/app.js";

let state = {
  period: "month",
  mode: "DEPARTMENTS",
  month: null,
  day: null,
  from: null,
  to: null,
};

function $(id) { return document.getElementById(id); }

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function fmtMoney(n) {
  const x = Math.round(Number(n || 0));
  try { return new Intl.NumberFormat("ru-RU").format(x) + " ₽"; } catch { return String(x) + " ₽"; }
}

function startOfWeekISO(dateStr) { // YYYY-MM-DD
  const d = new Date(dateStr + "T00:00:00");
  const day = (d.getDay() + 6) % 7; // Mon=0
  d.setDate(d.getDate() - day);
  return d.toISOString().slice(0, 10);
}

function addDaysISO(dateStr, days) {
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function normalizeState() {
  state.month = (state.month || currentMonth()).slice(0, 7);
  state.day = state.day || todayISO();
  state.from = state.from || todayISO();
  state.to = state.to || todayISO();

  if (state.period === "range" && state.from > state.to) {
    [state.from, state.to] = [state.to, state.from];
  }
}

function syncPickers() {
  const monthPick = $("monthPick");
  const dayPick = $("dayPick");
  const rangePick = $("rangePick");

  normalizeState();

  if (monthPick) monthPick.style.display = state.period === "month" ? "" : "none";
  if (dayPick) dayPick.style.display = (state.period === "day" || state.period === "week") ? "" : "none";
  if (rangePick) rangePick.style.display = state.period === "range" ? "flex" : "none";

  if (monthPick) monthPick.value = state.month;
  if (dayPick) dayPick.value = state.day;
  if ($("fromPick")) $("fromPick").value = state.from;
  if ($("toPick")) $("toPick").value = state.to;

  renderPeriodHint();
}

function buildQuery() {
  normalizeState();

  const qp = new URLSearchParams();
  qp.set("mode", state.mode);

  if (state.period === "month") {
    qp.set("month", state.month || currentMonth());
  } else if (state.period === "day") {
    qp.set("date_from", state.day || todayISO());
    qp.set("date_to", state.day || todayISO());
  } else if (state.period === "week") {
    const baseDay = state.day || todayISO();
    const monday = startOfWeekISO(baseDay);
    qp.set("date_from", monday);
    qp.set("date_to", addDaysISO(monday, 6));
  } else {
    qp.set("date_from", state.from || todayISO());
    qp.set("date_to", state.to || todayISO());
  }

  return qp.toString();
}

function formatHumanDate(dateStr) {
  if (!dateStr) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "long", year: "numeric" }).format(new Date(`${dateStr}T00:00:00`));
  } catch {
    return dateStr;
  }
}

function formatHumanMonth(monthStr) {
  if (!monthStr) return "—";
  try {
    const [y, m] = String(monthStr).split("-").map(Number);
    return new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric" }).format(new Date(y, (m || 1) - 1, 1));
  } catch {
    return monthStr;
  }
}

function renderPeriodHint() {
  const el = $("periodHint");
  if (!el) return;

  if (state.period === "month") {
    el.textContent = `За ${formatHumanMonth(state.month)}`;
    return;
  }
  if (state.period === "day") {
    el.textContent = formatHumanDate(state.day);
    return;
  }
  if (state.period === "week") {
    const monday = startOfWeekISO(state.day || todayISO());
    el.textContent = `${formatHumanDate(monday)} — ${formatHumanDate(addDaysISO(monday, 6))}`;
    return;
  }
  el.textContent = `${formatHumanDate(state.from)} — ${formatHumanDate(state.to)}`;
}

function syncUrl() {
  const qp = new URLSearchParams();
  qp.set("period", state.period);
  qp.set("mode", state.mode);

  if (getActiveVenueId()) qp.set("venue_id", String(getActiveVenueId()));

  if (state.period === "month") qp.set("month", state.month || currentMonth());
  if (state.period === "day" || state.period === "week") qp.set("day", state.day || todayISO());
  if (state.period === "range") {
    qp.set("date_from", state.from || todayISO());
    qp.set("date_to", state.to || todayISO());
  }

  history.replaceState(null, "", `${location.pathname}?${qp.toString()}`);
}

async function load() {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  syncUrl();
  const qs = buildQuery();
  const data = await api(`/venues/${encodeURIComponent(venueId)}/revenue?${qs}`);

  $("total").textContent = fmtMoney(data?.total || 0);

  const rowsEl = $("rows");
  rowsEl.innerHTML = "";

  const rows = Array.isArray(data?.rows) ? data.rows : [];
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "muted";
    empty.style.padding = "6px 0";
    empty.textContent = "Нет данных за выбранный период";
    rowsEl.appendChild(empty);
    return;
  }

  for (const r of rows) {
    const el = document.createElement("div");
    el.className = "row";
    el.style.justifyContent = "space-between";
    el.style.padding = "8px 0";
    const title = r?.title || r?.name || r?.code || "—";
    el.innerHTML = `<div>${esc(title)}</div><div class="mono">${esc(fmtMoney(r?.amount || 0))}</div>`;
    rowsEl.appendChild(el);
  }
}

function setActiveSeg(containerId, dataKey, value) {
  document.querySelectorAll(`#${containerId} button`).forEach((b) => {
    if (b.dataset[dataKey] === value) b.classList.add("active");
    else b.classList.remove("active");
  });
}

function applySeg(containerId, key) {
  document.querySelectorAll(`#${containerId} button`).forEach((btn) => {
    btn.onclick = () => {
      const val = btn.dataset[key];
      if (!val) return;
      state[key] = val;
      setActiveSeg(containerId, key, val);
      syncPickers();
      load().catch((e) => toast("Ошибка: " + (e?.message || e), "err"));
    };
  });
}

function initFromQuery() {
  const q = new URLSearchParams(location.search);
  const nowMonth = currentMonth();
  const today = todayISO();

  state.mode = q.get("mode") || "DEPARTMENTS";
  state.period = q.get("period") || "month";

  state.month = (q.get("month") || nowMonth).slice(0,7);
  state.day = q.get("day") || q.get("date_from") || today;
  state.from = q.get("date_from") || today;
  state.to = q.get("date_to") || today;

  normalizeState();

  $("monthPick").value = state.month || currentMonth();
  $("dayPick").value = state.day;
  $("fromPick").value = state.from;
  $("toPick").value = state.to;

  setActiveSeg("modeSeg", "mode", state.mode);
  setActiveSeg("periodSeg", "period", state.period);
}

function bindPickers() {
  $("monthPick").onchange = (e) => {
    state.month = e.target.value || currentMonth();
    syncPickers();
    load().catch(console.error);
  };
  $("dayPick").onchange = (e) => {
    state.day = e.target.value || todayISO();
    syncPickers();
    load().catch(console.error);
  };
  $("fromPick").onchange = (e) => {
    state.from = e.target.value || todayISO();
    syncPickers();
    load().catch(console.error);
  };
  $("toPick").onchange = (e) => {
    state.to = e.target.value || todayISO();
    syncPickers();
    load().catch(console.error);
  };

  $("exportBtn").onclick = async () => {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  const qs = buildQuery();
  try {
    const url = `${API_BASE}/venues/${encodeURIComponent(venueId)}/revenue/export?${qs}&fmt=xlsx`;

    const tg = window.Telegram?.WebApp;
    try {
      if (tg?.openLink) {
        tg.openLink(url, { try_instant_view: false });
        return;
      }
    } catch {}

    window.location.href = url;
  } catch (e) {
    console.error(e);
    toast("Не удалось начать экспорт");
  }
};
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);

  await mountNav({ activeTab: "summary" }); // page is reached from Summary

  // subtitle: venue name
  try {
    const venues = await getMyVenues();
    const v = venues.find(x => String(x.id) === String(getActiveVenueId()));
    if (v) $("subtitle").textContent = v.name || "";
  } catch {}

  initFromQuery();
  syncPickers();
  applySeg("modeSeg", "mode");
  applySeg("periodSeg", "period");
  bindPickers();

  await load();
}

document.addEventListener("DOMContentLoaded", () => {
  boot().catch((e) => toast("Ошибка: " + (e?.message || e), "err"));
});

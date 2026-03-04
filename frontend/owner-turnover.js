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

function syncPickers() {
  const monthPick = $("monthPick");
  const dayPick = $("dayPick");
  const rangePick = $("rangePick");

  if (monthPick) monthPick.style.display = state.period === "month" ? "" : "none";
  if (dayPick) dayPick.style.display = (state.period === "day" || state.period === "week") ? "" : "none";
  if (rangePick) rangePick.style.display = state.period === "range" ? "flex" : "none";
}

function buildQuery() {
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

async function load() {
  const venueId = getActiveVenueId();
  if (!venueId) return;

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
  state.day = q.get("day") || today;
  state.from = q.get("date_from") || today;
  state.to = q.get("date_to") || today;

  $("monthPick").value = state.month || currentMonth();
  $("dayPick").value = state.day;
  $("fromPick").value = state.from;
  $("toPick").value = state.to;

  setActiveSeg("modeSeg", "mode", state.mode);
  setActiveSeg("periodSeg", "period", state.period);
}

function bindPickers() {
  $("monthPick").onchange = (e) => { state.month = e.target.value || currentMonth(); load().catch(console.error); };
  $("dayPick").onchange = (e) => { state.day = e.target.value || todayISO(); load().catch(console.error); };
  $("fromPick").onchange = (e) => { state.from = e.target.value || todayISO(); load().catch(console.error); };
  $("toPick").onchange = (e) => { state.to = e.target.value || todayISO(); load().catch(console.error); };

  
$("exportBtn").onclick = async () => {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  const qs = buildQuery();
  try {
    // 1) Request signed public link (requires auth in miniapp, uses cookies)
    const link = await api(`/venues/${encodeURIComponent(venueId)}/revenue/export_link?${qs}&fmt=xlsx`, { method: "GET" });
    const url = (link.path ? (API_BASE + link.path) : (API_BASE + `/venues/${encodeURIComponent(venueId)}/revenue/export?${qs}&fmt=xlsx`));

    // 2) Open in browser / Telegram in-app browser (downloads work there without auth)
    const tg = window.Telegram?.WebApp;
    try {
      if (tg?.openLink) {
        tg.openLink(url, { try_instant_view: false });
        return;
      }
    } catch {}
    window.open(url, "_blank");
  } catch (e) {
    console.error(e);
    toast("Не удалось создать ссылку на экспорт");
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

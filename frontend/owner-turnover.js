// Canonical revenue page for owners. Legacy route: /owner-revenue.html -> redirect.
import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  downloadFile,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

let state = {
  period: "month",
  mode: "DEPARTMENTS",
  month: null,
  day: null,
  from: null,
  to: null,
  canView: true,
  canExport: true,
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

function startOfWeekISO(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const day = (d.getDay() + 6) % 7;
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

function normalizeRange() {
  if (!state.from) state.from = todayISO();
  if (!state.to) state.to = state.from;
  if (state.from > state.to) {
    const x = state.from;
    state.from = state.to;
    state.to = x;
  }
}

function syncPickers() {
  const monthPick = $("monthPick");
  const dayPick = $("dayPick");
  const rangePick = $("rangePick");

  if (monthPick) monthPick.style.display = state.period === "month" ? "" : "none";
  if (dayPick) dayPick.style.display = (state.period === "day" || state.period === "week") ? "" : "none";
  if (rangePick) rangePick.style.display = state.period === "range" ? "flex" : "none";
}

function periodLabel() {
  if (state.period === "month") return `За ${state.month || currentMonth()}`;
  if (state.period === "day") return `За ${state.day || todayISO()}`;
  if (state.period === "week") {
    const start = startOfWeekISO(state.day || todayISO());
    return `Неделя ${start} — ${addDaysISO(start, 6)}`;
  }
  normalizeRange();
  return `Период ${state.from} — ${state.to}`;
}

function syncCaption() {
  const el = $("periodCaption");
  if (el) el.textContent = periodLabel();
}

function buildQuery() {
  const qp = new URLSearchParams();
  qp.set("mode", state.mode);
  qp.set("period", state.period);

  if (state.period === "month") {
    qp.set("month", state.month || currentMonth());
  } else if (state.period === "day") {
    qp.set("day", state.day || todayISO());
    qp.set("date_from", state.day || todayISO());
    qp.set("date_to", state.day || todayISO());
  } else if (state.period === "week") {
    const baseDay = state.day || todayISO();
    const monday = startOfWeekISO(baseDay);
    qp.set("day", baseDay);
    qp.set("date_from", monday);
    qp.set("date_to", addDaysISO(monday, 6));
  } else {
    normalizeRange();
    qp.set("date_from", state.from || todayISO());
    qp.set("date_to", state.to || todayISO());
  }

  return qp;
}

function syncUrl() {
  const qp = buildQuery();
  const venueId = getActiveVenueId();
  if (venueId) qp.set("venue_id", venueId);
  const target = `${location.pathname}?${qp.toString()}`;
  history.replaceState(null, "", target);
}

async function load() {
  const venueId = getActiveVenueId();
  if (!venueId || !state.canView) return;

  normalizeRange();
  syncCaption();
  syncUrl();

  const qs = buildQuery().toString();
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
  state.period = q.get("period") || (q.get("month") ? "month" : (q.get("date_from") && q.get("date_to") ? "range" : "month"));

  state.month = (q.get("month") || nowMonth).slice(0,7);
  state.day = q.get("day") || q.get("date_from") || today;
  state.from = q.get("date_from") || today;
  state.to = q.get("date_to") || today;
  normalizeRange();

  $("monthPick").value = state.month || currentMonth();
  $("dayPick").value = state.day;
  $("fromPick").value = state.from;
  $("toPick").value = state.to;

  setActiveSeg("modeSeg", "mode", state.mode);
  setActiveSeg("periodSeg", "period", state.period);
  syncCaption();
}

function bindPickers() {
  $("monthPick").onchange = (e) => { state.month = e.target.value || currentMonth(); load().catch(console.error); };
  $("dayPick").onchange = (e) => { state.day = e.target.value || todayISO(); load().catch(console.error); };
  $("fromPick").onchange = (e) => { state.from = e.target.value || todayISO(); load().catch(console.error); };
  $("toPick").onchange = (e) => { state.to = e.target.value || todayISO(); load().catch(console.error); };

  $("exportBtn").onclick = async () => {
    const venueId = getActiveVenueId();
    if (!venueId || !state.canExport) return;

    const qs = buildQuery().toString();
    const btn = $("exportBtn");
    const prev = btn?.textContent || "Экспорт XLSX";

    try {
      if (btn) {
        btn.disabled = true;
        btn.textContent = "Скачивание…";
      }

      const modeLabel = (state.mode || "DEPARTMENTS").toUpperCase() === "PAYMENTS" ? "payments" : "departments";
      const periodLabel = state.period === "month"
        ? (state.month || currentMonth())
        : state.period === "day"
          ? (state.day || todayISO())
          : `${state.from || todayISO()}_${state.to || todayISO()}`;

      await downloadFile(
        `/venues/${encodeURIComponent(venueId)}/revenue/export?${qs}&fmt=xlsx`,
        { filenameFallback: `revenue_${periodLabel}_${modeLabel}.xlsx` }
      );
    } catch (e) {
      console.error(e);
      toast(e?.message || "Не удалось скачать экспорт", "err");
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.textContent = prev;
      }
    }
  };
}

async function resolveRevenueAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  try {
    const permsResp = await api(`/me/venues/${encodeURIComponent(venueId)}/permissions`);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isPrivileged = role === "OWNER" || role === "VENUE_OWNER" || role === "SUPER_ADMIN" || role === "MODERATOR";

    state.canView = isPrivileged || hasPerm(pset, "REVENUE_VIEW");
    state.canExport = isPrivileged || hasPerm(pset, "REVENUE_EXPORT");
  } catch {
    state.canView = true;
    state.canExport = true;
  }

  const exportBtn = $("exportBtn");
  if (exportBtn) exportBtn.style.display = state.canExport ? "" : "none";

  if (!state.canView) {
    toast("Нет доступа к выручке", "err");
    const venue = getActiveVenueId();
    const qp = venue ? `?venue_id=${encodeURIComponent(venue)}` : "";
    setTimeout(() => { location.replace(`/owner-summary.html${qp}`); }, 150);
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);

  await mountNav({ activeTab: "summary" });

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
  await resolveRevenueAccess();
  if (!state.canView) return;
  await load();
}

document.addEventListener("DOMContentLoaded", () => {
  boot().catch((e) => toast("Ошибка: " + (e?.message || e), "err"));
});

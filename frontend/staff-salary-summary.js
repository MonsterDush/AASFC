import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  api,
  toast,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
} from "/app.js";

import { permSetFromResponse, hasPermPrefix, hasAnyPerm, roleUpper } from "/permissions.js";

applyTelegramTheme();
mountCommonUI("finance");
await ensureLogin({ silent: true });

// keep venue context for navbar (even though the summary is cross-venue)
const params = new URLSearchParams(location.search);
const venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);
let __tab = "salary";
try {
  const pr = await (venueId ? api(`/me/venues/${encodeURIComponent(venueId)}/permissions`) : null);
  const pset = permSetFromResponse(pr);
  const role = roleUpper(pr);
  const canViewReports =
    role === "OWNER" || role === "SUPER_ADMIN" || role === "MODERATOR" ||
    hasPermPrefix(pset, "SHIFT_REPORT_") || hasPermPrefix(pset, "REPORTS_") ||
    hasAnyPerm(pset, ["SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_REOPEN"]);
  if (canViewReports) __tab = "finance";
} catch {}
await mountNav({ activeTab: __tab, requireVenue: true });

// best-effort subtitle with current venue
try {
  const venues = await getMyVenues();
  const v = venues.find((x) => String(x.id) === String(getActiveVenueId()));
  if (v?.name) document.getElementById("subtitle").textContent = `по всем заведениям · текущий контекст: ${v.name}`;
} catch {}

const el = {
  monthLabel: document.getElementById("monthLabel"),
  monthPicker: document.getElementById("monthPicker"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  reload: document.getElementById("btnReload"),
  tEarned: document.getElementById("tEarned"),
  tTips: document.getElementById("tTips"),
  tBonuses: document.getElementById("tBonuses"),
  tPenalties: document.getElementById("tPenalties"),
  tNet: document.getElementById("tNet"),
  venuesCount: document.getElementById("venuesCount"),
  list: document.getElementById("venuesList"),
};

function pad2(n) {
  return String(n).padStart(2, "0");
}

function ym(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function monthTitle(d) {
  const ru = [
    "январь", "февраль", "март", "апрель", "май", "июнь",
    "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь",
  ];
  const m = ru[d.getMonth()] || "";
  const cap = m ? (m[0].toUpperCase() + m.slice(1)) : "—";
  return `${cap} ${d.getFullYear()}`;
}

function fmtMoney(n) {
  const v = Math.round(Number(n || 0));
  return v.toLocaleString("ru-RU");
}

function esc(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

let cur = new Date();
cur.setDate(1);

// allow ?month=YYYY-MM
const qMonth = params.get("month");
if (qMonth && /^\d{4}-\d{2}$/.test(qMonth)) {
  const [yy, mm] = qMonth.split("-").map((x) => parseInt(x, 10));
  if (yy && mm) cur = new Date(yy, mm - 1, 1);
}

function syncUrl() {
  const p = new URLSearchParams(location.search);
  p.set("month", ym(cur));
  if (getActiveVenueId()) p.set("venue_id", String(getActiveVenueId()));
  history.replaceState({}, "", `${location.pathname}?${p.toString()}`);
}

function renderSkeleton() {
  el.list.innerHTML = `
    <div class="venue-card"><div class="skeleton"></div></div>
    <div class="venue-card"><div class="skeleton"></div></div>
  `;
}

function renderVenueCard(it) {
  const name = it?.venue?.name || `venue #${it?.venue?.id || "?"}`;

  const earned = fmtMoney(it?.earned);
  const tips = fmtMoney(it?.tips);
  const bonuses = fmtMoney(it?.bonuses);
  const penalties = fmtMoney(it?.penalties);
  const net = fmtMoney(it?.net);

  const card = document.createElement("div");
  card.className = "venue-card";
  card.innerHTML = `
    <div class="venue-top">
      <div style="min-width:0">
        <div class="venue-name">${esc(name)}</div>
      </div>
      <div class="venue-net">
        <div class="muted">Итого</div>
        <b>${net}</b>
      </div>
    </div>

    <div class="chips">
      <div class="chip">Начислено: <b>${earned}</b></div>
      <div class="chip">Чаевые: <b>${tips}</b></div>
      <div class="chip">Премии: <b>${bonuses}</b></div>
      <div class="chip">Штрафы: <b>${penalties}</b></div>
    </div>
  `;
  return card;
}

async function load() {
  syncUrl();

  el.monthLabel.textContent = monthTitle(cur);
  if (el.monthPicker) el.monthPicker.value = ym(cur);

  if (el.venuesCount) el.venuesCount.textContent = "";
  renderSkeleton();

  try {
    const data = await api(`/me/salary-summary?month=${encodeURIComponent(ym(cur))}`);
    const totals = data?.totals || {};

    el.tEarned.textContent = fmtMoney(totals.earned);
    el.tTips.textContent = fmtMoney(totals.tips);
    el.tBonuses.textContent = fmtMoney(totals.bonuses);
    el.tPenalties.textContent = fmtMoney(totals.penalties);
    el.tNet.textContent = fmtMoney(totals.net);

    const items = Array.isArray(data?.items) ? data.items : [];
    if (el.venuesCount) el.venuesCount.textContent = items.length ? `${items.length}` : "";

    if (!items.length) {
      el.list.innerHTML = `<div class="muted">За этот месяц данных нет</div>`;
      return;
    }

    el.list.innerHTML = "";
    items.forEach((it) => el.list.appendChild(renderVenueCard(it)));
  } catch (e) {
    console.error(e);
    toast(e?.data?.detail || e?.message || "Не удалось загрузить сводку", "err");
    el.list.innerHTML = `<div class="muted">Ошибка загрузки</div>`;
  }
}

el.prev.onclick = () => {
  cur = new Date(cur.getFullYear(), cur.getMonth() - 1, 1);
  load();
};

el.next.onclick = () => {
  cur = new Date(cur.getFullYear(), cur.getMonth() + 1, 1);
  load();
};

el.monthPicker && (el.monthPicker.onchange = () => {
  const v = String(el.monthPicker.value || "").trim();
  if (/^\d{4}-\d{2}$/.test(v)) {
    const [yy, mm] = v.split("-").map((x) => parseInt(x, 10));
    if (yy && mm) cur = new Date(yy, mm - 1, 1);
    load();
  }
});

el.reload.onclick = () => load();

await load();
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

applyTelegramTheme();
mountCommonUI("finance");
await ensureLogin({ silent: true });

// keep venue context for navbar (even though the summary is cross-venue)
const params = new URLSearchParams(location.search);
const venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);
await mountNav({ activeTab: "finance", requireVenue: true });

// best-effort subtitle with current venue
try {
  const venues = await getMyVenues();
  const v = venues.find((x) => String(x.id) === String(getActiveVenueId()));
  if (v?.name) document.getElementById("subtitle").textContent = `по всем заведениям · текущий контекст: ${v.name}`;
} catch {}

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  reload: document.getElementById("btnReload"),
  tEarned: document.getElementById("tEarned"),
  tTips: document.getElementById("tTips"),
  tBonuses: document.getElementById("tBonuses"),
  tPenalties: document.getElementById("tPenalties"),
  tNet: document.getElementById("tNet"),
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
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
  ];
  return `${ru[d.getMonth()]} ${d.getFullYear()}`;
}

function fmtMoney(n) {
  const v = Math.round(Number(n || 0));
  return v.toLocaleString("ru-RU");
}

let cur = new Date();
cur.setDate(1);

// allow ?month=YYYY-MM
const qMonth = params.get("month");
if (qMonth && /^\d{4}-\d{2}$/.test(qMonth)) {
  const [yy, mm] = qMonth.split("-").map((x) => parseInt(x, 10));
  if (yy && mm) {
    cur = new Date(yy, mm - 1, 1);
  }
}

function syncUrl() {
  const p = new URLSearchParams(location.search);
  p.set("month", ym(cur));
  if (getActiveVenueId()) p.set("venue_id", String(getActiveVenueId()));
  history.replaceState({}, "", `${location.pathname}?${p.toString()}`);
}

async function load() {
  syncUrl();
  el.monthLabel.textContent = monthTitle(cur);
  el.list.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;

  try {
    const data = await api(`/me/salary-summary?month=${encodeURIComponent(ym(cur))}`);
    const totals = data?.totals || {};

    el.tEarned.textContent = fmtMoney(totals.earned);
    el.tTips.textContent = fmtMoney(totals.tips);
    el.tBonuses.textContent = fmtMoney(totals.bonuses);
    el.tPenalties.textContent = fmtMoney(totals.penalties);
    el.tNet.textContent = fmtMoney(totals.net);

    const items = Array.isArray(data?.items) ? data.items : [];
    if (!items.length) {
      el.list.innerHTML = `<div class="muted">За этот месяц данных нет</div>`;
      return;
    }

    el.list.innerHTML = "";
    items.forEach((it) => {
      const name = it?.venue?.name || `venue #${it?.venue?.id || "?"}`;
      const row = document.createElement("div");
      row.className = "row";
      row.style = "justify-content:space-between; border-bottom:1px solid var(--border); padding:10px 0; gap:12px; align-items:flex-start";
      row.innerHTML = `
        <div style="min-width:0">
          <b style="display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${name}</b>
          <div class="muted" style="margin-top:4px; font-size:12px">Начислено ${fmtMoney(it.earned)} · Чаевые ${fmtMoney(it.tips)} · Премии ${fmtMoney(it.bonuses)} · Штрафы ${fmtMoney(it.penalties)}</div>
        </div>
        <div style="text-align:right; flex:0 0 auto">
          <div class="muted" style="font-size:12px">Итого</div>
          <b>${fmtMoney(it.net)}</b>
        </div>
      `;
      el.list.appendChild(row);
    });
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

el.reload.onclick = () => load();

await load();

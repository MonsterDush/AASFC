import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
} from "/app.js";

import { permSetFromResponse, roleUpper, canViewReports as canViewReportsPerms } from "/permissions.js";

applyTelegramTheme();
mountCommonUI("salary");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);

// preload venues once (used for: auto-pick active venue + show/hide "all venues" switch)
let __venues = [];
try { __venues = await getMyVenues().catch(() => []); } catch { __venues = []; }
const __venueIdOf = (v) => v?.id ?? v?.venue_id ?? v?.venueId ?? v?.venueID;
const __venueNameOf = (id) => {
  if (id == null) return "";
  const sid = String(id);
  // getMyVenues() may return {id, name} or {venue_id, venue_name}
  const v = (__venues || []).find((x) => String(__venueIdOf(x) ?? "") === sid);
  return v?.name || v?.venue_name || v?.title || "";
};


let venueId = params.get("venue_id") || getActiveVenueId();
if (!venueId && Array.isArray(__venues) && __venues.length) {
  const id0 = __venueIdOf(__venues[0]);
  if (id0 != null) venueId = String(id0);
}
if (venueId) setActiveVenueId(venueId);

// scope mode (venue vs all); allow "all" only if user has 2+ venues
let scopeMode = (params.get("scope") || "venue").toLowerCase();
if (scopeMode !== "all") scopeMode = "venue";
if (!Array.isArray(__venues) || __venues.length < 2) scopeMode = "venue";

// Determine whether user has report access for this venue (affects navbar layout)
let __canReports = false;
try {
  if (venueId) {
    const pr = await api(`/me/venues/${encodeURIComponent(venueId)}/permissions`);
    const pset = permSetFromResponse(pr);
    const role = roleUpper(pr);
    __canReports = canViewReportsPerms(pset, role, "");
  }
} catch {}

await mountNav({ activeTab: (__canReports ? "finance" : "salary") });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  sumSalary: document.getElementById("sumSalary"),
  sumTips: document.getElementById("sumTips"),
  sumPenalties: document.getElementById("sumPenalties"),
  sumBonuses: document.getElementById("sumBonuses"),
  rowWriteoffs: document.getElementById("rowWriteoffs"),
  sumWriteoffs: document.getElementById("sumWriteoffs"),
  sumTotal: document.getElementById("sumTotal"),
  daysList: document.getElementById("daysList"),
  monthChart: document.getElementById("monthChart"),
  btnThisVenue: document.getElementById("btnThisVenue"),
  btnAllVenues: document.getElementById("btnAllVenues"),
};

const allEls = {
  card: document.getElementById("allVenuesCard"),
  count: document.getElementById("allVenuesCount"),
  hint: document.getElementById("allVenuesHint"),
  earned: document.getElementById("allEarned"),
  tips: document.getElementById("allTips"),
  bonuses: document.getElementById("allBonuses"),
  penalties: document.getElementById("allPenalties"),
  net: document.getElementById("allNet"),
  list: document.getElementById("allVenuesList"),
};

function setScopeMode(next) {
  scopeMode = (next === "all") ? "all" : "venue";

  if (el.btnThisVenue) el.btnThisVenue.disabled = (scopeMode === "venue");
  if (el.btnAllVenues) el.btnAllVenues.disabled = (scopeMode === "all");

  if (allEls.card) allEls.card.style.display = (scopeMode === "all") ? "" : "none";

  const vs = document.getElementById("venueScopeWrap");
  if (vs) vs.style.display = (scopeMode === "all") ? "none" : "";

  // keep URL in sync without reload
  try {
    const p = new URLSearchParams(location.search);
    if (scopeMode === "all") p.set("scope", "all"); else p.delete("scope");
    history.replaceState(null, "", `${location.pathname}?${p.toString()}`);
  } catch {}
}

// Hide "All venues" switch if user has only one venue
try {
  const scope = document.getElementById("salaryScope");
  if (scope && (!Array.isArray(__venues) || __venues.length < 2)) scope.style.display = "none";
} catch {}

setScopeMode(scopeMode);

el.btnThisVenue?.addEventListener("click", () => { setScopeMode("venue"); refresh(); });
el.btnAllVenues?.addEventListener("click", () => { setScopeMode("all"); refresh(); });

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitleEl = document.getElementById("modalSubtitle");
function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);
function openModal(title, subtitle, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "День";
  if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle || "";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
let curMonth = new Date(); curMonth.setDate(1);

// allow ?month=YYYY-MM
const qMonth = params.get("month");
if (qMonth && /^\d{4}-\d{2}$/.test(qMonth)) {
  const [yy, mm] = qMonth.split("-").map((x) => parseInt(x, 10));
  if (yy && mm) curMonth = new Date(yy, mm - 1, 1);
}

function syncUrl() {
  try {
    const p = new URLSearchParams(location.search);
    p.set("month", ym(curMonth));
    if (venueId) p.set("venue_id", String(venueId));
    history.replaceState(null, "", `${location.pathname}?${p.toString()}`);
  } catch {}
}

function monthTitle(d) {
  const m = d.toLocaleString("ru-RU", { month: "long" });
  return `${m[0].toUpperCase()}${m.slice(1)} ${d.getFullYear()}`;
}
function formatMoney(x) {
  const n = Number(x);
  if (!Number.isFinite(n)) return "0";
  return Math.round(n).toString();
}
function esc(s){
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

let shifts = [];
let days = []; // [{date, salary, hasReport, shifts:[] }]
let adjustments = []; // month items

async function loadMonth() {
  if (!venueId) {
    const m = ym(curMonth);
    if (el.monthLabel) el.monthLabel.textContent = monthTitle(curMonth);
    if (el.daysList) el.daysList.innerHTML = `<div class="muted">Нет активного заведения</div>`;
    if (el.monthChart) el.monthChart.innerHTML = `<div class="muted">Нет активного заведения</div>`;
    return;
  }

  const m = ym(curMonth);
  el.monthLabel.textContent = monthTitle(curMonth);
  el.daysList.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;

  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/shifts?month=${encodeURIComponent(m)}`);
    shifts = Array.isArray(out) ? out : (out?.items || []);
  } catch (e) {
    shifts = [];
    toast(e?.message || "Не удалось загрузить смены", "err");
  }

  try {
    const adj = await api(`/venues/${encodeURIComponent(venueId)}/adjustments?month=${encodeURIComponent(m)}&mine=1`);
    adjustments = Array.isArray(adj?.items) ? adj.items : [];
  } catch {
    adjustments = [];
  }

  // group by date
  const map = new Map(); // date -> {salary, hasReport, shifts:[]}
  for (const s of shifts) {
    const d = s.date;
    if (!d) continue;
    const row = map.get(d) || { date: d, salary: 0, hasReport: !!s.report_exists, shifts: [] };
    row.hasReport = row.hasReport || !!s.report_exists;
    row.shifts.push(s);

    const val = Number(s.my_salary);
    if (Number.isFinite(val)) row.salary += val;

    const tip = Number(s.my_tips_share);
    if (!Number.isFinite(row.tips)) row.tips = 0;
    if (Number.isFinite(tip)) row.tips += tip;

    map.set(d, row);
  }

  days = Array.from(map.values()).sort((a,b)=>a.date.localeCompare(b.date));

  renderSummary();
  renderMonthChart();
  renderDays();
}



async function loadMonthAll() {
  if (!allEls.list) return;

  const m = ym(curMonth);
  el.monthLabel.textContent = monthTitle(curMonth);

  allEls.list.innerHTML = `<div class="card"><div class="skeleton"></div></div><div class="card"><div class="skeleton"></div></div>`;

  try {
    const data = await api(`/me/salary-summary?month=${encodeURIComponent(m)}`);
    const totals = data?.totals || {};
    const items = Array.isArray(data?.venues) ? data.venues : [];

    const fmt = (n) => Math.round(Number(n || 0)).toLocaleString("ru-RU");

    if (allEls.earned) allEls.earned.textContent = fmt(totals.earned);
    if (allEls.tips) allEls.tips.textContent = fmt(totals.tips);
    if (allEls.bonuses) allEls.bonuses.textContent = fmt(totals.bonuses);
    if (allEls.penalties) allEls.penalties.textContent = fmt(totals.penalties);
    if (allEls.net) allEls.net.textContent = fmt(totals.net);

    if (allEls.count) allEls.count.textContent = items.length ? `${items.length} завед.` : "—";
    if (allEls.hint) allEls.hint.textContent = items.length ? "" : "Нет данных";

    allEls.list.innerHTML = items.length
      ? items.map((v) => {
          const vid = v?.venue_id ?? v?.id ?? v?.venueId ?? v?.venueID;
          const name = esc(v?.venue_name || v?.name || __venueNameOf(vid) || `#${vid || ""}`);
          const net = fmt(v?.net);
          const earned = fmt(v?.earned);
          const tips = fmt(v?.tips);
          const bonuses = fmt(v?.bonuses);
          const pen = fmt(v?.penalties);
          return `
            <div class="card">
              <b>${name}</b>
              <div class="muted small mt-6">Итого: <b>${net}</b></div>
              <div class="muted small mt-6">Начислено: ${earned} · Чаевые: ${tips}</div>
              <div class="muted small">Премии: ${bonuses} · Штрафы: ${pen}</div>
            </div>`;
        }).join("")
      : `<div class="muted">Нет данных за выбранный месяц</div>`;
  } catch (e) {
    allEls.list.innerHTML = `<div class="muted">Не удалось загрузить сводку</div>`;
    toast(e?.message || "Не удалось загрузить сводку", "err");
  }
}

async function refresh() {
  // Update scope UI + cards
  setScopeMode(scopeMode);

  if (scopeMode === "all") {
    if (el.daysList) el.daysList.innerHTML = "";
    await loadMonthAll();
    return;
  }
  await loadMonth();
}

function formatDateRuNoG(iso) {
  const dt = new Date(String(iso).length === 10 ? iso + "T00:00:00" : iso);
  const dd = String(dt.getDate()).padStart(2, "0");
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const yyyy = dt.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

function renderSummary() {
  const totalSalary = days.reduce((acc, d) => acc + (Number.isFinite(d.salary) ? d.salary : 0), 0);
  const totalTips = days.reduce((acc, d) => acc + (Number.isFinite(d.tips) ? d.tips : 0), 0);

  const totalPenalties = adjustments.filter(x => x.type === "penalty").reduce((a,x)=>a+Number(x.amount||0),0);
  const totalBonuses = adjustments.filter(x => x.type === "bonus").reduce((a,x)=>a+Number(x.amount||0),0);

  // Флаг удержания списаний (позже будет настройка заведения)
  const holdWriteoffs = false;
  const totalWriteoffs = adjustments.filter(x => x.type === "writeoff").reduce((a,x)=>a+Number(x.amount||0),0);

  el.sumSalary.textContent = formatMoney(totalSalary);
  el.sumTips.textContent = formatMoney(totalTips);
  el.sumPenalties.textContent = formatMoney(totalPenalties);
  el.sumBonuses.textContent = formatMoney(totalBonuses);

  if (holdWriteoffs) {
    el.rowWriteoffs.style.display = "flex";
    el.sumWriteoffs.textContent = formatMoney(totalWriteoffs);
  } else {
    el.rowWriteoffs.style.display = "none";
  }

  const total = totalSalary - totalPenalties + totalBonuses - (holdWriteoffs ? totalWriteoffs : 0);
  el.sumTotal.textContent = formatMoney(total);
}


function renderMonthChart() {
  if (!el.monthChart) return;
  if (!days.length) {
    el.monthChart.innerHTML = `<div class="muted">Нет данных за этот месяц</div>`;
    return;
  }

  const maxVal = Math.max(1, ...days.map(d => Math.max(0, Number(d.salary) || 0)));
  const bars = days.map((d) => {
    const dt = new Date(String(d.date).length === 10 ? d.date + "T00:00:00" : d.date);
    const label = String(dt.getDate());
    const val = Math.max(0, Number(d.salary) || 0);
    let h = Math.round((val / maxVal) * 100);
    if (!h && d.hasReport) h = 8; // show a small stub if report exists but salary is 0
    const barColor = d.hasReport ? "var(--accent)" : "var(--borderSoft)";
    return `
      <button class="bar" type="button" data-date="${esc(d.date)}" style="--h:${h}%;--barColor:${barColor}">
        <div class="bar__track"><div class="bar__fill"></div></div>
        <div class="bar__label">${esc(label)}</div>
      </button>
    `;
  }).join("");

  el.monthChart.innerHTML = `<div class="chart__bars">${bars}</div>`;
  el.monthChart.querySelectorAll(".bar").forEach((btn) => {
    const date = btn.getAttribute("data-date");
    const d = days.find(x => x.date === date);
    if (!d) return;
    btn.addEventListener("click", () => openDayModal(d));
  });
}


function renderDays() {
  el.daysList.innerHTML = "";
  if (!days.length) {
    el.daysList.innerHTML = `<div class="muted">Нет данных за этот месяц</div>`;
    return;
  }

  for (const d of days) {
    const card = document.createElement("div");
    const dd = formatDateRuNoG(d.date); // <-- "dd.mm.yyyy"
    card.className = "list__row";

    card.innerHTML = `
      <div class="row row--between">
        <div>
          <b>${esc(dd)}</b>
        </div>
        <div class="dayrow__right">
          <div class="day-salary ${d.salary>0 ? "" : "day-salary--muted"}">${d.salary>0 ? ("+"+formatMoney(d.salary)) : "Нет отчета"}</div>
          <button class="btn" data-open>Подробнее</button>
        </div>
      </div>
    `;
    card.querySelector("[data-open]").addEventListener("click", () => openDayModal(d));
    el.daysList.appendChild(card);
  }
}

function openDayModal(d) {
  const shiftsHtml = (d.shifts || []).map(s => {
    const interval = s.interval?.title || s.interval_title || s.interval?.id || "Смена";
    const sal = Number(s.my_salary);
    const salText = Number.isFinite(sal) ? ("+"+formatMoney(sal)) : "—";
    return `
      <div class="section">
        <div class="row row--between">
          <div>
            <b>${esc(interval)}</b>
            <div class="muted small">${s.report_exists ? "Отчёт есть" : "Нет отчёта"}</div>
          </div>
          <div class="day-salary" style="${Number.isFinite(sal) ? "" : "opacity:.45"}">${esc(salText)}</div>
        </div>
      </div>
    `;
  }).join("");

  openModal(
    `${formatDateRuNoG(d.date)}`,
    "",
    `<div class="itemcard" style="margin-top:12px">
        <div class="row" style="justify-content:space-between;align-items:center">
          <div class="muted">Итого за день</div>
          <div class="day-salary ${d.salary>0 ? "" : "day-salary--muted"}">${d.salary>0 ? ("+"+formatMoney(d.salary)) : "—"}</div>
        </div>
        <div class="row" style="justify-content:space-between;align-items:center; margin-top:6px">
          <div class="muted">Чаевые</div>
          <div class="day-salary">${formatMoney(d.tips || 0)}</div>
        </div>
        <div style="margin-top:10px">${shiftsHtml || `<div class="muted">Смен нет</div>`}</div>
      </div>`
  );
}

el.prev.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  syncUrl();
  await refresh();
});
el.next.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  syncUrl();
  await refresh();
});

syncUrl();
refresh();
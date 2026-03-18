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

let __venues = [];
try { __venues = await getMyVenues().catch(() => []); } catch { __venues = []; }
const __venueIdOf = (v) => v?.venue?.id ?? v?.id ?? v?.venue_id ?? v?.venueId ?? v?.venueID ?? v?.venue?.venue_id ?? null;
const __venueNameOf = (id) => {
  if (id == null) return "";
  const sid = String(id);
  const v = (__venues || []).find((x) => String(__venueIdOf(x)) === sid || String(__venueIdOf(x?.venue)) === sid);
  const nested = v?.venue || null;
  return v?.name ?? v?.venue_name ?? v?.title ?? nested?.name ?? nested?.venue_name ?? nested?.title ?? "";
};

async function ensureVenuesLoaded() {
  if (Array.isArray(__venues) && __venues.length) return __venues;
  try { __venues = await getMyVenues().catch(() => []); } catch { __venues = []; }
  return __venues;
}

let venueId = params.get("venue_id") || getActiveVenueId();
if (!venueId && Array.isArray(__venues) && __venues.length) {
  const id0 = __venueIdOf(__venues[0]);
  if (id0 != null) venueId = String(id0);
}
if (venueId) setActiveVenueId(venueId);

let scopeMode = (params.get("scope") || "venue").toLowerCase();
if (scopeMode !== "all") scopeMode = "venue";
if (!Array.isArray(__venues) || __venues.length < 2) scopeMode = "venue";

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
  sourceHint: document.getElementById("salarySourceHint"),
  payrollBreakdownRow: document.getElementById("payrollBreakdownRow"),
  openPayrollBreakdownBtn: document.getElementById("openPayrollBreakdownBtn"),
  daysChartTitle: document.getElementById("daysChartTitle"),
  daysChartHint: document.getElementById("daysChartHint"),
  daysListTitle: document.getElementById("daysListTitle"),
  daysListHint: document.getElementById("daysListHint"),
};

const allEls = {
  card: document.getElementById("allVenuesCard"),
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
  try {
    const p = new URLSearchParams(location.search);
    if (scopeMode === "all") p.set("scope", "all"); else p.delete("scope");
    history.replaceState(null, "", `${location.pathname}?${p.toString()}`);
  } catch {}
}

try {
  const scope = document.getElementById("salaryScope");
  if (scope && (!Array.isArray(__venues) || __venues.length < 2)) scope.style.display = "none";
} catch {}

setScopeMode(scopeMode);
el.btnThisVenue?.addEventListener("click", () => { setScopeMode("venue"); refresh(); });
el.btnAllVenues?.addEventListener("click", () => { setScopeMode("all"); refresh(); });

function ensureModal() {
  let m = document.getElementById("modal");
  if (!m) {
    m = document.createElement("div");
    m.id = "modal";
    m.className = "modal";
    m.innerHTML = `
      <div class="modal__backdrop" data-close></div>
      <div class="modal__panel">
        <div class="modal__head row row--between ai-center">
          <div>
            <div class="modal__title">Детали</div>
            <div class="muted small" id="modalSubtitle"></div>
          </div>
          <button class="btn sm" data-close aria-label="Закрыть">✕</button>
        </div>
        <div class="modal__body"></div>
      </div>
    `;
    document.body.appendChild(m);
  }
  if (!m.__bound) {
    const close = () => m.classList.remove("open");
    m.querySelectorAll("[data-close]").forEach((x) => x.addEventListener("click", close));
    m.__bound = true;
  }
  return m;
}

const modal = ensureModal();
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitleEl = document.getElementById("modalSubtitle");
function openModal(title, subtitle, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Детали";
  if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle || "";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
let curMonth = new Date(); curMonth.setDate(1);
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
  return Math.round(n).toLocaleString("ru-RU");
}
function formatMoneyMinor(x) {
  const n = Number(x || 0) / 100;
  if (!Number.isFinite(n)) return "0,00";
  return n.toLocaleString("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function esc(s){
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
function formatDateRu(iso) {
  const dt = new Date(String(iso).length === 10 ? iso + "T00:00:00" : iso);
  const dd = String(dt.getDate()).padStart(2, "0");
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const yyyy = dt.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

let shifts = [];
let days = [];
let adjustments = [];
let monthSummaryItem = null;
let payrollLine = null;
let payrollWorkedDates = new Set();

function buildDaysFromShifts() {
  const map = new Map();
  for (const s of shifts) {
    const d = String(s?.date || "").slice(0, 10);
    if (!d) continue;
    const row = map.get(d) || { date: d, salary: 0, hasReport: !!s.report_exists, shifts: [], tips: 0, includedInPayroll: false };
    row.hasReport = row.hasReport || !!s.report_exists;
    row.shifts.push(s);
    const val = Number(s.my_salary);
    if (Number.isFinite(val)) row.salary += val;
    const tip = Number(s.my_tips_share);
    if (Number.isFinite(tip)) row.tips += tip;
    map.set(d, row);
  }
  for (const d of payrollWorkedDates) {
    if (!map.has(d)) map.set(d, { date: d, salary: 0, hasReport: true, shifts: [], tips: 0, includedInPayroll: true });
  }
  days = Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date));
  for (const row of days) row.includedInPayroll = payrollWorkedDates.has(row.date);
}

async function loadMonth() {
  if (!venueId) {
    if (el.monthLabel) el.monthLabel.textContent = monthTitle(curMonth);
    if (el.daysList) el.daysList.innerHTML = `<div class="muted">Нет активного заведения</div>`;
    if (el.monthChart) el.monthChart.innerHTML = `<div class="muted">Нет активного заведения</div>`;
    return;
  }

  const m = ym(curMonth);
  el.monthLabel.textContent = monthTitle(curMonth);
  if (el.daysList) el.daysList.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;

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

  monthSummaryItem = null;
  payrollLine = null;
  payrollWorkedDates = new Set();
  try {
    const summary = await api(`/me/salary-summary?month=${encodeURIComponent(m)}`);
    const items = Array.isArray(summary?.items) ? summary.items : [];
    monthSummaryItem = items.find((item) => String(item?.venue?.id ?? item?.venue_id ?? item?.venueId ?? "") === String(venueId)) || null;
    if (monthSummaryItem?.source === "payroll") {
      payrollLine = await api(`/me/payroll-line?month=${encodeURIComponent(m)}&venue_id=${encodeURIComponent(venueId)}`).catch(() => null);
      const worked = Array.isArray(payrollLine?.breakdown?.metrics?.worked_dates) ? payrollLine.breakdown.metrics.worked_dates : [];
      payrollWorkedDates = new Set(worked.map((x) => String(x || "").slice(0, 10)).filter(Boolean));
    }
  } catch {
    monthSummaryItem = null;
    payrollLine = null;
  }

  buildDaysFromShifts();
  renderSummary();
  renderMonthChart();
  renderDays();
}

async function loadMonthAll() {
  await ensureVenuesLoaded();
  if (!allEls.list) return;

  const m = ym(curMonth);
  el.monthLabel.textContent = monthTitle(curMonth);
  allEls.list.innerHTML = `<div class="card"><div class="skeleton"></div></div><div class="card"><div class="skeleton"></div></div>`;

  let totals = null;
  let items = null;
  try {
    const data = await api(`/me/salary-summary?month=${encodeURIComponent(m)}`);
    totals = (data && typeof data === "object" && (data.totals || data.total || data.summary)) || null;
    items = Array.isArray(data?.items) ? data.items : null;
  } catch {
    totals = null;
    items = null;
  }

  if ((!items || !items.length) && Array.isArray(__venues) && __venues.length) {
    items = [];
    const agg = { earned: 0, tips: 0, bonuses: 0, penalties: 0, net: 0 };
    for (const v of __venues) {
      const vid = __venueIdOf(v);
      if (vid == null) continue;
      const name = __venueNameOf(vid) || `#${vid}`;
      let venueShifts = [];
      let adjs = [];
      try {
        const out = await api(`/venues/${encodeURIComponent(String(vid))}/shifts?month=${encodeURIComponent(m)}`);
        venueShifts = Array.isArray(out) ? out : (out?.items || []);
      } catch {}
      try {
        const adj = await api(`/venues/${encodeURIComponent(String(vid))}/adjustments?month=${encodeURIComponent(m)}&mine=1`);
        adjs = Array.isArray(adj?.items) ? adj.items : [];
      } catch {}
      const earned = venueShifts.reduce((a, s) => a + (Number(s?.my_salary) || 0), 0);
      const tips = venueShifts.reduce((a, s) => a + (Number(s?.my_tips_share) || 0), 0);
      const bonuses = adjs.filter(x => x?.type === "bonus").reduce((a, x) => a + (Number(x?.amount) || 0), 0);
      const penalties = adjs.filter(x => x?.type === "penalty" || x?.type === "writeoff").reduce((a, x) => a + (Number(x?.amount) || 0), 0);
      const net = earned + tips + bonuses - penalties;
      items.push({ venue: { id: vid, name }, earned, tips, bonuses, penalties, net, source: "legacy" });
      agg.earned += earned; agg.tips += tips; agg.bonuses += bonuses; agg.penalties += penalties; agg.net += net;
    }
    totals = agg;
  }

  const t = totals || {};
  if (allEls.earned) allEls.earned.textContent = formatMoney(t.earned ?? t.salary ?? t.total_salary);
  if (allEls.tips) allEls.tips.textContent = formatMoney(t.tips ?? t.total_tips);
  if (allEls.bonuses) allEls.bonuses.textContent = formatMoney(t.bonuses ?? t.total_bonuses);
  if (allEls.penalties) allEls.penalties.textContent = formatMoney(t.penalties ?? t.total_penalties ?? t.penalties_total);
  if (allEls.net) allEls.net.textContent = formatMoney(t.net ?? t.total ?? t.total_net);

  const safeItems = Array.isArray(items) ? items : [];
  if (allEls.hint) allEls.hint.textContent = safeItems.length ? "" : "Нет данных";
  if (!safeItems.length) {
    allEls.list.innerHTML = `<div class="muted">Нет данных за выбранный месяц</div>`;
    return;
  }

  safeItems.sort((a, b) => (Number(b?.net) || 0) - (Number(a?.net) || 0));
  allEls.list.innerHTML = safeItems.map((v) => {
    const vid = v?.venue?.id ?? v?.venue_id ?? v?.venueId ?? v?.id ?? null;
    const name = esc(v?.venue?.name ?? v?.venue_name ?? v?.venueName ?? v?.name ?? __venueNameOf(vid) ?? `#${vid ?? ""}`);
    const earned = Number(v?.earned ?? 0);
    const tips = Number(v?.tips ?? 0);
    const bonuses = Number(v?.bonuses ?? 0);
    const penalties = Number(v?.penalties ?? 0);
    const net = Number(v?.net ?? (earned + tips + bonuses - penalties) ?? 0);
    const badge = v?.source === "payroll" ? `<span class="badge">payroll</span>` : `<span class="badge">legacy</span>`;
    return `
      <div class="card">
        <div class="row row--between ai-center" style="gap:8px; flex-wrap:wrap;">
          <b>${name}</b>
          ${badge}
        </div>
        <div class="grid mt-10 salary-all-kpis">
          <div class="mini-kpi"><div class="muted small">Начислено</div><b>${formatMoney(earned)}</b></div>
          <div class="mini-kpi"><div class="muted small">Чаевые</div><b>${formatMoney(tips)}</b></div>
          <div class="mini-kpi"><div class="muted small">Премии</div><b>${formatMoney(bonuses)}</b></div>
          <div class="mini-kpi"><div class="muted small">Штрафы/Списания</div><b>${formatMoney(penalties)}</b></div>
          <div class="mini-kpi total"><div class="muted small">Итого</div><b>${formatMoney(net)}</b></div>
        </div>
      </div>`;
  }).join("");
}

async function refresh() {
  setScopeMode(scopeMode);
  if (scopeMode === "all") {
    if (el.daysList) el.daysList.innerHTML = "";
    await loadMonthAll();
    return;
  }
  await loadMonth();
}

function renderSummary() {
  const legacySalary = days.reduce((acc, d) => acc + (Number.isFinite(d.salary) ? d.salary : 0), 0);
  const legacyTips = days.reduce((acc, d) => acc + (Number.isFinite(d.tips) ? d.tips : 0), 0);
  const totalPenalties = adjustments.filter(x => x.type === "penalty").reduce((a,x)=>a+Number(x.amount||0),0);
  const totalBonuses = adjustments.filter(x => x.type === "bonus").reduce((a,x)=>a+Number(x.amount||0),0);
  const totalWriteoffs = adjustments.filter(x => x.type === "writeoff").reduce((a,x)=>a+Number(x.amount||0),0);
  const holdWriteoffs = false;

  const earned = Number(monthSummaryItem?.earned ?? legacySalary ?? 0);
  const tips = Number(monthSummaryItem?.tips ?? legacyTips ?? 0);
  const bonuses = Number(monthSummaryItem?.bonuses ?? totalBonuses ?? 0);
  const penalties = Number(monthSummaryItem?.penalties ?? totalPenalties ?? 0);
  const total = Number(monthSummaryItem?.net ?? (earned + tips + bonuses - penalties - (holdWriteoffs ? totalWriteoffs : 0)) ?? 0);

  el.sumSalary.textContent = formatMoney(earned);
  el.sumTips.textContent = formatMoney(tips);
  el.sumPenalties.textContent = formatMoney(penalties);
  el.sumBonuses.textContent = formatMoney(bonuses);
  if (holdWriteoffs) {
    el.rowWriteoffs.style.display = "flex";
    el.sumWriteoffs.textContent = formatMoney(totalWriteoffs);
  } else {
    el.rowWriteoffs.style.display = "none";
  }
  el.sumTotal.textContent = formatMoney(total);

  const isPayroll = monthSummaryItem?.source === "payroll";
  if (el.sourceHint) {
    if (isPayroll) {
      el.sourceHint.textContent = "Основной источник — новый payroll. Месячная сумма и итог берутся из payroll-начисления; блоки ниже показывают справочную детализацию по дням и сменам.";
    } else if (monthSummaryItem?.source === "legacy") {
      el.sourceHint.textContent = "Для этого заведения payroll за месяц ещё не рассчитан, поэтому сумма временно взята из старой shift-логики.";
    } else {
      el.sourceHint.textContent = "";
    }
  }
  if (el.payrollBreakdownRow) el.payrollBreakdownRow.style.display = (isPayroll && payrollLine?.breakdown) ? "flex" : "none";
  if (el.daysChartTitle) el.daysChartTitle.textContent = isPayroll ? "Дни, вошедшие в расчёт" : "График по дням";
  if (el.daysChartHint) el.daysChartHint.textContent = isPayroll ? "Подсвечены даты, которые реально попали в payroll" : "Выбери день для подробностей";
  if (el.daysListTitle) el.daysListTitle.textContent = isPayroll ? "Смены по дням" : "По дням";
  if (el.daysListHint) el.daysListHint.textContent = isPayroll ? "Это справочная детализация, а не источник месячной суммы" : "";
}

function renderMonthChart() {
  if (!el.monthChart) return;
  if (!days.length) {
    el.monthChart.innerHTML = `<div class="muted">Нет данных за этот месяц</div>`;
    return;
  }

  const isPayroll = monthSummaryItem?.source === "payroll";
  let bars = "";
  if (isPayroll) {
    bars = days.map((d) => {
      const dt = new Date(String(d.date).length === 10 ? d.date + "T00:00:00" : d.date);
      const label = String(dt.getDate());
      const h = d.includedInPayroll ? 100 : (d.shifts?.length ? 35 : 12);
      const barColor = d.includedInPayroll ? "var(--accent)" : "var(--borderSoft)";
      return `
        <button class="bar" type="button" data-date="${esc(d.date)}" style="--h:${h}%;--barColor:${barColor}">
          <div class="bar__track"><div class="bar__fill"></div></div>
          <div class="bar__label">${esc(label)}</div>
        </button>`;
    }).join("");
  } else {
    const maxVal = Math.max(1, ...days.map(d => Math.max(0, Number(d.salary) || 0)));
    bars = days.map((d) => {
      const dt = new Date(String(d.date).length === 10 ? d.date + "T00:00:00" : d.date);
      const label = String(dt.getDate());
      const val = Math.max(0, Number(d.salary) || 0);
      let h = Math.round((val / maxVal) * 100);
      if (!h && d.hasReport) h = 8;
      const barColor = d.hasReport ? "var(--accent)" : "var(--borderSoft)";
      return `
        <button class="bar" type="button" data-date="${esc(d.date)}" style="--h:${h}%;--barColor:${barColor}">
          <div class="bar__track"><div class="bar__fill"></div></div>
          <div class="bar__label">${esc(label)}</div>
        </button>`;
    }).join("");
  }

  el.monthChart.innerHTML = `<div class="chart__bars">${bars}</div>`;
  el.monthChart.querySelectorAll(".bar").forEach((btn) => {
    const date = btn.getAttribute("data-date");
    const d = days.find(x => x.date === date);
    if (!d) return;
    btn.addEventListener("click", () => openDayModal(d));
  });
}

function renderDays() {
  if (!el.daysList) return;
  el.daysList.innerHTML = "";
  if (!days.length) {
    el.daysList.innerHTML = `<div class="muted">Нет данных за этот месяц</div>`;
    return;
  }

  const isPayroll = monthSummaryItem?.source === "payroll";
  for (const d of days) {
    const card = document.createElement("div");
    card.className = "list__row";
    const dd = formatDateRu(d.date);
    const rightText = isPayroll
      ? (d.includedInPayroll ? "Вошло в расчёт" : (d.shifts?.length ? "Не вошло" : "—"))
      : (d.salary > 0 ? `+${formatMoney(d.salary)}` : "Нет отчета");
    const rightClass = isPayroll
      ? (d.includedInPayroll ? "day-salary" : "day-salary day-salary--muted")
      : (d.salary > 0 ? "day-salary" : "day-salary day-salary--muted");
    card.innerHTML = `
      <div class="row row--between" style="gap:10px; align-items:center;">
        <div>
          <b>${esc(dd)}</b>
          <div class="muted small mt-4">${isPayroll ? `${Math.max(0, d.shifts?.length || 0)} смен(ы)` : (d.hasReport ? "Есть отчёт" : "Нет закрытого отчёта")}</div>
        </div>
        <div class="dayrow__right">
          <div class="${rightClass}">${esc(rightText)}</div>
          <button class="btn" data-open>Подробнее</button>
        </div>
      </div>`;
    card.querySelector("[data-open]")?.addEventListener("click", () => openDayModal(d));
    el.daysList.appendChild(card);
  }
}

function breakdownMetaHtml(c) {
  const type = String(c?.component_type || "").toUpperCase();
  if (type === "PERCENT_TOTAL_REVENUE") {
    return `<div class="muted small mt-4">${esc(((Number(c.percent_bps || 0) / 100).toFixed(2)))}% от базы ${esc(formatMoneyMinor(c.base_amount_minor || 0))}</div>`;
  }
  if (type === "PERCENT_DEPARTMENT_REVENUE") {
    const dep = c?.department_title ? ` · ${esc(c.department_title)}` : "";
    return `<div class="muted small mt-4">${esc(((Number(c.percent_bps || 0) / 100).toFixed(2)))}% от базы ${esc(formatMoneyMinor(c.base_amount_minor || 0))}${dep}</div>`;
  }
  if (type === "KPI_BONUS") {
    const threshold = c?.threshold_value ?? "—";
    return `<div class="muted small mt-4">KPI: ${esc(c.kpi_metric_title || c.kpi_metric_id || "—")} · факт: ${esc(c.metric_value ?? 0)} · порог: ${esc(threshold)}</div>`;
  }
  if (type === "SALARY_HOURLY") {
    return `<div class="muted small mt-4">Часы: ${esc(c.hours_total ?? 0)}</div>`;
  }
  if (type === "SALARY_PER_SHIFT") {
    return `<div class="muted small mt-4">Смен: ${esc(c.shifts_count ?? 0)}</div>`;
  }
  return `<div class="muted small mt-4">Компонент профиля</div>`;
}

function openPayrollBreakdown() {
  if (!payrollLine?.breakdown) return;
  const breakdown = payrollLine.breakdown || {};
  const metrics = breakdown.metrics || {};
  const components = Array.isArray(breakdown.components) ? breakdown.components : [];
  const dates = Array.isArray(metrics.worked_dates) ? metrics.worked_dates : [];
  const componentsHtml = components.length ? components.map((c) => `
    <div class="payroll-breakdown__row">
      <div>
        <b>${esc(c.title || c.component_type || "Компонент")}</b>
        <div class="muted small mt-4">${esc(String(c.component_type || ""))}</div>
        ${breakdownMetaHtml(c)}
      </div>
      <div><b>${esc(formatMoneyMinor(c.amount_minor || 0))}</b></div>
    </div>`).join("") : `<div class="muted">Нет breakdown</div>`;

  openModal(
    `Начисление за ${ym(curMonth)}`,
    breakdown.pay_profile_title ? `Профиль: ${breakdown.pay_profile_title}` : "",
    `<div class="itemcard" style="margin-top:12px">
      <div class="row" style="justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;">
        <div class="muted">Итого начислено</div>
        <div class="day-salary">${esc(formatMoneyMinor(payrollLine.amount_minor || 0))}</div>
      </div>
      <div class="muted small mt-8">Часы: ${esc(metrics.hours_total ?? 0)} · Смены: ${esc(metrics.shifts_count ?? 0)} · Дней: ${esc(metrics.worked_dates_count ?? 0)}</div>
      ${dates.length ? `<div class="muted small mt-6">Даты в расчёте: ${dates.map((d) => esc(formatDateRu(d))).join(", ")}</div>` : ""}
      <div class="payroll-breakdown mt-12">
        <div class="payroll-breakdown__body mt-8">${componentsHtml}</div>
      </div>
    </div>`
  );
}

function openDayModal(d) {
  const isPayroll = monthSummaryItem?.source === "payroll";
  const shiftsHtml = (d.shifts || []).map((s) => {
    const interval = s.interval?.title || s.interval_title || s.interval?.id || "Смена";
    const status = d.includedInPayroll ? "Вошло в payroll" : (s.report_exists ? "Есть отчёт, но не вошло" : "Нет закрытого отчёта");
    const legacySalary = Number(s.my_salary);
    const trailing = isPayroll
      ? `<div class="muted small">${esc(status)}</div>`
      : `<div class="day-salary" style="${Number.isFinite(legacySalary) ? "" : "opacity:.45"}">${esc(Number.isFinite(legacySalary) ? ("+" + formatMoney(legacySalary)) : "—")}</div>`;
    return `
      <div class="section">
        <div class="row row--between" style="gap:12px; align-items:flex-start;">
          <div>
            <b>${esc(interval)}</b>
            <div class="muted small">${s.report_exists ? "Отчёт есть" : "Нет отчёта"}</div>
          </div>
          <div>${trailing}</div>
        </div>
      </div>`;
  }).join("");

  if (isPayroll) {
    openModal(
      `${formatDateRu(d.date)}`,
      d.includedInPayroll ? "Этот день попал в payroll-расчёт" : "Этот день не участвует в payroll-итоге",
      `<div class="itemcard" style="margin-top:12px">
        <div class="row" style="justify-content:space-between;align-items:center; gap:12px;">
          <div class="muted">Статус дня</div>
          <div class="day-salary ${d.includedInPayroll ? "" : "day-salary--muted"}">${d.includedInPayroll ? "Вошло в расчёт" : "Не вошло"}</div>
        </div>
        <div class="row" style="justify-content:space-between;align-items:center; margin-top:6px">
          <div class="muted">Чаевые за день</div>
          <div class="day-salary">${formatMoney(d.tips || 0)}</div>
        </div>
        <div class="muted small mt-8">Месячная сумма берётся из payroll, поэтому здесь показана только справочная детализация по сменам.</div>
        <div style="margin-top:10px">${shiftsHtml || `<div class="muted">Смен нет</div>`}</div>
      </div>`
    );
    return;
  }

  openModal(
    `${formatDateRu(d.date)}`,
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

el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  syncUrl();
  await refresh();
});
el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  syncUrl();
  await refresh();
});
el.openPayrollBreakdownBtn?.addEventListener("click", openPayrollBreakdown);

syncUrl();
refresh();

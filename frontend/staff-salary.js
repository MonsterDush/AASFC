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
    } else {
      monthSummaryItem = {
        venue: { id: venueId, name: __venueNameOf(venueId) || "" },
        source: "not_calculated",
        calculated: false,
      };
    }
  } catch {
    monthSummaryItem = {
      venue: { id: venueId, name: __venueNameOf(venueId) || "" },
      source: "not_calculated",
      calculated: false,
    };
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

  const t = totals || {};
  if (allEls.earned) allEls.earned.textContent = formatMoney(t.earned ?? t.salary ?? t.total_salary);
  if (allEls.tips) allEls.tips.textContent = formatMoney(t.tips ?? t.total_tips);
  if (allEls.bonuses) allEls.bonuses.textContent = formatMoney(t.bonuses ?? t.total_bonuses);
  if (allEls.penalties) allEls.penalties.textContent = formatMoney(t.penalties ?? t.total_penalties ?? t.penalties_total);
  if (allEls.net) allEls.net.textContent = formatMoney(t.net ?? t.total ?? t.total_net);

  const summaryItems = Array.isArray(items) ? items : [];
  const summaryByVenue = new Map(summaryItems.map((item) => [String(item?.venue?.id ?? item?.venue_id ?? item?.venueId ?? ""), item]));
  const safeItems = [];
  for (const v of (__venues || [])) {
    const vid = __venueIdOf(v);
    if (vid == null) continue;
    const found = summaryByVenue.get(String(vid));
    if (found) {
      safeItems.push(found);
    } else {
      safeItems.push({
        venue: { id: vid, name: __venueNameOf(vid) || `#${vid}` },
        source: "not_calculated",
        calculated: false,
      });
    }
  }
  if (!safeItems.length) {
    for (const item of summaryItems) safeItems.push(item);
  }

  const missingCount = safeItems.filter((item) => item?.source !== "payroll").length;
  if (allEls.hint) {
    allEls.hint.textContent = missingCount
      ? `Не рассчитано по ${missingCount} ${missingCount === 1 ? "заведению" : "заведениям"}`
      : "Все начисления рассчитаны";
  }
  if (!safeItems.length) {
    allEls.list.innerHTML = `<div class="muted">Нет заведений для отображения</div>`;
    return;
  }

  safeItems.sort((a, b) => {
    const ap = a?.source === "payroll" ? 1 : 0;
    const bp = b?.source === "payroll" ? 1 : 0;
    if (bp !== ap) return bp - ap;
    return (Number(b?.net) || 0) - (Number(a?.net) || 0);
  });
  allEls.list.innerHTML = safeItems.map((v) => {
    const vid = v?.venue?.id ?? v?.venue_id ?? v?.venueId ?? v?.id ?? null;
    const name = esc(v?.venue?.name ?? v?.venue_name ?? v?.venueName ?? v?.name ?? __venueNameOf(vid) ?? `#${vid ?? ""}`);
    const earned = Number(v?.earned ?? 0);
    const tips = Number(v?.tips ?? 0);
    const bonuses = Number(v?.bonuses ?? 0);
    const penalties = Number(v?.penalties ?? 0);
    const net = Number(v?.net ?? (earned + tips + bonuses - penalties) ?? 0);
    if (v?.source !== "payroll") {
      return `
        <div class="card">
          <div class="row row--between ai-center" style="gap:8px; flex-wrap:wrap;">
            <b>${name}</b>
            <span class="badge">не рассчитано</span>
          </div>
          <div class="muted mt-10">Начисление за этот месяц ещё не рассчитано. Сумма появится после payroll-расчёта.</div>
        </div>`;
    }
    return `
      <div class="card">
        <div class="row row--between ai-center" style="gap:8px; flex-wrap:wrap;">
          <b>${name}</b>
          <span class="badge">payroll</span>
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
  const totalWriteoffs = adjustments.filter(x => x.type === "writeoff").reduce((a,x)=>a+Number(x.amount||0),0);
  const isPayroll = monthSummaryItem?.source === "payroll";
  const isCalculated = isPayroll && !!monthSummaryItem?.calculated;

  if (isCalculated) {
    const earned = Number(monthSummaryItem?.earned ?? 0);
    const tips = Number(monthSummaryItem?.tips ?? 0);
    const bonuses = Number(monthSummaryItem?.bonuses ?? 0);
    const penalties = Number(monthSummaryItem?.penalties ?? 0);
    const total = Number(monthSummaryItem?.net ?? (earned + tips + bonuses - penalties) ?? 0);
    el.sumSalary.textContent = formatMoney(earned);
    el.sumTips.textContent = formatMoney(tips);
    el.sumPenalties.textContent = formatMoney(penalties);
    el.sumBonuses.textContent = formatMoney(bonuses);
    el.sumTotal.textContent = formatMoney(total);
    if (el.sourceHint) {
      el.sourceHint.textContent = "Экран сотрудника теперь работает только от payroll. Месячная сумма и итог берутся из рассчитанного payroll-начисления; блоки ниже показывают справочную детализацию по дням и сменам.";
    }
  } else {
    el.sumSalary.textContent = "—";
    el.sumTips.textContent = "—";
    el.sumPenalties.textContent = "—";
    el.sumBonuses.textContent = "—";
    el.sumTotal.textContent = "—";
    if (el.sourceHint) {
      el.sourceHint.textContent = "Начисление за этот месяц ещё не рассчитано. Старый shift-расчёт больше не используется; сумма появится после payroll-расчёта.";
    }
  }
  if (el.rowWriteoffs) el.rowWriteoffs.style.display = "none";
  if (el.sumWriteoffs) el.sumWriteoffs.textContent = formatMoney(totalWriteoffs);
  if (el.payrollBreakdownRow) el.payrollBreakdownRow.style.display = (isCalculated && payrollLine?.breakdown) ? "flex" : "none";
  if (el.daysChartTitle) el.daysChartTitle.textContent = isCalculated ? "Дни, вошедшие в расчёт" : "Календарь смен";
  if (el.daysChartHint) el.daysChartHint.textContent = isCalculated ? "Подсвечены даты, которые реально попали в payroll" : "Здесь показаны смены и закрытые дни, но итоговая сумма появится только после payroll-расчёта";
  if (el.daysListTitle) el.daysListTitle.textContent = isCalculated ? "Смены по дням" : "Смены за месяц";
  if (el.daysListHint) el.daysListHint.textContent = isCalculated ? "Это справочная детализация, а не источник месячной суммы" : "Справочная детализация без расчёта зарплаты";
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
    bars = days.map((d) => {
      const dt = new Date(String(d.date).length === 10 ? d.date + "T00:00:00" : d.date);
      const label = String(dt.getDate());
      const shiftsCount = Math.max(0, d.shifts?.length || 0);
      const h = d.hasReport ? 100 : (shiftsCount ? 45 : 12);
      const barColor = d.hasReport ? "var(--accent)" : (shiftsCount ? "var(--borderSoft)" : "var(--borderSoft)");
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
      : (d.hasReport ? "Есть закрытый отчёт" : (d.shifts?.length ? "Смена без закрытия" : "—"));
    const rightClass = isPayroll
      ? (d.includedInPayroll ? "day-salary" : "day-salary day-salary--muted")
      : (d.hasReport ? "day-salary" : "day-salary day-salary--muted");
    card.innerHTML = `
      <div class="row row--between" style="gap:10px; align-items:center;">
        <div>
          <b>${esc(dd)}</b>
          <div class="muted small mt-4">${Math.max(0, d.shifts?.length || 0)} смен(ы)</div>
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
    const status = isPayroll
      ? (d.includedInPayroll ? "Вошло в payroll" : (s.report_exists ? "Есть отчёт, но не вошло" : "Нет закрытого отчёта"))
      : (s.report_exists ? "Есть закрытый отчёт" : "Нет закрытого отчёта");
    return `
      <div class="section">
        <div class="row row--between" style="gap:12px; align-items:flex-start;">
          <div>
            <b>${esc(interval)}</b>
            <div class="muted small">${s.report_exists ? "Отчёт есть" : "Нет отчёта"}</div>
          </div>
          <div class="muted small">${esc(status)}</div>
        </div>
      </div>`;
  }).join("");

  openModal(
    `${formatDateRu(d.date)}`,
    isPayroll
      ? (d.includedInPayroll ? "Этот день попал в payroll-расчёт" : "Этот день не участвует в payroll-итоге")
      : "Начисление за месяц ещё не рассчитано",
    `<div class="itemcard" style="margin-top:12px">
      <div class="row" style="justify-content:space-between;align-items:center; gap:12px;">
        <div class="muted">Статус дня</div>
        <div class="day-salary ${isPayroll ? (d.includedInPayroll ? "" : "day-salary--muted") : (d.hasReport ? "" : "day-salary--muted")}">${isPayroll ? (d.includedInPayroll ? "Вошло в расчёт" : "Не вошло") : (d.hasReport ? "Закрытый день" : "Без закрытия")}</div>
      </div>
      <div class="muted small mt-8">${isPayroll
        ? "Месячная сумма берётся из payroll, поэтому здесь показана только справочная детализация по сменам."
        : "Payroll за этот месяц ещё не рассчитан, поэтому суммы по дням скрыты и ниже показана только справочная детализация по сменам."}</div>
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

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
  coerceDemoMonth,
  isDemoUiMode,
  getStoredDemoUiState,
  getDemoMonthLabel,
  mountDemoPageTour,
  trackDemoEvent,
} from "/app.js";

import { hasReportAccess, permSetFromResponse, roleUpper, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js";

let financialValuesHidden = false;

const COMPONENT_LABELS = {
  SALARY_FIXED_MONTH: "Оклад за месяц",
  SALARY_HOURLY: "Почасовая ставка",
  SALARY_PER_SHIFT: "Фикс за смену",
  PERCENT_TOTAL_REVENUE: "% от общей выручки",
  PERCENT_DEPARTMENT_REVENUE: "% от выручки департамента",
  KPI_BONUS: "KPI-бонус",
  MINIMUM_PAYOUT: "Минимальная сумма к выплате",
  TIP: "Чаевые",
  BONUS: "Премия",
  PENALTY: "Штраф",
  WRITEOFF: "Списание",
};


const DEMO_STAFF_SALARY_INTRO_DISMISSED_KEY = "axelio.demo_intro.staff_salary.dismissed";

function renderDemoStaffSalaryIntro() {
  const intro = document.getElementById("demoStaffSalaryIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) { intro.classList.add("hidden"); return; }
  try { if (sessionStorage.getItem(DEMO_STAFF_SALARY_INTRO_DISMISSED_KEY) === "1") { intro.classList.add("hidden"); return; } } catch {}
  const introText = document.getElementById("demoStaffSalaryIntroText");
  if (introText) introText.textContent = `Подготовленные начисления за ${getDemoMonthLabel(demoState) || 'DEMO-месяц'}. Посмотри итог, разрез по дням и потом вернись к графику.`;
  document.getElementById("demoStaffSalaryGoShifts")?.addEventListener("click", () => { const v = venueId || getActiveVenueId(); if (v) location.href = `/staff-shifts.html?venue_id=${encodeURIComponent(String(v))}`; });
  document.getElementById("demoStaffSalaryIntroClose")?.addEventListener("click", () => { intro.classList.add("hidden"); try { sessionStorage.setItem(DEMO_STAFF_SALARY_INTRO_DISMISSED_KEY, "1"); } catch {} });
  intro.classList.remove("hidden");
}

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
    financialValuesHidden = isFinancialValuesHidden(pr);
    const pset = permSetFromResponse(pr);
    const role = roleUpper(pr);
    __canReports = hasReportAccess(pset, role, "");
  }
} catch {}

await mountNav({ activeTab: (__canReports ? "finance" : "salary") });
renderDemoStaffSalaryIntro();

const el = {
  monthLabel: document.getElementById("monthLabel"),
  periodMonthBtn: document.getElementById("periodMonthBtn"),
  periodRangeBtn: document.getElementById("periodRangeBtn"),
  monthControls: document.getElementById("monthControls"),
  rangeControls: document.getElementById("rangeControls"),
  rangeFrom: document.getElementById("rangeFrom"),
  rangeTo: document.getElementById("rangeTo"),
  rangeApply: document.getElementById("rangeApply"),
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
  addManualTipBtn: document.getElementById("addManualTipBtn"),
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
  if (el.addManualTipBtn) el.addManualTipBtn.style.display = (scopeMode === "all") ? "none" : "";
  syncUrl();
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
          <button class="btn sm subtle" data-close>Закрыть</button>
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


function isoToday() {
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function monthStartIso(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-01`;
}

function monthEndIso(d) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate())}`;
}

let periodMode = (params.get("period_mode") || ((params.get("date_from") && params.get("date_to")) ? "range" : "month")).toLowerCase();
if (periodMode !== "range") periodMode = "month";
if (isDemoUiMode()) periodMode = "month";

function defaultTipDate() {
  const today = isoToday();
  if (periodMode === "range") {
    const from = String(rangeFrom || "");
    const to = String(rangeTo || "");
    if (from && to && today >= from && today <= to) return today;
    return from || today;
  }
  const currentMonth = ym(curMonth);
  return today.startsWith(`${currentMonth}-`) ? today : `${currentMonth}-01`;
}

function closeModal() {
  modal?.classList.remove("open");
}

function openManualTipModal() {
  const venueOptions = (__venues || []).map((v) => {
    const id = __venueIdOf(v);
    const name = __venueNameOf(id) || `#${id}`;
    return `<option value="${esc(id)}">${esc(name)}</option>`;
  }).join("");
  const defaultVenueId = String(venueId || __venueIdOf(__venues?.[0]) || "");
  openModal(
    "Добавить чаевые",
    "Сумма попадёт в зарплатную сводку сотрудника",
    `<div class="itemcard" style="margin-top:12px">
      <div class="grid" style="gap:10px">
        <label>
          <div class="muted small" style="margin-bottom:6px">Заведение</div>
          <select id="manualTipVenue">${venueOptions}</select>
        </label>
        <label>
          <div class="muted small" style="margin-bottom:6px">Дата начисления</div>
          <input id="manualTipDate" type="date" value="${esc(defaultTipDate())}" />
        </label>
        <label>
          <div class="muted small" style="margin-bottom:6px">Сумма</div>
          <input id="manualTipAmount" type="number" min="1" inputmode="numeric" placeholder="0" />
        </label>
        <label>
          <div class="muted small" style="margin-bottom:6px">Комментарий</div>
          <input id="manualTipNote" type="text" maxlength="500" placeholder="Необязательно" />
        </label>
      </div>
      <div class="row" style="justify-content:flex-end; gap:8px; margin-top:12px; flex-wrap:wrap;">
        <button class="btn sm" type="button" id="manualTipCancel">Отмена</button>
        <button class="btn sm" type="button" id="manualTipSave">Сохранить</button>
      </div>
    </div>`
  );

  const venueSelect = modalBody?.querySelector("#manualTipVenue");
  const dateInput = modalBody?.querySelector("#manualTipDate");
  const amountInput = modalBody?.querySelector("#manualTipAmount");
  const noteInput = modalBody?.querySelector("#manualTipNote");
  if (venueSelect) venueSelect.value = defaultVenueId;
  modalBody?.querySelector("#manualTipCancel")?.addEventListener("click", closeModal);
  modalBody?.querySelector("#manualTipSave")?.addEventListener("click", async () => {
    const payload = {
      venue_id: Number(venueSelect?.value || 0),
      date: String(dateInput?.value || "").trim(),
      amount: Math.round(Number(amountInput?.value || 0)),
      note: String(noteInput?.value || "").trim() || null,
    };
    if (!payload.venue_id) { toast("Выбери заведение", "err"); return; }
    if (!/^\d{4}-\d{2}-\d{2}$/.test(payload.date)) { toast("Укажи дату", "err"); return; }
    if (!Number.isFinite(payload.amount) || payload.amount <= 0) { toast("Укажи сумму больше нуля", "err"); return; }
    try {
      await api(`/me/manual-tips`, { method: "POST", body: payload });
      if (String(payload.venue_id) !== String(venueId)) {
        venueId = String(payload.venue_id);
        setActiveVenueId(venueId);
      }
      closeModal();
      toast("Чаевые добавлены", "ok");
      await refresh();
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось добавить чаевые", "err");
    }
  });
}

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
function normalizeSalaryShiftSlot(value) {
  const raw = String(value || "TOTAL").trim().toUpperCase();
  return ["TOTAL", "DAY", "NIGHT"].includes(raw) ? raw : "TOTAL";
}
function salaryShiftSlotLabel(value) {
  const slot = normalizeSalaryShiftSlot(value);
  if (slot === "DAY") return "День";
  if (slot === "NIGHT") return "Ночь";
  return "Итого";
}
const deepLinkDate = /^\d{4}-\d{2}-\d{2}$/.test(String(params.get("date") || "")) ? String(params.get("date")) : "";
const selectedSalaryShiftSlot = normalizeSalaryShiftSlot(params.get("shift_slot") || "TOTAL");
const shouldAutoOpenDay = String(params.get("open_day") || "") === "1" && !!deepLinkDate;
let deepLinkAutoOpened = false;
let curMonth = new Date(`${coerceDemoMonth(`${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, "0")}`, { notify: false, context: "staff-salary" })}-01T00:00:00`); curMonth.setDate(1);
const qMonth = params.get("month");
if (qMonth && /^\d{4}-\d{2}$/.test(qMonth)) {
  const [yy, mm] = qMonth.split("-").map((x) => parseInt(x, 10));
  if (yy && mm) curMonth = new Date(`${coerceDemoMonth(`${yy}-${String(mm).padStart(2, "0")}`, { notify: false, context: "staff-salary" })}-01T00:00:00`);
} else if (deepLinkDate) {
  const [yy, mm] = deepLinkDate.slice(0, 7).split("-").map((x) => parseInt(x, 10));
  if (yy && mm) curMonth = new Date(`${coerceDemoMonth(`${yy}-${String(mm).padStart(2, "0")}`, { notify: false, context: "staff-salary" })}-01T00:00:00`);
}
let rangeFrom = /^\d{4}-\d{2}-\d{2}$/.test(String(params.get("date_from") || "")) ? String(params.get("date_from")) : monthStartIso(curMonth);
let rangeTo = /^\d{4}-\d{2}-\d{2}$/.test(String(params.get("date_to") || "")) ? String(params.get("date_to")) : (deepLinkDate || isoToday());
if (rangeTo < rangeFrom) rangeTo = rangeFrom;

function getPeriodQuery() {
  const q = new URLSearchParams();
  if (periodMode === "range") {
    q.set("period_mode", "range");
    q.set("date_from", String(rangeFrom || ""));
    q.set("date_to", String(rangeTo || ""));
  } else {
    q.set("month", ym(curMonth));
  }
  return q;
}

function syncPeriodUi() {
  const isRangeMode = periodMode === "range" && !isDemoUiMode();

  if (el.monthControls) {
    el.monthControls.classList.toggle("hidden", isRangeMode);
    el.monthControls.style.display = isRangeMode ? "none" : "flex";
  }

  if (el.rangeControls) {
    el.rangeControls.classList.toggle("hidden", !isRangeMode);
    el.rangeControls.style.display = isRangeMode ? "flex" : "none";
  }

  if (el.periodMonthBtn) el.periodMonthBtn.disabled = periodMode === "month";
  if (el.periodRangeBtn) {
    el.periodRangeBtn.disabled = isDemoUiMode() || periodMode === "range";
    el.periodRangeBtn.style.display = isDemoUiMode() ? "none" : "";
  }
  if (el.rangeFrom) el.rangeFrom.value = rangeFrom || "";
  if (el.rangeTo) el.rangeTo.value = rangeTo || "";
  if (el.monthLabel) el.monthLabel.textContent = periodMode === "month" ? monthTitle(curMonth) : `${formatDateRu(rangeFrom)} — ${formatDateRu(rangeTo)}`;
  if (el.daysChartTitle) el.daysChartTitle.textContent = periodMode === "month" ? "График по дням" : "Период по дням";
  if (el.daysListTitle) el.daysListTitle.textContent = periodMode === "month" ? "По дням" : "Дни в диапазоне";
  if (el.daysListHint) el.daysListHint.textContent = periodMode === "month" ? "" : `${formatDateRu(rangeFrom)} — ${formatDateRu(rangeTo)}`;
}

function syncUrl() {
  try {
    const p = getPeriodQuery();
    if (scopeMode === "all") p.set("scope", "all");
    if (venueId) p.set("venue_id", String(venueId));
    history.replaceState(null, "", `${location.pathname}?${p.toString()}`);
  } catch {}
}

function monthTitle(d) {
  const m = d.toLocaleString("ru-RU", { month: "long" });
  return `${m[0].toUpperCase()}${m.slice(1)} ${d.getFullYear()}`;
}
function formatMoney(x) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  const n = Number(x);
  if (!Number.isFinite(n)) return "0";
  return Math.round(n).toLocaleString("ru-RU");
}
function formatMoneyMinor(x) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
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

function recalcReasonLabel(reason) {
  const map = {
    manual_calculation: "Ручной расчёт",
    report_closed: "Автоперерасчёт после закрытия отчёта",
    report_reopened: "Автоперерасчёт после переоткрытия отчёта",
    closed_report_updated: "Автоперерасчёт после изменения закрытого отчёта",
    shift_assignment_added: "Автоперерасчёт после назначения сотрудника",
    shift_assignment_removed: "Автоперерасчёт после снятия сотрудника",
    shift_updated: "Автоперерасчёт после изменения смены",
    shift_deleted: "Автоперерасчёт после удаления смены",
    member_removed_from_venue: "Автоперерасчёт после удаления из заведения",
    member_left_venue: "Автоперерасчёт после выхода из заведения",
  };
  return map[String(reason || "")] || "Автоперерасчёт начисления";
}

function periodQueryString() {
  return getPeriodQuery().toString();
}

let shifts = [];
let days = [];
let adjustments = [];
let monthSummaryItem = null;
let payrollLine = null;
let payrollWorkedDates = new Set();
const dayBreakdownCache = new Map();

function buildDaysFromShifts() {
  const map = new Map();
  for (const s of shifts) {
    const d = String(s?.date || "").slice(0, 10);
    if (!d) continue;
    const row = map.get(d) || {
      date: d,
      salary: 0,
      hasReport: !!s.report_exists,
      shifts: [],
      tips: 0,
      bonuses: 0,
      penalties: 0,
      writeoffs: 0,
      includedInPayroll: false,
      adjustmentCount: 0,
    };
    row.hasReport = row.hasReport || !!s.report_exists;
    row.shifts.push(s);
    const val = Number(s.my_salary);
    if (Number.isFinite(val)) row.salary += val;
    const tip = Number(s.my_tips_share);
    if (Number.isFinite(tip)) row.tips += tip;
    map.set(d, row);
  }
  for (const adj of adjustments || []) {
    const d = String(adj?.date || "").slice(0, 10);
    if (!d) continue;
    const row = map.get(d) || {
      date: d,
      salary: 0,
      hasReport: false,
      shifts: [],
      tips: 0,
      bonuses: 0,
      penalties: 0,
      writeoffs: 0,
      includedInPayroll: false,
      adjustmentCount: 0,
    };
    row.adjustmentCount += 1;
    const amount = Number(adj?.amount || 0);
    if (String(adj?.type || "").toLowerCase() === "bonus") row.bonuses += amount;
    else if (String(adj?.type || "").toLowerCase() === "tip") row.tips += amount;
    else if (String(adj?.type || "").toLowerCase() === "writeoff") row.writeoffs += amount;
    else row.penalties += amount;
    map.set(d, row);
  }
  for (const d of payrollWorkedDates) {
    if (!map.has(d)) map.set(d, { date: d, salary: 0, hasReport: true, shifts: [], tips: 0, bonuses: 0, penalties: 0, writeoffs: 0, includedInPayroll: true, adjustmentCount: 0 });
  }
  days = Array.from(map.values()).sort((a, b) => a.date.localeCompare(b.date));
  for (const row of days) row.includedInPayroll = payrollWorkedDates.has(row.date);
}


async function loadMonth() {
  syncPeriodUi();
  if (!venueId) {
    if (el.daysList) el.daysList.innerHTML = `<div class="muted">Нет активного заведения</div>`;
    if (el.monthChart) el.monthChart.innerHTML = `<div class="muted">Нет активного заведения</div>`;
    return;
  }

  const q = periodQueryString();
  if (el.daysList) el.daysList.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;

  try {
    const out = await api(`/me/shifts?venue_id=${encodeURIComponent(venueId)}&${q}`);
    shifts = Array.isArray(out) ? out : (out?.items || []);
  } catch (e) {
    shifts = [];
    toast(e?.message || "Не удалось загрузить смены", "err");
  }

  try {
    const adj = await api(`/venues/${encodeURIComponent(venueId)}/adjustments?${q}&mine=1`);
    adjustments = Array.isArray(adj?.items) ? adj.items : [];
  } catch {
    adjustments = [];
  }

  monthSummaryItem = null;
  payrollLine = null;
  payrollWorkedDates = new Set();
  try {
    const summary = await api(`/me/salary-summary?${q}`);
    const items = Array.isArray(summary?.items) ? summary.items : [];
    monthSummaryItem = items.find((item) => String(item?.venue?.id ?? item?.venue_id ?? item?.venueId ?? "") === String(venueId)) || null;
    if (periodMode === "month" && monthSummaryItem?.source === "payroll") {
      payrollLine = await api(`/me/payroll-line?month=${encodeURIComponent(ym(curMonth))}&venue_id=${encodeURIComponent(venueId)}`).catch(() => null);
      const worked = Array.isArray(payrollLine?.breakdown?.metrics?.worked_dates) ? payrollLine.breakdown.metrics.worked_dates : [];
      payrollWorkedDates = new Set(worked.map((x) => String(x || "").slice(0, 10)).filter(Boolean));
    } else {
      monthSummaryItem = monthSummaryItem || {
        venue: { id: venueId, name: __venueNameOf(venueId) || "" },
        source: "not_calculated",
        calculated: false,
        period_state: "empty",
      };
    }
  } catch {
    monthSummaryItem = {
      venue: { id: venueId, name: __venueNameOf(venueId) || "" },
      source: "not_calculated",
      calculated: false,
      period_state: "empty",
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

  const q = periodQueryString();
  syncPeriodUi();
  allEls.list.innerHTML = `<div class="card"><div class="skeleton"></div></div><div class="card"><div class="skeleton"></div></div>`;

  let totals = null;
  let items = null;
  try {
    const data = await api(`/me/salary-summary?${q}`);
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
        period_state: "empty",
      });
    }
  }
  if (!safeItems.length) {
    for (const item of summaryItems) safeItems.push(item);
  }

  const missingCount = safeItems.filter((item) => item?.period_state === "empty").length;
  if (allEls.hint) {
    allEls.hint.textContent = missingCount
      ? `Нет начислений по ${missingCount} ${missingCount === 1 ? "заведению" : "заведениям"}`
      : "Данные собраны по выбранному периоду";
  }
  if (!safeItems.length) {
    allEls.list.innerHTML = `<div class="muted">Нет заведений для отображения</div>`;
    return;
  }

  safeItems.sort((a, b) => {
    const ap = a?.calculated ? 1 : 0;
    const bp = b?.calculated ? 1 : 0;
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
    const net = Number(v?.net ?? (earned + bonuses - penalties) ?? 0);
    const state = String(v?.period_state || "empty");
    const latest = v?.latest_recalculation?.trigger_reason ? `<div class="muted small mt-8">${esc(recalcReasonLabel(v.latest_recalculation.trigger_reason))}</div>` : "";
    if (state === "empty") {
      return `
        <div class="card">
          <div class="row row--between ai-center" style="gap:8px; flex-wrap:wrap;">
            <b>${name}</b>
            <span class="badge">нет данных</span>
          </div>
          <div class="muted mt-10">За выбранный период начислений нет.</div>
        </div>`;
    }
    return `
      <div class="card">
        <div class="row row--between ai-center" style="gap:8px; flex-wrap:wrap;">
          <b>${name}</b>
          <span class="badge">${state === "partial" ? "частично" : "готово"}</span>
        </div>
        <div class="grid mt-10 salary-all-kpis">
          <div class="mini-kpi"><div class="muted small">Начислено</div><b>${formatMoney(earned)}</b></div>
          <div class="mini-kpi"><div class="muted small">Чаевые</div><b>${formatMoney(tips)}</b></div>
          <div class="mini-kpi"><div class="muted small">Премии</div><b>${formatMoney(bonuses)}</b></div>
          <div class="mini-kpi"><div class="muted small">Штрафы/Списания</div><b>${formatMoney(penalties)}</b></div>
          <div class="mini-kpi total"><div class="muted small">Итого начисление</div><b>${formatMoney(net)}</b></div>
        </div>
        ${latest}
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
  await maybeAutoOpenDay();
}

function renderSummary() {
  const totalWriteoffs = adjustments.filter(x => x.type === "writeoff").reduce((a, x) => a + Number(x.amount || 0), 0);
  const state = String(monthSummaryItem?.period_state || (monthSummaryItem?.source === "payroll" ? "ready" : "empty"));
  const earned = Number(monthSummaryItem?.earned ?? 0);
  const tips = Number(monthSummaryItem?.tips ?? 0);
  const bonuses = Number(monthSummaryItem?.bonuses ?? 0);
  const penalties = Number(monthSummaryItem?.penalties ?? 0);
  const total = Number(monthSummaryItem?.net ?? (earned + bonuses - penalties) ?? 0);
  const latest = monthSummaryItem?.latest_recalculation || null;
  const hasAny = state !== "empty" || earned !== 0 || tips !== 0 || bonuses !== 0 || penalties !== 0 || total !== 0;

  if (hasAny) {
    el.sumSalary.textContent = formatMoney(earned);
    el.sumTips.textContent = formatMoney(tips);
    el.sumPenalties.textContent = formatMoney(penalties);
    el.sumBonuses.textContent = formatMoney(bonuses);
    el.sumTotal.textContent = formatMoney(total);
  } else {
    el.sumSalary.textContent = "—";
    el.sumTips.textContent = "—";
    el.sumPenalties.textContent = "—";
    el.sumBonuses.textContent = "—";
    el.sumTotal.textContent = "—";
  }

  let hint = "";
  if (!hasAny) {
    hint = periodMode === "month"
      ? "За этот месяц начислений пока нет. Суммы появятся после расчёта начислений; чаевые и корректировки показываются отдельно."
      : "За выбранный диапазон начислений пока нет.";
  } else if (state === "partial") {
    hint = "Часть дней уже пересчитана автоматически, но часть данных ещё может быть в процессе обновления.";
  } else if (periodMode === "month" && payrollLine?.breakdown) {
    hint = "Месячная сумма взята из итогового расчёта, а детализация по дням собрана из тех же данных.";
  } else {
    hint = "Сводка собрана за выбранный период по дневной детализации начислений.";
  }
  if (latest?.trigger_reason) {
    const suffix = latest?.created_at ? ` · ${new Date(latest.created_at).toLocaleString("ru-RU")}` : "";
    hint = `${hint} ${recalcReasonLabel(latest.trigger_reason)}${suffix}.`;
  }
  if (el.sourceHint) el.sourceHint.textContent = hint;

  if (el.rowWriteoffs) el.rowWriteoffs.style.display = "none";
  if (el.sumWriteoffs) el.sumWriteoffs.textContent = formatMoney(totalWriteoffs);
  if (el.payrollBreakdownRow) el.payrollBreakdownRow.style.display = (periodMode === "month" && payrollLine?.breakdown) ? "flex" : "none";
  if (el.daysChartHint) {
    el.daysChartHint.textContent = periodMode === "month"
      ? ((monthSummaryItem?.source === "payroll") ? "Подсвечены даты, которые вошли в итоговый расчёт" : "Выбери день для подробностей")
      : "Выбери день, чтобы увидеть детализацию начисления и перерасчёта";
  }
}


function renderMonthChart() {
  if (!el.monthChart) return;
  if (!days.length) {
    el.monthChart.innerHTML = `<div class="muted">${periodMode === "month" ? "Нет данных за этот месяц" : "Нет данных за этот диапазон"}</div>`;
    return;
  }

  const isPayroll = monthSummaryItem?.source === "payroll";
  const bars = days.map((d) => {
    const dt = new Date(String(d.date).length === 10 ? d.date + "T00:00:00" : d.date);
    const label = periodMode === "month" ? String(dt.getDate()) : `${pad2(dt.getDate())}.${pad2(dt.getMonth() + 1)}`;
    const shiftsCount = Math.max(0, d.shifts?.length || 0);
    const hasAdjustments = (Number(d.adjustmentCount || 0) > 0);
    const h = isPayroll
      ? (d.includedInPayroll ? 100 : (hasAdjustments ? 55 : (shiftsCount ? 35 : 12)))
      : (d.hasReport ? 100 : (hasAdjustments ? 55 : (shiftsCount ? 45 : 12)));
    const barColor = isPayroll
      ? (d.includedInPayroll ? "var(--accent)" : "var(--borderSoft)")
      : (d.hasReport ? "var(--accent)" : "var(--borderSoft)");
    return `
      <button class="bar" type="button" data-date="${esc(d.date)}" style="--h:${h}%;--barColor:${barColor}">
        <div class="bar__track"><div class="bar__fill"></div></div>
        <div class="bar__label">${esc(label)}</div>
      </button>`;
  }).join("");

  el.monthChart.innerHTML = `<div class="chart__bars">${bars}</div>`;
  el.monthChart.querySelectorAll(".bar").forEach((btn) => {
    const date = btn.getAttribute("data-date");
    const d = days.find(x => x.date === date);
    if (!d) return;
    btn.addEventListener("click", () => { void openDayModal(d); });
  });
}


function renderDays() {
  if (!el.daysList) return;
  el.daysList.innerHTML = "";
  if (!days.length) {
    el.daysList.innerHTML = `<div class="muted">${periodMode === "month" ? "Нет данных за этот месяц" : "Нет данных за этот диапазон"}</div>`;
    return;
  }

  const isPayroll = monthSummaryItem?.source === "payroll";
  for (const d of days) {
    const card = document.createElement("div");
    card.className = "list__row";
    const dd = formatDateRu(d.date);
    let rightText = "—";
    if (isPayroll) {
      rightText = d.includedInPayroll ? "Вошло в расчёт" : ((d.shifts?.length || d.adjustmentCount) ? "Есть изменения вне итогового расчёта" : "—");
    } else if (d.hasReport) {
      rightText = "Есть закрытый отчёт";
    } else if (d.adjustmentCount) {
      rightText = "Есть корректировки";
    } else if (d.shifts?.length) {
      rightText = "Смена без закрытия";
    }
    const rightClass = (isPayroll && d.includedInPayroll) || d.hasReport || d.adjustmentCount
      ? "day-salary"
      : "day-salary day-salary--muted";
    const details = [];
    details.push(`${Math.max(0, d.shifts?.length || 0)} смен(ы)`);
    if (d.adjustmentCount) details.push(`${d.adjustmentCount} коррект.`);
    card.innerHTML = `
      <div class="row row--between" style="gap:10px; align-items:center;">
        <div>
          <b>${esc(dd)}</b>
          <div class="muted small mt-4">${esc(details.join(" · "))}</div>
        </div>
        <div class="dayrow__right">
          <div class="${rightClass}">${esc(rightText)}</div>
          <button class="btn" data-open>Подробнее</button>
        </div>
      </div>`;
    card.querySelector("[data-open]")?.addEventListener("click", () => { void openDayModal(d); });
    el.daysList.appendChild(card);
  }
}


async function loadDayBreakdown(dateIso) {
  const day = String(dateIso || "").slice(0, 10);
  const slot = selectedSalaryShiftSlot;
  const key = `${venueId}:${day}:${slot}`;
  if (dayBreakdownCache.has(key)) return dayBreakdownCache.get(key);
  const req = api(`/me/salary-day-breakdown?venue_id=${encodeURIComponent(venueId)}&date=${encodeURIComponent(day)}&shift_slot=${encodeURIComponent(slot)}`);
  dayBreakdownCache.set(key, req);
  try {
    const data = await req;
    dayBreakdownCache.set(key, data);
    return data;
  } catch (e) {
    dayBreakdownCache.delete(key);
    throw e;
  }
}

function renderDayBreakdownItems(items, detailed = false) {
  if (!Array.isArray(items) || !items.length) return `<div class="muted">Нет деталей начисления за этот день</div>`;
  return items.map((item) => {
    const amountMinor = Number(item?.amount_minor || 0);
    const amountClass = amountMinor < 0 ? "day-salary day-salary--muted" : "day-salary";
    const baseText = String(item?.base_text || "").trim();
    const formulaText = String(item?.formula_text || "").trim();
        return `
      <div class="payroll-breakdown__row">
        <div>
          <b>${esc(item?.title || "Компонент")}</b>
          ${baseText ? `<div class="muted small mt-4">База: ${esc(baseText)}</div>` : ""}
          ${formulaText ? `<div class="muted small mt-4">Формула: ${esc(formulaText)}</div>` : ""}
        </div>
        <div><b class="${amountClass}">${esc(formatMoneyMinor(amountMinor))}</b></div>
      </div>`;
  }).join("");
}

function fallbackDayModalHtml(d) {
  const isPayroll = monthSummaryItem?.source === "payroll";
  const shiftsHtml = (d.shifts || []).map((s) => {
    const interval = s.interval?.title || s.interval_title || s.interval?.id || "Смена";
    const status = isPayroll
      ? (d.includedInPayroll ? "Вошло в расчёт" : (s.report_exists ? "Есть отчёт, но не вошло" : "Нет закрытого отчёта"))
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

  return `<div class="itemcard" style="margin-top:12px">
    <div class="row" style="justify-content:space-between;align-items:center; gap:12px;">
      <div class="muted">Статус дня</div>
      <div class="day-salary ${isPayroll ? (d.includedInPayroll ? "" : "day-salary--muted") : (d.hasReport ? "" : "day-salary--muted")}">${isPayroll ? (d.includedInPayroll ? "Вошло в расчёт" : "Не вошло") : (d.hasReport ? "Закрытый день" : "Без закрытия")}</div>
    </div>
    <div class="muted small mt-8">${isPayroll
      ? "Месячная сумма берётся из итогового расчёта, поэтому здесь показана только справочная детализация по сменам."
      : "Итоговый расчёт за этот месяц ещё не готов, поэтому суммы по дням скрыты и ниже показана только справочная детализация по сменам."}</div>
    <div style="margin-top:10px">${shiftsHtml || `<div class="muted">Смен нет</div>`}</div>
  </div>`;
}

function renderDayBreakdownModal(d, breakdown) {
  const state = String(breakdown?.state || "ready");
  const summary = breakdown?.summary || {};
  const context = breakdown?.context || {};
  const itemsHtml = renderDayBreakdownItems(breakdown?.items || [], false);
  const stateText = state === "ready"
    ? "Начисление рассчитано"
    : (state === "partial"
      ? "Данные частичные"
      : (state === "no_payroll"
        ? "Начисление ещё не рассчитано"
        : (state === "slot_limited"
          ? `Детализация по слоту: ${salaryShiftSlotLabel(breakdown?.shift_slot)}`
          : (state === "slot_empty" ? `Нет данных по слоту: ${salaryShiftSlotLabel(breakdown?.shift_slot)}` : "Начислений не найдено"))));
  const shiftsCount = Number(context?.shifts_count || d?.shifts?.length || 0);
  const hoursTotal = Number(context?.hours_total || 0);
  const hoursText = Number.isFinite(hoursTotal) ? hoursTotal.toLocaleString("ru-RU", { minimumFractionDigits: 0, maximumFractionDigits: 2 }) : "0";
  const fallbackShifts = (d?.shifts || []).length ? `<div class="muted small mt-10">Смен за день: ${esc((d.shifts || []).map((s) => s.interval?.title || s.interval_title || "Смена").join(", "))}</div>` : "";
  const latest = context?.latest_recalculation || null;
  const recalcHtml = latest?.trigger_reason
    ? `<div class="muted small mt-10">${esc(recalcReasonLabel(latest.trigger_reason))}${latest?.created_at ? ` · ${esc(new Date(latest.created_at).toLocaleString("ru-RU"))}` : ""}</div>`
    : "";
  const slotNote = String(context?.slot_note || "").trim();
  const slotNoteHtml = slotNote ? `<div class="muted small mt-10">${esc(slotNote)}</div>` : "";

  return `<div class="itemcard" style="margin-top:12px">
    <div class="row" style="justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap;">
      <div>
        <div class="muted small">Статус</div>
        <b>${esc(stateText)}</b>
      </div>
      <div class="day-salary">${esc(formatMoneyMinor(summary?.total_minor || 0))}</div>
    </div>

    <div class="grid mt-12" style="gap:8px">
      <div class="row row--between"><div class="muted">Основное начисление</div><b>${esc(formatMoneyMinor(summary?.earnings_minor || 0))}</b></div>
      <div class="row row--between"><div class="muted">Чаевые (отдельно)</div><b>${esc(formatMoneyMinor(summary?.tips_minor || 0))}</b></div>
      <div class="row row--between"><div class="muted">Премии</div><b>${esc(formatMoneyMinor(summary?.bonuses_minor || 0))}</b></div>
      <div class="row row--between"><div class="muted">Штрафы/списания</div><b>${esc(formatMoneyMinor(-(Number(summary?.penalties_minor || 0))))}</b></div>
      <div class="row row--between"><div class="muted">Смен / часов</div><b>${esc(String(shiftsCount))} / ${esc(hoursText)}</b></div>
    </div>

    <div class="payroll-breakdown mt-12">
      <div class="muted small">Компонент · База расчёта · Формула · Итог</div>
      <div class="payroll-breakdown__body mt-8">${itemsHtml}</div>
    </div>

    ${recalcHtml}
    ${slotNoteHtml}
    ${state === "partial" ? `<div class="muted small mt-10">Часть начислений ещё в пересчёте или появится после payroll.</div>` : ""}
    ${state === "no_payroll" ? `<div class="muted small mt-10">За этот день уже могут быть чаевые или корректировки, но payroll-начисление ещё не собрано.</div>` : ""}
    ${state === "empty" ? `<div class="muted small mt-10">Нет начисления за этот день. Проверь, была ли смена, закрыт ли отчёт и назначен ли профиль оплаты.</div>` : ""}
    ${fallbackShifts}
  </div>`;
}


async function maybeAutoOpenDay() {
  if (!shouldAutoOpenDay || deepLinkAutoOpened || scopeMode === "all" || !deepLinkDate) return;
  if (periodMode === "month" && ym(curMonth) !== deepLinkDate.slice(0, 7)) return;
  if (periodMode === "range" && (deepLinkDate < rangeFrom || deepLinkDate > rangeTo)) return;
  const target = days.find((x) => String(x?.date || "").slice(0, 10) === deepLinkDate)
    || { date: deepLinkDate, shifts: [], hasReport: false, includedInPayroll: payrollWorkedDates.has(deepLinkDate), adjustmentCount: 0 };
  deepLinkAutoOpened = true;
  await openDayModal(target);
}

function componentSnapshot(c) {
  return c && typeof c.calculation_snapshot === 'object' && c.calculation_snapshot ? c.calculation_snapshot : (c || {});
}

function listTitles(value) {
  return Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
}

function componentDepartmentLabel(component, prefix = 'department') {
  const titles = listTitles(component?.[`${prefix}_titles`]);
  if (titles.length) return titles.join(' + ');
  const title = component?.[`${prefix}_title`];
  if (title) return String(title);
  const ids = Array.isArray(component?.[`${prefix}_ids`]) ? component[`${prefix}_ids`].filter(Boolean) : [];
  return ids.length ? ids.map((id) => `#${id}`).join(' + ') : '';
}

function minimumScopeLabel(snap) {
  return String(snap?.minimum_guarantee_scope_title || (String(snap?.minimum_guarantee_scope || '').toUpperCase() === 'DAY' ? 'за день' : 'за месяц'));
}

function breakdownMetaHtml(c) {
  const type = String(c?.component_type || "").toUpperCase();
  if (type === "PERCENT_TOTAL_REVENUE" || type === "PERCENT_DEPARTMENT_REVENUE") {
    const depLabel = componentDepartmentLabel(c, 'department');
    const dep = depLabel ? ` · ${esc(depLabel)}` : "";
    const scope = c?.base_scope_title ? ` · ${esc(c.base_scope_title)}` : "";
    const boost = c?.boost_enabled && c?.boost_percent_bps != null ? ` · boost ${esc(((Number(c.boost_percent_bps || 0) / 100).toFixed(2)))}%${c?.boost_applied ? ' ✓' : ''}` : '';
    const minMax = `${c?.minimum_applied ? ' · мин. гарантия' : ''}${c?.maximum_applied ? ' · потолок' : ''}`;
    return `<div class="muted small mt-4">${esc(((Number(c.percent_bps || 0) / 100).toFixed(2)))}% от базы ${esc(formatMoneyMinor(c.base_amount_minor || 0))}${dep}${scope}${boost}${minMax}</div>`;
  }
  if (type === "KPI_BONUS") {
    const threshold = c?.threshold_value ?? "—";
    return `<div class="muted small mt-4">KPI: ${esc(c.kpi_metric_title || "показатель")} · факт: ${esc(c.metric_value ?? 0)} · порог: ${esc(threshold)}</div>`;
  }
  if (type === "MINIMUM_PAYOUT") {
    return `<div class="muted small mt-4">Доплата до минимума: ${esc(formatMoneyMinor(c.minimum_target_minor ?? c.source_amount_minor ?? 0))}</div>`;
  }
  if (type === "SALARY_HOURLY") {
    return `<div class="muted small mt-4">Часы: ${esc(c.hours_total ?? 0)}</div>`;
  }
  if (type === "SALARY_PER_SHIFT") {
    return `<div class="muted small mt-4">Смен: ${esc(c.shifts_count ?? 0)}</div>`;
  }
  return `<div class="muted small mt-4">Компонент профиля</div>`;
}

function breakdownBadgesHtml(c) {
  const snap = componentSnapshot(c);
  const badges = [];
  if (snap?.boost_enabled && snap?.boost_percent_bps != null) badges.push(`<span class="payroll-chip ${snap?.boost_applied ? 'payroll-chip--ok' : 'payroll-chip--muted'}">boost ${esc(((Number(snap.boost_percent_bps || 0) / 100).toFixed(2)) + '%' )}</span>`);
  if (snap?.boost_source_title) badges.push(`<span class="payroll-chip payroll-chip--muted">${esc(snap.boost_source_title)}</span>`);
  if (snap?.minimum_applied) badges.push(`<span class="payroll-chip payroll-chip--warn">мин. гарантия</span>`);
  if (snap?.maximum_applied) badges.push(`<span class="payroll-chip payroll-chip--warn">потолок</span>`);
  if (Array.isArray(snap?.day_rows) && snap.day_rows.length) badges.push(`<span class="payroll-chip payroll-chip--muted">по дням</span>`);
  return badges.length ? `<div class="payroll-breakdown__badges">${badges.join('')}</div>` : '';
}

function breakdownKvHtml(c) {
  const snap = componentSnapshot(c);
  const rows = [];
  const push = (label, value) => {
    if (value == null || value === '') return;
    rows.push(`<div class="payroll-breakdown__kv-item"><span class="payroll-breakdown__kv-label">${esc(label)}</span><span class="payroll-breakdown__kv-value">${esc(value)}</span></div>`);
  };
  const type = String(c?.component_type || '').toUpperCase();
  if (type === 'MINIMUM_PAYOUT') {
    if (snap.minimum_target_minor != null || c.minimum_target_minor != null || c.source_amount_minor != null) push('Минимум', formatMoneyMinor(snap.minimum_target_minor ?? c.minimum_target_minor ?? c.source_amount_minor));
    if (snap.amount_before_minimum_minor != null || c.amount_before_minimum_minor != null) push('Было начислено', formatMoneyMinor(snap.amount_before_minimum_minor ?? c.amount_before_minimum_minor));
  }
  if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
    push('База', formatMoneyMinor(snap.base_amount_minor || c.base_amount_minor || 0));
    if (snap.base_scope_title || c.base_scope_title) push('База расчёта', snap.base_scope_title || c.base_scope_title);
    if (snap.regular_percent_bps != null || c.regular_percent_bps != null) push('Обычный %', ((Number(snap.regular_percent_bps ?? c.regular_percent_bps ?? 0) / 100).toFixed(2)) + '%');
    if (snap.applied_percent_bps != null || c.percent_bps != null) push('Применённый %', ((Number(snap.applied_percent_bps ?? c.percent_bps ?? 0) / 100).toFixed(2)) + '%');
    if (snap.boost_target_minor != null) push('Цель', formatMoneyMinor(snap.boost_target_minor));
    else if (snap.boost_target_value != null) push('Цель KPI', String(snap.boost_target_value));
    if (snap.boost_actual_minor != null) push('Факт', formatMoneyMinor(snap.boost_actual_minor));
    else if (snap.boost_actual_value != null) push('Факт KPI', String(snap.boost_actual_value));
    if (snap.boost_recalc_mode_title) push('Режим', snap.boost_recalc_mode_title);
    if (snap.minimum_guarantee_minor != null) push('Мин. гарантия', `${formatMoneyMinor(snap.minimum_guarantee_minor)} ${minimumScopeLabel(snap)}`);
    if (snap.maximum_cap_minor != null) push('Максимум', formatMoneyMinor(snap.maximum_cap_minor));
  }
  return rows.length ? `<div class="payroll-breakdown__kv">${rows.join('')}</div>` : '';
}

function breakdownExplain(component) {
  const snap = componentSnapshot(component);
  const type = String(component?.component_type || '').toUpperCase();
  if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
    const parts = [];
    if (snap?.boost_enabled) {
      parts.push(snap?.boost_applied ? 'Повышенный процент применился.' : 'Сейчас остаётся базовый процент.');
    } else {
      parts.push('Без условия повышения.');
    }
    if (snap?.minimum_applied) parts.push('Итог поднят минимальной гарантией.');
    if (snap?.maximum_applied) parts.push('Итог ограничен потолком.');
    if (Array.isArray(snap?.day_rows) && snap.day_rows.length) parts.push('Компонент разложен по дням.');
    return parts.join(' ');
  }
  if (type === 'KPI_BONUS') {
    if (component?.matched_step?.threshold_value != null) return 'Сработала подходящая ступень KPI-бонуса.';
    return 'Фиксированный бонус за выполнение KPI.';
  }
  if (type === 'SALARY_HOURLY') return 'Компонент посчитан по фактически отработанным часам.';
  if (type === 'SALARY_PER_SHIFT') return 'Компонент посчитан по количеству смен в периоде.';
  if (type === 'SALARY_FIXED_MONTH') return 'Фиксированная часть за период.';
  if (type === 'MINIMUM_PAYOUT') return component?.minimum_applied ? 'Добавлена доплата до минимальной суммы выплаты.' : 'Минимум уже перекрыт другими компонентами.';
  return 'Компонент профиля начисления.';
}

function breakdownDayRowsHtml(c) {
  const snap = componentSnapshot(c);
  const rows = Array.isArray(snap?.day_rows) ? snap.day_rows : [];
  if (!rows.length) return '';
  return `<div class="payroll-breakdown__dayrows">${rows.map((row) => {
    const meta = [];
    if (row?.base_amount_minor != null) meta.push(`база ${formatMoneyMinor(row.base_amount_minor)}`);
    if (row?.target_amount_minor != null) meta.push(`цель ${formatMoneyMinor(row.target_amount_minor)}`);
    if (row?.actual_amount_minor != null) meta.push(`факт ${formatMoneyMinor(row.actual_amount_minor)}`);
    if (row?.percent_bps != null) meta.push(((Number(row.percent_bps || 0) / 100).toFixed(2)) + '%');
    if (row?.boost_applied) meta.push('boost ✓');
    if (row?.minimum_applied) meta.push('мин ✓');
    return `<div class="payroll-breakdown__dayrow"><div class="payroll-breakdown__dayrow-main"><div class="payroll-breakdown__dayrow-date">${esc(formatDateRu(row.date))}</div><div class="payroll-breakdown__dayrow-meta">${esc(meta.join(' · '))}</div></div><div class="payroll-breakdown__dayrow-amount">${esc(formatMoneyMinor(row.amount_minor || 0))}</div></div>`;
  }).join('')}</div>`;
}

function openPayrollBreakdown() {
  if (!payrollLine?.breakdown) return;
  const breakdown = payrollLine.breakdown || {};
  const metrics = breakdown.metrics || {};
  const components = Array.isArray(breakdown.components) ? breakdown.components : [];
  const dates = Array.isArray(metrics.worked_dates) ? metrics.worked_dates : [];
  const componentsHtml = components.length ? components.map((c) => `
    <div class="payroll-breakdown__row">
      <div class="payroll-breakdown__meta">
        <div class="payroll-breakdown__header">
          <div>
            <div class="payroll-breakdown__eyebrow">${esc(COMPONENT_LABELS[String(c.component_type || '').toUpperCase()] || c.component_type || 'Компонент')}</div>
            <div class="payroll-breakdown__title">${esc(c.title || c.component_type || "Компонент")}</div>
            <div class="payroll-breakdown__explain">${esc(breakdownExplain(c))}</div>
          </div>
          <div class="payroll-breakdown__amount">${esc(formatMoneyMinor(c.amount_minor || 0))}</div>
        </div>
        ${breakdownMetaHtml(c)}
        ${breakdownBadgesHtml(c)}
        ${breakdownKvHtml(c)}
        ${breakdownDayRowsHtml(c)}
      </div>
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

async function openDayModal(d) {
  const slotLabel = selectedSalaryShiftSlot !== "TOTAL" ? ` · ${salaryShiftSlotLabel(selectedSalaryShiftSlot)}` : "";
  const subtitle = (monthSummaryItem?.source === "payroll"
    ? (d?.includedInPayroll ? "Этот день вошёл в итоговый расчёт" : "Детализация начисления за день")
    : "Детализация начисления за день") + slotLabel;
  openModal(
    `${formatDateRu(d.date)}`,
    subtitle,
    `<div class="itemcard" style="margin-top:12px"><div class="muted">Загружаем детализацию начисления…</div></div>`
  );

  try {
    const breakdown = await loadDayBreakdown(d.date);
    if (modalTitle) modalTitle.textContent = formatDateRu(d.date);
    if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle;
    if (modalBody) modalBody.innerHTML = renderDayBreakdownModal(d, breakdown);
  } catch (e) {
    if (modalTitle) modalTitle.textContent = formatDateRu(d.date);
    if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle;
    if (modalBody) modalBody.innerHTML = fallbackDayModalHtml(d);
    toast(e?.data?.detail || e?.message || "Не удалось загрузить детализацию начисления", "err");
  }
}

el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth = new Date(`${coerceDemoMonth(ym(curMonth), { context: "staff-salary" })}-01T00:00:00`);
  curMonth.setDate(1);
  syncUrl();
  await refresh();
});
el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth = new Date(`${coerceDemoMonth(ym(curMonth), { context: "staff-salary" })}-01T00:00:00`);
  curMonth.setDate(1);
  syncUrl();
  await refresh();
});
el.periodMonthBtn?.addEventListener("click", async () => {
  periodMode = "month";
  syncPeriodUi();
  syncUrl();
  await refresh();
});
el.periodRangeBtn?.addEventListener("click", async () => {
  if (isDemoUiMode()) return;
  periodMode = "range";
  if (!rangeFrom || !rangeTo) {
    rangeFrom = monthStartIso(curMonth);
    rangeTo = monthEndIso(curMonth);
  }
  syncPeriodUi();
  syncUrl();
  await refresh();
});
el.rangeApply?.addEventListener("click", async () => {
  if (isDemoUiMode()) return;
  const from = String(el.rangeFrom?.value || "").trim();
  const to = String(el.rangeTo?.value || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(from) || !/^\d{4}-\d{2}-\d{2}$/.test(to)) {
    toast("Укажи обе даты диапазона", "err");
    return;
  }
  if (from > to) {
    toast("Дата начала должна быть раньше даты окончания", "err");
    return;
  }
  rangeFrom = from;
  rangeTo = to;
  periodMode = "range";
  syncPeriodUi();
  syncUrl();
  await refresh();
});
el.openPayrollBreakdownBtn?.addEventListener("click", openPayrollBreakdown);
el.addManualTipBtn?.addEventListener("click", async () => {
  await ensureVenuesLoaded();
  openManualTipModal();
});

syncPeriodUi();
syncUrl();
refresh();


function mountDemoFlowTour() {
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) return;
  const v = venueId || getActiveVenueId();
  const q = v ? `?venue_id=${encodeURIComponent(String(v))}` : "";
  mountDemoPageTour({
    tourId: "demo-staff-flow",
    step: 2,
    total: 2,
    title: "Финальный шаг DEMO-тура",
    text: "Здесь сотрудник видит зарплату за подготовленный месяц и разрез по дням. После этого можно завершить тур и продолжить свободный просмотр.",
    prevPath: `/staff-shifts.html${q}`,
    finishPath: `/staff-shifts.html${q}`,
  });
}

try { mountDemoFlowTour(); } catch {}

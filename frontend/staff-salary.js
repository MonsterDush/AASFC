import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
} from "/app.js";

applyTelegramTheme();
mountCommonUI("salary");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "salary", requireVenue: true });

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
};

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
let days = [];
let adjustmentsByDate = new Map();
let adjustmentsSummary = { penalties: 0, bonuses: 0, writeoffs: 0 }; // [{date, salary, hasReport, shifts:[] }]

async function loadMonth() {
  if (!venueId) return;

  const m = ym(curMonth);
  el.monthLabel.textContent = monthTitle(curMonth);
  el.daysList.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;

  // shifts
  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/shifts?month=${encodeURIComponent(m)}`);
    shifts = Array.isArray(out) ? out : (out?.items || []);
  } catch (e) {
    shifts = [];
    toast(e?.message || "Не удалось загрузить смены", "err");
  }


  // adjustments (mine)
  adjustmentsByDate = new Map();
  adjustmentsSummary = { penalties: 0, bonuses: 0, writeoffs: 0 };
  try {
    const out2 = await api(`/venues/${encodeURIComponent(venueId)}/adjustments?month=${encodeURIComponent(m)}&mine=1`);
    const items = out2?.items || [];
    for (const it of items) {
      const d = it.date;
      if (!d) continue;
      const arr = adjustmentsByDate.get(d) || [];
      arr.push(it);
      adjustmentsByDate.set(d, arr);

      if (it.type === "penalty") adjustmentsSummary.penalties += Number(it.amount) || 0;
      if (it.type === "bonus") adjustmentsSummary.bonuses += Number(it.amount) || 0;
      if (it.type === "writeoff") adjustmentsSummary.writeoffs += Number(it.amount) || 0;
    }
  } catch (e) {
    // ignore, still show salary
  }

  // group by date
  const map = new Map(); // date -> {salary, hasReport, shifts:[]}
  for (const s of shifts) {
    const d = s.date;
    if (!d) continue;
    const row = map.get(d) || { date: d, salary: 0, tips: 0, hasReport: !!s.report_exists, shifts: [] };
    row.hasReport = row.hasReport || !!s.report_exists;
    row.shifts.push(s);

    const val = Number(s.my_salary);
    if (Number.isFinite(val)) row.salary += val;

    const tval = Number(s.my_tips_share);
    // tips share is per day: only add once
    if (Number.isFinite(tval) && tval > 0 && row.tips === 0) row.tips = tval;

    map.set(d, row);
  }

  days = Array.from(map.values()).sort((a,b)=>a.date.localeCompare(b.date));

  renderSummary();
  renderDays();
}

function renderSummary() {
  const totalSalary = days.reduce((acc, d) => acc + (Number.isFinite(d.salary) ? d.salary : 0), 0);
  const totalTips = days.reduce((acc, d) => acc + (Number.isFinite(d.tips) ? d.tips : 0), 0);

  const totalPenalties = adjustmentsSummary.penalties;
  const totalBonuses = adjustmentsSummary.bonuses;

  // пока удержание списаний не включаем (можно будет сделать настройкой заведения)
  const holdWriteoffs = false;
  const totalWriteoffs = adjustmentsSummary.writeoffs;

  el.sumSalary.textContent = formatMoney(totalSalary);
  if (el.sumTips) el.sumTips.textContent = formatMoney(totalTips);
  el.sumPenalties.textContent = formatMoney(totalPenalties);
  el.sumBonuses.textContent = formatMoney(totalBonuses);

  if (holdWriteoffs) {
    el.rowWriteoffs.style.display = "flex";
    el.sumWriteoffs.textContent = formatMoney(totalWriteoffs);
  } else {
    el.rowWriteoffs.style.display = "none";
  }

  const total = totalSalary + totalTips - totalPenalties + totalBonuses - (holdWriteoffs ? totalWriteoffs : 0);
  el.sumTotal.textContent = formatMoney(total);
}

function renderDays() {
  el.daysList.innerHTML = "";
  if (!days.length) {
    el.daysList.innerHTML = `<div class="muted">Нет данных за этот месяц</div>`;
    return;
  }

function formatDateRuNoG(iso) {
  const dt = new Date(String(iso).length === 10 ? iso + "T00:00:00" : iso);
  const dd = String(dt.getDate()).padStart(2, "0");
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const yyyy = dt.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

  for (const d of days) {
    const card = document.createElement("div");
    const dd = formatDateRuNoG(d.date); // <-- "dd.mm.yyyy"
    card.className = "dayrow";

    card.innerHTML = `
      <div class="row" style="justify-content:space-between; gap:10px; align-items:center; margin-top:3px !important;">
        <div>
          <b>${esc(dd)}</b>
        </div>
        <div class="dayrow__right">
          <div class="day-salary" style="${d.salary>0 ? "" : "opacity:.45"}">${d.salary>0 ? ("+"+formatMoney(d.salary)) : "Нет отчета"}</div>
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
      <div style="border-bottom:1px solid var(--border); padding:10px 0;">
        <div class="row" style="justify-content:space-between; align-items:center; gap:10px">
          <div>
            <b>${esc(interval)}</b>
            <div class="muted" style="font-size:12px">${s.report_exists ? "Отчёт есть" : "Нет отчёта"}</div>
          </div>
          <div class="day-salary" style="${Number.isFinite(sal) ? "" : "opacity:.45"}">${esc(salText)}</div>
        </div>
      </div>
    `;
  }).join("");

  openModal(
    `День ${d.date}`,
    "",
    `<div class="itemcard">
        <div class="row" style="justify-content:space-between;align-items:center">
          <div class="muted">Итого за день</div>
          <div class="day-salary" style="${d.salary>0 ? "" : "opacity:.45"}">${d.salary>0 ? ("+"+formatMoney(d.salary)) : "—"}</div>
        </div>
        <div class="row" style="justify-content:space-between;align-items:center; margin-top:8px">
          <div class="muted">Чаевые за день</div>
          <div class="day-salary" style="${d.tips>0 ? "" : "opacity:.45"}">${d.tips>0 ? ("+"+formatMoney(d.tips)) : "—"}</div>
        </div>
        <div style="margin-top:10px">${shiftsHtml || `<div class="muted">Смен нет</div>`}</div>
        <div style="margin-top:10px">
          ${(() => {
            const arr = adjustmentsByDate.get(d.date) || [];
            if (!arr.length) return `<div class="muted">Штрафов/премий/списаний нет</div>`;
            const rows = arr.map(it => {
              const sign = it.type === "penalty" || it.type === "writeoff" ? "-" : "+";
              const label = it.type === "penalty" ? "Штраф" : (it.type === "bonus" ? "Премия" : "Списание");
              return `<div class="row" style="justify-content:space-between; gap:10px; margin-top:8px">
                <div>${label}${it.reason ? ` · <span class="muted">${esc(it.reason)}</span>` : ""}</div>
                <b>${sign}${formatMoney(Number(it.amount)||0)}</b>
              </div>`;
            }).join("");
            return `<div class="itemcard" style="margin-top:12px">
              <b>Штрафы/Премии</b>
              ${rows}
              <div class="muted" style="margin-top:8px; font-size:12px">Оспорить можно в разделе «Штрафы»</div>
            </div>`;
          })()}
        </div>

      </div>`
  );
}

el.prev.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonth();
});
el.next.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonth();
});

loadMonth();

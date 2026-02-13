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
let days = []; // [{date, salary, hasReport, shifts:[] }]

async function loadMonth() {
  if (!venueId) return;

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

    map.set(d, row);
  }

  days = Array.from(map.values()).sort((a,b)=>a.date.localeCompare(b.date));

  renderSummary();
  renderDays();
}

function renderSummary() {
  const totalSalary = days.reduce((acc, d) => acc + (Number.isFinite(d.salary) ? d.salary : 0), 0);

  // Пока G1 не сделан — нули (но UI готов)
  const totalPenalties = 0;
  const totalBonuses = 0;

  // Флаг удержания списаний (позже будет настройка заведения)
  const holdWriteoffs = false;
  const totalWriteoffs = 0;

  el.sumSalary.textContent = formatMoney(totalSalary);
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

function renderDays() {
  el.daysList.innerHTML = "";
  if (!days.length) {
    el.daysList.innerHTML = `<div class="muted">Нет данных за этот месяц</div>`;
    return;
  }

  for (const d of days) {
    const card = document.createElement("div");
    card.className = "dayrow";
    card.innerHTML = `
      <div class="row" style="justify-content:space-between; gap:10px; align-items:center">
        <div>
          <b>${esc(d.date)}</b>
          <div class="muted" style="font-size:12px">${d.hasReport ? "Есть отчёт" : "Нет отчёта"}</div>
        </div>
        <div class="dayrow__right">
          <div class="day-salary" style="${d.salary>0 ? "" : "opacity:.45"}">${d.salary>0 ? ("+"+formatMoney(d.salary)) : "—"}</div>
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
        <div style="margin-top:10px">${shiftsHtml || `<div class="muted">Смен нет</div>`}</div>
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

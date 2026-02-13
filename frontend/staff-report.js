import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenuePermissions,
  getVenueById,
} from "/app.js";

applyTelegramTheme();
mountCommonUI("report");
await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "report" });

const els = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  grid: document.getElementById("calGrid"),
  dayPanel: document.getElementById("dayPanel"),
  venueMeta: document.getElementById("venueMeta"),
};

const WEEKDAYS = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"];

function esc(s){
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}
function ymd(d){
  const dt = (d instanceof Date) ? d : new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth()+1).padStart(2,"0");
  const dd = String(dt.getDate()).padStart(2,"0");
  return `${y}-${m}-${dd}`;
}
function ym(d){
  const dt = (d instanceof Date) ? d : new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth()+1).padStart(2,"0");
  return `${y}-${m}`;
}
function monthTitle(d){
  const dt = (d instanceof Date) ? d : new Date(d);
  const m = dt.toLocaleString("ru-RU", { month: "long" });
  const y = dt.getFullYear();
  return `${m.charAt(0).toUpperCase()}${m.slice(1)} ${y}`;
}

let curMonth = new Date();
curMonth.setDate(1);

let venueName = "";
let perms = { role: null, flags: {} };
let reportsByDate = new Map();
let selectedDay = null;

async function loadVenueMeta(){
  if (!venueId) {
    els.venueMeta.textContent = "Заведение не выбрано";
    return;
  }
  try {
    const v = await getVenueById(venueId);
    venueName = v?.name || "";
  } catch { venueName = ""; }
  els.venueMeta.textContent = venueName ? `Заведение: ${venueName}` : `venue_id=${venueId}`;
}

async function loadPerms(){
  perms = { role: null, flags: {} };
  if (!venueId) return;
  try {
    const p = await getMyVenuePermissions(venueId);
    perms.role = p?.role || null;
    perms.flags = p?.position_flags || p?.position || {};
    if (perms.flags.can_make_reports) {
      perms.flags.can_view_reports = true;
      perms.flags.can_view_revenue = true;
    }
  } catch { perms = { role: null, flags: {} }; }
}
const canViewReports = () => perms.role === "OWNER" || !!perms.flags.can_view_reports || !!perms.flags.can_make_reports;
const canEditReports = () => perms.role === "OWNER" || !!perms.flags.can_make_reports;
const canViewRevenue = () => perms.role === "OWNER" || !!perms.flags.can_view_revenue || !!perms.flags.can_make_reports;

async function loadMonthReports(){
  reportsByDate = new Map();
  if (!venueId || !canViewReports()) return;
  const month = ym(curMonth);
  try {
    const list = await api(`/venues/${encodeURIComponent(venueId)}/reports?month=${encodeURIComponent(month)}`);
    (list || []).forEach(r => { if (r?.date) reportsByDate.set(r.date, r); });
  } catch { reportsByDate = new Map(); }
}

function renderMonth(){
  els.monthLabel.textContent = monthTitle(curMonth);
  els.grid.innerHTML = "";

  const head = document.createElement("div");
  head.className = "cal-head";
  WEEKDAYS.forEach(w => {
    const c = document.createElement("div");
    c.className = "cal-hcell";
    c.textContent = w;
    head.appendChild(c);
  });
  els.grid.appendChild(head);

  const body = document.createElement("div");
  body.className = "cal-body";

  const first = new Date(curMonth);
  const jsDow = first.getDay();
  const mondayBased = (jsDow + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayBased);

  const monthStr = ym(curMonth);
  const todayStr = ymd(new Date());

  for (let i=0;i<42;i++){
    const d = new Date(start);
    d.setDate(start.getDate()+i);
    const dStr = ymd(d);

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell";
    const hasReport = reportsByDate.has(dStr);

    cell.innerHTML = `
      <div class="cal-num">${d.getDate()}</div>
      <div class="cal-sub muted" style="font-size:11px">${hasReport ? "отчёт" : ""}</div>
    `;

    if (ym(d) !== monthStr) cell.classList.add("is-out");
    if (dStr === todayStr) cell.classList.add("is-today");
    if (hasReport) cell.classList.add("has-report");
    if (selectedDay === dStr) cell.classList.add("is-selected");

    cell.addEventListener("click", () => openDay(dStr));
    body.appendChild(cell);
  }

  els.grid.appendChild(body);
}

async function fetchReport(dayISO){
  try {
    return await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}`);
  } catch { return null; }
}

function renderDayPanel(dayISO, report){
  const exists = !!report;
  const edit = canEditReports();
  const viewRevenue = canViewRevenue();

  const cash = report?.cash ?? "";
  const cashless = report?.cashless ?? "";
  const total = report?.revenue_total ?? "";

  els.dayPanel.innerHTML = `
    <div class="itemcard">
      <div class="row" style="justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
        <div>
          <b>${esc(dayISO)}</b>
          <div class="muted" style="margin-top:4px">${exists ? "Отчёт есть" : "Отчёта нет"}</div>
        </div>
        <div class="row" style="gap:10px;flex-wrap:wrap">
          ${edit ? `<button class="btn primary" id="btnSave">${exists ? "Сохранить" : "Создать"}</button>` : ""}
        </div>
      </div>

      <div class="row" style="gap:10px;flex-wrap:wrap;margin-top:12px">
        <label style="min-width:180px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Наличка</div>
          <input id="cash" type="number" min="0" value="${esc(cash)}" ${edit && viewRevenue ? "" : "disabled"} />
        </label>
        <label style="min-width:180px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Безнал</div>
          <input id="cashless" type="number" min="0" value="${esc(cashless)}" ${edit && viewRevenue ? "" : "disabled"} />
        </label>
        <label style="min-width:220px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Выручка (итого)</div>
          <input id="total" type="number" min="0" value="${esc(total)}" ${edit && viewRevenue ? "" : "disabled"} />
        </label>
      </div>

      <div class="muted" style="margin-top:8px;font-size:12px">
        ${edit ? (viewRevenue ? "Можно редактировать и сохранять отчёт." : "Нет доступа к суммам — редактирование отключено.") : "Нет права на создание/редактирование отчётов."}
      </div>
    </div>
  `;

  if (edit) {
    els.dayPanel.querySelector("#btnSave")?.addEventListener("click", async () => {
      if (!viewRevenue) { toast("Нет доступа к суммам отчёта", "err"); return; }
      const cashV = Number(els.dayPanel.querySelector("#cash")?.value || 0);
      const cashlessV = Number(els.dayPanel.querySelector("#cashless")?.value || 0);
      const totalV = Number(els.dayPanel.querySelector("#total")?.value || 0);

      try {
        await api(`/venues/${encodeURIComponent(venueId)}/reports`, {
          method: "POST",
          body: { date: dayISO, cash: cashV, cashless: cashlessV, revenue_total: totalV },
        });
        toast("Отчёт сохранён", "ok");
        await reload();
        await openDay(dayISO);
      } catch (e) {
        toast("Ошибка сохранения: " + (e?.message || "неизвестно"), "err");
      }
    });
  }
}

async function openDay(dayISO){
  selectedDay = dayISO;
  renderMonth();

  if (!canViewReports()) {
    els.dayPanel.innerHTML = `
      <div class="itemcard">
        <b>${esc(dayISO)}</b>
        <div class="muted" style="margin-top:6px">Нет прав на просмотр отчётов.</div>
      </div>
    `;
    return;
  }

  els.dayPanel.innerHTML = `<div class="itemcard"><div class="muted">Загрузка отчёта…</div></div>`;
  const report = await fetchReport(dayISO);
  renderDayPanel(dayISO, report);
}

async function reload(){
  await loadPerms();
  await loadVenueMeta();
  await loadMonthReports();
  renderMonth();
}

els.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth()-1);
  curMonth.setDate(1);
  await loadMonthReports();
  renderMonth();
});
els.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth()+1);
  curMonth.setDate(1);
  await loadMonthReports();
  renderMonth();
});

(async function boot(){
  if (!venueId) {
    els.grid.innerHTML = `
      <div class="itemcard">
        <b>Не выбрано заведение</b>
        <div class="muted" style="margin-top:6px">Открой отчёты из меню заведения или добавь <span class="mono">?venue_id=...</span>.</div>
      </div>
    `;
    return;
  }
  await reload();
  await openDay(ymd(new Date()));
})();

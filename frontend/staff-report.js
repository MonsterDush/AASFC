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
} from "/app.js";

applyTelegramTheme();
mountCommonUI("report");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "report", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  grid: document.getElementById("calGrid"),
};

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitleEl = document.getElementById("modalSubtitle");

function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);

function openModal(title, subtitle, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Отчёт";
  if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle || "";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
function ymd(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

let curMonth = new Date();
curMonth.setDate(1);

let perms = { can_make_reports: false, can_view_reports: false, can_view_revenue: false };
    permsUnknown = true;
let permsUnknown = true; // if we can't reliably detect perms, allow attempting save (backend will enforce)
let reportsByDate = new Map(); // dateISO -> report row (may contain null numbers)

function monthTitle(d) {
  const m = d.toLocaleString("ru-RU", { month: "long" });
  return `${m[0].toUpperCase()}${m.slice(1)} ${d.getFullYear()}`;
}

function canMakeReports() { return !!perms.can_make_reports || permsUnknown; }
function canViewReports() { return !!perms.can_view_reports || !!perms.can_make_reports || permsUnknown; }
function canViewRevenue() { return !!perms.can_view_revenue || !!perms.can_make_reports; }

function parsePerms(obj) {
  // Backend may return a list of permission codes OR direct boolean flags.
  const role = obj?.role || obj?.venue_role || "";
  const isOwner = role === "OWNER";

  const list = obj?.permissions || obj?.permission_codes || obj?.codes || [];
  const has = (code) => Array.isArray(list) && list.includes(code);

  const boolMake = obj?.can_make_reports === true;
  const boolView = obj?.can_view_reports === true;
  const boolRevenue = obj?.can_view_revenue === true;

  // If we can't see explicit report permissions, we allow "try save" mode.
  // This is important when permissions are stored on venue_position rather than in /me/venues/.../permissions.
  permsUnknown = !(
    isOwner ||
    boolMake || boolView || boolRevenue ||
    has("can_make_reports") || has("can_view_reports") || has("can_view_revenue")
  );

  perms = {
    can_make_reports: isOwner || boolMake || has("can_make_reports"),
    can_view_reports: isOwner || boolView || boolMake || has("can_view_reports") || has("can_make_reports"),
    can_view_revenue: isOwner || boolRevenue || boolMake || has("can_view_revenue") || has("can_make_reports"),
  };
}

async function loadPerms() {
  if (!venueId) return;
  try {
    const p = await getMyVenuePermissions(venueId);
    parsePerms(p);
  } catch {
    // если не получилось — оставим false, бэк всё равно не даст лишнего
    perms = { can_make_reports: false, can_view_reports: false, can_view_revenue: false };
    permsUnknown = true;
  }
}

async function loadMonthReports() {
  if (!venueId) return;
  reportsByDate = new Map();
  const m = ym(curMonth);
  try {
    const list = await api(`/venues/${encodeURIComponent(venueId)}/reports?month=${encodeURIComponent(m)}`);
    (list || []).forEach(r => { if (r?.date) reportsByDate.set(r.date, r); });
  } catch (e) {
    // если нет права видеть отчёты — покажем тост и пустой календарь
    toast(e?.message || "Не удалось загрузить отчёты", "err");
    reportsByDate = new Map();
  }
}

function renderMonth() {
  el.monthLabel.textContent = monthTitle(curMonth);
  el.grid.innerHTML = "";

  const head = document.createElement("div");
  head.className = "cal-head";
  for (const wd of WEEKDAYS) {
    const c = document.createElement("div");
    c.className = "cal-hcell";
    c.textContent = wd;
    head.appendChild(c);
  }
  el.grid.appendChild(head);

  const body = document.createElement("div");
  body.className = "cal-body";

  const first = new Date(curMonth);
  const jsDow = first.getDay();
  const mondayBased = (jsDow + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayBased);

  const todayStr = ymd(new Date());

  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const inMonth = d.getMonth() === curMonth.getMonth();
    const dateStr = ymd(d);

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className =
      "cal-cell" +
      (inMonth ? "" : " cal-cell--out") +
      (dateStr === todayStr ? " cal-cell--today" : "");
    cell.setAttribute("data-date", dateStr);

    const top = document.createElement("div");
    top.className = "cal-daynum";
    top.textContent = String(d.getDate());
    cell.appendChild(top);

    const box = document.createElement("div");
    box.className = "cal-badges";

    if (reportsByDate.has(dateStr)) {
      const pill = document.createElement("div");
      pill.className = "pill";
      pill.textContent = "Отчёт";
      box.appendChild(pill);
    } else {
      const hint = document.createElement("div");
      hint.className = "muted";
      hint.style.fontSize = "11px";
      hint.textContent = "";
      box.appendChild(hint);
    }

    cell.appendChild(box);

    cell.addEventListener("click", async () => {
      if (!canViewReports()) {
        toast("Нет доступа к отчётам", "warn");
        return;
      }
      await openReportModal(dateStr);
    });

    body.appendChild(cell);
  }

  el.grid.appendChild(body);
}

function esc(s){
  return String(s ?? "")
    .replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
}

function numOrZero(x) {
  const n = Number(x);
  return Number.isFinite(n) ? n : 0;
}

async function openReportModal(dateStr) {
  let report = null;
  try {
    report = await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dateStr)}`);
  } catch (e) {
    // 404 = нет отчёта
    if (!String(e?.message || "").includes("404")) throw e;
  }

  const canEdit = canMakeReports();
  const showNumbers = canViewRevenue() && report !== null;

  const cash = report?.cash ?? "";
  const cashless = report?.cashless ?? "";
  const total = report?.revenue_total ?? "";

  openModal(
    `Отчёт за ${dateStr}`,
    report ? "Отчёт найден" : "Отчёта нет",
    `
      <div class="itemcard">
        <div class="row" style="gap:12px;flex-wrap:wrap">
          <label style="min-width:170px;display:block">
            <div class="muted" style="font-size:12px;margin-bottom:4px">Наличка</div>
            <input id="repCash" type="number" min="0" value="${esc(String(cash))}" ${canEdit ? "" : "disabled"} placeholder="${canEdit ? "0" : (showNumbers ? "0" : "нет доступа")}" />
          </label>

          <label style="min-width:170px;display:block">
            <div class="muted" style="font-size:12px;margin-bottom:4px">Безнал</div>
            <input id="repCashless" type="number" min="0" value="${esc(String(cashless))}" ${canEdit ? "" : "disabled"} placeholder="${canEdit ? "0" : (showNumbers ? "0" : "нет доступа")}" />
          </label>

          <label style="min-width:210px;display:block">
            <div class="muted" style="font-size:12px;margin-bottom:4px">Выручка (итого)</div>
            <input id="repTotal" type="number" min="0" value="${esc(String(total))}" ${canEdit ? "" : "disabled"} placeholder="${canEdit ? "0" : (showNumbers ? "0" : "нет доступа")}" />
          </label>
        </div>

        <div class="row" style="justify-content:space-between;align-items:center;margin-top:12px;gap:10px;flex-wrap:wrap">
          <div class="muted" style="font-size:12px">
            ${canEdit ? "Можно сохранить изменения." : "Нет права на создание/редактирование отчётов."}
          </div>
          <div class="row" style="gap:10px">
            <button class="btn" id="btnCloseRep">Закрыть</button>
            ${canEdit ? `<button class="btn primary" id="btnSaveRep">${report ? "Сохранить" : "Создать"}</button>` : ""}
          </div>
        </div>
      </div>
    `
  );

  document.getElementById("btnCloseRep")?.addEventListener("click", closeModal);

  if (canEdit) {
    document.getElementById("btnSaveRep")?.addEventListener("click", async () => {
      const cash = numOrZero(document.getElementById("repCash")?.value);
      const cashless = numOrZero(document.getElementById("repCashless")?.value);
      const revenue_total = numOrZero(document.getElementById("repTotal")?.value);

      try {
        await api(`/venues/${encodeURIComponent(venueId)}/reports`, {
          method: "POST",
          body: { date: dateStr, cash, cashless, revenue_total },
        });
        toast("Отчёт сохранён", "ok");
        closeModal();
        await loadMonthReports();
        renderMonth();
      } catch (e) {
        toast("Ошибка сохранения: " + (e?.message || "неизвестно"), "err");
      }
    });
  }
}

async function boot() {
  await loadPerms();
  await loadMonthReports();
  renderMonth();
}

el.prev.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonthReports();
  renderMonth();
});
el.next.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonthReports();
  renderMonth();
});

boot();

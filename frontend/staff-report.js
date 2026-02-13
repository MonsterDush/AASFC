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
if (!venueId) toast("Сначала выбери заведение в «Настройках»", "warn");
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "report", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  grid: document.getElementById("calGrid"),
  dayPanel: document.getElementById("dayPanel"),
};

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);

function openModal(title, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Отчёт";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
function ymd(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }
function monthTitle(d) {
  const m = d.toLocaleString("ru-RU", { month: "long" });
  return `${m[0].toUpperCase()}${m.slice(1)} ${d.getFullYear()}`;
}
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[c]));
}

function money(x) {
  if (x == null) return "—";
  const n = Number(x);
  if (Number.isNaN(n)) return "—";
  return `${n.toLocaleString("ru-RU")}₽`;
}

function dateOnly(d) {
  const x = new Date(d);
  x.setHours(0, 0, 0, 0);
  return x;
}
function cmpDateStr(dateStr) {
  const today = dateOnly(new Date());
  const d = dateOnly(new Date(dateStr));
  if (d.getTime() === today.getTime()) return 0;
  return d.getTime() < today.getTime() ? -1 : 1;
}

let curMonth = new Date();
curMonth.setDate(1);

let perms = null;
let canMake = false;
let canView = false;
let canViewRevenue = false;

let reports = [];
let reportByDate = new Map();

async function loadPerms() {
  if (!venueId) return;
  perms = await getMyVenuePermissions(venueId).catch(() => null);
  const role = perms?.role || perms?.venue_role || perms?.my_role || null;
  const flags = perms?.position_flags || {};
  const posObj = perms?.position || {};

  const isOwner = role === "OWNER" || role === "SUPER_ADMIN";
  canMake = isOwner || !!flags.can_make_reports || !!posObj.can_make_reports;
  canView = canMake || isOwner || !!flags.can_view_reports || !!posObj.can_view_reports;
  canViewRevenue = canMake || isOwner || !!flags.can_view_revenue || !!posObj.can_view_revenue;
}

async function loadMonth() {
  if (!venueId) return;
  const m = ym(curMonth);
  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/reports?month=${encodeURIComponent(m)}`);
    reports = Array.isArray(out) ? out : (out?.items || out?.reports || []);
  } catch (e) {
    reports = [];
    // 403 is a normal case for users without view permission
    if (e?.status === 403) {
      toast("Нет доступа к отчётам", "warn");
    } else {
      toast(e?.message || "Не удалось загрузить отчёты", "err");
    }
  }

  reportByDate = new Map();
  for (const r of reports) {
    if (r?.date) reportByDate.set(String(r.date), r);
  }

  renderMonth();
  if (el.dayPanel) el.dayPanel.innerHTML = "";
}

function renderMonth() {
  if (!el.grid || !el.monthLabel) return;
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
    const rel = cmpDateStr(dateStr);

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
    const r = reportByDate.get(dateStr) || null;

    if (r) {
      const b = document.createElement("div");
      b.className = "badge";
      b.textContent = canViewRevenue ? `Выручка: ${money(r.revenue_total)}` : "Отчёт готов";
      box.appendChild(b);
    } else {
      if (rel !== 1) {
        const b = document.createElement("div");
        b.className = "badge";
        b.textContent = "Нет отчёта";
        b.style.opacity = "0.6";
        box.appendChild(b);
      }
    }

    cell.appendChild(box);
    cell.onclick = () => openDay(dateStr);
    body.appendChild(cell);
  }

  el.grid.appendChild(body);
}

async function openDay(dateStr) {
  if (!el.dayPanel) return;
  el.dayPanel.innerHTML = "";

  const titleDate = new Date(dateStr).toLocaleDateString("ru-RU", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  let report = null;
  let reportExists = false;
  try {
    report = await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dateStr)}`);
    reportExists = true;
  } catch (e) {
    if (e?.status === 404) {
      reportExists = false;
    } else if (e?.status === 403) {
      el.dayPanel.innerHTML = `<div class="card"><b>${esc(titleDate)}</b><div class="muted" style="margin-top:6px">Нет доступа к просмотру отчётов</div></div>`;
      return;
    } else {
      toast(e?.message || "Не удалось загрузить отчёт", "err");
      return;
    }
  }

  const cash = report?.cash ?? null;
  const cashless = report?.cashless ?? null;
  const revenue = report?.revenue_total ?? null;
  const numbersHidden = (reportExists && cash == null && cashless == null && revenue == null);

  const actions = [];
  if (canMake) {
    actions.push(`<button class="btn" id="btnEdit">${reportExists ? "Редактировать" : "Создать"}</button>`);
  }

  el.dayPanel.innerHTML = `
    <div class="card">
      <div class="row" style="justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
        <div>
          <b>${esc(titleDate)}</b>
          <div class="muted" style="margin-top:4px">${reportExists ? "Отчёт за день" : "Отчёта пока нет"}</div>
        </div>
        <div class="row" style="gap:8px;align-items:center">${actions.join("")}</div>
      </div>

      <div style="margin-top:10px">
        ${reportExists ? `
          <div class="row" style="gap:10px;flex-wrap:wrap">
            <div class="pill" style="flex:1;min-width:160px">
              <div class="muted" style="font-size:12px">Наличка</div>
              <div style="font-size:18px"><b>${numbersHidden ? "Скрыто" : money(cash)}</b></div>
            </div>
            <div class="pill" style="flex:1;min-width:160px">
              <div class="muted" style="font-size:12px">Безнал</div>
              <div style="font-size:18px"><b>${numbersHidden ? "Скрыто" : money(cashless)}</b></div>
            </div>
            <div class="pill" style="flex:1;min-width:160px">
              <div class="muted" style="font-size:12px">Выручка</div>
              <div style="font-size:18px"><b>${numbersHidden ? "Скрыто" : money(revenue)}</b></div>
            </div>
          </div>
        ` : `<div class="muted">Если у тебя есть право, нажми «Создать» и заполни отчёт.</div>`}
      </div>
    </div>
  `;

  document.getElementById("btnEdit")?.addEventListener("click", () => openEditModal(dateStr, reportExists ? report : null));
}

function inputRow(label, id, value, disabled = false) {
  return `
    <label class="field" style="display:block;margin-top:10px">
      <div class="muted" style="font-size:12px;margin-bottom:6px">${esc(label)}</div>
      <input class="input" id="${esc(id)}" ${disabled ? "disabled" : ""} value="${esc(value ?? "")}" />
    </label>
  `;
}

function num(v) {
  const x = Number(String(v || "").trim().replace(/\s/g, ""));
  if (!Number.isFinite(x) || x < 0) return null;
  return Math.floor(x);
}

function openEditModal(dateStr, report) {
  const cash = report?.cash ?? "";
  const cashless = report?.cashless ?? "";
  const revenue = report?.revenue_total ?? "";

  openModal(
    report ? "Редактировать отчёт" : "Создать отчёт",
    `
      <div class="muted" style="font-size:12px">Дата: <b>${esc(dateStr)}</b></div>
      ${inputRow("Наличка", "cash", cash)}
      ${inputRow("Безнал", "cashless", cashless)}
      ${inputRow("Выручка", "revenue_total", revenue)}

      <div class="row" style="gap:10px;justify-content:flex-end;margin-top:14px">
        <button class="btn" data-close>Отмена</button>
        <button class="btn primary" id="btnSave">Сохранить</button>
      </div>
    `
  );

  modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const vCash = num(document.getElementById("cash")?.value);
    const vCashless = num(document.getElementById("cashless")?.value);
    const vRev = num(document.getElementById("revenue_total")?.value);

    if (vCash == null || vCashless == null || vRev == null) {
      toast("Заполни числа (0 и выше)", "warn");
      return;
    }

    try {
      await api(`/venues/${encodeURIComponent(venueId)}/reports`, {
        method: "POST",
        body: { date: dateStr, cash: vCash, cashless: vCashless, revenue_total: vRev },
      });
      closeModal();
      toast("Отчёт сохранён", "ok");
      await loadMonth();
      await openDay(dateStr);
    } catch (e) {
      toast(e?.message || "Не удалось сохранить отчёт", "err");
    }
  });
}

// month navigation
el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonth();
});
el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonth();
});

await loadPerms();
await loadMonth();

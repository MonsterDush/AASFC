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
await mountNav({ activeTab: "report" });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

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

function openModal(title, html) {
  if (!modal || !modalTitle || !modalBody) return;
  modalTitle.textContent = title || "Окно";
  modalBody.innerHTML = html;
  modal.classList.add("open");
}
function closeModal() {
  modal?.classList.remove("open");
}
document.querySelector("#modal [data-close]")?.addEventListener("click", closeModal);
document.querySelector("#modal .modal__backdrop")?.addEventListener("click", closeModal);

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function ymd(d) {
  const dt = new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}
function ym(d) {
  const dt = new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}
function monthTitle(d) {
  const dt = new Date(d);
  const m = dt.toLocaleString("ru-RU", { month: "long" });
  const y = dt.getFullYear();
  return `${m.charAt(0).toUpperCase()}${m.slice(1)} ${y}`;
}

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

let curMonth = new Date();
curMonth.setDate(1);

let reportsByDate = new Map(); // dateISO -> report
let perms = {
  can_make_reports: false,
  can_view_reports: false,
  can_view_revenue: false,
  is_owner: false, // если вдруг появится
};

async function loadPermsBestEffort() {
  // best-effort: если не получилось — не блокируем UI
  perms = { can_make_reports: false, can_view_reports: false, can_view_revenue: false, is_owner: false };

  if (!venueId) return;

  try {
    const p = await getMyVenuePermissions(venueId);

    // разные варианты структуры: поддержим все
    const flags = p?.position_flags || p?.position || {};
    const hasList = Array.isArray(p?.permissions) ? p.permissions : [];

    const has = (code) => hasList.includes(code);

    const canMake =
      p?.can_make_reports === true ||
      flags.can_make_reports === true ||
      has("SHIFT_REPORTS_CREATE") ||
      has("SHIFT_REPORTS_EDIT");

    const canView =
      p?.can_view_reports === true ||
      flags.can_view_reports === true ||
      canMake ||
      has("SHIFT_REPORTS_VIEW");

    const canRevenue =
      p?.can_view_revenue === true ||
      flags.can_view_revenue === true ||
      canMake ||
      has("SHIFT_REVENUE_VIEW");

    perms.can_make_reports = !!canMake;
    perms.can_view_reports = !!canView;
    perms.can_view_revenue = !!canRevenue;

    // если у тебя где-то прокидывается owner-флаг — тоже учтём
    perms.is_owner = p?.is_owner === true;
  } catch {
    // молча — но UI не блокируем
  }
}

async function loadMonthReports() {
  reportsByDate = new Map();
  if (!venueId) return;

  const m = ym(curMonth);
  try {
    const list = await api(`/venues/${encodeURIComponent(venueId)}/reports?month=${encodeURIComponent(m)}`);
    (list || []).forEach((r) => {
      if (r?.date) reportsByDate.set(r.date, r);
    });
  } catch (e) {
    // если нет права — просто покажем пустой календарь, но не сломаем UI
    reportsByDate = new Map();
  }
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
  const jsDow = first.getDay(); // 0 Sun..6 Sat
  const mondayBased = (jsDow + 6) % 7; // Mon=0..Sun=6
  const start = new Date(first);
  start.setDate(first.getDate() - mondayBased);

  const todayStr = ymd(new Date());
  const monthStr = ym(curMonth);

  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const dStr = ymd(d);

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell";
    cell.innerHTML = `
      <div class="cal-num">${d.getDate()}</div>
      <div class="cal-sub muted" style="font-size:11px">${esc(reportsByDate.has(dStr) ? "есть отчёт" : "")}</div>
    `;

    if (ym(d) !== monthStr) cell.classList.add("is-out");
    if (dStr === todayStr) cell.classList.add("is-today");
    if (reportsByDate.has(dStr)) cell.classList.add("has-report");

    cell.addEventListener("click", () => openDay(dStr));
    body.appendChild(cell);
  }

  el.grid.appendChild(body);
}

async function openDay(dayISO) {
  if (!venueId) return;

  // короткая панель на странице (не форма)
  if (el.dayPanel) {
    const exists = reportsByDate.has(dayISO);
    const canEdit = perms.is_owner || perms.can_make_reports || true; // best-effort: пусть бэк решит
    el.dayPanel.innerHTML = `
      <div class="itemcard">
        <div class="row" style="justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
          <div>
            <b>${esc(dayISO)}</b>
            <div class="muted" style="margin-top:4px">${exists ? "Отчёт уже есть" : "Отчёта нет"}</div>
          </div>
          <div class="row" style="gap:10px">
            <button class="btn ${canEdit ? "primary" : ""}" id="btnOpenReport">
              ${exists ? "Открыть отчёт" : "Создать отчёт"}
            </button>
          </div>
        </div>
      </div>
    `;
    el.dayPanel.querySelector("#btnOpenReport")?.addEventListener("click", () => showReportModal(dayISO));
  }

  // можно сразу открывать модалку по клику на день — но оставим через кнопку
}

function numOr0(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : 0;
}

async function showReportModal(dayISO) {
  if (!venueId) return;

  // Попробуем получить отчёт. Если 404 — будем создавать.
  let report = null;
  let exists = false;
  try {
    report = await api(`/venues/${encodeURIComponent(venueId)}/reports/${encodeURIComponent(dayISO)}`);
    exists = true;
  } catch (e) {
    // 404 — ок, создаём новый
    exists = false;
  }

  // Если бэк вернул числа как null (нет права видеть выручку) — поля отображаем как read-only/placeholder
  const canSeeNumbers = (report?.revenue_total !== null && report?.revenue_total !== undefined) || perms.can_view_revenue || perms.can_make_reports || perms.is_owner;

  // best-effort: позволяем редактировать, но если прав реально нет — получим 403 на save
  const canEdit = perms.can_make_reports || perms.is_owner || true;

  const cashVal = report?.cash ?? "";
  const cashlessVal = report?.cashless ?? "";
  const totalVal = report?.revenue_total ?? "";

  openModal(
    `Отчёт за ${dayISO}`,
    `
    <div class="itemcard">
      <div class="muted" style="margin-bottom:10px">
        ${exists ? "Редактирование/просмотр отчёта" : "Создание отчёта"}
      </div>

      <div class="row" style="gap:10px;flex-wrap:wrap">
        <label style="min-width:180px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Наличка</div>
          <input id="repCash" type="number" min="0"
            value="${esc(cashVal)}"
            ${(!canEdit || !canSeeNumbers) ? "disabled" : "" }
            placeholder="${canSeeNumbers ? "0" : "нет доступа"}"
          />
        </label>

        <label style="min-width:180px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Безнал</div>
          <input id="repCashless" type="number" min="0"
            value="${esc(cashlessVal)}"
            ${(!canEdit || !canSeeNumbers) ? "disabled" : "" }
            placeholder="${canSeeNumbers ? "0" : "нет доступа"}"
          />
        </label>

        <label style="min-width:220px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Выручка (итого)</div>
          <input id="repTotal" type="number" min="0"
            value="${esc(totalVal)}"
            ${(!canEdit || !canSeeNumbers) ? "disabled" : "" }
            placeholder="${canSeeNumbers ? "0" : "нет доступа"}"
          />
        </label>
      </div>

      <div class="row" style="justify-content:space-between;align-items:center;margin-top:12px;gap:10px;flex-wrap:wrap">
        <div class="muted" style="font-size:12px">
          ${canEdit ? "Сохранение доступно (права проверит сервер)" : "Нет прав на редактирование"}
        </div>
        <div class="row" style="gap:10px">
          <button class="btn" id="btnCloseRep">Закрыть</button>
          ${canEdit ? `<button class="btn primary" id="btnSaveRep">${exists ? "Сохранить" : "Создать"}</button>` : ""}
        </div>
      </div>
    </div>
    `
  );

  document.getElementById("btnCloseRep")?.addEventListener("click", closeModal);

  if (canEdit) {
    document.getElementById("btnSaveRep")?.addEventListener("click", async () => {
      // Если нет доступа к цифрам — не дадим отправлять мусор
      if (!canSeeNumbers) {
        toast("Нет доступа к суммам отчёта", "err");
        return;
      }

      const cash = Math.max(0, numOr0(document.getElementById("repCash")?.value));
      const cashless = Math.max(0, numOr0(document.getElementById("repCashless")?.value));
      const revenue_total = Math.max(0, numOr0(document.getElementById("repTotal")?.value));

      try {
        await api(`/venues/${encodeURIComponent(venueId)}/reports`, {
          method: "POST",
          body: { date: dayISO, cash, cashless, revenue_total },
        });

        toast("Отчёт сохранён", "ok");
        closeModal();

        await loadMonthReports();
        renderMonth();
        await openDay(dayISO);
      } catch (e) {
        toast("Ошибка сохранения: " + (e?.message || "неизвестно"), "err");
      }
    });
  }
}

function renderNoVenue() {
  if (el.grid) {
    el.grid.innerHTML = `
      <div class="itemcard">
        <b>Не выбрано заведение</b>
        <div class="muted" style="margin-top:6px">
          Открой страницу из меню приложения или добавь <span class="mono">?venue_id=...</span>.
        </div>
      </div>
    `;
  }
  if (el.dayPanel) el.dayPanel.innerHTML = "";
}

async function boot() {
  if (!el.grid || !el.monthLabel) {
    // если сломалась разметка
    toast("Ошибка: не найден календарь на странице", "err");
    return;
  }

  if (!venueId) {
    renderNoVenue();
    return;
  }

  try {
    await loadPermsBestEffort();
    await loadMonthReports();
    renderMonth();
  } catch (e) {
    // главное — не оставить пустую страницу
    toast("Ошибка загрузки отчётов: " + (e?.message || "неизвестно"), "err");
    renderMonth();
  }
}

el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonthReports();
  renderMonth();
});
el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonthReports();
  renderMonth();
});

boot();

import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
  getPayroll,
  calculatePayroll,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const id = params.get("venue_id") || "";
  if (id) setActiveVenueId(id);
  return id;
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function fmtMoneyMinor(minor) {
  const value = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";
  } catch {
    return value.toFixed(2) + " ₽";
  }
}

function memberName(member) {
  if (!member) return "—";
  return member.short_name || member.full_name || (member.tg_username ? `@${member.tg_username}` : `user #${member.user_id || ""}`);
}

const COMPONENT_LABELS = {
  SALARY_FIXED_MONTH: "Оклад за месяц",
  SALARY_HOURLY: "Почасовая ставка",
  SALARY_PER_SHIFT: "Фикс за смену",
  PERCENT_TOTAL_REVENUE: "% от общей выручки",
  PERCENT_DEPARTMENT_REVENUE: "% от выручки департамента",
};

function fmtPercentBps(bps) {
  const value = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + "%";
  } catch {
    return value.toFixed(2) + "%";
  }
}

function breakdownComponentMeta(component) {
  const type = String(component?.component_type || "").toUpperCase();
  const label = COMPONENT_LABELS[type] || type || "Компонент";
  if (type === "PERCENT_TOTAL_REVENUE") {
    return `${label} · ${fmtPercentBps(component?.percent_bps)} · база ${fmtMoneyMinor(component?.base_amount_minor || 0)}`;
  }
  if (type === "PERCENT_DEPARTMENT_REVENUE") {
    const depTitle = component?.department_title ? ` · ${component.department_title}` : "";
    return `${label} · ${fmtPercentBps(component?.percent_bps)}${depTitle} · база ${fmtMoneyMinor(component?.base_amount_minor || 0)}`;
  }
  return label;
}

let state = {
  venueId: "",
  month: currentMonth(),
  me: null,
  perms: null,
  can: { view: false, calculate: false },
  data: null,
};

function computeCaps(perms, me) {
  const role = roleUpper(perms);
  const pset = permSetFromResponse(perms);
  const sysRole = String(me?.system_role || "").toUpperCase();
  const isOwner = role === "OWNER" || role === "VENUE_OWNER";
  const isAdmin = sysRole === "SUPER_ADMIN" || sysRole === "MODERATOR";
  return {
    view: isOwner || isAdmin || hasPerm(pset, "PAYROLL_VIEW") || hasPerm(pset, "PAYROLL_CALCULATE"),
    calculate: isOwner || isAdmin || hasPerm(pset, "PAYROLL_CALCULATE"),
  };
}

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Начисления</b>
          <div class="muted" id="subtitle">расчёт зарплаты за месяц</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="revenue-toolbar__actions">
        <div class="revenue-toolbar__caption">
          <b>Расчёт зарплаты</b>
          <div class="muted mt-6">Считается по активным назначениям профилей. Поддержаны фиксированные ставки и проценты по закрытым отчётам.</div>
        </div>
        <div class="pickers pickers--revenue">
          <input id="monthPick" type="month" style="width:auto; min-width:160px;" />
          <button class="btn primary" id="btnCalculate">Рассчитать</button>
          <a class="btn" id="openProfilesBtn" href="#">Профили</a>
        </div>
      </div>

      <div class="finance-stats finance-stats-1 mt-12" style="grid-template-columns:repeat(3,minmax(0,1fr));">
        <div class="itemcard finance-stat">
          <div class="finance-stat__label">Итого</div>
          <div class="finance-stat__value" id="totalAmount">—</div>
        </div>
        <div class="itemcard finance-stat">
          <div class="finance-stat__label">Сотрудников</div>
          <div class="finance-stat__value" id="linesCount">—</div>
        </div>
        <div class="itemcard finance-stat">
          <div class="finance-stat__label">Статус расчёта</div>
          <div class="finance-stat__value" id="runMeta">—</div>
        </div>
      </div>

      <div class="itemcard mt-12">
        <div class="section-head">
          <div class="section-title"><b>Строки начислений</b></div>
        </div>
        <div id="linesList" class="mt-12"><div class="skeleton"></div><div class="skeleton"></div></div>
      </div>

      <div class="row mt-12" style="justify-content:space-between; gap:12px; flex-wrap:wrap;">
        <a class="link" id="backVenue" href="#">← Назад к заведению</a>
        <a class="link" id="openSummary" href="#">Открыть сводку →</a>
      </div>
    </div>

    <div id="toast" class="toast"><div class="toast__text"></div></div>
    <div id="modal" class="modal">
      <div class="modal__backdrop"></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div class="modal__title">JSON</div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body"></div>
      </div>
    </div>

    <div class="nav"><div class="wrap"><div id="nav"></div></div></div>
  `;

  mountCommonUI("none");
}

function renderState() {
  const btnCalculate = document.getElementById("btnCalculate");
  const monthPick = document.getElementById("monthPick");
  const backVenue = document.getElementById("backVenue");
  const openSummary = document.getElementById("openSummary");
  const openProfilesBtn = document.getElementById("openProfilesBtn");
  if (monthPick) monthPick.value = state.month;
  if (btnCalculate) btnCalculate.style.display = state.can.calculate ? "" : "none";
  if (backVenue) backVenue.href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;
  if (openSummary) openSummary.href = `/owner-summary.html?venue_id=${encodeURIComponent(state.venueId)}&month=${encodeURIComponent(state.month)}`;
  if (openProfilesBtn) openProfilesBtn.href = `/owner-pay-profiles.html?venue_id=${encodeURIComponent(state.venueId)}`;
}

function renderLines() {
  const totalAmount = document.getElementById("totalAmount");
  const linesCount = document.getElementById("linesCount");
  const runMeta = document.getElementById("runMeta");
  const linesList = document.getElementById("linesList");
  if (!linesList) return;

  if (!state.can.view) {
    linesList.innerHTML = `<div class="muted">Нет доступа к начислениям</div>`;
    if (totalAmount) totalAmount.textContent = "—";
    if (linesCount) linesCount.textContent = "—";
    if (runMeta) runMeta.textContent = "нет доступа";
    return;
  }

  const data = state.data || { lines: [], total_amount_minor: 0, lines_count: 0, run: null };
  if (totalAmount) totalAmount.textContent = fmtMoneyMinor(data.total_amount_minor);
  if (linesCount) linesCount.textContent = String(Number(data.lines_count || 0));
  if (runMeta) runMeta.textContent = data.run?.calculated_at ? "рассчитано" : "ещё не считалось";

  const lines = Array.isArray(data.lines) ? data.lines : [];
  if (!lines.length) {
    linesList.innerHTML = `<div class="muted">За выбранный месяц начислений пока нет. Нажми «Рассчитать», если профили уже назначены.</div>`;
    return;
  }

  linesList.innerHTML = "";
  lines.forEach((line) => {
    const breakdown = line.breakdown || {};
    const metrics = breakdown.metrics || {};
    const components = Array.isArray(breakdown.components) ? breakdown.components : [];
    const row = document.createElement("div");
    row.className = "expense-row";
    row.innerHTML = `
      <div>
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <b class="expense-row__title">${esc(memberName(line.member))}</b>
          ${line.pay_profile_title ? `<span class="badge">${esc(line.pay_profile_title)}</span>` : ""}
        </div>
        <div class="mono mt-6">Часы: ${esc(metrics.hours_total ?? 0)} · Смены: ${esc(metrics.shifts_count ?? 0)}</div>
        <details class="mt-12 payroll-breakdown">
          <summary>Показать разбор</summary>
          <div class="payroll-breakdown__body mt-8">
            ${components.length ? components.map((c) => `
              <div class="payroll-breakdown__row">
                <div>
                  <b>${esc(c.title || c.component_type || "Компонент")}</b>
                  <div class="mono mt-4">${esc(breakdownComponentMeta(c))}</div>
                </div>
                <div><b>${esc(fmtMoneyMinor(c.amount_minor || 0))}</b></div>
              </div>
            `).join("") : `<div class="muted">Нет breakdown</div>`}
          </div>
        </details>
      </div>
      <div class="expense-row__side">
        <div class="expense-row__amount">${esc(fmtMoneyMinor(line.amount_minor))}</div>
      </div>
    `;
    linesList.appendChild(row);
  });
}

async function load() {
  const linesList = document.getElementById("linesList");
  if (linesList) linesList.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
  try {
    state.data = await getPayroll(state.venueId, state.month);
    renderLines();
  } catch (e) {
    if (linesList) linesList.innerHTML = `<div class="muted">Ошибка: ${esc(e?.data?.detail || e?.message || "не удалось загрузить")}</div>`;
    toast("Не удалось загрузить начисления", "err");
  }
}

async function onCalculate() {
  try {
    await calculatePayroll(state.venueId, state.month);
    toast("Расчёт выполнен", "ok");
    await load();
  } catch (e) {
    toast("Ошибка расчёта: " + (e?.data?.detail || e?.message || "не удалось рассчитать"), "err");
  }
}

async function boot() {
  applyTelegramTheme();
  renderShell();
  await ensureLogin({ silent: true });

  state.venueId = parseVenueId();
  if (!state.venueId) {
    root.innerHTML = `<div class="card"><div class="muted">Не найден venue_id</div></div>`;
    return;
  }

  const params = new URLSearchParams(location.search);
  state.month = params.get("month") || currentMonth();

  await mountNav({ activeTab: "summary" });

  try {
    state.me = await getMe();
  } catch {
    state.me = null;
  }

  try {
    state.perms = await getMyVenuePermissions(state.venueId);
  } catch {
    state.perms = null;
  }

  state.can = computeCaps(state.perms, state.me);
  renderState();

  document.getElementById("monthPick")?.addEventListener("change", async (e) => {
    state.month = e.target.value || currentMonth();
    renderState();
    await load();
  });

  document.getElementById("btnCalculate")?.addEventListener("click", onCalculate);

  await load();
}

document.addEventListener("DOMContentLoaded", boot);

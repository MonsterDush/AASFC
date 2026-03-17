import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  getMyVenuePermissions,
  api,
  toast,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

const state = {
  month: "",
  payload: null,
  access: {
    canView: false,
    canCalculate: false,
    canViewProfiles: false,
  },
};

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtMinor(minor) {
  const rub = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return rub.toFixed(2) + " ₽";
  }
}

function fmtDateTime(value) {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
  } catch {
    return String(value);
  }
}

function openHtmlModal(title, html) {
  const modal = document.getElementById("modal");
  if (!modal) return;
  const head = modal.querySelector(".modal__title");
  const body = modal.querySelector(".modal__body");
  if (head) head.textContent = title;
  if (body) body.innerHTML = html;
  modal.classList.add("open");
}

function breakdownHtml(line) {
  const breakdown = line?.breakdown || {};
  const metrics = breakdown?.metrics || {};
  const components = Array.isArray(breakdown?.components) ? breakdown.components : [];
  return `
    <div class="payroll-breakdown">
      <div class="itemcard">
        <b>${esc(breakdown?.member_name || line?.member?.short_name || "Сотрудник")}</b>
        <div class="muted mt-6">Профиль: ${esc(breakdown?.pay_profile_title || line?.pay_profile_title || "—")}</div>
        <div class="entity-tags mt-8">
          <span class="badge">Часов: ${Number(metrics.hours_total || 0)}</span>
          <span class="badge">Минут: ${Number(metrics.minutes_total || 0)}</span>
          <span class="badge">Смен: ${Number(metrics.shifts_count || 0)}</span>
          <span class="badge">Итого: ${esc(fmtMinor(line?.amount_minor))}</span>
        </div>
      </div>
      ${components.map((component) => `
        <div class="itemcard payroll-breakdown__item">
          <div class="entity-row__title">${esc(component.title || component.component_type || "Компонент")}</div>
          <div class="entity-tags mt-8">
            <span class="badge">${esc(component.component_type || "—")}</span>
            <span class="badge">Сумма: ${esc(fmtMinor(component.amount_minor))}</span>
            <span class="badge">Часов: ${Number(component.hours_total || 0)}</span>
            <span class="badge">Смен: ${Number(component.shifts_count || 0)}</span>
          </div>
        </div>
      `).join("") || '<div class="muted">Нет компонентов в breakdown.</div>'}
    </div>
  `;
}

function showEmpty(message) {
  const list = document.getElementById("payrollLines");
  if (list) list.innerHTML = `<div class="muted">${esc(message)}</div>`;
}

async function loadAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return state.access;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    state.access = {
      canView: isOwner || hasPerm(pset, "PAYROLL_VIEW") || hasPerm(pset, "PAYROLL_CALCULATE"),
      canCalculate: isOwner || hasPerm(pset, "PAYROLL_CALCULATE"),
      canViewProfiles: isOwner || hasPerm(pset, "PAY_PROFILES_VIEW") || hasPerm(pset, "PAY_PROFILES_MANAGE"),
    };
  } catch {
    state.access = { canView: false, canCalculate: false, canViewProfiles: false };
  }
  return state.access;
}

function syncActions() {
  const calcBtn = document.getElementById("calculatePayrollBtn");
  const profilesBtn = document.getElementById("openProfilesBtn");
  const venueId = getActiveVenueId();
  if (calcBtn) calcBtn.style.display = state.access.canCalculate ? "" : "none";
  if (profilesBtn) {
    profilesBtn.style.display = state.access.canViewProfiles ? "" : "none";
    profilesBtn.onclick = () => {
      location.href = `/owner-pay-profiles.html?venue_id=${encodeURIComponent(venueId)}`;
    };
  }
}

function renderPayroll() {
  const run = state.payload?.run || null;
  const lines = Array.isArray(state.payload?.lines) ? state.payload.lines : [];
  const hint = document.getElementById("payrollHint");
  const totalEl = document.getElementById("payrollTotal");
  const countEl = document.getElementById("payrollLinesCount");
  const atEl = document.getElementById("payrollCalculatedAt");
  const stateEl = document.getElementById("payrollState");
  const list = document.getElementById("payrollLines");

  if (totalEl) totalEl.textContent = fmtMinor(state.payload?.total_amount_minor || 0);
  if (countEl) countEl.textContent = String(state.payload?.lines_count || 0);
  if (atEl) atEl.textContent = fmtDateTime(run?.calculated_at);
  if (stateEl) stateEl.textContent = run ? "Рассчитано" : "Нет расчёта";
  if (hint) hint.textContent = run ? `месяц ${state.month}` : `месяц ${state.month} · расчёт не запускался`;

  if (!list) return;
  if (!run || !lines.length) {
    showEmpty(state.access.canCalculate ? "Пока нет расчёта за этот месяц. Нажмите «Рассчитать»." : "Пока нет расчёта за этот месяц.");
    return;
  }

  list.innerHTML = lines.map((line) => {
    const memberName = line?.member?.short_name || line?.member?.full_name || (line?.member?.tg_username ? `@${line.member.tg_username}` : `user #${line.member_user_id}`);
    const metrics = line?.breakdown?.metrics || {};
    return `
      <div class="entity-row">
        <div>
          <div class="entity-row__title">${esc(memberName)}</div>
          <div class="muted mt-6">Профиль: ${esc(line?.pay_profile_title || "—")}</div>
          <div class="entity-tags mt-8">
            <span class="badge">Часов: ${Number(metrics.hours_total || 0)}</span>
            <span class="badge">Смен: ${Number(metrics.shifts_count || 0)}</span>
            <span class="badge">Компонентов: ${Array.isArray(line?.breakdown?.components) ? line.breakdown.components.length : 0}</span>
          </div>
        </div>
        <div class="entity-row__side">
          <div class="payroll-line__amount">${esc(fmtMinor(line?.amount_minor))}</div>
          <button class="btn small" data-open-breakdown="${line.id}">Подробнее</button>
          ${state.access.canViewProfiles && line?.pay_profile_id ? `<a class="btn small" href="/owner-pay-profile.html?venue_id=${encodeURIComponent(getActiveVenueId())}&profile_id=${encodeURIComponent(line.pay_profile_id)}">Профиль</a>` : ""}
        </div>
      </div>
    `;
  }).join("");

  list.querySelectorAll("[data-open-breakdown]").forEach((btn) => {
    btn.onclick = () => {
      const line = lines.find((item) => String(item.id) === String(btn.dataset.openBreakdown));
      if (!line) return;
      openHtmlModal("Breakdown начисления", breakdownHtml(line));
    };
  });
}

async function loadPayroll() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  const list = document.getElementById("payrollLines");
  if (list) list.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
  try {
    state.payload = await api(`/venues/${encodeURIComponent(venueId)}/payroll?month=${encodeURIComponent(state.month)}`);
    renderPayroll();
  } catch (e) {
    state.payload = null;
    showEmpty(e?.data?.detail || e.message || "Не удалось загрузить начисления");
    const stateEl = document.getElementById("payrollState");
    if (stateEl) stateEl.textContent = "Ошибка";
    toast("Не удалось загрузить начисления", "err");
  }
}

async function calculatePayroll() {
  try {
    await api(`/venues/${encodeURIComponent(getActiveVenueId())}/payroll/calculate`, {
      method: "POST",
      body: { month: state.month },
    });
    toast("Начисления пересчитаны", "ok");
    await loadPayroll();
  } catch (e) {
    toast(e?.data?.detail || e.message || "Не удалось выполнить расчёт", "err");
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);
  state.month = params.get("month") || currentMonth();

  await mountNav({ activeTab: "summary" });
  await loadAccess();
  syncActions();

  try {
    const venues = await getMyVenues();
    const venue = venues.find((item) => String(item.id) === String(getActiveVenueId()));
    if (venue) {
      const subtitle = document.getElementById("subtitle");
      if (subtitle) subtitle.textContent = venue.name || "";
    }
  } catch {}

  const monthPick = document.getElementById("payrollMonthPick");
  if (monthPick) {
    monthPick.value = state.month;
    monthPick.onchange = async () => {
      state.month = monthPick.value || currentMonth();
      await loadPayroll();
    };
  }

  const refreshBtn = document.getElementById("refreshPayrollBtn");
  if (refreshBtn) refreshBtn.onclick = () => loadPayroll();

  const calcBtn = document.getElementById("calculatePayrollBtn");
  if (calcBtn) calcBtn.onclick = () => calculatePayroll();

  if (!state.access.canView) {
    showEmpty("Нет прав на просмотр начислений.");
    const stateEl = document.getElementById("payrollState");
    if (stateEl) stateEl.textContent = "Нет доступа";
    return;
  }

  await loadPayroll();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

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
import { roleUpper } from "/permissions.js";

const state = {
  date: null,
  month: null,
  mode: "MONTH",
  access: { canManage: false },
  effectivePlan: null,
  monthPlan: null,
  overridePlan: null,
  templates: [],
};

const WEEKDAYS = [
  [0, "Понедельник"],
  [1, "Вторник"],
  [2, "Среда"],
  [3, "Четверг"],
  [4, "Пятница"],
  [5, "Суббота"],
  [6, "Воскресенье"],
];

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function monthISO(dateStr) {
  const d = dateStr ? new Date(`${dateStr}T00:00:00`) : new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function fmtMoneyMinor(minor) {
  if (minor === null || minor === undefined || minor === "") return "—";
  const rub = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return `${rub.toFixed(2)} ₽`;
  }
}

function parseMoneyToMinor(value) {
  const raw = String(value ?? "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!raw) return null;
  const num = Number(raw);
  if (!Number.isFinite(num)) throw new Error("Неверный денежный формат");
  return Math.round(num * 100);
}

function toInputMoney(minor) {
  if (minor === null || minor === undefined) return "";
  return (Number(minor) / 100).toFixed(2);
}

function getVenueId() {
  return getActiveVenueId();
}

function buildDayEconomicsLink() {
  const qp = new URLSearchParams();
  const venueId = getVenueId();
  if (venueId) qp.set("venue_id", String(venueId));
  qp.set("date", state.date || todayISO());
  return `/owner-day-economics.html?${qp.toString()}`;
}

function sourceLabel(plan) {
  const source = String(plan?.source || "NONE").toUpperCase();
  if (source === "DATE_OVERRIDE") return "Override на дату";
  if (source === "MONTH_TEMPLATE") return `Месяц · ${plan?.template_month_title || plan?.template_month || state.month}`;
  if (source === "WEEKDAY_TEMPLATE") return `День недели · ${plan?.template_weekday_title || "шаблон"}`;
  return "План не задан";
}

function sourceHint(plan) {
  const source = String(plan?.source || "NONE").toUpperCase();
  if (source === "DATE_OVERRIDE") return `Для ${plan?.date || state.date} используется override на дату.`;
  if (source === "MONTH_TEMPLATE") return `Для ${plan?.date || state.date} используется общий план на месяц ${plan?.template_month_title || plan?.template_month || state.month}.`;
  if (source === "WEEKDAY_TEMPLATE") return `Для ${plan?.date || state.date} используется шаблон по дню недели.`;
  return "На дату пока не задан ни override, ни план на месяц, ни шаблон по дню недели.";
}

function extractEnabled(plan) {
  return {
    revenue: plan?.revenue_plan_minor != null,
    profit: plan?.profit_plan_minor != null,
    revenuePerAssigned: plan?.revenue_per_assigned_plan_minor != null,
    assignedUsers: plan?.assigned_user_target != null,
  };
}

function planFormHtml(prefix, title, subtitle, plan = {}) {
  const enabled = extractEnabled(plan);
  return `
    <div class="row" style="justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
      <div>
        <b>${esc(title)}</b>
        <div class="muted mt-6">${esc(subtitle)}</div>
      </div>
    </div>
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="${prefix}_enable_revenue" ${enabled.revenue ? "checked" : ""} /> Использовать план выручки</span>
      <input name="${prefix}_revenue_plan" type="text" placeholder="150000.00" value="${esc(toInputMoney(plan?.revenue_plan_minor))}" />
    </label>
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="${prefix}_enable_profit" ${enabled.profit ? "checked" : ""} /> Использовать план прибыли</span>
      <input name="${prefix}_profit_plan" type="text" placeholder="50000.00" value="${esc(toInputMoney(plan?.profit_plan_minor))}" />
    </label>
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="${prefix}_enable_revenue_per_assigned" ${enabled.revenuePerAssigned ? "checked" : ""} /> Использовать план выручки на сотрудника</span>
      <input name="${prefix}_revenue_per_assigned_plan" type="text" placeholder="30000.00" value="${esc(toInputMoney(plan?.revenue_per_assigned_plan_minor))}" />
    </label>
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="${prefix}_enable_assigned_user_target" ${enabled.assignedUsers ? "checked" : ""} /> Использовать цель по сотрудникам</span>
      <input name="${prefix}_assigned_user_target" type="number" min="0" step="1" placeholder="5" value="${plan?.assigned_user_target == null ? "" : esc(String(plan.assigned_user_target))}" />
    </label>
    <label>Комментарий<textarea name="${prefix}_notes" rows="3" placeholder="Комментарий">${esc(plan?.notes || "")}</textarea></label>
  `;
}

function bindToggleDisable(form, prefix) {
  const pairs = [
    ["enable_revenue", "revenue_plan"],
    ["enable_profit", "profit_plan"],
    ["enable_revenue_per_assigned", "revenue_per_assigned_plan"],
    ["enable_assigned_user_target", "assigned_user_target"],
  ];
  pairs.forEach(([toggleName, inputName]) => {
    const toggle = form.elements.namedItem(`${prefix}_${toggleName}`);
    const input = form.elements.namedItem(`${prefix}_${inputName}`);
    if (!toggle || !input) return;
    const sync = () => { input.disabled = !toggle.checked; };
    toggle.addEventListener("change", sync);
    sync();
  });
}

function buildPlanPayload(form, prefix) {
  const fd = new FormData(form);
  const enabledRevenue = fd.get(`${prefix}_enable_revenue`) === "on";
  const enabledProfit = fd.get(`${prefix}_enable_profit`) === "on";
  const enabledRevenuePerAssigned = fd.get(`${prefix}_enable_revenue_per_assigned`) === "on";
  const enabledAssigned = fd.get(`${prefix}_enable_assigned_user_target`) === "on";
  return {
    revenue_plan_minor: enabledRevenue ? parseMoneyToMinor(fd.get(`${prefix}_revenue_plan`)) : null,
    profit_plan_minor: enabledProfit ? parseMoneyToMinor(fd.get(`${prefix}_profit_plan`)) : null,
    revenue_per_assigned_plan_minor: enabledRevenuePerAssigned ? parseMoneyToMinor(fd.get(`${prefix}_revenue_per_assigned_plan`)) : null,
    assigned_user_target: enabledAssigned ? (fd.get(`${prefix}_assigned_user_target`) ? Number(fd.get(`${prefix}_assigned_user_target`)) : 0) : null,
    notes: String(fd.get(`${prefix}_notes`) || "").trim() || null,
  };
}

function renderEffective(plan) {
  setText("effectivePlanSourceBadge", sourceLabel(plan));
  setText("effectivePlanHint", sourceHint(plan));
  setText("effectivePlanRevenue", fmtMoneyMinor(plan?.revenue_plan_minor));
  setText("effectivePlanProfit", fmtMoneyMinor(plan?.profit_plan_minor));
  setText("effectivePlanPerAssigned", fmtMoneyMinor(plan?.revenue_per_assigned_plan_minor));
  setText("effectivePlanAssigned", plan?.assigned_user_target == null ? "—" : String(plan.assigned_user_target));
  setText("effectivePlanNotes", plan?.notes || "Без комментария.");
}

function renderMonthPlan(plan) {
  setText("monthPlanBadge", plan?.template_month_title || state.month || "—");
  setText("monthPlanHint", plan?.notes || "Этот план применяется ко всем дням выбранного месяца, если на дату нет override.");
  const form = document.getElementById("monthPlanForm");
  if (!form) return;
  form.innerHTML = planFormHtml("month", "План на месяц", `Шаблон для ${plan?.template_month_title || state.month}`, plan) + `<div class="row gap-8 mt-12"><button class="btn" type="submit">Сохранить план месяца</button></div>`;
  bindToggleDisable(form, "month");
  form.style.display = state.access.canManage ? "" : "none";
  form.onsubmit = saveMonthPlan;
}

function renderOverride(plan) {
  setText("overrideBadge", plan?.revenue_plan_minor != null || plan?.profit_plan_minor != null || plan?.revenue_per_assigned_plan_minor != null || plan?.assigned_user_target != null ? "Заполнен" : "Не задан");
  const form = document.getElementById("planOverrideForm");
  if (!form) return;
  form.innerHTML = planFormHtml("override", "Override на дату", `Для ${state.date} можно задать отдельный план.`, plan) + `<div class="row gap-8 mt-12"><button class="btn" type="submit">Сохранить override</button></div>`;
  bindToggleDisable(form, "override");
  form.style.display = state.access.canManage ? "" : "none";
  form.onsubmit = saveOverride;
}

function templateCard(template) {
  const weekday = Number(template.weekday);
  const formId = `weekdayTemplateForm_${weekday}`;
  return `
    <div class="itemcard mt-8">
      <div class="row" style="justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap;">
        <div>
          <b>${esc(template.weekday_title || "День недели")}</b>
          <div class="muted mt-6">Используется, если нет override на дату и плана на месяц.</div>
        </div>
        <span class="badge">${esc(template.weekday_title || "—")}</span>
      </div>
      <form id="${formId}" class="finance-form mt-12">
        ${planFormHtml(`weekday_${weekday}`, template.weekday_title || "День недели", "Настройки для всех соответствующих дней недели.", template)}
        <div class="row gap-8 mt-12"><button class="btn" type="submit">Сохранить шаблон</button></div>
      </form>
    </div>
  `;
}

function renderTemplates(list) {
  const container = document.getElementById("planTemplatesList");
  if (!container) return;
  container.innerHTML = Array.isArray(list) && list.length ? list.map(templateCard).join("") : `<div class="muted">Шаблонов пока нет.</div>`;
  (Array.isArray(list) ? list : []).forEach((template) => {
    const weekday = Number(template.weekday);
    const form = document.getElementById(`weekdayTemplateForm_${weekday}`);
    if (!form) return;
    bindToggleDisable(form, `weekday_${weekday}`);
    form.style.display = state.access.canManage ? "" : "none";
    form.addEventListener("submit", (event) => saveTemplate(event, weekday));
  });
}

function setMode(mode) {
  state.mode = mode === "WEEKDAYS" ? "WEEKDAYS" : "MONTH";
  const monthCard = document.getElementById("monthPlanCard");
  const weekdayCard = document.getElementById("weekdayPlansCard");
  if (monthCard) monthCard.style.display = state.mode === "MONTH" ? "" : "none";
  if (weekdayCard) weekdayCard.style.display = state.mode === "WEEKDAYS" ? "" : "none";
  document.querySelectorAll('input[name="planMode"]').forEach((radio) => {
    radio.checked = radio.value === state.mode;
  });
}

async function loadAccess() {
  const venueId = getVenueId();
  if (!venueId) return;
  try {
    const resp = await getMyVenuePermissions(venueId);
    const role = roleUpper(resp);
    state.access.canManage = role === "OWNER" || role === "VENUE_OWNER";
  } catch {
    state.access.canManage = false;
  }
}

async function loadData() {
  const venueId = getVenueId();
  if (!venueId) return;
  const [effectivePlan, overridePlan, monthPlan, templates] = await Promise.all([
    api(`/venues/${encodeURIComponent(venueId)}/economics/plan?date=${encodeURIComponent(state.date)}`),
    api(`/venues/${encodeURIComponent(venueId)}/economics/plan/override?date=${encodeURIComponent(state.date)}`),
    api(`/venues/${encodeURIComponent(venueId)}/economics/plan-month?month=${encodeURIComponent(state.month)}`),
    api(`/venues/${encodeURIComponent(venueId)}/economics/plan-templates`),
  ]);
  state.effectivePlan = effectivePlan || {};
  state.overridePlan = overridePlan || {};
  state.monthPlan = monthPlan || {};
  state.templates = Array.isArray(templates) ? templates : [];
  renderEffective(state.effectivePlan);
  renderMonthPlan(state.monthPlan);
  renderOverride(state.overridePlan);
  renderTemplates(state.templates);
}

async function saveMonthPlan(event) {
  event.preventDefault();
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const payload = buildPlanPayload(event.currentTarget, "month");
    await api(`/venues/${encodeURIComponent(venueId)}/economics/plan-month?month=${encodeURIComponent(state.month)}`, {
      method: "PUT",
      body: payload,
    });
    toast("План на месяц сохранён", "ok");
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось сохранить план месяца", "err");
  }
}

async function saveOverride(event) {
  event.preventDefault();
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const payload = buildPlanPayload(event.currentTarget, "override");
    await api(`/venues/${encodeURIComponent(venueId)}/economics/plan?date=${encodeURIComponent(state.date)}`, {
      method: "PUT",
      body: payload,
    });
    toast("Override сохранён", "ok");
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось сохранить override", "err");
  }
}

async function saveTemplate(event, weekday) {
  event.preventDefault();
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const payload = buildPlanPayload(event.currentTarget, `weekday_${weekday}`);
    await api(`/venues/${encodeURIComponent(venueId)}/economics/plan-templates/${encodeURIComponent(weekday)}`, {
      method: "PUT",
      body: payload,
    });
    toast("Шаблон сохранён", "ok");
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось сохранить шаблон", "err");
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin();

  const params = new URLSearchParams(location.search);
  const venues = await getMyVenues();
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);
  if (!getActiveVenueId() && Array.isArray(venues) && venues.length) setActiveVenueId(venues[0].id);

  state.date = params.get("date") || todayISO();
  state.month = params.get("month") || monthISO(state.date);
  state.mode = String(params.get("mode") || "MONTH").toUpperCase() === "WEEKDAYS" ? "WEEKDAYS" : "MONTH";

  await mountNav({ activeTab: "summary" });
  await loadAccess();

  const datePick = document.getElementById("plansDatePick");
  if (datePick) {
    datePick.value = state.date;
    datePick.onchange = async (e) => {
      state.date = e.target.value || todayISO();
      if (state.month !== monthISO(state.date)) {
        state.month = monthISO(state.date);
        const monthPick = document.getElementById("plansMonthPick");
        if (monthPick) monthPick.value = state.month;
      }
      await loadData();
    };
  }

  const monthPick = document.getElementById("plansMonthPick");
  if (monthPick) {
    monthPick.value = state.month;
    monthPick.onchange = async (e) => {
      state.month = e.target.value || monthISO(state.date);
      await loadData();
    };
  }

  document.querySelectorAll('input[name="planMode"]').forEach((radio) => {
    radio.addEventListener("change", (e) => setMode(e.target.value));
  });
  setMode(state.mode);

  const openBtn = document.getElementById("openDayEconomicsFromPlansBtn");
  if (openBtn) openBtn.onclick = () => { location.href = buildDayEconomicsLink(); };

  await loadData();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

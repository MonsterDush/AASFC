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
  departmentMonthPlans: null,
  departmentDayPlans: null,
  copyResultHint: '—',
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

const TARGET_GROUPS = {
  WORKDAYS: [0, 1, 2, 3, 4],
  WEEKENDS: [5, 6],
  ALL: [0, 1, 2, 3, 4, 5, 6],
};

function dayKindLabel(kind) {
  const key = String(kind || '').toUpperCase();
  if (key === 'HOLIDAY') return 'Праздник';
  if (key === 'SPECIAL') return 'Спец-день';
  return '';
}

function templateOptionsHtml(selected) {
  return WEEKDAYS.map(([id, title]) => `<option value="${id}" ${String(selected) === String(id) ? 'selected' : ''}>${esc(title)}</option>`).join('');
}

function customTargetsHtml(selected = []) {
  const set = new Set((Array.isArray(selected) ? selected : []).map((v) => Number(v)));
  return WEEKDAYS.map(([id, title]) => `<label class="badge" style="cursor:pointer;"><input type="checkbox" name="custom_target_weekday" value="${id}" ${set.has(id) ? 'checked' : ''} /> ${esc(title)}</label>`).join(' ');
}

function setAllPlanToggles(form, prefix, checked) {
  ['revenue', 'profit', 'revenue_per_assigned', 'assigned_user_target'].forEach((name) => {
    const toggle = form?.elements?.namedItem(`${prefix}_enable_${name}`);
    if (toggle) {
      toggle.checked = checked;
      toggle.dispatchEvent(new Event('change'));
    }
  });
}

function selectedCopyWeekdays(form) {
  return Array.from(form.querySelectorAll('input[name="custom_target_weekday"]:checked')).map((el) => Number(el.value));
}

function syncWeekdayCopyTargets() {
  const form = document.getElementById('weekdayCopyForm');
  const wrap = document.getElementById('weekdayCopyCustomTargets');
  if (!form || !wrap) return;
  const group = String(form.elements.namedItem('target_group')?.value || 'WORKDAYS').toUpperCase();
  wrap.style.display = group === 'CUSTOM' ? '' : 'none';
}

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

function shiftISODate(dateStr, deltaDays) {
  const d = dateStr ? new Date(`${dateStr}T00:00:00`) : new Date();
  d.setDate(d.getDate() + Number(deltaDays || 0));
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function syncDepartmentDayQuickControls() {
  const copyInput = document.getElementById('departmentDayCopyFromDate');
  if (copyInput) copyInput.value = shiftISODate(state.date || todayISO(), -7);
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


function usageInlineText(payload, { empty = 'Пока не используется в процентных начислениях' } = {}) {
  const componentCount = Number(payload?.usage_component_count || 0);
  const profileCount = Number(payload?.usage_profile_count || 0);
  if (!componentCount) return empty;
  return `Используется в ${componentCount} компонент(ах)${profileCount ? ` · профилей: ${profileCount}` : ''}`;
}

function departmentPlansTableHtml(prefix, payload = {}, options = {}) {
  const rows = Array.isArray(payload?.items) ? payload.items : [];
  const canManage = !!options.canManage;
  if (!rows.length) return `<div class="muted">Нет активных департаментов.</div>`;
  return `
    <div class="dept-plan-table">
      <div class="dept-plan-table__head">
        <div>Департамент</div>
        <div>План</div>
        <div>${prefix === 'dept_month' ? 'Факт текущий' : 'Факт дня'}</div>
        <div>${prefix === 'dept_month' ? 'Прошлый месяц' : 'Комментарий'}</div>
      </div>
      ${rows.map((row) => `
        <div class="dept-plan-table__row">
          <div>
            <b>${esc(row.department_title || 'Департамент')}</b>
            <div class="muted mt-6">${esc(row.department_code || '')}</div>
            <div class="muted mt-6">${esc(usageInlineText(row))}</div>
            <input type="hidden" name="${prefix}_department_id" value="${esc(row.department_id)}" />
          </div>
          <div>
            <input ${canManage ? '' : 'disabled'} name="${prefix}_revenue_plan_minor_${row.department_id}" type="text" placeholder="0.00" value="${esc(toInputMoney(row.revenue_plan_minor))}" />
          </div>
          <div>
            <b>${fmtMoneyMinor(row.actual_current_minor)}</b>
          </div>
          <div>
            ${prefix === 'dept_month' ? `<b>${fmtMoneyMinor(row.actual_previous_minor)}</b>` : `<textarea ${canManage ? '' : 'disabled'} name="${prefix}_notes_${row.department_id}" rows="2" placeholder="Комментарий">${esc(row.notes || '')}</textarea>`}
          </div>
        </div>
      `).join('')}
    </div>
    ${canManage ? `<div class="row gap-8 mt-12"><button class="btn" type="submit">Сохранить ${prefix === 'dept_month' ? 'планы месяца' : 'планы на дату'}</button></div>` : ''}
  `;
}

function buildDepartmentPlanPayload(form, prefix) {
  const rows = [];
  form.querySelectorAll(`input[name="${prefix}_department_id"]`).forEach((hidden) => {
    const depId = Number(hidden.value || 0);
    if (!depId) return;
    const revenueInput = form.querySelector(`[name="${prefix}_revenue_plan_minor_${depId}"]`);
    const notesInput = form.querySelector(`[name="${prefix}_notes_${depId}"]`);
    rows.push({
      department_id: depId,
      revenue_plan_minor: parseMoneyToMinor(revenueInput?.value || ''),
      notes: notesInput ? String(notesInput.value || '').trim() || null : null,
    });
  });
  return { items: rows };
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
  const kind = dayKindLabel(plan?.day_kind);
  const suffix = kind ? ` · ${kind}` : "";
  if (source === "DATE_OVERRIDE") return `Override на дату${suffix}`;
  if (source === "MONTH_TEMPLATE") return `Месяц · ${plan?.template_month_title || plan?.template_month || state.month}`;
  if (source === "WEEKDAY_TEMPLATE") return `День недели · ${plan?.template_weekday_title || "шаблон"}`;
  return "План не задан";
}

function sourceHint(plan) {
  const source = String(plan?.source || "NONE").toUpperCase();
  const kind = dayKindLabel(plan?.day_kind);
  const title = String(plan?.title || '').trim();
  if (source === "DATE_OVERRIDE") return `Для ${plan?.date || state.date} используется override на дату${kind ? ` (${kind.toLowerCase()})` : ''}${title ? ` — ${title}` : ''}.`;
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

function planFormHtml(prefix, title, subtitle, plan = {}, options = {}) {
  const enabled = extractEnabled(plan);
  const includeDayMeta = Boolean(options.includeDayMeta);
  const dayKind = String(plan?.day_kind || '').toUpperCase();
  return `
    <div class="row" style="justify-content:space-between; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:8px;">
      <div>
        <b>${esc(title)}</b>
        <div class="muted mt-6">${esc(subtitle)}</div>
      </div>
      <div class="row" style="gap:8px; align-items:center; flex-wrap:wrap;">
        <button class="btn ghost" type="button" data-plan-action="enable-all" data-prefix="${prefix}">Включить всё</button>
        <button class="btn ghost" type="button" data-plan-action="disable-all" data-prefix="${prefix}">Выключить всё</button>
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
    ${includeDayMeta ? `
      <label>
        <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="${prefix}_enable_day_meta" ${dayKind ? "checked" : ""} /> Отметить как спец-день / праздник</span>
        <select name="${prefix}_day_kind">
          <option value="SPECIAL" ${dayKind === 'SPECIAL' ? 'selected' : ''}>Спец-день</option>
          <option value="HOLIDAY" ${dayKind === 'HOLIDAY' ? 'selected' : ''}>Праздник</option>
        </select>
      </label>
      <label>Название дня / события<input name="${prefix}_title" type="text" maxlength="255" placeholder="Например, 8 Марта / Турнир / Вечеринка" value="${esc(plan?.title || '')}" /></label>
    ` : ''}
    <label>Комментарий<textarea name="${prefix}_notes" rows="3" placeholder="Комментарий">${esc(plan?.notes || "")}</textarea></label>
  `;
}

function bindToggleDisable(form, prefix) {
  const pairs = [
    ["enable_revenue", "revenue_plan"],
    ["enable_profit", "profit_plan"],
    ["enable_revenue_per_assigned", "revenue_per_assigned_plan"],
    ["enable_assigned_user_target", "assigned_user_target"],
    ["enable_day_meta", "day_kind"],
    ["enable_day_meta", "title"],
  ];
  pairs.forEach(([toggleName, inputName]) => {
    const toggle = form.elements.namedItem(`${prefix}_${toggleName}`);
    const input = form.elements.namedItem(`${prefix}_${inputName}`);
    if (!toggle || !input) return;
    const sync = () => { input.disabled = !toggle.checked; };
    toggle.addEventListener("change", sync);
    sync();
  });
  form.querySelectorAll('[data-plan-action]').forEach((btn) => {
    btn.onclick = () => {
      const action = btn.getAttribute('data-plan-action');
      setAllPlanToggles(form, prefix, action === 'enable-all');
    };
  });
}

function buildPlanPayload(form, prefix) {
  const fd = new FormData(form);
  const enabledRevenue = fd.get(`${prefix}_enable_revenue`) === "on";
  const enabledProfit = fd.get(`${prefix}_enable_profit`) === "on";
  const enabledRevenuePerAssigned = fd.get(`${prefix}_enable_revenue_per_assigned`) === "on";
  const enabledAssigned = fd.get(`${prefix}_enable_assigned_user_target`) === "on";
  const enabledDayMeta = fd.get(`${prefix}_enable_day_meta`) === "on";
  return {
    revenue_plan_minor: enabledRevenue ? parseMoneyToMinor(fd.get(`${prefix}_revenue_plan`)) : null,
    profit_plan_minor: enabledProfit ? parseMoneyToMinor(fd.get(`${prefix}_profit_plan`)) : null,
    revenue_per_assigned_plan_minor: enabledRevenuePerAssigned ? parseMoneyToMinor(fd.get(`${prefix}_revenue_per_assigned_plan`)) : null,
    assigned_user_target: enabledAssigned ? (fd.get(`${prefix}_assigned_user_target`) ? Number(fd.get(`${prefix}_assigned_user_target`)) : 0) : null,
    day_kind: enabledDayMeta ? String(fd.get(`${prefix}_day_kind`) || '').toUpperCase() || null : null,
    title: enabledDayMeta ? String(fd.get(`${prefix}_title`) || '').trim() || null : null,
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
  const kind = dayKindLabel(plan?.day_kind);
  const title = String(plan?.title || '').trim();
  const parts = [];
  if (kind) parts.push(kind);
  if (title) parts.push(title);
  if (plan?.notes) parts.push(plan.notes);
  setText("effectivePlanUsage", usageInlineText(plan, { empty: 'Этот источник пока не используется в повышенном проценте.' }));
  setText("effectivePlanNotes", parts.length ? parts.join(" · ") : "Без комментария.");
}

function renderMonthPlan(plan) {
  setText("monthPlanBadge", plan?.template_month_title || state.month || "—");
  setText("monthPlanHint", plan?.notes || "Этот план применяется ко всем дням выбранного месяца, если на дату нет override.");
  setText("monthPlanUsage", usageInlineText(plan, { empty: 'Месячный план заведения пока не участвует в повышенном проценте.' }));
  const form = document.getElementById("monthPlanForm");
  if (!form) return;
  form.innerHTML = planFormHtml("month", "План на месяц", `Шаблон для ${plan?.template_month_title || state.month}`, plan) + `<div class="row gap-8 mt-12"><button class="btn" type="submit">Сохранить план месяца</button></div>`;
  bindToggleDisable(form, "month");
  form.style.display = state.access.canManage ? "" : "none";
  form.onsubmit = saveMonthPlan;
}

function renderDepartmentMonthPlans(payload) {
  const form = document.getElementById('departmentMonthPlansForm');
  if (!form) return;
  form.innerHTML = departmentPlansTableHtml('dept_month', payload, { canManage: state.access.canManage });
  form.style.display = '';
  form.onsubmit = saveDepartmentMonthPlans;
}

function renderDepartmentDayPlans(payload) {
  const form = document.getElementById('departmentDayPlansForm');
  const badge = document.getElementById('departmentDayPlansBadge');
  if (badge) badge.textContent = payload?.date || state.date || '—';
  if (!form) return;
  form.innerHTML = departmentPlansTableHtml('dept_day', payload, { canManage: state.access.canManage });
  form.style.display = '';
  form.onsubmit = saveDepartmentDayPlans;
}

function renderOverride(plan) {
  const hasValues = plan?.revenue_plan_minor != null || plan?.profit_plan_minor != null || plan?.revenue_per_assigned_plan_minor != null || plan?.assigned_user_target != null || !!plan?.day_kind || !!plan?.title;
  setText("overrideBadge", hasValues ? (dayKindLabel(plan?.day_kind) || "Заполнен") : "Не задан");
  const form = document.getElementById("planOverrideForm");
  if (!form) return;
  form.innerHTML = planFormHtml("override", "Override на дату", `Для ${state.date} можно задать отдельный план.`, plan, { includeDayMeta: true }) + `<div class="row gap-8 mt-12"><button class="btn" type="submit">Сохранить override</button></div>`;
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
        <div class="row gap-8 mt-12"><button class="btn" type="submit">Сохранить шаблон</button><button class="btn ghost" type="button" data-copy-template="${weekday}">Скопировать этот шаблон</button></div>
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
    form.querySelectorAll('[data-copy-template]').forEach((btn) => {
      btn.onclick = () => openCopyFromWeekday(weekday);
    });
  });
  renderWeekdayCopyControls();
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

function openCopyFromWeekday(weekday) {
  const form = document.getElementById('weekdayCopyForm');
  if (!form) return;
  form.elements.namedItem('source_weekday').value = String(weekday);
  syncWeekdayCopyTargets();
  const card = document.getElementById('weekdayCopyCard');
  if (card?.scrollIntoView) card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderWeekdayCopyControls() {
  const form = document.getElementById('weekdayCopyForm');
  if (!form) return;
  const source = form.elements.namedItem('source_weekday');
  if (source && !source.options.length) source.innerHTML = templateOptionsHtml(0);
  const wrap = document.getElementById('weekdayCopyCustomTargets');
  if (wrap && !wrap.innerHTML.trim()) wrap.innerHTML = customTargetsHtml();
  const targetGroup = form.elements.namedItem('target_group');
  if (targetGroup && !targetGroup._bound) {
    targetGroup.addEventListener('change', syncWeekdayCopyTargets);
    targetGroup._bound = true;
  }
  syncWeekdayCopyTargets();
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
  const [effectivePlan, overridePlan, monthPlan, templates, departmentMonthPlans, departmentDayPlans] = await Promise.all([
    api(`/venues/${encodeURIComponent(venueId)}/economics/plan?date=${encodeURIComponent(state.date)}`),
    api(`/venues/${encodeURIComponent(venueId)}/economics/plan/override?date=${encodeURIComponent(state.date)}`),
    api(`/venues/${encodeURIComponent(venueId)}/economics/plan-month?month=${encodeURIComponent(state.month)}`),
    api(`/venues/${encodeURIComponent(venueId)}/economics/plan-templates`),
    api(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-month?month=${encodeURIComponent(state.month)}`),
    api(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-day?date=${encodeURIComponent(state.date)}`),
  ]);
  state.effectivePlan = effectivePlan || {};
  state.overridePlan = overridePlan || {};
  state.monthPlan = monthPlan || {};
  state.templates = Array.isArray(templates) ? templates : [];
  state.departmentMonthPlans = departmentMonthPlans || { items: [] };
  state.departmentDayPlans = departmentDayPlans || { items: [] };
  renderEffective(state.effectivePlan);
  renderMonthPlan(state.monthPlan);
  renderDepartmentMonthPlans(state.departmentMonthPlans);
  renderDepartmentDayPlans(state.departmentDayPlans);
  syncDepartmentDayQuickControls();
  renderOverride(state.overridePlan);
  renderTemplates(state.templates);
}

async function copyPreviousMonthPlan() {
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const result = await api(`/venues/${encodeURIComponent(venueId)}/economics/plan-month/copy-previous?month=${encodeURIComponent(state.month)}&overwrite=true`, {
      method: 'POST',
    });
    toast(result?.copied ? `План скопирован из ${result?.copied_from_month}` : 'План уже существовал и не был изменён', 'ok');
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || 'Не удалось скопировать прошлый месяц', 'err');
  }
}

async function copyWeekdayTemplates(event) {
  event.preventDefault();
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const fd = new FormData(event.currentTarget);
    const group = String(fd.get('target_group') || 'WORKDAYS').toUpperCase();
    const targets = group === 'CUSTOM' ? selectedCopyWeekdays(event.currentTarget) : (TARGET_GROUPS[group] || TARGET_GROUPS.WORKDAYS);
    const result = await api(`/venues/${encodeURIComponent(venueId)}/economics/plan-templates/copy`, {
      method: 'POST',
      body: {
        source_weekday: Number(fd.get('source_weekday') || 0),
        target_weekdays: targets,
        overwrite: fd.get('overwrite') === 'on',
      },
    });
    const hint = document.getElementById('weekdayCopyHint');
    if (hint) {
      hint.textContent = `Скопировано: ${result?.copied_count || 0}. Пропущено: ${result?.skipped_count || 0}.`;
    }
    toast(`Скопировано: ${result?.copied_count || 0}`, 'ok');
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || 'Не удалось скопировать шаблоны', 'err');
  }
}

async function quickCopyMondayToWeekdays() {
  const form = document.getElementById('weekdayCopyForm');
  if (!form) return;
  form.elements.namedItem('source_weekday').value = '0';
  form.elements.namedItem('target_group').value = 'WORKDAYS';
  const overwrite = form.elements.namedItem('overwrite');
  if (overwrite) overwrite.checked = true;
  syncWeekdayCopyTargets();
  await copyWeekdayTemplates({ preventDefault() {}, currentTarget: form });
}

async function saveDepartmentMonthPlans(event) {
  event.preventDefault();
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const payload = buildDepartmentPlanPayload(event.currentTarget, 'dept_month');
    await api(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-month?month=${encodeURIComponent(state.month)}`, {
      method: 'PUT',
      body: payload,
    });
    toast('Планы департаментов на месяц сохранены', 'ok');
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || 'Не удалось сохранить планы департаментов', 'err');
  }
}

async function saveDepartmentDayPlans(event) {
  event.preventDefault();
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const payload = buildDepartmentPlanPayload(event.currentTarget, 'dept_day');
    await api(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-day?date=${encodeURIComponent(state.date)}`, {
      method: 'PUT',
      body: payload,
    });
    toast('Планы департаментов на дату сохранены', 'ok');
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || 'Не удалось сохранить планы департаментов на дату', 'err');
  }
}

async function autofillDepartmentMonthPlans() {
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const result = await api(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-month/autofill-from-last-month?month=${encodeURIComponent(state.month)}&overwrite=true`, { method: 'POST' });
    toast(`Заполнено из ${result?.copied_from_month || 'прошлого месяца'}`, 'ok');
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || 'Не удалось заполнить планы из прошлого месяца', 'err');
  }
}

async function distributeDepartmentMonthPlans() {
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const result = await api(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-month/distribute-from-venue-plan?month=${encodeURIComponent(state.month)}&overwrite=true`, { method: 'POST' });
    toast(`Распределено: ${fmtMoneyMinor(result?.distributed_total_minor)}`, 'ok');
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || 'Не удалось распределить план заведения', 'err');
  }
}

async function copyDepartmentDayPlansFromDate() {
  if (!state.access.canManage) return;
  const sourceInput = document.getElementById('departmentDayCopyFromDate');
  const sourceDate = String(sourceInput?.value || '').trim();
  if (!sourceDate) {
    toast('Выбери дату-источник', 'warn');
    return;
  }
  try {
    const venueId = getVenueId();
    const result = await api(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-day/copy-from-date?source_date=${encodeURIComponent(sourceDate)}&target_date=${encodeURIComponent(state.date)}&overwrite=true`, { method: 'POST' });
    toast(`Скопировано: ${result?.copied || 0}`, 'ok');
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || 'Не удалось скопировать планы с даты', 'err');
  }
}

async function autofillDepartmentDayPlansFromHistory(mode = 'SAME_WEEKDAY_AVG') {
  if (!state.access.canManage) return;
  try {
    const venueId = getVenueId();
    const result = await api(`/venues/${encodeURIComponent(venueId)}/economics/department-plan-day/autofill-from-history?target_date=${encodeURIComponent(state.date)}&mode=${encodeURIComponent(mode)}&overwrite=true&lookback_weeks=4`, { method: 'POST' });
    const label = mode === 'PREVIOUS_WEEK' ? 'прошлой недели' : mode === 'PREVIOUS_DAY' ? 'вчера' : 'похожих дней';
    toast(`Автозаполнено из ${label}: ${result?.copied || 0}`, 'ok');
    await loadData();
  } catch (err) {
    toast(err?.data?.detail || err.message || 'Не удалось автозаполнить планы на дату', 'err');
  }
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
      syncDepartmentDayQuickControls();
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
  const copyPrevBtn = document.getElementById('copyPrevMonthPlanBtn');
  if (copyPrevBtn) copyPrevBtn.onclick = () => { copyPreviousMonthPlan(); };
  const copyMondayBtn = document.getElementById('copyMondayToWeekdaysBtn');
  if (copyMondayBtn) copyMondayBtn.onclick = () => { quickCopyMondayToWeekdays(); };
  const deptAutofillBtn = document.getElementById('deptAutofillMonthBtn');
  if (deptAutofillBtn) deptAutofillBtn.onclick = () => { autofillDepartmentMonthPlans(); };
  const deptDistributeBtn = document.getElementById('deptDistributeMonthBtn');
  if (deptDistributeBtn) deptDistributeBtn.onclick = () => { distributeDepartmentMonthPlans(); };
  const deptCopyDayBtn = document.getElementById('deptCopyDayBtn');
  if (deptCopyDayBtn) deptCopyDayBtn.onclick = () => { copyDepartmentDayPlansFromDate(); };
  const deptFillPrevWeekBtn = document.getElementById('deptFillPrevWeekBtn');
  if (deptFillPrevWeekBtn) deptFillPrevWeekBtn.onclick = () => { autofillDepartmentDayPlansFromHistory('PREVIOUS_WEEK'); };
  const deptFillAvgWeekdayBtn = document.getElementById('deptFillAvgWeekdayBtn');
  if (deptFillAvgWeekdayBtn) deptFillAvgWeekdayBtn.onclick = () => { autofillDepartmentDayPlansFromHistory('SAME_WEEKDAY_AVG'); };
  const weekdayCopyForm = document.getElementById('weekdayCopyForm');
  if (weekdayCopyForm) weekdayCopyForm.addEventListener('submit', copyWeekdayTemplates);

  await loadData();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
  getVenueMembers,
  getDepartments,
  getKpiMetrics,
  getPayProfile,
  updatePayProfile,
  createPayProfileAssignment,
  updatePayProfileAssignment,
  deletePayProfileAssignment,
  createPayComponent,
  updatePayComponent,
  deletePayComponent,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

const root = document.getElementById("root");

const COMPONENT_LABELS = {
  SALARY_FIXED_MONTH: "Оклад за месяц",
  SALARY_HOURLY: "Почасовая ставка",
  SALARY_PER_SHIFT: "Фикс за смену",
  PERCENT_TOTAL_REVENUE: "% от общей выручки",
  PERCENT_DEPARTMENT_REVENUE: "% от выручки департамента",
  KPI_BONUS: "KPI-бонус",
};

const BASE_SCOPE_LABELS = {
  FULL_PERIOD: "по всему периоду",
  WORKED_DATES: "по отработанным дням",
};

const BOOST_SOURCE_LABELS = {
  NONE: "без условия",
  VENUE_MONTH_PLAN: "месячный план заведения",
  VENUE_DAY_PLAN: "суточный план заведения",
  DEPARTMENT_MONTH_PLAN: "месячный план департамента",
  DEPARTMENT_DAY_PLAN: "суточный план департамента",
  KPI_METRIC: "KPI",
};

const BOOST_RECALC_LABELS = {
  REPLACE_ALL: "весь объём",
  EXCESS_ONLY: "только превышение",
};

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseParams() {
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || "";
  const profileId = params.get("profile_id") || "";
  if (venueId) setActiveVenueId(venueId);
  return { venueId, profileId };
}

function fmtMoneyMinor(minor) {
  const value = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";
  } catch {
    return value.toFixed(2) + " ₽";
  }
}

function fmtPercentBps(bps) {
  const value = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + "%";
  } catch {
    return value.toFixed(2) + "%";
  }
}

function percentInputFromBps(bps) {
  const value = Number(bps || 0) / 100;
  return Number.isFinite(value) ? String(value).replace(/\.0+$/, "") : "";
}

function moneyInputFromMinor(minor) {
  if (minor == null || minor === "") return "";
  const value = Number(minor) / 100;
  if (!Number.isFinite(value)) return "";
  return String(value).replace(/\.0+$/, "");
}

function parseMoneyRubToMinor(value) {
  const normalized = String(value || "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!normalized) return null;
  const num = Number(normalized);
  if (!Number.isFinite(num) || num < 0) return null;
  return Math.round(num * 100);
}

function parsePercentInputToBps(value) {
  const normalized = String(value || "").trim().replace(",", ".");
  if (!normalized) return null;
  const num = Number(normalized);
  if (!Number.isFinite(num) || num < 0) return null;
  return Math.round(num * 100);
}

function departmentTitleFor(item) {
  const direct = item?.department_title || item?.department?.title;
  if (direct) return direct;
  const depId = Number(item?.department_id || 0);
  if (!depId) return null;
  const found = (state.departments || []).find((d) => Number(d?.id) === depId);
  return found?.title || "Департамент";
}

function kpiMetricTitleFor(item) {
  const direct = item?.kpi_metric_title || item?.kpi_metric?.title;
  if (direct) return direct;
  const metricId = Number(item?.kpi_metric_id || 0);
  if (!metricId) return null;
  const found = (state.kpiMetrics || []).find((m) => Number(m?.id) === metricId);
  return found?.title || "KPI";
}


function effectiveBaseScopeFor(item) {
  return String(item?.effective_base_scope || item?.base_scope || (String(item?.component_type || '').toUpperCase() === 'PERCENT_DEPARTMENT_REVENUE' ? 'WORKED_DATES' : 'FULL_PERIOD')).toUpperCase();
}

function effectiveBoostSourceFor(item) {
  return String(item?.effective_boost_source_type || item?.boost_source_type || 'NONE').toUpperCase();
}

function effectiveBoostRecalcModeFor(item) {
  return String(item?.effective_boost_recalc_mode || item?.boost_recalc_mode || 'REPLACE_ALL').toUpperCase();
}

function baseScopeLabel(scope) {
  return BASE_SCOPE_LABELS[String(scope || '').toUpperCase()] || String(scope || '');
}

function boostSourceLabel(source) {
  return BOOST_SOURCE_LABELS[String(source || '').toUpperCase()] || String(source || '');
}

function boostRecalcLabel(mode) {
  return BOOST_RECALC_LABELS[String(mode || '').toUpperCase()] || String(mode || '');
}

function formatPercentConfig(item) {
  const parts = [];
  parts.push(fmtPercentBps(item.percent_bps));
  const scope = baseScopeLabel(effectiveBaseScopeFor(item));
  if (scope) parts.push(scope);
  if (item.minimum_guarantee_minor != null) parts.push(`мин ${fmtMoneyMinor(item.minimum_guarantee_minor)}`);
  if (item.maximum_cap_minor != null) parts.push(`потолок ${fmtMoneyMinor(item.maximum_cap_minor)}`);
  if (item.boost_enabled && item.boost_percent_bps != null) {
    const sourceLabel = boostSourceLabel(effectiveBoostSourceFor(item));
    const modeLabel = boostRecalcLabel(effectiveBoostRecalcModeFor(item));
    const boostBits = [`boost ${fmtPercentBps(item.boost_percent_bps)}`];
    if (sourceLabel) boostBits.push(sourceLabel);
    if (modeLabel) boostBits.push(modeLabel);
    if (item.boost_department_title) boostBits.push(item.boost_department_title);
    if (item.boost_kpi_metric_title) boostBits.push(item.boost_kpi_metric_title);
    if (item.boost_threshold_value != null && String(effectiveBoostSourceFor(item)) === 'KPI_METRIC') {
      boostBits.push(`цель ${item.boost_threshold_value}`);
    }
    parts.push(boostBits.join(' · '));
  }
  return parts.join(' · ');
}

function percentBoostOptions(selected) {
  const value = String(selected || 'NONE').toUpperCase();
  return [
    ['NONE', 'Без условия'],
    ['VENUE_MONTH_PLAN', 'Месячный план заведения'],
    ['VENUE_DAY_PLAN', 'Суточный план заведения'],
    ['DEPARTMENT_MONTH_PLAN', 'Месячный план департамента'],
    ['DEPARTMENT_DAY_PLAN', 'Суточный план департамента'],
    ['KPI_METRIC', 'KPI'],
  ].map(([code, title]) => `<option value="${code}" ${value === code ? 'selected' : ''}>${title}</option>`).join('');
}

function baseScopeOptions(selected, componentType) {
  const type = String(componentType || '').toUpperCase();
  const fallback = type === 'PERCENT_DEPARTMENT_REVENUE' ? 'WORKED_DATES' : 'FULL_PERIOD';
  const value = String(selected || fallback).toUpperCase();
  return [
    ['FULL_PERIOD', 'По всему периоду'],
    ['WORKED_DATES', 'По отработанным дням'],
  ].map(([code, title]) => `<option value="${code}" ${value === code ? 'selected' : ''}>${title}</option>`).join('');
}

function boostRecalcOptions(selected) {
  const value = String(selected || 'REPLACE_ALL').toUpperCase();
  return [
    ['REPLACE_ALL', 'Весь объём по повышенному %'],
    ['EXCESS_ONLY', 'Только превышение по повышенному %'],
  ].map(([code, title]) => `<option value="${code}" ${value === code ? 'selected' : ''}>${title}</option>`).join('');
}

function isDepartmentBoostSource(sourceType) {
  const value = String(sourceType || '').toUpperCase();
  return value === 'DEPARTMENT_MONTH_PLAN' || value === 'DEPARTMENT_DAY_PLAN';
}

function defaultBoostSourceForType(componentType) {
  return String(componentType || '').toUpperCase() === 'PERCENT_DEPARTMENT_REVENUE' ? 'DEPARTMENT_MONTH_PLAN' : 'VENUE_MONTH_PLAN';
}

function applyPercentSmartDefaults() {
  const type = String(document.getElementById('f_component_type')?.value || '').toUpperCase();
  if (type !== 'PERCENT_TOTAL_REVENUE' && type !== 'PERCENT_DEPARTMENT_REVENUE') return;
  const boostEnabled = !!document.getElementById('f_boost_enabled')?.checked;
  const boostSourceEl = document.getElementById('f_boost_source_type');
  const departmentEl = document.getElementById('f_department_id');
  const boostDepartmentEl = document.getElementById('f_boost_department_id');
  const boostKpiMetricEl = document.getElementById('f_boost_kpi_metric_id');
  const baseScopeEl = document.getElementById('f_base_scope');

  if (baseScopeEl && !String(baseScopeEl.value || '').trim()) {
    baseScopeEl.value = type === 'PERCENT_DEPARTMENT_REVENUE' ? 'WORKED_DATES' : 'FULL_PERIOD';
  }
  if (boostEnabled && boostSourceEl && (!String(boostSourceEl.value || '').trim() || String(boostSourceEl.value).toUpperCase() === 'NONE')) {
    boostSourceEl.value = defaultBoostSourceForType(type);
  }
  if (boostSourceEl && isDepartmentBoostSource(boostSourceEl.value) && boostDepartmentEl && !String(boostDepartmentEl.value || '').trim() && String(departmentEl?.value || '').trim()) {
    boostDepartmentEl.value = String(departmentEl.value || '');
  }
  if (boostSourceEl && String(boostSourceEl.value || '').toUpperCase() === 'KPI_METRIC' && boostKpiMetricEl && !String(boostKpiMetricEl.value || '').trim() && Array.isArray(state.kpiMetrics) && state.kpiMetrics.length) {
    boostKpiMetricEl.value = String(state.kpiMetrics[0].id);
  }
}

function syncComponentConfigHint() {
  const box = document.getElementById('f_config_hint');
  if (!box) return;
  const type = String(document.getElementById('f_component_type')?.value || '').toUpperCase();
  const warnings = [];
  const infos = [];
  if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
    const percentBps = parsePercentInputToBps(document.getElementById('f_percent')?.value || '') || 0;
    const boostEnabled = !!document.getElementById('f_boost_enabled')?.checked;
    const boostBps = parsePercentInputToBps(document.getElementById('f_boost_percent')?.value || '') || 0;
    const boostSourceType = String(document.getElementById('f_boost_source_type')?.value || 'NONE').toUpperCase();
    const recalcMode = String(document.getElementById('f_boost_recalc_mode')?.value || 'REPLACE_ALL').toUpperCase();
    const baseScope = String(document.getElementById('f_base_scope')?.value || '').toUpperCase();
    const minMinor = parseMoneyRubToMinor(document.getElementById('f_minimum_guarantee_minor')?.value || '');
    const maxMinor = parseMoneyRubToMinor(document.getElementById('f_maximum_cap_minor')?.value || '');
    const boostDepartmentId = String(document.getElementById('f_boost_department_id')?.value || '').trim();

    infos.push('Процентные компоненты считаются только по закрытым отчётам.');
    if (baseScope === 'WORKED_DATES') infos.push('База будет собрана только по дням, когда сотрудник реально работал.');
    if (baseScope === 'FULL_PERIOD') infos.push('База будет собрана по всему выбранному периоду, даже если сотрудник работал не каждый день.');

    if (boostEnabled && percentBps > 0 && boostBps > 0 && boostBps < percentBps) {
      warnings.push('Повышенный процент сейчас меньше базового — проверь настройки.');
    }
    if (minMinor != null && maxMinor != null && minMinor > maxMinor) {
      warnings.push('Минимальная гарантия больше максимума — сохранить такой компонент не получится.');
    }
    if (boostEnabled && (!boostSourceType || boostSourceType === 'NONE')) {
      warnings.push('Включено повышение, но не выбрано условие.');
    }
    if (isDepartmentBoostSource(boostSourceType) && !boostDepartmentId) {
      warnings.push('Для плана департамента нужно выбрать департамент в блоке условия повышения.');
    }
    if (type === 'PERCENT_TOTAL_REVENUE' && isDepartmentBoostSource(boostSourceType)) {
      warnings.push('Процент считается от общей выручки, а условие повышения — по департаменту. Это допустимо, но проверь, что именно так и задумано.');
    }
    if (boostSourceType === 'KPI_METRIC' && recalcMode === 'EXCESS_ONLY') {
      warnings.push('Для KPI режим «только превышение» всё равно считается как полный пересчёт по повышенному %.');
    }
  }
  const parts = [];
  if (warnings.length) {
    parts.push(`<div class="form-note form-note--warn">${warnings.map((msg) => `<div>${esc(msg)}</div>`).join('')}</div>`);
  }
  if (infos.length) {
    parts.push(`<div class="form-note form-note--info">${infos.map((msg) => `<div>${esc(msg)}</div>`).join('')}</div>`);
  }
  box.innerHTML = parts.join('');
  box.style.display = parts.length ? 'grid' : 'none';
}

function normalizeStepsForForm(steps) {
  if (!Array.isArray(steps)) return [];
  return steps
    .map((step) => ({
      threshold_value: step?.threshold_value ?? "",
      amount_rub: moneyInputFromMinor(step?.amount_minor),
      title: step?.title || "",
    }))
    .filter((step) => String(step.threshold_value).trim() !== "" || String(step.amount_rub).trim() !== "" || String(step.title).trim() !== "");
}

function stepsRowsMarkup(steps) {
  const normalized = normalizeStepsForForm(steps);
  const rows = normalized.length ? normalized : [{ threshold_value: "", amount_rub: "", title: "" }];
  return rows.map((step, idx) => `
    <div class="kpi-step-row" data-step-row>
      <label>
        <span>Порог</span>
        <input data-step-threshold inputmode="numeric" placeholder="Например: 10" value="${esc(step.threshold_value ?? "")}" />
      </label>
      <label>
        <span>Бонус, ₽</span>
        <input data-step-amount inputmode="decimal" placeholder="Например: 500" value="${esc(step.amount_rub ?? "")}" />
      </label>
      <label>
        <span>Подпись</span>
        <input data-step-title placeholder="Например: серебро" value="${esc(step.title ?? "")}" />
      </label>
      <div class="kpi-step-row__actions">
        <button class="btn sm danger" type="button" data-remove-step ${rows.length === 1 ? "disabled" : ""}>Удалить</button>
      </div>
    </div>
  `).join("");
}

function wireStepsBuilder() {
  const container = document.getElementById("f_steps_rows");
  const addBtn = document.getElementById("btnAddStep");
  if (!container) return;

  const refreshRemoveButtons = () => {
    const buttons = Array.from(container.querySelectorAll("[data-remove-step]"));
    buttons.forEach((btn) => { btn.disabled = buttons.length <= 1; });
  };

  const addRow = (step = { threshold_value: "", amount_rub: "", title: "" }) => {
    const wrap = document.createElement("div");
    wrap.innerHTML = stepsRowsMarkup([step]).trim();
    const row = wrap.firstElementChild;
    if (!row) return;
    row.querySelector("[data-remove-step]")?.addEventListener("click", () => {
      row.remove();
      refreshRemoveButtons();
    });
    container.appendChild(row);
    refreshRemoveButtons();
  };

  Array.from(container.querySelectorAll("[data-remove-step]")).forEach((btn) => {
    btn.addEventListener("click", () => {
      btn.closest("[data-step-row]")?.remove();
      refreshRemoveButtons();
    });
  });

  addBtn?.addEventListener("click", () => addRow());
  refreshRemoveButtons();
}

function readStepsBuilder() {
  const rows = Array.from(document.querySelectorAll("#f_steps_rows [data-step-row]"));
  const out = [];
  for (const row of rows) {
    const thresholdRaw = String(row.querySelector("[data-step-threshold]")?.value || "").trim();
    const amountRaw = String(row.querySelector("[data-step-amount]")?.value || "").trim();
    const titleRaw = String(row.querySelector("[data-step-title]")?.value || "").trim();
    if (!thresholdRaw && !amountRaw && !titleRaw) continue;
    const thresholdValue = Number(thresholdRaw);
    const amountMinor = parseMoneyRubToMinor(amountRaw);
    if (!Number.isFinite(thresholdValue) || thresholdValue < 0 || !Number.isInteger(thresholdValue)) {
      return false;
    }
    if (amountMinor == null) {
      return false;
    }
    const step = { threshold_value: thresholdValue, amount_minor: amountMinor };
    if (titleRaw) step.title = titleRaw;
    out.push(step);
  }
  out.sort((a, b) => Number(a.threshold_value || 0) - Number(b.threshold_value || 0));
  return out;
}

function memberName(member) {
  if (!member) return "—";
  return member.display_name || member.short_name || member.full_name || (member.tg_username ? `@${member.tg_username}` : "—");
}

let state = {
  venueId: "",
  profileId: "",
  me: null,
  perms: null,
  can: { view: false, manage: false },
  profile: null,
  members: [],
  departments: [],
  kpiMetrics: [],
};

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Профиль зарплаты</b>
          <div class="muted" id="subtitle">компоненты и назначения</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="itemcard">
        <div class="section-head">
          <div class="section-title">
            <b id="profileTitle">—</b>
            <div class="muted mt-6" id="profileDescription">—</div>
          </div>
          <div class="section-actions">
            <button class="btn" id="btnEditProfile">Редактировать</button>
          </div>
        </div>
        <div class="muted mt-8" id="profileMeta">—</div>
      </div>

      <div class="grid grid2 mt-12">
        <div class="itemcard">
          <div class="section-head">
            <div class="section-title"><b>Компоненты</b></div>
            <div class="section-actions"><button class="btn primary" id="btnAddComponent">+ Добавить</button></div>
          </div>
          <div class="muted mt-6">Доступны: оклад, почасовая ставка, фикс за смену, проценты по выручке и KPI-бонусы по закрытым отчётам.</div>
          <div id="componentsList" class="mt-12"><div class="skeleton"></div></div>
        </div>

        <div class="itemcard">
          <div class="section-head">
            <div class="section-title"><b>Назначения</b></div>
            <div class="section-actions"><button class="btn primary" id="btnAddAssignment">+ Назначить</button></div>
          </div>
          <div class="muted mt-6">Назначения определяют, какой профиль действует у сотрудника в выбранный период.</div>
          <div id="assignmentsList" class="mt-12"><div class="skeleton"></div></div>
        </div>
      </div>

      <div class="row mt-12" style="justify-content:space-between; gap:12px; flex-wrap:wrap;">
        <a class="btn subtle inline" id="backProfiles" href="#">← К списку профилей</a>
        <a class="btn subtle inline" id="openPayroll" href="#">Открыть начисления →</a>
      </div>
    </div>

    <div id="toast" class="toast"><div class="toast__text"></div></div>

    <div id="modal" class="modal">
      <div class="modal__backdrop"></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div class="modal__title">Подтверждение</div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body"></div>
      </div>
    </div>

    <div id="editModal" class="modal">
      <div class="modal__backdrop" data-close></div>
      <div class="modal__panel modal__panel--wide">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="editTitle">Редактирование</b>
            <div class="muted" id="editHint" style="margin-top:4px; font-size:12px"></div>
          </div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body" id="editBody"></div>
      </div>
    </div>

    <div class="nav"><div class="wrap"><div id="nav"></div></div></div>
  `;

  mountCommonUI("none");
}

function computeCaps(perms, me) {
  const role = roleUpper(perms);
  const pset = permSetFromResponse(perms);
  const sysRole = String(me?.system_role || "").toUpperCase();
  const isOwner = role === "OWNER" || role === "VENUE_OWNER";
  const isAdmin = sysRole === "SUPER_ADMIN" || sysRole === "MODERATOR";
  return {
    view: isOwner || isAdmin || hasPerm(pset, "PAY_PROFILES_VIEW") || hasPerm(pset, "PAY_PROFILES_MANAGE"),
    manage: isOwner || isAdmin || hasPerm(pset, "PAY_PROFILES_MANAGE"),
  };
}

function closeEditModal() {
  document.getElementById("editModal")?.classList.remove("open");
}

function openEditModal({ title, hint, bodyHtml }) {
  const modal = document.getElementById("editModal");
  const titleEl = document.getElementById("editTitle");
  const hintEl = document.getElementById("editHint");
  const bodyEl = document.getElementById("editBody");
  if (titleEl) titleEl.textContent = title || "Редактирование";
  if (hintEl) hintEl.textContent = hint || "";
  if (bodyEl) bodyEl.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function wireEditModalClose() {
  const m = document.getElementById("editModal");
  if (!m) return;
  m.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeEditModal));
}

function renderHeader() {
  const p = state.profile;
  document.getElementById("title").textContent = p?.title || "Профиль зарплаты";
  document.getElementById("subtitle").textContent = p?.description || "компоненты и назначения";
  document.getElementById("profileTitle").textContent = p?.title || "—";
  document.getElementById("profileDescription").textContent = p?.description || "Без описания";
  document.getElementById("profileMeta").textContent = `${p?.is_active ? "Активный профиль" : "Профиль выключен"} · Компонентов: ${Number(p?.components?.length || 0)} · Назначений: ${Number(p?.assignments?.length || 0)}`;
  document.getElementById("backProfiles").href = `/owner-pay-profiles.html?venue_id=${encodeURIComponent(state.venueId)}`;
  document.getElementById("openPayroll").href = `/owner-payroll.html?venue_id=${encodeURIComponent(state.venueId)}`;
  document.getElementById("btnEditProfile").style.display = state.can.manage ? "" : "none";
  document.getElementById("btnAddComponent").style.display = state.can.manage ? "" : "none";
  document.getElementById("btnAddAssignment").style.display = state.can.manage ? "" : "none";
}

function componentStepsPreview(item) {
  const steps = Array.isArray(item?.steps) ? item.steps : [];
  if (!steps.length) return "";
  return `<div class="kpi-step-chips">${steps.map((step) => `<span class="kpi-step-chip">от ${esc(step.threshold_value)} → ${esc(fmtMoneyMinor(step.amount_minor || 0))}${step?.title ? ` · ${esc(step.title)}` : ""}</span>`).join("")}</div>`;
}

function componentSubtitle(item) {
  const type = String(item?.component_type || "").toUpperCase();
  if (type === "SALARY_FIXED_MONTH") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.amount_minor)}`;
  if (type === "SALARY_HOURLY") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.rate_minor)} / час`;
  if (type === "SALARY_PER_SHIFT") return `${COMPONENT_LABELS[type]} · ${fmtMoneyMinor(item.amount_minor)} / смена`;
  if (type === "PERCENT_TOTAL_REVENUE") return `${COMPONENT_LABELS[type]} · ${formatPercentConfig(item)}`;
  if (type === "PERCENT_DEPARTMENT_REVENUE") {
    const depTitle = departmentTitleFor(item);
    return `${COMPONENT_LABELS[type]} · ${formatPercentConfig(item)}${depTitle ? ` · ${depTitle}` : ""}`;
  }
  if (type === "KPI_BONUS") {
    const metricTitle = kpiMetricTitleFor(item);
    const threshold = item.threshold_value != null ? ` · порог ${item.threshold_value}` : "";
    const stepsCount = Array.isArray(item.steps) && item.steps.length ? ` · ступеней: ${item.steps.length}` : "";
    return `${COMPONENT_LABELS[type]}${metricTitle ? ` · ${metricTitle}` : ""}${threshold}${stepsCount}${item.amount_minor != null ? ` · ${fmtMoneyMinor(item.amount_minor)}` : ""}`;
  }
  return `${type} · ${fmtMoneyMinor(item.amount_minor || item.rate_minor || 0)}`;
}

function renderComponents() {
  const el = document.getElementById("componentsList");
  if (!el) return;
  if (!state.can.view) {
    el.innerHTML = `<div class="muted">Нет доступа</div>`;
    return;
  }
  const items = Array.isArray(state.profile?.components) ? state.profile.components : [];
  if (!items.length) {
    el.innerHTML = `<div class="muted">Компоненты ещё не добавлены</div>`;
    return;
  }
  el.innerHTML = "";
  items.forEach((it) => {
    const row = document.createElement("div");
    row.className = "listrow";
    row.innerHTML = `
      <div class="listrow__left">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
          <b>${esc(it.title)}</b>
          ${it.is_active ? "" : `<span class="badge">неактивен</span>`}
        </div>
        <div class="muted mt-6">${esc(COMPONENT_LABELS[String(it.component_type || "").toUpperCase()] || it.component_type || "Компонент")}</div>
        <div class="muted listrow__meta">${esc(componentSubtitle(it))}</div>
        ${String(it?.component_type || "").toUpperCase() === "KPI_BONUS" ? componentStepsPreview(it) : ""}
      </div>
      <div class="row row--nowrap" style="gap:8px; flex:0 0 auto;" id="componentActions_${it.id}"></div>
    `;
    const actions = row.querySelector(`#componentActions_${it.id}`);
    if (state.can.manage && actions) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn sm";
      editBtn.textContent = "Изменить";
      editBtn.onclick = () => openComponentEditor({ mode: "edit", item: it });
      actions.appendChild(editBtn);

      const toggleBtn = document.createElement("button");
      toggleBtn.className = "btn sm" + (it.is_active ? " danger" : "");
      toggleBtn.textContent = it.is_active ? "Отключить" : "Включить";
      toggleBtn.onclick = async () => {
        try {
          await updatePayComponent(state.venueId, it.id, { is_active: !it.is_active });
          toast("Компонент обновлён", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
        }
      };
      actions.appendChild(toggleBtn);

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn sm danger";
      deleteBtn.textContent = "Удалить";
      deleteBtn.onclick = async () => {
        const ok = await confirmModal({
          title: "Удалить компонент?",
          text: `Удалить компонент "${it.title}"?`,
          confirmText: "Удалить",
          danger: true,
        });
        if (!ok) return;
        try {
          await deletePayComponent(state.venueId, it.id);
          toast("Компонент удалён", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось удалить"), "err");
        }
      };
      actions.appendChild(deleteBtn);
    }
    el.appendChild(row);
  });
}

function renderAssignments() {
  const el = document.getElementById("assignmentsList");
  if (!el) return;
  if (!state.can.view) {
    el.innerHTML = `<div class="muted">Нет доступа</div>`;
    return;
  }
  const items = Array.isArray(state.profile?.assignments) ? state.profile.assignments : [];
  if (!items.length) {
    el.innerHTML = `<div class="muted">Назначений пока нет</div>`;
    return;
  }
  el.innerHTML = "";
  items.forEach((it) => {
    const label = memberName(it.member);
    const range = `${it.start_date || "без даты начала"} → ${it.end_date || "без даты окончания"}`;
    const row = document.createElement("div");
    row.className = "listrow";
    row.innerHTML = `
      <div class="listrow__left">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
          <b>${esc(label)}</b>
          ${it.is_active ? "" : `<span class="badge">неактивно</span>`}
        </div>
        <div class="mono listrow__meta">${esc(range)}</div>
      </div>
      <div class="row row--nowrap" style="gap:8px; flex:0 0 auto;" id="assignmentActions_${it.id}"></div>
    `;
    const actions = row.querySelector(`#assignmentActions_${it.id}`);
    if (state.can.manage && actions) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn sm";
      editBtn.textContent = "Изменить";
      editBtn.onclick = () => openAssignmentEditor({ mode: "edit", item: it });
      actions.appendChild(editBtn);

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn sm danger";
      deleteBtn.textContent = "Удалить";
      deleteBtn.onclick = async () => {
        const ok = await confirmModal({
          title: "Удалить назначение?",
          text: `Удалить назначение для ${label}?`,
          confirmText: "Удалить",
          danger: true,
        });
        if (!ok) return;
        try {
          await deletePayProfileAssignment(state.venueId, it.id);
          toast("Назначение удалено", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось удалить"), "err");
        }
      };
      actions.appendChild(deleteBtn);
    }
    el.appendChild(row);
  });
}


function kpiMetricUsageSuffix(metric) {
  const total = Number(metric?.usage_component_count || 0);
  const bonus = Number(metric?.usage_bonus_component_count || 0);
  const boost = Number(metric?.usage_boost_component_count || 0);
  if (!total) return '';
  const parts = [];
  if (bonus) parts.push(`бонус ${bonus}`);
  if (boost) parts.push(`boost ${boost}`);
  return ` · ${parts.join(' · ')}`;
}

function kpiMetricOptionLabel(metric) {
  const unit = String(metric?.unit || 'QTY').toUpperCase();
  return `${metric?.title || 'KPI'} · ${unit}${kpiMetricUsageSuffix(metric)}`;
}

function findKpiMetricById(value) {
  const id = Number(value || 0);
  return Array.isArray(state.kpiMetrics) ? state.kpiMetrics.find((metric) => Number(metric.id) === id) || null : null;
}

function syncComponentSummary() {
  const box = document.getElementById('f_live_summary');
  if (!box) return;
  const type = String(document.getElementById('f_component_type')?.value || '').toUpperCase();
  const typeTitle = COMPONENT_LABELS[type] || 'Компонент';
  const titleRaw = String(document.getElementById('f_title')?.value || '').trim();
  const amountMinor = parseMoneyRubToMinor(document.getElementById('f_amount_minor')?.value || '');
  const rateMinor = parseMoneyRubToMinor(document.getElementById('f_rate_minor')?.value || '');
  const percentBps = parsePercentInputToBps(document.getElementById('f_percent')?.value || '');
  const departmentId = Number(document.getElementById('f_department_id')?.value || 0);
  const department = Array.isArray(state.departments) ? state.departments.find((dep) => Number(dep.id) === departmentId) : null;
  const baseScope = String(document.getElementById('f_base_scope')?.value || '').toUpperCase();
  const boostEnabled = !!document.getElementById('f_boost_enabled')?.checked;
  const boostPercentBps = parsePercentInputToBps(document.getElementById('f_boost_percent')?.value || '');
  const boostSourceType = String(document.getElementById('f_boost_source_type')?.value || 'NONE').toUpperCase();
  const boostDepartmentId = Number(document.getElementById('f_boost_department_id')?.value || 0);
  const boostDepartment = Array.isArray(state.departments) ? state.departments.find((dep) => Number(dep.id) === boostDepartmentId) : null;
  const boostMetric = findKpiMetricById(document.getElementById('f_boost_kpi_metric_id')?.value);
  const kpiMetric = findKpiMetricById(document.getElementById('f_kpi_metric_id')?.value);
  const thresholdValue = String(document.getElementById('f_threshold_value')?.value || '').trim();
  const boostThresholdValue = String(document.getElementById('f_boost_threshold_value')?.value || '').trim();
  let heading = titleRaw || typeTitle;
  const bits = [];
  if (type === 'SALARY_FIXED_MONTH' || type === 'SALARY_PER_SHIFT') {
    if (amountMinor != null) bits.push(fmtMoneyMinor(amountMinor));
  } else if (type === 'SALARY_HOURLY') {
    if (rateMinor != null) bits.push(`${fmtMoneyMinor(rateMinor)} / час`);
  } else if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
    if (percentBps != null) bits.push(fmtPercentBps(percentBps));
    if (type === 'PERCENT_DEPARTMENT_REVENUE' && department?.title) bits.push(department.title);
    if (baseScope) bits.push(baseScopeLabel(baseScope));
    if (boostEnabled && boostPercentBps != null) {
      const boostBits = [`boost ${fmtPercentBps(boostPercentBps)}`];
      if (boostSourceType && boostSourceType !== 'NONE') boostBits.push(boostSourceLabel(boostSourceType));
      if (boostDepartment?.title) boostBits.push(boostDepartment.title);
      if (boostMetric?.title) boostBits.push(boostMetric.title);
      if (boostThresholdValue && boostSourceType === 'KPI_METRIC') boostBits.push(`цель ${boostThresholdValue}`);
      bits.push(boostBits.join(' · '));
    }
  } else if (type === 'KPI_BONUS') {
    if (kpiMetric?.title) bits.push(kpiMetric.title);
    if (thresholdValue) bits.push(`порог ${thresholdValue}`);
  }
  box.innerHTML = `
    <div class="pay-config-summary__eyebrow">Как будет работать компонент</div>
    <div class="pay-config-summary__title">${esc(heading)}</div>
    <div class="pay-config-summary__meta">${esc(bits.filter(Boolean).join(' · ') || 'Заполни поля — здесь появится краткая схема расчёта.')}</div>
  `;
  box.style.display = 'grid';
}

function componentForm({ mode, item }) {
  const it = item || {};
  const type = String(it.component_type || "SALARY_FIXED_MONTH").toUpperCase();
  const activeChecked = (mode === "edit" ? !!it.is_active : true) ? "checked" : "";
  const hasDepartments = Array.isArray(state.departments) && state.departments.length > 0;
  const departmentOptions = state.departments.map((dep) => `<option value="${esc(dep.id)}" ${Number(dep.id) === Number(it.department_id) ? "selected" : ""}>${esc(dep.title)}</option>`).join("");
  const boostDepartmentOptions = state.departments.map((dep) => `<option value="${esc(dep.id)}" ${Number(dep.id) === Number(it.boost_department_id) ? "selected" : ""}>${esc(dep.title)}</option>`).join("");
  const hasKpiMetrics = Array.isArray(state.kpiMetrics) && state.kpiMetrics.length > 0;
  const kpiOptions = state.kpiMetrics.map((metric) => `<option value="${esc(metric.id)}" ${Number(metric.id) === Number(it.kpi_metric_id) ? "selected" : ""}>${esc(kpiMetricOptionLabel(metric))}</option>`).join("");
  const boostKpiOptions = state.kpiMetrics.map((metric) => `<option value="${esc(metric.id)}" ${Number(metric.id) === Number(it.boost_kpi_metric_id) ? "selected" : ""}>${esc(kpiMetricOptionLabel(metric))}</option>`).join("");
  const boostEnabled = it?.boost_enabled ? "checked" : "";
  return `
    <div class="finance-form mt-8">
      <div class="form-section">
        <div class="form-section__head">
          <div class="form-section__title">Основа компонента</div>
          <div class="form-section__subtitle">Сначала выбери тип и базовые параметры. Остальные блоки подстроятся автоматически.</div>
        </div>
        <div class="form-section__grid">
          <label>
            <span>Тип</span>
            <select id="f_component_type">
              <option value="SALARY_FIXED_MONTH" ${type === "SALARY_FIXED_MONTH" ? "selected" : ""}>Оклад за месяц</option>
              <option value="SALARY_HOURLY" ${type === "SALARY_HOURLY" ? "selected" : ""}>Почасовая ставка</option>
              <option value="SALARY_PER_SHIFT" ${type === "SALARY_PER_SHIFT" ? "selected" : ""}>Фикс за смену</option>
              <option value="PERCENT_TOTAL_REVENUE" ${type === "PERCENT_TOTAL_REVENUE" ? "selected" : ""}>% от общей выручки</option>
              <option value="PERCENT_DEPARTMENT_REVENUE" ${type === "PERCENT_DEPARTMENT_REVENUE" ? "selected" : ""}>% от выручки департамента</option>
              <option value="KPI_BONUS" ${type === "KPI_BONUS" ? "selected" : ""}>KPI-бонус</option>
            </select>
          </label>
          <label>
            <span>Название компонента</span>
            <input id="f_title" placeholder="Например: % бара" value="${esc(it.title || "")}" />
          </label>
        </div>
        <div class="form-section__grid">
          <label id="f_amount_wrap">
            <span id="f_amount_label">Сумма, ₽</span>
            <input id="f_amount_minor" inputmode="decimal" placeholder="0" value="${esc(moneyInputFromMinor(it.amount_minor))}" />
          </label>
          <label id="f_rate_wrap">
            <span id="f_rate_label">Ставка, ₽ / час</span>
            <input id="f_rate_minor" inputmode="decimal" placeholder="0" value="${esc(moneyInputFromMinor(it.rate_minor))}" />
          </label>
          <label id="f_percent_wrap">
            <span id="f_percent_label">Процент</span>
            <input id="f_percent" inputmode="decimal" placeholder="Например, 5" value="${esc(percentInputFromBps(it.percent_bps))}" />
          </label>
        </div>
        <div class="form-section__grid">
          <label>
            <span>Порядок</span>
            <input id="f_sort_order" inputmode="numeric" placeholder="0" value="${esc(it.sort_order ?? 0)}" />
          </label>
          <label class="chk" style="margin-top:auto;">
            <input type="checkbox" id="f_active" ${activeChecked} />
            <span>Компонент активен</span>
          </label>
        </div>
        <div id="f_live_summary" class="pay-config-summary"></div>
      </div>

      <div class="form-section" id="f_percent_section">
        <div class="form-section__head">
          <div class="form-section__title">Расчёт процента</div>
          <div class="form-section__subtitle">Настрой базу расчёта и, при необходимости, департамент.</div>
        </div>
        <div class="form-section__grid">
          ${hasDepartments ? `
          <label id="f_department_wrap">
            <span>Департамент</span>
            <select id="f_department_id">
              <option value="">Выбери департамент</option>
              ${departmentOptions}
            </select>
          </label>` : `
          <label id="f_department_wrap">
            <span>Номер департамента</span>
            <input id="f_department_id" inputmode="numeric" placeholder="Номер департамента" value="${esc(it.department_id ?? "")}" />
          </label>
          <div id="f_department_hint" class="form-inline-note">Список департаментов не загрузился. Укажи номер вручную.</div>`}
          <label id="f_base_scope_wrap">
            <span>База расчёта</span>
            <select id="f_base_scope">${baseScopeOptions(it.base_scope || it.effective_base_scope, type)}</select>
          </label>
        </div>
        <div id="f_percent_help" class="form-inline-note">Можно считать по всему периоду или только по отработанным дням сотрудника.</div>
      </div>

      <div class="form-section" id="f_boost_section">
        <div class="form-section__head">
          <div class="form-section__title">Повышение процента</div>
          <div class="form-section__subtitle">Этот блок нужен только для процентных компонентов. Повышение можно привязать к плану заведения, плану департамента или KPI.</div>
        </div>
        <label class="chk" id="f_boost_enabled_wrap">
          <input type="checkbox" id="f_boost_enabled" ${boostEnabled} />
          <span>Повышенный процент по плану / KPI</span>
        </label>
        <div id="f_boost_details" class="form-section__grid">
          <label id="f_boost_percent_wrap">
            <span>Повышенный процент</span>
            <input id="f_boost_percent" inputmode="decimal" placeholder="Например, 7" value="${esc(percentInputFromBps(it.boost_percent_bps))}" />
          </label>
          <label id="f_boost_source_wrap">
            <span>Условие повышения</span>
            <select id="f_boost_source_type">${percentBoostOptions(it.boost_source_type || it.effective_boost_source_type || 'NONE')}</select>
          </label>
          ${hasDepartments ? `
          <label id="f_boost_department_wrap">
            <span>Департамент для условия</span>
            <select id="f_boost_department_id">
              <option value="">Выбери департамент</option>
              ${boostDepartmentOptions}
            </select>
          </label>` : `
          <label id="f_boost_department_wrap">
            <span>Номер департамента для условия</span>
            <input id="f_boost_department_id" inputmode="numeric" placeholder="Номер департамента" value="${esc(it.boost_department_id ?? "")}" />
          </label>
          <div id="f_boost_department_hint" class="form-inline-note">Если условие связано с департаментом, укажи его номер вручную.</div>`}
          <label id="f_boost_recalc_wrap">
            <span>Режим пересчёта</span>
            <select id="f_boost_recalc_mode">${boostRecalcOptions(it.boost_recalc_mode || it.effective_boost_recalc_mode || 'REPLACE_ALL')}</select>
          </label>
          ${hasKpiMetrics ? `
          <label id="f_boost_kpi_metric_wrap">
            <span>KPI для повышения</span>
            <select id="f_boost_kpi_metric_id">
              <option value="">Выбери KPI</option>
              ${boostKpiOptions}
            </select>
          </label>` : `
          <label id="f_boost_kpi_metric_wrap">
            <span>Номер KPI для повышения</span>
            <input id="f_boost_kpi_metric_id" inputmode="numeric" placeholder="Номер KPI" value="${esc(it.boost_kpi_metric_id ?? "")}" />
          </label>`}
          <label id="f_boost_threshold_wrap">
            <span id="f_boost_threshold_label">Цель KPI</span>
            <input id="f_boost_threshold_value" inputmode="numeric" placeholder="Например: 30" value="${esc(it.boost_threshold_value ?? "")}" />
          </label>
        </div>
        <div id="f_config_hint" style="display:none;"></div>
      </div>

      <div class="form-section" id="f_limits_section">
        <div class="form-section__head">
          <div class="form-section__title">Ограничения</div>
          <div class="form-section__subtitle">Эти ограничения применяются уже после расчёта суммы компонента.</div>
        </div>
        <div class="form-section__grid">
          <label id="f_min_wrap">
            <span>Минимальная гарантия, ₽</span>
            <input id="f_minimum_guarantee_minor" inputmode="decimal" placeholder="Например: 40000" value="${esc(moneyInputFromMinor(it.minimum_guarantee_minor))}" />
          </label>
          <label id="f_max_wrap">
            <span>Максимум, ₽</span>
            <input id="f_maximum_cap_minor" inputmode="decimal" placeholder="Например: 90000" value="${esc(moneyInputFromMinor(it.maximum_cap_minor))}" />
          </label>
        </div>
      </div>

      <div class="form-section" id="f_sim_section">
        <div class="form-section__head">
          <div class="form-section__title">Симулятор</div>
          <div class="form-section__subtitle">Помогает быстро проверить базовую и повышенную логику до сохранения компонента.</div>
        </div>
        <div id="f_sim_wrap" class="pay-sim">
          <div class="pay-sim__title">Симулятор компонента</div>
          <div class="pay-sim__grid">
            <label>
              <span>Тестовая база, ₽</span>
              <input id="f_sim_base_rub" inputmode="decimal" placeholder="Например: 500000" />
            </label>
            <label id="f_sim_target_wrap">
              <span id="f_sim_target_label">Цель</span>
              <input id="f_sim_target" inputmode="decimal" placeholder="Например: 450000" />
            </label>
            <label id="f_sim_actual_wrap">
              <span id="f_sim_actual_label">Факт</span>
              <input id="f_sim_actual" inputmode="decimal" placeholder="Например: 500000" />
            </label>
          </div>
          <div class="pay-sim__result muted" id="f_sim_result">Укажи процент и базу, чтобы увидеть пример начисления.</div>
        </div>
      </div>

      <div class="form-section" id="f_kpi_section">
        <div class="form-section__head">
          <div class="form-section__title">KPI-бонус</div>
          <div class="form-section__subtitle">Для бонуса можно использовать фиксированную сумму или ступени по мере роста значения KPI.</div>
        </div>
        <div class="form-section__grid">
          ${hasKpiMetrics ? `
          <label id="f_kpi_metric_wrap">
            <span>KPI-метрика</span>
            <select id="f_kpi_metric_id">
              <option value="">Выбери KPI</option>
              ${kpiOptions}
            </select>
          </label>` : `
          <label id="f_kpi_metric_wrap">
            <span>Номер KPI-метрики</span>
            <input id="f_kpi_metric_id" inputmode="numeric" placeholder="Номер KPI" value="${esc(it.kpi_metric_id ?? "")}" />
          </label>
          <div id="f_kpi_metric_hint" class="form-inline-note">Список KPI не загрузился. Укажи номер вручную.</div>`}
          <label id="f_threshold_wrap">
            <span id="f_threshold_label">Порог KPI</span>
            <input id="f_threshold_value" inputmode="numeric" placeholder="Например: 30" value="${esc(it.threshold_value ?? "")}" />
          </label>
          <label id="f_use_steps_wrap" class="chk" style="margin-top:auto;">
            <input type="checkbox" id="f_use_steps" ${Array.isArray(it.steps) && it.steps.length ? "checked" : ""} />
            <span>Использовать ступени бонуса</span>
          </label>
        </div>
        <div id="f_steps_wrap" class="kpi-steps-builder">
          <div class="row row--between ai-center" style="gap:8px; flex-wrap:wrap; margin-bottom:8px;">
            <div>
              <b>Ступени бонуса</b>
              <div class="muted mt-4">Будет выбрана максимальная подходящая ступень.</div>
            </div>
            <button class="btn sm" type="button" id="btnAddStep">+ Ступень</button>
          </div>
          <div id="f_steps_rows">${stepsRowsMarkup(it.steps)}</div>
        </div>
        <div id="f_steps_hint" class="form-inline-note">Ступени можно не использовать: тогда сработает обычный порог и фиксированный бонус.</div>
      </div>
    </div>

    <div class="row mt-12" style="justify-content:flex-end; gap:8px">
      <button class="btn" id="btnCancel" type="button">Отмена</button>
      <button class="btn primary" id="btnSave" type="button">Сохранить</button>
    </div>
  `;
}

function syncComponentSimulator() {
  const type = String(document.getElementById("f_component_type")?.value || "").toUpperCase();
  const wrap = document.getElementById("f_sim_wrap");
  const result = document.getElementById("f_sim_result");
  if (!wrap || !result) return;
  if (!["PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"].includes(type)) {
    wrap.style.display = "none";
    return;
  }
  wrap.style.display = "grid";
  const baseMinor = parseMoneyRubToMinor(document.getElementById("f_sim_base_rub")?.value || "") || 0;
  const percentBps = parsePercentInputToBps(document.getElementById("f_percent")?.value || "") || 0;
  const boostEnabled = !!document.getElementById("f_boost_enabled")?.checked;
  const boostPercentBps = parsePercentInputToBps(document.getElementById("f_boost_percent")?.value || "") || 0;
  const sourceType = String(document.getElementById("f_boost_source_type")?.value || "NONE").toUpperCase();
  const recalcMode = String(document.getElementById("f_boost_recalc_mode")?.value || "REPLACE_ALL").toUpperCase();
  const minimumMinor = parseMoneyRubToMinor(document.getElementById("f_minimum_guarantee_minor")?.value || "");
  const maximumMinor = parseMoneyRubToMinor(document.getElementById("f_maximum_cap_minor")?.value || "");
  const simTargetWrap = document.getElementById("f_sim_target_wrap");
  const simActualWrap = document.getElementById("f_sim_actual_wrap");
  const simTargetLabel = document.getElementById("f_sim_target_label");
  const simActualLabel = document.getElementById("f_sim_actual_label");
  const targetRaw = String(document.getElementById("f_sim_target")?.value || "").trim();
  const actualRaw = String(document.getElementById("f_sim_actual")?.value || "").trim();
  const targetIsMoney = sourceType !== "KPI_METRIC";
  const targetValue = targetIsMoney ? (parseMoneyRubToMinor(targetRaw) || 0) : Number(targetRaw || 0);
  const actualValue = targetIsMoney ? (parseMoneyRubToMinor(actualRaw) || 0) : Number(actualRaw || 0);
  if (simTargetWrap) simTargetWrap.style.display = boostEnabled && sourceType !== "NONE" ? "grid" : "none";
  if (simActualWrap) simActualWrap.style.display = boostEnabled && sourceType !== "NONE" ? "grid" : "none";
  if (simTargetLabel) simTargetLabel.textContent = sourceType === "KPI_METRIC" ? "Цель KPI" : "План / цель";
  if (simActualLabel) simActualLabel.textContent = sourceType === "KPI_METRIC" ? "Факт KPI" : "Факт";

  if (!baseMinor || !percentBps) {
    result.textContent = "Укажи процент и базу, чтобы увидеть пример начисления.";
    return;
  }

  const regular = Math.round((baseMinor * percentBps) / 10000);
  let finalAmount = regular;
  let applied = false;
  let modeLabel = 'базовый расчёт';
  let note = `Без дополнительных условий компонент дал бы ${fmtMoneyMinor(regular)}.`;

  if (boostEnabled && boostPercentBps > 0 && sourceType !== "NONE") {
    applied = Number.isFinite(actualValue) && Number.isFinite(targetValue) && actualValue >= targetValue && targetValue > 0;
    if (applied) {
      if (recalcMode === "EXCESS_ONLY" && sourceType !== "KPI_METRIC") {
        const regularPart = Math.round((Math.min(baseMinor, targetValue) * percentBps) / 10000);
        const boostPart = Math.round((Math.max(baseMinor - targetValue, 0) * boostPercentBps) / 10000);
        finalAmount = regularPart + boostPart;
        modeLabel = 'повышение на превышение';
        note = `Условие выполнено. До цели действует базовый %, а сверх цели — повышенный.`;
      } else {
        finalAmount = Math.round((baseMinor * boostPercentBps) / 10000);
        modeLabel = 'повышенный процент';
        note = `Условие выполнено. Ко всей тестовой базе применился повышенный процент.`;
      }
    } else {
      note = `Условие пока не выполнено, поэтому остаётся базовый процент.`;
    }
  }

  const rawBeforeCaps = finalAmount;
  if (minimumMinor != null && finalAmount < minimumMinor) {
    finalAmount = minimumMinor;
    note += ` Сработала минимальная гарантия ${fmtMoneyMinor(minimumMinor)}.`;
  }
  if (maximumMinor != null && finalAmount > maximumMinor) {
    finalAmount = maximumMinor;
    note += ` Сработал потолок ${fmtMoneyMinor(maximumMinor)}.`;
  }

  result.innerHTML = `
    <div class="pay-sim__stats">
      <div class="pay-sim__stat">
        <div class="pay-sim__stat-label">Базовый расчёт</div>
        <div class="pay-sim__stat-value">${esc(fmtMoneyMinor(regular))}</div>
      </div>
      <div class="pay-sim__stat ${applied ? 'pay-sim__stat--accent' : ''}">
        <div class="pay-sim__stat-label">Режим</div>
        <div class="pay-sim__stat-value">${esc(applied ? modeLabel : 'базовый %')}</div>
      </div>
      <div class="pay-sim__stat">
        <div class="pay-sim__stat-label">До ограничений</div>
        <div class="pay-sim__stat-value">${esc(fmtMoneyMinor(rawBeforeCaps))}</div>
      </div>
      <div class="pay-sim__stat pay-sim__stat--accent">
        <div class="pay-sim__stat-label">Итог</div>
        <div class="pay-sim__stat-value">${esc(fmtMoneyMinor(finalAmount))}</div>
      </div>
    </div>
    <div class="pay-sim__note">${esc(note)}</div>
  `;
}

function syncComponentFields() {
  applyPercentSmartDefaults();
  const type = String(document.getElementById("f_component_type")?.value || "").toUpperCase();
  const useSteps = !!document.getElementById("f_use_steps")?.checked;
  const boostEnabled = !!document.getElementById("f_boost_enabled")?.checked;
  const boostSourceType = String(document.getElementById("f_boost_source_type")?.value || "NONE").toUpperCase();
  const amountWrap = document.getElementById("f_amount_wrap");
  const rateWrap = document.getElementById("f_rate_wrap");
  const percentWrap = document.getElementById("f_percent_wrap");
  const departmentWrap = document.getElementById("f_department_wrap");
  const departmentHint = document.getElementById("f_department_hint");
  const baseScopeWrap = document.getElementById("f_base_scope_wrap");
  const boostEnabledWrap = document.getElementById("f_boost_enabled_wrap");
  const boostPercentWrap = document.getElementById("f_boost_percent_wrap");
  const boostSourceWrap = document.getElementById("f_boost_source_wrap");
  const boostDepartmentWrap = document.getElementById("f_boost_department_wrap");
  const boostDepartmentHint = document.getElementById("f_boost_department_hint");
  const boostRecalcWrap = document.getElementById("f_boost_recalc_wrap");
  const boostKpiMetricWrap = document.getElementById("f_boost_kpi_metric_wrap");
  const boostThresholdWrap = document.getElementById("f_boost_threshold_wrap");
  const minWrap = document.getElementById("f_min_wrap");
  const maxWrap = document.getElementById("f_max_wrap");
  const percentHelp = document.getElementById("f_percent_help");
  const simWrap = document.getElementById("f_sim_wrap");
  const kpiMetricWrap = document.getElementById("f_kpi_metric_wrap");
  const kpiMetricHint = document.getElementById("f_kpi_metric_hint");
  const thresholdWrap = document.getElementById("f_threshold_wrap");
  const useStepsWrap = document.getElementById("f_use_steps_wrap");
  const stepsWrap = document.getElementById("f_steps_wrap");
  const stepsHint = document.getElementById("f_steps_hint");
  const amountLabel = document.getElementById("f_amount_label");
  const rateLabel = document.getElementById("f_rate_label");
  const percentLabel = document.getElementById("f_percent_label");
  const thresholdLabel = document.getElementById("f_threshold_label");
  const boostThresholdLabel = document.getElementById("f_boost_threshold_label");
  const selectedBoostMetric = findKpiMetricById(document.getElementById("f_boost_kpi_metric_id")?.value);
  const selectedBonusMetric = findKpiMetricById(document.getElementById("f_kpi_metric_id")?.value);
  const percentSection = document.getElementById('f_percent_section');
  const boostSection = document.getElementById('f_boost_section');
  const limitsSection = document.getElementById('f_limits_section');
  const simSection = document.getElementById('f_sim_section');
  const kpiSection = document.getElementById('f_kpi_section');
  const boostDetails = document.getElementById('f_boost_details');

  [amountWrap, rateWrap, percentWrap, departmentWrap, departmentHint, baseScopeWrap, boostEnabledWrap, boostPercentWrap, boostSourceWrap, boostDepartmentWrap, boostDepartmentHint, boostRecalcWrap, boostKpiMetricWrap, boostThresholdWrap, minWrap, maxWrap, percentHelp, simWrap, kpiMetricWrap, kpiMetricHint, thresholdWrap, useStepsWrap, stepsWrap, stepsHint, percentSection, boostSection, limitsSection, simSection, kpiSection, boostDetails].forEach((el) => {
    if (el) el.style.display = "none";
  });

  if (type === "SALARY_HOURLY") {
    if (rateWrap) rateWrap.style.display = "grid";
    if (rateLabel) rateLabel.textContent = "Ставка, ₽ / час";
    syncComponentSummary();
    return syncComponentSimulator();
  }

  if (type === "SALARY_FIXED_MONTH" || type === "SALARY_PER_SHIFT") {
    if (amountWrap) amountWrap.style.display = "grid";
    if (amountLabel) amountLabel.textContent = type === "SALARY_PER_SHIFT" ? "Сумма, ₽ / смена" : "Сумма, ₽ / месяц";
    syncComponentSummary();
    return syncComponentSimulator();
  }

  if (type === "PERCENT_TOTAL_REVENUE" || type === "PERCENT_DEPARTMENT_REVENUE") {
    if (percentSection) percentSection.style.display = "grid";
    if (boostSection) boostSection.style.display = "grid";
    if (limitsSection) limitsSection.style.display = "grid";
    if (simSection) simSection.style.display = "grid";
    if (percentWrap) percentWrap.style.display = "grid";
    if (baseScopeWrap) baseScopeWrap.style.display = "grid";
    if (boostEnabledWrap) boostEnabledWrap.style.display = "flex";
    if (minWrap) minWrap.style.display = "grid";
    if (maxWrap) maxWrap.style.display = "grid";
    if (percentHelp) percentHelp.style.display = "";
    if (simWrap) simWrap.style.display = "grid";
    if (type === "PERCENT_DEPARTMENT_REVENUE") {
      if (departmentWrap) departmentWrap.style.display = "grid";
      if (departmentHint) departmentHint.style.display = "";
      if (percentLabel) percentLabel.textContent = "Процент от выручки департамента";
    } else if (percentLabel) {
      percentLabel.textContent = "Процент от общей выручки";
    }
    if (boostEnabled) {
      if (boostDetails) boostDetails.style.display = 'grid';
      if (boostPercentWrap) boostPercentWrap.style.display = "grid";
      if (boostSourceWrap) boostSourceWrap.style.display = "grid";
      if (boostRecalcWrap) boostRecalcWrap.style.display = "grid";
      if (isDepartmentBoostSource(boostSourceType) && boostDepartmentWrap) boostDepartmentWrap.style.display = "grid";
      if (isDepartmentBoostSource(boostSourceType) && boostDepartmentHint) boostDepartmentHint.style.display = "";
      if (boostSourceType === "KPI_METRIC") {
        if (boostKpiMetricWrap) boostKpiMetricWrap.style.display = "grid";
        if (boostThresholdWrap) boostThresholdWrap.style.display = "grid";
        if (boostThresholdLabel) boostThresholdLabel.textContent = `Цель KPI${selectedBoostMetric ? ` (${String(selectedBoostMetric.unit || 'QTY').toUpperCase()})` : ''}`;
      }
    }
    syncComponentSummary();
    syncComponentSimulator();
    syncComponentConfigHint();
    return;
  }

  if (type === "KPI_BONUS") {
    if (kpiSection) kpiSection.style.display = "grid";
    if (kpiMetricWrap) kpiMetricWrap.style.display = "grid";
    if (kpiMetricHint) kpiMetricHint.style.display = "";
    if (thresholdWrap) thresholdWrap.style.display = "grid";
    if (useStepsWrap) useStepsWrap.style.display = "flex";
    if (stepsHint) stepsHint.style.display = "";
    if (thresholdLabel) thresholdLabel.textContent = `Порог KPI${selectedBonusMetric ? ` (${String(selectedBonusMetric.unit || 'QTY').toUpperCase()})` : ''}`;
    if (useSteps) {
      if (stepsWrap) stepsWrap.style.display = "block";
    } else {
      if (stepsWrap) stepsWrap.style.display = "none";
      if (amountWrap) amountWrap.style.display = "grid";
      if (amountLabel) amountLabel.textContent = "Бонус, ₽";
    }
  }
  syncComponentSummary();
  syncComponentSimulator();
  syncComponentConfigHint();
}

function openComponentEditor({ mode, item = null }) {
  if (!state.can.manage) return;
  const isEdit = mode === "edit";
  openEditModal({
    title: isEdit ? "Редактировать компонент" : "Новый компонент",
    hint: "Поддержаны ставки, проценты и KPI-бонусы",
    bodyHtml: componentForm({ mode, item }),
  });
  document.getElementById("f_component_type")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_use_steps")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_boost_enabled")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_boost_source_type")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_boost_recalc_mode")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_department_id")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_boost_department_id")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_base_scope")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_kpi_metric_id")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_boost_kpi_metric_id")?.addEventListener("change", syncComponentFields);
  ["f_title","f_amount_minor","f_rate_minor","f_percent","f_boost_percent","f_threshold_value","f_boost_threshold_value","f_minimum_guarantee_minor","f_maximum_cap_minor","f_sim_base_rub","f_sim_target","f_sim_actual"].forEach((id) => {
    document.getElementById(id)?.addEventListener("input", () => { syncComponentSummary(); syncComponentSimulator(); syncComponentConfigHint(); });
  });
  wireStepsBuilder();
  syncComponentFields();
  syncComponentSummary();
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const componentType = String(document.getElementById("f_component_type")?.value || "").toUpperCase();
    const title = String(document.getElementById("f_title")?.value || "").trim();
    const amountMinorRaw = String(document.getElementById("f_amount_minor")?.value || "").trim();
    const rateMinorRaw = String(document.getElementById("f_rate_minor")?.value || "").trim();
    const percentRaw = String(document.getElementById("f_percent")?.value || "").trim();
    const departmentRaw = String(document.getElementById("f_department_id")?.value || "").trim();
    const baseScope = String(document.getElementById("f_base_scope")?.value || "").trim().toUpperCase();
    const boostEnabled = !!document.getElementById("f_boost_enabled")?.checked;
    const boostPercentRaw = String(document.getElementById("f_boost_percent")?.value || "").trim();
    const boostSourceType = String(document.getElementById("f_boost_source_type")?.value || "NONE").trim().toUpperCase();
    const boostRecalcMode = String(document.getElementById("f_boost_recalc_mode")?.value || "REPLACE_ALL").trim().toUpperCase();
    const boostDepartmentRaw = String(document.getElementById("f_boost_department_id")?.value || "").trim();
    const boostKpiMetricRaw = String(document.getElementById("f_boost_kpi_metric_id")?.value || "").trim();
    const boostThresholdRaw = String(document.getElementById("f_boost_threshold_value")?.value || "").trim();
    const minGuaranteeRaw = String(document.getElementById("f_minimum_guarantee_minor")?.value || "").trim();
    const maxCapRaw = String(document.getElementById("f_maximum_cap_minor")?.value || "").trim();
    const sortRaw = String(document.getElementById("f_sort_order")?.value || "0").trim();
    const isActive = !!document.getElementById("f_active")?.checked;

    if (!title) {
      toast("Укажи название компонента", "warn");
      return;
    }

    const kpiMetricRaw = String(document.getElementById("f_kpi_metric_id")?.value || "").trim();
    const thresholdRaw = String(document.getElementById("f_threshold_value")?.value || "").trim();
    const useSteps = !!document.getElementById("f_use_steps")?.checked;

    const payload = {
      component_type: componentType,
      title,
      amount_minor: null,
      rate_minor: null,
      percent_bps: null,
      department_id: null,
      kpi_metric_id: null,
      threshold_value: null,
      steps_json: null,
      base_scope: null,
      boost_enabled: false,
      boost_percent_bps: null,
      boost_source_type: null,
      boost_recalc_mode: null,
      boost_kpi_metric_id: null,
      boost_threshold_value: null,
      minimum_guarantee_minor: null,
      maximum_cap_minor: null,
      sort_order: Number(sortRaw || 0),
      is_active: isActive,
    };

    if (componentType === "SALARY_HOURLY") {
      if (!rateMinorRaw) {
        toast("Укажи почасовую ставку в рублях", "warn");
        return;
      }
      payload.rate_minor = parseMoneyRubToMinor(rateMinorRaw);
      if (payload.rate_minor === null) {
        toast("Некорректная почасовая ставка", "warn");
        return;
      }
    } else if (componentType === "SALARY_FIXED_MONTH" || componentType === "SALARY_PER_SHIFT") {
      if (!amountMinorRaw) {
        toast("Укажи сумму в рублях", "warn");
        return;
      }
      payload.amount_minor = parseMoneyRubToMinor(amountMinorRaw);
      if (payload.amount_minor === null) {
        toast("Некорректная сумма", "warn");
        return;
      }
    } else if (componentType === "PERCENT_TOTAL_REVENUE" || componentType === "PERCENT_DEPARTMENT_REVENUE") {
      const percentBps = parsePercentInputToBps(percentRaw);
      if (percentBps === null) {
        toast("Укажи процент, например 5 или 7.5", "warn");
        return;
      }
      payload.percent_bps = percentBps;
      payload.base_scope = baseScope || (componentType === "PERCENT_DEPARTMENT_REVENUE" ? "WORKED_DATES" : "FULL_PERIOD");
      if (componentType === "PERCENT_DEPARTMENT_REVENUE") {
        if (!departmentRaw) {
          toast("Выбери департамент", "warn");
          return;
        }
        payload.department_id = Number(departmentRaw);
      }
      if (minGuaranteeRaw) {
        payload.minimum_guarantee_minor = parseMoneyRubToMinor(minGuaranteeRaw);
        if (payload.minimum_guarantee_minor == null) {
          toast("Некорректная минимальная гарантия", "warn");
          return;
        }
      }
      if (maxCapRaw) {
        payload.maximum_cap_minor = parseMoneyRubToMinor(maxCapRaw);
        if (payload.maximum_cap_minor == null) {
          toast("Некорректный максимум", "warn");
          return;
        }
      }
      if (boostEnabled) {
        const boostPercentBps = parsePercentInputToBps(boostPercentRaw);
        if (boostPercentBps === null) {
          toast("Укажи повышенный процент", "warn");
          return;
        }
        payload.boost_enabled = true;
        payload.boost_percent_bps = boostPercentBps;
        payload.boost_source_type = boostSourceType;
        payload.boost_recalc_mode = boostRecalcMode;
        if (!boostSourceType || boostSourceType === "NONE") {
          toast("Выбери условие повышения", "warn");
          return;
        }
        if (isDepartmentBoostSource(boostSourceType)) {
          if (!boostDepartmentRaw) {
            toast("Выбери департамент для условия повышения", "warn");
            return;
          }
          payload.boost_department_id = Number(boostDepartmentRaw);
        }
        if (boostSourceType === "KPI_METRIC") {
          if (!boostKpiMetricRaw) {
            toast("Выбери KPI для повышения", "warn");
            return;
          }
          if (!boostThresholdRaw) {
            toast("Укажи цель KPI", "warn");
            return;
          }
          payload.boost_kpi_metric_id = Number(boostKpiMetricRaw);
          payload.boost_threshold_value = Number(boostThresholdRaw);
        }
      }
      if (payload.minimum_guarantee_minor != null && payload.maximum_cap_minor != null && payload.minimum_guarantee_minor > payload.maximum_cap_minor) {
        toast("Минимальная гарантия не может быть больше максимума", "warn");
        return;
      }
    } else if (componentType === "KPI_BONUS") {
      if (!kpiMetricRaw) {
        toast("Выбери KPI-метрику", "warn");
        return;
      }
      payload.kpi_metric_id = Number(kpiMetricRaw);
      if (thresholdRaw) payload.threshold_value = Number(thresholdRaw);
      if (useSteps) {
        const parsedSteps = readStepsBuilder();
        if (parsedSteps === false) {
          toast("Проверь ступени: укажи целый порог и сумму в рублях в каждой строке", "warn");
          return;
        }
        if (!Array.isArray(parsedSteps) || !parsedSteps.length) {
          toast("Добавь хотя бы одну ступень или отключи режим ступеней", "warn");
          return;
        }
        payload.steps_json = parsedSteps;
      } else {
        if (!amountMinorRaw) {
          toast("Укажи бонус в рублях или включи ступени", "warn");
          return;
        }
        payload.amount_minor = parseMoneyRubToMinor(amountMinorRaw);
        if (payload.amount_minor === null) {
          toast("Некорректный бонус", "warn");
          return;
        }
      }
    }

    try {
      if (isEdit && item?.id) {
        await updatePayComponent(state.venueId, item.id, payload);
        toast("Компонент обновлён", "ok");
      } else {
        await createPayComponent(state.venueId, state.profileId, payload);
        toast("Компонент создан", "ok");
      }
      closeEditModal();
      await load();
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

function assignmentForm({ mode, item }) {
  const it = item || {};
  const activeChecked = (mode === "edit" ? !!it.is_active : true) ? "checked" : "";
  const hasMembers = Array.isArray(state.members) && state.members.length > 0;
  const options = state.members.map((m) => `<option value="${esc(m.user_id)}">${esc(memberName(m))}</option>`).join("");
  return `
    <div class="finance-form mt-8">
      ${mode === "edit" ? `
        <label>
          <span>Сотрудник</span>
          <input value="${esc(memberName(it.member))}" disabled />
        </label>
      ` : hasMembers ? `
        <label>
          <span>Сотрудник</span>
          <select id="f_member_user_id">
            <option value="">Выбери сотрудника</option>
            ${options}
          </select>
        </label>
      ` : `
        <label>
          <span>Номер сотрудника</span>
          <input id="f_member_user_id" inputmode="numeric" placeholder="Например: 12" />
        </label>
        <div class="muted">Список сотрудников не загрузился. Можно ввести номер сотрудника вручную.</div>
      `}
      <label>
        <span>Дата начала</span>
        <input id="f_start_date" type="date" value="${esc(it.start_date || "")}" />
      </label>
      <label>
        <span>Дата окончания</span>
        <input id="f_end_date" type="date" value="${esc(it.end_date || "")}" />
      </label>
      <label class="chk">
        <input type="checkbox" id="f_active" ${activeChecked} />
        <span>Назначение активно</span>
      </label>
    </div>

    <div class="row mt-12" style="justify-content:flex-end; gap:8px">
      <button class="btn" id="btnCancel" type="button">Отмена</button>
      <button class="btn primary" id="btnSave" type="button">Сохранить</button>
    </div>
  `;
}

function openAssignmentEditor({ mode, item = null }) {
  if (!state.can.manage) return;
  const isEdit = mode === "edit";
  openEditModal({
    title: isEdit ? "Редактировать назначение" : "Новое назначение",
    hint: "Если даты пустые, профиль считается действующим без ограничений",
    bodyHtml: assignmentForm({ mode, item }),
  });
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const memberUserId = String(document.getElementById("f_member_user_id")?.value || "").trim();
    const startDate = String(document.getElementById("f_start_date")?.value || "").trim();
    const endDate = String(document.getElementById("f_end_date")?.value || "").trim();
    const isActive = !!document.getElementById("f_active")?.checked;

    const payload = {
      start_date: startDate || null,
      end_date: endDate || null,
      is_active: isActive,
    };

    if (!isEdit) {
      if (!memberUserId) {
        toast("Выбери сотрудника", "warn");
        return;
      }
      payload.member_user_id = Number(memberUserId);
    }

    try {
      if (isEdit && item?.id) {
        await updatePayProfileAssignment(state.venueId, item.id, payload);
        toast("Назначение обновлено", "ok");
      } else {
        await createPayProfileAssignment(state.venueId, state.profileId, payload);
        toast("Назначение создано", "ok");
      }
      closeEditModal();
      await load();
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

function openProfileEditor() {
  if (!state.can.manage || !state.profile) return;
  openEditModal({
    title: "Редактировать профиль",
    hint: "Изменения применятся ко всем последующим расчётам",
    bodyHtml: `
      <div class="finance-form mt-8">
        <label>
          <span>Название</span>
          <input id="f_title" value="${esc(state.profile.title || "")}" />
        </label>
        <label>
          <span>Описание</span>
          <textarea id="f_description" rows="4">${esc(state.profile.description || "")}</textarea>
        </label>
        <label class="chk">
          <input type="checkbox" id="f_active" ${state.profile.is_active ? "checked" : ""} />
          <span>Профиль активен</span>
        </label>
      </div>
      <div class="row mt-12" style="justify-content:flex-end; gap:8px">
        <button class="btn" id="btnCancel" type="button">Отмена</button>
        <button class="btn primary" id="btnSave" type="button">Сохранить</button>
      </div>
    `,
  });
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const title = String(document.getElementById("f_title")?.value || "").trim();
    const description = String(document.getElementById("f_description")?.value || "").trim();
    const isActive = !!document.getElementById("f_active")?.checked;
    if (!title) {
      toast("Укажи название профиля", "warn");
      return;
    }
    try {
      await updatePayProfile(state.venueId, state.profileId, {
        title,
        description: description || null,
        is_active: isActive,
      });
      toast("Профиль обновлён", "ok");
      closeEditModal();
      await load();
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

async function load() {
  const componentsList = document.getElementById("componentsList");
  const assignmentsList = document.getElementById("assignmentsList");
  if (componentsList) componentsList.innerHTML = `<div class="skeleton"></div>`;
  if (assignmentsList) assignmentsList.innerHTML = `<div class="skeleton"></div>`;

  try {
    state.profile = await getPayProfile(state.venueId, state.profileId);
  } catch (e) {
    root.innerHTML = `<div class="card"><div class="muted">Ошибка загрузки профиля: ${esc(e?.data?.detail || e?.message || "не удалось загрузить")}</div></div>`;
    return;
  }

  renderHeader();
  renderComponents();
  renderAssignments();
}

async function boot() {
  applyTelegramTheme();
  renderShell();
  wireEditModalClose();
  await ensureLogin({ silent: true });

  const params = parseParams();
  state.venueId = params.venueId;
  state.profileId = params.profileId;

  if (!state.venueId || !state.profileId) {
    root.innerHTML = `<div class="card"><div class="muted">Не найден venue_id или profile_id</div></div>`;
    return;
  }

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

  try {
    const membersResp = await getVenueMembers(state.venueId);
    state.members = Array.isArray(membersResp?.members) ? membersResp.members : [];
  } catch {
    state.members = [];
  }

  try {
    const depsResp = await getDepartments(state.venueId);
    state.departments = Array.isArray(depsResp) ? depsResp : [];
  } catch {
    state.departments = [];
  }

  try {
    const kpiResp = await getKpiMetrics(state.venueId, { includeArchived: false });
    state.kpiMetrics = Array.isArray(kpiResp) ? kpiResp : [];
  } catch {
    state.kpiMetrics = [];
  }

  document.getElementById("btnEditProfile")?.addEventListener("click", openProfileEditor);
  document.getElementById("btnAddComponent")?.addEventListener("click", () => openComponentEditor({ mode: "create" }));
  document.getElementById("btnAddAssignment")?.addEventListener("click", () => openAssignmentEditor({ mode: "create" }));

  await load();
}

document.addEventListener("DOMContentLoaded", boot);

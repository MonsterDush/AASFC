
export function createPayComponentSupport({ state, esc }) {
const COMPONENT_LABELS = {
  SALARY_FIXED_MONTH: "Оклад за месяц",
  SALARY_HOURLY: "Почасовая ставка",
  SALARY_PER_SHIFT: "Фикс за смену",
  PERCENT_TOTAL_REVENUE: "% от общей выручки",
  PERCENT_DEPARTMENT_REVENUE: "% от выручки департамента",
  KPI_BONUS: "KPI-бонус",
  MINIMUM_PAYOUT: "Минимальная сумма к выплате",
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

const MINIMUM_GUARANTEE_SCOPE_LABELS = {
  MONTH: "за месяц",
  DAY: "за день",
  SHIFT: "за смену",
};

function fmtMoneyMinor(minor) {
  const value = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";
  } catch {
    return value.toFixed(2) + " ₽";
  }
}

function fmtPercentBps(bps) {
  const value = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + "%";
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

function normalizeIdsArray(value) {
  if (Array.isArray(value)) {
    const out = [];
    const seen = new Set();
    value.forEach((raw) => {
      const id = Number(raw || 0);
      if (Number.isFinite(id) && id > 0 && !seen.has(id)) {
        seen.add(id);
        out.push(id);
      }
    });
    return out;
  }
  const id = Number(value || 0);
  return Number.isFinite(id) && id > 0 ? [id] : [];
}

function selectedDepartmentIdsFor(item) {
  const ids = normalizeIdsArray(item?.department_ids);
  const legacy = Number(item?.department_id || 0);
  if (legacy > 0 && !ids.includes(legacy)) ids.unshift(legacy);
  return ids;
}

function selectedBoostDepartmentIdsFor(item) {
  const ids = normalizeIdsArray(item?.boost_department_ids);
  const legacy = Number(item?.boost_department_id || 0);
  if (legacy > 0 && !ids.includes(legacy)) ids.unshift(legacy);
  return ids;
}

function departmentTitlesForIds(ids, explicitTitles = []) {
  const titles = [];
  const explicit = Array.isArray(explicitTitles) ? explicitTitles : [];
  normalizeIdsArray(ids).forEach((id, index) => {
    const explicitTitle = explicit[index];
    if (explicitTitle) {
      titles.push(String(explicitTitle));
      return;
    }
    const found = (state.departments || []).find((d) => Number(d?.id) === id);
    titles.push(found?.title || `#${id}`);
  });
  return titles;
}

function departmentTitleFor(item) {
  const ids = selectedDepartmentIdsFor(item);
  if (ids.length) return departmentTitlesForIds(ids, item?.department_titles).join(" + ");
  const direct = item?.department_title || item?.department?.title;
  if (direct) return direct;
  return null;
}

function minimumGuaranteeScopeLabel(scope) {
  const value = String(scope || "MONTH").toUpperCase();
  return MINIMUM_GUARANTEE_SCOPE_LABELS[value] || MINIMUM_GUARANTEE_SCOPE_LABELS.MONTH;
}

function minimumPayoutScopeLabel(scope) {
  const value = String(scope || "MONTH").toUpperCase();
  return value === "SHIFT" || value === "DAY" ? "за каждую отработанную смену" : "за месяц";
}

function selectedIdsFromField(id) {
  const el = document.getElementById(id);
  if (!el) return [];
  if (el.tagName === "SELECT" && el.multiple) {
    return Array.from(el.selectedOptions || []).map((option) => Number(option.value || 0)).filter((value) => Number.isFinite(value) && value > 0);
  }
  return normalizeIdsArray(String(el.value || "").split(",").map((value) => value.trim()).filter(Boolean));
}

function selectedDepartmentTitlesFromField(id) {
  return departmentTitlesForIds(selectedIdsFromField(id));
}

function departmentsOptionsMarkup(selectedIds = []) {
  const selected = new Set(normalizeIdsArray(selectedIds).map(String));
  return (state.departments || []).map((dep) => {
    const id = String(dep.id);
    return `<option value="${esc(id)}" ${selected.has(id) ? "selected" : ""}>${esc(dep.title)}</option>`;
  }).join("");
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
  if (item.minimum_guarantee_minor != null) {
    parts.push(`мин ${fmtMoneyMinor(item.minimum_guarantee_minor)} ${minimumGuaranteeScopeLabel(item.effective_minimum_guarantee_scope || item.minimum_guarantee_scope)}`);
  }
  if (item.maximum_cap_minor != null) parts.push(`потолок ${fmtMoneyMinor(item.maximum_cap_minor)}`);
  if (item.boost_enabled && item.boost_percent_bps != null) {
    const sourceLabel = boostSourceLabel(effectiveBoostSourceFor(item));
    const modeLabel = boostRecalcLabel(effectiveBoostRecalcModeFor(item));
    const boostBits = [`boost ${fmtPercentBps(item.boost_percent_bps)}`];
    if (sourceLabel) boostBits.push(sourceLabel);
    if (modeLabel) boostBits.push(modeLabel);
    const boostDepartmentTitles = departmentTitlesForIds(selectedBoostDepartmentIdsFor(item), item.boost_department_titles);
    if (boostDepartmentTitles.length) boostBits.push(boostDepartmentTitles.join(" + "));
    else if (item.boost_department_title) boostBits.push(item.boost_department_title);
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
  if (boostSourceEl && isDepartmentBoostSource(boostSourceEl.value) && boostDepartmentEl && !selectedIdsFromField('f_boost_department_id').length && selectedIdsFromField('f_department_id').length) {
    const baseIds = new Set(selectedIdsFromField('f_department_id').map(String));
    if (boostDepartmentEl.tagName === "SELECT" && boostDepartmentEl.multiple) {
      Array.from(boostDepartmentEl.options || []).forEach((option) => {
        option.selected = baseIds.has(String(option.value || ""));
      });
    } else {
      boostDepartmentEl.value = selectedIdsFromField('f_department_id').join(",");
    }
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
    const boostDepartmentIds = selectedIdsFromField('f_boost_department_id');
    const minScope = String(document.getElementById('f_minimum_guarantee_scope')?.value || 'MONTH').toUpperCase();

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
    if (minMinor != null && minScope === 'DAY') {
      infos.push('Дневная минималка применяется отдельно к каждому рабочему дню компонента.');
    }
    if (isDepartmentBoostSource(boostSourceType) && !boostDepartmentIds.length) {
      warnings.push('Для плана департамента нужно выбрать один или несколько департаментов в блоке условия повышения.');
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
  box.classList.toggle('hidden', !parts.length);
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

return {
  COMPONENT_LABELS,
  fmtMoneyMinor,
  fmtPercentBps,
  percentInputFromBps,
  moneyInputFromMinor,
  parseMoneyRubToMinor,
  parsePercentInputToBps,
  selectedDepartmentIdsFor,
  selectedBoostDepartmentIdsFor,
  departmentTitleFor,
  minimumGuaranteeScopeLabel,
  minimumPayoutScopeLabel,
  selectedIdsFromField,
  selectedDepartmentTitlesFromField,
  departmentsOptionsMarkup,
  kpiMetricTitleFor,
  baseScopeLabel,
  boostSourceLabel,
  formatPercentConfig,
  percentBoostOptions,
  baseScopeOptions,
  boostRecalcOptions,
  isDepartmentBoostSource,
  applyPercentSmartDefaults,
  syncComponentConfigHint,
  stepsRowsMarkup,
  wireStepsBuilder,
  readStepsBuilder,
};
}

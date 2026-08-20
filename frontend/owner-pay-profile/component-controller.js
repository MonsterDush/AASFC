
export function createPayComponentController({
  state,
  esc,
  support,
  componentForm,
  openEditModal,
  closeEditModal,
  toast,
  createPayComponent,
  updatePayComponent,
  load,
}) {
const {
  COMPONENT_LABELS,
  fmtMoneyMinor,
  fmtPercentBps,
  parseMoneyRubToMinor,
  parsePercentInputToBps,
  selectedIdsFromField,
  selectedDepartmentTitlesFromField,
  minimumGuaranteeScopeLabel,
  minimumPayoutScopeLabel,
  baseScopeLabel,
  boostSourceLabel,
  isDepartmentBoostSource,
  applyPercentSmartDefaults,
  syncComponentConfigHint,
  wireStepsBuilder,
  readStepsBuilder,
} = support;

function findKpiMetricById(value) {
  const id = Number(value || 0);
  return Array.isArray(state.kpiMetrics) ? state.kpiMetrics.find((metric) => Number(metric.id) === id) || null : null;
}

function setVisible(element, visible) {
  element?.classList.toggle("hidden", !visible);
}

function readWeekdayRates({ validate = false } = {}) {
  const rows = [];
  for (const checkbox of document.querySelectorAll("[data-weekday-enabled]")) {
    if (!checkbox.checked) continue;
    const weekday = Number(checkbox.dataset.weekdayEnabled);
    const input = document.querySelector(`[data-weekday-rate="${weekday}"]`);
    const raw = String(input?.value || "").trim();
    const rateMinor = parseMoneyRubToMinor(raw);
    if (!raw || rateMinor === null) {
      if (validate) return false;
      continue;
    }
    rows.push({ weekday, rate_minor: rateMinor });
  }
  return rows;
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
  const departmentIds = selectedIdsFromField('f_department_id');
  const departmentTitles = selectedDepartmentTitlesFromField('f_department_id');
  const baseScope = String(document.getElementById('f_base_scope')?.value || '').toUpperCase();
  const boostEnabled = !!document.getElementById('f_boost_enabled')?.checked;
  const boostPercentBps = parsePercentInputToBps(document.getElementById('f_boost_percent')?.value || '');
  const boostSourceType = String(document.getElementById('f_boost_source_type')?.value || 'NONE').toUpperCase();
  const boostDepartmentIds = selectedIdsFromField('f_boost_department_id');
  const boostDepartmentTitles = selectedDepartmentTitlesFromField('f_boost_department_id');
  const minimumMinor = parseMoneyRubToMinor(document.getElementById('f_minimum_guarantee_minor')?.value || '');
  const minimumScope = String(document.getElementById('f_minimum_guarantee_scope')?.value || 'MONTH').toUpperCase();
  const boostMetric = findKpiMetricById(document.getElementById('f_boost_kpi_metric_id')?.value);
  const kpiMetric = findKpiMetricById(document.getElementById('f_kpi_metric_id')?.value);
  const kpiCalculationMode = String(document.getElementById('f_kpi_calculation_mode')?.value || 'FIXED').toUpperCase();
  const salaryAccrualDay = String(document.getElementById('f_salary_accrual_day')?.value || '').trim();
  const weekdayRates = readWeekdayRates();
  const thresholdValue = String(document.getElementById('f_threshold_value')?.value || '').trim();
  const boostThresholdValue = String(document.getElementById('f_boost_threshold_value')?.value || '').trim();
  let heading = titleRaw || typeTitle;
  const bits = [];
  if (type === 'SALARY_FIXED_MONTH' || type === 'SALARY_PER_SHIFT' || type === 'MINIMUM_PAYOUT') {
    if (amountMinor != null) bits.push(type === 'MINIMUM_PAYOUT' ? `доплата до ${fmtMoneyMinor(amountMinor)} ${minimumPayoutScopeLabel(minimumScope)}` : fmtMoneyMinor(amountMinor));
    if (type === 'SALARY_FIXED_MONTH' && salaryAccrualDay) bits.push(`начисление ${salaryAccrualDay}-го числа`);
  } else if (type === 'SALARY_HOURLY') {
    if (rateMinor != null) bits.push(`${fmtMoneyMinor(rateMinor)} / час`);
  } else if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
    if (percentBps != null) bits.push(fmtPercentBps(percentBps));
    if (type === 'PERCENT_DEPARTMENT_REVENUE' && departmentTitles.length) bits.push(departmentTitles.join(' + '));
    if (baseScope) bits.push(baseScopeLabel(baseScope));
    if (minimumMinor != null) bits.push(`мин ${fmtMoneyMinor(minimumMinor)} ${minimumGuaranteeScopeLabel(minimumScope)}`);
    if (boostEnabled && boostPercentBps != null) {
      const boostBits = [`boost ${fmtPercentBps(boostPercentBps)}`];
      if (boostSourceType && boostSourceType !== 'NONE') boostBits.push(boostSourceLabel(boostSourceType));
      if (boostDepartmentIds.length && boostDepartmentTitles.length) boostBits.push(boostDepartmentTitles.join(' + '));
      if (boostMetric?.title) boostBits.push(boostMetric.title);
      if (boostThresholdValue && boostSourceType === 'KPI_METRIC') boostBits.push(`цель ${boostThresholdValue}`);
      bits.push(boostBits.join(' · '));
    }
  } else if (type === 'KPI_BONUS') {
    if (kpiMetric?.title) bits.push(kpiMetric.title);
    if (thresholdValue) bits.push(`порог ${thresholdValue}`);
    if (kpiCalculationMode === 'PERCENT') {
      if (percentBps != null) bits.push(`${fmtPercentBps(percentBps)} от KPI`);
      bits.push('по закрытым сменам сотрудника');
    }
  }
  if ((type === 'SALARY_HOURLY' || type === 'SALARY_PER_SHIFT') && weekdayRates.length) {
    const weekdayNames = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];
    bits.push(`отдельные ставки: ${weekdayRates.map((row) => weekdayNames[row.weekday]).join(", ")}`);
  }
  box.innerHTML = `
    <div class="pay-config-summary__eyebrow">Как будет работать компонент</div>
    <div class="pay-config-summary__title">${esc(heading)}</div>
    <div class="pay-config-summary__meta">${esc(bits.filter(Boolean).join(' · ') || 'Заполни поля — здесь появится краткая схема расчёта.')}</div>
  `;
  setVisible(box, true);
}

function syncComponentSimulator() {
  const type = String(document.getElementById("f_component_type")?.value || "").toUpperCase();
  const wrap = document.getElementById("f_sim_wrap");
  const result = document.getElementById("f_sim_result");
  if (!wrap || !result) return;
  if (!["PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"].includes(type)) {
    setVisible(wrap, false);
    return;
  }
  setVisible(wrap, true);
  const baseMinor = parseMoneyRubToMinor(document.getElementById("f_sim_base_rub")?.value || "") || 0;
  const percentBps = parsePercentInputToBps(document.getElementById("f_percent")?.value || "") || 0;
  const boostEnabled = !!document.getElementById("f_boost_enabled")?.checked;
  const boostPercentBps = parsePercentInputToBps(document.getElementById("f_boost_percent")?.value || "") || 0;
  const sourceType = String(document.getElementById("f_boost_source_type")?.value || "NONE").toUpperCase();
  const recalcMode = String(document.getElementById("f_boost_recalc_mode")?.value || "REPLACE_ALL").toUpperCase();
  const minimumMinor = parseMoneyRubToMinor(document.getElementById("f_minimum_guarantee_minor")?.value || "");
  const minimumScope = String(document.getElementById("f_minimum_guarantee_scope")?.value || "MONTH").toUpperCase();
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
  setVisible(simTargetWrap, boostEnabled && sourceType !== "NONE");
  setVisible(simActualWrap, boostEnabled && sourceType !== "NONE");
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
    note += ` Сработала минимальная гарантия ${fmtMoneyMinor(minimumMinor)} ${minimumGuaranteeScopeLabel(minimumScope)}.`;
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
  const salaryAccrualDayWrap = document.getElementById("f_salary_accrual_day_wrap");
  const weekdayRatesSection = document.getElementById("f_weekday_rates_section");
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
  const minScopeWrap = document.getElementById("f_min_scope_wrap");
  const maxWrap = document.getElementById("f_max_wrap");
  const percentHelp = document.getElementById("f_percent_help");
  const simWrap = document.getElementById("f_sim_wrap");
  const kpiMetricWrap = document.getElementById("f_kpi_metric_wrap");
  const kpiMetricHint = document.getElementById("f_kpi_metric_hint");
  const kpiCalculationModeWrap = document.getElementById("f_kpi_calculation_mode_wrap");
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
  const kpiCalculationMode = String(document.getElementById("f_kpi_calculation_mode")?.value || "FIXED").toUpperCase();
  const percentSection = document.getElementById('f_percent_section');
  const boostSection = document.getElementById('f_boost_section');
  const limitsSection = document.getElementById('f_limits_section');
  const simSection = document.getElementById('f_sim_section');
  const kpiSection = document.getElementById('f_kpi_section');
  const boostDetails = document.getElementById('f_boost_details');
  const minimumScopeSelect = document.getElementById('f_minimum_guarantee_scope');
  const minimumScopeDayOption = minimumScopeSelect?.querySelector('option[value="DAY"]');
  const minimumScopeShiftOption = minimumScopeSelect?.querySelector('option[value="SHIFT"]');

  if (minimumScopeDayOption) minimumScopeDayOption.hidden = type === "MINIMUM_PAYOUT";
  if (minimumScopeShiftOption) minimumScopeShiftOption.hidden = type !== "MINIMUM_PAYOUT";
  if (minimumScopeSelect && type === "MINIMUM_PAYOUT" && String(minimumScopeSelect.value || "MONTH").toUpperCase() === "DAY") {
    minimumScopeSelect.value = "SHIFT";
  }
  if (minimumScopeSelect && type !== "MINIMUM_PAYOUT" && String(minimumScopeSelect.value || "MONTH").toUpperCase() === "SHIFT") {
    minimumScopeSelect.value = "MONTH";
  }

  [amountWrap, rateWrap, percentWrap, salaryAccrualDayWrap, weekdayRatesSection, departmentWrap, departmentHint, baseScopeWrap, boostEnabledWrap, boostPercentWrap, boostSourceWrap, boostDepartmentWrap, boostDepartmentHint, boostRecalcWrap, boostKpiMetricWrap, boostThresholdWrap, minWrap, minScopeWrap, maxWrap, percentHelp, simWrap, kpiMetricWrap, kpiMetricHint, kpiCalculationModeWrap, thresholdWrap, useStepsWrap, stepsWrap, stepsHint, percentSection, boostSection, limitsSection, simSection, kpiSection, boostDetails].forEach((el) => {
    setVisible(el, false);
  });

  if (type === "SALARY_HOURLY") {
    setVisible(rateWrap, true);
    setVisible(weekdayRatesSection, true);
    document.querySelectorAll("[data-weekday-unit]").forEach((element) => { element.textContent = "₽ / час"; });
    if (rateLabel) rateLabel.textContent = "Ставка, ₽ / час";
    syncComponentSummary();
    return syncComponentSimulator();
  }

  if (type === "SALARY_FIXED_MONTH" || type === "SALARY_PER_SHIFT" || type === "MINIMUM_PAYOUT") {
    setVisible(amountWrap, true);
    setVisible(weekdayRatesSection, type === "SALARY_PER_SHIFT");
    if (type === "SALARY_PER_SHIFT") {
      document.querySelectorAll("[data-weekday-unit]").forEach((element) => { element.textContent = "₽ / смена"; });
    }
    setVisible(salaryAccrualDayWrap, type === "SALARY_FIXED_MONTH");
    if (type === "MINIMUM_PAYOUT") {
      setVisible(limitsSection, true);
      setVisible(minScopeWrap, true);
    }
    if (amountLabel) {
      amountLabel.textContent = type === "SALARY_PER_SHIFT"
        ? "Сумма, ₽ / смена"
        : (type === "MINIMUM_PAYOUT" ? "Минимум к выплате, ₽" : "Сумма, ₽ / месяц");
    }
    syncComponentSummary();
    return syncComponentSimulator();
  }

  if (type === "PERCENT_TOTAL_REVENUE" || type === "PERCENT_DEPARTMENT_REVENUE") {
    [percentSection, boostSection, limitsSection, simSection, percentWrap, baseScopeWrap, boostEnabledWrap, minWrap, minScopeWrap, maxWrap, percentHelp, simWrap].forEach((element) => setVisible(element, true));
    if (type === "PERCENT_DEPARTMENT_REVENUE") {
      setVisible(departmentWrap, true);
      setVisible(departmentHint, true);
      if (percentLabel) percentLabel.textContent = "Процент от выручки департамента";
    } else if (percentLabel) {
      percentLabel.textContent = "Процент от общей выручки";
    }
    if (boostEnabled) {
      [boostDetails, boostPercentWrap, boostSourceWrap, boostRecalcWrap].forEach((element) => setVisible(element, true));
      setVisible(boostDepartmentWrap, isDepartmentBoostSource(boostSourceType));
      setVisible(boostDepartmentHint, isDepartmentBoostSource(boostSourceType));
      if (boostSourceType === "KPI_METRIC") {
        setVisible(boostKpiMetricWrap, true);
        setVisible(boostThresholdWrap, true);
        if (boostThresholdLabel) boostThresholdLabel.textContent = `Цель KPI${selectedBoostMetric ? ` (${String(selectedBoostMetric.unit || 'QTY').toUpperCase()})` : ''}`;
      }
    }
    syncComponentSummary();
    syncComponentSimulator();
    syncComponentConfigHint();
    return;
  }

  if (type === "KPI_BONUS") {
    [kpiSection, kpiMetricWrap, kpiMetricHint, kpiCalculationModeWrap, thresholdWrap, stepsHint].forEach((element) => setVisible(element, true));
    if (thresholdLabel) {
      thresholdLabel.textContent = kpiCalculationMode === "PERCENT"
        ? `Минимальное значение KPI, необязательно${selectedBonusMetric ? ` (${String(selectedBonusMetric.unit || 'QTY').toUpperCase()})` : ''}`
        : `Порог KPI${selectedBonusMetric ? ` (${String(selectedBonusMetric.unit || 'QTY').toUpperCase()})` : ''}`;
    }
    setVisible(useStepsWrap, kpiCalculationMode === "FIXED");
    setVisible(stepsWrap, kpiCalculationMode === "FIXED" && useSteps);
    if (kpiCalculationMode === "PERCENT") {
      setVisible(percentWrap, true);
      if (percentLabel) percentLabel.textContent = "Процент от значения KPI";
    } else if (!useSteps) {
      setVisible(amountWrap, true);
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
  document.getElementById("f_minimum_guarantee_scope")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_base_scope")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_kpi_metric_id")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_kpi_calculation_mode")?.addEventListener("change", syncComponentFields);
  document.getElementById("f_salary_accrual_day")?.addEventListener("change", syncComponentSummary);
  document.getElementById("f_boost_kpi_metric_id")?.addEventListener("change", syncComponentFields);
  document.querySelectorAll("[data-weekday-enabled]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const weekday = Number(checkbox.dataset.weekdayEnabled);
      const input = document.querySelector(`[data-weekday-rate="${weekday}"]`);
      if (input) {
        input.disabled = !checkbox.checked;
        if (checkbox.checked && !String(input.value || "").trim()) {
          const type = String(document.getElementById("f_component_type")?.value || "").toUpperCase();
          const baseInput = type === "SALARY_HOURLY"
            ? document.getElementById("f_rate_minor")
            : document.getElementById("f_amount_minor");
          input.value = String(baseInput?.value || "");
        }
      }
      syncComponentSummary();
    });
  });
  document.querySelectorAll("[data-weekday-rate]").forEach((input) => {
    input.addEventListener("input", syncComponentSummary);
  });
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
    const departmentIds = selectedIdsFromField("f_department_id");
    const baseScope = String(document.getElementById("f_base_scope")?.value || "").trim().toUpperCase();
    const boostEnabled = !!document.getElementById("f_boost_enabled")?.checked;
    const boostPercentRaw = String(document.getElementById("f_boost_percent")?.value || "").trim();
    const boostSourceType = String(document.getElementById("f_boost_source_type")?.value || "NONE").trim().toUpperCase();
    const boostRecalcMode = String(document.getElementById("f_boost_recalc_mode")?.value || "REPLACE_ALL").trim().toUpperCase();
    const boostDepartmentIds = selectedIdsFromField("f_boost_department_id");
    const boostKpiMetricRaw = String(document.getElementById("f_boost_kpi_metric_id")?.value || "").trim();
    const boostThresholdRaw = String(document.getElementById("f_boost_threshold_value")?.value || "").trim();
    const minGuaranteeRaw = String(document.getElementById("f_minimum_guarantee_minor")?.value || "").trim();
    const minGuaranteeScope = String(document.getElementById("f_minimum_guarantee_scope")?.value || "MONTH").trim().toUpperCase();
    const maxCapRaw = String(document.getElementById("f_maximum_cap_minor")?.value || "").trim();
    const sortRaw = String(document.getElementById("f_sort_order")?.value || "0").trim();
    const salaryAccrualDayRaw = String(document.getElementById("f_salary_accrual_day")?.value || "").trim();
    const isActive = !!document.getElementById("f_active")?.checked;

    if (!title) {
      toast("Укажи название компонента", "warn");
      return;
    }

    const kpiMetricRaw = String(document.getElementById("f_kpi_metric_id")?.value || "").trim();
    const thresholdRaw = String(document.getElementById("f_threshold_value")?.value || "").trim();
    const useSteps = !!document.getElementById("f_use_steps")?.checked;
    const kpiCalculationMode = String(document.getElementById("f_kpi_calculation_mode")?.value || "FIXED").trim().toUpperCase();

    const payload = {
      component_type: componentType,
      title,
      amount_minor: null,
      rate_minor: null,
      weekday_rates: [],
      percent_bps: null,
      department_id: null,
      department_ids: null,
      kpi_metric_id: null,
      threshold_value: null,
      steps_json: null,
      kpi_calculation_mode: "FIXED",
      salary_accrual_day: null,
      base_scope: null,
      boost_enabled: false,
      boost_percent_bps: null,
      boost_source_type: null,
      boost_recalc_mode: null,
      boost_department_id: null,
      boost_department_ids: null,
      boost_kpi_metric_id: null,
      boost_threshold_value: null,
      minimum_guarantee_minor: null,
      minimum_guarantee_scope: null,
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
      const weekdayRates = readWeekdayRates({ validate: true });
      if (weekdayRates === false) {
        toast("Заполни ставку для каждого выбранного дня", "warn");
        return;
      }
      payload.weekday_rates = weekdayRates;
    } else if (componentType === "SALARY_FIXED_MONTH" || componentType === "SALARY_PER_SHIFT" || componentType === "MINIMUM_PAYOUT") {
      if (!amountMinorRaw) {
        toast("Укажи сумму в рублях", "warn");
        return;
      }
      payload.amount_minor = parseMoneyRubToMinor(amountMinorRaw);
      if (payload.amount_minor === null) {
        toast("Некорректная сумма", "warn");
        return;
      }
      if (componentType === "SALARY_PER_SHIFT") {
        const weekdayRates = readWeekdayRates({ validate: true });
        if (weekdayRates === false) {
          toast("Заполни ставку для каждого выбранного дня", "warn");
          return;
        }
        payload.weekday_rates = weekdayRates;
      }
      if (componentType === "MINIMUM_PAYOUT") {
        payload.minimum_guarantee_scope = minGuaranteeScope === "SHIFT" || minGuaranteeScope === "DAY" ? "SHIFT" : "MONTH";
      } else if (componentType === "SALARY_FIXED_MONTH" && salaryAccrualDayRaw) {
        payload.salary_accrual_day = Number(salaryAccrualDayRaw);
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
        if (!departmentIds.length) {
          toast("Выбери один или несколько департаментов", "warn");
          return;
        }
        payload.department_ids = departmentIds;
        payload.department_id = departmentIds[0];
      }
      if (minGuaranteeRaw) {
        payload.minimum_guarantee_minor = parseMoneyRubToMinor(minGuaranteeRaw);
        if (payload.minimum_guarantee_minor == null) {
          toast("Некорректная минимальная гарантия", "warn");
          return;
        }
        payload.minimum_guarantee_scope = minGuaranteeScope === "DAY" ? "DAY" : "MONTH";
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
          if (!boostDepartmentIds.length) {
            toast("Выбери один или несколько департаментов для условия повышения", "warn");
            return;
          }
          payload.boost_department_ids = boostDepartmentIds;
          payload.boost_department_id = boostDepartmentIds[0];
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
      payload.kpi_calculation_mode = kpiCalculationMode === "PERCENT" ? "PERCENT" : "FIXED";
      if (thresholdRaw) payload.threshold_value = Number(thresholdRaw);
      if (payload.kpi_calculation_mode === "PERCENT") {
        const selectedMetric = findKpiMetricById(payload.kpi_metric_id);
        if (selectedMetric && String(selectedMetric.unit || "").toUpperCase() !== "RUB") {
          toast("Процент можно считать только от KPI с единицей ₽", "warn");
          return;
        }
        const percentBps = parsePercentInputToBps(percentRaw);
        if (percentBps === null) {
          toast("Укажи процент от KPI, например 5", "warn");
          return;
        }
        payload.percent_bps = percentBps;
      } else if (useSteps) {
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

return { openComponentEditor };
}

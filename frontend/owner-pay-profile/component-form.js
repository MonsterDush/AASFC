
export function createPayComponentFormRenderer({ state, esc, support }) {
const {
  selectedDepartmentIdsFor,
  selectedBoostDepartmentIdsFor,
  departmentsOptionsMarkup,
  moneyInputFromMinor,
  percentInputFromBps,
  baseScopeOptions,
  percentBoostOptions,
  boostRecalcOptions,
  stepsRowsMarkup,
} = support;

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

const WEEKDAYS = [
  [0, "Понедельник"],
  [1, "Вторник"],
  [2, "Среда"],
  [3, "Четверг"],
  [4, "Пятница"],
  [5, "Суббота"],
  [6, "Воскресенье"],
];

function componentForm({ mode, item }) {
  const it = item || {};
  const type = String(it.component_type || "SALARY_FIXED_MONTH").toUpperCase();
  const activeChecked = (mode === "edit" ? !!it.is_active : true) ? "checked" : "";
  const hasDepartments = Array.isArray(state.departments) && state.departments.length > 0;
  const departmentIds = selectedDepartmentIdsFor(it);
  const boostDepartmentIds = selectedBoostDepartmentIdsFor(it);
  const departmentOptions = departmentsOptionsMarkup(departmentIds);
  const boostDepartmentOptions = departmentsOptionsMarkup(boostDepartmentIds);
  const minScope = String(it.effective_minimum_guarantee_scope || it.minimum_guarantee_scope || "MONTH").toUpperCase();
  const hasKpiMetrics = Array.isArray(state.kpiMetrics) && state.kpiMetrics.length > 0;
  const kpiOptions = state.kpiMetrics.map((metric) => `<option value="${esc(metric.id)}" data-unit="${esc(String(metric?.unit || "QTY").toUpperCase())}" ${Number(metric.id) === Number(it.kpi_metric_id) ? "selected" : ""}>${esc(kpiMetricOptionLabel(metric))}</option>`).join("");
  const boostKpiOptions = state.kpiMetrics.map((metric) => `<option value="${esc(metric.id)}" ${Number(metric.id) === Number(it.boost_kpi_metric_id) ? "selected" : ""}>${esc(kpiMetricOptionLabel(metric))}</option>`).join("");
  const boostEnabled = it?.boost_enabled ? "checked" : "";
  const kpiCalculationMode = String(it.kpi_calculation_mode || "FIXED").toUpperCase();
  const salaryAccrualDay = Number(it.salary_accrual_day || 0);
  const salaryAccrualDayOptions = Array.from({ length: 31 }, (_, index) => index + 1)
    .map((day) => `<option value="${day}" ${salaryAccrualDay === day ? "selected" : ""}>${day}-е число</option>`)
    .join("");
  const weekdayRates = new Map(
    (Array.isArray(it.weekday_rates) ? it.weekday_rates : [])
      .map((row) => [Number(row?.weekday), row?.rate_minor]),
  );
  const weekdayRatesMarkup = WEEKDAYS.map(([weekday, title]) => {
    const enabled = weekdayRates.has(weekday);
    return `
      <div class="weekday-rate-row" data-weekday-row="${weekday}">
        <label class="chk weekday-rate-toggle">
          <input type="checkbox" data-weekday-enabled="${weekday}" ${enabled ? "checked" : ""} />
          <span>${esc(title)}</span>
        </label>
        <label class="weekday-rate-value">
          <span class="sr-only">Ставка для дня ${esc(title)}</span>
          <input inputmode="decimal" data-weekday-rate="${weekday}" placeholder="Базовая ставка" value="${esc(enabled ? moneyInputFromMinor(weekdayRates.get(weekday)) : "")}" ${enabled ? "" : "disabled"} />
          <span class="weekday-rate-unit" data-weekday-unit>₽</span>
        </label>
      </div>
    `;
  }).join("");
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
              <option value="MINIMUM_PAYOUT" ${type === "MINIMUM_PAYOUT" ? "selected" : ""}>Минимальная сумма к выплате</option>
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
          <label id="f_salary_accrual_day_wrap">
            <span>День начисления оклада</span>
            <select id="f_salary_accrual_day">
              <option value="">Не указан</option>
              ${salaryAccrualDayOptions}
            </select>
          </label>
        </div>
        <div class="form-section__grid">
          <label>
            <span>Порядок</span>
            <input id="f_sort_order" inputmode="numeric" placeholder="0" value="${esc(it.sort_order ?? 0)}" />
          </label>
          <label class="chk pay-form-check-bottom">
            <input type="checkbox" id="f_active" ${activeChecked} />
            <span>Компонент активен</span>
          </label>
        </div>
        <div id="f_live_summary" class="pay-config-summary"></div>
      </div>

      <div class="form-section" id="f_weekday_rates_section">
        <div class="form-section__head">
          <div class="form-section__title">Ставки по дням недели</div>
          <div class="form-section__subtitle">Необязательно. Включи нужные дни — в остальные дни будет действовать базовая ставка.</div>
        </div>
        <div class="weekday-rate-list">
          ${weekdayRatesMarkup}
        </div>
      </div>

      <div class="form-section" id="f_percent_section">
        <div class="form-section__head">
          <div class="form-section__title">Расчёт процента</div>
          <div class="form-section__subtitle">Настрой базу расчёта и, при необходимости, департамент.</div>
        </div>
        <div class="form-section__grid">
          ${hasDepartments ? `
          <label id="f_department_wrap">
            <span>Департаменты</span>
            <select id="f_department_id" multiple size="${Math.min(Math.max(state.departments.length, 3), 6)}">
              ${departmentOptions}
            </select>
          </label>` : `
          <label id="f_department_wrap">
            <span>Номера департаментов</span>
            <input id="f_department_id" inputmode="numeric" placeholder="Например: 1,2" value="${esc(departmentIds.join(","))}" />
          </label>
          <div id="f_department_hint" class="form-inline-note">Список департаментов не загрузился. Укажи номера вручную через запятую.</div>`}
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
            <span>Департаменты для условия</span>
            <select id="f_boost_department_id" multiple size="${Math.min(Math.max(state.departments.length, 3), 6)}">
              ${boostDepartmentOptions}
            </select>
          </label>` : `
          <label id="f_boost_department_wrap">
            <span>Номера департаментов для условия</span>
            <input id="f_boost_department_id" inputmode="numeric" placeholder="Например: 1,2" value="${esc(boostDepartmentIds.join(","))}" />
          </label>
          <div id="f_boost_department_hint" class="form-inline-note">Если условие связано с департаментами, укажи номера через запятую.</div>`}
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
        <div id="f_config_hint" class="hidden"></div>
      </div>

      <div class="form-section" id="f_limits_section">
        <div class="form-section__head">
          <div class="form-section__title">Ограничения</div>
          <div class="form-section__subtitle">Эти ограничения применяются уже после расчёта суммы компонента.</div>
        </div>
        <div class="form-section__grid">
          <label id="f_min_wrap">
            <span>Минимальная гарантия, ₽</span>
            <input id="f_minimum_guarantee_minor" inputmode="decimal" placeholder="Например: 6000" value="${esc(moneyInputFromMinor(it.minimum_guarantee_minor))}" />
          </label>
          <label id="f_min_scope_wrap">
            <span>Период минималки</span>
            <select id="f_minimum_guarantee_scope">
              <option value="MONTH" ${minScope === "MONTH" ? "selected" : ""}>За месяц</option>
              <option value="DAY" ${minScope === "DAY" ? "selected" : ""}>За день</option>
              <option value="SHIFT" ${minScope === "SHIFT" ? "selected" : ""}>За каждую отработанную смену</option>
            </select>
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
          <div class="form-section__subtitle">Используй фикс, ступени, процент от KPI в ₽ или сумму за каждую единицу количественного KPI.</div>
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
          <label id="f_kpi_calculation_mode_wrap">
            <span>Способ расчёта</span>
            <select id="f_kpi_calculation_mode">
              <option value="FIXED" ${kpiCalculationMode === "FIXED" ? "selected" : ""}>Фиксированная сумма / ступени</option>
              <option value="PERCENT" ${kpiCalculationMode === "PERCENT" ? "selected" : ""}>Процент от значения KPI</option>
              <option value="PER_UNIT" ${kpiCalculationMode === "PER_UNIT" ? "selected" : ""}>Сумма за каждую единицу KPI</option>
            </select>
          </label>
          <label id="f_threshold_wrap">
            <span id="f_threshold_label">Порог KPI</span>
            <input id="f_threshold_value" inputmode="numeric" placeholder="Например: 30" value="${esc(it.threshold_value ?? "")}" />
          </label>
          <label id="f_use_steps_wrap" class="chk pay-form-check-bottom">
            <input type="checkbox" id="f_use_steps" ${Array.isArray(it.steps) && it.steps.length ? "checked" : ""} />
            <span>Использовать ступени бонуса</span>
          </label>
        </div>
        <div id="f_steps_wrap" class="kpi-steps-builder">
          <div class="row row--between ai-center gap-8 mb-8">
            <div>
              <b>Ступени бонуса</b>
              <div class="muted mt-4">Будет выбрана максимальная подходящая ступень.</div>
            </div>
            <button class="btn sm" type="button" id="btnAddStep">+ Ступень</button>
          </div>
          <div id="f_steps_rows">${stepsRowsMarkup(it.steps)}</div>
        </div>
        <div id="f_steps_hint" class="form-inline-note">FIXED — фикс или ступени. PERCENT — только KPI в ₽. PER_UNIT — только количественный KPI (QTY), ставка умножается на факт по закрытым сменам сотрудника.</div>
      </div>
    </div>

    <div class="row row--end gap-8 mt-12">
      <button class="btn" id="btnCancel" type="button">Отмена</button>
      <button class="btn primary" id="btnSave" type="button">Сохранить</button>
    </div>
  `;
}

return { componentForm };
}

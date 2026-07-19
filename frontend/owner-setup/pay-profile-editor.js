export function createPayProfileSetupController(context) {
  const { toast, confirmModal, api, getDepartments, getKpiMetrics, getPayProfiles, getPayProfile, createPayProfile, updatePayProfile, deletePayProfile, createPayComponent, updatePayComponent, deletePayComponent, percentInputFromBps, moneyInputFromMinor, parseMoneyRubToMinor, parsePercentInputToBps, state, defaultPayComponentTitle, payComponentValueLabel, payComponentTypeOptions, buildSimpleOptions, syncInlinePayComponentFields, esc, getVisibleSteps, getStepByKey, getAdjacentUnlockedStep, moveToStep, loadSetup } = context;

  async function ensurePayProfileAuxData() {
    if (!Array.isArray(state.departments)) {
      try { state.departments = await getDepartments(state.venueId, { includeArchived: false }); } catch { state.departments = []; }
    }
    if (!Array.isArray(state.kpiMetrics)) {
      try { state.kpiMetrics = await getKpiMetrics(state.venueId, { includeArchived: false }); } catch { state.kpiMetrics = []; }
    }
  }

  async function loadInlinePayProfileDetail(profileId, { force = false } = {}) {
    const inlineState = state.inline.pay_profiles;
    if (!profileId) return null;
    const key = String(profileId);
    if (!force && inlineState.details && inlineState.details[key]) return inlineState.details[key];
    const detail = await getPayProfile(state.venueId, profileId);
    inlineState.details = inlineState.details || {};
    inlineState.details[key] = detail;
    return detail;
  }

  function buildPayProfileComponentEditor(detail, editingComponent = null) {
    const type = String(editingComponent?.component_type || 'SALARY_FIXED_MONTH').toUpperCase();
    return `
      <div class="setup-formgrid mt-12">
        <label>
          <span>Тип компонента</span>
          <select class="input" id="inlineComponentType">${payComponentTypeOptions(type)}</select>
        </label>
        <label>
          <span>Название</span>
          <input class="input" id="inlineComponentTitle" placeholder="Например, Ставка за час" value="${esc(editingComponent?.title || defaultPayComponentTitle(type))}" />
        </label>
        <label id="inlineComponentAmountRow" style="display:${['SALARY_FIXED_MONTH','SALARY_PER_SHIFT','KPI_BONUS','MINIMUM_PAYOUT'].includes(type) ? '' : 'none'}">
          <span>Сумма, ₽</span>
          <input class="input" id="inlineComponentAmount" inputmode="decimal" placeholder="0" value="${esc(moneyInputFromMinor(editingComponent?.amount_minor))}" />
        </label>
        <label id="inlineComponentMinimumScopeRow" style="display:${type === 'MINIMUM_PAYOUT' ? '' : 'none'}">
          <span>Период минимума</span>
          <select class="input" id="inlineComponentMinimumScope">
            <option value="MONTH" ${String(editingComponent?.effective_minimum_guarantee_scope || editingComponent?.minimum_guarantee_scope || 'MONTH').toUpperCase() === 'MONTH' ? 'selected' : ''}>За месяц</option>
            <option value="SHIFT" ${['SHIFT','DAY'].includes(String(editingComponent?.effective_minimum_guarantee_scope || editingComponent?.minimum_guarantee_scope || '').toUpperCase()) ? 'selected' : ''}>За каждую отработанную смену</option>
          </select>
        </label>
        <label id="inlineComponentRateRow" style="display:${type === 'SALARY_HOURLY' ? '' : 'none'}">
          <span>Ставка в час, ₽</span>
          <input class="input" id="inlineComponentRate" inputmode="decimal" placeholder="0" value="${esc(moneyInputFromMinor(editingComponent?.rate_minor))}" />
        </label>
        <label id="inlineComponentPercentRow" style="display:${['PERCENT_TOTAL_REVENUE','PERCENT_DEPARTMENT_REVENUE'].includes(type) ? '' : 'none'}">
          <span>Процент</span>
          <input class="input" id="inlineComponentPercent" inputmode="decimal" placeholder="0" value="${esc(percentInputFromBps(editingComponent?.percent_bps))}" />
        </label>
        <label id="inlineComponentDepartmentRow" style="display:${type === 'PERCENT_DEPARTMENT_REVENUE' ? '' : 'none'}">
          <span>Департамент</span>
          <select class="input" id="inlineComponentDepartmentId">${buildSimpleOptions(state.departments || [], editingComponent?.department_id, 'Выбери департамент')}</select>
        </label>
        <label id="inlineComponentKpiRow" style="display:${type === 'KPI_BONUS' ? '' : 'none'}">
          <span>KPI</span>
          <select class="input" id="inlineComponentKpiMetricId">${buildSimpleOptions(state.kpiMetrics || [], editingComponent?.kpi_metric_id, 'Выбери KPI')}</select>
        </label>
        <label>
          <span>Активность</span>
          <select class="input" id="inlineComponentActive">
            <option value="1" ${(editingComponent?.is_active === false) ? '' : 'selected'}>Активен</option>
            <option value="0" ${(editingComponent?.is_active === false) ? 'selected' : ''}>Неактивен</option>
          </select>
        </label>
      </div>
    `;
  }

  function renderPayProfileComponentsBlock(detail, inlineState) {
    const selectedProfile = detail?.title || 'Профиль';
    const components = Array.isArray(detail?.components) ? detail.components : [];
    const editingId = inlineState.componentEditor?.id || null;
    const editingComponent = editingId ? components.find((item) => String(item.id) === String(editingId)) : null;
    const mode = editingComponent ? 'edit' : 'create';
    return `
      <div class="setup-formcard mt-12">
        <div class="setup-editor__title">Компоненты профиля «${esc(selectedProfile)}»</div>
        <div class="muted mt-6">Здесь можно сразу собрать правила начисления для выбранного профиля.</div>
        <div class="setup-minirows mt-12">
          ${components.length ? components.map((item) => `
            <div class="setup-minirow">
              <div class="setup-minirow__main">
                <div class="setup-minirow__titlewrap">
                  <b>${esc(item.title || defaultPayComponentTitle(item.component_type))}</b>
                  ${item.is_active === false ? '<span class="badge">неактивен</span>' : ''}
                </div>
                <div class="setup-minirow__meta">${esc(payComponentValueLabel(item))}</div>
              </div>
              <div class="setup-minirow__actions">
                <button class="btn sm" type="button" data-inline-edit-component="${esc(item.id)}">Изменить</button>
                <button class="btn sm danger" type="button" data-inline-delete-component="${esc(item.id)}">Удалить</button>
              </div>
            </div>
          `).join('') : '<div class="setup-empty">Компоненты ещё не добавлены. Создай хотя бы один, чтобы профиль был готов к работе.</div>'}
        </div>
        <div class="setup-editor__title mt-12">${mode === 'edit' ? 'Редактирование компонента' : 'Новый компонент'}</div>
        ${buildPayProfileComponentEditor(detail, editingComponent)}
        <div class="setup-actionbar mt-12">
          <button class="btn primary" id="btnInlineSaveComponent" type="button">${mode === 'edit' ? 'Сохранить компонент' : 'Добавить компонент'}</button>
          ${mode === 'edit' ? '<button class="btn subtle" id="btnInlineCancelComponentEdit" type="button">Отмена</button>' : ''}
        </div>
      </div>
    `;
  }

  async function loadInlinePayProfiles({ force = false } = {}) {
    const inlineState = state.inline.pay_profiles;
    if (!force && Array.isArray(inlineState.items)) return inlineState.items;
    inlineState.loading = true;
    try {
      const items = await getPayProfiles(state.venueId, { includeInactive: true });
      inlineState.items = Array.isArray(items) ? items : [];
      return inlineState.items;
    } finally {
      inlineState.loading = false;
    }
  }

  function renderPayProfilesEditor(items, currentStep) {
    const inlineState = state.inline.pay_profiles;
    const visibleItems = inlineState.showInactive ? items : items.filter((item) => item.is_active !== false);
    const editingId = inlineState.editor?.id || null;
    const editingItem = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
    const mode = editingItem ? "edit" : "create";
    const selectedProfileId = inlineState.selectedProfileId || editingId || "";
    const detail = selectedProfileId ? (inlineState.details?.[String(selectedProfileId)] || null) : null;
    const activeCount = items.filter((item) => item.is_active !== false).length;
    return `
      <div class="setup-editor__panel">
        <div class="setup-editor__toolbar">
          <div class="setup-editor__title">Профили зарплаты</div>
          <label class="setup-toggle">
            <input type="checkbox" id="inlineShowInactiveProfiles" ${inlineState.showInactive ? "checked" : ""} />
            <span>Показывать неактивные</span>
          </label>
        </div>
        <div class="setup-editor__grid mt-12">
          <div>
            <div class="setup-minirows">
              ${visibleItems.length ? visibleItems.map((item) => `
                <div class="setup-minirow">
                  <div class="setup-minirow__main">
                    <div class="setup-minirow__titlewrap">
                      <b>${esc(item.title)}</b>
                      ${item.is_active === false ? '<span class="badge">неактивен</span>' : ''}
                      ${String(selectedProfileId) === String(item.id) ? '<span class="badge">выбран</span>' : ''}
                    </div>
                    <div class="setup-minirow__meta">${esc(item.description || 'Без описания')}${Number(item.components_count || 0) > 0 ? ' · Компоненты настроены' : ' · Компоненты пока не добавлены'}</div>
                  </div>
                  <div class="setup-minirow__actions">
                    <button class="btn sm" type="button" data-inline-select-profile="${esc(item.id)}">Компоненты</button>
                    <button class="btn sm" type="button" data-inline-edit-profile="${esc(item.id)}">Изменить</button>
                    <button class="btn sm ${item.is_active === false ? '' : 'danger'}" type="button" data-inline-toggle-profile="${esc(item.id)}">${item.is_active === false ? 'Включить' : 'Отключить'}</button>
                    <button class="btn sm danger" type="button" data-inline-delete-profile="${esc(item.id)}">Удалить</button>
                  </div>
                </div>
              `).join('') : '<div class="setup-empty">Пока нет профилей зарплаты. Создай хотя бы один базовый профиль, чтобы потом связать его с должностями.</div>'}
            </div>
          </div>
          <div>
            <div class="setup-formcard">
              <div class="setup-editor__title">${mode === 'edit' ? 'Редактирование профиля' : 'Новый профиль'}</div>
              <div class="muted mt-6">Профили создаются без назначения на сотрудников. Сейчас важно собрать базовые шаблоны.</div>
              <div class="setup-formgrid mt-12">
                <label>
                  <span>Название</span>
                  <input class="input" id="inlineProfileTitle" placeholder="Например, Официант / Бар" value="${esc(editingItem?.title || '')}" />
                </label>
                <label>
                  <span>Активность</span>
                  <select class="input" id="inlineProfileActive">
                    <option value="1" ${(editingItem?.is_active === false) ? '' : 'selected'}>Активен</option>
                    <option value="0" ${(editingItem?.is_active === false) ? 'selected' : ''}>Неактивен</option>
                  </select>
                </label>
                <label style="grid-column:1 / -1">
                  <span>Описание</span>
                  <textarea class="input" id="inlineProfileDescription" rows="4" placeholder="Коротко опиши, для какой роли нужен этот профиль">${esc(editingItem?.description || '')}</textarea>
                </label>
              </div>
              <div class="setup-actionbar mt-12">
                <button class="btn primary" id="btnInlineSaveProfile" type="button">${mode === 'edit' ? 'Сохранить' : 'Создать'}</button>
                ${mode === 'edit' ? '<button class="btn subtle" id="btnInlineCancelProfileEdit" type="button">Отмена</button>' : ''}
              </div>
            </div>
            ${detail ? renderPayProfileComponentsBlock(detail, inlineState) : (activeCount > 0 ? '<div class="setup-inline-note">Выбери профиль слева, чтобы сразу настроить его компоненты.</div>' : '')}
          </div>
        </div>
        <div class="setup-actionbar mt-14">
          ${activeCount > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteProfiles" type="button">Подтвердить шаг</button>' : ''}
          ${activeCount > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteProfilesNext" type="button">Подтвердить и дальше</button>' : ''}
        </div>
      </div>
    `;
  }

  async function mountPayProfilesEditor(currentStep) {
    const host = document.getElementById('setupInlineEditor');
    if (!host) return;
    host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
    await ensurePayProfileAuxData();
    const items = await loadInlinePayProfiles();
    const inlineState = state.inline.pay_profiles;
    if (Number(currentStep.count || 0) !== items.filter((item) => item.is_active !== false).length) {
      await loadSetup({ preserveSelection: true });
      return;
    }
    if (inlineState.selectedProfileId && !items.some((item) => String(item.id) === String(inlineState.selectedProfileId))) {
      inlineState.selectedProfileId = null;
      inlineState.componentEditor = { mode: 'create', id: null };
    }
    if (inlineState.selectedProfileId) {
      try { await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true }); } catch {}
    }
    host.innerHTML = renderPayProfilesEditor(items, getStepByKey('pay_profiles') || currentStep);

    document.getElementById('inlineShowInactiveProfiles')?.addEventListener('change', async (e) => {
      inlineState.showInactive = !!e.target?.checked;
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
    });

    document.getElementById('btnInlineCancelProfileEdit')?.addEventListener('click', async () => {
      inlineState.editor = { mode: 'create', id: null };
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
    });

    document.getElementById('btnInlineSaveProfile')?.addEventListener('click', async () => {
      const title = String(document.getElementById('inlineProfileTitle')?.value || '').trim();
      const description = String(document.getElementById('inlineProfileDescription')?.value || '').trim();
      const is_active = String(document.getElementById('inlineProfileActive')?.value || '1') === '1';
      if (!title) return toast('Укажи название профиля', 'err');
      try {
        let saved = null;
        if (inlineState.editor?.id) saved = await updatePayProfile(state.venueId, inlineState.editor.id, { title, description: description || null, is_active });
        else saved = await createPayProfile(state.venueId, { title, description: description || null, is_active });
        inlineState.editor = { mode: 'create', id: null };
        if (saved?.id) inlineState.selectedProfileId = saved.id;
        await loadInlinePayProfiles({ force: true });
        if (inlineState.selectedProfileId) await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
        await loadSetup({ preserveSelection: true });
        await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
        if (!currentStep.completed) {
          try {
            await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'pay_profiles' } });
            await loadSetup({ preserveSelection: true });
          } catch {}
        }
        toast('Профиль сохранён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось сохранить профиль', 'err');
      }
    });

    host.querySelectorAll('[data-inline-select-profile]').forEach((btn) => btn.addEventListener('click', async () => {
      inlineState.selectedProfileId = btn.getAttribute('data-inline-select-profile') || null;
      inlineState.componentEditor = { mode: 'create', id: null };
      await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
    }));

    host.querySelectorAll('[data-inline-edit-profile]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-inline-edit-profile') || null;
      inlineState.editor = { mode: 'edit', id };
      inlineState.selectedProfileId = id;
      await loadInlinePayProfileDetail(id, { force: true });
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
    }));

    host.querySelectorAll('[data-inline-toggle-profile]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-inline-toggle-profile') || '';
      const item = (state.inline.pay_profiles.items || []).find((row) => String(row.id) === String(id));
      if (!item) return;
      try {
        await updatePayProfile(state.venueId, item.id, { is_active: !(item.is_active !== false) });
        await loadInlinePayProfiles({ force: true });
        if (inlineState.selectedProfileId) await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
        await loadSetup({ preserveSelection: true });
        await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
        toast('Состояние профиля обновлено', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось изменить профиль', 'err');
      }
    }));

    host.querySelectorAll('[data-inline-delete-profile]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-inline-delete-profile') || '';
      const item = (state.inline.pay_profiles.items || []).find((row) => String(row.id) === String(id));
      if (!item) return;
      const ok = await confirmModal({ title: 'Удалить профиль?', text: `Профиль «${item.title}» будет удалён безвозвратно.`, confirmText: 'Удалить', danger: true });
      if (!ok) return;
      try {
        await deletePayProfile(state.venueId, item.id);
        if (String(inlineState.selectedProfileId || '') === String(item.id)) inlineState.selectedProfileId = null;
        await loadInlinePayProfiles({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
        toast('Профиль удалён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось удалить профиль', 'err');
      }
    }));

    document.getElementById('inlineComponentType')?.addEventListener('change', () => {
      const titleEl = document.getElementById('inlineComponentTitle');
      if (titleEl && !String(titleEl.value || '').trim()) titleEl.value = defaultPayComponentTitle(document.getElementById('inlineComponentType')?.value || '');
      syncInlinePayComponentFields();
    });
    syncInlinePayComponentFields();

    document.getElementById('btnInlineCancelComponentEdit')?.addEventListener('click', async () => {
      inlineState.componentEditor = { mode: 'create', id: null };
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
    });

    host.querySelectorAll('[data-inline-edit-component]').forEach((btn) => btn.addEventListener('click', async () => {
      inlineState.componentEditor = { mode: 'edit', id: btn.getAttribute('data-inline-edit-component') || null };
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
    }));

    host.querySelectorAll('[data-inline-delete-component]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-inline-delete-component') || '';
      if (!inlineState.selectedProfileId) return;
      const detail = await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
      const item = (detail?.components || []).find((row) => String(row.id) === String(id));
      if (!item) return;
      const ok = await confirmModal({ title: 'Удалить компонент?', text: `Компонент «${item.title || defaultPayComponentTitle(item.component_type)}» будет удалён.`, confirmText: 'Удалить', danger: true });
      if (!ok) return;
      try {
        await deletePayComponent(state.venueId, item.id);
        inlineState.componentEditor = { mode: 'create', id: null };
        await loadInlinePayProfiles({ force: true });
        await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
        await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
        toast('Компонент удалён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось удалить компонент', 'err');
      }
    }));

    document.getElementById('btnInlineSaveComponent')?.addEventListener('click', async () => {
      const profileId = inlineState.selectedProfileId;
      if (!profileId) return toast('Сначала выбери профиль', 'err');
      const type = String(document.getElementById('inlineComponentType')?.value || 'SALARY_FIXED_MONTH').toUpperCase();
      const title = String(document.getElementById('inlineComponentTitle')?.value || '').trim() || defaultPayComponentTitle(type);
      const is_active = String(document.getElementById('inlineComponentActive')?.value || '1') === '1';
      const payload = { component_type: type, title, is_active };
      try {
        if (type === 'SALARY_FIXED_MONTH' || type === 'SALARY_PER_SHIFT' || type === 'KPI_BONUS' || type === 'MINIMUM_PAYOUT') {
          const amount_minor = parseMoneyRubToMinor(document.getElementById('inlineComponentAmount')?.value || '');
          if (amount_minor == null) return toast('Укажи сумму', 'err');
          payload.amount_minor = amount_minor;
          if (type === 'MINIMUM_PAYOUT') {
            const scope = String(document.getElementById('inlineComponentMinimumScope')?.value || 'MONTH').toUpperCase();
            payload.minimum_guarantee_scope = scope === 'SHIFT' ? 'SHIFT' : 'MONTH';
          }
        }
        if (type === 'SALARY_HOURLY') {
          const rate_minor = parseMoneyRubToMinor(document.getElementById('inlineComponentRate')?.value || '');
          if (rate_minor == null) return toast('Укажи ставку', 'err');
          payload.rate_minor = rate_minor;
        }
        if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
          const percent_bps = parsePercentInputToBps(document.getElementById('inlineComponentPercent')?.value || '');
          if (percent_bps == null) return toast('Укажи процент', 'err');
          payload.percent_bps = percent_bps;
        }
        if (type === 'PERCENT_DEPARTMENT_REVENUE') {
          const departmentId = Number(document.getElementById('inlineComponentDepartmentId')?.value || 0);
          if (!departmentId) return toast('Выбери департамент', 'err');
          payload.department_id = departmentId;
        }
        if (type === 'KPI_BONUS') {
          const kpiMetricId = Number(document.getElementById('inlineComponentKpiMetricId')?.value || 0);
          if (!kpiMetricId) return toast('Выбери KPI', 'err');
          payload.kpi_metric_id = kpiMetricId;
        }
        if (inlineState.componentEditor?.id) await updatePayComponent(state.venueId, inlineState.componentEditor.id, payload);
        else await createPayComponent(state.venueId, profileId, payload);
        inlineState.componentEditor = { mode: 'create', id: null };
        await loadInlinePayProfiles({ force: true });
        await loadInlinePayProfileDetail(profileId, { force: true });
        await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
        toast('Компонент сохранён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось сохранить компонент', 'err');
      }
    });

    document.getElementById('btnInlineCompleteProfiles')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'pay_profiles' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineCompleteProfilesNext')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'pay_profiles' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
        const next = getAdjacentUnlockedStep(getVisibleSteps(), 'pay_profiles', 1);
        if (next) moveToStep(next.key);
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });
  }

  return { mountPayProfilesEditor, loadInlinePayProfiles };
}

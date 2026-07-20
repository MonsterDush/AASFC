export function createPositionSetupController(context) {
  const { toast, confirmModal, api, state, esc, buildDefaultPermissionsCatalog, ensurePermissionsCatalog, ensurePositionPermissionTemplates, getPositionTemplateById, buildPositionTemplateOptions, renderPositionTemplateSummary, applyPositionTemplateSelection, parsePermissionCodes, getPositionPresets, savePositionPresets, buildPayProfileOptions, getStepByKey, getNextStepKey, moveToStep, loadInlinePayProfiles, loadSetup } = context;

  function renderPermissionChecklist(selectedCodes = []) {
    const groups = Array.isArray(state.permissionsCatalog) && state.permissionsCatalog.length ? state.permissionsCatalog : buildDefaultPermissionsCatalog();
    const selected = new Set(parsePermissionCodes(selectedCodes));
    return groups.map((group) => `
      <div class="card setup-permission-group">
        <div class="perm-group-title">
          <div>
            <b>${esc(group.title)}</b>
            ${group.hint ? `<div class="muted mt-6 setup-permission-hint">${esc(group.hint)}</div>` : ''}
          </div>
          <div class="setup-permission-actions">
            <button class="btn sm" type="button" data-preset-group="${esc(group.key)}" data-value="1">Все</button>
            <button class="btn sm" type="button" data-preset-group="${esc(group.key)}" data-value="0">Ничего</button>
          </div>
        </div>
        ${(group.items || []).map((item) => `
          <div class="perm-row">
            <div class="perm-text">
              <div class="perm-title">${esc(item.title)}</div>
              ${item.description ? `<div class="perm-desc">${esc(item.description)}</div>` : ''}
            </div>
            <label class="switch">
              <input type="checkbox" data-preset-perm-code="${esc(item.code)}" data-preset-perm-group="${esc(group.key)}" ${selected.has(String(item.code).toUpperCase()) ? 'checked' : ''} />
              <span class="slider"></span>
            </label>
          </div>
        `).join('')}
      </div>
    `).join('');
  }

  function collectPresetPermissionCodes(host) {
    return Array.from(host.querySelectorAll('input[data-preset-perm-code]:checked'))
      .map((el) => String(el.getAttribute('data-preset-perm-code') || '').trim().toUpperCase())
      .filter(Boolean);
  }

  function renderPositionPresetForm(preset) {
    const templateId = preset?.template_id || "";
    return `
      <div class="setup-formgrid mt-12">
        <label>
          <span>Название должности</span>
          <input class="input" id="positionPresetTitle" placeholder="Например, Бармен" value="${esc(preset?.title || '')}" />
        </label>
        <label>
          <span>Профиль зарплаты</span>
          <select class="input" id="positionPresetPayProfile">${buildPayProfileOptions(preset?.pay_profile_id || '')}</select>
        </label>
        <label class="setup-formgrid__full">
          <span>Шаблон прав</span>
          <select class="input" id="positionPresetTemplate">${buildPositionTemplateOptions(templateId)}</select>
        </label>
      </div>
      <div id="positionPresetTemplateSummary" class="itemcard setup-position-template-summary">${renderPositionTemplateSummary(templateId)}</div>
      <div class="setup-inline-note">На этом этапе ты создаёшь именно заготовки должностей. Людей на них назначим на следующем шаге через приглашения.</div>
      <div class="setup-permission-grid">${renderPermissionChecklist(preset?.permission_codes || [])}</div>
    `;
  }

  function renderPositionsEditor(currentStep) {
    const presets = getPositionPresets();
    const inlineState = state.inline.positions;
    const editingId = inlineState.editorId || '';
    const editing = presets.find((item) => String(item.id) === String(editingId)) || null;
    return `
      <div class="setup-editor__panel">
        <div class="setup-editor__toolbar">
          <div class="setup-editor__title">Заготовки должностей</div>
        </div>
        <div class="setup-editor__grid mt-12">
          <div>
            <div class="setup-editor__title">Заготовки должностей</div>
            <div class="setup-minirows mt-8">
              ${presets.length ? presets.map((item) => `
                <div class="setup-minirow">
                  <div class="setup-minirow__main">
                    <div class="setup-minirow__titlewrap">
                      <b>${esc(item.title)}</b>
                      ${item.is_active ? '' : '<span class="badge">архив</span>'}
                    </div>
                    <div class="setup-minirow__meta">${item.pay_profile_title ? `Профиль: ${esc(item.pay_profile_title)}` : 'Профиль пока не выбран'}${item.template_title ? ` · Шаблон: ${esc(item.template_title)}` : ''}</div>
                  </div>
                  <div class="setup-minirow__actions">
                    <button class="btn sm" type="button" data-edit-preset="${esc(item.id)}">Изменить</button>
                    <button class="btn sm ${item.is_active ? 'danger' : ''}" type="button" data-toggle-preset="${esc(item.id)}">${item.is_active ? 'В архив' : 'Вернуть'}</button>
                    <button class="btn sm danger" type="button" data-delete-preset="${esc(item.id)}">Удалить</button>
                  </div>
                </div>
              `).join('') : '<div class="setup-empty">Пока нет заготовок должностей. Создай хотя бы одну должность, чтобы потом быстро назначать её приглашённым сотрудникам.</div>'}
            </div>
          </div>
          <div class="setup-formcard">
            <div class="setup-editor__title">${editing ? 'Редактирование должности' : 'Новая должность'}</div>
            <div class="muted mt-6">На этом шаге должности создаются без привязки к конкретным людям. На следующем шаге их можно будет назначать прямо в приглашении.</div>
            ${renderPositionPresetForm(editing)}
            <div class="setup-actionbar mt-12">
              <button class="btn primary" id="btnSavePreset" type="button">${editing ? 'Сохранить' : 'Создать'}</button>
              ${editing ? '<button class="btn subtle" id="btnCancelPresetEdit" type="button">Отмена</button>' : ''}
            </div>
          </div>
        </div>
        <div class="setup-actionbar mt-14">
          ${presets.filter((item) => item.is_active).length > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompletePositions" type="button">Подтвердить шаг</button>' : ''}
          ${presets.filter((item) => item.is_active).length > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompletePositionsNext" type="button">Подтвердить и дальше</button>' : ''}
        </div>
      </div>
    `;
  }

  async function mountPositionsEditor(currentStep) {
    const host = document.getElementById('setupInlineEditor');
    if (!host) return;
    await Promise.all([ensurePermissionsCatalog(), ensurePositionPermissionTemplates()]);
    await loadInlinePayProfiles();
    host.innerHTML = renderPositionsEditor(getStepByKey('positions') || currentStep);
    const presets = getPositionPresets();

    host.querySelectorAll('[data-preset-group]').forEach((btn) => btn.addEventListener('click', () => {
      const group = btn.getAttribute('data-preset-group') || '';
      const turnOn = btn.getAttribute('data-value') === '1';
      host.querySelectorAll(`input[data-preset-perm-group="${group}"]`).forEach((el) => { el.checked = turnOn; });
    }));

    host.querySelector('#positionPresetTemplate')?.addEventListener('change', (e) => {
      const templateId = String(e?.target?.value || '').trim();
      if (!templateId) { const summary = host.querySelector('#positionPresetTemplateSummary'); if (summary) summary.innerHTML = renderPositionTemplateSummary(''); return; }
      if (applyPositionTemplateSelection(host, templateId)) toast('Шаблон применён', 'ok');
    });

    document.getElementById('btnCancelPresetEdit')?.addEventListener('click', async () => {
      state.inline.positions.editorId = null;
      await mountPositionsEditor(getStepByKey('positions') || currentStep);
    });

    document.getElementById('btnSavePreset')?.addEventListener('click', async () => {
      const title = String(document.getElementById('positionPresetTitle')?.value || '').trim();
      const payProfileIdRaw = String(document.getElementById('positionPresetPayProfile')?.value || '').trim();
      if (!title) return toast('Укажи название должности', 'err');
      const selectedProfile = (state.inline.pay_profiles.items || []).find((item) => String(item.id) === payProfileIdRaw) || null;
      const next = [...presets];
      const payload = {
        id: state.inline.positions.editorId || `preset-${Date.now()}`,
        title,
        pay_profile_id: payProfileIdRaw ? Number(payProfileIdRaw) : null,
        pay_profile_title: selectedProfile?.title || '',
        template_id: String(document.getElementById('positionPresetTemplate')?.value || '').trim() || null,
        template_title: getPositionTemplateById(String(document.getElementById('positionPresetTemplate')?.value || '').trim())?.title || null,
        permission_codes: collectPresetPermissionCodes(host),
        rate: 0,
        percent: 0,
        is_active: true,
      };
      const idx = next.findIndex((item) => String(item.id) === String(payload.id));
      if (idx >= 0) next[idx] = { ...next[idx], ...payload };
      else next.push(payload);
      try {
        await savePositionPresets(next);
        state.inline.positions.editorId = null;
        await loadSetup({ preserveSelection: true });
        await mountPositionsEditor(getStepByKey('positions') || currentStep);
        toast('Заготовка должности сохранена', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось сохранить должность', 'err');
      }
    });

    host.querySelectorAll('[data-edit-preset]').forEach((btn) => btn.addEventListener('click', async () => {
      state.inline.positions.editorId = btn.getAttribute('data-edit-preset') || null;
      await mountPositionsEditor(getStepByKey('positions') || currentStep);
    }));

    host.querySelectorAll('[data-toggle-preset]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-toggle-preset') || '';
      const next = presets.map((item) => String(item.id) === String(id) ? { ...item, is_active: !item.is_active } : item);
      try {
        await savePositionPresets(next);
        await loadSetup({ preserveSelection: true });
        await mountPositionsEditor(getStepByKey('positions') || currentStep);
        toast('Состояние должности обновлено', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось обновить должность', 'err');
      }
    }));

    host.querySelectorAll('[data-delete-preset]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete-preset') || '';
      const target = presets.find((item) => String(item.id) === String(id));
      if (!target) return;
      const ok = await confirmModal({ title: 'Удалить заготовку?', text: `Заготовка «${target.title}» будет удалена из мастера настройки.`, confirmText: 'Удалить', danger: true });
      if (!ok) return;
      try {
        await savePositionPresets(presets.filter((item) => String(item.id) !== String(id)));
        await loadSetup({ preserveSelection: true });
        await mountPositionsEditor(getStepByKey('positions') || currentStep);
        toast('Заготовка удалена', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось удалить заготовку', 'err');
      }
    }));

    document.getElementById('btnInlineCompletePositions')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'positions' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineCompletePositionsNext')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'positions' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
        const next = getNextStepKey('positions');
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });
  }

  return { mountPositionsEditor };
}

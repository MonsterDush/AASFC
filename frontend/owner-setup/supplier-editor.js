export function createSupplierSetupController(context) {
  const { toast, confirmModal, api, state, esc, getStepByKey, getNextStepKey, moveToStep, loadSetup } = context;

  async function loadInlineSuppliers({ force = false } = {}) {
    const inlineState = state.inline.suppliers;
    if (!force && Array.isArray(inlineState.items)) return inlineState.items;
    inlineState.loading = true;
    try {
      const items = await api(`/venues/${encodeURIComponent(state.venueId)}/suppliers?include_archived=true`);
      inlineState.items = Array.isArray(items) ? items : [];
      return inlineState.items;
    } finally {
      inlineState.loading = false;
    }
  }

  function renderSuppliersEditor(items, currentStep) {
    const inlineState = state.inline.suppliers;
    const cfg = { listLabel: "Настроенные поставщики" };
    const showArchived = !!inlineState.showArchived;
    const visibleItems = showArchived ? items : items.filter((item) => item.is_active !== false);
    const activeCount = items.filter((item) => item.is_active !== false).length;
    const editingId = inlineState.editor?.id;
    const editing = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
    return `
      <div class="setup-editor__panel">
        <div class="setup-editor__toolbar">
          <div class="setup-editor__title">${esc(cfg.listLabel)}</div>
          <label class="setup-toggle">
            <input type="checkbox" id="inlineShowArchivedSuppliers" ${showArchived ? "checked" : ""} />
            <span>Показывать архив</span>
          </label>
        </div>
        <div class="setup-editor__grid mt-12">
          <div>
            <div class="setup-editor__title">Настроенные поставщики</div>
            <div class="setup-minirows mt-8">
              ${visibleItems.length ? visibleItems.map((item) => `
                <div class="setup-minirow">
                  <div class="setup-minirow__main">
                    <div class="setup-minirow__titlewrap">
                      <b>${esc(item.title)}</b>
                      ${item.is_active === false ? '<span class="badge">архив</span>' : ''}
                    </div>
                    <div class="setup-minirow__meta">${esc(item.contact || 'Контакты не указаны')}</div>
                  </div>
                  <div class="setup-minirow__actions">
                    <button class="btn sm" type="button" data-edit-supplier="${esc(item.id)}">Изменить</button>
                    <button class="btn sm ${item.is_active === false ? '' : 'danger'}" type="button" data-toggle-supplier="${esc(item.id)}">${item.is_active === false ? 'Вернуть' : 'В архив'}</button>
                  </div>
                </div>`).join('') : '<div class="setup-empty">Пока нет поставщиков. Этот шаг можно отложить и вернуться позже.</div>'}
            </div>
          </div>
          <div class="setup-formcard">
            <div class="setup-editor__title">${editing ? 'Редактировать поставщика' : 'Новый поставщик'}</div>
            <div class="muted mt-6">Поставщики ускоряют занесение расходов и помогают держать закупки в порядке.</div>
            <div class="setup-formgrid mt-12">
              <label>
                <span>Название</span>
                <input class="input" id="supplierTitle" placeholder="Например, ООО Поставщик" value="${esc(editing?.title || '')}" />
              </label>
              <label>
                <span>Контакт</span>
                <input class="input" id="supplierContact" placeholder="Телефон, Telegram, email" value="${esc(editing?.contact || '')}" />
              </label>
              <label>
                <span>Активность</span>
                <select class="input" id="supplierActive">
                  <option value="1" ${editing?.is_active === false ? '' : 'selected'}>Активен</option>
                  <option value="0" ${editing?.is_active === false ? 'selected' : ''}>Неактивен</option>
                </select>
              </label>
            </div>
            <div class="setup-actionbar mt-12">
              <button class="btn primary" id="btnSaveSupplierInline" type="button">${editing ? 'Сохранить' : 'Создать'}</button>
              ${editing ? '<button class="btn subtle" id="btnCancelSupplierEdit" type="button">Отмена</button>' : ''}
              <button class="btn subtle" id="btnReloadSuppliersInline" type="button">Обновить список</button>
            </div>
          </div>
        </div>
        <div class="setup-actionbar mt-14">
          ${activeCount > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteSuppliers" type="button">Подтвердить шаг</button>' : ''}
          ${activeCount > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteSuppliersNext" type="button">Подтвердить и дальше</button>' : ''}
          ${!currentStep.completed && !currentStep.skipped ? '<button class="btn subtle" id="btnInlineSkipSuppliers" type="button">Поставщиков добавлю позже</button>' : ''}
        </div>
      </div>
    `;
  }

  async function mountSuppliersEditor(currentStep) {
    const host = document.getElementById('setupInlineEditor');
    if (!host) return;
    host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
    const items = await loadInlineSuppliers();
    if (Number(currentStep.count || 0) !== items.filter((item) => item.is_active !== false).length && !currentStep.skipped) {
      await loadSetup({ preserveSelection: true });
      return;
    }
    host.innerHTML = renderSuppliersEditor(items, getStepByKey('suppliers') || currentStep);
    const inlineState = state.inline.suppliers;

    document.getElementById('inlineShowArchivedSuppliers')?.addEventListener('change', async (e) => {
      inlineState.showArchived = !!e.target?.checked;
      await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
    });

    document.getElementById('btnReloadSuppliersInline')?.addEventListener('click', async () => {
      await loadInlineSuppliers({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
      toast('Список обновлён', 'ok');
    });

    document.getElementById('btnCancelSupplierEdit')?.addEventListener('click', async () => {
      inlineState.editor = { mode: 'create', id: null };
      await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
    });

    document.getElementById('btnSaveSupplierInline')?.addEventListener('click', async () => {
      const title = String(document.getElementById('supplierTitle')?.value || '').trim();
      const contact = String(document.getElementById('supplierContact')?.value || '').trim() || null;
      const is_active = String(document.getElementById('supplierActive')?.value || '1') === '1';
      if (!title) return toast('Укажи название поставщика', 'err');
      const sortOrderBase = Math.max(0, ...(items || []).map((item) => Number(item.sort_order || 0))) || 0;
      const payload = { title, contact, is_active, sort_order: inlineState.editor?.id ? undefined : (sortOrderBase + 10) };
      try {
        if (inlineState.editor?.id) await api(`/venues/${encodeURIComponent(state.venueId)}/suppliers/${encodeURIComponent(inlineState.editor.id)}`, { method: 'PATCH', body: payload });
        else await api(`/venues/${encodeURIComponent(state.venueId)}/suppliers`, { method: 'POST', body: payload });
        inlineState.editor = { mode: 'create', id: null };
        await loadInlineSuppliers({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
        if (!currentStep.completed) {
          try {
            await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'suppliers' } });
            await loadSetup({ preserveSelection: true });
          } catch {}
        }
        toast('Поставщик сохранён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось сохранить поставщика', 'err');
      }
    });

    host.querySelectorAll('[data-edit-supplier]').forEach((btn) => btn.addEventListener('click', async () => {
      inlineState.editor = { mode: 'edit', id: btn.getAttribute('data-edit-supplier') || null };
      await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
    }));

    host.querySelectorAll('[data-toggle-supplier]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-toggle-supplier') || '';
      const item = (state.inline.suppliers.items || []).find((row) => String(row.id) === String(id));
      if (!item) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/suppliers/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: { is_active: !(item.is_active !== false) } });
        await loadInlineSuppliers({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
        toast('Поставщик обновлён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось обновить поставщика', 'err');
      }
    }));

    document.getElementById('btnInlineCompleteSuppliers')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'suppliers' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineCompleteSuppliersNext')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'suppliers' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
        const next = getNextStepKey('suppliers');
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineSkipSuppliers')?.addEventListener('click', async () => {
      const ok = await confirmModal({ title: 'Отложить поставщиков?', text: 'Этот шаг можно завершить позже без потери прогресса мастера.', confirmText: 'Отложить', danger: false });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, { method: 'POST', body: { step_key: 'suppliers' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг отложен', 'ok');
        const next = getNextStepKey('suppliers');
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось отложить шаг', 'err');
      }
    });
  }

  return { mountSuppliersEditor };
}

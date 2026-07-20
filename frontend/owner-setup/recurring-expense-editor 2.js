export function createRecurringExpenseSetupController(context) {
  const { toast, confirmModal, api, getPaymentMethods, state, esc, todayIso, parseMoneyToMinor, minorToMoneyInput, buildSelectOptions, recurringModeLabel, buildBasisPaymentMethodCheckboxes, getStepByKey, getNextStepKey, moveToStep, loadSetup, setVisible } = context;

  async function loadInlineRecurringExpenses({ force = false } = {}) {
    const inlineState = state.inline.recurring_expenses;
    if (!force && Array.isArray(inlineState.items) && Array.isArray(inlineState.categories) && Array.isArray(inlineState.suppliers) && Array.isArray(inlineState.paymentMethods)) return inlineState;
    inlineState.loading = true;
    try {
      const [items, categories, suppliers, paymentMethods] = await Promise.all([
        api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules`),
        api(`/venues/${encodeURIComponent(state.venueId)}/expense-categories`),
        api(`/venues/${encodeURIComponent(state.venueId)}/suppliers`),
        getPaymentMethods(state.venueId, { includeArchived: false }).catch(() => []),
      ]);
      inlineState.items = Array.isArray(items) ? items : [];
      inlineState.categories = Array.isArray(categories) ? categories : [];
      inlineState.suppliers = Array.isArray(suppliers) ? suppliers : [];
      inlineState.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
      return inlineState;
    } finally {
      inlineState.loading = false;
    }
  }

  function renderRecurringExpensesEditor(data, currentStep) {
    const items = Array.isArray(data?.items) ? data.items : [];
    const categories = Array.isArray(data?.categories) ? data.categories : [];
    const suppliers = Array.isArray(data?.suppliers) ? data.suppliers : [];
    const paymentMethods = Array.isArray(data?.paymentMethods) ? data.paymentMethods : [];
    const inlineState = state.inline.recurring_expenses;
    const showInactive = !!inlineState.showInactive;
    const visibleItems = showInactive ? items : items.filter((item) => item.is_active !== false);
    const activeCount = items.filter((item) => item.is_active !== false).length;
    const editingId = inlineState.editor?.id;
    const editing = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
    const isPercent = String(editing?.generation_mode || 'FIXED').toUpperCase() === 'PERCENT';
    return `
      <div class="setup-editor__panel">
        <div class="setup-editor__toolbar">
          <div class="setup-editor__title">Правила регулярных расходов</div>
          <label class="setup-toggle">
            <input type="checkbox" id="inlineShowInactiveRecurring" ${showInactive ? 'checked' : ''} />
            <span>Показывать неактивные</span>
          </label>
        </div>
        <div class="setup-editor__grid mt-12">
          <div>
            <div class="setup-editor__title">Правила регулярных расходов</div>
            <div class="setup-minirows mt-8">
              ${visibleItems.length ? visibleItems.map((item) => `
                <div class="setup-minirow">
                  <div class="setup-minirow__main">
                    <div class="setup-minirow__titlewrap">
                      <b>${esc(item.title || 'Без названия')}</b>
                      <span class="badge">${esc(recurringModeLabel(item.generation_mode))}</span>
                      ${item.is_active === false ? '<span class="badge">выключено</span>' : ''}
                    </div>
                    <div class="setup-minirow__meta">${esc(item.category?.title || 'Без категории')} · день ${esc(item.day_of_month || 1)} · ${String(item.generation_mode || 'FIXED').toUpperCase() === 'PERCENT' ? `${esc(minorToMoneyInput(item.percent_bps || 0))}%` : `${esc(minorToMoneyInput(item.amount_minor || 0))} ₽`}</div>
                  </div>
                  <div class="setup-minirow__actions">
                    <button class="btn sm" type="button" data-edit-recurring="${esc(item.id)}">Изменить</button>
                    <button class="btn sm ${item.is_active === false ? '' : 'danger'}" type="button" data-toggle-recurring="${esc(item.id)}">${item.is_active === false ? 'Включить' : 'Выключить'}</button>
                    <button class="btn sm danger" type="button" data-delete-recurring="${esc(item.id)}">Удалить</button>
                  </div>
                </div>`).join('') : '<div class="setup-empty">Пока нет правил. Можно добавить первое правило прямо здесь или отложить шаг на потом.</div>'}
            </div>
          </div>
          <div class="setup-formcard">
            <div class="setup-editor__title">${editing ? 'Редактировать правило' : 'Новое правило'}</div>
            <div class="muted mt-6">Регулярные расходы помогают автоматизировать повторяющиеся траты без ручного ввода каждый месяц.</div>
            ${!categories.length ? '<div class="setup-inline-note mt-12">Сначала создай хотя бы одну категорию расходов, иначе правило не получится сохранить.</div>' : `
            <div class="setup-formgrid mt-12">
              <label><span>Название</span><input class="input" id="recurringTitle" placeholder="Например, аренда" value="${esc(editing?.title || '')}" /></label>
              <label><span>Категория</span><select class="input" id="recurringCategoryId">${buildSelectOptions(categories, editing?.category_id, 'Выбери категорию')}</select></label>
              <label><span>Поставщик</span><select class="input" id="recurringSupplierId">${buildSelectOptions(suppliers, editing?.supplier_id, 'Без поставщика')}</select></label>
              <label><span>Оплачивать через</span><select class="input" id="recurringPaymentMethodId">${buildSelectOptions(paymentMethods, editing?.payment_method_id, 'Не указано')}</select></label>
              <label><span>Дата старта</span><input class="input" id="recurringStartDate" type="date" value="${esc(editing?.start_date || todayIso())}" /></label>
              <label><span>Дата окончания</span><input class="input" id="recurringEndDate" type="date" value="${esc(editing?.end_date || '')}" /></label>
              <label><span>День месяца</span><input class="input" id="recurringDayOfMonth" type="number" min="1" max="31" value="${esc(editing?.day_of_month || 1)}" /></label>
              <label><span>Размазать на месяцев</span><input class="input" id="recurringSpreadMonths" type="number" min="1" max="120" value="${esc(editing?.spread_months || 1)}" /></label>
              <label><span>Режим</span><select class="input" id="recurringGenerationMode"><option value="FIXED" ${isPercent ? '' : 'selected'}>Фиксированная сумма</option><option value="PERCENT" ${isPercent ? 'selected' : ''}>Процент от оплат</option></select></label>
              <label id="recurringAmountWrap" class="${isPercent ? 'hidden' : ''}"><span>Сумма, ₽</span><input class="input" id="recurringAmount" placeholder="150000.00" value="${esc(minorToMoneyInput(editing?.amount_minor))}" /></label>
              <label id="recurringPercentWrap" class="${isPercent ? '' : 'hidden'}"><span>Процент, %</span><input class="input" id="recurringPercent" placeholder="2.50" value="${esc(minorToMoneyInput(editing?.percent_bps))}" /></label>
              <label><span>Активность</span><select class="input" id="recurringActive"><option value="1" ${editing?.is_active === false ? '' : 'selected'}>Активно</option><option value="0" ${editing?.is_active === false ? 'selected' : ''}>Неактивно</option></select></label>
              <label class="setup-formgrid__full"><span>Комментарий</span><textarea class="input" id="recurringDescription" rows="3" placeholder="Например, аренда помещения">${esc(editing?.description || '')}</textarea></label>
              <div class="setup-formgrid__full${isPercent ? '' : ' hidden'}" id="recurringBasisWrap">
                <span>База для процента</span>
                <div class="finance-form mt-8">${buildBasisPaymentMethodCheckboxes(paymentMethods, editing?.payment_method_ids || [])}</div>
              </div>
            </div>
            <div class="setup-actionbar mt-12">
              <button class="btn primary" id="btnSaveRecurringInline" type="button">${editing ? 'Сохранить' : 'Создать'}</button>
              ${editing ? '<button class="btn subtle" id="btnCancelRecurringEdit" type="button">Отмена</button>' : ''}
              <button class="btn subtle" id="btnReloadRecurringInline" type="button">Обновить список</button>
            </div>`}
          </div>
        </div>
        <div class="setup-actionbar mt-14">
          ${activeCount > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteRecurring" type="button">Подтвердить шаг</button>' : ''}
          ${activeCount > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteRecurringNext" type="button">Подтвердить и дальше</button>' : ''}
          ${!currentStep.completed && !currentStep.skipped ? '<button class="btn subtle" id="btnInlineSkipRecurring" type="button">Регулярные правила добавлю позже</button>' : ''}
        </div>
      </div>
    `;
  }

  function syncRecurringModeVisibility() {
    const mode = String(document.getElementById('recurringGenerationMode')?.value || 'FIXED').toUpperCase();
    const amountWrap = document.getElementById('recurringAmountWrap');
    const percentWrap = document.getElementById('recurringPercentWrap');
    const basisWrap = document.getElementById('recurringBasisWrap');
    setVisible(amountWrap, mode === 'FIXED');
    setVisible(percentWrap, mode === 'PERCENT');
    setVisible(basisWrap, mode === 'PERCENT');
  }

  async function mountRecurringExpensesEditor(currentStep) {
    const host = document.getElementById('setupInlineEditor');
    if (!host) return;
    host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
    const data = await loadInlineRecurringExpenses();
    if (Number(currentStep.count || 0) !== (data.items || []).filter((item) => item.is_active !== false).length && !currentStep.skipped) {
      await loadSetup({ preserveSelection: true });
      return;
    }
    host.innerHTML = renderRecurringExpensesEditor(data, getStepByKey('recurring_expenses') || currentStep);
    const inlineState = state.inline.recurring_expenses;

    document.getElementById('inlineShowInactiveRecurring')?.addEventListener('change', async (e) => {
      inlineState.showInactive = !!e.target?.checked;
      await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
    });

    document.getElementById('btnReloadRecurringInline')?.addEventListener('click', async () => {
      await loadInlineRecurringExpenses({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
      toast('Список обновлён', 'ok');
    });

    document.getElementById('btnCancelRecurringEdit')?.addEventListener('click', async () => {
      inlineState.editor = { mode: 'create', id: null };
      await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
    });

    document.getElementById('recurringGenerationMode')?.addEventListener('change', syncRecurringModeVisibility);
    syncRecurringModeVisibility();

    document.getElementById('btnSaveRecurringInline')?.addEventListener('click', async () => {
      if (!(data.categories || []).length) {
        toast('Сначала создай категорию расходов', 'err');
        return;
      }
      const title = String(document.getElementById('recurringTitle')?.value || '').trim();
      if (!title) return toast('Укажи название правила', 'err');
      const generationMode = String(document.getElementById('recurringGenerationMode')?.value || 'FIXED').toUpperCase();
      const payload = {
        title,
        category_id: Number(document.getElementById('recurringCategoryId')?.value || 0),
        supplier_id: document.getElementById('recurringSupplierId')?.value ? Number(document.getElementById('recurringSupplierId')?.value) : null,
        payment_method_id: document.getElementById('recurringPaymentMethodId')?.value ? Number(document.getElementById('recurringPaymentMethodId')?.value) : null,
        is_active: String(document.getElementById('recurringActive')?.value || '1') === '1',
        start_date: String(document.getElementById('recurringStartDate')?.value || todayIso()),
        end_date: String(document.getElementById('recurringEndDate')?.value || '').trim() || null,
        frequency: 'MONTHLY',
        day_of_month: Number(document.getElementById('recurringDayOfMonth')?.value || 1),
        spread_months: Number(document.getElementById('recurringSpreadMonths')?.value || 1),
        generation_mode: generationMode,
        amount_minor: generationMode === 'FIXED' ? parseMoneyToMinor(document.getElementById('recurringAmount')?.value || '') : null,
        percent_bps: generationMode === 'PERCENT' ? parseMoneyToMinor(document.getElementById('recurringPercent')?.value || '') : null,
        description: String(document.getElementById('recurringDescription')?.value || '').trim() || null,
        payment_method_ids: generationMode === 'PERCENT' ? Array.from(host.querySelectorAll('input[name="recurringBasisPaymentMethod"]:checked')).map((el) => Number(el.value)).filter((x) => Number.isFinite(x) && x > 0) : [],
      };
      if (!payload.category_id) return toast('Выбери категорию расхода', 'err');
      try {
        if (inlineState.editor?.id) await api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules/${encodeURIComponent(inlineState.editor.id)}`, { method: 'PATCH', body: payload });
        else await api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules`, { method: 'POST', body: payload });
        inlineState.editor = { mode: 'create', id: null };
        await loadInlineRecurringExpenses({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
        if (!currentStep.completed) {
          try {
            await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'recurring_expenses' } });
            await loadSetup({ preserveSelection: true });
          } catch {}
        }
        toast('Правило сохранено', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось сохранить правило', 'err');
      }
    });

    host.querySelectorAll('[data-edit-recurring]').forEach((btn) => btn.addEventListener('click', async () => {
      inlineState.editor = { mode: 'edit', id: btn.getAttribute('data-edit-recurring') || null };
      await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
    }));

    host.querySelectorAll('[data-toggle-recurring]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-toggle-recurring') || '';
      const item = (state.inline.recurring_expenses.items || []).find((row) => String(row.id) === String(id));
      if (!item) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: { is_active: !(item.is_active !== false) } });
        await loadInlineRecurringExpenses({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
        toast('Правило обновлено', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось обновить правило', 'err');
      }
    }));

    host.querySelectorAll('[data-delete-recurring]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete-recurring') || '';
      const ok = await confirmModal({ title: 'Удалить правило?', text: 'Правило регулярных расходов будет удалено без возможности восстановления.', confirmText: 'Удалить', danger: true });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules/${encodeURIComponent(id)}`, { method: 'DELETE' });
        await loadInlineRecurringExpenses({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
        toast('Правило удалено', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось удалить правило', 'err');
      }
    }));

    document.getElementById('btnInlineCompleteRecurring')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'recurring_expenses' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineCompleteRecurringNext')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'recurring_expenses' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
        const next = getNextStepKey('recurring_expenses');
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineSkipRecurring')?.addEventListener('click', async () => {
      const ok = await confirmModal({ title: 'Отложить регулярные настройки?', text: 'К этому шагу можно будет спокойно вернуться после запуска заведения.', confirmText: 'Отложить', danger: false });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, { method: 'POST', body: { step_key: 'recurring_expenses' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг отложен', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось отложить шаг', 'err');
      }
    });
  }

  return { mountRecurringExpensesEditor };
}

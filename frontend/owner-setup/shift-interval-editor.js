import { intervalPositionLabel, positionScopeEditor, readPositionScope, wirePositionScope } from "/shift-interval-scope.js?v=20260905-scopes1";
import { formatShiftIntervalRange } from "/shift-time.js?v=20260729-overnight1";

export function createShiftIntervalSetupController(context) {
  const { toast, confirmModal, api, state, esc, getStepByKey, getNextStepKey, moveToStep, loadSetup } = context;

  async function loadInlineShiftIntervals({ force = false } = {}) {
    const inlineState = state.inline.shift_intervals;
    if (!force && Array.isArray(inlineState.items)) return inlineState.items;
    inlineState.loading = true;
    try {
      const items = await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals?include_inactive=true`);
      inlineState.items = Array.isArray(items) ? items : [];
      return inlineState.items;
    } finally {
      inlineState.loading = false;
    }
  }

  async function loadInlineShiftPositions({ force = false } = {}) {
    const inlineState = state.inline.shift_intervals;
    if (!force && Array.isArray(inlineState.positions)) return inlineState.positions;
    const out = await api(`/venues/${encodeURIComponent(state.venueId)}/positions`);
    inlineState.positions = Array.isArray(out) ? out : [];
    return inlineState.positions;
  }


  function renderShiftIntervalsEditor(items, currentStep) {
    const inlineState = state.inline.shift_intervals;
    const cfg = { listLabel: "Настроенные интервалы смен" };
    const visibleItems = inlineState.showArchived ? items : items.filter((item) => item.is_active !== false);
    const editingId = inlineState.editor?.id || null;
    const editing = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
    const activeCount = items.filter((item) => item.is_active !== false).length;
    return `
      <div class="setup-editor__panel">
        <div class="setup-editor__toolbar">
          <div class="setup-editor__title">${esc(cfg.listLabel)}</div>
          <label class="setup-toggle">
            <input type="checkbox" id="inlineShowArchivedIntervals" ${inlineState.showArchived ? 'checked' : ''} />
            <span>Показывать архив</span>
          </label>
        </div>
        <div class="setup-editor__grid mt-12">
          <div>
            <div class="setup-editor__title">Интервалы смен</div>
            <div class="setup-minirows mt-8">
              ${visibleItems.length ? visibleItems.map((item) => `
                <div class="setup-minirow">
                  <div class="setup-minirow__main">
                    <div class="setup-minirow__titlewrap">
                      <b>${esc(item.title)}</b>
                      ${item.is_active === false ? '<span class="badge">архив</span>' : ''}
                    </div>
                    <div class="setup-minirow__meta">
                      ${esc(formatShiftIntervalRange(item.start_time, item.end_time))}
                      · <span>Должность</span>: ${esc(intervalPositionLabel(item))}
                      · Смен: ${Number(item.usage_count || 0)}
                    </div>
                  </div>
                  <div class="setup-minirow__actions">
                    <button class="btn sm" type="button" data-edit-interval="${esc(item.id)}">Изменить</button>
                    <button class="btn sm ${item.is_active === false ? '' : 'danger'}" type="button" data-toggle-interval="${esc(item.id)}">${item.is_active === false ? 'Вернуть' : 'В архив'}</button>
                    ${item.can_delete ? `<button class="btn sm danger" type="button" data-delete-interval="${esc(item.id)}">Удалить</button>` : ''}
                  </div>
                </div>
              `).join('') : '<div class="setup-empty">Пока нет интервалов. Добавь хотя бы один, чтобы график и часть зарплатной логики были готовы к работе.</div>'}
            </div>
          </div>
          <div class="setup-formcard">
            <div class="setup-editor__title">${editing ? 'Редактирование интервала' : 'Новый интервал'}</div>
            <div class="muted mt-6">Интервалы используются в графике и могут участвовать в расчётах начислений.</div>
            <div class="setup-formgrid mt-12">
              <label>
                <span>Название</span>
                <input class="input" id="intervalTitle" placeholder="Например, Вечер" value="${esc(editing?.title || '')}" />
              </label>
              <label>
                <span>Активность</span>
                <select class="input" id="intervalActive">
                  <option value="1" ${(editing?.is_active === false) ? '' : 'selected'}>Активен</option>
                  <option value="0" ${(editing?.is_active === false) ? 'selected' : ''}>Неактивен</option>
                </select>
              </label>
              <label>
                <span>Начало</span>
                <input class="input" id="intervalStart" type="time" value="${esc(editing?.start_time || '')}" />
              </label>
              <label>
                <span>Окончание</span>
                <input class="input" id="intervalEnd" type="time" value="${esc(editing?.end_time || '')}" />
              </label>
              ${positionScopeEditor("intervalPosition", inlineState.positions || [], editing, esc)}
            </div>
            <div class="setup-actionbar mt-12">
              <button class="btn primary" id="btnSaveIntervalInline" type="button">${editing ? 'Сохранить' : 'Создать'}</button>
              ${editing ? '<button class="btn subtle" id="btnCancelIntervalEdit" type="button">Отмена</button>' : ''}
              <button class="btn subtle" id="btnReloadIntervalsInline" type="button">Обновить список</button>
            </div>
          </div>
        </div>
        <div class="setup-actionbar mt-14">
          ${activeCount > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteIntervals" type="button">Подтвердить шаг</button>' : ''}
          ${activeCount > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteIntervalsNext" type="button">Подтвердить и дальше</button>' : ''}
        </div>
      </div>
    `;
  }

  async function mountShiftIntervalsEditor(currentStep) {
    const host = document.getElementById('setupInlineEditor');
    if (!host) return;
    host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
    const [items] = await Promise.all([
      loadInlineShiftIntervals(),
      loadInlineShiftPositions(),
    ]);
    if (Number(currentStep.count || 0) !== items.filter((item) => item.is_active !== false).length) {
      await loadSetup({ preserveSelection: true });
      return;
    }
    host.innerHTML = renderShiftIntervalsEditor(items, getStepByKey('shift_intervals') || currentStep);
    const inlineState = state.inline.shift_intervals;
    wirePositionScope(document.getElementById('intervalPosition'));

    document.getElementById('inlineShowArchivedIntervals')?.addEventListener('change', async (e) => {
      inlineState.showArchived = !!e.target?.checked;
      await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
    });

    document.getElementById('btnReloadIntervalsInline')?.addEventListener('click', async () => {
      await Promise.all([
        loadInlineShiftIntervals({ force: true }),
        loadInlineShiftPositions({ force: true }),
      ]);
      await loadSetup({ preserveSelection: true });
      await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
      toast('Список обновлён', 'ok');
    });

    document.getElementById('btnCancelIntervalEdit')?.addEventListener('click', async () => {
      inlineState.editor = { mode: 'create', id: null };
      await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
    });

    document.getElementById('btnSaveIntervalInline')?.addEventListener('click', async () => {
      const title = String(document.getElementById('intervalTitle')?.value || '').trim();
      const start_time = String(document.getElementById('intervalStart')?.value || '').trim();
      const end_time = String(document.getElementById('intervalEnd')?.value || '').trim();
      const position_ids = readPositionScope(document.getElementById('intervalPosition'));
      const is_active = String(document.getElementById('intervalActive')?.value || '1') === '1';
      if (!title) return toast('Укажи название интервала', 'err');
      if (!/^\d{2}:\d{2}$/.test(start_time)) return toast('Укажи время начала', 'err');
      if (!/^\d{2}:\d{2}$/.test(end_time)) return toast('Укажи время окончания', 'err');
      try {
        if (inlineState.editor?.id) {
          await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(inlineState.editor.id)}`, { method: 'PATCH', body: { title, start_time, end_time, position_ids, is_active } });
        } else {
          await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals`, { method: 'POST', body: { title, start_time, end_time, position_ids, is_active } });
        }
        inlineState.editor = { mode: 'create', id: null };
        await loadInlineShiftIntervals({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
        if (!currentStep.completed) {
          try {
            await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'shift_intervals' } });
            await loadSetup({ preserveSelection: true });
          } catch {}
        }
        toast('Интервал сохранён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось сохранить интервал', 'err');
      }
    });

    host.querySelectorAll('[data-edit-interval]').forEach((btn) => btn.addEventListener('click', async () => {
      inlineState.editor = { mode: 'edit', id: btn.getAttribute('data-edit-interval') || null };
      await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
    }));

    host.querySelectorAll('[data-toggle-interval]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-toggle-interval') || '';
      const item = (state.inline.shift_intervals.items || []).find((row) => String(row.id) === String(id));
      if (!item) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: { is_active: !(item.is_active !== false) } });
        await loadInlineShiftIntervals({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
        toast('Интервал обновлён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось обновить интервал', 'err');
      }
    }));

    host.querySelectorAll('[data-delete-interval]').forEach((btn) => btn.addEventListener('click', async () => {
      const id = btn.getAttribute('data-delete-interval') || '';
      const ok = await confirmModal({ title: 'Удалить интервал?', text: 'Интервал будет удалён без возможности восстановления.', confirmText: 'Удалить', danger: true });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(id)}`, { method: 'DELETE' });
        await loadInlineShiftIntervals({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
        toast('Интервал удалён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось удалить интервал', 'err');
      }
    }));

    document.getElementById('btnInlineCompleteIntervals')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'shift_intervals' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineCompleteIntervalsNext')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'shift_intervals' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
        const next = getNextStepKey('shift_intervals');
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });
  }

  return { mountShiftIntervalsEditor };
}

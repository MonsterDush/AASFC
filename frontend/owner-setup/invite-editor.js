export function createInviteSetupController(context) {
  const { toast, confirmModal, api, getVenueMembers, patchInviteDefaultPosition, state, esc, fmtDateTime, roleLabel, memberDisplayName, getPositionPresets, buildPresetOptionList, getStepByKey, getNextStepKey, moveToStep, loadSetup } = context;

  async function loadInlineInvites({ force = false } = {}) {
    const inlineState = state.inline.invites;
    if (!force && inlineState.data) return inlineState.data;
    inlineState.loading = true;
    try {
      const data = await getVenueMembers(state.venueId);
      inlineState.data = data || { members: [], pending_invites: [] };
      return inlineState.data;
    } finally {
      inlineState.loading = false;
    }
  }

  function renderInvitesEditor(data, currentStep) {
    const pending = Array.isArray(data?.pending_invites) ? data.pending_invites : [];
    const members = Array.isArray(data?.members) ? data.members : [];
    return `
      <div class="setup-editor__panel">
        <div class="setup-editor__toolbar">
          <div class="setup-inline-list setup-inline-list--compact">
            <span class="setup-chip">Участников: ${members.length}</span>
            <span class="setup-chip">Ожидают: ${pending.length}</span>
          </div>
        </div>
        <div class="setup-editor__grid mt-12">
          <div>
            <div class="setup-editor__title">Ожидающие приглашения</div>
            <div class="setup-minirows mt-8">
              ${pending.length ? pending.map((item) => `
                <div class="setup-minirow">
                  <div class="setup-minirow__main">
                    <div class="setup-minirow__titlewrap">
                      <b>${esc(item.contact_label || item.tg_username || item.phone || 'Приглашение')}</b>
                      <span class="badge">${esc(roleLabel(item.venue_role))}</span>
                    </div>
                    <div class="setup-minirow__meta">${esc(item.channel === 'PHONE' ? (item.phone || 'Телефон') : (item.tg_username || 'Telegram'))} · ${esc(item.default_position?.title || 'Без должности')} · Создано: ${esc(fmtDateTime(item.created_at))}</div>
                  </div>
                  <div class="setup-minirow__actions">
                    <select class="input" data-invite-preset="${esc(item.id)}" style="max-width:220px">${buildPresetOptionList(item.default_position || '')}</select>
                    <button class="btn sm" type="button" data-apply-invite-preset="${esc(item.id)}">Назначить</button>
                    <button class="btn sm danger" type="button" data-delete-invite="${esc(item.id)}">Отменить</button>
                  </div>
                </div>
              `).join('') : '<div class="setup-empty">Пока нет приглашений. Можно пригласить людей сейчас или отложить этот шаг.</div>'}
            </div>
            ${members.length ? `<div class="setup-inline-note">Уже в заведении: ${members.map((item) => esc(memberDisplayName(item))).join(', ')}</div>` : ''}
          </div>
          <div class="setup-formcard">
            <div class="setup-editor__title">Новое приглашение</div>
            <div class="muted mt-6">Можно пригласить по Telegram или по телефону и сразу заранее назначить должность.</div>
            <div class="setup-formgrid mt-12">
              <label>
                <span>Канал</span>
                <select class="input" id="inviteChannel">
                  <option value="TELEGRAM">Telegram</option>
                  <option value="PHONE">Телефон</option>
                </select>
              </label>
              <label>
                <span>Роль</span>
                <select class="input" id="inviteRole">
                  <option value="STAFF">Сотрудник</option>
                  <option value="OWNER">Владелец</option>
                </select>
              </label>
              <label id="inviteTelegramWrap">
                <span>Ник в Telegram</span>
                <input class="input" id="inviteTelegram" placeholder="@username" />
              </label>
              <label id="invitePhoneWrap" style="display:none">
                <span>Телефон</span>
                <input class="input" id="invitePhone" placeholder="+7 ..." />
              </label>
              <label>
                <span>Контакт / имя</span>
                <input class="input" id="inviteContactLabel" placeholder="Например, Иван" />
              </label>
              <label>
                <span>Назначить должность</span>
                <select class="input" id="invitePresetSelect">${buildPresetOptionList('')}</select>
              </label>
            </div>
            <div class="setup-actionbar mt-12">
              <button class="btn primary" id="btnCreateInviteInline" type="button">Создать приглашение</button>
              <button class="btn subtle" id="btnReloadInvitesInline" type="button">Обновить список</button>
            </div>
          </div>
        </div>
        <div class="setup-actionbar mt-14">
          ${pending.length > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteInvites" type="button">Подтвердить шаг</button>' : ''}
          ${pending.length > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteInvitesNext" type="button">Подтвердить и дальше</button>' : ''}
          ${!currentStep.completed && !currentStep.skipped ? '<button class="btn subtle" id="btnInlineSkipInvites" type="button">Приглашу позже</button>' : ''}
        </div>
      </div>
    `;
  }

  async function mountInvitesEditor(currentStep) {
    const host = document.getElementById('setupInlineEditor');
    if (!host) return;
    host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
    const data = await loadInlineInvites();
    host.innerHTML = renderInvitesEditor(data, getStepByKey('invites') || currentStep);
    const syncChannel = () => {
      const channel = String(document.getElementById('inviteChannel')?.value || 'TELEGRAM').toUpperCase();
      const tgWrap = document.getElementById('inviteTelegramWrap');
      const phWrap = document.getElementById('invitePhoneWrap');
      if (tgWrap) tgWrap.style.display = channel === 'TELEGRAM' ? '' : 'none';
      if (phWrap) phWrap.style.display = channel === 'PHONE' ? '' : 'none';
    };
    document.getElementById('inviteChannel')?.addEventListener('change', syncChannel);
    syncChannel();

    document.getElementById('btnReloadInvitesInline')?.addEventListener('click', async () => {
      await loadInlineInvites({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountInvitesEditor(getStepByKey('invites') || currentStep);
      toast('Список обновлён', 'ok');
    });

    document.getElementById('btnCreateInviteInline')?.addEventListener('click', async () => {
      const channel = String(document.getElementById('inviteChannel')?.value || 'TELEGRAM').toUpperCase();
      const venue_role = String(document.getElementById('inviteRole')?.value || 'STAFF').toUpperCase();
      const contact_label = String(document.getElementById('inviteContactLabel')?.value || '').trim() || null;
      const body = { invite_channel: channel, venue_role, contact_label };
      if (channel === 'PHONE') {
        const phone = String(document.getElementById('invitePhone')?.value || '').trim();
        if (!phone) return toast('Укажи телефон', 'err');
        body.phone = phone;
      } else {
        const tg = String(document.getElementById('inviteTelegram')?.value || '').trim();
        if (!tg) return toast('Укажи Telegram', 'err');
        body.tg_username = tg;
      }
      const selectedPresetId = String(document.getElementById('invitePresetSelect')?.value || '').trim();
      const selectedPreset = getPositionPresets().find((item) => String(item.id) === selectedPresetId) || null;
      try {
        const out = await api(`/venues/${encodeURIComponent(state.venueId)}/invites`, { method: 'POST', body });
        if (out?.invite_id && selectedPreset) {
          await patchInviteDefaultPosition(state.venueId, out.invite_id, {
            title: selectedPreset.title,
            rate: Number(selectedPreset.rate || 0) || 0,
            percent: Number(selectedPreset.percent || 0) || 0,
            pay_profile_id: selectedPreset.pay_profile_id || null,
            pay_profile_title: selectedPreset.pay_profile_title || null,
            permission_codes: selectedPreset.permission_codes || [],
          });
        }
        await loadInlineInvites({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountInvitesEditor(getStepByKey('invites') || currentStep);
        toast(out?.mode === 'member_added' ? 'Участник добавлен' : 'Приглашение создано', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось создать приглашение', 'err');
      }
    });

    host.querySelectorAll('[data-apply-invite-preset]').forEach((btn) => btn.addEventListener('click', async () => {
      const inviteId = btn.getAttribute('data-apply-invite-preset') || '';
      const select = host.querySelector(`[data-invite-preset="${inviteId}"]`);
      const presetId = String(select?.value || '').trim();
      const selectedPreset = getPositionPresets().find((item) => String(item.id) === presetId) || null;
      try {
        await patchInviteDefaultPosition(state.venueId, inviteId, selectedPreset ? {
          title: selectedPreset.title,
          rate: Number(selectedPreset.rate || 0) || 0,
          percent: Number(selectedPreset.percent || 0) || 0,
          pay_profile_id: selectedPreset.pay_profile_id || null,
          pay_profile_title: selectedPreset.pay_profile_title || null,
          permission_codes: selectedPreset.permission_codes || [],
        } : null);
        await loadInlineInvites({ force: true });
        await mountInvitesEditor(getStepByKey('invites') || currentStep);
        toast(selectedPreset ? 'Должность назначена приглашению' : 'Должность снята', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось обновить приглашение', 'err');
      }
    }));

    host.querySelectorAll('[data-delete-invite]').forEach((btn) => btn.addEventListener('click', async () => {
      const inviteId = btn.getAttribute('data-delete-invite') || '';
      const ok = await confirmModal({ title: 'Отменить приглашение?', text: 'Приглашение станет недействительным.', confirmText: 'Отменить', danger: true });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/invites/${encodeURIComponent(inviteId)}`, { method: 'DELETE' });
        await loadInlineInvites({ force: true });
        await loadSetup({ preserveSelection: true });
        await mountInvitesEditor(getStepByKey('invites') || currentStep);
        toast('Приглашение отменено', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось отменить приглашение', 'err');
      }
    }));

    document.getElementById('btnInlineCompleteInvites')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'invites' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineCompleteInvitesNext')?.addEventListener('click', async () => {
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'invites' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг подтверждён', 'ok');
        const next = getNextStepKey('invites');
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
      }
    });

    document.getElementById('btnInlineSkipInvites')?.addEventListener('click', async () => {
      const ok = await confirmModal({ title: 'Пригласить позже?', text: 'Этот шаг будет помечен как отложенный. К нему можно вернуться в любой момент.', confirmText: 'Отложить', danger: false });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, { method: 'POST', body: { step_key: 'invites' } });
        await loadSetup({ preserveSelection: true });
        toast('Шаг отложен', 'ok');
        const next = getNextStepKey('invites');
        if (next) moveToStep(next);
      } catch (e) {
        toast(e?.data?.detail || e?.message || 'Не удалось отложить шаг', 'err');
      }
    });
  }

  return { mountInvitesEditor };
}

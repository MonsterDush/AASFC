import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  api,
} from "/app.js?v=20260726-navmore1";

applyTelegramTheme();
mountCommonUI("admin-position-templates");
await ensureLogin({ silent: true });
await mountNav({ activeTab: "admin-position-templates" });

const root = document.getElementById("root");
const statusEl = document.getElementById("status");
const btnNew = document.getElementById("btnNew");
const btnShowInactive = document.getElementById("btnShowInactive");
const btnSeedDefaults = document.getElementById("btnSeedDefaults");

const state = {
  items: [],
  showInactive: true,
  editorId: null,
  editorDraft: null,
  permissionsCatalog: null,
};

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

const DEFAULT_META = {
  Reports: { key: "reports", title: "Отчёты и финансы", hint: "Закрытие смены, выручка и сводка" },
  Adjustments: { key: "adjustments", title: "Штрафы и споры", hint: "Штрафы, списания и споры" },
  Expenses: { key: "expenses", title: "Расходы", hint: "Расходы и категории" },
  Shifts: { key: "shifts", title: "Смены", hint: "График и интервалы" },
  Staff: { key: "staff", title: "Команда", hint: "Сотрудники и управление" },
  Positions: { key: "positions", title: "Должности", hint: "Должности и права" },
  Venue: { key: "venue", title: "Заведение", hint: "Карточка и настройки" },
  Catalogs: { key: "catalogs", title: "Справочники", hint: "Оплаты, департаменты и KPI" },
  Payroll: { key: "payroll", title: "Зарплаты", hint: "Профили и начисления" },
};

function normalizePermissionCatalog(items = []) {
  const groups = [];
  const byKey = new Map();
  for (const raw of Array.isArray(items) ? items : []) {
    const code = String(raw?.code || "").trim().toUpperCase();
    if (!code) continue;
    const srcGroup = String(raw?.group || "Other").trim() || "Other";
    const meta = DEFAULT_META[srcGroup] || { key: srcGroup.toLowerCase(), title: srcGroup, hint: "" };
    let group = byKey.get(meta.key);
    if (!group) {
      group = { key: meta.key, title: meta.title, hint: meta.hint, items: [] };
      byKey.set(meta.key, group);
      groups.push(group);
    }
    group.items.push({ code, title: String(raw?.title || code).trim(), description: String(raw?.description || "").trim() });
  }
  groups.forEach((g) => g.items.sort((a, b) => a.title.localeCompare(b.title, "ru")));
  return groups;
}

async function ensurePermissionsCatalog() {
  if (Array.isArray(state.permissionsCatalog) && state.permissionsCatalog.length) return state.permissionsCatalog;
  try {
    const resp = await api('/me/permissions/catalog');
    state.permissionsCatalog = normalizePermissionCatalog(resp?.items || []);
  } catch {
    state.permissionsCatalog = [];
  }
  return state.permissionsCatalog;
}

function selectedTemplate() {
  const found = state.items.find((item) => String(item.id) === String(state.editorId || ''));
  return found || state.editorDraft || null;
}

function emptyDraft() {
  return { id: null, code: '', title: '', description: '', permission_codes: [], sort_order: '', is_active: true, is_system: false };
}

function renderPermissionChecklist(selectedCodes = []) {
  const selected = new Set((selectedCodes || []).map((code) => String(code || '').trim().toUpperCase()));
  const groups = Array.isArray(state.permissionsCatalog) ? state.permissionsCatalog : [];
  return groups.map((group) => `
    <div class="tpl-perm-group">
      <div class="row">
        <div>
          <b>${esc(group.title)}</b>
          ${group.hint ? `<div class="muted small mt-4">${esc(group.hint)}</div>` : ''}
        </div>
        <div class="tpl-perm-tools">
          <button class="btn sm" type="button" data-perm-set="${esc(group.key)}" data-value="1">Все</button>
          <button class="btn sm" type="button" data-perm-set="${esc(group.key)}" data-value="0">Ничего</button>
        </div>
      </div>
      ${(group.items || []).map((item) => `
        <div class="tpl-perm-row">
          <div>
            <div class="tpl-perm-title">${esc(item.title)}</div>
            ${item.description ? `<div class="tpl-perm-desc">${esc(item.description)}</div>` : ''}
          </div>
          <label class="switch">
            <input type="checkbox" data-perm-code="${esc(item.code)}" data-perm-group="${esc(group.key)}" ${selected.has(String(item.code).toUpperCase()) ? 'checked' : ''}>
            <span class="slider"></span>
          </label>
        </div>
      `).join('')}
    </div>
  `).join('');
}

function renderList() {
  const visible = state.showInactive ? state.items : state.items.filter((item) => item.is_active);
  if (!visible.length) return `<div class="tpl-state tpl-state--empty">Шаблонов пока нет. Можно создать свой или одним кликом добавить базовые пресеты.</div>`;
  return `
    <div class="tpl-list">
      ${visible.map((item) => {
        const labels = Array.isArray(item?.permission_summary?.summary_labels) ? item.permission_summary.summary_labels : [];
        return `
          <article class="tpl-item">
            <div class="row tpl-item__head">
              <div class="tpl-item__main">
                <b>${esc(item.title)}</b>
                <div class="muted mt-4">${esc(item.description || 'Без описания')}</div>
              </div>
              <div class="tpl-tags">
                ${item.is_system ? '<span class="tpl-tag">system</span>' : ''}
                ${item.is_active ? '<span class="tpl-tag">активен</span>' : '<span class="tpl-tag">архив</span>'}
                <span class="tpl-tag">прав: ${Number(item?.permission_summary?.permission_count || (item.permission_codes || []).length || 0)}</span>
              </div>
            </div>
            <div class="tpl-tags">${labels.length ? labels.map((label) => `<span class="tpl-tag">${esc(label)}</span>`).join('') : '<span class="muted">Группы не определены</span>'}</div>
            <div class="row tpl-item__footer">
              <div class="muted">Код: ${esc(item.code || '—')} · Порядок: ${Number(item.sort_order || 0)}</div>
              <div class="row tpl-actions">
                <button class="btn sm" type="button" data-edit="${esc(item.id)}">Изменить</button>
                <button class="btn sm ${item.is_active ? 'danger' : ''}" type="button" data-archive="${esc(item.id)}" data-value="${item.is_active ? '0' : '1'}">${item.is_active ? 'В архив' : 'Вернуть'}</button>
              </div>
            </div>
          </article>
        `;
      }).join('')}
    </div>
  `;
}

function renderEditor() {
  const item = selectedTemplate() || emptyDraft();
  const isNew = !item.id;
  return `
    <section class="card tpl-sticky">
      <div class="row tpl-editor-head">
        <div>
          <b>${isNew ? 'Новый шаблон' : 'Редактирование шаблона'}</b>
          <div class="muted mt-4">Шаблон применяется копированием прав. После применения владелец может вручную подправить конкретную должность.</div>
        </div>
        ${!isNew ? '<button class="btn subtle" id="btnResetEditor" type="button">Новый</button>' : ''}
      </div>
      <div class="tpl-field mt-12"><span>Код шаблона</span><input id="tplCode" class="input" placeholder="например shift_manager" value="${esc(item.code || '')}"></div>
      <div class="tpl-field mt-10"><span>Название шаблона</span><input id="tplTitle" class="input" placeholder="Например, Администратор зала" value="${esc(item.title || '')}"></div>
      <div class="tpl-field mt-10"><span>Описание</span><textarea id="tplDescription" class="input" rows="3" placeholder="Коротко опиши, для какой роли этот шаблон">${esc(item.description || '')}</textarea></div>
      <div class="tpl-field mt-10"><span>Порядок сортировки</span><input id="tplSortOrder" class="input" type="number" min="0" step="1" value="${esc(item.sort_order ?? '')}"></div>
      <label class="checkline mt-10"><input id="tplActive" type="checkbox" ${item.is_active !== false ? 'checked' : ''}><span>Шаблон активен и доступен владельцам</span></label>
      <div class="mt-12">${renderPermissionChecklist(item.permission_codes || [])}</div>
      <div class="row gap-8 mt-12 tpl-savebar"><button class="btn primary" id="btnSaveTemplate" type="button">${isNew ? 'Создать шаблон' : 'Сохранить изменения'}</button></div>
    </section>
  `;
}

function collectPermissionCodes() {
  return Array.from(root.querySelectorAll('input[data-perm-code]:checked'))
    .map((el) => String(el.getAttribute('data-perm-code') || '').trim().toUpperCase())
    .filter(Boolean);
}

function render() {
  root.innerHTML = `<div class="tpl-list-column">${renderList()}</div><div class="tpl-editor-column">${renderEditor()}</div>`;
  wire();
}

async function load() {
  setStatus('Загрузка…');
  const resp = await api(`/admin/position-permission-templates?include_inactive=${state.showInactive ? 'true' : 'false'}`);
  state.items = Array.isArray(resp?.items) ? resp.items : [];
  if (state.editorId) {
    const current = state.items.find((item) => String(item.id) === String(state.editorId));
    if (!current) state.editorId = null;
  }
  setStatus(`Шаблонов: ${state.items.length}`);
  render();
}

function setStatus(text) { statusEl.textContent = text || ''; }

function wire() {
  root.querySelectorAll('[data-edit]').forEach((btn) => btn.addEventListener('click', () => {
    state.editorId = btn.getAttribute('data-edit') || null;
    state.editorDraft = null;
    render();
  }));
  root.querySelectorAll('[data-archive]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-archive') || '';
    const isActive = btn.getAttribute('data-value') === '1';
    const item = state.items.find((row) => String(row.id) === String(id));
    if (!item) return;
    const ok = await confirmModal({
      title: isActive ? 'Вернуть шаблон?' : 'Архивировать шаблон?',
      text: isActive ? `Шаблон «${item.title}» снова станет доступен владельцам.` : `Шаблон «${item.title}» пропадёт из списков выбора, но уже созданные должности не изменятся.`,
      confirmText: isActive ? 'Вернуть' : 'В архив',
      danger: !isActive,
    });
    if (!ok) return;
    await api(`/admin/position-permission-templates/${encodeURIComponent(id)}/archive`, { method: 'POST', body: { is_active: isActive } });
    toast(isActive ? 'Шаблон возвращён' : 'Шаблон архивирован', 'ok');
    await load();
  }));
  root.querySelectorAll('[data-perm-set]').forEach((btn) => btn.addEventListener('click', () => {
    const group = btn.getAttribute('data-perm-set') || '';
    const turnOn = btn.getAttribute('data-value') === '1';
    root.querySelectorAll(`input[data-perm-group="${group}"]`).forEach((el) => { el.checked = turnOn; });
  }));
  document.getElementById('btnResetEditor')?.addEventListener('click', () => {
    state.editorId = null;
    state.editorDraft = null;
    render();
  });
  document.getElementById('btnSaveTemplate')?.addEventListener('click', async () => {
    const code = String(document.getElementById('tplCode')?.value || '').trim();
    const title = String(document.getElementById('tplTitle')?.value || '').trim();
    const description = String(document.getElementById('tplDescription')?.value || '').trim();
    const sortOrderRaw = String(document.getElementById('tplSortOrder')?.value || '').trim();
    const isActive = !!document.getElementById('tplActive')?.checked;
    if (!title) return toast('Укажи название шаблона', 'err');
    const payload = { code: code || null, title, description: description || null, sort_order: sortOrderRaw ? Number(sortOrderRaw) : 0, is_active: isActive, permission_codes: collectPermissionCodes() };
    if (!Number.isFinite(payload.sort_order) || payload.sort_order < 0) return toast('Порядок сортировки должен быть числом от 0', 'err');
    if (state.editorId) await api(`/admin/position-permission-templates/${encodeURIComponent(state.editorId)}`, { method: 'PATCH', body: payload });
    else await api('/admin/position-permission-templates', { method: 'POST', body: payload });
    toast(state.editorId ? 'Шаблон обновлён' : 'Шаблон создан', 'ok');
    state.editorDraft = null;
    await load();
  });
}

btnNew?.addEventListener('click', () => {
  state.editorId = null;
  state.editorDraft = emptyDraft();
  render();
});

btnShowInactive?.addEventListener('click', async () => {
  state.showInactive = !state.showInactive;
  btnShowInactive.textContent = state.showInactive ? 'Скрыть архив' : 'Показывать архив';
  await load();
});

btnSeedDefaults?.addEventListener('click', async () => {
  await api('/admin/position-permission-templates/seed-defaults', { method: 'POST', body: { reactivate: true } });
  toast('Базовые шаблоны готовы', 'ok');
  await load();
});

await ensurePermissionsCatalog();
await load();

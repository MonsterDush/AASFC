import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  setActiveVenueId,
  getActiveVenueId,
  getMyVenuePermissions,
  api,
  isDemoUiMode,
} from "/app.js?v=20260813-i18n1";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function slugifyCategoryCode(value) {
  const map = { а:"a", б:"b", в:"v", г:"g", д:"d", е:"e", ё:"e", ж:"zh", з:"z", и:"i", й:"y", к:"k", л:"l", м:"m", н:"n", о:"o", п:"p", р:"r", с:"s", т:"t", у:"u", ф:"f", х:"h", ц:"ts", ч:"ch", ш:"sh", щ:"sch", ъ:"", ы:"y", ь:"", э:"e", ю:"yu", я:"ya" };
  return String(value || "")
    .trim()
    .toLowerCase()
    .split("")
    .map((ch) => (map[ch] !== undefined ? map[ch] : ch))
    .join("")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
    .slice(0, 64) || "expense";
}

let state = { venueId: "", items: [], loadError: "", includeArchived: false, canManage: false, canView: false };

function renderShell() {
  root.innerHTML = `
    <div class="topbar catalog-topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b>Категории расходов</b>
          <div class="muted">для учёта расходов</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card catalog-hero">
      <div class="muted catalog-intro">Соберите единый список статей, которые сотрудники смогут выбирать при добавлении расходов.</div>
      <div class="itemcard catalog-list-card">
        <div class="section-head">
          <div class="section-title"><b>Список категорий</b></div>
          <div class="section-actions"><button class="btn primary" id="btnCreate">+ Добавить</button></div>
        </div>
        <div class="section-actions catalog-filter" id="catalogFilter">
          <label class="chk"><input type="checkbox" id="showArchived" /><span class="muted">Показывать архив</span></label>
        </div>
        <div id="list" class="catalog-list" aria-live="polite"><div class="catalog-loading" aria-busy="true"><div class="skeleton"></div><div class="skeleton"></div></div></div>
      </div>
      <div class="catalog-footer"><button class="btn subtle inline" id="back" type="button" data-nav-button>← К расходам</button></div>
    </div>

    <div id="toast" class="toast"><div class="toast__text"></div></div>
    <div id="modal" class="modal">
      <div class="modal__backdrop"></div>
      <div class="modal__panel">
        <div class="modal__head"><div class="modal__title">Подтверждение</div><button class="btn" data-close>Закрыть</button></div>
        <div class="modal__body"></div>
      </div>
    </div>
    <div id="editModal" class="modal">
      <div class="modal__backdrop" data-close></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div><b class="modal__title" id="editTitle">Категория расхода</b><div class="muted small mt-4" id="editHint"></div></div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body" id="editBody"></div>
      </div>
    </div>

    <div class="nav"><div class="wrap"><div id="nav"></div></div></div>
  `;
  mountCommonUI("none");
}

function openEditModal({ title, hint, bodyHtml }) {
  document.getElementById("editTitle").textContent = title || "Категория расхода";
  document.getElementById("editHint").textContent = hint || "";
  document.getElementById("editBody").innerHTML = bodyHtml || "";
  document.getElementById("editModal")?.classList.add("open");
}
function closeEditModal() { document.getElementById("editModal")?.classList.remove("open"); }
function wireEditModalClose() { document.querySelectorAll("#editModal [data-close]").forEach((x) => x.addEventListener("click", closeEditModal)); }

function renderList() {
  const el = document.getElementById("list");
  if (!el) return;
  if (!state.canView) { el.innerHTML = `<div class="catalog-state catalog-state--denied"><b>Нет доступа к категориям расходов</b><span>Обратитесь к владельцу заведения, чтобы получить право просмотра.</span></div>`; return; }
  if (state.loadError) { el.innerHTML = `<div class="catalog-state catalog-state--error"><b>Не удалось загрузить категории расходов</b><span>${esc(state.loadError)}</span></div>`; return; }
  if (!state.items.length) { el.innerHTML = `<div class="catalog-state catalog-state--empty"><b>Категорий расходов пока нет</b><span>Добавьте первую категорию для корректного учёта расходов.</span></div>`; return; }
  el.innerHTML = state.items.map((it) => `
    <div class="catalog-row">
      <div class="catalog-row__copy">
        <div class="catalog-row__title">
          <b>${esc(it.title)}</b>
          ${it.is_active ? "" : `<span class="badge">архив</span>`}
        </div>
        <div class="muted catalog-row__meta">${it.is_active ? "Доступна при создании расхода" : "Скрыта из списка"}</div>
      </div>
      <div class="catalog-row__actions${state.canManage ? "" : " hidden"}">
        <button class="btn sm" data-edit="${it.id}">Изменить</button>
        <button class="btn sm ${it.is_active ? "danger" : ""}" data-archive="${it.id}">${it.is_active ? "В архив" : "Вернуть"}</button>
      </div>
    </div>
  `).join("");
  el.querySelectorAll("[data-edit]").forEach((btn) => btn.onclick = () => openEditor(state.items.find((x) => String(x.id) === String(btn.dataset.edit))));
  el.querySelectorAll("[data-archive]").forEach((btn) => btn.onclick = async () => {
    const item = state.items.find((x) => String(x.id) === String(btn.dataset.archive));
    if (!item) return;
    const ok = await confirmModal({
      title: item.is_active ? "Архивировать категорию?" : "Восстановить категорию?",
      text: `${item.is_active ? "Убрать" : "Вернуть"} "${item.title}"?`,
      confirmText: item.is_active ? "В архив" : "Вернуть",
      danger: !!item.is_active,
    });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/expense-categories/${encodeURIComponent(item.id)}`, { method: "PATCH", body: { is_active: !item.is_active } });
      toast("Готово", "ok");
      await load();
    } catch (e) {
      toast(e?.data?.detail || e.message || "Ошибка", "err");
    }
  });
}

function editorForm(item = null) {
  const it = item || {};
  return `
    <div class="grid grid2 catalog-form">
      <div>
        <div class="muted mb-6">Название</div>
        <input id="f_title" placeholder="Аренда" value="${esc(it.title || "")}" />
      </div>
      <div>
        <div class="muted mb-6">Порядок в списке</div>
        <input id="f_sort" inputmode="numeric" placeholder="0" value="${esc(it.sort_order ?? 0)}" />
      </div>
      <div>
        <div class="muted mb-6">Отображение</div>
        <label class="row gap-8 ai-center">
          <input type="checkbox" id="f_active" ${(it.is_active ?? true) ? "checked" : ""} />
          <span>Показывать в списке</span>
        </label>
      </div>
    </div>
    <div class="catalog-modal-actions">
      <button class="btn ghost" id="btnCancel">Отмена</button>
      <button class="btn primary" id="btnSave">Сохранить</button>
    </div>
  `;
}

function openEditor(item = null) {
  openEditModal({ title: item ? "Редактировать категорию" : "Добавить категорию", hint: item ? "Изменения применятся сразу после сохранения" : "Название можно изменить позже", bodyHtml: editorForm(item) });
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  const titleEl = document.getElementById("f_title");
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const payload = {
      code: slugifyCategoryCode(titleEl?.value || ""),
      title: String(titleEl?.value || "").trim(),
      sort_order: Number(document.getElementById("f_sort")?.value || 0),
      is_active: !!document.getElementById("f_active")?.checked,
    };
    if (!payload.title) { toast("Введите название", "warn"); return; }
    try {
      if (item) {
        await api(`/venues/${encodeURIComponent(state.venueId)}/expense-categories/${encodeURIComponent(item.id)}`, { method: "PATCH", body: payload });
        toast("Категория обновлена", "ok");
      } else {
        await api(`/venues/${encodeURIComponent(state.venueId)}/expense-categories`, { method: "POST", body: payload });
        toast("Категория добавлена", "ok");
      }
      closeEditModal();
      await load();
    } catch (e) {
      toast(e?.data?.detail || e.message || "Не удалось сохранить", "err");
    }
  });
}

async function load() {
  const listEl = document.getElementById("list");
  if (listEl) listEl.innerHTML = `<div class="catalog-loading" aria-busy="true"><div class="skeleton"></div><div class="skeleton"></div></div>`;
  if (!state.canView) {
    state.items = [];
    state.loadError = "";
    renderList();
    return;
  }
  try {
    const rows = await api(`/venues/${encodeURIComponent(state.venueId)}/expense-categories?include_archived=${state.includeArchived ? "true" : "false"}`);
    state.items = Array.isArray(rows) ? rows : [];
    state.loadError = "";
  } catch (e) {
    state.items = [];
    state.loadError = e?.data?.detail || e?.message || "Повторите попытку позже.";
    toast("Ошибка загрузки", "err");
  }
  renderList();
}

async function boot() {
  applyTelegramTheme();
  await ensureLogin({ silent: true });
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);
  state.venueId = getActiveVenueId() || venueId || "";
  renderShell();
  await mountNav({ activeTab: "expenses", requireVenue: true });
  wireEditModalClose();

  try {
    const permsResp = await getMyVenuePermissions(state.venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    state.canView = role === "OWNER" || role === "VENUE_OWNER" || hasPerm(pset, "EXPENSE_CATEGORIES_MANAGE");
    state.canManage = !isDemoUiMode(permsResp) && state.canView;
  } catch {
    state.canView = false;
    state.canManage = false;
  }
  document.getElementById("catalogFilter")?.classList.toggle("hidden", !state.canView);

  document.getElementById("showArchived").checked = state.includeArchived;
  document.getElementById("showArchived").onchange = async (e) => { state.includeArchived = !!e.target.checked; await load(); };
  document.getElementById("btnCreate").onclick = () => openEditor();
  document.getElementById("btnCreate").classList.toggle("hidden", !state.canManage);
  document.getElementById("back").href = `/owner-expenses.html?venue_id=${encodeURIComponent(state.venueId)}`;

  await load();
}

document.addEventListener("DOMContentLoaded", boot);

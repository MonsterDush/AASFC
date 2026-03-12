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
} from "/app.js";
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

let state = { venueId: "", items: [], includeArchived: false, canManage: false };

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b>Категории расходов</b>
          <div class="muted">просмотр, редактирование и архив</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="itemcard">
        <div class="section-head">
          <div class="section-title"><b>Список категорий</b></div>
          <div class="section-actions"><button class="btn primary" id="btnCreate">+ Добавить</button></div>
        </div>
        <div class="section-actions">
          <label class="chk"><input type="checkbox" id="showArchived" /><span class="muted">Показывать архив</span></label>
        </div>
        <div id="list" style="margin-top:10px"><div class="skeleton"></div><div class="skeleton"></div></div>
      </div>
      <div class="row" style="margin-top:12px"><a class="link" id="back" href="#">← К расходам</a></div>
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
          <div><b class="modal__title" id="editTitle">Категория расхода</b><div class="muted" id="editHint" style="margin-top:4px; font-size:12px"></div></div>
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
  if (!state.canManage) { el.innerHTML = `<div class="muted">Нет доступа</div>`; return; }
  if (!state.items.length) { el.innerHTML = `<div class="muted">Пока пусто</div>`; return; }
  el.innerHTML = state.items.map((it) => `
    <div class="listrow">
      <div class="listrow__left">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
          <b>${esc(it.title)}</b>
          ${it.is_active ? "" : `<span class="badge">архив</span>`}
        </div>
        <div class="mono muted listrow__meta">code=${esc(it.code)} · sort=${esc(it.sort_order)}</div>
      </div>
      <div class="row row--nowrap" style="gap:8px; flex:0 0 auto;">
        <button class="btn sm" data-edit="${it.id}">Редакт.</button>
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
    <div class="grid grid2" style="margin-top:10px">
      <div>
        <div class="muted" style="margin-bottom:6px">Код</div>
        <input id="f_code" placeholder="rent" value="${esc(it.code || "")}" />
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Название</div>
        <input id="f_title" placeholder="Аренда" value="${esc(it.title || "")}" />
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Порядок</div>
        <input id="f_sort" inputmode="numeric" placeholder="0" value="${esc(it.sort_order ?? 0)}" />
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Статус</div>
        <label class="row" style="gap:8px; align-items:center">
          <input type="checkbox" id="f_active" ${(it.is_active ?? true) ? "checked" : ""} />
          <span>Активна</span>
        </label>
      </div>
    </div>
    <div class="row" style="margin-top:12px; justify-content:flex-end; gap:8px">
      <button class="btn ghost" id="btnCancel">Отмена</button>
      <button class="btn primary" id="btnSave">Сохранить</button>
    </div>
  `;
}

function openEditor(item = null) {
  openEditModal({ title: item ? "Редактировать категорию" : "Добавить категорию", hint: item ? "Изменения применятся сразу после сохранения" : "Код можно поправить вручную", bodyHtml: editorForm(item) });
  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  const titleEl = document.getElementById("f_title");
  const codeEl = document.getElementById("f_code");
  if (!item && titleEl && codeEl) titleEl.addEventListener("input", () => { if (!codeEl.dataset.touched) codeEl.value = slugifyCategoryCode(titleEl.value); });
  if (codeEl) codeEl.addEventListener("input", () => { codeEl.dataset.touched = "1"; });
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const payload = {
      code: String(codeEl?.value || slugifyCategoryCode(titleEl?.value || "")).trim() || slugifyCategoryCode(titleEl?.value || ""),
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
  const rows = await api(`/venues/${encodeURIComponent(state.venueId)}/expense-categories?include_archived=${state.includeArchived ? "true" : "false"}`);
  state.items = Array.isArray(rows) ? rows : [];
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
    state.canManage = role === "OWNER" || role === "VENUE_OWNER" || hasPerm(pset, "EXPENSE_CATEGORIES_MANAGE");
  } catch {
    state.canManage = false;
  }

  document.getElementById("showArchived").checked = state.includeArchived;
  document.getElementById("showArchived").onchange = async (e) => { state.includeArchived = !!e.target.checked; await load(); };
  document.getElementById("btnCreate").onclick = () => openEditor();
  document.getElementById("btnCreate").style.display = state.canManage ? "" : "none";
  document.getElementById("back").href = `/owner-expenses.html?venue_id=${encodeURIComponent(state.venueId)}`;

  try {
    await load();
  } catch (e) {
    document.getElementById("list").innerHTML = `<div class="muted">${esc(e?.data?.detail || e.message || "Ошибка загрузки")}</div>`;
  }
}

document.addEventListener("DOMContentLoaded", boot);

import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  setActiveVenueId,
  getMyVenuePermissions,
  getMe,
  getPayProfiles,
  createPayProfile,
  updatePayProfile,
  deletePayProfile,
  applyDemoReadonlyCaps,
} from "/app.js?v=20260820-i18nmetrika1";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const id = params.get("venue_id") || "";
  if (id) setActiveVenueId(id);
  return id;
}

function capFirst(s) {
  const v = String(s || "").trim();
  return v ? v.charAt(0).toUpperCase() + v.slice(1) : "";
}

let state = {
  venueId: "",
  perms: null,
  me: null,
  items: [],
  includeInactive: false,
  can: { view: false, manage: false },
};

function renderShell() {
  root.innerHTML = `
    <div class="topbar pay-profile-topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Профили зарплаты</b>
          <div class="muted">шаблоны начислений для сотрудников</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <main class="pay-profile-content">
    <section class="card pay-profile-hero">
      <div class="muted pay-profile-intro">Здесь настраиваются шаблоны начислений: оклад, почасовая ставка и фикс за смену. Назначения к сотрудникам редактируются внутри карточки профиля.</div>

      <div class="itemcard pay-profile-list-card">
        <div class="section-head">
          <div class="section-title">
            <b>Список профилей</b>
          </div>
          <div class="section-actions">
            <button class="btn primary" id="btnCreate">+ Добавить профиль</button>
          </div>
        </div>

        <div class="section-actions">
          <label class="chk pay-profile-filter">
            <input type="checkbox" id="showInactive" />
            <span class="muted">Показывать неактивные</span>
          </label>
        </div>

        <div id="list" class="pay-profile-list">
          <div class="pay-profile-loading"><div class="skeleton"></div><div class="skeleton"></div></div>
        </div>
      </div>

      <div class="pay-profile-footer">
        <button class="btn subtle inline" id="back" type="button" data-nav-button>← Назад к заведению</button>
      </div>
    </section>
    </main>

    <div id="toast" class="toast"><div class="toast__text"></div></div>

    <div id="modal" class="modal">
      <div class="modal__backdrop"></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div class="modal__title">Подтверждение</div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body"></div>
      </div>
    </div>

    <div id="editModal" class="modal">
      <div class="modal__backdrop" data-close></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="editTitle">Профиль зарплаты</b>
            <div class="muted small mt-4" id="editHint"></div>
          </div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body" id="editBody"></div>
      </div>
    </div>

    <div class="nav"><div class="wrap"><div id="nav"></div></div></div>
  `;

  mountCommonUI("none");
}

function closeEditModal() {
  document.getElementById("editModal")?.classList.remove("open");
}

function openEditModal({ title, hint, bodyHtml }) {
  const modal = document.getElementById("editModal");
  const titleEl = document.getElementById("editTitle");
  const hintEl = document.getElementById("editHint");
  const bodyEl = document.getElementById("editBody");
  if (titleEl) titleEl.textContent = title || "Профиль зарплаты";
  if (hintEl) hintEl.textContent = hint || "";
  if (bodyEl) bodyEl.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function wireEditModalClose() {
  const m = document.getElementById("editModal");
  if (!m) return;
  m.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeEditModal));
}

function computeCaps(perms, me) {
  const role = roleUpper(perms);
  const pset = permSetFromResponse(perms);
  const sysRole = String(me?.system_role || "").toUpperCase();
  const isOwner = role === "OWNER" || role === "VENUE_OWNER";
  const isAdmin = sysRole === "SUPER_ADMIN" || sysRole === "MODERATOR";
  return {
    view: isOwner || isAdmin || hasPerm(pset, "PAY_PROFILES_VIEW") || hasPerm(pset, "PAY_PROFILES_MANAGE"),
    manage: isOwner || isAdmin || hasPerm(pset, "PAY_PROFILES_MANAGE"),
  };
}

function renderList() {
  const el = document.getElementById("list");
  const btnCreate = document.getElementById("btnCreate");
  const chk = document.getElementById("showInactive");
  const back = document.getElementById("back");

  btnCreate?.classList.toggle("hidden", !state.can.manage);
  if (chk) chk.checked = !!state.includeInactive;
  if (back) back.href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;

  if (!el) return;
  if (!state.can.view) {
    el.innerHTML = `<div class="pay-profile-state pay-profile-state--denied"><b>Нет доступа</b><span>Для просмотра профилей оплаты нужны соответствующие права.</span></div>`;
    return;
  }
  if (!state.items.length) {
    el.innerHTML = `<div class="pay-profile-state pay-profile-state--empty"><b>Профилей пока нет</b><span>Создай первый профиль, чтобы настроить компоненты и назначения сотрудникам.</span></div>`;
    return;
  }

  el.innerHTML = "";
  state.items.forEach((it) => {
    const row = document.createElement("div");
    row.className = "pay-profile-row";

    const left = document.createElement("div");
    left.className = "pay-profile-row__copy";
    left.innerHTML = `
      <div class="pay-profile-row__title">
        <b>${esc(it.title)}</b>
        ${it.is_active ? "" : `<span class="badge">неактивен</span>`}
      </div>
      <div class="muted">${esc(it.description || "Без описания")}</div>
      <div class="mono small">Компонентов: ${Number(it.components_count || 0)} · Назначений: ${Number(it.assignments_count || 0)}</div>
    `;

    const right = document.createElement("div");
    right.className = "pay-profile-row__actions";

    const openBtn = document.createElement("a");
    openBtn.className = "btn sm";
    openBtn.href = `/owner-pay-profile.html?venue_id=${encodeURIComponent(state.venueId)}&profile_id=${encodeURIComponent(it.id)}`;
    openBtn.textContent = "Открыть";
    right.appendChild(openBtn);

    if (state.can.manage) {
      const editBtn = document.createElement("button");
      editBtn.className = "btn sm";
      editBtn.textContent = "Изменить";
      editBtn.onclick = () => openEditor({ mode: "edit", item: it });
      right.appendChild(editBtn);

      const toggleBtn = document.createElement("button");
      toggleBtn.className = "btn sm" + (it.is_active ? " danger" : "");
      toggleBtn.textContent = it.is_active ? "Отключить" : "Включить";
      toggleBtn.onclick = async () => {
        try {
          await updatePayProfile(state.venueId, it.id, { is_active: !it.is_active });
          toast("Сохранено", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
        }
      };
      right.appendChild(toggleBtn);

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "btn sm danger";
      deleteBtn.textContent = "Удалить";
      deleteBtn.onclick = async () => {
        const ok = await confirmModal({
          title: "Удалить профиль?",
          text: `Профиль "${it.title}" будет удалён безвозвратно.`,
          confirmText: "Удалить",
          danger: true,
        });
        if (!ok) return;
        try {
          await deletePayProfile(state.venueId, it.id);
          toast("Профиль удалён", "ok");
          await load();
        } catch (e) {
          toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось удалить"), "err");
        }
      };
      right.appendChild(deleteBtn);
    }

    row.appendChild(left);
    row.appendChild(right);
    el.appendChild(row);
  });
}

function editorForm({ mode, item }) {
  const it = item || {};
  const activeChecked = (mode === "edit" ? !!it.is_active : true) ? "checked" : "";
  return `
    <div class="finance-form mt-8">
      <label>
        <span>Название</span>
        <input id="f_title" placeholder="Бармен — ставка" value="${esc(it.title || "")}" />
      </label>
      <label>
        <span>Описание</span>
        <textarea id="f_description" rows="4" placeholder="Например: базовый профиль для барменов">${esc(it.description || "")}</textarea>
      </label>
      <label class="chk">
        <input type="checkbox" id="f_active" ${activeChecked} />
        <span>Профиль активен</span>
      </label>
    </div>

    <div class="pay-profile-modal-actions">
      <button class="btn" id="btnCancel" type="button">Отмена</button>
      <button class="btn primary" id="btnSave" type="button">Сохранить</button>
    </div>
  `;
}

function openEditor({ mode, item = null }) {
  if (!state.can.manage) return;
  const isEdit = mode === "edit";
  openEditModal({
    title: isEdit ? "Редактировать профиль" : "Новый профиль",
    hint: isEdit ? "Изменения применятся сразу после сохранения" : "После создания откроется карточка профиля",
    bodyHtml: editorForm({ mode, item }),
  });

  document.getElementById("btnCancel")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSave")?.addEventListener("click", async () => {
    const title = String(document.getElementById("f_title")?.value || "").trim();
    const description = String(document.getElementById("f_description")?.value || "").trim();
    const isActive = !!document.getElementById("f_active")?.checked;

    if (!title) {
      toast("Укажи название профиля", "warn");
      return;
    }

    const payload = {
      title,
      description: description || null,
      is_active: isActive,
    };

    try {
      if (isEdit && item?.id) {
        await updatePayProfile(state.venueId, item.id, payload);
        toast("Профиль обновлён", "ok");
        closeEditModal();
        await load();
        return;
      }

      const created = await createPayProfile(state.venueId, payload);
      toast("Профиль создан", "ok");
      closeEditModal();
      location.href = `/owner-pay-profile.html?venue_id=${encodeURIComponent(state.venueId)}&profile_id=${encodeURIComponent(created.id)}`;
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

async function load() {
  const list = document.getElementById("list");
  if (!state.can.view) {
    state.items = [];
    renderList();
    return;
  }
  if (list) list.innerHTML = `<div class="pay-profile-loading"><div class="skeleton"></div><div class="skeleton"></div></div>`;

  try {
    state.items = await getPayProfiles(state.venueId, { includeInactive: state.includeInactive });
    renderList();
  } catch (e) {
    if (list) {
      list.innerHTML = `<div class="pay-profile-state pay-profile-state--error"><b>Не удалось загрузить профили</b><span>${esc(e?.data?.detail || e?.message || "Проверь подключение и повтори попытку.")}</span></div>`;
    }
    toast("Не удалось загрузить профили", "err");
  }
}

async function boot() {
  applyTelegramTheme();
  renderShell();
  wireEditModalClose();
  await ensureLogin({ silent: true });

  state.venueId = parseVenueId();
  if (!state.venueId) {
    root.innerHTML = `<div class="pay-profile-state"><b>Не выбрано заведение</b><span>Открой профили оплаты из карточки нужного заведения.</span></div>`;
    return;
  }

  await mountNav({ activeTab: "summary" });

  try {
    state.me = await getMe();
  } catch {
    state.me = null;
  }

  try {
    state.perms = await getMyVenuePermissions(state.venueId);
  } catch {
    state.perms = null;
  }

  state.can = applyDemoReadonlyCaps(computeCaps(state.perms, state.me), { source: state.perms });

  document.getElementById("btnCreate")?.addEventListener("click", () => openEditor({ mode: "create" }));
  document.getElementById("showInactive")?.addEventListener("change", (e) => {
    state.includeInactive = !!e.target.checked;
    load();
  });

  await load();
}

document.addEventListener("DOMContentLoaded", boot);

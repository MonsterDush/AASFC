import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  api,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
} from "/app.js?v=20260321-miniappfix1";

import { permSetFromResponse, roleUpper, hasPerm, isSysAdminRole, isOwnerRole } from "/permissions.js?v=20260321-miniappfix1";

const root = document.getElementById("root");
applyTelegramTheme();
await ensureLogin({ silent: true });

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function normalizeList(out) {
  if (Array.isArray(out)) return out;
  if (Array.isArray(out?.items)) return out.items;
  if (Array.isArray(out?.data)) return out.data;
  if (Array.isArray(out?.results)) return out.results;
  return [];
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const id = params.get("venue_id") || "";
  if (id) setActiveVenueId(id);
  return id;
}

function canManageIntervals({ me, perms }) {
  const pset = permSetFromResponse(perms);
  const venueRole = roleUpper(perms);
  const sysRole = String(me?.system_role || "").toUpperCase();
  return isOwnerRole(venueRole) || isSysAdminRole(sysRole) || hasPerm(pset, "SHIFTS_MANAGE");
}

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b>Интервалы смен</b>
          <div class="muted">создание, редактирование и архив</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="muted">Интервалы используются в графике и при создании смен. Если интервал уже участвовал в сменах, его можно архивировать, но нельзя удалить.</div>

      <div class="itemcard" style="margin-top:12px">
        <div class="section-head">
          <div class="section-title">
            <b>Список интервалов</b>
          </div>
          <div class="section-actions">
            <button class="btn primary" id="btnCreate">+ Добавить</button>
          </div>
        </div>
        <div class="section-actions">
          <label class="chk">
            <input type="checkbox" id="showArchived" />
            <span class="muted">Показывать архив</span>
          </label>
        </div>
        <div id="list" style="margin-top:10px"><div class="skeleton"></div><div class="skeleton"></div></div>
      </div>

      <div class="row" style="margin-top:12px; gap:10px; flex-wrap:wrap">
        <a class="link" id="backToShifts" href="#">← Назад к графику</a>
        <a class="link" id="backToVenue" href="#">К заведению</a>
      </div>
    </div>

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
            <b class="modal__title" id="editTitle">Интервал</b>
            <div class="muted" id="editHint" style="margin-top:4px; font-size:12px"></div>
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

function openEditModal({ title, hint, bodyHtml }) {
  const m = document.getElementById("editModal");
  const t = document.getElementById("editTitle");
  const h = document.getElementById("editHint");
  const b = document.getElementById("editBody");
  if (t) t.textContent = title || "Интервал";
  if (h) h.textContent = hint || "";
  if (b) b.innerHTML = bodyHtml || "";
  m?.classList.add("open");
}

function closeEditModal() {
  document.getElementById("editModal")?.classList.remove("open");
}

function wireEditModalClose() {
  const m = document.getElementById("editModal");
  if (!m) return;
  m.querySelectorAll("[data-close]").forEach((x) => x.addEventListener("click", closeEditModal));
}

const state = {
  venueId: parseVenueId(),
  me: null,
  perms: null,
  items: [],
  includeArchived: false,
  canManage: false,
};

function sortIntervals(list) {
  return [...list].sort((a, b) => {
    const aa = `${a?.start_time || ""}|${a?.end_time || ""}|${a?.title || ""}`;
    const bb = `${b?.start_time || ""}|${b?.end_time || ""}|${b?.title || ""}`;
    return aa.localeCompare(bb, "ru");
  });
}

function renderList() {
  const el = document.getElementById("list");
  if (!el) return;

  if (!state.canManage) {
    el.innerHTML = `<div class="muted">Нет доступа к управлению интервалами</div>`;
    return;
  }

  if (!state.items.length) {
    el.innerHTML = `<div class="muted">Пока нет интервалов</div>`;
    return;
  }

  el.innerHTML = "";
  for (const item of sortIntervals(state.items)) {
    const row = document.createElement("div");
    row.className = "listrow";
    row.innerHTML = `
      <div class="listrow__left">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
          <b>${esc(item.title)}</b>
          ${item.is_active ? "" : `<span class="badge">архив</span>`}
        </div>
        <div class="mono muted listrow__meta">${esc(item.start_time)}–${esc(item.end_time)} · Смен: ${Number(item.usage_count || 0)}</div>
      </div>
      <div class="row row--nowrap" style="gap:8px; flex:0 0 auto;">
        <button class="btn sm" data-edit="${item.id}">Редакт.</button>
        <button class="btn sm ${item.is_active ? "danger" : ""}" data-archive="${item.id}">${item.is_active ? "В архив" : "Вернуть"}</button>
        ${item.can_delete ? `<button class="btn sm danger" data-delete="${item.id}">Удалить</button>` : ""}
      </div>
    `;
    el.appendChild(row);
  }

  el.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = state.items.find((x) => String(x.id) === String(btn.getAttribute("data-edit")));
      if (item) openEditor({ mode: "edit", item });
    });
  });

  el.querySelectorAll("[data-archive]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const item = state.items.find((x) => String(x.id) === String(btn.getAttribute("data-archive")));
      if (!item) return;
      const nextActive = !item.is_active;
      const ok = await confirmModal({
        title: nextActive ? "Вернуть интервал?" : "Архивировать интервал?",
        text: `${nextActive ? "Вернуть" : "Убрать в архив"} интервал «${item.title}»?`,
        confirmText: nextActive ? "Вернуть" : "В архив",
        danger: !nextActive,
      });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          body: { is_active: nextActive },
        });
        toast("Готово", "ok");
        await load();
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось обновить интервал", "err");
      }
    });
  });

  el.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const item = state.items.find((x) => String(x.id) === String(btn.getAttribute("data-delete")));
      if (!item) return;
      const ok = await confirmModal({
        title: "Удалить интервал?",
        text: `Интервал «${item.title}» будет удалён без возможности восстановления.`,
        confirmText: "Удалить",
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(item.id)}`, {
          method: "DELETE",
        });
        toast("Интервал удалён", "ok");
        await load();
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось удалить интервал", "err");
      }
    });
  });
}

function editorForm({ mode, item }) {
  const it = item || {};
  const isEdit = mode === "edit";
  return `
    <div class="grid grid2" style="margin-top:10px">
      <div>
        <div class="muted" style="margin-bottom:6px">Название</div>
        <input id="f_title" class="input" placeholder="Например, Утро" value="${esc(it.title || "")}" />
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Статус</div>
        <label class="chk">
          <input type="checkbox" id="f_active" ${it.is_active === false ? "" : "checked"} />
          <span class="muted">Активен</span>
        </label>
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Начало</div>
        <input id="f_start" class="input" type="time" value="${esc(it.start_time || "")}" />
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Конец</div>
        <input id="f_end" class="input" type="time" value="${esc(it.end_time || "")}" />
      </div>
    </div>

    <div class="row" style="margin-top:12px; justify-content:flex-end; gap:8px">
      <button class="btn" id="btnCancelEdit">Отмена</button>
      <button class="btn primary" id="btnSaveEdit">${isEdit ? "Сохранить" : "Создать"}</button>
    </div>
  `;
}

function openEditor({ mode, item }) {
  const isEdit = mode === "edit";
  openEditModal({
    title: isEdit ? "Редактирование интервала" : "Новый интервал",
    hint: isEdit ? `Смен уже использовало: ${Number(item?.usage_count || 0)}` : "Интервал будет доступен при создании смен",
    bodyHtml: editorForm({ mode, item }),
  });

  document.getElementById("btnCancelEdit")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSaveEdit")?.addEventListener("click", async () => {
    const title = document.getElementById("f_title")?.value?.trim();
    const start = document.getElementById("f_start")?.value?.trim();
    const end = document.getElementById("f_end")?.value?.trim();
    const is_active = !!document.getElementById("f_active")?.checked;

    if (!title) return toast("Укажи название", "warn");
    if (!/^\d{2}:\d{2}$/.test(start || "")) return toast("Укажи время начала", "warn");
    if (!/^\d{2}:\d{2}$/.test(end || "")) return toast("Укажи время окончания", "warn");

    try {
      if (isEdit) {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          body: { title, start_time: start, end_time: end, is_active },
        });
        toast("Интервал обновлён", "ok");
      } else {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals`, {
          method: "POST",
          body: { title, start_time: start, end_time: end, is_active },
        });
        toast("Интервал создан", "ok");
      }
      closeEditModal();
      await load();
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось сохранить интервал", "err");
    }
  });
}

async function load() {
  const out = await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals?include_inactive=${state.includeArchived ? 1 : 0}`);
  state.items = normalizeList(out);
  renderList();
}

renderShell();
wireEditModalClose();

state.me = await getMe().catch(() => null);
state.perms = await getMyVenuePermissions(state.venueId).catch(() => null);
state.canManage = canManageIntervals({ me: state.me, perms: state.perms });

await mountNav({ activeTab: "shifts", requireVenue: true });

document.getElementById("backToShifts")?.setAttribute("href", `/staff-shifts.html?venue_id=${encodeURIComponent(state.venueId)}`);
document.getElementById("backToVenue")?.setAttribute("href", `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`);
document.getElementById("btnCreate")?.addEventListener("click", () => openEditor({ mode: "create" }));
document.getElementById("btnCreate")?.classList.toggle("hidden", !state.canManage);
document.getElementById("showArchived")?.addEventListener("change", async (e) => {
  state.includeArchived = !!e.target.checked;
  await load();
});

await load();

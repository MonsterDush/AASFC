import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  getMyVenuePermissions,
  api,
  toast,
  closeModal,
  confirmModal,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

const state = {
  includeInactive: false,
  profiles: [],
  access: {
    canView: false,
    canManage: false,
    canViewPayroll: false,
  },
};

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtDate(value) {
  if (!value) return "—";
  try {
    return new Intl.DateTimeFormat("ru-RU").format(new Date(value));
  } catch {
    return String(value);
  }
}

function showEmpty(message) {
  const list = document.getElementById("profilesList");
  if (list) list.innerHTML = `<div class="muted">${esc(message)}</div>`;
}

function openHtmlModal(title, html) {
  const modal = document.getElementById("modal");
  if (!modal) return;
  const head = modal.querySelector(".modal__title");
  const body = modal.querySelector(".modal__body");
  if (head) head.textContent = title;
  if (body) body.innerHTML = html;
  modal.classList.add("open");
}

async function loadAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return state.access;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    state.access = {
      canView: isOwner || hasPerm(pset, "PAY_PROFILES_VIEW") || hasPerm(pset, "PAY_PROFILES_MANAGE"),
      canManage: isOwner || hasPerm(pset, "PAY_PROFILES_MANAGE"),
      canViewPayroll: isOwner || hasPerm(pset, "PAYROLL_VIEW") || hasPerm(pset, "PAYROLL_CALCULATE"),
    };
  } catch {
    state.access = { canView: false, canManage: false, canViewPayroll: false };
  }
  return state.access;
}

function syncActions() {
  const addBtn = document.getElementById("addProfileBtn");
  const payrollBtn = document.getElementById("openPayrollBtn");
  const venueId = getActiveVenueId();
  if (addBtn) addBtn.style.display = state.access.canManage ? "" : "none";
  if (payrollBtn) {
    payrollBtn.style.display = state.access.canViewPayroll ? "" : "none";
    payrollBtn.onclick = () => {
      location.href = `/owner-payroll.html?venue_id=${encodeURIComponent(venueId)}`;
    };
  }
}

function profileStatusBadge(profile) {
  return profile?.is_active ? '<span class="badge">Активный</span>' : '<span class="badge">Неактивный</span>';
}

function renderProfiles() {
  const list = document.getElementById("profilesList");
  const hint = document.getElementById("profilesHint");
  const stateEl = document.getElementById("profilesState");
  if (!list) return;

  if (!state.access.canView) {
    showEmpty("Нет прав на просмотр профилей зарплаты.");
    if (hint) hint.textContent = "Доступ ограничен";
    if (stateEl) stateEl.textContent = "Нет доступа";
    return;
  }

  if (!state.profiles.length) {
    showEmpty(state.includeInactive ? "Профилей пока нет." : "Активных профилей пока нет.");
    if (hint) hint.textContent = "0 профилей";
    if (stateEl) stateEl.textContent = "Пусто";
    return;
  }

  if (hint) hint.textContent = `${state.profiles.length} проф.`;
  if (stateEl) stateEl.textContent = state.includeInactive ? "Все профили" : "Только активные";

  list.innerHTML = state.profiles.map((profile) => {
    const desc = profile.description ? `<div class="muted mt-6">${esc(profile.description)}</div>` : "";
    const counts = `
      <div class="entity-tags mt-8">
        <span class="badge">Компонентов: ${Number(profile.components_count || 0)}</span>
        <span class="badge">Назначений: ${Number(profile.assignments_count || 0)}</span>
        ${profileStatusBadge(profile)}
      </div>
    `;
    return `
      <div class="entity-row">
        <div>
          <div class="entity-row__title">${esc(profile.title || `Профиль #${profile.id}`)}</div>
          ${desc}
          ${counts}
          <div class="muted mt-8">Обновлён: ${esc(fmtDate(profile.updated_at || profile.created_at))}</div>
        </div>
        <div class="entity-row__side">
          <a class="btn" href="/owner-pay-profile.html?venue_id=${encodeURIComponent(getActiveVenueId())}&profile_id=${encodeURIComponent(profile.id)}">Открыть</a>
          ${state.access.canManage ? `<button class="btn small" data-edit-profile="${profile.id}">Изменить</button>` : ""}
          ${state.access.canManage ? `<button class="btn small" data-toggle-profile="${profile.id}">${profile.is_active ? "В архив" : "Вернуть"}</button>` : ""}
          ${state.access.canManage ? `<button class="btn danger small" data-delete-profile="${profile.id}">Удалить</button>` : ""}
        </div>
      </div>
    `;
  }).join("");

  list.querySelectorAll("[data-edit-profile]").forEach((btn) => {
    btn.onclick = () => {
      const profile = state.profiles.find((item) => String(item.id) === String(btn.dataset.editProfile));
      if (profile) openProfileModal(profile);
    };
  });

  list.querySelectorAll("[data-toggle-profile]").forEach((btn) => {
    btn.onclick = async () => {
      const profile = state.profiles.find((item) => String(item.id) === String(btn.dataset.toggleProfile));
      if (!profile) return;
      try {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profiles/${encodeURIComponent(profile.id)}`, {
          method: "PATCH",
          body: { is_active: !profile.is_active },
        });
        toast(profile.is_active ? "Профиль отправлен в архив" : "Профиль восстановлен", "ok");
        await loadProfiles();
      } catch (e) {
        toast(e?.data?.detail || e.message || "Не удалось обновить профиль", "err");
      }
    };
  });

  list.querySelectorAll("[data-delete-profile]").forEach((btn) => {
    btn.onclick = async () => {
      const profile = state.profiles.find((item) => String(item.id) === String(btn.dataset.deleteProfile));
      if (!profile) return;
      const ok = await confirmModal({
        title: "Удалить профиль?",
        text: `Профиль «${profile.title}» будет удалён без возможности восстановления.`,
        confirmText: "Удалить",
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profiles/${encodeURIComponent(profile.id)}`, { method: "DELETE" });
        toast("Профиль удалён", "ok");
        await loadProfiles();
      } catch (e) {
        toast(e?.data?.detail || e.message || "Не удалось удалить профиль", "err");
      }
    };
  });
}

function profileFormHtml(profile = null) {
  return `
    <form id="payProfileForm" class="finance-form">
      <label>
        Название
        <input name="title" type="text" maxlength="120" required value="${esc(profile?.title || "")}" />
      </label>
      <label>
        Описание
        <textarea name="description" rows="4" maxlength="500" placeholder="Например: бармены, фикс+почасовая ставка">${esc(profile?.description || "")}</textarea>
      </label>
      <label class="row" style="gap:8px; align-items:center;">
        <input name="is_active" type="checkbox" style="width:auto;" ${profile?.is_active === false ? "" : "checked"} />
        <span>Профиль активен</span>
      </label>
      <div class="row" style="gap:8px; justify-content:flex-end; flex-wrap:wrap; margin-top:4px;">
        <button type="button" class="btn" data-close-inline>Отмена</button>
        <button type="submit" class="btn primary">${profile ? "Сохранить" : "Создать"}</button>
      </div>
    </form>
  `;
}

function openProfileModal(profile = null) {
  if (!state.access.canManage) return;
  openHtmlModal(profile ? "Изменить профиль" : "Новый профиль", profileFormHtml(profile));
  const form = document.getElementById("payProfileForm");
  const closeBtn = document.querySelector("[data-close-inline]");
  if (closeBtn) closeBtn.onclick = () => closeModal();
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {
      title: String(fd.get("title") || "").trim(),
      description: String(fd.get("description") || "").trim() || null,
      is_active: fd.get("is_active") === "on",
    };
    if (!body.title) {
      toast("Введите название профиля", "warn");
      return;
    }
    try {
      if (profile?.id) {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profiles/${encodeURIComponent(profile.id)}`, { method: "PATCH", body });
        toast("Профиль обновлён", "ok");
      } else {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profiles`, { method: "POST", body });
        toast("Профиль создан", "ok");
      }
      closeModal();
      await loadProfiles();
    } catch (err) {
      toast(err?.data?.detail || err.message || "Не удалось сохранить профиль", "err");
    }
  };
}

async function loadProfiles() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  const list = document.getElementById("profilesList");
  if (list) list.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
  try {
    const rows = await api(`/venues/${encodeURIComponent(venueId)}/pay-profiles?include_inactive=${state.includeInactive ? "true" : "false"}`);
    state.profiles = Array.isArray(rows) ? rows : [];
    renderProfiles();
  } catch (e) {
    state.profiles = [];
    showEmpty(e?.data?.detail || e.message || "Не удалось загрузить профили");
    const hint = document.getElementById("profilesHint");
    if (hint) hint.textContent = "Ошибка";
    const stateEl = document.getElementById("profilesState");
    if (stateEl) stateEl.textContent = "Ошибка";
    toast("Не удалось загрузить профили зарплаты", "err");
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("venue");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);

  await mountNav({ activeTab: "venue" });
  await loadAccess();
  syncActions();

  try {
    const venues = await getMyVenues();
    const venue = venues.find((item) => String(item.id) === String(getActiveVenueId()));
    if (venue) {
      const subtitle = document.getElementById("subtitle");
      if (subtitle) subtitle.textContent = venue.name || "";
    }
  } catch {}

  const showInactive = document.getElementById("showInactiveProfiles");
  if (showInactive) {
    showInactive.checked = state.includeInactive;
    showInactive.onchange = async () => {
      state.includeInactive = !!showInactive.checked;
      await loadProfiles();
    };
  }

  const refreshBtn = document.getElementById("refreshProfilesBtn");
  if (refreshBtn) refreshBtn.onclick = () => loadProfiles();

  const addBtn = document.getElementById("addProfileBtn");
  if (addBtn) addBtn.onclick = () => openProfileModal(null);

  await loadProfiles();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

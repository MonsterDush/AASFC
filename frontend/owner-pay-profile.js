import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
  getVenueMembers,
  getDepartments,
  getKpiMetrics,
  getPayProfile,
  updatePayProfile,
  createPayProfileAssignment,
  updatePayProfileAssignment,
  deletePayProfileAssignment,
  createPayComponent,
  updatePayComponent,
  deletePayComponent,
  applyDemoReadonlyCaps,
} from "/app.js?v=20260813-i18n1";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";
import { createPayComponentSupport } from "/owner-pay-profile/component-support.js?v=20260729-payroll1";
import { createPayComponentFormRenderer } from "/owner-pay-profile/component-form.js?v=20260729-payroll1";
import { createPayComponentController } from "/owner-pay-profile/component-controller.js?v=20260729-payroll1";
import { createPayComponentList } from "/owner-pay-profile/component-list.js?v=20260729-payroll1";
import { createPayAssignmentController } from "/owner-pay-profile/assignment-controller.js?v=20260723-functional1";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setVisible(element, visible) {
  element?.classList.toggle("hidden", !visible);
}

function parseParams() {
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || "";
  const profileId = params.get("profile_id") || "";
  if (venueId) setActiveVenueId(venueId);
  return { venueId, profileId };
}

function memberName(member) {
  if (!member) return "—";
  return member.display_name
    || member.short_name
    || member.full_name
    || (member.tg_username ? `@${member.tg_username}` : "")
    || member.phone
    || (member.user_id ? `user #${member.user_id}` : "—");
}

let state = {
  venueId: "",
  profileId: "",
  me: null,
  perms: null,
  can: { view: false, manage: false },
  profile: null,
  members: [],
  departments: [],
  kpiMetrics: [],
};

function renderShell() {
  root.innerHTML = `
    <div class="topbar pay-profile-topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Профиль зарплаты</b>
          <div class="muted" id="subtitle">компоненты и назначения</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <main class="pay-profile-content">
    <section class="card pay-profile-hero">
      <div class="pay-profile-detail-head">
        <div class="section-head">
          <div class="section-title">
            <b id="profileTitle">—</b>
            <div class="muted mt-6" id="profileDescription">—</div>
          </div>
          <div class="section-actions">
            <button class="btn" id="btnEditProfile">Редактировать</button>
          </div>
        </div>
        <div class="muted pay-profile-meta" id="profileMeta">—</div>
      </div>

      <div class="pay-profile-detail-grid">
        <section class="pay-profile-section">
          <div class="section-head">
            <div class="section-title"><b>Компоненты</b></div>
            <div class="section-actions"><button class="btn primary" id="btnAddComponent">+ Добавить</button></div>
          </div>
          <div class="muted pay-profile-section__intro">Доступны: оклад, почасовая ставка, фикс за смену, проценты по выручке и KPI-бонусы по закрытым отчётам.</div>
          <div id="componentsList" class="pay-profile-section-list"><div class="pay-profile-loading"><div class="skeleton"></div></div></div>
        </section>

        <section class="pay-profile-section">
          <div class="section-head">
            <div class="section-title"><b>Назначения</b></div>
            <div class="section-actions"><button class="btn primary" id="btnAddAssignment">+ Назначить</button></div>
          </div>
          <div class="muted pay-profile-section__intro">Назначения определяют, какой профиль действует у сотрудника в выбранный период.</div>
          <div id="assignmentsList" class="pay-profile-section-list"><div class="pay-profile-loading"><div class="skeleton"></div></div></div>
        </section>
      </div>

      <div class="pay-profile-links">
        <button class="btn subtle inline" id="backProfiles" type="button" data-nav-button>← К списку профилей</button>
        <button class="btn subtle inline" id="openPayroll" type="button" data-nav-button>Открыть начисления →</button>
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
      <div class="modal__panel modal__panel--wide">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="editTitle">Редактирование</b>
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

function closeEditModal() {
  document.getElementById("editModal")?.classList.remove("open");
}

function openEditModal({ title, hint, bodyHtml }) {
  const modal = document.getElementById("editModal");
  const titleEl = document.getElementById("editTitle");
  const hintEl = document.getElementById("editHint");
  const bodyEl = document.getElementById("editBody");
  if (titleEl) titleEl.textContent = title || "Редактирование";
  if (hintEl) hintEl.textContent = hint || "";
  if (bodyEl) bodyEl.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function wireEditModalClose() {
  const m = document.getElementById("editModal");
  if (!m) return;
  m.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", closeEditModal));
}

function renderHeader() {
  const p = state.profile;
  document.getElementById("title").textContent = p?.title || "Профиль зарплаты";
  document.getElementById("subtitle").textContent = p?.description || "компоненты и назначения";
  document.getElementById("profileTitle").textContent = p?.title || "—";
  document.getElementById("profileDescription").textContent = p?.description || "Без описания";
  document.getElementById("profileMeta").textContent = `${p?.is_active ? "Активный профиль" : "Профиль выключен"} · Компонентов: ${Number(p?.components?.length || 0)} · Назначений: ${Number(p?.assignments?.length || 0)}`;
  document.getElementById("backProfiles").href = `/owner-pay-profiles.html?venue_id=${encodeURIComponent(state.venueId)}`;
  document.getElementById("openPayroll").href = `/owner-payroll.html?venue_id=${encodeURIComponent(state.venueId)}`;
  setVisible(document.getElementById("btnEditProfile"), state.can.manage);
  setVisible(document.getElementById("btnAddComponent"), state.can.manage);
  setVisible(document.getElementById("btnAddAssignment"), state.can.manage);
}


const componentSupport = createPayComponentSupport({ state, esc });
const { componentForm } = createPayComponentFormRenderer({ state, esc, support: componentSupport });
const { openComponentEditor } = createPayComponentController({
  state,
  esc,
  support: componentSupport,
  componentForm,
  openEditModal,
  closeEditModal,
  toast,
  createPayComponent,
  updatePayComponent,
  load,
});
const { renderComponents } = createPayComponentList({
  state,
  esc,
  support: componentSupport,
  openComponentEditor,
  updatePayComponent,
  deletePayComponent,
  toast,
  confirmModal,
  load,
});
const { renderAssignments, openAssignmentEditor } = createPayAssignmentController({
  state,
  esc,
  memberName,
  openEditModal,
  closeEditModal,
  toast,
  confirmModal,
  createPayProfileAssignment,
  updatePayProfileAssignment,
  deletePayProfileAssignment,
  load,
});


function openProfileEditor() {
  if (!state.can.manage || !state.profile) return;
  openEditModal({
    title: "Редактировать профиль",
    hint: "Изменения применятся ко всем последующим расчётам",
    bodyHtml: `
      <div class="finance-form mt-8">
        <label>
          <span>Название</span>
          <input id="f_title" value="${esc(state.profile.title || "")}" />
        </label>
        <label>
          <span>Описание</span>
          <textarea id="f_description" rows="4">${esc(state.profile.description || "")}</textarea>
        </label>
        <label class="chk">
          <input type="checkbox" id="f_active" ${state.profile.is_active ? "checked" : ""} />
          <span>Профиль активен</span>
        </label>
      </div>
      <div class="pay-profile-modal-actions">
        <button class="btn" id="btnCancel" type="button">Отмена</button>
        <button class="btn primary" id="btnSave" type="button">Сохранить</button>
      </div>
    `,
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
    try {
      await updatePayProfile(state.venueId, state.profileId, {
        title,
        description: description || null,
        is_active: isActive,
      });
      toast("Профиль обновлён", "ok");
      closeEditModal();
      await load();
    } catch (e) {
      toast("Ошибка: " + (e?.data?.detail || e?.message || "не удалось сохранить"), "err");
    }
  });
}

async function load() {
  const componentsList = document.getElementById("componentsList");
  const assignmentsList = document.getElementById("assignmentsList");
  if (componentsList) componentsList.innerHTML = `<div class="pay-profile-loading"><div class="skeleton"></div></div>`;
  if (assignmentsList) assignmentsList.innerHTML = `<div class="pay-profile-loading"><div class="skeleton"></div></div>`;

  try {
    state.profile = await getPayProfile(state.venueId, state.profileId);
  } catch (e) {
    root.innerHTML = `<div class="pay-profile-state pay-profile-state--error"><b>Не удалось загрузить профиль</b><span>${esc(e?.data?.detail || e?.message || "Проверь подключение и повтори попытку.")}</span></div>`;
    return;
  }

  renderHeader();
  renderComponents();
  renderAssignments();
}

async function boot() {
  applyTelegramTheme();
  renderShell();
  wireEditModalClose();
  await ensureLogin({ silent: true });

  const params = parseParams();
  state.venueId = params.venueId;
  state.profileId = params.profileId;

  if (!state.venueId || !state.profileId) {
    root.innerHTML = `<div class="pay-profile-state"><b>Профиль не выбран</b><span>Открой профиль оплаты из списка нужного заведения.</span></div>`;
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

  if (!state.can.view) {
    const content = root.querySelector(".pay-profile-content");
    if (content) {
      content.innerHTML = `<div class="pay-profile-state pay-profile-state--denied"><b>Нет доступа</b><span>Для просмотра профиля оплаты нужны соответствующие права.</span></div>`;
    }
    return;
  }

  try {
    const membersResp = await getVenueMembers(state.venueId);
    state.members = Array.isArray(membersResp?.members) ? membersResp.members : [];
  } catch {
    state.members = [];
  }

  try {
    const depsResp = await getDepartments(state.venueId);
    state.departments = Array.isArray(depsResp) ? depsResp : [];
  } catch {
    state.departments = [];
  }

  try {
    const kpiResp = await getKpiMetrics(state.venueId, { includeArchived: false });
    state.kpiMetrics = Array.isArray(kpiResp) ? kpiResp : [];
  } catch {
    state.kpiMetrics = [];
  }

  document.getElementById("btnEditProfile")?.addEventListener("click", openProfileEditor);
  document.getElementById("btnAddComponent")?.addEventListener("click", () => openComponentEditor({ mode: "create" }));
  document.getElementById("btnAddAssignment")?.addEventListener("click", () => openAssignmentEditor({ mode: "create" }));

  await load();
}

document.addEventListener("DOMContentLoaded", boot);

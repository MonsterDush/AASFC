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
  profile: null,
  members: [],
  access: {
    canView: false,
    canManage: false,
    canViewPayroll: false,
  },
};

const COMPONENT_OPTIONS = [
  { value: "SALARY_FIXED_MONTH", label: "Оклад за месяц" },
  { value: "SALARY_HOURLY", label: "Почасовая ставка" },
  { value: "SALARY_PER_SHIFT", label: "Фикс за смену" },
];

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

function fmtMinor(minor) {
  const rub = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return rub.toFixed(2) + " ₽";
  }
}

function parseMoneyToMinor(value) {
  const normalized = String(value || "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!normalized) return 0;
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) throw new Error("Введите сумму в формате 1234.56");
  return Math.round(Number(normalized) * 100);
}

function componentTypeLabel(value) {
  const item = COMPONENT_OPTIONS.find((entry) => entry.value === String(value || "").toUpperCase());
  return item?.label || String(value || "—");
}

function componentValueLabel(component) {
  const type = String(component?.component_type || "").toUpperCase();
  if (type === "SALARY_HOURLY") return `${fmtMinor(component?.rate_minor)} / час`;
  return fmtMinor(component?.amount_minor);
}

function memberLabel(member) {
  if (!member) return "—";
  return member.short_name || member.full_name || (member.tg_username ? `@${member.tg_username}` : `user #${member.user_id}`);
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

function showEmpty(targetId, message) {
  const el = document.getElementById(targetId);
  if (el) el.innerHTML = `<div class="muted">${esc(message)}</div>`;
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

function syncToolbar() {
  const editBtn = document.getElementById("editProfileBtn");
  const addComponentBtn = document.getElementById("addComponentBtn");
  const addAssignmentBtn = document.getElementById("addAssignmentBtn");
  const payrollBtn = document.getElementById("openPayrollPageBtn");
  const backBtn = document.getElementById("backToProfilesBtn");
  const venueId = getActiveVenueId();
  const profileId = state.profile?.id || new URLSearchParams(location.search).get("profile_id") || "";

  if (editBtn) editBtn.style.display = state.access.canManage ? "" : "none";
  if (addComponentBtn) addComponentBtn.style.display = state.access.canManage ? "" : "none";
  if (addAssignmentBtn) addAssignmentBtn.style.display = state.access.canManage ? "" : "none";
  if (payrollBtn) {
    payrollBtn.style.display = state.access.canViewPayroll ? "" : "none";
    payrollBtn.onclick = () => { location.href = `/owner-payroll.html?venue_id=${encodeURIComponent(venueId)}`; };
  }
  if (backBtn) backBtn.href = `/owner-pay-profiles.html?venue_id=${encodeURIComponent(venueId)}`;
  if (editBtn) editBtn.onclick = () => openProfileEditModal(state.profile);
  if (addComponentBtn) addComponentBtn.onclick = () => openComponentModal(null);
  if (addAssignmentBtn) addAssignmentBtn.onclick = () => openAssignmentModal(null);
}

function renderHeader() {
  const profile = state.profile;
  const title = document.getElementById("title");
  const headline = document.getElementById("profileHeadline");
  const meta = document.getElementById("profileMeta");
  if (!profile) return;
  const value = profile.title || `Профиль #${profile.id}`;
  if (title) title.textContent = value;
  if (headline) headline.textContent = value;
  if (meta) {
    const badges = [profile.is_active ? "активный" : "неактивный", `компонентов: ${profile.components?.length || 0}`, `назначений: ${profile.assignments?.length || 0}`];
    if (profile.description) badges.unshift(profile.description);
    meta.textContent = badges.join(" · ");
  }
}

function renderComponents() {
  const list = document.getElementById("componentsList");
  const hint = document.getElementById("componentsHint");
  if (!list) return;
  const items = Array.isArray(state.profile?.components) ? state.profile.components : [];
  if (hint) hint.textContent = `${items.length} шт.`;

  if (!items.length) {
    showEmpty("componentsList", "Компоненты ещё не добавлены.");
    return;
  }

  list.innerHTML = items.map((component) => `
    <div class="entity-row">
      <div>
        <div class="entity-row__title">${esc(component.title || componentTypeLabel(component.component_type))}</div>
        <div class="entity-tags mt-8">
          <span class="badge">${esc(componentTypeLabel(component.component_type))}</span>
          <span class="badge">${esc(componentValueLabel(component))}</span>
          <span class="badge">Сортировка: ${Number(component.sort_order || 0)}</span>
          ${component.is_active ? '<span class="badge">Активный</span>' : '<span class="badge">Неактивный</span>'}
        </div>
      </div>
      <div class="entity-row__side">
        ${state.access.canManage ? `<button class="btn small" data-edit-component="${component.id}">Изменить</button>` : ""}
        ${state.access.canManage ? `<button class="btn danger small" data-delete-component="${component.id}">Удалить</button>` : ""}
      </div>
    </div>
  `).join("");

  list.querySelectorAll("[data-edit-component]").forEach((btn) => {
    btn.onclick = () => {
      const component = items.find((item) => String(item.id) === String(btn.dataset.editComponent));
      if (component) openComponentModal(component);
    };
  });

  list.querySelectorAll("[data-delete-component]").forEach((btn) => {
    btn.onclick = async () => {
      const component = items.find((item) => String(item.id) === String(btn.dataset.deleteComponent));
      if (!component) return;
      const ok = await confirmModal({
        title: "Удалить компонент?",
        text: `Компонент «${component.title}» будет удалён из профиля.`,
        confirmText: "Удалить",
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-components/${encodeURIComponent(component.id)}`, { method: "DELETE" });
        toast("Компонент удалён", "ok");
        await loadProfile();
      } catch (e) {
        toast(e?.data?.detail || e.message || "Не удалось удалить компонент", "err");
      }
    };
  });
}

function renderAssignments() {
  const list = document.getElementById("assignmentsList");
  const hint = document.getElementById("assignmentsHint");
  if (!list) return;
  const items = Array.isArray(state.profile?.assignments) ? state.profile.assignments : [];
  if (hint) hint.textContent = `${items.length} шт.`;

  if (!items.length) {
    showEmpty("assignmentsList", "Назначений пока нет.");
    return;
  }

  list.innerHTML = items.map((assignment) => `
    <div class="entity-row">
      <div>
        <div class="entity-row__title">${esc(memberLabel(assignment.member))}</div>
        <div class="entity-tags mt-8">
          <span class="badge">Старт: ${esc(assignment.start_date || "без даты")}</span>
          <span class="badge">Конец: ${esc(assignment.end_date || "бессрочно")}</span>
          ${assignment.is_active ? '<span class="badge">Активно</span>' : '<span class="badge">Неактивно</span>'}
        </div>
      </div>
      <div class="entity-row__side">
        ${state.access.canManage ? `<button class="btn small" data-edit-assignment="${assignment.id}">Изменить</button>` : ""}
        ${state.access.canManage ? `<button class="btn danger small" data-delete-assignment="${assignment.id}">Удалить</button>` : ""}
      </div>
    </div>
  `).join("");

  list.querySelectorAll("[data-edit-assignment]").forEach((btn) => {
    btn.onclick = () => {
      const assignment = items.find((item) => String(item.id) === String(btn.dataset.editAssignment));
      if (assignment) openAssignmentModal(assignment);
    };
  });

  list.querySelectorAll("[data-delete-assignment]").forEach((btn) => {
    btn.onclick = async () => {
      const assignment = items.find((item) => String(item.id) === String(btn.dataset.deleteAssignment));
      if (!assignment) return;
      const ok = await confirmModal({
        title: "Удалить назначение?",
        text: `Сотрудник «${memberLabel(assignment.member)}» будет отвязан от профиля.`,
        confirmText: "Удалить",
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profile-assignments/${encodeURIComponent(assignment.id)}`, { method: "DELETE" });
        toast("Назначение удалено", "ok");
        await loadProfile();
      } catch (e) {
        toast(e?.data?.detail || e.message || "Не удалось удалить назначение", "err");
      }
    };
  });
}

function profileEditForm(profile) {
  return `
    <form id="profileEditForm" class="finance-form">
      <label>
        Название
        <input name="title" type="text" maxlength="120" required value="${esc(profile?.title || "")}" />
      </label>
      <label>
        Описание
        <textarea name="description" rows="4" maxlength="500">${esc(profile?.description || "")}</textarea>
      </label>
      <label class="row" style="gap:8px; align-items:center;">
        <input name="is_active" type="checkbox" style="width:auto;" ${profile?.is_active === false ? "" : "checked"} />
        <span>Профиль активен</span>
      </label>
      <div class="row" style="gap:8px; justify-content:flex-end; flex-wrap:wrap; margin-top:4px;">
        <button type="button" class="btn" data-close-inline>Отмена</button>
        <button type="submit" class="btn primary">Сохранить</button>
      </div>
    </form>
  `;
}

function openProfileEditModal(profile) {
  if (!state.access.canManage || !profile) return;
  openHtmlModal("Изменить профиль", profileEditForm(profile));
  const form = document.getElementById("profileEditForm");
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
    if (!body.title) return toast("Введите название профиля", "warn");
    try {
      await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profiles/${encodeURIComponent(profile.id)}`, { method: "PATCH", body });
      toast("Профиль обновлён", "ok");
      closeModal();
      await loadProfile();
    } catch (e2) {
      toast(e2?.data?.detail || e2.message || "Не удалось сохранить профиль", "err");
    }
  };
}

function componentFormHtml(component = null) {
  const selectedType = String(component?.component_type || "SALARY_FIXED_MONTH").toUpperCase();
  const moneyValue = selectedType === "SALARY_HOURLY" ? Number(component?.rate_minor || 0) / 100 : Number(component?.amount_minor || 0) / 100;
  return `
    <form id="componentForm" class="finance-form">
      <label>
        Название
        <input name="title" type="text" maxlength="120" required value="${esc(component?.title || "")}" />
      </label>
      <label>
        Тип
        <select name="component_type" id="componentTypeSelect">
          ${COMPONENT_OPTIONS.map((item) => `<option value="${item.value}" ${item.value === selectedType ? "selected" : ""}>${esc(item.label)}</option>`).join("")}
        </select>
      </label>
      <label>
        <span id="componentAmountLabel">${selectedType === "SALARY_HOURLY" ? "Ставка за час" : "Сумма"}</span>
        <input name="money_value" id="componentMoneyInput" type="text" inputmode="decimal" placeholder="0.00" value="${moneyValue ? esc(moneyValue.toFixed(2)) : ""}" />
      </label>
      <label>
        Порядок
        <input name="sort_order" type="number" min="0" step="1" value="${Number(component?.sort_order || 0)}" />
      </label>
      <label class="row" style="gap:8px; align-items:center;">
        <input name="is_active" type="checkbox" style="width:auto;" ${component?.is_active === false ? "" : "checked"} />
        <span>Компонент активен</span>
      </label>
      <div class="row" style="gap:8px; justify-content:flex-end; flex-wrap:wrap; margin-top:4px;">
        <button type="button" class="btn" data-close-inline>Отмена</button>
        <button type="submit" class="btn primary">${component ? "Сохранить" : "Добавить"}</button>
      </div>
    </form>
  `;
}

function openComponentModal(component = null) {
  if (!state.access.canManage) return;
  openHtmlModal(component ? "Изменить компонент" : "Новый компонент", componentFormHtml(component));
  const form = document.getElementById("componentForm");
  const closeBtn = document.querySelector("[data-close-inline]");
  const typeSelect = document.getElementById("componentTypeSelect");
  const amountLabel = document.getElementById("componentAmountLabel");
  if (closeBtn) closeBtn.onclick = () => closeModal();
  const syncType = () => {
    const type = String(typeSelect?.value || "SALARY_FIXED_MONTH").toUpperCase();
    if (amountLabel) amountLabel.textContent = type === "SALARY_HOURLY" ? "Ставка за час" : "Сумма";
  };
  if (typeSelect) typeSelect.onchange = syncType;
  syncType();
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const componentType = String(fd.get("component_type") || "SALARY_FIXED_MONTH").toUpperCase();
    let moneyMinor = 0;
    try {
      moneyMinor = parseMoneyToMinor(fd.get("money_value"));
    } catch (err) {
      toast(err.message || "Проверьте сумму", "warn");
      return;
    }
    const body = {
      component_type: componentType,
      title: String(fd.get("title") || "").trim(),
      sort_order: Number(fd.get("sort_order") || 0),
      is_active: fd.get("is_active") === "on",
      amount_minor: componentType === "SALARY_HOURLY" ? null : moneyMinor,
      rate_minor: componentType === "SALARY_HOURLY" ? moneyMinor : null,
      percent_bps: null,
      department_id: null,
      kpi_metric_id: null,
      threshold_value: null,
      steps_json: null,
    };
    if (!body.title) return toast("Введите название компонента", "warn");
    try {
      if (component?.id) {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-components/${encodeURIComponent(component.id)}`, { method: "PATCH", body });
        toast("Компонент обновлён", "ok");
      } else {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profiles/${encodeURIComponent(state.profile.id)}/components`, { method: "POST", body });
        toast("Компонент добавлен", "ok");
      }
      closeModal();
      await loadProfile();
    } catch (e2) {
      toast(e2?.data?.detail || e2.message || "Не удалось сохранить компонент", "err");
    }
  };
}

function assignmentFormHtml(assignment = null) {
  const options = state.members.map((member) => {
    const value = String(member.user_id);
    const selected = String(assignment?.member_user_id || "") === value ? "selected" : "";
    return `<option value="${esc(value)}" ${selected}>${esc(memberLabel(member))}</option>`;
  }).join("");
  return `
    <form id="assignmentForm" class="finance-form">
      <label>
        Сотрудник
        <select name="member_user_id" ${assignment ? "disabled" : ""}>
          <option value="">Выберите сотрудника</option>
          ${options}
        </select>
      </label>
      <label>
        Дата начала
        <input name="start_date" type="date" value="${esc(assignment?.start_date || "")}" />
      </label>
      <label>
        Дата окончания
        <input name="end_date" type="date" value="${esc(assignment?.end_date || "")}" />
      </label>
      <label class="row" style="gap:8px; align-items:center;">
        <input name="is_active" type="checkbox" style="width:auto;" ${assignment?.is_active === false ? "" : "checked"} />
        <span>Назначение активно</span>
      </label>
      <div class="row" style="gap:8px; justify-content:flex-end; flex-wrap:wrap; margin-top:4px;">
        <button type="button" class="btn" data-close-inline>Отмена</button>
        <button type="submit" class="btn primary">${assignment ? "Сохранить" : "Назначить"}</button>
      </div>
    </form>
  `;
}

function openAssignmentModal(assignment = null) {
  if (!state.access.canManage) return;
  openHtmlModal(assignment ? "Изменить назначение" : "Назначить профиль", assignmentFormHtml(assignment));
  const form = document.getElementById("assignmentForm");
  const closeBtn = document.querySelector("[data-close-inline]");
  if (closeBtn) closeBtn.onclick = () => closeModal();
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {
      member_user_id: Number(assignment?.member_user_id || fd.get("member_user_id") || 0),
      start_date: String(fd.get("start_date") || "").trim() || null,
      end_date: String(fd.get("end_date") || "").trim() || null,
      is_active: fd.get("is_active") === "on",
    };
    if (!body.member_user_id) return toast("Выберите сотрудника", "warn");
    try {
      if (assignment?.id) {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profile-assignments/${encodeURIComponent(assignment.id)}`, { method: "PATCH", body });
        toast("Назначение обновлено", "ok");
      } else {
        await api(`/venues/${encodeURIComponent(getActiveVenueId())}/pay-profiles/${encodeURIComponent(state.profile.id)}/assignments`, { method: "POST", body });
        toast("Профиль назначен сотруднику", "ok");
      }
      closeModal();
      await loadProfile();
    } catch (e2) {
      toast(e2?.data?.detail || e2.message || "Не удалось сохранить назначение", "err");
    }
  };
}

async function loadMembers() {
  try {
    const out = await api(`/venues/${encodeURIComponent(getActiveVenueId())}/members`);
    state.members = Array.isArray(out?.members) ? out.members : [];
  } catch {
    state.members = [];
  }
}

async function loadProfile() {
  const venueId = getActiveVenueId();
  const profileId = new URLSearchParams(location.search).get("profile_id") || "";
  if (!venueId || !profileId) return;
  showEmpty("componentsList", "Загрузка...");
  showEmpty("assignmentsList", "Загрузка...");
  try {
    const profile = await api(`/venues/${encodeURIComponent(venueId)}/pay-profiles/${encodeURIComponent(profileId)}`);
    state.profile = profile;
    renderHeader();
    syncToolbar();
    renderComponents();
    renderAssignments();
  } catch (e) {
    state.profile = null;
    showEmpty("componentsList", e?.data?.detail || e.message || "Не удалось загрузить профиль");
    showEmpty("assignmentsList", "—");
    toast("Не удалось загрузить профиль зарплаты", "err");
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
  await loadMembers();

  try {
    const venues = await getMyVenues();
    const venue = venues.find((item) => String(item.id) === String(getActiveVenueId()));
    if (venue) {
      const subtitle = document.getElementById("subtitle");
      if (subtitle) subtitle.textContent = venue.name || "";
    }
  } catch {}

  syncToolbar();

  if (!state.access.canView) {
    showEmpty("componentsList", "Нет прав на просмотр профиля зарплаты.");
    showEmpty("assignmentsList", "Нет доступа.");
    return;
  }

  await loadProfile();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

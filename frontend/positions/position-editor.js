
export function createPositionEditor({
  state,
  auth,
  esc,
  domain,
  permissions,
  openPosModal,
  closePosModal,
  toast,
  confirmModal,
  createVenuePosition,
  updateVenuePosition,
  deleteVenuePosition,
  load,
}) {
const { memberLabel, parsePermCodes, uniqueTitles } = domain;
const {
  buildDefaultPermissionsCatalog,
  ensurePermissionsCatalog,
  ensurePermissionTemplates,
  renderPermissionTemplateSelect,
  renderTemplateSummaryBlock,
  applyPermissionTemplateToModal,
} = permissions;

function renderPayProfileOptions(selectedId = null) {
  const current = selectedId == null || selectedId === "" ? "" : String(selectedId);
  const options = ['<option value="">— без профиля начисления —</option>'];
  for (const profile of state.payProfiles || []) {
    if (profile?.is_active === false) continue;
    const id = String(profile?.id || "");
    if (!id) continue;
    const count = Number(profile?.components_count || 0);
    const suffix = count > 0 ? ` · компонентов: ${count}` : "";
    options.push(`<option value="${esc(id)}" ${id === current ? "selected" : ""}>${esc(profile.title || `Профиль #${id}`)}${esc(suffix)}</option>`);
  }
  return options.join("");
}

function renderTitleDatalist() {
  const titles = uniqueTitles();
  return `
    <datalist id="posTitleHints">
      ${titles.map(t => `<option value="${esc(t)}"></option>`).join("")}
    </datalist>
  `;
}

function renderPositionForm({ mode, position }) {
  const p = position || {};
  const titles = uniqueTitles();

  const permsOnly = mode === "perms";
  const canEditMain = auth.canManage && !permsOnly;
  const canEditPerms = auth.canManagePerms;
  const canChangeMember = auth.canAssign && mode === "edit";

  const membersOptions = state.members
    .map((m) => `<option value="${esc(String(m.user_id))}">${esc(memberLabel(m))}</option>`)
    .join("");

  const hint = titles.length
    ? "Начни вводить — будут подсказки (например: Бармен, Официант…)"
    : "Подсказок пока нет — создай первую должность";

  const curPerms = (() => {
    const arr = Array.isArray(p.permission_codes) ? p.permission_codes : [];
    return arr.map((x) => String(x || "").trim()).filter(Boolean);
  })();

  const isChecked = (code) => curPerms.includes(code);

  const PERM_GROUPS = Array.isArray(state.permissionsCatalog) && state.permissionsCatalog.length
    ? state.permissionsCatalog
    : buildDefaultPermissionsCatalog();

  const permCardsHtml = !canEditPerms
    ? ``
    : `
      <div style="margin-top:12px; display:grid; grid-template-columns: 1fr; gap:10px">
        <div class="perm-tools">
          <button class="btn sm" type="button" id="btnPermAllOn">Включить все</button>
          <button class="btn sm" type="button" id="btnPermAllOff">Выключить все</button>
        </div>

        ${PERM_GROUPS.map((g) => {
          const rows = (g.items || []).map((it) => `
            <div class="perm-row">
              <div class="perm-text">
                <div class="perm-title">${esc(it.title)}</div>
                <div class="perm-desc">${esc(it.description || "")}</div>
              </div>
              <label class="switch">
                <input type="checkbox"
                  data-perm-code="${esc(it.code)}"
                  data-perm-group="${esc(g.key)}"
                  ${isChecked(it.code) ? "checked" : ""} />
                <span class="slider"></span>
              </label>
            </div>
          `).join("");

          return `
            <div class="card" style="padding:12px">
              <div class="perm-group-title">
                <div>
                  <b>${esc(g.title)}</b>
                  ${g.hint ? `<div class="muted" style="margin-top:4px; font-size:12px">${esc(g.hint)}</div>` : ``}
                </div>
                <div class="row" style="gap:6px; flex:0 0 auto">
                  <button class="btn sm" type="button" data-perm-set="${esc(g.key)}" data-value="1">Все</button>
                  <button class="btn sm" type="button" data-perm-set="${esc(g.key)}" data-value="0">Ничего</button>
                </div>
              </div>
              ${rows}
              ${g.extraHtml || ``}
            </div>
          `;
        }).join("")}
      </div>
    `;

  return `
    ${renderTitleDatalist()}

    <div class="grid grid2" style="margin-top:10px">
      <div>
        <div class="muted" style="margin-bottom:6px">Название должности</div>
        <input id="f_title" placeholder="Например: Бармен" list="posTitleHints" value="${esc(p.title || "")}" ${canEditMain ? "" : "disabled"} />
        <div class="muted" style="margin-top:6px; font-size:12px">${esc(hint)}</div>
      </div>

      <div>
        <div class="muted" style="margin-bottom:6px">Сотрудник</div>
        <select id="f_member" ${((mode === "edit") && !canChangeMember) || !auth.canManage ? "disabled" : ""}>${membersOptions}</select>
      </div>

      <div>
        <div class="muted" style="margin-bottom:6px">Профиль зарплаты</div>
        <select id="f_pay_profile" ${canEditMain ? "" : "disabled"}>${renderPayProfileOptions(p.pay_profile_id ?? "")}</select>
        <div class="muted" style="margin-top:6px; font-size:12px">Можно оставить без профиля, а затем назначить его позже.</div>
      </div>

      <div>
        <div class="muted" style="margin-bottom:6px">Начисление</div>
        <div class="itemcard" style="padding:10px 12px; min-height:44px; display:flex; align-items:center">
          <span class="muted" id="f_pay_profile_hint">${esc(p.pay_profile_title || "Без назначенного профиля")}</span>
        </div>
      </div>

      <div>
        <div class="muted" style="margin-bottom:6px">Шаблон прав</div>
        <select id="f_perm_template" ${canEditPerms ? "" : "disabled"}>${renderPermissionTemplateSelect(p.template_id || "")}</select>
        <div class="row" style="gap:8px; margin-top:8px; flex-wrap:wrap">
          ${canEditPerms ? '<button class="btn sm" type="button" id="btnApplyTemplate">Применить шаблон</button>' : ''}
          ${(auth.sysRole === "SUPER_ADMIN") ? '<a class="btn sm subtle inline" href="/admin-position-templates.html">Управлять шаблонами</a>' : ''}
        </div>
      </div>
    </div>

    <div id="f_perm_template_summary_wrap" class="itemcard" style="margin-top:12px; padding:10px 12px">${renderTemplateSummaryBlock(p.template_id || "")}</div>

    ${permCardsHtml}

    <div class="row" style="gap:8px; margin-top:12px; flex-wrap:wrap">
      ${((mode === "create") ? auth.canManage : (auth.canManage || auth.canManagePerms)) ? `<button class="btn primary" id="btnSavePos">Сохранить</button>` : ``}
      <button class="btn" id="btnCancelPos">Отмена</button>
      ${
        (mode === "edit" && auth.canManage)
          ? `<button class="btn danger" id="btnDeletePos" style="margin-left:auto">Архивировать</button>`
          : `<span class="muted" style="margin-left:auto">Можно назначать несколько людей на одну должность</span>`
      }
    </div>
  `;
}


function collectPayload(base = {}) {
  const titleEl = document.getElementById("f_title");
  const memberEl = document.getElementById("f_member");
  const payProfileEl = document.getElementById("f_pay_profile");

  const title = (titleEl && !titleEl.disabled) ? (titleEl.value || "").trim() : String(base.title || "").trim();
  const member_user_id = (memberEl && !memberEl.disabled) ? Number(memberEl.value) : Number(base.member_user_id);
  const pay_profile_id = (payProfileEl && !payProfileEl.disabled) ? (payProfileEl.value ? Number(payProfileEl.value) : null) : (base.pay_profile_id ? Number(base.pay_profile_id) : null);

  if (!title) throw new Error("Укажите название должности");
  if (!Number.isFinite(member_user_id) || member_user_id <= 0) throw new Error("Выберите сотрудника");
  if (pay_profile_id !== null && (!Number.isFinite(pay_profile_id) || pay_profile_id <= 0)) throw new Error("Выберите корректный профиль зарплаты");

  // New permissions list (permission codes)
  const modal = document.getElementById("posModal");
  const hasPermInputs = !!(modal && modal.querySelector('input[data-perm-code]'));

  const permCodes = (() => {
    if (hasPermInputs) {
      return Array.from(modal.querySelectorAll('input[data-perm-code]:checked'))
        .map((x) => String(x.getAttribute("data-perm-code") || "").trim())
        .filter(Boolean);
    }
    // no perm UI in this modal -> keep existing codes from base (do NOT clear by accident)
    if (base && Object.prototype.hasOwnProperty.call(base, "permission_codes")) return parsePermCodes(base.permission_codes);
    return [];
  })();
  return {
    title,
    member_user_id,
    rate: 0,
    percent: 0,
    pay_profile_id,
    // keep active by default for create; on update backend accepts bool|None
    is_active: (base.is_active === false) ? false : true,
    // permission codes (source of truth)
    _perm_codes: permCodes,
  };
}


function setupPermUX() {
  const modal = document.getElementById("posModal");
  if (!modal) return;

  const boxes = (group) => {
    const sel = group ? `input[data-perm-code][data-perm-group="${group}"]` : "input[data-perm-code]";
    return Array.from(modal.querySelectorAll(sel));
  };
  const setMany = (arr, val) => {
    arr.forEach((b) => (b.checked = !!val));
  };

  function ensure(code, on) {
    const el = modal.querySelector(`input[data-perm-code="${code}"]`);
    if (el && on) el.checked = true;
    if (el && !on) el.checked = false;
  }

  function isOn(code) {
    const el = modal.querySelector(`input[data-perm-code="${code}"]`);
    return !!el?.checked;
  }

  function syncDeps() {
    // manage -> view patterns
    if (isOn("SHIFTS_MANAGE")) ensure("SHIFTS_VIEW", true);
    if (isOn("ADJUSTMENTS_MANAGE") || isOn("DISPUTES_RESOLVE")) ensure("ADJUSTMENTS_VIEW", true);
    if (isOn("STAFF_MANAGE")) ensure("STAFF_VIEW", true);
    if (isOn("POSITIONS_MANAGE") || isOn("POSITION_PERMISSIONS_MANAGE") || isOn("POSITIONS_ASSIGN")) ensure("POSITIONS_VIEW", true);

    if (isOn("EXPENSE_ADD") || isOn("EXPENSE_CATEGORIES_MANAGE")) ensure("EXPENSE_VIEW", true);

    // catalogs create/edit/archive -> view
    const cat = [
      ["DEPARTMENTS_CREATE", "DEPARTMENTS_VIEW"],
      ["DEPARTMENTS_EDIT", "DEPARTMENTS_VIEW"],
      ["DEPARTMENTS_ARCHIVE", "DEPARTMENTS_VIEW"],
      ["PAYMENT_METHODS_CREATE", "PAYMENT_METHODS_VIEW"],
      ["PAYMENT_METHODS_EDIT", "PAYMENT_METHODS_VIEW"],
      ["PAYMENT_METHODS_ARCHIVE", "PAYMENT_METHODS_VIEW"],
      ["KPI_METRICS_CREATE", "KPI_METRICS_VIEW"],
      ["KPI_METRICS_EDIT", "KPI_METRICS_VIEW"],
      ["KPI_METRICS_ARCHIVE", "KPI_METRICS_VIEW"],
    ];
    cat.forEach(([a, v]) => { if (isOn(a)) ensure(v, true); });

    // shift report close/edit/reopen -> view
    if (isOn("SHIFT_REPORT_CLOSE") || isOn("SHIFT_REPORT_EDIT") || isOn("SHIFT_REPORT_REOPEN")) ensure("SHIFT_REPORT_VIEW", true);
  }

  // global on/off
  document.getElementById("btnPermAllOn")?.addEventListener("click", () => {
    setMany(boxes(), true);
    syncDeps();
  });
  document.getElementById("btnPermAllOff")?.addEventListener("click", () => {
    setMany(boxes(), false);
  });

  // group on/off
  modal.querySelectorAll("[data-perm-set]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const g = btn.getAttribute("data-perm-set");
      const v = btn.getAttribute("data-value") === "1";
      setMany(boxes(g), v);
      if (v) syncDeps();
    });
  });

  // deps on any change
  modal.querySelectorAll('input[data-perm-code]').forEach((el) => {
    el?.addEventListener("change", () => syncDeps());
  });

  // initial deps
  syncDeps();
}

function wirePositionFormUx() {
  setupPermUX();

  const payProfileSelect = document.getElementById("f_pay_profile");
  const payProfileHint = document.getElementById("f_pay_profile_hint");
  const syncPayProfileHint = () => {
    if (!payProfileHint) return;
    const selected = (state.payProfiles || []).find((item) => String(item?.id || "") === String(payProfileSelect?.value || ""));
    payProfileHint.textContent = selected ? String(selected.title || "") : "Без назначенного профиля";
  };
  payProfileSelect?.addEventListener("change", syncPayProfileHint);
  syncPayProfileHint();

  const templateSelect = document.getElementById("f_perm_template");
  templateSelect?.addEventListener("change", () => {
    const wrap = document.getElementById("f_perm_template_summary_wrap");
    if (wrap) wrap.innerHTML = renderTemplateSummaryBlock(templateSelect.value);
  });
  document.getElementById("btnApplyTemplate")?.addEventListener("click", () => {
    const templateId = String(templateSelect?.value || "").trim();
    if (!templateId) return toast("Выбери шаблон прав", "warn");
    if (!applyPermissionTemplateToModal(templateId)) return toast("Шаблон не найден", "err");
    toast("Шаблон применён", "ok");
  });
  document.getElementById("btnCancelPos")?.addEventListener("click", closePosModal);
}


async function callPositionApiWithPerms({ kind, positionId, payload, permCodes }) {
  const basePayload = { ...payload };
  // do not leak helper field
  delete basePayload._perm_codes;

  const canSendPerms = Array.isArray(permCodes);

  const callCreate = (p) => createVenuePosition(state.venueId, p);
  const callUpdate = (p) => updateVenuePosition(state.venueId, positionId, p);

  const fn = kind === "create" ? callCreate : callUpdate;

  // This page is code-only: permissions are stored only as permission_codes.
  if (!canSendPerms) return fn(basePayload);

  try {
    return await fn({ ...basePayload, permission_codes: permCodes });
  } catch (e) {
    // Do not fall back to removed boolean permission flags here.
    if (e?.status === 422) {
      toast("Сервер не поддерживает permission_codes для должностей. Обнови бэкенд.", "err");
    }
    throw e;
  }
}



/* ---------- Modal actions ---------- */

async function openCreateModal({ title = "", hint = "" } = {}) {
  if (!auth.canManage) {
    toast("Нет прав на создание должностей", "err");
    return;
  }
  await Promise.all([ensurePermissionsCatalog(), ensurePermissionTemplates()]);

  openPosModal({
    title: "Создать должность",
    hint: hint || "Одна должность может быть у нескольких сотрудников (например «Бармен»).",
    bodyHtml: renderPositionForm({ mode: "create", position: title ? { title } : null }),
  });

  // дефолтный выбор сотрудника
  const sel = document.getElementById("f_member");
  if (sel && sel.options.length) sel.value = sel.options[0].value;
  wirePositionFormUx();

  document.getElementById("btnSavePos")?.addEventListener("click", async () => {
    let payload;
    try {
      payload = collectPayload({});
    } catch (e) {
      toast(e?.message || "Ошибка формы", "warn");
      return;
    }

    try {
      await callPositionApiWithPerms({ kind: "create", payload, permCodes: auth.canManagePerms ? payload._perm_codes : null });
      toast("Должность создана", "ok");
      closePosModal();
      await load();
    } catch (e) {
      toast("Ошибка сохранения: " + (e?.message || e), "err");
    }
  });
}

async function openEditModal(p, modeOverride = null) {
  const mode = modeOverride || (auth.canManage ? "edit" : (auth.canManagePerms ? "perms" : "view"));
  if (mode === "view") {
    toast("Нет прав на изменение должности", "err");
    return;
  }
  await Promise.all([ensurePermissionsCatalog(), ensurePermissionTemplates()]);

  openPosModal({
    title: "Изменить должность",
    hint: "Меняй должность/условия для выбранного сотрудника.",
    bodyHtml: renderPositionForm({ mode, position: p }),
  });

  const sel = document.getElementById("f_member");
  if (sel) sel.value = String(p.member_user_id ?? "");
  wirePositionFormUx();

  document.getElementById("btnSavePos")?.addEventListener("click", async () => {
    let payload;
    try {
      payload = collectPayload(p);
    } catch (e) {
      toast(e?.message || "Ошибка формы", "warn");
      return;
    }

    try {
      await callPositionApiWithPerms({ kind: "update", positionId: p.id, payload, permCodes: auth.canManagePerms ? payload._perm_codes : null });
      toast("Изменения сохранены", "ok");
      closePosModal();
      await load();
    } catch (e) {
      toast("Ошибка сохранения: " + (e?.message || e), "err");
    }
  });

  document.getElementById("btnDeletePos")?.addEventListener("click", async () => {
    const ok = await confirmModal({
      title: "Архивировать должность?",
      text: `Удалить должность «${p.title || ""}» для сотрудника?`,
      confirmText: "В архив",
      danger: true,
    });
    if (!ok) return;

    try {
      await deleteVenuePosition(state.venueId, p.id);
      toast("Должность архивирована", "ok");
      closePosModal();
      await load();
    } catch (e) {
      toast("Ошибка удаления: " + (e?.message || e), "err");
    }
  });
}

return {
  renderPositionForm,
  collectPayload,
  setupPermUX,
  wirePositionFormUx,
  callPositionApiWithPerms,
  openCreateModal,
  openEditModal,
};
}

import {
  applyTelegramTheme,
  ensureLogin,
  bootPage,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  api,
  setActiveVenueId,
  getMyVenuePermissions,
  getVenueMembers,
  getVenuePositions,
  createVenuePosition,
  updateVenuePosition,
  deleteVenuePosition,
  patchInviteDefaultPosition,
} from "/app.js";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function money(n) {
  if (n === null || n === undefined || n === "") return "—";
  const x = Number(String(n).replace(",", "."));
  if (!Number.isFinite(x)) return String(n);
  return x.toLocaleString("ru-RU");
}

function fioInitials(fullName) {
  const s = String(fullName || "").trim();
  if (!s) return "";
  const p = s.split(/\s+/).filter(Boolean);
  if (p.length === 1) return p[0];
  const surname = p[0];
  const initials = p.slice(1).map(x => (x[0] ? x[0].toUpperCase() + "." : "")).join("");
  return `${surname} ${initials}`.trim();
}

function memberNiceName(m) {
  const shortName = (m?.short_name || "").trim();
  if (shortName) return shortName;
  const fi = fioInitials(m?.full_name);
  if (fi) return fi;
  const u = (m?.tg_username || "").trim();
  if (u) return u.startsWith("@") ? u : `@${u}`;
  return m?.user_id ? `user#${m.user_id}` : "—";
}

function memberLabel(m) {
  const name = memberNiceName(m);
  const u = (m?.tg_username || "").trim();
  const uTxt = u ? (u.startsWith("@") ? u : `@${u}`) : "";
  const role = (m?.venue_role || "").toUpperCase();
  return `${name}${uTxt && !name.includes("@") ? ` · ${uTxt}` : ""}${role ? ` · ${role}` : ""}`;
}

/* ---------- Page shell ---------- */

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Должности</b>
          <div class="muted" id="subtitle">настройка ставок и прав</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="muted">Создайте должности, назначьте сотрудников и задайте условия оплаты.</div>
      <div class="muted small" id="accessHint" style="margin-top:6px"></div>

      <div class="itemcard" style="margin-top:12px">
        <div class="row" style="justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap">
          <b>Список должностей</b>
          <button class="btn primary" id="btnOpenCreate">+ Создать</button>
        </div>
        <div id="list" style="margin-top:10px">
          <div class="skeleton"></div><div class="skeleton"></div>
        </div>
      </div>



<div class="itemcard" style="margin-top:12px; display:none" id="invitesCard">
  <div class="row" style="justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap">
    <b>Приглашённые <span class="badge badge--draft">приглашён</span></b>
  </div>
  <div class="muted" style="margin-top:6px; font-size:12px">Назначьте должность заранее — применится после принятия приглашения.</div>
  <div id="invitesList" style="margin-top:10px">
    <div class="muted">—</div>
  </div>
</div>
      <div class="row" style="margin-top:12px">
        <a class="link" id="back" href="#">← Назад к заведению</a>
      </div>
    </div>

    <div id="toast" class="toast"><div class="toast__text"></div></div>

    <!-- confirm modal (используется confirmModal()) -->
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

    <!-- editor modal для создания/редактирования должности -->
    <div id="posModal" class="modal">
      <div class="modal__backdrop" data-close></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="posModalTitle">Должность</b>
            <div class="muted" id="posModalHint" style="margin-top:4px; font-size:12px"></div>
          </div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body" id="posModalBody"></div>
      </div>
    </div>

    <div class="nav">
      <div class="wrap"><div id="nav"></div></div>
    </div>
  `;

  mountCommonUI("none");
}


function applyAccessToShell() {
  const btn = document.getElementById("btnOpenCreate");
  if (btn) btn.style.display = auth.canManage ? "" : "none";

  const sub = document.getElementById("subtitle");
  if (sub) {
    if (auth.canManage && auth.canManagePerms) sub.textContent = "настройка ставок и прав";
    else if (auth.canManage) sub.textContent = "настройка ставок";
    else if (auth.canManagePerms) sub.textContent = "настройка прав";
    else sub.textContent = "просмотр";
  }

  const ah = document.getElementById("accessHint");
  if (ah) {
    const marks = (ok) => ok ? "✓" : "—";
    ah.textContent = `Права: просмотр ${marks(auth.canViewList)} · управление ${marks(auth.canManage)} · права позиции ${marks(auth.canManagePerms)} · назначение ${marks(auth.canAssign)}`;
  }
}

function openPosModal({ title, hint, bodyHtml }) {
  const m = document.getElementById("posModal");
  const t = document.getElementById("posModalTitle");
  const h = document.getElementById("posModalHint");
  const b = document.getElementById("posModalBody");
  if (t) t.textContent = title || "Должность";
  if (h) h.textContent = hint || "";
  if (b) b.innerHTML = bodyHtml || "";
  m?.classList.add("open");
}

function closePosModal() {
  document.getElementById("posModal")?.classList.remove("open");
}

function wirePosModalClose() {
  const m = document.getElementById("posModal");
  if (!m) return;
  m.querySelectorAll("[data-close]").forEach((x) => x.addEventListener("click", closePosModal));
}

/* ---------- State ---------- */

let state = {
  venueId: "",
  members: [],
  positions: [],
  invites: [],
};


let auth = {
  role: "",
  permissions: [],
  flags: {},
  isOwnerOrAdmin: false,
  canViewList: false,
  canManage: false,
  canAssign: false,
  canManagePerms: false,
};

function hasPerm(code) {
  return Array.isArray(auth.permissions) && auth.permissions.includes(code);
}

function computeAuth(perms) {
  const role = String(perms?.role || perms?.venue_role || perms?.my_role || "").toUpperCase();
  const sysRole = String(perms?.system_role || "").toUpperCase();
  const isOwnerOrAdmin = role === "OWNER" || sysRole === "SUPER_ADMIN" || sysRole === "MODERATOR" || role === "SUPER_ADMIN" || role === "MODERATOR";
  const permissions = Array.isArray(perms?.permissions) ? perms.permissions : [];
  const flags = perms?.position_flags || {};

  auth.role = role || sysRole || "";
  auth.permissions = permissions;
  auth.flags = flags;
  auth.isOwnerOrAdmin = isOwnerOrAdmin;

  auth.canViewList = isOwnerOrAdmin || permissions.some((c) => ["POSITIONS_VIEW", "POSITIONS_MANAGE", "POSITIONS_ASSIGN", "POSITION_PERMISSIONS_MANAGE"].includes(c));
  auth.canManage = isOwnerOrAdmin || permissions.includes("POSITIONS_MANAGE");
  auth.canAssign = isOwnerOrAdmin || permissions.includes("POSITIONS_ASSIGN");
  auth.canManagePerms = isOwnerOrAdmin || permissions.includes("POSITION_PERMISSIONS_MANAGE");
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || "";
  if (venueId) setActiveVenueId(venueId);
  return venueId;
}

function normalizePositions(out) {
  if (!out) return [];
  if (Array.isArray(out)) return out;
  if (Array.isArray(out.items)) return out.items;
  if (Array.isArray(out.positions)) return out.positions;
  if (Array.isArray(out.data)) return out.data;
  return [];
}

function uniqueTitles() {
  const set = new Set();
  for (const p of state.positions) {
    const t = String(p.title || "").trim();
    if (t) set.add(t);
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
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
    ? "Начни вводить — будут подсказки (например: Бармен, Официант…) "
    : "Подсказок пока нет — создай первую должность";

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
        <div class="muted" style="margin-bottom:6px">Ставка</div>
        <input id="f_rate" inputmode="decimal" placeholder="0" value="${esc(p.rate ?? "")}" ${canEditMain ? "" : "disabled"} />
      </div>

      <div>
        <div class="muted" style="margin-bottom:6px">Процент от продаж</div>
        <input id="f_percent" inputmode="decimal" placeholder="0" value="${esc(p.percent ?? "")}" ${canEditMain ? "" : "disabled"} />
      </div>
    </div>

    
    <div style="margin-top:12px; display:${canEditPerms ? "grid" : "none"}; grid-template-columns: 1fr; gap:10px">

      <div class="perm-tools">
        <button class="btn sm" type="button" id="btnPermAllOn">Включить все</button>
        <button class="btn sm" type="button" id="btnPermAllOff">Выключить все</button>
      </div>

      <div class="card" style="padding:12px">
        <div class="perm-group-title">
          <div>
            <b>Права для отчётов</b>
            <div class="muted" style="margin-top:4px; font-size:12px">Можно включать выборочно</div>
          </div>
          <div class="row" style="gap:6px; flex:0 0 auto">
            <button class="btn sm" type="button" data-perm-set="reports" data-value="1">Все</button>
            <button class="btn sm" type="button" data-perm-set="reports" data-value="0">Ничего</button>
          </div>
        </div>

        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">Создание отчётов</div>
            <div class="perm-desc">Может создавать отчёты по сменам</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="f_rep_create" data-perm-group="reports" ${p.can_make_reports ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>

        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">Редактирование отчётов</div>
            <div class="perm-desc">Может исправлять ранее созданные отчёты</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="f_rep_edit" data-perm-group="reports" ${p.can_make_reports ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>

        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">Просмотр отчётов</div>
            <div class="perm-desc">Может смотреть отчёты (даже если сам их не создаёт)</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="f_rep_view" data-perm-group="reports" ${(p.can_view_reports || p.can_make_reports) ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>

        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">Просмотр выручки</div>
            <div class="perm-desc">Может видеть суммы выручки в отчётах</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="f_rep_revenue" data-perm-group="reports" ${(p.can_view_revenue || p.can_make_reports) ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>

        <div class="muted" style="font-size:12px; margin-top:6px">
          Владелец видит отчёты всегда, независимо от должности.
        </div>
      </div>

      <div class="card" style="padding:12px">
        <div class="perm-group-title">
          <b>Права для графика</b>
          <div class="row" style="gap:6px; flex:0 0 auto">
            <button class="btn sm" type="button" data-perm-set="schedule" data-value="1">Все</button>
            <button class="btn sm" type="button" data-perm-set="schedule" data-value="0">Ничего</button>
          </div>
        </div>

        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">Редактировать график</div>
            <div class="perm-desc">Может добавлять и менять смены в календаре</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="f_can_schedule" data-perm-group="schedule" ${p.can_edit_schedule ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>
      </div>

      <div class="card" style="padding:12px">
        <div class="perm-group-title">
          <div>
            <b>Штрафы / Списания / Премии</b>
            <div class="muted" style="margin-top:4px; font-size:12px">Доступ к финансовым корректировкам</div>
          </div>
          <div class="row" style="gap:6px; flex:0 0 auto">
            <button class="btn sm" type="button" data-perm-set="adjustments" data-value="1">Все</button>
            <button class="btn sm" type="button" data-perm-set="adjustments" data-value="0">Ничего</button>
          </div>
        </div>

        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">Просмотр</div>
            <div class="perm-desc">Может смотреть штрафы/премии и историю</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="f_adj_view" data-perm-group="adjustments" ${(p.can_view_adjustments || p.can_manage_adjustments) ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>

        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">Создание и редактирование</div>
            <div class="perm-desc">Может создавать, менять и отменять корректировки</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="f_adj_manage" data-perm-group="adjustments" ${p.can_manage_adjustments ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>

        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">Оспаривания</div>
            <div class="perm-desc">Может разруливать споры по штрафам/премиям</div>
          </div>
          <label class="switch">
            <input type="checkbox" id="f_adj_dispute" data-perm-group="adjustments" ${(p.can_resolve_disputes || p.can_manage_adjustments) ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        </div>
      </div>
    </div>


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
  const rateEl = document.getElementById("f_rate");
  const percentEl = document.getElementById("f_percent");

  const title = (titleEl && !titleEl.disabled) ? (titleEl.value || "").trim() : String(base.title || "").trim();
  const member_user_id = (memberEl && !memberEl.disabled) ? Number(memberEl.value) : Number(base.member_user_id);

  const toNum = (v) => {
    const x = Number(String(v ?? "").replace(",", "."));
    return Number.isFinite(x) ? x : 0;
  };

  const rate = (rateEl && !rateEl.disabled) ? toNum(rateEl.value) : toNum(base.rate);
  const percent = (percentEl && !percentEl.disabled) ? toNum(percentEl.value) : toNum(base.percent);

  // Permission flags block may be hidden
  const readChk = (id, fallback) => {
    const el = document.getElementById(id);
    if (!el) return !!fallback;
    return !!el.checked;
  };

  const rep_create = readChk("f_rep_create", base.can_make_reports);
  const rep_edit = readChk("f_rep_edit", base.can_make_reports);
  const can_make_reports = rep_create || rep_edit;
  const can_view_reports = readChk("f_rep_view", (base.can_view_reports || can_make_reports));
  const can_view_revenue = readChk("f_rep_revenue", (base.can_view_revenue || can_make_reports));

  const can_edit_schedule = readChk("f_can_schedule", base.can_edit_schedule);

  const can_view_adjustments = readChk("f_adj_view", (base.can_view_adjustments || base.can_manage_adjustments));
  const can_manage_adjustments = readChk("f_adj_manage", base.can_manage_adjustments);
  const can_resolve_disputes = readChk("f_adj_dispute", (base.can_resolve_disputes || base.can_manage_adjustments));

  if (!title) throw new Error("Укажите название должности");
  if (!Number.isFinite(member_user_id) || member_user_id <= 0) throw new Error("Выберите сотрудника");

  // Validate numeric only when editable
  if (rateEl && !rateEl.disabled && !Number.isFinite(rate)) throw new Error("Укажите корректную ставку (число)");
  if (percentEl && !percentEl.disabled && !Number.isFinite(percent)) throw new Error("Укажите корректный процент (число)");

  return {
    title,
    member_user_id,
    rate: Math.max(0, Math.round(rate)),
    percent: Math.max(0, Math.min(100, Math.round(percent))),
    can_make_reports,
    can_view_reports,
    can_view_revenue,
    can_edit_schedule,
    can_view_adjustments,
    can_manage_adjustments,
    can_resolve_disputes,
  };
}


function setupPermUX() {
  const modal = document.getElementById("posModal");
  if (!modal) return;

  // Bulk-режим: чтобы "Включить/Выключить все" срабатывало сразу (без "по одному"),
  // и чтобы зависимости применялись один раз в конце.
  let bulk = false;

  const allBoxes = () =>
    Array.from(modal.querySelectorAll('input[type="checkbox"]'));

  const setBoxes = (boxes, val, after) => {
    bulk = true;
    boxes.forEach((b) => {
      b.checked = !!val;
    });
    bulk = false;
    if (typeof after === "function") after();
  };

  // Global on/off
  document.getElementById("btnPermAllOn")?.addEventListener("click", () => {
    setBoxes(allBoxes(), true, () => {
      syncReports();
      syncAdjustments();
    });
  });
  document.getElementById("btnPermAllOff")?.addEventListener("click", () => {
    setBoxes(allBoxes(), false, () => {
      // При "Выключить все" ожидаем 0 без автодовключений
      if (repView) repView.checked = false;
      if (adjView) adjView.checked = false;
      syncReports();
      syncAdjustments();
    });
  });

  // Group on/off
  modal.querySelectorAll("[data-perm-set]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const group = btn.getAttribute("data-perm-set");
      const v = btn.getAttribute("data-value") === "1";
      const boxes = Array.from(
        modal.querySelectorAll(`input[type="checkbox"][data-perm-group="${group}"]`)
      );
      setBoxes(boxes, v, () => {
        syncReports();
        syncAdjustments();
      });
    });
  });

  // Dependency helpers
  const repCreate = document.getElementById("f_rep_create");
  const repEdit = document.getElementById("f_rep_edit");
  const repView = document.getElementById("f_rep_view");
  const repRevenue = document.getElementById("f_rep_revenue");

  const adjView = document.getElementById("f_adj_view");
  const adjManage = document.getElementById("f_adj_manage");
  const adjDispute = document.getElementById("f_adj_dispute");

  function syncReports() {
    if (bulk) return;
    const mustView = (!!repCreate?.checked) || (!!repEdit?.checked) || (!!repRevenue?.checked);
    if (mustView && repView) repView.checked = true;
    if (repView && !repView.checked) {
      // если пользователь попытался выключить просмотр при включённых зависимых правах — вернём обратно
      if (mustView) repView.checked = true;
      // если выручка включена, без просмотра её быть не может
      if (repRevenue?.checked && repView) repView.checked = true;
    }
  }

  function syncAdjustments() {
    if (bulk) return;
    // manage -> view
    if (adjManage?.checked && adjView) adjView.checked = true;

    // dispute -> manage + view
    if (adjDispute?.checked) {
      if (adjManage) adjManage.checked = true;
      if (adjView) adjView.checked = true;
    }

    // если manage выключили — dispute тоже выключаем
    if (adjManage && !adjManage.checked && adjDispute) adjDispute.checked = false;

    // если view выключили при manage/dispute — вернём view
    if (adjView && !adjView.checked && ((adjManage?.checked) || (adjDispute?.checked))) {
      adjView.checked = true;
    }
  }

  // Attach listeners
  [repCreate, repEdit, repView, repRevenue].forEach((el) => {
    if (!el) return;
    el.addEventListener("change", syncReports);
  });
  [adjView, adjManage, adjDispute].forEach((el) => {
    if (!el) return;
    el.addEventListener("change", syncAdjustments);
  });

  // Initial sync
  syncReports();
  syncAdjustments();
}


/* ---------- Modal actions ---------- */

function openCreateModal() {
  if (!auth.canManage) {
    toast("Нет прав на создание должностей", "err");
    return;
  }
  openPosModal({
    title: "Создать должность",
    hint: "Одна должность может быть у нескольких сотрудников (например «Бармен»).",
    bodyHtml: renderPositionForm({ mode: "create" }),
  });

  // дефолтный выбор сотрудника
  const sel = document.getElementById("f_member");
  if (sel && sel.options.length) sel.value = sel.options[0].value;
  setupPermUX();

  document.getElementById("btnCancelPos")?.addEventListener("click", closePosModal);

  document.getElementById("btnSavePos")?.addEventListener("click", async () => {
    let payload;
    try {
      payload = collectPayload({});
    } catch (e) {
      toast(e?.message || "Ошибка формы", "warn");
      return;
    }

    try {
      await createVenuePosition(state.venueId, payload);
      toast("Должность создана", "ok");
      closePosModal();
      await load();
    } catch (e) {
      toast("Ошибка сохранения: " + (e?.message || e), "err");
    }
  });
}

function openEditModal(p, modeOverride = null) {
  const mode = modeOverride || (auth.canManage ? "edit" : (auth.canManagePerms ? "perms" : "view"));
  if (mode === "view") {
    toast("Нет прав на изменение должности", "err");
    return;
  }
  openPosModal({
    title: "Изменить должность",
    hint: "Меняй должность/условия для выбранного сотрудника.",
    bodyHtml: renderPositionForm({ mode, position: p }),
  });

  const sel = document.getElementById("f_member");
  if (sel) sel.value = String(p.member_user_id ?? "");
  setupPermUX();

  document.getElementById("btnCancelPos")?.addEventListener("click", closePosModal);

  document.getElementById("btnSavePos")?.addEventListener("click", async () => {
    let payload;
    try {
      payload = collectPayload(p);
    } catch (e) {
      toast(e?.message || "Ошибка формы", "warn");
      return;
    }

    try {
      await updateVenuePosition(state.venueId, p.id, payload);
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

/* ---------- Render list grouped by title ---------- */

function renderPositions() {
  const list = document.getElementById("list");
  list.innerHTML = "";

  if (!state.positions.length) {
    list.innerHTML = `<div class="muted">Должностей пока нет</div>`;
    return;
  }

  const memberById = new Map(state.members.map((m) => [String(m.user_id), m]));

  // group by title
  const groups = new Map();
  for (const p of state.positions) {
    const t = String(p.title || "Без названия").trim() || "Без названия";
    if (!groups.has(t)) groups.set(t, []);
    groups.get(t).push(p);
  }

  const titles = Array.from(groups.keys()).sort((a, b) => a.localeCompare(b, "ru"));

  for (const title of titles) {
    const arr = groups.get(title).slice().sort((a, b) => {
      const aa = String(memberById.get(String(a.member_user_id))?.tg_username || "");
      const bb = String(memberById.get(String(b.member_user_id))?.tg_username || "");
      return aa.localeCompare(bb);
    });

    const wrap = document.createElement("div");
    wrap.className = "itemcard";
    wrap.style.marginTop = "10px";

    wrap.innerHTML = `
      <div class="row" style="justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap">
        <b>${esc(title)} <span class="muted">(${arr.length})</span></b>
        ${auth.canManage ? `<button class="btn" data-add-same>+ Добавить сотрудника</button>` : ``}
      </div>
      <div class="list" style="margin-top:10px" data-rows></div>
    `;

    // "+ Добавить сотрудника" с предзаполненным title
    const addSameBtn = wrap.querySelector("[data-add-same]");
    if (addSameBtn) addSameBtn.onclick = () => {
      if (!auth.canManage) { toast("Нет прав на создание должностей", "err"); return; }
      openPosModal({
        title: "Создать должность",
        hint: "Добавляем ещё одного сотрудника на эту должность.",
        bodyHtml: renderPositionForm({ mode: "create", position: { title } }),
      });
      // проставим title
      const t = document.getElementById("f_title");
      if (t) t.value = title;

      const sel = document.getElementById("f_member");
      if (sel && sel.options.length) sel.value = sel.options[0].value;
  setupPermUX();

      document.getElementById("btnCancelPos")?.addEventListener("click", closePosModal);
      document.getElementById("btnSavePos")?.addEventListener("click", async () => {
        let payload;
        try { payload = collectPayload(); } catch (e) { toast(e?.message || "Ошибка формы", "warn"); return; }
        try {
          await createVenuePosition(state.venueId, payload);
          toast("Должность создана", "ok");
          closePosModal();
          await load();
        } catch (e) {
          toast("Ошибка сохранения: " + (e?.message || e), "err");
        }
      });
    };

    const rows = wrap.querySelector("[data-rows]");

    for (const p of arr) {
      const m = memberById.get(String(p.member_user_id || ""));
      const who = m ? memberLabel(m) : (p.member_user_id ? `user_id=${p.member_user_id}` : "—");

      const row = document.createElement("div");
      row.className = "list__row";

      row.innerHTML = `
        <div class="list__main">
          <div><b>${esc(who)}</b></div>
          <div class="muted" style="margin-top:4px">
            Ставка: ${esc(money(p.rate))} · Процент: ${esc(money(p.percent))}% ·
            Отчёты: ${p.can_make_reports ? "да" : "нет"} · График: ${p.can_edit_schedule ? "да" : "нет"}
          </div>
        </div>
        <div class="row" style="gap:8px; flex-wrap:wrap">
          ${auth.canManage ? `<button class="btn" data-edit>Изменить</button>` : (auth.canManagePerms ? `<button class="btn" data-perms>Права</button>` : ``)}
          ${auth.canManage ? `<button class="btn danger" data-del>Архивировать</button>` : ``}
        </div>
      `;

      const btnEdit = row.querySelector("[data-edit]");
      if (btnEdit) btnEdit.onclick = () => openEditModal(p, "edit");

      const btnPerms = row.querySelector("[data-perms]");
      if (btnPerms) btnPerms.onclick = () => openEditModal(p, "perms");

      const btnDel = row.querySelector("[data-del]");
      if (btnDel) btnDel.onclick = async () => {
        const ok = await confirmModal({
          title: "Архивировать должность?",
          text: `Удалить должность «${title}» для сотрудника?`,
          confirmText: "В архив",
          danger: true,
        });
        if (!ok) return;

        try {
          await deleteVenuePosition(state.venueId, p.id);
          toast("Должность архивирована", "ok");
          await load();
        } catch (e) {
          toast("Ошибка удаления: " + (e?.message || e), "err");
        }
      };

      rows.appendChild(row);
    }


    list.appendChild(wrap);
  }
}

/* ---------- Pending invites (position preset) ---------- */

function positionPresetFromTemplate(title) {
  const t = String(title || "").trim();
  if (!t) return null;
  const p = state.positions.find((x) => String(x.title || "").trim() === t);
  const src = p || { title: t };
  return {
    title: t,
    rate: Math.max(0, Math.round(Number(src.rate || 0) || 0)),
    percent: Math.max(0, Math.min(100, Math.round(Number(src.percent || 0) || 0))),
    can_make_reports: !!src.can_make_reports,
    can_view_reports: !!src.can_view_reports,
    can_view_revenue: !!src.can_view_revenue,
    can_edit_schedule: !!src.can_edit_schedule,
    can_view_adjustments: !!src.can_view_adjustments,
    can_manage_adjustments: !!src.can_manage_adjustments,
    can_resolve_disputes: !!src.can_resolve_disputes,
  };
}

function renderInvites() {
  const card = document.getElementById("invitesCard");
  const list = document.getElementById("invitesList");
  if (!card || !list) return;

  const invites = Array.isArray(state.invites) ? state.invites : [];
  if (!invites.length) {
    card.style.display = "none";
    return;
  }

  card.style.display = "";
  list.innerHTML = "";

  const titles = uniqueTitles();
  const canAssign = auth.canAssign;

  if (!titles.length) {
    const hint = document.createElement("div");
    hint.className = "muted";
    hint.textContent = "Сначала создайте хотя бы одну должность — тогда можно будет назначать её приглашённым.";
    list.appendChild(hint);
  }

  invites.forEach((inv) => {
    const row = document.createElement("div");
    row.className = "row";
    row.style = "justify-content:space-between; gap:12px; border-bottom:1px solid var(--border); padding:10px 0; align-items:flex-start; flex-wrap:wrap";

    const uname = (inv?.tg_username || "").trim();
    const presetTitle = inv?.default_position?.title ? String(inv.default_position.title) : "";

    const options = [
      `<option value="">— не назначено —</option>`,
      ...titles.map((t) => `<option value="${esc(t)}" ${t === presetTitle ? "selected" : ""}>${esc(t)}</option>`),
    ].join("");

    row.innerHTML = `
      <div style="min-width:220px">
        <div><b>@${esc(uname || "-")}</b> <span class="badge badge--draft">приглашён</span></div>
        <div class="muted" style="margin-top:4px; font-size:12px">роль=${esc(inv?.venue_role || "STAFF")}</div>
      </div>
      <div style="min-width:240px">
        <div class="muted" style="margin-bottom:6px">Должность</div>
        <select data-invite-id="${esc(String(inv.id))}" ${(!canAssign || !titles.length) ? "disabled" : ""}>
          ${options}
        </select>
        ${!canAssign ? `<div class="muted small" style="margin-top:6px">Нет права POSITIONS_ASSIGN</div>` : ``}
      </div>
    `;

    list.appendChild(row);
  });

  // handlers
  list.querySelectorAll("select[data-invite-id]").forEach((sel) => {
    sel.addEventListener("change", async () => {
      const inviteId = Number(sel.getAttribute("data-invite-id"));
      if (!inviteId) return;
      if (!auth.canAssign) return;

      const v = String(sel.value || "");
      const preset = v ? positionPresetFromTemplate(v) : null;

      try {
        await patchInviteDefaultPosition(state.venueId, inviteId, preset);
        toast("Сохранено", "ok");

        // update local state
        for (const it of state.invites) {
          if (Number(it.id) === inviteId) {
            it.default_position = preset;
            break;
          }
        }

        renderInvites();
      } catch (e) {
        toast("Не удалось назначить должность: " + (e?.data?.detail || e?.message || "ошибка"), "err");
      }
    });
  });
}

/* ---------- Load ---------- */

async function load() {
  const m = await getVenueMembers(state.venueId);
  state.members = (m?.members || []).slice().sort((a, b) => {
    const aa = (a.tg_username || "").toLowerCase();
    const bb = (b.tg_username || "").toLowerCase();
    return aa.localeCompare(bb);
  });

  state.invites = (m?.pending_invites || []).slice().sort((a, b) => String(a.tg_username || "").localeCompare(String(b.tg_username || ""), "ru"));

  const pos = await getVenuePositions(state.venueId);
  state.positions = normalizePositions(pos);

  renderPositions();
  renderInvites();
}

/* ---------- Main ---------- */

async function main() {
  renderShell();

  // ✅ ВАЖНО: applyTelegramTheme должен быть ПОСЛЕ renderShell, иначе data-userpill ещё нет
  applyTelegramTheme();
  wirePosModalClose();

  await ensureLogin({ silent: true });
  await mountNav({ activeTab: "none" });

  const venueId = parseVenueId() || (await bootPage({ requireVenue: true, silentLogin: true })).activeVenueId;
  state.venueId = venueId;

  if (!state.venueId) {
    toast("Не выбрано заведение", "warn");
    location.href = "/app-venues.html";
    return;
  }

  // access check: permissions-based
  try {
    const [me, perms] = await Promise.all([api("/me"), getMyVenuePermissions(state.venueId)]);
    perms.system_role = me?.system_role;
    computeAuth(perms);
  } catch (e) {
    computeAuth({});
  }

  applyAccessToShell();

  if (!auth.canViewList) {
    toast("Нет доступа к должностям", "err");
    location.replace(`/app-dashboard.html?venue_id=${encodeURIComponent(state.venueId)}`);
    return;
  }

  document.getElementById("back").href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;
  const btnCreate = document.getElementById("btnOpenCreate");
  if (btnCreate) btnCreate.onclick = openCreateModal;

  try {
    await load();
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || e), "err");
    const list = document.getElementById("list");
    if (list) list.innerHTML = `<div class="muted">Ошибка загрузки: ${esc(e?.message || e)}</div>`;
  }
}

main();

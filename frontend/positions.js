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
  getVenuePositionPresets,
  getPayProfiles,
  createVenuePosition,
  updateVenuePosition,
  deleteVenuePosition,
  patchInviteDefaultPosition,
  isDemoUiMode,
} from "/app.js?v=20260726-navmore1";

import { permSetFromResponse, roleUpper, hasAnyPerm } from "/permissions.js";
import { createPositionPermissionController } from "/positions/permission-controller.js?v=20260726-navmore1";
import { createPositionDomain } from "/positions/position-domain.js?v=20260720-unified6";
import { createPositionEditor } from "/positions/position-editor.js?v=20260723-functional1";
import { createPositionList } from "/positions/position-list.js?v=20260725-polish3";
import { createPositionInviteController } from "/positions/invite-controller.js?v=20260725-polish4";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Должности</b>
          <div class="muted" id="subtitle">настройка профилей зарплаты и прав</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <main class="positions-shell">
      <section class="card section-card positions-hero">
        <div class="section-card__head">
          <div class="section-card__title">
            <b>Роли команды и рабочие настройки</b>
            <div class="muted">Создайте должности, назначьте сотрудников и выберите профиль начислений и права.</div>
          </div>
        </div>
        <div class="positions-access" id="accessHint"></div>
      </section>

      <section class="itemcard section-card positions-section">
        <div class="section-card__head">
          <div class="section-card__title">
            <b>Список должностей</b>
            <div class="muted small">Шаблон должности остаётся в списке, даже если сотрудник ещё не назначен.</div>
          </div>
          <button class="btn primary" id="btnOpenCreate">+ Создать</button>
        </div>
        <div class="position-group-list" id="list" aria-live="polite">
          <div class="skeleton skeleton--card"></div>
          <div class="skeleton skeleton--card"></div>
        </div>
      </section>

      <section class="itemcard section-card positions-section positions-invites hidden" id="invitesCard">
        <div class="section-card__head">
          <div class="section-card__title">
            <b>Приглашённые <span class="badge badge--draft">ожидают входа</span></b>
            <div class="muted small">Назначьте должность заранее — она применится после принятия приглашения.</div>
          </div>
        </div>
        <div class="position-invite-list" id="invitesList" aria-live="polite">
          <div class="muted">—</div>
        </div>
      </section>

      <div class="positions-back-actions">
        <button class="btn subtle inline" id="back" type="button" data-nav-button>← Назад к заведению</button>
      </div>
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

    <div id="posModal" class="modal">
      <div class="modal__backdrop" data-close></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="posModalTitle">Должность</b>
            <div class="muted small mt-4" id="posModalHint"></div>
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
  btn?.classList.toggle("hidden", !auth.canManage);

  const sub = document.getElementById("subtitle");
  if (sub) {
    if (auth.canManage && auth.canManagePerms) sub.textContent = "должности, профили зарплаты и права";
    else if (auth.canManage) sub.textContent = "должности и профили зарплаты";
    else if (auth.canManagePerms) sub.textContent = "должности и права";
    else sub.textContent = "список должностей";
  }

  const ah = document.getElementById("accessHint");
  if (ah) {
    const marks = (ok) => ok ? "✓" : "—";
    ah.innerHTML = `
      <span class="position-access-chip">Список ${marks(auth.canViewList)}</span>
      <span class="position-access-chip">Редактирование ${marks(auth.canManage)}</span>
      <span class="position-access-chip">Права ${marks(auth.canManagePerms)}</span>
      <span class="position-access-chip">Назначения ${marks(auth.canAssign)}</span>
    `;
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
  positionPresets: [],
  invites: [],
  payProfiles: [],
};


let auth = {
  role: "",
  permissions: [],
  isOwnerOrAdmin: false,
  canViewList: false,
  canManage: false,
  canAssign: false,
  canManagePerms: false,
};

function computeAuth(perms) {
  const role = roleUpper(perms);
  const sysRole = String(perms?.system_role || "").toUpperCase();
  const isOwnerOrAdmin =
    role === "OWNER" ||
    role === "VENUE_OWNER" ||
    sysRole === "SUPER_ADMIN" ||
    sysRole === "MODERATOR";

  const pset = permSetFromResponse(perms);
  const permissions = Array.from(pset);

  auth.role = role || sysRole || "";
  auth.permissions = permissions;
  auth.isOwnerOrAdmin = isOwnerOrAdmin;

  auth.canViewList =
    isOwnerOrAdmin ||
    hasAnyPerm(pset, ["POSITIONS_VIEW", "POSITIONS_MANAGE", "POSITIONS_ASSIGN", "POSITION_PERMISSIONS_MANAGE"]);

  auth.canManage = isOwnerOrAdmin || pset.has("POSITIONS_MANAGE");
  auth.canAssign = isOwnerOrAdmin || pset.has("POSITIONS_ASSIGN");
  auth.canManagePerms = isOwnerOrAdmin || pset.has("POSITION_PERMISSIONS_MANAGE");
  if (isDemoUiMode(perms)) {
    auth.canManage = false;
    auth.canAssign = false;
    auth.canManagePerms = false;
  }
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || "";
  if (venueId) setActiveVenueId(venueId);
  return venueId;
}


const positionDomain = createPositionDomain({ state });
const positionPermissions = createPositionPermissionController({ state, api });
const positionEditor = createPositionEditor({
  state,
  auth,
  esc,
  domain: positionDomain,
  permissions: positionPermissions,
  openPosModal,
  closePosModal,
  toast,
  confirmModal,
  createVenuePosition,
  updateVenuePosition,
  deleteVenuePosition,
  load,
});
const { openCreateModal } = positionEditor;
const { renderPositions } = createPositionList({
  state,
  auth,
  esc,
  domain: positionDomain,
  editor: positionEditor,
  toast,
  confirmModal,
  deleteVenuePosition,
  load,
});
const { renderInvites } = createPositionInviteController({
  state,
  auth,
  esc,
  domain: positionDomain,
  toast,
  patchInviteDefaultPosition,
});
const { normalizePositions, normalizePositionPresets } = positionDomain;
const { ensurePermissionTemplates } = positionPermissions;


async function load() {
  const m = await getVenueMembers(state.venueId);
  state.members = (m?.members || []).slice().sort((a, b) => {
    const aa = (a.tg_username || "").toLowerCase();
    const bb = (b.tg_username || "").toLowerCase();
    return aa.localeCompare(bb);
  });

  state.invites = (m?.pending_invites || []).slice().sort((a, b) => String(a.tg_username || "").localeCompare(String(b.tg_username || ""), "ru"));

  try {
    const profiles = await getPayProfiles(state.venueId, { includeInactive: false });
    state.payProfiles = Array.isArray(profiles) ? profiles : [];
  } catch {
    state.payProfiles = [];
  }

  const pos = await getVenuePositions(state.venueId);
  state.positions = normalizePositions(pos);

  try {
    const presets = await getVenuePositionPresets(state.venueId, { includeInactive: false });
    state.positionPresets = normalizePositionPresets(presets);
  } catch {
    state.positionPresets = [];
  }

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
  if (btnCreate) btnCreate.onclick = () => openCreateModal();

  try { await ensurePermissionTemplates(); } catch {}

  try {
    await load();
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || e), "err");
    const list = document.getElementById("list");
    if (list) list.innerHTML = `<div class="position-state position-state--error">Ошибка загрузки: ${esc(e?.message || e)}</div>`;
  }
}

main();

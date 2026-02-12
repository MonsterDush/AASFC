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
} from "/app.js";

applyTelegramTheme();

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
  const x = Number(n);
  if (!Number.isFinite(x)) return String(n);
  return x.toLocaleString("ru-RU");
}

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

      <div class="itemcard" style="margin-top:12px" id="formCard">
        <b id="formTitle">Создать должность</b>
        <div class="grid grid2" style="margin-top:10px">
          <div>
            <div class="muted" style="margin-bottom:6px">Название должности</div>
            <input id="f_title" placeholder="Например: Бармен" />
          </div>
          <div>
            <div class="muted" style="margin-bottom:6px">Сотрудник</div>
            <select id="f_member"></select>
          </div>
          <div>
            <div class="muted" style="margin-bottom:6px">Ставка</div>
            <input id="f_rate" inputmode="decimal" placeholder="0" />
          </div>
          <div>
            <div class="muted" style="margin-bottom:6px">Процент от продаж</div>
            <input id="f_percent" inputmode="decimal" placeholder="0" />
          </div>
        </div>

        <div style="margin-top:10px">
          <label class="row" style="gap:10px; align-items:center; margin:6px 0">
            <input type="checkbox" id="f_can_reports" />
            <span>Может заполнять отчёты</span>
          </label>
          <label class="row" style="gap:10px; align-items:center; margin:6px 0">
            <input type="checkbox" id="f_can_schedule" />
            <span>Может редактировать график</span>
          </label>
        </div>

        <div class="row" style="gap:8px; margin-top:10px; flex-wrap:wrap">
          <button class="btn primary" id="btnSave">Сохранить</button>
          <button class="btn" id="btnReset">Сбросить</button>
          <span class="muted" id="formHint" style="margin-left:auto"></span>
        </div>
      </div>

      <div class="itemcard" style="margin-top:12px">
        <b>Список должностей</b>
        <div id="list" style="margin-top:10px">
          <div class="skeleton"></div><div class="skeleton"></div>
        </div>
      </div>

      <div class="row" style="margin-top:12px">
        <a class="link" id="back" href="#">← Назад к заведению</a>
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

    <div class="nav">
      <div class="wrap"><div id="nav"></div></div>
    </div>
  `;

  mountCommonUI("none");
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || "";
  if (venueId) setActiveVenueId(venueId);
  return venueId;
}

let state = {
  venueId: "",
  members: [],
  positions: [],
  editingId: null,
};

function memberLabel(m) {
  const u = m?.tg_username ? `@${m.tg_username}` : `user_id=${m.user_id}`;
  return `${u} (${m.venue_role})`;
}

function fillMemberSelect() {
  const sel = document.getElementById("f_member");
  sel.innerHTML = "";

  // показываем только активных участников, кроме OWNER? — можно и OWNER, вдруг надо
  for (const m of state.members) {
    const opt = document.createElement("option");
    opt.value = String(m.user_id);
    opt.textContent = memberLabel(m);
    sel.appendChild(opt);
  }
}

function setFormMode(editing) {
  const title = document.getElementById("formTitle");
  const hint = document.getElementById("formHint");
  const btnSave = document.getElementById("btnSave");

  if (editing) {
    title.textContent = "Редактировать должность";
    btnSave.textContent = "Сохранить";
    hint.textContent = "";
  } else {
    title.textContent = "Создать должность";
    btnSave.textContent = "Создать";
    hint.textContent = "";
  }
}

function resetForm() {
  state.editingId = null;
  document.getElementById("f_title").value = "";
  document.getElementById("f_rate").value = "";
  document.getElementById("f_percent").value = "";
  document.getElementById("f_can_reports").checked = false;
  document.getElementById("f_can_schedule").checked = false;
  // member select оставить как есть
  setFormMode(false);
}

function populateFormFromPosition(p) {
  state.editingId = p.id;
  document.getElementById("f_title").value = p.title || "";
  document.getElementById("f_rate").value = p.rate ?? "";
  document.getElementById("f_percent").value = p.percent ?? "";
  document.getElementById("f_can_reports").checked = !!p.can_make_reports;
  document.getElementById("f_can_schedule").checked = !!p.can_edit_schedule;

  const sel = document.getElementById("f_member");
  if (p.member_user_id) sel.value = String(p.member_user_id);

  setFormMode(true);
}

function renderPositions() {
  const list = document.getElementById("list");
  list.innerHTML = "";

  if (!state.positions.length) {
    list.innerHTML = `<div class="muted">Должностей пока нет</div>`;
    return;
  }

  const memberById = new Map(state.members.map((m) => [String(m.user_id), m]));

  for (const p of state.positions) {
    const m = memberById.get(String(p.member_user_id || ""));
    const who = m ? memberLabel(m) : (p.member_user_id ? `user_id=${p.member_user_id}` : "—");

    const card = document.createElement("div");
    card.className = "itemcard";
    card.style.marginTop = "10px";

    card.innerHTML = `
      <div class="row" style="justify-content:space-between; gap:10px; flex-wrap:wrap">
        <div>
          <b>${esc(p.title || "Без названия")}</b>
          <div class="muted" style="margin-top:4px">${esc(who)}</div>
        </div>
        <div class="row" style="gap:8px; flex-wrap:wrap">
          <button class="btn" data-edit>Изменить</button>
          <button class="btn danger" data-del>Удалить</button>
        </div>
      </div>
      <div class="grid" style="grid-template-columns:1fr 1fr; gap:10px; margin-top:10px">
        <div class="mono">Ставка: ${esc(money(p.rate))}</div>
        <div class="mono">Процент: ${esc(money(p.percent))}%</div>
        <div class="mono">Отчёты: ${p.can_make_reports ? "да" : "нет"}</div>
        <div class="mono">График: ${p.can_edit_schedule ? "да" : "нет"}</div>
      </div>
    `;

    card.querySelector("[data-edit]").onclick = () => {
      populateFormFromPosition(p);
      toast("Режим редактирования", "info");
      window.scrollTo({ top: 0, behavior: "smooth" });
    };

    card.querySelector("[data-del]").onclick = async () => {
      const ok = await confirmModal({
        title: "Удалить должность?",
        text: `Удалить должность «${p.title || ""}»?`,
        confirmText: "Удалить",
        danger: true,
      });
      if (!ok) return;

      try {
        await deleteVenuePosition(state.venueId, p.id);
        toast("Должность удалена", "ok");
        await load();
      } catch (e) {
        toast("Ошибка удаления: " + (e?.message || e), "err");
      }
    };

    list.appendChild(card);
  }
}

async function load() {
  // members
  const m = await getVenueMembers(state.venueId);
  state.members = (m?.members || []).slice().sort((a, b) => {
    const aa = (a.tg_username || "").toLowerCase();
    const bb = (b.tg_username || "").toLowerCase();
    return aa.localeCompare(bb);
  });

  fillMemberSelect();

  // positions
  const pos = await getVenuePositions(state.venueId);
  state.positions = Array.isArray(pos) ? pos : (pos?.items || []);

  renderPositions();
}

function collectPayload() {
  const title = document.getElementById("f_title").value.trim();
  const member_user_id = Number(document.getElementById("f_member").value);
  const rate = Number(document.getElementById("f_rate").value);
  const percent = Number(document.getElementById("f_percent").value);
  const can_make_reports = document.getElementById("f_can_reports").checked;
  const can_edit_schedule = document.getElementById("f_can_schedule").checked;

  if (!title) throw new Error("Укажите название должности");
  if (!Number.isFinite(member_user_id)) throw new Error("Выберите сотрудника");
  if (!Number.isFinite(rate)) throw new Error("Укажите корректную ставку (число)");
  if (!Number.isFinite(percent)) throw new Error("Укажите корректный процент (число)");

  return {
    title,
    member_user_id,
    rate,
    percent,
    can_make_reports,
    can_edit_schedule,
  };
}

async function main() {
  renderShell();
  await ensureLogin({ silent: true });

  // mount bottom nav
  await mountNav({ activeTab: "none" });

  const venueId = parseVenueId() || (await bootPage({ requireVenue: true, silentLogin: true })).activeVenueId;
  state.venueId = venueId;

  if (!state.venueId) {
    toast("Не выбрано заведение", "warn");
    location.href = "/app-venues.html";
    return;
  }

  // access check: owner or super_admin
  try {
    const me = await api("/me");
    if (me?.system_role !== "SUPER_ADMIN") {
      const perms = await getMyVenuePermissions(state.venueId);
      const role = String(perms?.venue_role || perms?.my_role || perms?.role || "").toUpperCase();
      if (role !== "OWNER") {
        toast("Нет доступа к должностям", "err");
        location.replace(`/app-dashboard.html?venue_id=${encodeURIComponent(state.venueId)}`);
        return;
      }
    }
  } catch {
    // best-effort
  }

  // back link
  const back = document.getElementById("back");
  back.href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;

  // form actions
  document.getElementById("btnReset").onclick = resetForm;

  document.getElementById("btnSave").onclick = async () => {
    let payload;
    try {
      payload = collectPayload();
    } catch (e) {
      toast(e?.message || "Ошибка формы", "warn");
      return;
    }

    try {
      if (state.editingId) {
        await updateVenuePosition(state.venueId, state.editingId, payload);
        toast("Изменения сохранены", "ok");
      } else {
        await createVenuePosition(state.venueId, payload);
        toast("Должность создана", "ok");
      }
      resetForm();
      await load();
    } catch (e) {
      toast("Ошибка сохранения: " + (e?.message || e), "err");
    }
  };

  // initial load
  try {
    await load();
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || e), "err");
    const list = document.getElementById("list");
    if (list) list.innerHTML = `<div class="muted">Ошибка загрузки: ${esc(e?.message || e)}</div>`;
  }
}

main();

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

      <div class="itemcard" style="margin-top:12px">
        <div class="row" style="justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap">
          <b>Список должностей</b>
          <button class="btn primary" id="btnOpenCreate">+ Создать</button>
        </div>
        <div id="list" style="margin-top:10px">
          <div class="skeleton"></div><div class="skeleton"></div>
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
};

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
        <input id="f_title" placeholder="Например: Бармен" list="posTitleHints" value="${esc(p.title || "")}" />
        <div class="muted" style="margin-top:6px; font-size:12px">${esc(hint)}</div>
      </div>

      <div>
        <div class="muted" style="margin-bottom:6px">Сотрудник</div>
        <select id="f_member">${membersOptions}</select>
      </div>

      <div>
        <div class="muted" style="margin-bottom:6px">Ставка</div>
        <input id="f_rate" inputmode="decimal" placeholder="0" value="${esc(p.rate ?? "")}" />
      </div>

      <div>
        <div class="muted" style="margin-bottom:6px">Процент от продаж</div>
        <input id="f_percent" inputmode="decimal" placeholder="0" value="${esc(p.percent ?? "")}" />
      </div>
    </div>

    
    <div style="margin-top:12px; display:grid; grid-template-columns: 1fr; gap:10px">

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
      <button class="btn primary" id="btnSavePos">Сохранить</button>
      <button class="btn" id="btnCancelPos">Отмена</button>
      ${
        mode === "edit"
          ? `<button class="btn danger" id="btnDeletePos" style="margin-left:auto">Удалить</button>`
          : `<span class="muted" style="margin-left:auto">Можно назначать несколько людей на одну должность</span>`
      }
    </div>
  `;
}

function collectPayload() {
  const title = document.getElementById("f_title")?.value?.trim();
  const member_user_id = Number(document.getElementById("f_member")?.value);
  const rate = Number(String(document.getElementById("f_rate")?.value ?? "").replace(",", "."));
  const percent = Number(String(document.getElementById("f_percent")?.value ?? "").replace(",", "."));
    const rep_create = !!document.getElementById("f_rep_create")?.checked;
  const rep_edit = !!document.getElementById("f_rep_edit")?.checked;
  const can_view_reports = !!document.getElementById("f_rep_view")?.checked;
  const can_view_revenue = !!document.getElementById("f_rep_revenue")?.checked;
  const can_make_reports = rep_create || rep_edit;
  const can_edit_schedule = !!document.getElementById("f_can_schedule")?.checked;

  if (!title) throw new Error("Укажите название должности");
  if (!Number.isFinite(member_user_id)) throw new Error("Выберите сотрудника");
  if (!Number.isFinite(rate)) throw new Error("Укажите корректную ставку (число)");
  if (!Number.isFinite(percent)) throw new Error("Укажите корректный процент (число)");

  const can_view_adjustments = !!document.getElementById("f_adj_view")?.checked;
  const can_manage_adjustments = !!document.getElementById("f_adj_manage")?.checked;
  const can_resolve_disputes = !!document.getElementById("f_adj_dispute")?.checked;

  return { title, member_user_id, rate, percent, can_make_reports, can_view_reports, can_view_revenue, can_edit_schedule, can_view_adjustments, can_manage_adjustments, can_resolve_disputes };
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
      payload = collectPayload();
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

function openEditModal(p) {
  openPosModal({
    title: "Изменить должность",
    hint: "Меняй должность/условия для выбранного сотрудника.",
    bodyHtml: renderPositionForm({ mode: "edit", position: p }),
  });

  const sel = document.getElementById("f_member");
  if (sel) sel.value = String(p.member_user_id ?? "");
  setupPermUX();

  document.getElementById("btnCancelPos")?.addEventListener("click", closePosModal);

  document.getElementById("btnSavePos")?.addEventListener("click", async () => {
    let payload;
    try {
      payload = collectPayload();
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
      title: "Удалить должность?",
      text: `Удалить должность «${p.title || ""}» для сотрудника?`,
      confirmText: "Удалить",
      danger: true,
    });
    if (!ok) return;

    try {
      await deleteVenuePosition(state.venueId, p.id);
      toast("Должность удалена", "ok");
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
        <button class="btn" data-add-same>+ Добавить сотрудника</button>
      </div>
      <div class="list" style="margin-top:10px" data-rows></div>
    `;

    // "+ Добавить сотрудника" с предзаполненным title
    wrap.querySelector("[data-add-same]").onclick = () => {
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
          <button class="btn" data-edit>Изменить</button>
          <button class="btn danger" data-del>Удалить</button>
        </div>
      `;

      row.querySelector("[data-edit]").onclick = () => openEditModal(p);

      row.querySelector("[data-del]").onclick = async () => {
        const ok = await confirmModal({
          title: "Удалить должность?",
          text: `Удалить должность «${title}» для сотрудника?`,
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

      rows.appendChild(row);
    }

    list.appendChild(wrap);
  }
}

/* ---------- Load ---------- */

async function load() {
  const m = await getVenueMembers(state.venueId);
  state.members = (m?.members || []).slice().sort((a, b) => {
    const aa = (a.tg_username || "").toLowerCase();
    const bb = (b.tg_username || "").toLowerCase();
    return aa.localeCompare(bb);
  });

  const pos = await getVenuePositions(state.venueId);
  state.positions = normalizePositions(pos);

  renderPositions();
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
  } catch {}

  document.getElementById("back").href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;
  document.getElementById("btnOpenCreate").onclick = openCreateModal;

  try {
    await load();
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || e), "err");
    const list = document.getElementById("list");
    if (list) list.innerHTML = `<div class="muted">Ошибка загрузки: ${esc(e?.message || e)}</div>`;
  }
}

main();

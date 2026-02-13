import {
  applyTelegramTheme,
  ensureLogin,
  bootPage,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
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
    .replace(/\\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function money(n) {
  if (n === null || n === undefined || n === "") return "—";
  const x = Number(n);
  if (!Number.isFinite(x)) return String(n);
  return x.toLocaleString("ru-RU");
}

function fioInitials(fullName) {
  const s = String(fullName || "").trim();
  if (!s) return "";
  const p = s.split(/\s+/).filter(Boolean);
  if (p.length === 1) return p[0];
  const surname = p[0];
  const initials = p
    .slice(1)
    .map((x) => (x[0] ? x[0].toUpperCase() + "." : ""))
    .join("");
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
  const role = m?.venue_role || "";
  return `${name}${uTxt && !name.includes("@") ? ` · ${uTxt}` : ""}${role ? ` · ${role}` : ""}`;
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

      <div class="itemcard" style="margin-top:12px">
        <div class="row" style="justify-content:space-between; gap:10px; align-items:center; flex-wrap:wrap">
          <b>Список должностей</b>
          <button class="btn primary" id="btnCreate">+ Создать</button>
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

    <!-- confirm modal used by confirmModal() -->
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

    <!-- editor modal -->
    <div id="posModal" class="modal">
      <div class="modal__backdrop" data-close></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div>
            <div class="modal__title" id="posModalTitle">Должность</div>
            <div class="muted" style="margin-top:4px;font-size:12px" id="posModalHint"></div>
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

const state = {
  venueId: null,
  perms: null,
  members: [],
  positions: [],
};

function parseVenueId() {
  const qs = new URLSearchParams(location.search);
  const vid = qs.get("venue_id");
  return vid ? Number(vid) : null;
}

// --- modal helpers ---
function posModalEls() {
  return {
    modal: document.getElementById("posModal"),
    body: document.getElementById("posModalBody"),
    title: document.getElementById("posModalTitle"),
    hint: document.getElementById("posModalHint"),
  };
}

function openPosModal({ title, hint, bodyHtml }) {
  const { modal, body, title: t, hint: h } = posModalEls();
  if (t) t.textContent = title || "Должность";
  if (h) h.textContent = hint || "";
  if (body) body.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function closePosModal() {
  document.getElementById("posModal")?.classList.remove("open");
}

function wirePosModalClose() {
  const modal = document.getElementById("posModal");
  if (!modal) return;
  modal.querySelectorAll("[data-close]").forEach((x) => x.addEventListener("click", closePosModal));
}

// --- suggestions ---
function uniqueTitles() {
  const set = new Set();
  for (const p of state.positions) {
    const t = String(p.title || "").trim();
    if (t) set.add(t);
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b, "ru"));
}

function renderPositionForm({ mode, position }) {
  const titles = uniqueTitles();
  const membersOptions = state.members
    .map((m) => `<option value="${esc(String(m.user_id))}">${esc(memberLabel(m))}</option>`)
    .join("");

  const pTitle = position?.title ?? "";
  const rate = position?.rate ?? "";
  const percent = position?.percent ?? "";
  const canReports = !!position?.can_make_reports;
  const canSchedule = !!position?.can_edit_schedule;

  const titleHint = titles.length ? "Начни вводить — будут подсказки" : "Пока нет шаблонов названий";

  return `
    <datalist id="titleHints">
      ${titles.map((t) => `<option value="${esc(t)}"></option>`).join("")}
    </datalist>

    <div class="grid grid2" style="margin-top:10px">
      <div>
        <div class="muted" style="margin-bottom:6px">Название должности</div>
        <input id="f_title" placeholder="Например: Бармен" list="titleHints" value="${esc(pTitle)}" />
        <div class="muted" style="margin-top:6px;font-size:12px">${esc(titleHint)}</div>
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Сотрудник</div>
        <select id="f_member">
          ${membersOptions}
        </select>
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Ставка</div>
        <input id="f_rate" inputmode="decimal" placeholder="0" value="${esc(rate)}" />
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Процент от продаж</div>
        <input id="f_percent" inputmode="decimal" placeholder="0" value="${esc(percent)}" />
      </div>
    </div>

    <div style="margin-top:10px">
      <label class="row" style="gap:10px; align-items:center; margin:6px 0">
        <input type="checkbox" id="f_can_reports" ${canReports ? "checked" : ""} />
        <span>Может заполнять отчёты</span>
      </label>
      <label class="row" style="gap:10px; align-items:center; margin:6px 0">
        <input type="checkbox" id="f_can_schedule" ${canSchedule ? "checked" : ""} />
        <span>Может редактировать график</span>
      </label>
    </div>

    <div class="row" style="gap:8px; margin-top:12px; flex-wrap:wrap">
      <button class="btn primary" id="btnSavePos">Сохранить</button>
      <button class="btn" id="btnCancelPos">Отмена</button>
      ${
        mode === "edit"
          ? `<button class="btn danger" id="btnDeletePos" style="margin-left:auto">Удалить</button>`
          : `<span class="muted" style="margin-left:auto">Можно создавать несколько сотрудников с одной должностью</span>`
      }
    </div>
  `;
}

function collectPayload() {
  const title = document.getElementById("f_title")?.value?.trim();
  const member = document.getElementById("f_member")?.value;
  const rateRaw = document.getElementById("f_rate")?.value;
  const percentRaw = document.getElementById("f_percent")?.value;
  const canReports = !!document.getElementById("f_can_reports")?.checked;
  const canSchedule = !!document.getElementById("f_can_schedule")?.checked;

  if (!title) throw new Error("Укажите название должности");
  if (!member) throw new Error("Выберите сотрудника");

  const rate = Number(String(rateRaw ?? "").replace(",", "."));
  const percent = Number(String(percentRaw ?? "").replace(",", "."));

  if (!Number.isFinite(rate)) throw new Error("Ставка должна быть числом");
  if (!Number.isFinite(percent)) throw new Error("Процент должен быть числом");

  return {
    title,
    member_user_id: Number(member),
    rate,
    percent,
    can_make_reports: canReports,
    can_edit_schedule: canSchedule,
  };
}

function openCreateModal() {
  openPosModal({
    title: "Создать должность",
    hint: "Можно создать одну должность (например, «Бармен») для нескольких сотрудников.",
    bodyHtml: renderPositionForm({ mode: "create", position: null }),
  });

  const sel = document.getElementById("f_member");
  if (sel && sel.options.length) sel.value = sel.options[0].value;

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
    const who = m ? memberLabel(m) : p.member_user_id ? `user_id=${p.member_user_id}` : "—";

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

    card.querySelector("[data-edit]").onclick = () => openEditModal(p);

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
  state.perms = await getMyVenuePermissions(state.venueId).catch(() => null);

  const m = await getVenueMembers(state.venueId);
  state.members = m?.members || m || [];

  const p = await getVenuePositions(state.venueId);
  state.positions = p?.positions || p || [];

  renderPositions();
}

async function main() {
  renderShell();
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

  setActiveVenueId(state.venueId);

  document.getElementById("back").onclick = (e) => {
    e.preventDefault();
    location.href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;
  };

  document.getElementById("btnCreate").onclick = () => openCreateModal();

  try {
    await load();
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || e), "err");
    const list = document.getElementById("list");
    if (list) list.innerHTML = `<div class="muted">Ошибка загрузки: ${esc(e?.message || e)}</div>`;
  }
}

main();

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
} from "/app.js";

import { permSetFromResponse, roleUpper, hasPerm, isSysAdminRole, isOwnerRole } from "/permissions.js?v=20260321-miniappfix1";

const root = document.getElementById("root");
applyTelegramTheme();
await ensureLogin({ silent: true });

const DAYS = [
  { value: 0, title: "Понедельник", short: "Пн" },
  { value: 1, title: "Вторник", short: "Вт" },
  { value: 2, title: "Среда", short: "Ср" },
  { value: 3, title: "Четверг", short: "Чт" },
  { value: 4, title: "Пятница", short: "Пт" },
  { value: 5, title: "Суббота", short: "Сб" },
  { value: 6, title: "Воскресенье", short: "Вс" },
];

const APPLY_MODES = [
  {
    value: "SKIP_FILLED_DAYS",
    title: "Не трогать дни, где уже есть смены",
    hint: "Если в конкретный день месяца уже есть хотя бы одна смена, весь этот день будет пропущен.",
  },
  {
    value: "ADD_MISSING",
    title: "Добавить недостающие интервалы",
    hint: "Существующие смены останутся, а система добавит только отсутствующие интервалы из шаблона.",
  },
  {
    value: "REPLACE_MONTH",
    title: "Заменить смены месяца",
    hint: "Активные смены выбранного месяца будут отправлены в архив, затем месяц заполнится по шаблону.",
    danger: true,
  },
];

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

function pad2(n) { return String(n).padStart(2, "0"); }
function currentMonthValue() {
  const d = new Date();
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

function monthTitle(value) {
  const raw = String(value || "");
  const [y, m] = raw.split("-").map((x) => Number(x));
  if (!Number.isInteger(y) || !Number.isInteger(m)) return raw || "месяц";
  try {
    return new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric" }).format(new Date(y, m - 1, 1));
  } catch {
    return raw;
  }
}

function canManageTemplates({ me, perms }) {
  const pset = permSetFromResponse(perms);
  const venueRole = roleUpper(perms);
  const sysRole = String(me?.system_role || "").toUpperCase();
  return isOwnerRole(venueRole) || isSysAdminRole(sysRole) || hasPerm(pset, "SHIFTS_MANAGE");
}

const state = {
  venueId: parseVenueId(),
  me: null,
  perms: null,
  canManage: false,
  includeArchived: false,
  templates: [],
  intervals: [],
  applyTemplate: null,
};

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b>Шаблоны графика</b>
          <div class="muted">недельный шаблон смен и заполнение месяца</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="muted">Настрой дни недели один раз, а затем применяй шаблон к нужному месяцу. Перед генерацией система спросит, что делать с уже созданными сменами.</div>

      <div class="itemcard" style="margin-top:12px">
        <div class="section-head">
          <div class="section-title">
            <b>Сохранённые шаблоны</b>
            <div class="muted" style="margin-top:4px">Например: «Обычный месяц», «Выходные усиленные», «24/7».</div>
          </div>
          <div class="section-actions">
            <button class="btn primary" id="btnCreateTemplate">+ Новый шаблон</button>
          </div>
        </div>
        <div class="section-actions" style="margin-top:8px">
          <label class="chk">
            <input type="checkbox" id="showArchived" />
            <span class="muted">Показывать архив</span>
          </label>
        </div>
        <div id="templateList" style="margin-top:10px"><div class="skeleton"></div><div class="skeleton"></div></div>
      </div>

      <div class="row" style="margin-top:12px; gap:10px; flex-wrap:wrap">
        <a class="btn subtle inline" id="backToIntervals" href="#">← Интервалы смен</a>
        <a class="btn subtle inline" id="backToShifts" href="#">К графику</a>
        <a class="btn subtle inline" id="backToVenue" href="#">К заведению</a>
      </div>
    </div>

    <div id="toast" class="toast"><div class="toast__text"></div></div>

    <div id="modal" class="modal" style="z-index:10050">
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
      <div class="modal__backdrop" data-close-edit></div>
      <div class="modal__panel" style="max-width:900px">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="editTitle">Шаблон</b>
            <div class="muted" id="editHint" style="margin-top:4px; font-size:12px"></div>
          </div>
          <button class="btn" data-close-edit>Закрыть</button>
        </div>
        <div class="modal__body" id="editBody"></div>
      </div>
    </div>

    <div id="applyModal" class="modal">
      <div class="modal__backdrop" data-close-apply></div>
      <div class="modal__panel" style="max-width:760px">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="applyTitle">Применить шаблон</b>
            <div class="muted" id="applyHint" style="margin-top:4px; font-size:12px"></div>
          </div>
          <button class="btn" data-close-apply>Закрыть</button>
        </div>
        <div class="modal__body" id="applyBody"></div>
      </div>
    </div>

    <div class="nav"><div class="wrap"><div id="nav"></div></div></div>
  `;

  mountCommonUI("none");
}

function closeEditModal() {
  document.getElementById("editModal")?.classList.remove("open");
}
function closeApplyModal() {
  document.getElementById("applyModal")?.classList.remove("open");
  state.applyTemplate = null;
}
function wireModalClose() {
  document.querySelectorAll("[data-close-edit]").forEach((x) => x.addEventListener("click", closeEditModal));
  document.querySelectorAll("[data-close-apply]").forEach((x) => x.addEventListener("click", closeApplyModal));
}

function intervalLabel(interval) {
  return `${interval?.title || "Интервал"} · ${interval?.start_time || "??:??"}–${interval?.end_time || "??:??"}`;
}

function templateGroups(template) {
  const groups = new Map(DAYS.map((d) => [d.value, []]));
  for (const item of template?.items || []) {
    const interval = item?.interval;
    if (!groups.has(Number(item.weekday))) groups.set(Number(item.weekday), []);
    groups.get(Number(item.weekday)).push(interval ? intervalLabel(interval) : `Интервал #${item.interval_id}`);
  }
  return groups;
}

function templateSummaryHtml(template) {
  const groups = templateGroups(template);
  const rows = [];
  for (const d of DAYS) {
    const values = groups.get(d.value) || [];
    if (!values.length) continue;
    rows.push(`<div><b>${esc(d.short)}:</b> ${values.map(esc).join(", ")}</div>`);
  }
  return rows.length ? rows.join("") : `<div class="muted">В шаблоне пока нет интервалов</div>`;
}

function renderTemplates() {
  const el = document.getElementById("templateList");
  if (!el) return;

  if (!state.canManage) {
    el.innerHTML = `<div class="muted">Нет доступа к управлению шаблонами графика</div>`;
    return;
  }

  if (!state.templates.length) {
    el.innerHTML = `<div class="muted">Шаблонов пока нет. Создай первый недельный шаблон и примени его к месяцу.</div>`;
    return;
  }

  el.innerHTML = "";
  for (const item of state.templates) {
    const card = document.createElement("div");
    card.className = "listrow";
    card.style.alignItems = "flex-start";
    card.innerHTML = `
      <div class="listrow__left">
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap">
          <b>${esc(item.title)}</b>
          ${item.is_active ? "" : `<span class="badge">архив</span>`}
        </div>
        ${item.description ? `<div class="muted" style="margin-top:4px">${esc(item.description)}</div>` : ""}
        <div class="muted" style="margin-top:8px; display:grid; gap:4px">${templateSummaryHtml(item)}</div>
      </div>
      <div class="row row--nowrap" style="gap:8px; flex:0 0 auto; flex-wrap:wrap; justify-content:flex-end">
        <button class="btn sm primary" data-apply="${item.id}" ${item.is_active ? "" : "disabled"}>Применить к месяцу</button>
        <button class="btn sm" data-edit="${item.id}">Изменить</button>
        <button class="btn sm ${item.is_active ? "danger" : ""}" data-archive="${item.id}">${item.is_active ? "В архив" : "Вернуть"}</button>
        <button class="btn sm danger" data-delete="${item.id}">Удалить</button>
      </div>
    `;
    el.appendChild(card);
  }

  el.querySelectorAll("[data-apply]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = state.templates.find((x) => String(x.id) === String(btn.getAttribute("data-apply")));
      if (item) openApplyModal(item);
    });
  });

  el.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const item = state.templates.find((x) => String(x.id) === String(btn.getAttribute("data-edit")));
      if (item) openEditor({ mode: "edit", item });
    });
  });

  el.querySelectorAll("[data-archive]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const item = state.templates.find((x) => String(x.id) === String(btn.getAttribute("data-archive")));
      if (!item) return;
      const nextActive = !item.is_active;
      const ok = await confirmModal({
        title: nextActive ? "Вернуть шаблон?" : "Архивировать шаблон?",
        text: `${nextActive ? "Вернуть" : "Убрать в архив"} шаблон «${item.title}»? Уже созданные смены не изменятся.`,
        confirmText: nextActive ? "Вернуть" : "В архив",
        danger: !nextActive,
      });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-schedule-templates/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          body: { is_active: nextActive },
        });
        toast("Готово", "ok");
        await loadTemplates();
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось обновить шаблон", "err");
      }
    });
  });

  el.querySelectorAll("[data-delete]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const item = state.templates.find((x) => String(x.id) === String(btn.getAttribute("data-delete")));
      if (!item) return;
      const ok = await confirmModal({
        title: "Удалить шаблон?",
        text: `Шаблон «${item.title}» будет удалён. Уже созданные смены не изменятся.`,
        confirmText: "Удалить",
        danger: true,
      });
      if (!ok) return;
      try {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-schedule-templates/${encodeURIComponent(item.id)}`, { method: "DELETE" });
        toast("Шаблон удалён", "ok");
        await loadTemplates();
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось удалить шаблон", "err");
      }
    });
  });
}

function selectedKeysFromTemplate(template) {
  const keys = new Set();
  for (const item of template?.items || []) {
    keys.add(`${Number(item.weekday)}:${Number(item.interval_id)}:${String(item.shift_slot || "DAY").toUpperCase()}`);
  }
  return keys;
}

function editorHtml({ item }) {
  const selected = selectedKeysFromTemplate(item);
  const intervalRows = state.intervals.map((interval) => {
    const activeBadge = interval.is_active === false ? ` <span class="badge">архив</span>` : "";
    return { interval, activeBadge };
  });

  const daysHtml = DAYS.map((day) => `
    <div class="itemcard" style="margin-top:10px">
      <div class="section-title"><b>${esc(day.title)}</b></div>
      <div style="display:grid; gap:8px; margin-top:8px">
        ${intervalRows.length ? intervalRows.map(({ interval, activeBadge }) => {
          const key = `${day.value}:${Number(interval.id)}:DAY`;
          return `
            <label class="chk" style="align-items:flex-start">
              <input type="checkbox" data-template-item="1" data-weekday="${day.value}" data-interval-id="${esc(interval.id)}" ${selected.has(key) ? "checked" : ""} />
              <span class="muted">${esc(intervalLabel(interval))}${activeBadge}</span>
            </label>
          `;
        }).join("") : `<div class="muted">Сначала создай интервалы смен</div>`}
      </div>
    </div>
  `).join("");

  return `
    <div class="grid grid2" style="margin-top:10px">
      <div>
        <div class="muted" style="margin-bottom:6px">Название</div>
        <input id="tpl_title" class="input" placeholder="Например, Обычный месяц" value="${esc(item?.title || "")}" />
      </div>
      <div>
        <div class="muted" style="margin-bottom:6px">Отображение</div>
        <label class="chk">
          <input type="checkbox" id="tpl_active" ${item?.is_active === false ? "" : "checked"} />
          <span class="muted">Шаблон активен</span>
        </label>
      </div>
    </div>
    <div style="margin-top:10px">
      <div class="muted" style="margin-bottom:6px">Описание</div>
      <textarea id="tpl_description" class="input" rows="2" placeholder="Например, будни стандартные, выходные усиленные">${esc(item?.description || "")}</textarea>
    </div>
    <div class="muted" style="margin-top:12px">Выбери, какие интервалы нужно создавать в каждый день недели. Можно выбрать несколько интервалов на один день.</div>
    <div class="grid grid2" style="margin-top:2px">${daysHtml}</div>
    <div class="row" style="margin-top:12px; justify-content:flex-end; gap:8px">
      <button class="btn" id="btnCancelEdit">Отмена</button>
      <button class="btn primary" id="btnSaveTemplate">Сохранить шаблон</button>
    </div>
  `;
}

function collectEditorItems() {
  const items = [];
  document.querySelectorAll("[data-template-item]").forEach((input) => {
    if (!input.checked) return;
    const weekday = Number(input.getAttribute("data-weekday"));
    const intervalId = Number(input.getAttribute("data-interval-id"));
    if (!Number.isInteger(weekday) || weekday < 0 || weekday > 6) return;
    if (!Number.isInteger(intervalId) || intervalId <= 0) return;
    items.push({ weekday, interval_id: intervalId, shift_slot: "DAY" });
  });
  return items;
}

function openEditor({ mode, item = null }) {
  if (!state.intervals.length) {
    toast("Сначала создай хотя бы один интервал смен", "warn");
  }
  const isEdit = mode === "edit";
  document.getElementById("editTitle").textContent = isEdit ? "Редактирование шаблона" : "Новый шаблон графика";
  document.getElementById("editHint").textContent = "Шаблон хранит назначения интервалов на дни недели";
  document.getElementById("editBody").innerHTML = editorHtml({ item });
  document.getElementById("editModal")?.classList.add("open");

  document.getElementById("btnCancelEdit")?.addEventListener("click", closeEditModal);
  document.getElementById("btnSaveTemplate")?.addEventListener("click", async () => {
    const title = document.getElementById("tpl_title")?.value?.trim();
    const description = document.getElementById("tpl_description")?.value?.trim() || null;
    const is_active = !!document.getElementById("tpl_active")?.checked;
    const items = collectEditorItems();

    if (!title) return toast("Укажи название шаблона", "warn");
    if (!items.length) return toast("Выбери хотя бы один интервал в неделе", "warn");

    const body = { title, description, is_active, items };
    try {
      if (isEdit) {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-schedule-templates/${encodeURIComponent(item.id)}`, {
          method: "PATCH",
          body,
        });
        toast("Шаблон обновлён", "ok");
      } else {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-schedule-templates`, {
          method: "POST",
          body,
        });
        toast("Шаблон создан", "ok");
      }
      closeEditModal();
      await loadTemplates();
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось сохранить шаблон", "err");
    }
  });
}

function openApplyModal(template) {
  state.applyTemplate = template;
  const defaultMonth = currentMonthValue();
  document.getElementById("applyTitle").textContent = `Применить «${template.title}»`;
  document.getElementById("applyHint").textContent = "Выбери месяц и поведение для уже созданных смен";
  document.getElementById("applyBody").innerHTML = `
    <div>
      <div class="muted" style="margin-bottom:6px">Месяц заполнения</div>
      <input id="apply_month" class="input" type="month" value="${esc(defaultMonth)}" />
    </div>
    <div class="itemcard" style="margin-top:12px">
      <div class="section-title"><b>Что делать, если в месяце уже есть смены?</b></div>
      <div style="display:grid; gap:10px; margin-top:10px">
        ${APPLY_MODES.map((mode, idx) => `
          <label class="chk" style="align-items:flex-start">
            <input type="radio" name="apply_mode" value="${esc(mode.value)}" ${idx === 1 ? "checked" : ""} />
            <span>
              <span class="${mode.danger ? "text-danger" : ""}"><b>${esc(mode.title)}</b></span>
              <span class="muted" style="display:block; margin-top:3px">${esc(mode.hint)}</span>
            </span>
          </label>
        `).join("")}
      </div>
    </div>
    <div class="muted" id="applyMonthNote" style="margin-top:12px"></div>
    <div class="row" style="margin-top:12px; justify-content:flex-end; gap:8px">
      <button class="btn" id="btnCancelApply">Отмена</button>
      <button class="btn primary" id="btnRunApply">Применить к месяцу</button>
    </div>
  `;
  const monthInput = document.getElementById("apply_month");
  const note = document.getElementById("applyMonthNote");
  const syncNote = () => {
    if (note) note.textContent = `Будет заполнен месяц: ${monthTitle(monthInput?.value || defaultMonth)}.`;
  };
  monthInput?.addEventListener("change", syncNote);
  syncNote();

  document.getElementById("btnCancelApply")?.addEventListener("click", closeApplyModal);
  document.getElementById("btnRunApply")?.addEventListener("click", runApplyTemplate);
  document.getElementById("applyModal")?.classList.add("open");
}

async function runApplyTemplate() {
  const template = state.applyTemplate;
  if (!template) return;
  const month = document.getElementById("apply_month")?.value || currentMonthValue();
  const mode = document.querySelector('input[name="apply_mode"]:checked')?.value || "ADD_MISSING";
  const selectedMode = APPLY_MODES.find((x) => x.value === mode);

  if (!/^\d{4}-\d{2}$/.test(month)) return toast("Выбери месяц", "warn");

  const ok = await confirmModal({
    title: `Заполнить ${monthTitle(month)}?`,
    text: `Шаблон: «${template.title}». Режим: ${selectedMode?.title || mode}.`,
    confirmText: "Заполнить месяц",
    danger: mode === "REPLACE_MONTH",
  });
  if (!ok) return;

  try {
    const out = await api(`/venues/${encodeURIComponent(state.venueId)}/shift-schedule-templates/${encodeURIComponent(template.id)}/apply`, {
      method: "POST",
      body: { month, mode },
      timeoutMs: 30000,
    });
    closeApplyModal();
    const created = Number(out?.created_count || 0);
    const restored = Number(out?.restored_count || 0);
    const skipped = Number(out?.skipped_count || 0);
    const archived = Number(out?.archived_count || 0);
    toast(`Готово: создано ${created}, восстановлено ${restored}, пропущено ${skipped}${archived ? `, архивировано ${archived}` : ""}`, "ok");
  } catch (e) {
    toast(e?.data?.detail || e?.message || "Не удалось заполнить месяц", "err");
  }
}

async function loadIntervals() {
  const out = await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals?include_inactive=true`);
  state.intervals = normalizeList(out).sort((a, b) => `${a.start_time || ""}|${a.title || ""}`.localeCompare(`${b.start_time || ""}|${b.title || ""}`, "ru"));
}

async function loadTemplates() {
  const out = await api(`/venues/${encodeURIComponent(state.venueId)}/shift-schedule-templates?include_inactive=${state.includeArchived ? 1 : 0}`);
  state.templates = normalizeList(out);
  renderTemplates();
}

renderShell();
wireModalClose();

state.me = await getMe().catch(() => null);
state.perms = await getMyVenuePermissions(state.venueId).catch(() => null);
state.canManage = canManageTemplates({ me: state.me, perms: state.perms });

await mountNav({ activeTab: "shifts", requireVenue: true });

document.getElementById("backToIntervals")?.setAttribute("href", `/shift-intervals.html?venue_id=${encodeURIComponent(state.venueId)}`);
document.getElementById("backToShifts")?.setAttribute("href", `/staff-shifts.html?venue_id=${encodeURIComponent(state.venueId)}`);
document.getElementById("backToVenue")?.setAttribute("href", `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`);
document.getElementById("btnCreateTemplate")?.addEventListener("click", () => openEditor({ mode: "create" }));
document.getElementById("btnCreateTemplate")?.classList.toggle("hidden", !state.canManage);
document.getElementById("showArchived")?.addEventListener("change", async (e) => {
  state.includeArchived = !!e.target.checked;
  await loadTemplates();
});

if (!state.venueId) {
  toast("Сначала выбери заведение", "warn");
} else if (state.canManage) {
  await loadIntervals();
  await loadTemplates();
} else {
  renderTemplates();
}

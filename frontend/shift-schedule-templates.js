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
  getVenueSettings,
} from "/app.js?v=20260719-split1";

import { permSetFromResponse, roleUpper, hasPerm, isSysAdminRole, isOwnerRole } from "/permissions.js?v=20260321-miniappfix1";

const root = document.getElementById("root");
applyTelegramTheme();
await ensureLogin({ silent: true });

const DAYS = [
  { value: 0, title: "Понедельник", short: "Пн", from: "понедельника", to: "вторник", toShort: "Вт" },
  { value: 1, title: "Вторник", short: "Вт", from: "вторника", to: "среду", toShort: "Ср" },
  { value: 2, title: "Среда", short: "Ср", from: "среды", to: "четверг", toShort: "Чт" },
  { value: 3, title: "Четверг", short: "Чт", from: "четверга", to: "пятницу", toShort: "Пт" },
  { value: 4, title: "Пятница", short: "Пт", from: "пятницы", to: "субботу", toShort: "Сб" },
  { value: 5, title: "Суббота", short: "Сб", from: "субботы", to: "воскресенье", toShort: "Вс" },
  { value: 6, title: "Воскресенье", short: "Вс", from: "воскресенья", to: "понедельник", toShort: "Пн" },
];

function normalizeShiftSlot(value) {
  return String(value || "DAY").trim().toUpperCase() === "NIGHT" ? "NIGHT" : "DAY";
}
function dayByValue(value) {
  return DAYS.find((d) => Number(d.value) === Number(value)) || DAYS[0];
}
function scheduleSlotTitle(weekday, slot) {
  const day = dayByValue(weekday);
  return normalizeShiftSlot(slot) === "NIGHT" ? `Ночь с ${day.from} на ${day.to}` : day.title;
}
function scheduleSlotShortTitle(weekday, slot) {
  const day = dayByValue(weekday);
  return normalizeShiftSlot(slot) === "NIGHT" ? `Ночь ${day.short}→${day.toShort}` : day.short;
}
function editorSlots() {
  const rows = [];
  for (const day of DAYS) {
    rows.push({ weekday: day.value, shift_slot: "DAY", title: day.title, hint: "Дневной слот этого календарного дня" });
    if (state.nightShiftsEnabled) {
      rows.push({ weekday: day.value, shift_slot: "NIGHT", title: scheduleSlotTitle(day.value, "NIGHT"), hint: "Ночная смена хранится датой начала ночи" });
    }
  }
  return rows;
}

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
  nightShiftsEnabled: false,
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
      <div class="muted">Настрой дни недели один раз, а затем применяй шаблон к нужному месяцу. Если в заведении включены ночные смены, шаблон отдельно показывает день и ночь вида «Ночь с понедельника на вторник».</div>

      <div class="itemcard mt-12">
        <div class="section-head">
          <div class="section-title">
            <b>Сохранённые шаблоны</b>
            <div class="muted mt-4">Например: «Обычный месяц», «Выходные усиленные», «24/7».</div>
          </div>
          <div class="section-actions">
            <button class="btn primary" id="btnCreateTemplate">+ Новый шаблон</button>
          </div>
        </div>
        <div class="section-actions">
          <label class="chk">
            <input type="checkbox" id="showArchived" />
            <span class="muted">Показывать архив</span>
          </label>
        </div>
        <div class="mt-10" id="templateList"><div class="skeleton"></div><div class="skeleton"></div></div>
      </div>

      <div class="row mt-12">
        <a class="btn subtle inline" id="backToIntervals" href="#">← Интервалы смен</a>
        <a class="btn subtle inline" id="backToShifts" href="#">К графику</a>
        <a class="btn subtle inline" id="backToVenue" href="#">К заведению</a>
      </div>
    </div>

    <div id="toast" class="toast"><div class="toast__text"></div></div>

    <div id="modal" class="modal schedule-template-confirm-modal">
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
      <div class="modal__panel schedule-template-modal__panel--editor">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="editTitle">Шаблон</b>
            <div class="muted small mt-4" id="editHint"></div>
          </div>
          <button class="btn" data-close-edit>Закрыть</button>
        </div>
        <div class="modal__body" id="editBody"></div>
      </div>
    </div>

    <div id="applyModal" class="modal">
      <div class="modal__backdrop" data-close-apply></div>
      <div class="modal__panel schedule-template-modal__panel--apply">
        <div class="modal__head">
          <div>
            <b class="modal__title" id="applyTitle">Применить шаблон</b>
            <div class="muted small mt-4" id="applyHint"></div>
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
  const groups = new Map();
  for (const item of template?.items || []) {
    const weekday = Number(item.weekday);
    const slot = normalizeShiftSlot(item.shift_slot);
    const key = `${weekday}:${slot}`;
    const interval = item?.interval;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(interval ? intervalLabel(interval) : `Интервал #${item.interval_id}`);
  }
  return groups;
}

function templateSummaryHtml(template) {
  const groups = templateGroups(template);
  const rows = [];
  const ordered = [];
  for (const day of DAYS) {
    ordered.push({ weekday: day.value, shift_slot: "DAY" });
    ordered.push({ weekday: day.value, shift_slot: "NIGHT" });
  }
  for (const row of ordered) {
    const key = `${row.weekday}:${row.shift_slot}`;
    const values = groups.get(key) || [];
    if (!values.length) continue;
    rows.push(`<div><b>${esc(scheduleSlotShortTitle(row.weekday, row.shift_slot))}:</b> ${values.map(esc).join(", ")}</div>`);
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
    card.className = "listrow ai-start";
    card.innerHTML = `
      <div class="listrow__left">
        <div class="row gap-8">
          <b>${esc(item.title)}</b>
          ${item.is_active ? "" : `<span class="badge">архив</span>`}
        </div>
        ${item.description ? `<div class="muted mt-4">${esc(item.description)}</div>` : ""}
        <div class="muted template-summary">${templateSummaryHtml(item)}</div>
      </div>
      <div class="row gap-8 flex-none row--end">
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

  const daysHtml = editorSlots().map((slotRow) => `
    <div class="itemcard mt-10">
      <div class="section-title">
        <b>${esc(slotRow.title)}</b>
        ${slotRow.shift_slot === "NIGHT" ? `<span class="badge">ночь</span>` : ``}
      </div>
      <div class="muted small mt-4">${esc(slotRow.hint)}</div>
      <div class="template-options">
        ${intervalRows.length ? intervalRows.map(({ interval, activeBadge }) => {
          const key = `${slotRow.weekday}:${Number(interval.id)}:${slotRow.shift_slot}`;
          return `
            <label class="chk ai-start">
              <input type="checkbox" data-template-item="1" data-weekday="${slotRow.weekday}" data-shift-slot="${slotRow.shift_slot}" data-interval-id="${esc(interval.id)}" ${selected.has(key) ? "checked" : ""} />
              <span class="muted">${esc(intervalLabel(interval))}${activeBadge}</span>
            </label>
          `;
        }).join("") : `<div class="muted">Сначала создай интервалы смен</div>`}
      </div>
    </div>
  `).join("");

  return `
    <div class="grid grid2 mt-10">
      <div>
        <div class="muted mb-6">Название</div>
        <input id="tpl_title" class="input" placeholder="Например, Обычный месяц" value="${esc(item?.title || "")}" />
      </div>
      <div>
        <div class="muted mb-6">Отображение</div>
        <label class="chk">
          <input type="checkbox" id="tpl_active" ${item?.is_active === false ? "" : "checked"} />
          <span class="muted">Шаблон активен</span>
        </label>
      </div>
    </div>
    <div class="mt-10">
      <div class="muted mb-6">Описание</div>
      <textarea id="tpl_description" class="input" rows="2" placeholder="Например, будни стандартные, выходные усиленные">${esc(item?.description || "")}</textarea>
    </div>
    <div class="muted mt-12">Выбери, какие интервалы нужно создавать в каждый слот недели. Ночь «с понедельника на вторник» будет создана датой понедельника и слотом NIGHT.</div>
    <div class="grid grid2 schedule-template-days">${daysHtml}</div>
    <div class="row row--end gap-8 mt-12">
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
    const shiftSlot = normalizeShiftSlot(input.getAttribute("data-shift-slot") || "DAY");
    if (!Number.isInteger(weekday) || weekday < 0 || weekday > 6) return;
    if (!Number.isInteger(intervalId) || intervalId <= 0) return;
    if (shiftSlot === "NIGHT" && !state.nightShiftsEnabled) return;
    items.push({ weekday, interval_id: intervalId, shift_slot: shiftSlot });
  });
  return items;
}

function openEditor({ mode, item = null }) {
  if (!state.intervals.length) {
    toast("Сначала создай хотя бы один интервал смен", "warn");
  }
  const isEdit = mode === "edit";
  document.getElementById("editTitle").textContent = isEdit ? "Редактирование шаблона" : "Новый шаблон графика";
  document.getElementById("editHint").textContent = state.nightShiftsEnabled ? "Шаблон хранит дневные и ночные интервалы недели" : "Шаблон хранит назначения интервалов на дни недели";
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
      <div class="muted mb-6">Месяц заполнения</div>
      <input id="apply_month" class="input" type="month" value="${esc(defaultMonth)}" />
    </div>
    <div class="itemcard mt-12">
      <div class="section-title"><b>Что делать, если в месяце уже есть смены?</b></div>
      <div class="schedule-template-apply-options">
        ${APPLY_MODES.map((mode, idx) => `
          <label class="chk ai-start">
            <input type="radio" name="apply_mode" value="${esc(mode.value)}" ${idx === 1 ? "checked" : ""} />
            <span>
              <span class="${mode.danger ? "text-danger" : ""}"><b>${esc(mode.title)}</b></span>
              <span class="muted block schedule-template-option-hint">${esc(mode.hint)}</span>
            </span>
          </label>
        `).join("")}
      </div>
    </div>
    <div class="muted mt-12" id="applyMonthNote"></div>
    ${state.nightShiftsEnabled ? `<div class="itemcard mt-12"><b>Важно по ночам</b><div class="muted mt-6">Например, «Ночь с понедельника на вторник» будет создана на календарную дату понедельника в ночном слоте. В графике её видно при переключателе «Ночь».</div></div>` : ``}
    <div class="row row--end gap-8 mt-12">
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
try {
  const settings = state.venueId ? await getVenueSettings(state.venueId) : null;
  state.nightShiftsEnabled = !!settings?.night_shifts_enabled;
} catch {
  state.nightShiftsEnabled = false;
}
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

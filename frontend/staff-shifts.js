import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
  getVenuePositions,
} from "/app.js";

applyTelegramTheme();
mountCommonUI("shifts");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();

if (!venueId) toast("Сначала выбери заведение в «Настройках»", "warn");
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "shifts", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  grid: document.getElementById("calGrid"),
  dayPanel: document.getElementById("dayPanel"),
};

const mode = {
  box: document.getElementById("calendarMode"),
  all: document.getElementById("modeAll"),
  mine: document.getElementById("modeMine"),
};

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitleEl = document.getElementById("modalSubtitle");

function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);

function openModal(title, subtitle, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Смены";
  if (modalSubtitleEl) modalSubtitleEl.textContent = subtitle || "";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function toHHMM(timeStr) {
  if (!timeStr) return "";
  const s = String(timeStr);
  return s.slice(0, 5);
}

function shortNameOrLogin(u) {
  const first = (u?.first_name || "").trim();
  const last = (u?.last_name || "").trim();
  const name = (first + " " + last).trim();
  const login = (u?.tg_username || u?.username || "").trim();
  return name || (login ? "@" + login.replace(/^@/, "") : "Без имени");
}

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
function ymd(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }
const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

function dateOnly(d) {
  const x = new Date(d);
  x.setHours(0,0,0,0);
  return x;
}
function cmpDateStr(dateStr) {
  const today = dateOnly(new Date());
  const d = dateOnly(new Date(dateStr));
  if (d.getTime() === today.getTime()) return 0;
  return d.getTime() < today.getTime() ? -1 : 1;
}
function isPastDay(isoDate) {
  return cmpDateStr(isoDate) === -1;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function pickShortName(obj) {
  const sn = (obj?.short_name || obj?.member?.short_name || obj?.user?.short_name || "").trim();
  if (sn) return sn;
  const fn = (obj?.full_name || obj?.member?.full_name || obj?.user?.full_name || "").trim();
  if (fn) return fn.split(/\s+/)[0];
  const un = (obj?.tg_username || obj?.member_username || obj?.user_username || obj?.user?.tg_username || obj?.username || "").trim();
  if (un) return un.replace(/^@/, "");
  const uid = obj?.member_user_id ?? obj?.user_id ?? obj?.user?.id;
  return uid ? `user#${uid}` : "—";
}

function fioInitials(fullName) {
  const s = (fullName || "").trim();
  if (!s) return "";
  const p = s.split(/\s+/).filter(Boolean);
  if (p.length === 1) return p[0];
  const surname = p[0];
  const initials = p.slice(1).map(x => x[0] ? x[0].toUpperCase() + "." : "").join("");
  return `${surname} ${initials}`.trim();
}

function displayPerson(obj) {
  const fn = (obj?.full_name || obj?.member?.full_name || "").trim();
  const fi = fioInitials(fn);
  if (fi) return fi;
  const sn = (obj?.short_name || obj?.member?.short_name || "").trim();
  if (sn) return sn;
  const un = (obj?.tg_username || obj?.member?.tg_username || "").trim();
  if (un) return un.startsWith("@") ? un : `@${un}`;
  const uid = obj?.member_user_id ?? obj?.user_id ?? obj?.user?.id;
  return uid ? `user#${uid}` : "—";
}

function normalizeList(out) {
  if (!out) return [];
  if (Array.isArray(out)) return out;
  for (const k of ["items", "data", "results", "intervals", "positions", "shifts"]) {
    if (Array.isArray(out[k])) return out[k];
  }
  return [];
}

let me = null;
let perms = null;
let myRole = null;
let canEdit = false;

// позже сделаем отдельное право, сейчас привязка к can_make_reports
let canViewRevenue = false;

const LS_SHOW_ALL = "axelio.shifts.showAll";
let showAllOnCalendar = false;

let curMonth = new Date();
curMonth.setDate(1);

let intervals = [];
let positions = [];
let shifts = [];
let shiftsByDate = new Map();
let salaryByDate = new Map(); // dateISO -> total my_salary for the day (only when report exists)

function shiftIntervalTitle(s) {
  const i = s.interval || s.shift_interval || {};
  return i.title || s.interval_title || "Смена";
}
function shiftIntervalId(s) {
  return (s.interval?.id ?? s.shift_interval?.id ?? s.interval_id ?? s.intervalId ?? "x");
}
function shiftTimeLabel(s) {
  const i = s.interval || s.shift_interval || {};
  const st = i.start_time || s.start_time || "";
  const et = i.end_time || s.end_time || "";
  return (st && et) ? `${st}-${et}` : (st || "");
}
function shiftStartHHMM(s) {
  const i = s.interval || s.shift_interval || {};
  const st = i.start_time || s.start_time || s.start || s.time_start || "";
  return toHHMM(st);
}

// --- toggle ---
function renderModeToggle() {
  if (!mode.box) return;
  if (!canEdit) { mode.box.style.display = "none"; return; }
  mode.box.style.display = "inline-flex";

  const setActive = () => {
    mode.all?.classList.toggle("active", !!showAllOnCalendar);
    mode.mine?.classList.toggle("active", !showAllOnCalendar);
  };
  setActive();

  mode.all.onclick = () => {
    showAllOnCalendar = true;
    localStorage.setItem(LS_SHOW_ALL, "1");
    setActive();
    renderMonth();
  };
  mode.mine.onclick = () => {
    showAllOnCalendar = false;
    localStorage.setItem(LS_SHOW_ALL, "0");
    setActive();
    renderMonth();
  };
}

async function loadContext() {
  if (!venueId) return;

  me = await getMe().catch(() => null);
  perms = await getMyVenuePermissions(venueId).catch(() => null);

  myRole = perms?.role || perms?.venue_role || perms?.my_role || null;
  const flags = perms?.position_flags || {};
  const posObj = perms?.position || {};

  canEdit =
    myRole === "OWNER" ||
    myRole === "SUPER_ADMIN" ||
    !!flags.can_edit_schedule ||
    !!posObj.can_edit_schedule;

  canViewRevenue = !!flags.can_make_reports || !!posObj.can_make_reports;

  // default: editor sees all
  showAllOnCalendar = canEdit ? true : false;
  const saved = localStorage.getItem(LS_SHOW_ALL);
  if (saved !== null) showAllOnCalendar = saved === "1";

  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/shift-intervals`);
    intervals = normalizeList(out).filter(x => x && (x.is_active === undefined || x.is_active));
  } catch { intervals = []; }

  try {
    const out = await getVenuePositions(venueId);
    positions = normalizeList(out).filter(p => p && (p.is_active === undefined || p.is_active));
  } catch { positions = []; }
}

async function loadMonth() {
  if (!venueId) return;

  const m = ym(curMonth);
  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/shifts?month=${encodeURIComponent(m)}`);
    shifts = normalizeList(out);
  } catch (e) {
    shifts = [];
    toast(e?.message || "Не удалось загрузить смены", "err");
  }

  buildIndex();
  renderMonth();
  if (el.dayPanel) el.dayPanel.innerHTML = ""; // больше не используем
}

function buildIndex() {
  shiftsByDate = new Map();
  salaryByDate = new Map();

  for (const s of shifts) {
    const date = s.date || s.shift_date || s.day;
    if (!date) continue;

    if (!shiftsByDate.has(date)) shiftsByDate.set(date, []);
    shiftsByDate.get(date).push(s);

    // salaryByDate: суммируем только если my_salary есть (backend выдаёт только при наличии отчёта)
    const sal = Number(s.my_salary);
    if (Number.isFinite(sal)) {
      salaryByDate.set(date, (salaryByDate.get(date) || 0) + sal);
    }
  }

  for (const [d, arr] of shiftsByDate.entries()) {
    arr.sort((a, b) => {
      const at = (a.interval?.start_time || a.shift_interval?.start_time || a.start_time || "");
      const bt = (b.interval?.start_time || b.shift_interval?.start_time || b.start_time || "");
      return String(at).localeCompare(String(bt));
    });
  }
}

function monthTitle(d) {
  const dt = new Date(d);
  const month = dt.toLocaleString("ru-RU", { month: "long" });
  const year = dt.getFullYear();
  const s = `${month} ${year}`;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatDateRuNoG(iso) {
  const x = String(iso);
  const dt = new Date(x.length === 10 ? x + "T00:00:00" : x);
  const dd = String(dt.getDate()).padStart(2, "0");
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const yyyy = dt.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

function filterForCalendar(listAll, dateStr) {
  const myId = me?.id ?? null;

  // staff w/o edit -> only mine
  if (!canEdit && myId) {
    return listAll
      .map(s => {
        const assigns = (s.assignments || s.shift_assignments || []).filter(a => (a.member_user_id ?? a.user_id) === myId);
        if (!assigns.length) return null;
        return { ...s, assignments: assigns };
      })
      .filter(Boolean);
  }

  // editor toggle -> mine
  if (canEdit && !showAllOnCalendar && myId) {
    return listAll
      .map(s => {
        const assigns = (s.assignments || s.shift_assignments || []).filter(a => (a.member_user_id ?? a.user_id) === myId);
        if (!assigns.length) return null;
        return { ...s, assignments: assigns };
      })
      .filter(Boolean);
  }

  return listAll;
}

// Формат строки для ALL-режима: "Имя/логин — HH:MM"
function formatAllModeLine(shift, assignment) {
  const who = assignment ? displayPerson(assignment) : pickShortName(shift);
  const t = shiftStartHHMM(shift);
  return t ? `${who} — ${t}` : `${who}`;
}

let expandedDate = null;
let expandWired = false;

function collapseExpanded() {
  if (!expandedDate) return;
  const prev = document.querySelector(`.cal-cell[data-date="${expandedDate}"]`);
  if (prev) {
    prev.classList.remove("is-expanded");
    prev.style.gridColumn = "";
    prev.style.gridRow = "";
  }
  expandedDate = null;
}

function expandCell(cell, dateISO) {
  collapseExpanded();
  expandedDate = dateISO;
  cell.classList.add("is-expanded");
  cell.style.gridColumn = "span 2";
  cell.style.gridRow = "span 2";
}

function wireGlobalCollapse() {
  if (expandWired) return;
  expandWired = true;

  document.addEventListener("click", (e) => {
    const inCell = e.target.closest?.(".cal-cell");
    const inModal = e.target.closest?.(".modal__panel");
    if (!inCell && !inModal) collapseExpanded();
  });
}

function renderMonth() {
  wireGlobalCollapse();

  el.monthLabel.textContent = monthTitle(curMonth);
  el.grid.innerHTML = "";

  const head = document.createElement("div");
  head.className = "cal-head";
  for (const wd of WEEKDAYS) {
    const c = document.createElement("div");
    c.className = "cal-hcell";
    c.textContent = wd;
    head.appendChild(c);
  }
  el.grid.appendChild(head);

  const body = document.createElement("div");
  body.className = "cal-body";

  const first = new Date(curMonth);
  const jsDow = first.getDay();
  const mondayBased = (jsDow + 6) % 7;
  const start = new Date(first);
  start.setDate(first.getDate() - mondayBased);

  const todayStr = ymd(new Date());

  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const inMonth = d.getMonth() === curMonth.getMonth();
    const dateStr = ymd(d);

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className =
      "cal-cell" +
      (inMonth ? "" : " cal-cell--out") +
      (dateStr === todayStr ? " cal-cell--today" : "");
    cell.setAttribute("data-date", dateStr);

    const top = document.createElement("div");
    top.className = "cal-daynum";
    top.textContent = String(d.getDate());
    cell.appendChild(top);

    const box = document.createElement("div");
    box.className = "cal-badges";

    const listAll = shiftsByDate.get(dateStr) || [];
    const list = filterForCalendar(listAll, dateStr);

    // --- Режим MY: показываем либо зарплату (прошлое с отчётом), либо время начала (будущие)
    if (!showAllOnCalendar) {
      const past = isPastDay(dateStr);
      const daySalary = salaryByDate.get(dateStr);

      if (past && Number.isFinite(daySalary) && daySalary > 0) {
        const sal = document.createElement("div");
        sal.className = "day-salary";
        sal.textContent = `+${Math.round(daySalary)}`;
        box.appendChild(sal);
      } else {
        // будущее / сегодня: показать время начала первой моей смены
        const firstShift = list[0];
        const t = firstShift ? shiftStartHHMM(firstShift) : "";
        if (t) {
          const line = document.createElement("div");
          line.className = "cal-line";
          line.textContent = t;
          box.appendChild(line);
        }
      }
    } else {
      // --- Режим ALL: показываем строки "Имя/логин — HH:MM", без кружков
      const maxLines = 4;
      let lines = [];

      for (const s of list) {
        const assigns = (s.assignments || s.shift_assignments || []);
        if (assigns.length) {
          for (const a of assigns) {
            lines.push(formatAllModeLine(s, a));
            if (lines.length >= maxLines) break;
          }
        } else {
          lines.push(formatAllModeLine(s, null));
        }
        if (lines.length >= maxLines) break;
      }

      for (const t of lines) {
        const line = document.createElement("div");
        line.className = "cal-line";
        line.textContent = t;
        box.appendChild(line);
      }

      // подсчёт общего количества "строк", чтобы показать +ещё
      const totalLines = list.reduce((acc, s) => {
        const assigns = (s.assignments || s.shift_assignments || []);
        return acc + Math.max(1, assigns.length);
      }, 0);

      if (totalLines > maxLines) {
        const more = document.createElement("div");
        more.className = "cal-line muted";
        more.textContent = `+ ещё ${totalLines - maxLines}`;
        box.appendChild(more);
      }
    }

    cell.appendChild(box);

    // 1-й клик: expand, 2-й клик: modal
    cell.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();

      if (expandedDate !== dateStr) {
        expandCell(cell, dateStr);
        return;
      }

      collapseExpanded();
      openDay(dateStr);
    });

    body.appendChild(cell);
  }

  el.grid.appendChild(body);
}

function renderShiftCard(s, allowEdit) {
  const title = shiftIntervalTitle(s);
  const time = shiftTimeLabel(s).replace("-", "–");
  const shiftId = s.id;

  const assignments = s.assignments || s.shift_assignments || [];
  let peopleHtml = "";
  if (!assignments.length) {
    peopleHtml = `<div class="muted" style="margin-top:8px">Пока никто не назначен</div>`;
  } else {
    peopleHtml =
      `<div class="list" style="margin-top:8px">` +
      assignments.map((a) => {
        const label = displayPerson(a);
        const uname = (a.tg_username || a.member_username || "").trim();
        const unameTxt = uname ? (uname.startsWith("@") ? uname : "@"+uname) : "";
        return `
          <div class="list__row">
            <div class="list__main">
              <div><b>${escapeHtml(label)}</b>${unameTxt ? `<span class="muted"> · ${escapeHtml(unameTxt)}</span>` : ""}</div>
            </div>
            ${allowEdit ? `<button class="btn danger sm" data-unassign data-shift="${shiftId}" data-user="${a.member_user_id}">Удалить</button>` : ""}
          </div>
        `;
      }).join("") +
      `</div>`;
  }

  let editorHtml = "";
  if (allowEdit) {
    editorHtml = `
      <div class="row" style="margin-top:10px; gap:10px; flex-wrap:wrap">
        <select class="input" data-posselect data-shift="${shiftId}" style="flex:1; min-width:240px"></select>
        <button class="btn primary" data-assign data-shift="${shiftId}">Назначить</button>
      </div>
    `;
  }

  return `
    <div class="card" data-shiftcard="${shiftId}">
      <b>${escapeHtml(title)} ${time ? `<span class="muted">(${escapeHtml(time)})</span>` : ""}</b>
      ${peopleHtml}
      ${editorHtml}
    </div>
  `;
}

function wireShiftEditor(dateStr, shift, allowEdit) {
  if (!allowEdit) return;

  const shiftId = shift.id;
  const card = document.querySelector(`[data-shiftcard="${shiftId}"]`);
  if (!card) return;

  const sel = card.querySelector(`[data-posselect][data-shift="${shiftId}"]`);
  const btnAssign = card.querySelector(`[data-assign][data-shift="${shiftId}"]`);

  if (sel) {
    sel.innerHTML = "";
    if (!positions.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Нет должностей (создай в «Должности»)";
      sel.appendChild(opt);
      sel.disabled = true;
      if (btnAssign) btnAssign.disabled = true;
    } else {
      for (const p of positions) {
        const opt = document.createElement("option");
        opt.value = p.id;
        const mem = p.member || {};
        const name = fioInitials(mem.full_name) || mem.short_name || (mem.tg_username ? mem.tg_username.replace(/^@/, "") : "");
        opt.textContent = `${p.title} · ${name || "—"}`;
        sel.appendChild(opt);
      }
      sel.disabled = false;
      if (btnAssign) btnAssign.disabled = false;
    }
  }

  if (btnAssign) {
    btnAssign.onclick = async () => {
      const posId = Number(sel?.value || 0);
      if (!posId) return toast("Выбери должность", "warn");
      try {
        await api(`/venues/${encodeURIComponent(venueId)}/shifts/${encodeURIComponent(shiftId)}/assignments`, {
          method: "POST",
          body: { venue_position_id: posId },
        });
        toast("Назначено", "ok");
        await loadMonth();
        openDay(dateStr);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось назначить", "err");
      }
    };
  }

  card.querySelectorAll("[data-unassign]").forEach((btn) => {
    btn.onclick = async () => {
      const uid = btn.getAttribute("data-user");
      if (!uid) return;
      try {
        await api(`/venues/${encodeURIComponent(venueId)}/shifts/${encodeURIComponent(shiftId)}/assignments/${encodeURIComponent(uid)}`, {
          method: "DELETE",
        });
        toast("Удалено", "ok");
        await loadMonth();
        openDay(dateStr);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось удалить", "err");
      }
    };
  });
}

function canEditDay(dateStr) {
  if (!canEdit) return false;
  if (myRole === "OWNER" || myRole === "SUPER_ADMIN") return true;
  // прошедшие дни — только owner/superadmin
  return !isPastDay(dateStr);
}

function openDay(dateStr) {
  const listAll = shiftsByDate.get(dateStr) || [];
  const list = listAll; // в модалке показываем всех

  const allowEdit = canEditDay(dateStr);

  const title = formatDateRuNoG(dateStr);
  const subtitle = allowEdit ? "Редактирование" : "Просмотр";

  let html = `
    <div class="row" style="justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
      <div>
        <div class="muted" style="margin-top:4px">${allowEdit ? "Можно редактировать график" : "Просмотр графика"}</div>
        ${(!allowEdit && canEdit && isPastDay(dateStr)) ? `<div class="muted" style="margin-top:4px">Прошедшие дни может редактировать только владелец</div>` : ``}
      </div>
      ${allowEdit ? `<button class="btn primary" id="btnAddShift">+ Добавить смену</button>` : ``}
    </div>
  `;

  if (!list.length) {
    html += `<div class="card" style="margin-top:12px"><div class="muted">На этот день смен нет</div></div>`;
  } else {
    html += `<div class="stack" style="margin-top:12px">`;
    for (const s of list) html += renderShiftCard(s, allowEdit);
    html += `</div>`;
  }

  if (allowEdit) {
    html += `
      <div class="card" style="margin-top:12px; display:none" id="addShiftCard">
        <b>Новая смена</b>
        <div class="muted" style="margin-top:6px">Выбери промежуток и создай смену на этот день</div>

        <div class="row" style="margin-top:10px; gap:10px; flex-wrap:wrap">
          <select class="input" id="intervalSelect" style="flex:1; min-width:220px"></select>
          <button class="btn primary" id="createShiftBtn">Создать смену</button>
        </div>

        <div id="createIntervalBox" class="card" style="margin-top:10px; display:none; background: rgba(255,255,255,0.04)">
          <b>Новый промежуток</b>
          <div class="grid2" style="margin-top:10px">
            <input class="input" id="newIntTitle" placeholder="Название (например, Бар)" />
            <div class="row" style="margin-top:10px">
              <input class="input" id="newIntStart" placeholder="Начало (HH:MM)" />
              <input class="input" id="newIntEnd" placeholder="Конец (HH:MM)" />
            </div>
          </div>
          <div class="row" style="margin-top:10px; gap:10px; justify-content:flex-end">
            <button class="btn" id="cancelCreateInterval">Отмена</button>
            <button class="btn primary" id="createIntervalBtn">Создать промежуток</button>
          </div>
        </div>
      </div>
    `;
  }

  openModal(title, subtitle, html);

  if (!allowEdit) return;

  const btn = document.getElementById("btnAddShift");
  const card = document.getElementById("addShiftCard");
  const sel = document.getElementById("intervalSelect");
  const createBtn = document.getElementById("createShiftBtn");

  if (btn && card) {
    btn.onclick = () => {
      card.style.display = card.style.display === "none" ? "block" : "none";
    };
  }

  if (sel) {
    sel.innerHTML = "";

    for (const i of intervals) {
      const opt = document.createElement("option");
      opt.value = String(i.id);
      opt.textContent = `${i.title} · ${i.start_time}-${i.end_time}`;
      sel.appendChild(opt);
    }

    const optCreate = document.createElement("option");
    optCreate.value = "__create__";
    optCreate.textContent = "➕ Создать промежуток…";
    sel.appendChild(optCreate);

    if (!intervals.length) sel.value = "__create__";

    const box = document.getElementById("createIntervalBox");
    const btnCancel = document.getElementById("cancelCreateInterval");
    const btnCreateInt = document.getElementById("createIntervalBtn");

    const syncBox = () => {
      const isCreate = sel.value === "__create__";
      if (box) box.style.display = isCreate ? "block" : "none";
      if (createBtn) createBtn.disabled = isCreate;
    };

    sel.onchange = syncBox;
    syncBox();

    if (btnCancel) {
      btnCancel.onclick = () => {
        if (intervals.length) sel.value = String(intervals[0].id);
        syncBox();
      };
    }

    if (btnCreateInt) {
      btnCreateInt.onclick = async () => {
        const title = document.getElementById("newIntTitle")?.value?.trim();
        const start = document.getElementById("newIntStart")?.value?.trim();
        const end = document.getElementById("newIntEnd")?.value?.trim();

        if (!title) return toast("Укажи название", "warn");
        if (!/^\d{2}:\d{2}$/.test(start || "")) return toast("Начало в формате HH:MM", "warn");
        if (!/^\d{2}:\d{2}$/.test(end || "")) return toast("Конец в формате HH:MM", "warn");

        try {
          await api(`/venues/${encodeURIComponent(venueId)}/shift-intervals`, {
            method: "POST",
            body: { title, start_time: start, end_time: end }
          });
          toast("Промежуток создан", "ok");
          await loadContext();
          await loadMonth();
          openDay(dateStr);
        } catch (e) {
          toast(e?.data?.detail || e?.message || "Не удалось создать промежуток", "err");
        }
      };
    }
  }

  if (createBtn) {
    createBtn.onclick = async () => {
      const intervalId = document.getElementById("intervalSelect")?.value;
      if (!intervalId) return toast("Выбери промежуток", "warn");
      if (intervalId === "__create__") return toast("Сначала создай промежуток", "warn");

      try {
        await api(`/venues/${encodeURIComponent(venueId)}/shifts`, {
          method: "POST",
          body: { date: dateStr, interval_id: Number(intervalId) },
        });
        toast("Смена создана", "ok");
        await loadMonth();
        openDay(dateStr);
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось создать смену", "err");
      }
    };
  }

  for (const s of list) wireShiftEditor(dateStr, s, allowEdit);
}

// month navigation
el.prev.onclick = async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonth();
};
el.next.onclick = async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonth();
};

// boot
await loadContext();
renderModeToggle();
await loadMonth();

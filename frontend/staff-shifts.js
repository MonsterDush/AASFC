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

if (!venueId) {
  toast("Сначала выбери заведение в «Настройках»", "warn");
}
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "shifts", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  grid: document.getElementById("calGrid"),
  dayPanel: document.getElementById("dayPanel"),
};

function pad2(n) { return String(n).padStart(2, "0"); }
function ym(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`; }
function ymd(d) { return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`; }

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

let me = null;
let perms = null;
let canEdit = false;

let curMonth = new Date();
curMonth.setDate(1);

let intervals = [];
let positions = [];
let shifts = [];
let shiftsByDate = new Map();

function normalizeList(out) {
  if (!out) return [];
  if (Array.isArray(out)) return out;
  for (const k of ["items", "data", "results", "intervals", "positions", "shifts"]) {
    if (Array.isArray(out[k])) return out[k];
  }
  return [];
}

async function loadContext() {
  if (!venueId) return;

  me = await getMe().catch(() => null);
  perms = await getMyVenuePermissions(venueId).catch(() => null);

  const role = perms?.role || perms?.venue_role || perms?.my_role || null;
  const flags = perms?.position_flags || {};
  const posObj = perms?.position || {};

  canEdit =
    role === "OWNER" ||
    role === "SUPER_ADMIN" ||
    !!flags.can_edit_schedule ||
    !!posObj.can_edit_schedule;

  // intervals
  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/shift-intervals`);
    intervals = normalizeList(out).filter((x) => x && (x.is_active === undefined || x.is_active));
  } catch {
    intervals = [];
  }

  // positions (for assigning)
  try {
    const out = await getVenuePositions(venueId);
    positions = normalizeList(out).filter((p) => p && (p.is_active === undefined || p.is_active));
  } catch {
    positions = [];
  }
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
  clearDayPanel();
}

function buildIndex() {
  shiftsByDate = new Map();
  for (const s of shifts) {
    const date = s.date || s.shift_date || s.day;
    if (!date) continue;
    if (!shiftsByDate.has(date)) shiftsByDate.set(date, []);
    shiftsByDate.get(date).push(s);
  }

  for (const [d, arr] of shiftsByDate.entries()) {
    arr.sort((a, b) => {
      const ai = a.interval || a.shift_interval || {};
      const bi = b.interval || b.shift_interval || {};
      const at = ai.start_time || a.start_time || "";
      const bt = bi.start_time || b.start_time || "";
      return String(at).localeCompare(String(bt));
    });
  }
}

function monthTitle(d) {
  const m = d.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
  return m.charAt(0).toUpperCase() + m.slice(1);
}

function renderMonth() {
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
  const jsDow = first.getDay(); // 0 Sun
  const mondayBased = (jsDow + 6) % 7; // 0 Mon
  const start = new Date(first);
  start.setDate(first.getDate() - mondayBased);

  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const inMonth = d.getMonth() === curMonth.getMonth();
    const dateStr = ymd(d);

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell" + (inMonth ? "" : " cal-cell--out");
    cell.setAttribute("data-date", dateStr);

    const top = document.createElement("div");
    top.className = "cal-daynum";
    top.textContent = String(d.getDate());
    cell.appendChild(top);

    const list = shiftsByDate.get(dateStr) || [];
    const badges = document.createElement("div");
    badges.className = "cal-badges";

    const myId = me?.id ?? null;
    for (const s of list.slice(0, 3)) {
      const badge = document.createElement("div");
      badge.className = "badge";
      badge.textContent = shiftLabel(s);

      if (myId && isAssignedTo(s, myId)) badge.classList.add("badge--me");
      badges.appendChild(badge);
    }
    if (list.length > 3) {
      const more = document.createElement("div");
      more.className = "badge badge--more";
      more.textContent = `+${list.length - 3}`;
      badges.appendChild(more);
    }

    cell.appendChild(badges);
    cell.onclick = () => openDay(dateStr);
    body.appendChild(cell);
  }

  el.grid.appendChild(body);
}

function shiftLabel(s) {
  const i = s.interval || s.shift_interval || {};
  const title = i.title || s.interval_title || "Смена";
  const st = i.start_time || s.start_time || "";
  const et = i.end_time || s.end_time || "";
  const time = st && et ? `${st}-${et}` : (st || "");
  return time ? `${title} ${time}` : title;
}

function isAssignedTo(s, userId) {
  const arr = s.assignments || s.shift_assignments || s.members || [];
  for (const a of arr) {
    const uid = a.member_user_id ?? a.user_id ?? a.user?.id;
    if (uid === userId) return true;
  }
  return false;
}

function clearDayPanel() {
  el.dayPanel.innerHTML = `<div class="muted">Выбери день в календаре</div>`;
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function renderShiftCard(s) {
  const i = s.interval || s.shift_interval || {};
  const title = i.title || "Смена";
  const st = i.start_time || s.start_time || "";
  const et = i.end_time || s.end_time || "";
  const time = (st && et) ? `${st}–${et}` : "";
  const shiftId = s.id;

  const assignments = s.assignments || s.shift_assignments || [];
  const people = assignments.map((a) => {
    const posTitle = a.position_title || a.title || a.position?.title || "";
    const uname = a.member_username || a.user_username || a.user?.tg_username || a.username || "";
    const uid = a.member_user_id ?? a.user_id ?? a.user?.id;
    const label = uname ? `@${uname}` : `user#${uid}`;
    return { uid, label, posTitle };
  });

  let peopleHtml = "";
  if (!people.length) {
    peopleHtml = `<div class="muted" style="margin-top:8px">Пока никто не назначен</div>`;
  } else {
    peopleHtml =
      `<div class="list" style="margin-top:8px">` +
      people.map((p) => `
        <div class="list__row">
          <div class="list__main">
            <div><b>${escapeHtml(p.label)}</b>${p.posTitle ? `<span class="muted"> · ${escapeHtml(p.posTitle)}</span>` : ""}</div>
          </div>
          ${canEdit ? `<button class="btn danger sm" data-unassign data-shift="${shiftId}" data-user="${p.uid}">Удалить</button>` : ""}
        </div>
      `).join("") +
      `</div>`;
  }

  let editorHtml = "";
  if (canEdit) {
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

function wireShiftEditor(dateStr, shift) {
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
        const memberId = p.member_user_id ?? p.user_id;
        const name = p.member_username ? `@${p.member_username}` : (memberId ? `user#${memberId}` : "");
        opt.textContent = `${p.title} · ${name} · ставка ${p.rate}, % ${p.percent}`;
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

function openDay(dateStr) {
  const list = shiftsByDate.get(dateStr) || [];
  const title = new Date(dateStr).toLocaleDateString("ru-RU", {
    weekday: "long", day: "2-digit", month: "long", year: "numeric"
  });

  let html = `
    <div class="row" style="justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap">
      <div>
        <b>${title.charAt(0).toUpperCase() + title.slice(1)}</b>
        <div class="muted" style="margin-top:4px">${canEdit ? "Можно редактировать график" : "Просмотр графика"}</div>
      </div>
      ${canEdit ? `<button class="btn primary" id="btnAddShift">+ Добавить смену</button>` : ``}
    </div>
  `;

  if (!list.length) {
    html += `<div class="card" style="margin-top:12px"><div class="muted">На этот день смен нет</div></div>`;
  } else {
    html += `<div class="stack" style="margin-top:12px">`;
    for (const s of list) html += renderShiftCard(s);
    html += `</div>`;
  }

  if (canEdit) {
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
                <input class="input" id="newIntTitle" placeholder="Название (например, День)" />
                <div class="row" style="gap:10px">
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

  el.dayPanel.innerHTML = html;

  if (canEdit) {
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

  // 1) Обычные интервалы
  for (const i of intervals) {
    const opt = document.createElement("option");
    opt.value = String(i.id);
    opt.textContent = `${i.title} · ${i.start_time}-${i.end_time}`;
    sel.appendChild(opt);
  }

  // 2) Пункт "Создать"
  const optCreate = document.createElement("option");
  optCreate.value = "__create__";
  optCreate.textContent = "➕ Создать промежуток…";
  sel.appendChild(optCreate);

  // Если интервалов нет — сразу открываем создание
  if (!intervals.length) {
    sel.value = "__create__";
  }

  const box = document.getElementById("createIntervalBox");
  const btnCancel = document.getElementById("cancelCreateInterval");
  const btnCreateInt = document.getElementById("createIntervalBtn");

  const syncBox = () => {
    const isCreate = sel.value === "__create__";
    if (box) box.style.display = isCreate ? "block" : "none";
    if (createBtn) createBtn.disabled = isCreate; // нельзя создать смену, пока в режиме создания интервала
  };

  sel.onchange = syncBox;
  syncBox();

  if (btnCancel) {
    btnCancel.onclick = () => {
      // вернёмся на первый интервал, если есть
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
            await loadContext();  // перезагрузит intervals
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

    for (const s of list) wireShiftEditor(dateStr, s);
  }
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
await loadMonth();
clearDayPanel();

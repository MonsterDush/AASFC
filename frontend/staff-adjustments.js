import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
} from "/app.js";

applyTelegramTheme();
mountCommonUI("adjustments");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "adjustments", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  typeSel: document.getElementById("typeSel"),
  grid: document.getElementById("calGrid"),
  dayPanel: document.getElementById("dayPanel"),
};

function esc(s){
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function ymd(d) {
  const dt = new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}
function ym(d) {
  const dt = new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}
function monthTitle(d) {
  const dt = new Date(d);
  const m = dt.toLocaleString("ru-RU", { month: "long" });
  const y = dt.getFullYear();
  return `${m.charAt(0).toUpperCase()}${m.slice(1)} ${y}`;
}
function formatDateRu(iso) {
  const d = new Date(iso);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}

const WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"];

let curMonth = new Date();
curMonth.setDate(1);

// month cache
let dayAgg = new Map(); // dateISO -> { penalty_sum, writeoff_sum, items: [...] }

async function loadMonth() {
  dayAgg = new Map();
  if (!venueId) return;
  const m = ym(curMonth);
  const type = el.typeSel?.value || "";

  const list = await api(`/venues/${encodeURIComponent(venueId)}/adjustments?month=${encodeURIComponent(m)}&mine=1${type ? `&type=${encodeURIComponent(type)}` : ""}`);

  for (const it of (list?.items || [])) {
    const d = it.date;
    if (!dayAgg.has(d)) dayAgg.set(d, { penalty_sum: 0, writeoff_sum: 0, items: [] });
    const slot = dayAgg.get(d);
    slot.items.push(it);
    if (it.type === "penalty") slot.penalty_sum += Number(it.amount || 0);
    if (it.type === "writeoff") slot.writeoff_sum += Number(it.amount || 0);
  }
}

function renderMonth() {
  if (!el.grid || !el.monthLabel) return;

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
  const monthStr = ym(curMonth);

  for (let i = 0; i < 42; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i);
    const dStr = ymd(d);

    const agg = dayAgg.get(dStr);
    const pSum = agg ? agg.penalty_sum : 0;
    const wSum = agg ? agg.writeoff_sum : 0;

    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell";

    const sub = [];
    if (pSum) sub.push(`Штрафы: ${pSum}`);
    if (wSum) sub.push(`Списания: ${wSum}`);

    cell.innerHTML = `
      <div class="cal-num">${d.getDate()}</div>
      <div class="cal-sub muted" style="font-size:11px">${esc(sub.join(" · "))}</div>
    `;

    if (ym(d) !== monthStr) cell.classList.add("is-out");
    if (dStr === todayStr) cell.classList.add("is-today");
    if (agg && agg.items.length) cell.classList.add("has-report");

    cell.onclick = () => renderDay(dStr);
    body.appendChild(cell);
  }

  el.grid.appendChild(body);
}

function renderDay(dayISO) {
  const agg = dayAgg.get(dayISO);
  const items = agg?.items || [];

  el.dayPanel.innerHTML = "";

  const card = document.createElement("div");
  card.className = "card";
  card.innerHTML = `
    <b>${formatDateRu(dayISO)}</b>
    <div class="muted" style="margin-top:6px">Штрафы и списания за выбранный день</div>
  `;

  const list = document.createElement("div");
  list.style.marginTop = "10px";

  if (!items.length) {
    list.innerHTML = `<div class="muted">Записей нет</div>`;
  } else {
    for (const it of items) {
      const row = document.createElement("div");
      row.className = "row";
      row.style = "justify-content:space-between; border-bottom:1px solid var(--border); padding:10px 0; gap:10px;";
      const typeTitle = it.type === "penalty" ? "Штраф" : (it.type === "writeoff" ? "Списание" : it.type);
      row.innerHTML = `
        <div>
          <b>${esc(typeTitle)}</b> · <b>${esc(it.amount)}</b>
          <div class="muted" style="margin-top:4px">${esc(it.reason || "—")}</div>
        </div>
        <button class="btn" data-open>Открыть</button>
      `;

      row.querySelector("[data-open]").onclick = () => openItem(it);
      list.appendChild(row);
    }
  }

  card.appendChild(list);
  el.dayPanel.appendChild(card);
}

function modalElements() {
  const modal = document.getElementById("modal");
  const body = modal?.querySelector(".modal__body");
  const title = modal?.querySelector(".modal__title");
  const subtitle = document.getElementById("modalSubtitle");
  function close() { modal?.classList.remove("open"); }
  modal?.querySelector("[data-close]")?.addEventListener("click", close);
  modal?.querySelector(".modal__backdrop")?.addEventListener("click", close);
  function open(t, st, html) {
    if (title) title.textContent = t || "Деталка";
    if (subtitle) subtitle.textContent = st || "";
    if (body) body.innerHTML = html || "";
    modal?.classList.add("open");
  }
  return { open, close };
}

const modal = modalElements();

function openItem(it) {
  const typeTitle = it.type === "penalty" ? "Штраф" : (it.type === "writeoff" ? "Списание" : it.type);

  const html = `
    <div class="itemcard">
      <div class="row" style="justify-content:space-between; gap:10px; align-items:center">
        <div>
          <b>${esc(typeTitle)} · ${esc(it.amount)}</b>
          <div class="muted" style="margin-top:4px">Дата: <span class="mono">${esc(it.date)}</span></div>
        </div>
        <button class="btn" id="btnDispute">Оспорить</button>
      </div>

      <div class="muted" style="margin-top:10px">Причина</div>
      <div style="margin-top:6px">${esc(it.reason || "—")}</div>

      <div class="muted" style="margin-top:12px">Оспаривание</div>
      <textarea id="disputeText" rows="3" placeholder="Комментарий для владельца/менеджера..."></textarea>
      <div class="row" style="justify-content:flex-end; gap:8px; margin-top:10px">
        <button class="btn primary" id="btnSendDispute">Отправить</button>
      </div>
    </div>
  `;

  modal.open(typeTitle, "Детали и оспаривание", html);

  document.getElementById("btnDispute")?.addEventListener("click", () => {
    const ta = document.getElementById("disputeText");
    ta?.focus();
  });

  document.getElementById("btnSendDispute")?.addEventListener("click", async () => {
    const message = String(document.getElementById("disputeText")?.value || "").trim();
    if (!message) {
      toast("Напиши комментарий", "err");
      return;
    }
    try {
      await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(it.type)}/${encodeURIComponent(it.id)}/dispute`, {
        method: "POST",
        body: { message },
      });
      toast("Оспаривание отправлено", "ok");
      modal.close();
    } catch (e) {
      toast("Ошибка: " + (e?.message || "неизвестно"), "err");
    }
  });
}

async function boot() {
  if (!venueId) {
    el.grid.innerHTML = `<div class="itemcard"><b>Не выбрано заведение</b><div class="muted" style="margin-top:6px">Открой страницу с параметром <span class="mono">?venue_id=...</span>.</div></div>`;
    return;
  }

  try {
    await loadMonth();
    renderMonth();
    el.dayPanel.innerHTML = `<div class="muted" style="margin-top:8px">Выберите день в календаре.</div>`;
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || "неизвестно"), "err");
  }
}

el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await loadMonth();
  renderMonth();
});

el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await loadMonth();
  renderMonth();
});

el.typeSel?.addEventListener("change", async () => {
  await loadMonth();
  renderMonth();
});

boot();

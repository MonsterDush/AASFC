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
  list: document.getElementById("list"),
};

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
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

function typeTitle(t) {
  if (t === "penalty") return "Штраф";
  if (t === "writeoff") return "Списание";
  if (t === "bonus") return "Премия";
  return t || "—";
}

// modal (reuse markup from html)
const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitle = document.getElementById("modalSubtitle");
function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);
function openModal(title, subtitle, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "";
  if (modalSubtitle) modalSubtitle.textContent = subtitle || "";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

let curMonth = new Date();
curMonth.setDate(1);
const targetDay = params.get("date");
if (targetDay) {
  const d = new Date(targetDay);
  if (!isNaN(d)) { curMonth = new Date(d.getFullYear(), d.getMonth(), 1); }
}

async function loadList() {
  if (!venueId) return { items: [] };
  const m = ym(curMonth);
  const type = el.typeSel?.value || "";
  const qs = `month=${encodeURIComponent(m)}&mine=1${type ? `&type=${encodeURIComponent(type)}` : ""}`;
  return api(`/venues/${encodeURIComponent(venueId)}/adjustments?${qs}`);
}

function groupByDate(items) {
  const map = new Map();
  for (const it of items) {
    const d = it.date || "";
    if (!map.has(d)) map.set(d, []);
    map.get(d).push(it);
  }
  // dates are ISO so string sort works
  return Array.from(map.entries()).sort((a, b) => (a[0] < b[0] ? 1 : -1));
}

function renderList(data) {
  el.monthLabel.textContent = monthTitle(curMonth);

  const items = data?.items || [];
  if (!items.length) {
    el.list.innerHTML = `<div class="muted">Записей нет</div>`;
    return;
  }

  const groups = groupByDate(items);
  el.list.innerHTML = "";

  for (const [day, list] of groups) {
    const dayCard = document.createElement("div");
    dayCard.id = `day-${day}`;
    dayCard.className = "itemcard";
    dayCard.style.marginTop = "10px";

    const sum = list.reduce((acc, x) => acc + (Number(x.amount) || 0), 0);

    dayCard.innerHTML = `
      <div class="row" style="justify-content:space-between; gap:10px; align-items:flex-start">
        <div>
          <b>${esc(day)}</b>
          <div class="muted" style="margin-top:4px">${esc(list.length)} шт. · сумма ${esc(sum)}</div>
        </div>
      </div>
      <div style="margin-top:10px" data-items></div>
    `;

    const wrap = dayCard.querySelector("[data-items]");
    for (const it of list) {
      const row = document.createElement("div");
      row.className = "row";
      row.style = "justify-content:space-between; border-top:1px solid var(--border); padding:10px 0; gap:10px;";

      row.innerHTML = `
        <div>
          <b>${esc(typeTitle(it.type))} · ${esc(it.amount)}</b>
          <div class="muted" style="margin-top:4px">${esc(it.reason || "—")}</div>
        </div>
        <button class="btn" data-open>Открыть</button>
      `;

      row.querySelector("[data-open]").onclick = () => openItem(it);
      wrap.appendChild(row);
    }

    el.list.appendChild(dayCard);
  }
}

function buildItemHtml(it) {
  return `
    <div class="itemcard" style="margin-top:12px">
      <b>${esc(typeTitle(it.type))} · ${esc(it.amount)}</b>
      <div class="muted" style="margin-top:6px">Дата: ${esc(it.date)}</div>
      <div class="muted" style="margin-top:6px">Причина: ${esc(it.reason || "—")}</div>
      <div class="muted" style="font-size:12px;margin-bottom:4px">Оспорить</div>
      <div class="row" style="justify-content:flex-end; gap:8px; margin-top:12px">
        <textarea id="disputeMsg" rows="3" placeholder="Напиши комментарий"></textarea>
        <button class="btn primary" id="btnDispute">Отправить</button>
      </div>
      <div class="muted" style="margin-top:10px;font-size:12px">
        После отправки владелец/менеджер получит уведомление и сможет отредактировать или удалить запись.
      </div>
    </div>
  `;
}

function openItem(it) {
  openModal("Штраф / Списание / Премия", "Детали", buildItemHtml(it));

  document.getElementById("btnDispute")?.addEventListener("click", async () => {
    const message = String(document.getElementById("disputeMsg")?.value || "").trim();
    if (!message) {
      toast("Напиши комментарий", "err");
      return;
    }

    try {
      await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(it.type)}/${encodeURIComponent(it.id)}/dispute`, {
        method: "POST",
        body: { message },
      });
      toast("Отправлено", "ok");
      closeModal();
    } catch (e) {
      toast("Ошибка: " + (e?.message || "неизвестно"), "err");
    }
  });
}

async function boot() {
  if (!venueId) {
    el.list.innerHTML = `<div class="itemcard"><b>Не выбрано заведение</b><div class="muted" style="margin-top:6px">Открой страницу с параметром <span class="mono">?venue_id=...</span>.</div></div>`;
    return;
  }

  try {
    const data = await loadList();
    renderList(data);
  if (targetDay) {
    const elDay = document.getElementById(`day-${targetDay}`);
    if (elDay) elDay.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || "неизвестно"), "err");
    el.list.innerHTML = `<div class="muted">Не удалось загрузить данные</div>`;
  }
}

el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  const data = await loadList();
  renderList(data);
});

el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  const data = await loadList();
  renderList(data);
});

el.typeSel?.addEventListener("change", async () => {
  const data = await loadList();
  renderList(data);
});

boot();

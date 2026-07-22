import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getStoredDemoUiState,
  coerceDemoMonth,
} from "/app.js?v=20260722-dynamic1";

import { canManageAdjustments, hasReportAccess, permSetFromResponse, roleUpper } from "/permissions.js";

applyTelegramTheme();
mountCommonUI("adjustments");

await ensureLogin({ silent: true });

// Guard: if cookie auth is missing, stop page init (prevents silent crash on 401)
let __sysRole = "";
const __meOk = await (async () => {
  try {
    const me = await api("/me");
    __sysRole = String(me?.system_role || "").toUpperCase();
    return true;
  } catch (e) {
    if (e?.status === 401) {
      toast("Не удалось подтянуть авторизацию. Открой через Telegram Mini App и обнови страницу.", "warn");
      return false;
    }
    throw e;
  }
})();
if (!__meOk) {
  // Freeze further init safely
  await new Promise(() => {});
}


const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

// Adjustments now live under "Finance" in the bottom nav
let __tab = "adjustments";
try {
  const pr = await (venueId ? api(`/me/venues/${encodeURIComponent(venueId)}/permissions`) : null);
  const pset = permSetFromResponse(pr);
  const role = roleUpper(pr);
  const canViewReports = hasReportAccess(pset, role, __sysRole);
  if (canViewReports) __tab = "finance";
} catch {}
// Determine whether user has report access for this venue (affects navbar layout)
let __canReports = false;
try {
  const pr = await (venueId ? api(`/me/venues/${encodeURIComponent(venueId)}/permissions`) : null);
  const pset = permSetFromResponse(pr);
  const role = roleUpper(pr);
  __canReports = hasReportAccess(pset, role, __sysRole);
} catch {}
await mountNav({ activeTab: (__canReports ? "finance" : "adjustments") });


const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  typeSel: document.getElementById("typeSel"),
  btnAddAdj: document.getElementById("btnAddAdj"),
  list: document.getElementById("list"),
};

// Show "Добавить" button when user can manage adjustments
async function setupManageButton() {
  if (!venueId || !el.btnAddAdj) return;
  try {
    const pr = await api(`/me/venues/${encodeURIComponent(venueId)}/permissions`);
    const pset = permSetFromResponse(pr);
    const role = roleUpper(pr);
    const canManage = canManageAdjustments(pset, role, __sysRole);
    if (canManage) {
      el.btnAddAdj.classList.remove("hidden");
      el.btnAddAdj.addEventListener("click", () => {
        location.href = `/app-adjustments.html?venue_id=${encodeURIComponent(venueId)}`;
      });
    }
  } catch {}
}


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

const demoState = getStoredDemoUiState();
let curMonth = new Date();
curMonth.setDate(1);
const targetDay = params.get("date");
if (targetDay) {
  const d = new Date(targetDay);
  if (!isNaN(d)) { curMonth = new Date(d.getFullYear(), d.getMonth(), 1); }
} else {
  const demoMonth = coerceDemoMonth(ym(curMonth), { source: demoState, notify: false });
  const match = String(demoMonth || "").match(/^(\d{4})-(\d{2})$/);
  if (match) {
    curMonth = new Date(Number(match[1]), Number(match[2]) - 1, 1);
  }
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
    dayCard.className = "itemcard mt-10";

    const sum = list.reduce((acc, x) => acc + (Number(x.amount) || 0), 0);

    dayCard.innerHTML = `
      <div class="row row--between gap-10 ai-start">
        <div>
          <b>${esc(day)}</b>
          <div class="muted mt-4">${esc(list.length)} шт. · сумма ${esc(sum)}</div>
        </div>
      </div>
      <div class="mt-10" data-items></div>
    `;

    const wrap = dayCard.querySelector("[data-items]");
    for (const it of list) {
      const row = document.createElement("div");
      row.className = "row row--between gap-10 staff-adjustment-row";

      row.innerHTML = `
        <div>
          <b>${esc(typeTitle(it.type))} · ${esc(it.amount)}</b>
          <div class="muted mt-4">${esc(it.reason || "—")}</div>
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
    <div class="itemcard mt-12">
      <b>${esc(typeTitle(it.type))} · ${esc(it.amount)}</b>
      <div class="muted mt-6">Дата: ${esc(it.date)}</div>
      <div class="muted mt-6">Причина: ${esc(it.reason || "—")}</div>
      <div class="muted mt-6">Оспорить</div>
      <div class="row gap-8 mt-12">
        <textarea id="disputeMsg" rows="3" placeholder="Напиши комментарий"></textarea>
        <button class="btn primary" id="btnDispute">Отправить</button>
      </div>
      <div class="muted small mt-10">
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
    el.list.innerHTML = `<div class="itemcard"><b>Не выбрано заведение</b><div class="muted mt-6">Выбери заведение и открой раздел ещё раз.</div></div>`;
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

await setupManageButton();

boot();

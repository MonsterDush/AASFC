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
await mountNav({ activeTab: "adjustments" });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

const ui = {
  monthPrev: document.getElementById("monthPrev"),
  monthNext: document.getElementById("monthNext"),
  monthLabel: document.getElementById("monthLabel"),
  typeSel: document.getElementById("typeSel"),
  list: document.getElementById("itemsList"),
};

function esc(s){
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function ymFromDate(d) {
  const dt = new Date(d);
  const y = dt.getFullYear();
  const m = String(dt.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}
function addMonths(ym, delta) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1, 1);
  d.setMonth(d.getMonth() + delta);
  return ymFromDate(d);
}
function monthTitleRu(ym) {
  const [y, m] = ym.split("-").map(Number);
  const d = new Date(y, m - 1, 1);
  return d.toLocaleDateString("ru-RU", { month: "long", year: "numeric" });
}
function formatDateRu(iso) {
  const d = new Date(iso);
  const dd = String(d.getDate()).padStart(2, "0");
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const yyyy = d.getFullYear();
  return `${dd}.${mm}.${yyyy}`;
}
function money(v){
  const n = Number(v || 0);
  return new Intl.NumberFormat("ru-RU").format(n);
}

let state = {
  month: ymFromDate(new Date()),
  type: "", // penalty|writeoff|bonus|""
  items: [],
};

async function fetchItems() {
  const q = new URLSearchParams();
  q.set("month", state.month);
  q.set("mine", "1");
  if (state.type) q.set("type", state.type);
  return api(`/venues/${encodeURIComponent(venueId)}/adjustments?` + q.toString());
}

function render() {
  ui.monthLabel.textContent = monthTitleRu(state.month);

  if (!state.items.length) {
    ui.list.innerHTML = `<div class="card"><div class="muted">Нет записей за этот период</div></div>`;
    return;
  }

  // group by date
  const groups = new Map();
  for (const it of state.items) {
    const k = it.date;
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(it);
  }
  // sort dates desc
  const dates = Array.from(groups.keys()).sort((a,b)=> (a>b ? -1 : a<b ? 1 : 0));

  let html = "";
  for (const day of dates) {
    const list = groups.get(day) || [];
    const sumPenalty = list.filter(x=>x.type==="penalty").reduce((s,x)=>s+Number(x.amount||0),0);
    const sumWriteoff = list.filter(x=>x.type==="writeoff").reduce((s,x)=>s+Number(x.amount||0),0);
    const sumBonus = list.filter(x=>x.type==="bonus").reduce((s,x)=>s+Number(x.amount||0),0);

    const totals = [];
    if (!state.type || state.type==="penalty") if (sumPenalty) totals.push(`Штрафы: <b>${money(sumPenalty)}</b>`);
    if (!state.type || state.type==="writeoff") if (sumWriteoff) totals.push(`Списания: <b>${money(sumWriteoff)}</b>`);
    if (!state.type || state.type==="bonus") if (sumBonus) totals.push(`Премии: <b>${money(sumBonus)}</b>`);

    html += `
      <div class="card" style="margin-top:12px">
        <div class="row" style="justify-content:space-between; align-items:center">
          <b>${formatDateRu(day)}</b>
          <div class="muted" style="text-align:right">${totals.join(" · ") || ""}</div>
        </div>
        <div style="margin-top:10px">
          ${list.map(it => renderItem(it)).join("")}
        </div>
      </div>
    `;
  }
  ui.list.innerHTML = html;

  // bind click handlers
  ui.list.querySelectorAll("[data-open]").forEach(el => {
    el.addEventListener("click", () => openItem(el.getAttribute("data-open")));
  });
}

function typeBadge(t){
  if (t==="penalty") return `<span class="badge badge--red">Штраф</span>`;
  if (t==="writeoff") return `<span class="badge badge--gray">Списание</span>`;
  if (t==="bonus") return `<span class="badge badge--green">Премия</span>`;
  return "";
}

function renderItem(it){
  const who = it.member?.short_name || it.member?.full_name || it.member?.tg_username || (it.member_user_id ? `#${it.member_user_id}` : "—");
  const reason = it.reason ? esc(it.reason) : "<span class='muted'>без причины</span>";
  return `
    <div class="itemcard" style="margin-top:8px; cursor:pointer" data-open="${esc(it.type)}:${esc(it.id)}">
      <div class="row" style="justify-content:space-between; align-items:center; gap:10px">
        <div class="row" style="gap:8px; align-items:center">
          ${typeBadge(it.type)}
          <b>${money(it.amount)}</b>
          <span class="muted">${esc(who)}</span>
        </div>
        <span class="muted">Открыть</span>
      </div>
      <div style="margin-top:6px">${reason}</div>
    </div>
  `;
}

async function openItem(key) {
  const [type, id] = String(key).split(":");
  try {
    const it = await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(type)}/${encodeURIComponent(id)}`);
    showModal(it);
  } catch (e) {
    toast("Не удалось открыть: " + (e?.message || e), "err");
  }
}

function showModal(it){
  const modal = document.getElementById("modal");
  const body = modal.querySelector(".modal__body");
  const subtitle = document.getElementById("modalSubtitle");
  subtitle.textContent = `${formatDateRu(it.date)} · ${it.type}`;

  const who = it.member?.short_name || it.member?.full_name || it.member?.tg_username || (it.member_user_id ? `#${it.member_user_id}` : "—");
  body.innerHTML = `
    <div class="itemcard">
      <div class="row" style="justify-content:space-between; align-items:center">
        <div>${typeBadge(it.type)} <b style="margin-left:6px">${money(it.amount)}</b></div>
        <div class="muted">${esc(who)}</div>
      </div>
      <div style="margin-top:8px"><b>Причина:</b> ${it.reason ? esc(it.reason) : "<span class='muted'>—</span>"}</div>
    </div>

    <div class="itemcard" style="margin-top:12px">
      <b>Оспорить</b>
      <div class="muted" style="margin-top:6px">Комментарий уйдёт менеджеру/владельцу в Telegram.</div>
      <textarea id="disputeMsg" rows="4" style="width:100%; margin-top:8px" placeholder="Например: не согласен, потому что…"></textarea>
      <div class="row" style="justify-content:flex-end; gap:8px; margin-top:10px">
        <button class="btn" id="btnDispute">Отправить</button>
      </div>
    </div>
  `;

  body.querySelector("#btnDispute")?.addEventListener("click", async () => {
    const msg = String(body.querySelector("#disputeMsg")?.value || "").trim();
    if (!msg) {
      toast("Напиши комментарий", "warn");
      return;
    }
    try {
      await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(it.type)}/${encodeURIComponent(it.id)}/dispute`, {
        method: "POST",
        body: { message: msg },
      });
      toast("Отправлено", "ok");
      closeModal();
    } catch (e) {
      toast("Ошибка: " + (e?.message || e), "err");
    }
  });

  modal.classList.add("is-open");
}

function closeModal(){
  document.getElementById("modal")?.classList.remove("is-open");
}

document.querySelectorAll("[data-close]").forEach(el => el.addEventListener("click", closeModal));
document.querySelector("#modal .modal__backdrop")?.addEventListener("click", closeModal);

async function load() {
  if (!venueId) {
    ui.list.innerHTML = `<div class="card"><div class="muted">Выбери заведение</div></div>`;
    return;
  }
  ui.typeSel.value = state.type;
  try {
    const res = await fetchItems();
    state.items = Array.isArray(res?.items) ? res.items : [];
    render();
  } catch (e) {
    ui.list.innerHTML = `<div class="card"><div class="muted">Ошибка загрузки</div></div>`;
    toast("Ошибка: " + (e?.message || e), "err");
  }
}

ui.monthPrev?.addEventListener("click", async () => {
  state.month = addMonths(state.month, -1);
  await load();
});
ui.monthNext?.addEventListener("click", async () => {
  state.month = addMonths(state.month, 1);
  await load();
});
ui.typeSel?.addEventListener("change", async () => {
  state.type = ui.typeSel.value;
  await load();
});

await load();

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
  grid: document.getElementById("calGrid"),
  dayPanel: document.getElementById("dayPanel"),
  typeFilter: document.getElementById("typeFilter"),
};

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
function closeModal() { modal?.classList.remove("open"); }
modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);
modal?.querySelector(".modal__backdrop")?.addEventListener("click", closeModal);
function openModal(title, bodyHtml) {
  if (modalTitle) modalTitle.textContent = title || "Детали";
  if (modalBody) modalBody.innerHTML = bodyHtml || "";
  modal?.classList.add("open");
}

function esc(s){return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));}
function fmtMonthLabel(dt){
  const mm = String(dt.getMonth()+1).padStart(2,"0");
  return `${dt.getFullYear()}-${mm}`;
}
function fmtRu(iso){
  const d = new Date(String(iso).length===10? iso+"T00:00:00": iso);
  const dd=String(d.getDate()).padStart(2,"0");
  const mm=String(d.getMonth()+1).padStart(2,"0");
  const yy=d.getFullYear();
  return `${dd}.${mm}.${yy}`;
}
function formatMoney(n){
  const v=Math.round(Number(n)||0);
  return v.toLocaleString("ru-RU");
}

let curMonth = new Date();
curMonth.setDate(1);

let itemsByDate = new Map(); // date -> items[]

async function loadMonth() {
  if (!venueId) return;
  const m = fmtMonthLabel(curMonth);
  if (el.monthLabel) el.monthLabel.textContent = m;

  itemsByDate = new Map();
  el.grid.innerHTML = `<div class="muted">Загрузка…</div>`;
  el.dayPanel.innerHTML = ``;

  const type = (el.typeFilter?.value || "").trim();

  try {
    const out = await api(`/venues/${encodeURIComponent(venueId)}/adjustments?month=${encodeURIComponent(m)}&mine=1${type?`&type=${encodeURIComponent(type)}`:""}`);
    const items = out?.items || [];
    for (const it of items) {
      const d = it.date;
      const arr = itemsByDate.get(d) || [];
      arr.push(it);
      itemsByDate.set(d, arr);
    }
  } catch (e) {
    toast(e?.message || "Не удалось загрузить", "err");
  }

  renderCalendar();
}

function daysInMonth(dt){
  const y=dt.getFullYear(), m=dt.getMonth();
  return new Date(y,m+1,0).getDate();
}
function firstWeekday(dt){
  const y=dt.getFullYear(), m=dt.getMonth();
  const wd=new Date(y,m,1).getDay(); // 0 Sun
  return (wd+6)%7; // Mon=0
}

function renderCalendar(){
  const y=curMonth.getFullYear();
  const m=curMonth.getMonth();
  const total=daysInMonth(curMonth);
  const pad=firstWeekday(curMonth);

  const cells=[];
  for(let i=0;i<pad;i++) cells.push(null);
  for(let d=1; d<=total; d++){
    const iso = `${y}-${String(m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;
    cells.push({d, iso});
  }

  el.grid.innerHTML = "";
  for(const cell of cells){
    const box=document.createElement("div");
    box.className="cal__day";

    if(!cell){
      box.classList.add("cal__empty");
      el.grid.appendChild(box);
      continue;
    }
    const list = itemsByDate.get(cell.iso) || [];
    box.innerHTML = `<div class="cal__num">${cell.d}</div>`;

    if(list.length){
      const dotrow=document.createElement("div");
      dotrow.className="dotrow";
      const maxDots=6;
      for(const it of list.slice(0,maxDots)){
        const dot=document.createElement("div");
        dot.className="dot";
        dot.style.background = it.type==="bonus" ? "var(--ok)" : "var(--danger)";
        dotrow.appendChild(dot);
      }
      box.appendChild(dotrow);
    }

    box.addEventListener("click", ()=>renderDay(cell.iso));
    el.grid.appendChild(box);
  }
}

function renderDay(dayISO){
  const list = (itemsByDate.get(dayISO) || []).slice().sort((a,b)=> (a.type+a.id).localeCompare(b.type+b.id));
  if(!list.length){
    el.dayPanel.innerHTML = `<div class="card"><b>${esc(fmtRu(dayISO))}</b><div class="muted" style="margin-top:6px">Нет штрафов/премий/списаний</div></div>`;
    return;
  }

  const rows = list.map(it=>{
    const label = it.type==="penalty" ? "Штраф" : (it.type==="bonus" ? "Премия" : "Списание");
    const sign = it.type==="bonus" ? "+" : "-";
    return `<div class="itemcard" style="margin-top:10px">
      <div class="row" style="justify-content:space-between; gap:10px">
        <div><b>${label}</b>${it.reason?`<div class="muted" style="margin-top:4px">${esc(it.reason)}</div>`:""}</div>
        <div><b>${sign}${formatMoney(it.amount)}</b></div>
      </div>
      <div class="row" style="justify-content:space-between; gap:10px; margin-top:10px">
        <button class="btn" data-dispute="${it.type}:${it.id}">Оспорить</button>
        <button class="btn" data-open="${it.type}:${it.id}">Детали</button>
      </div>
    </div>`;
  }).join("");

  el.dayPanel.innerHTML = `<div class="card"><b>${esc(fmtRu(dayISO))}</b>${rows}</div>`;

  el.dayPanel.querySelectorAll("[data-open]").forEach(btn=>{
    btn.addEventListener("click", async ()=> {
      const [t,id]=String(btn.getAttribute("data-open")||"").split(":");
      await openDetails(t, Number(id));
    });
  });
  el.dayPanel.querySelectorAll("[data-dispute]").forEach(btn=>{
    btn.addEventListener("click", async ()=> {
      const [t,id]=String(btn.getAttribute("data-dispute")||"").split(":");
      await openDisputeForm(t, Number(id), dayISO);
    });
  });
}

async function openDetails(t, id){
  try{
    const out = await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(t)}/${encodeURIComponent(id)}`);
    openModal("Детали", `<pre style="white-space:pre-wrap">${esc(JSON.stringify(out,null,2))}</pre>`);
  }catch(e){
    toast(e?.message || "Не удалось открыть", "err");
  }
}

async function openDisputeForm(t, id, dayISO){
  openModal("Оспорить", `
    <div class="itemcard">
      <div class="muted" style="margin-bottom:6px">Сообщение</div>
      <textarea id="dispMsg" rows="4" placeholder="Опиши причину"></textarea>
      <div class="row" style="gap:10px; margin-top:10px">
        <button class="btn primary" id="dispSend">Отправить</button>
        <button class="btn" data-close>Закрыть</button>
      </div>
    </div>
  `);
  modal?.querySelector("[data-close]")?.addEventListener("click", closeModal);

  document.getElementById("dispSend")?.addEventListener("click", async ()=>{
    const msg = String(document.getElementById("dispMsg")?.value||"").trim();
    if(!msg){ toast("Нужно сообщение", "err"); return; }
    try{
      await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(t)}/${encodeURIComponent(id)}/dispute`, {
        method:"POST",
        body:{ message: msg },
      });
      toast("Отправлено");
      closeModal();
      await loadMonth();
      renderDay(dayISO);
    }catch(e){
      toast(e?.message || "Не удалось отправить", "err");
    }
  });
}

el.prev?.addEventListener("click", async ()=>{
  curMonth.setMonth(curMonth.getMonth()-1);
  curMonth.setDate(1);
  await loadMonth();
});
el.next?.addEventListener("click", async ()=>{
  curMonth.setMonth(curMonth.getMonth()+1);
  curMonth.setDate(1);
  await loadMonth();
});
el.typeFilter?.addEventListener("change", loadMonth);

await loadMonth();

import {
  applyTelegramTheme,
  ensureLogin,
  mountCommonUI,
  mountNav,
  toast,
  api,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenuePermissions,
} from "/app.js";

applyTelegramTheme();
mountCommonUI("adjustments_manage");

await ensureLogin({ silent: true });

const params = new URLSearchParams(location.search);
let venueId = params.get("venue_id") || getActiveVenueId();
if (venueId) setActiveVenueId(venueId);

await mountNav({ activeTab: "none", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  typeSel: document.getElementById("typeSel"),
  list: document.getElementById("list"),
  btnCreate: document.getElementById("btnCreate"),
};

function esc(s){
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

const modal = document.getElementById("modal");
const modalTitle = modal?.querySelector(".modal__title");
const modalBody = modal?.querySelector(".modal__body");
const modalSubtitle = document.getElementById("modalSubtitle");
function closeModal(){ modal?.classList.remove("open"); }
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
let perms = null;

function hasManageAccess() {
  const flags = perms?.position_flags || {};
  const codes = Array.isArray(perms?.permissions) ? perms.permissions : [];
  return (perms?.role === "OWNER") || flags.can_manage_adjustments === true || codes.includes("ADJUSTMENTS_MANAGE");
}

async function loadPerms() {
  perms = null;
  if (!venueId) return;
  try { perms = await getMyVenuePermissions(venueId); } catch { perms = null; }
}

async function loadList() {
  if (!venueId) return { items: [] };
  const m = ym(curMonth);
  const type = el.typeSel?.value || "";
  return api(`/venues/${encodeURIComponent(venueId)}/adjustments?month=${encodeURIComponent(m)}${type ? `&type=${encodeURIComponent(type)}` : ""}`);
}

function typeTitle(t) {
  if (t === "penalty") return "Штраф";
  if (t === "writeoff") return "Списание";
  if (t === "bonus") return "Премия";
  return t;
}

function renderList(data) {
  el.monthLabel.textContent = monthTitle(curMonth);

  if (!hasManageAccess()) {
    el.list.innerHTML = `
      <div class="itemcard">
        <b>Нет доступа</b>
        <div class="muted" style="margin-top:6px">Нужны права на управление штрафами/списаниями/премиями.</div>
      </div>
    `;
    el.btnCreate.style.display = "none";
    return;
  }

  el.btnCreate.style.display = "";

  const items = data?.items || [];
  if (!items.length) {
    el.list.innerHTML = `<div class="muted">Записей нет</div>`;
    return;
  }

  el.list.innerHTML = "";
  for (const it of items) {
    const row = document.createElement("div");
    row.className = "row";
    row.style = "justify-content:space-between; border-bottom:1px solid var(--border); padding:10px 0; gap:10px;";

    const who = it.member ? `@${it.member.tg_username || "-"}` : "(заведение)";

    row.innerHTML = `
      <div>
        <b>${esc(typeTitle(it.type))} · ${esc(it.amount)}</b>
        <div class="muted" style="margin-top:4px">${esc(it.date)} · ${esc(who)}</div>
        <div class="muted" style="margin-top:4px">${esc(it.reason || "—")}</div>
      </div>
      <button class="btn" data-edit>Открыть</button>
    `;

    row.querySelector("[data-edit]").onclick = () => {
      // пока просто показываем JSON + подсказку. В следующем шаге сделаем полноценную карточку+редактирование.
      const html = `
        <div class="itemcard">
          <b>${esc(typeTitle(it.type))}</b>
          <div class="muted" style="margin-top:6px">MVP карточка</div>
          <pre style="white-space:pre-wrap; margin-top:10px;">${esc(JSON.stringify(it, null, 2))}</pre>
        </div>
      `;
      openModal("Карточка", "Детали", html);
    };

    el.list.appendChild(row);
  }
}

async function loadMembers() {
  const res = await api(`/me/venues/${encodeURIComponent(venueId)}/members`);
  return res?.items || [];
}

function buildCreateForm(members) {
  const opts = members.map(m => `<option value="${esc(m.user_id)}">@${esc(m.tg_username || "-")}${m.full_name ? ` (${esc(m.full_name)})` : ""}</option>`).join("");

  return `
    <div class="itemcard">
      <div class="row" style="gap:10px;flex-wrap:wrap">
        <label style="min-width:220px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Тип</div>
          <select id="adjType">
            <option value="penalty">Штраф</option>
            <option value="writeoff">Списание</option>
            <option value="bonus">Премия</option>
          </select>
        </label>

        <label style="min-width:220px;display:block" id="memberWrap">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Сотрудник</div>
          <select id="adjMember">
            <option value="">(не выбран)</option>
            ${opts}
          </select>
          <div class="muted" style="font-size:12px;margin-top:6px" id="memberHint">Для штрафа/премии сотрудник обязателен. Для списания можно оставить пустым (списание по заведению).</div>
        </label>

        <label style="min-width:180px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Дата</div>
          <input id="adjDate" type="date" />
        </label>

        <label style="min-width:160px;display:block">
          <div class="muted" style="font-size:12px;margin-bottom:4px">Сумма</div>
          <input id="adjAmount" type="number" min="0" placeholder="0" />
        </label>
      </div>

      <div style="margin-top:10px">
        <div class="muted" style="font-size:12px;margin-bottom:4px">Причина</div>
        <textarea id="adjReason" rows="3" placeholder="Опиши причину"></textarea>
      </div>

      <div class="row" style="justify-content:flex-end; gap:8px; margin-top:12px">
        <button class="btn primary" id="btnCreateAdj">Создать</button>
      </div>
    </div>
  `;
}

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${dd}`;
}

async function openCreate() {
  const members = await loadMembers();
  openModal("Создать", "Штраф / Списание / Премия", buildCreateForm(members));

  const typeSel = document.getElementById("adjType");
  const memberSel = document.getElementById("adjMember");
  const dateInp = document.getElementById("adjDate");
  if (dateInp) dateInp.value = todayISO();

  function applyTypeHints() {
    const t = typeSel?.value;
    const hint = document.getElementById("memberHint");
    if (!hint) return;
    if (t === "writeoff") {
      hint.textContent = "Для списания можно оставить сотрудника пустым — это будет списание по заведению.";
    } else {
      hint.textContent = "Для штрафа/премии сотрудник обязателен.";
    }
  }

  typeSel?.addEventListener("change", applyTypeHints);
  applyTypeHints();

  document.getElementById("btnCreateAdj")?.addEventListener("click", async () => {
    const type = String(typeSel?.value || "");
    const date = String(dateInp?.value || "");
    const amount = Number(document.getElementById("adjAmount")?.value || 0);
    const reason = String(document.getElementById("adjReason")?.value || "").trim();
    const member_user_id_raw = String(memberSel?.value || "");
    const member_user_id = member_user_id_raw ? Number(member_user_id_raw) : null;

    if (!type || !date) {
      toast("Заполни тип и дату", "err");
      return;
    }
    if (!Number.isFinite(amount) || amount < 0) {
      toast("Проверь сумму", "err");
      return;
    }
    if ((type === "penalty" || type === "bonus") && !member_user_id) {
      toast("Выбери сотрудника", "err");
      return;
    }

    try {
      await api(`/venues/${encodeURIComponent(venueId)}/adjustments`, {
        method: "POST",
        body: { type, date, amount: Math.floor(amount), reason, member_user_id },
      });
      toast("Создано", "ok");
      closeModal();
      const data = await loadList();
      renderList(data);
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

  await loadPerms();

  try {
    const data = await loadList();
    renderList(data);
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || "неизвестно"), "err");
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

el.btnCreate?.addEventListener("click", openCreate);

boot();

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

function escapeHtml(s) {
  return String(s ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
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

let _openedFromQuery = false;
function maybeOpenFromQuery() {
  if (_openedFromQuery) return;
  const params = new URLSearchParams(location.search);
  const openId = params.get("open");
  if (!openId) return;
  const btn = document.querySelector(`[data-edit][data-id="${CSS.escape(openId)}"]`);
  if (btn) {
    _openedFromQuery = true;
    btn.click();
  }
}

let curMonth = new Date();
curMonth.setDate(1);
let perms = null;

function hasManageAccess() {
  const flags = perms?.position_flags || {};
  const codes = Array.isArray(perms?.permissions) ? perms.permissions : [];
  return (perms?.role === "OWNER") || (perms?.role === "SUPER_ADMIN") || flags.can_manage_adjustments === true || codes.includes("ADJUSTMENTS_MANAGE");
}

function hasResolveAccess() {
  const flags = perms?.position_flags || {};
  return (perms?.role === "OWNER") || (perms?.role === "SUPER_ADMIN") || flags.can_resolve_disputes === true;
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
      <button class="btn" data-edit data-id="${esc(it.id)}">Открыть</button>
    `;

    row.querySelector("[data-edit]").onclick = async () => {
      const members = await loadMembers().catch(() => []);
      const memberOpts = [
        `<option value="0">— (по заведению)</option>`,
        ...members.map((m) => `<option value="${esc(m.user_id)}">@${esc(m.tg_username || "-")}${m.full_name ? ` (${esc(m.full_name)})` : ""}</option>`),
      ].join("");

      const html = `
        <style>
          /* Admin adjustments modal: make the form readable on narrow screens */
          .adj-modal .adj-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
          .adj-modal label{display:block}
          .adj-modal select,.adj-modal input,.adj-modal textarea{width:100%}
          .adj-modal .adj-help{font-size:12px;margin-top:4px}
          .adj-modal .adj-actions{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;margin-top:12px}
          .adj-modal .adj-actions-right{display:flex;gap:8px;flex-wrap:wrap}
          .adj-modal .adj-card{margin-top:12px}
          .adj-modal .dispute-top{display:flex;justify-content:space-between;gap:10px;align-items:center;flex-wrap:wrap}
          .adj-modal .dispute-list .card{padding:10px}
          @media (max-width:520px){
            .adj-modal .adj-grid{grid-template-columns:1fr}
          }
        </style>

        <div class="adj-modal">
        <div class="itemcard adj-card">
          <div class="adj-grid">
            <label>Тип
              <select id="edType">
                <option value="penalty">Штраф</option>
                <option value="writeoff">Списание</option>
                <option value="bonus">Премия</option>
              </select>
            </label>
            <label>Дата
              <input id="edDate" type="date" />
            </label>
            <label>Сотрудник
              <select id="edMember">${memberOpts}</select>
              <div class="muted adj-help">Для “Списание” можно оставить “по заведению”.</div>
            </label>
            <label>Сумма
              <input id="edAmount" type="number" min="0" step="1" />
            </label>
          </div>

          <label style="display:block;margin-top:10px">Причина
            <textarea id="edReason" rows="3" placeholder="Причина"></textarea>
          </label>

          <div class="adj-actions">
            <button class="btn danger" id="btnAdjDelete">Удалить</button>
            <div class="adj-actions-right">
              <button class="btn" id="btnAdjClose">Закрыть</button>
              <button class="btn primary" id="btnAdjSave">Сохранить</button>
            </div>
          </div>
        </div>

        <div class="itemcard adj-card" id="disputeBox">
          <div class="dispute-top">
            <div>
              <b>Спор</b>
              <div class="muted" style="margin-top:4px" id="disputeStatus">Загрузка…</div>
            </div>
            <button class="btn" id="btnDisputeToggle">…</button>
          </div>

          <div id="disputeComments" class="dispute-list" style="margin-top:10px"></div>

          <div style="margin-top:10px">
            <textarea id="disputeReply" rows="3" placeholder="Ответить…" style="width:100%"></textarea>
            <div class="row" style="justify-content:flex-end; gap:8px; margin-top:8px">
              <button class="btn primary" id="btnDisputeSend">Отправить</button>
            </div>
          </div>
        </div>
        </div>
      `;
      
async function renderDisputeUI(venueId, adj) {
  const box = document.getElementById("disputeBox");
  if (!box) return;

  // Only show for managers/owners or when explicitly opened via ?tab=disputes
  const params = new URLSearchParams(location.search);
  const force = (params.get("tab") || "") === "disputes";
  if (!force && !hasManageAccess() && !hasResolveAccess()) {
    box.style.display = "none";
    return;
  }

  let data = await loadDisputeThread(venueId, adj);
  const statusEl = document.getElementById("disputeStatus");
  const listEl = document.getElementById("disputeComments");
  const btnSend = document.getElementById("btnDisputeSend");
  const btnToggle = document.getElementById("btnDisputeToggle");
  const ta = document.getElementById("disputeReply");

  function render() {
    const dis = data?.dispute;
    if (!dis) {
      if (statusEl) statusEl.textContent = "Спора нет (сотрудник ещё не оспаривал).";
      if (listEl) listEl.innerHTML = "";
      if (btnToggle) btnToggle.disabled = true;
      return;
    }
    if (statusEl) statusEl.textContent = `Статус: ${dis.status}`;
    if (btnToggle) {
      const can = hasResolveAccess();
      btnToggle.disabled = !can;
      btnToggle.textContent = dis.status === "OPEN" ? "Закрыть спор" : "Открыть спор";
    }
    if (listEl) {
      const items = Array.isArray(data.comments) ? data.comments : [];
      listEl.innerHTML = items.length
        ? items.map(c => `<div class="card" style="padding:10px"><div class="muted" style="font-size:12px">${(c.created_at||"").slice(0,19).replace("T"," ")}</div><div style="margin-top:6px;white-space:pre-wrap">${escapeHtml(c.message||"")}</div></div>`).join("")
        : `<div class="muted">Комментариев пока нет</div>`;
    }
  }

  render();

  if (force) {
    try { box.scrollIntoView({ behavior: "smooth", block: "start" }); } catch {}
  }

  btnSend?.addEventListener("click", async () => {
    const dis = data?.dispute;
    if (!dis) return toast("Спор ещё не создан сотрудником", "err");
    const msg = (ta?.value || "").trim();
    if (!msg) return toast("Введите сообщение", "err");
    try {
      await postDisputeComment(venueId, dis.id, msg);
      if (ta) ta.value = "";
      data = await loadDisputeThread(venueId, adj);
      render();
      toast("Отправлено", "ok");
    } catch (e) {
      toast("Не удалось отправить: " + (e?.data?.detail || e?.message || "ошибка"), "err");
    }
  });

  btnToggle?.addEventListener("click", async () => {
    const dis = data?.dispute;
    if (!dis) return;
    if (!hasResolveAccess()) return toast("Нет прав", "err");
    try {
      const next = dis.status === "OPEN" ? "CLOSED" : "OPEN";
      await setDisputeStatus(venueId, dis.id, next);
      data = await loadDisputeThread(venueId, adj);
      render();
      toast("Готово", "ok");
    } catch (e) {
      toast("Не удалось: " + (e?.data?.detail || e?.message || "ошибка"), "err");
    }
  });
}

openModal("Карточка", "Редактирование", html);
      renderDisputeUI(venueId, it);


      const edType = document.getElementById("edType");
      const edDate = document.getElementById("edDate");
      const edMember = document.getElementById("edMember");
      const edAmount = document.getElementById("edAmount");
      const edReason = document.getElementById("edReason");

      if (edType) edType.value = it.type || "penalty";
      if (edDate) edDate.value = (it.date || "").slice(0, 10);
      if (edAmount) edAmount.value = it.amount ?? 0;
      if (edReason) edReason.value = it.reason || "";

      // member: for penalty/bonus must be selected; for writeoff can be 0
      const curMember = it.member_user_id ? String(it.member_user_id) : "0";
      if (edMember) edMember.value = curMember;

      function applyTypeRules() {
        const t = edType?.value || "penalty";
        if (!edMember) return;
        if (t === "writeoff") {
          // allow 0
        } else {
          if (edMember.value === "0") {
            // pick first real member if exists
            const first = members.find((x) => x.user_id);
            if (first) edMember.value = String(first.user_id);
          }
        }
      }
      edType?.addEventListener("change", applyTypeRules);
      applyTypeRules();

      document.getElementById("btnAdjClose")?.addEventListener("click", closeModal);

      document.getElementById("btnAdjSave")?.addEventListener("click", async () => {
        try {
          const payload = {
            type: edType?.value,
            date: edDate?.value,
            amount: Number(edAmount?.value || 0),
            reason: edReason?.value || "",
            member_user_id: Number(edMember?.value || 0),
          };
          await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(it.id)}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
          });
          toast("Сохранено", "ok");
          closeModal();
          const data = await loadList();
          renderList(data);
          maybeOpenFromQuery();

        } catch (e) {
          toast("Не удалось сохранить: " + (e?.data?.detail || e?.message || "ошибка"), "err");
        }
      });

      document.getElementById("btnAdjDelete")?.addEventListener("click", async () => {
        if (!confirm("Удалить запись?")) return;
        try {
          await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(it.id)}`, { method: "DELETE" });
          toast("Удалено", "ok");
          closeModal();
          const data = await loadList();
          renderList(data);
          maybeOpenFromQuery();
        } catch (e) {
          toast("Не удалось удалить: " + (e?.data?.detail || e?.message || "ошибка"), "err");
        }
      });
    };

    el.list.appendChild(row);
  }

  // If we came from bot deep-link, open the requested item once list is on the page.
  maybeOpenFromQuery();
}

async function loadMembers() {
  // backend returns { venue_id, members: [...] }
  const res = await api(`/me/venues/${encodeURIComponent(venueId)}/members`);
  return res?.members || res?.items || [];
}

async function loadDisputeThread(venueId, adj) {
  try {
    return await api(`/venues/${encodeURIComponent(venueId)}/adjustments/${encodeURIComponent(adj.type)}/${encodeURIComponent(adj.id)}/dispute`);
  } catch (e) {
    return { dispute: null, comments: [] };
  }
}

async function postDisputeComment(venueId, disputeId, message) {
  return await api(`/venues/${encodeURIComponent(venueId)}/disputes/${encodeURIComponent(disputeId)}/comments`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}

async function setDisputeStatus(venueId, disputeId, status) {
  return await api(`/venues/${encodeURIComponent(venueId)}/disputes/${encodeURIComponent(disputeId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status }),
  });
}


function buildCreateForm(members) {
  const opts = members.map(m => `<option value="${esc(m.user_id)}">@${esc(m.tg_username || "-")}${m.full_name ? ` (${esc(m.full_name)})` : ""}</option>`).join("");

  return `
    <div class="itemcard" style="margin-top:12px;">
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

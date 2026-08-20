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
  getStoredDemoUiState,
  isDemoReadonlyUi,
  getDemoMonthLabel,
  coerceDemoMonth,
} from "/app.js?v=20260820-i18nmetrika1";


import { permSetFromResponse, roleUpper, hasPerm, hasAnyPerm } from "/permissions.js";
applyTelegramTheme();
mountCommonUI("adjustments_manage");

await ensureLogin({ silent: true });

let me = null;

// Guard: if cookie auth is missing, stop page init (prevents silent crash on 401)
const __meOk = await (async () => {
  try {
    me = await api("/me");
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

// Management adjustments screen is part of "Finance" navigation group
await mountNav({ activeTab: "finance", requireVenue: true });

const el = {
  monthLabel: document.getElementById("monthLabel"),
  prev: document.getElementById("monthPrev"),
  next: document.getElementById("monthNext"),
  typeSel: document.getElementById("typeSel"),
  list: document.getElementById("list"),
  btnCreate: document.getElementById("btnCreate"),
};

function personLabel(u) {
  if (!u) return "—";
  if (u.full_name) return u.full_name;
  if (u.short_name) return u.short_name;
  if (u.tg_username) return "@" + u.tg_username;
  return "#" + (u.id ?? "");
}

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
  const m = dt.toLocaleString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { month: "long" });
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
const demoState = getStoredDemoUiState();
const demoReadonly = isDemoReadonlyUi(demoState);
const demoMonth = coerceDemoMonth(ym(curMonth), { source: demoState, notify: false });
const demoMonthMatch = String(demoMonth || "").match(/^(\d{4})-(\d{2})$/);
if (demoMonthMatch) {
  curMonth = new Date(Number(demoMonthMatch[1]), Number(demoMonthMatch[2]) - 1, 1);
}

function hasManageAccess() {
  const pset = permSetFromResponse(perms);
  const role = roleUpper(perms);
  const sys = String(me?.system_role || "").toUpperCase();
  const isAdmin = sys === "SUPER_ADMIN" || sys === "MODERATOR";
  const isOwner = role === "OWNER" || role === "VENUE_OWNER";
  return isOwner || isAdmin || hasPerm(pset, "ADJUSTMENTS_MANAGE");
}

function hasResolveAccess() {
  const pset = permSetFromResponse(perms);
  const role = roleUpper(perms);
  const sys = String(me?.system_role || "").toUpperCase();
  const isAdmin = sys === "SUPER_ADMIN" || sys === "MODERATOR";
  const isOwner = role === "OWNER" || role === "VENUE_OWNER";
  return isOwner || isAdmin || hasPerm(pset, "DISPUTES_RESOLVE");
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

function typeClass(t) {
  if (t === "bonus") return "bonus";
  if (t === "writeoff") return "writeoff";
  return "penalty";
}

function signedAmount(item) {
  const amount = Number(item?.amount || 0);
  return `${item?.type === "bonus" ? "+" : "−"}${Math.abs(amount)}`;
}

function renderList(data) {
  el.monthLabel.textContent = monthTitle(curMonth);

  if (!hasManageAccess()) {
    el.list.innerHTML = `
      <div class="app-adjustments-state app-adjustments-state--denied">
        <b>Нет доступа</b>
        <span>Нужны права на управление штрафами, списаниями и премиями.</span>
      </div>
    `;
    el.btnCreate.classList.add("hidden");
    return;
  }

  el.btnCreate.classList.toggle("hidden", demoReadonly);
  if (demoReadonly && !document.getElementById("demoAdjustmentsNote")) {
    const note = document.createElement("div");
    note.id = "demoAdjustmentsNote";
    note.className = "app-adjustments-note";
    note.textContent = `Пробный режим: изменения по штрафам, списаниям и премиям отключены. Подготовлены данные за ${getDemoMonthLabel(demoState)}.`;
    el.list.parentElement?.insertBefore(note, el.list);
  }

  const items = data?.items || [];
  if (!items.length) {
    el.list.innerHTML = `<div class="app-adjustments-state app-adjustments-state--empty"><b>Записей нет</b><span>За выбранный месяц и тип операции корректировки не найдены.</span></div>`;
    return;
  }

  el.list.innerHTML = "";
  for (const it of items) {
    const row = document.createElement("div");
    row.className = "itemcard app-adjustment-row";

    const who = it.member ? personLabel(it.member) : "(заведение)";
    const kind = typeClass(it.type);
    const positive = kind === "bonus";

    row.innerHTML = `
      <div class="app-adjustment-row__main">
        <span class="app-adjustment-type app-adjustment-type--${esc(kind)}">${esc(typeTitle(it.type))}</span>
        <div class="app-adjustment-row__copy">
          <div class="app-adjustment-row__head">
            <b class="app-adjustment-amount app-adjustment-amount--${positive ? "positive" : "negative"}">${esc(signedAmount(it))}</b>
            <span class="muted small">${esc(it.date)} · ${esc(who)}</span>
          </div>
          <div class="muted small">${esc(it.reason || "Без комментария")}</div>
        </div>
      </div>
      <button class="btn sm" data-edit data-id="${esc(it.id)}">${demoReadonly ? "Просмотр" : "Подробнее"}</button>
    `;

    row.querySelector("[data-edit]").onclick = async () => {
      const members = await loadMembers().catch(() => []);
      const memberOpts = [
        `<option value="0">— (по заведению)</option>`,
        ...members.map((m) => {
          const label = (m.full_name || m.short_name) ? `${esc(m.full_name || m.short_name)}${m.tg_username ? ` — @${esc(m.tg_username)}` : ""}` : `@${esc(m.tg_username || "-")}`;
          return `<option value="${esc(m.user_id)}">${label}</option>`;
        }),
      ].join("");

      const html = `
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

          <label class="adj-reason">Причина
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
              <div class="muted mt-4" id="disputeStatus">Загрузка…</div>
            </div>
            <button class="btn" id="btnDisputeToggle">…</button>
          </div>

          <div id="disputeComments" class="dispute-list mt-10"></div>

          <div class="mt-10">
            <textarea class="w-100" id="disputeReply" rows="3" placeholder="Ответить…"></textarea>
            <div class="row row--end gap-8 mt-8">
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
    box.classList.add("hidden");
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
    if (statusEl) statusEl.textContent = `Статус: ${disputeStatusLabel(dis.status)}`;
    if (btnToggle) {
      const can = hasResolveAccess();
      btnToggle.disabled = !can;
      btnToggle.textContent = dis.status === "OPEN" ? "Закрыть спор" : "Открыть спор";
    }
    if (listEl) {
      const items = Array.isArray(data.comments) ? data.comments : [];
      listEl.innerHTML = items.length
        ? items.map(c => `<div class="card dispute-comment"><div class="muted small">${(c.created_at||"").slice(0,19).replace("T"," ")}</div><div class="dispute-comment__message">${escapeHtml(c.message||"")}</div></div>`).join("")
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

      if (demoReadonly) {
        [edType, edDate, edMember, edAmount, edReason].forEach((input) => { if (input) input.disabled = true; });
        const saveBtn = document.getElementById("btnAdjSave");
        const delBtn = document.getElementById("btnAdjDelete");
        saveBtn?.classList.add("hidden");
        delBtn?.classList.add("hidden");
      }

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
          await refreshList();
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
          await refreshList();
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

function disputeStatusLabel(status) {
  const s = String(status || "").toUpperCase();
  if (s === "OPEN") return "открыт";
  if (s === "RESOLVED") return "решён";
  if (s === "CLOSED") return "закрыт";
  return "не указан";
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
    <div class="app-adjustment-create">
      <div class="row adjustment-create-grid">
        <label class="adjustment-field adjustment-field--member">
          <div class="muted small mb-4">Тип</div>
          <select id="adjType">
            <option value="penalty">Штраф</option>
            <option value="writeoff">Списание</option>
            <option value="bonus">Премия</option>
          </select>
        </label>

        <label class="adjustment-field adjustment-field--member" id="memberWrap">
          <div class="muted small mb-4">Сотрудник</div>
          <select id="adjMember">
            <option value="">(не выбран)</option>
            ${opts}
          </select>
          <div class="muted small mt-6" id="memberHint">Для штрафа/премии сотрудник обязателен. Для списания можно оставить пустым (списание по заведению).</div>
        </label>

        <label class="adjustment-field adjustment-field--date">
          <div class="muted small mb-4">Дата</div>
          <input id="adjDate" type="date" />
        </label>

        <label class="adjustment-field adjustment-field--amount">
          <div class="muted small mb-4">Сумма</div>
          <input id="adjAmount" type="number" min="0" placeholder="0" />
        </label>
      </div>

      <div class="mt-10">
        <div class="muted small mb-4">Причина</div>
        <textarea id="adjReason" rows="3" placeholder="Опиши причину"></textarea>
      </div>

      <div class="app-adjustment-form-actions">
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
  if (demoReadonly) {
    toast(`Пробный режим: создание записей отключено. Данные за ${getDemoMonthLabel(demoState)}.`, "warn");
    return;
  }
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
      await refreshList();
    } catch (e) {
      toast("Ошибка: " + (e?.message || "неизвестно"), "err");
    }
  });
}

function renderListLoading() {
  if (el.monthLabel) el.monthLabel.textContent = monthTitle(curMonth);
  if (el.list) {
    el.list.innerHTML = `<div class="app-adjustments-loading"><div class="skeleton"></div><div class="skeleton"></div></div>`;
  }
}

async function refreshList() {
  if (!hasManageAccess()) {
    renderList({ items: [] });
    return;
  }
  renderListLoading();
  try {
    const data = await loadList();
    renderList(data);
  } catch (e) {
    toast("Ошибка загрузки: " + (e?.message || "неизвестно"), "err");
    if (el.list) {
      el.list.innerHTML = `<div class="app-adjustments-state app-adjustments-state--error"><b>Не удалось загрузить данные</b><span>Проверь подключение и повтори попытку.</span></div>`;
    }
  }
}

async function boot() {
  if (!venueId) {
    el.list.innerHTML = `<div class="app-adjustments-state"><b>Не выбрано заведение</b><span>Выбери заведение и открой раздел ещё раз.</span></div>`;
    return;
  }

  await loadPerms();
  await refreshList();
}

el.prev?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() - 1);
  curMonth.setDate(1);
  await refreshList();
});

el.next?.addEventListener("click", async () => {
  curMonth.setMonth(curMonth.getMonth() + 1);
  curMonth.setDate(1);
  await refreshList();
});

el.typeSel?.addEventListener("change", async () => {
  await refreshList();
});

el.btnCreate?.addEventListener("click", openCreate);

await boot();

import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenuePermissions,
  getPaymentMethods,
  api,
  toast,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

function fmtMoneyMinor(minor) {
  const rub = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return rub.toFixed(2) + " ₽";
  }
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseMoneyToMinor(value) {
  const raw = String(value || "").trim().replace(/\s+/g, "").replace(/,/g, ".");
  if (!raw) throw new Error("Введите сумму");
  if (!/^\d+(\.\d{1,2})?$/.test(raw)) throw new Error("Сумма должна быть числом, например 1200.50");
  const [rubStr, fracStr = ""] = raw.split(".");
  return (Number(rubStr || 0) * 100) + Number((fracStr + "00").slice(0, 2));
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function statusLabel(status) {
  const norm = String(status || "DRAFT").toUpperCase();
  if (norm === "CONFIRMED") return "Подтверждён";
  if (norm === "CANCELLED") return "Отменён";
  return "Черновик";
}

function openHtmlModal(title, html) {
  const m = document.getElementById("modal");
  if (!m) return;
  const head = m.querySelector(".modal__title");
  const body = m.querySelector(".modal__body");
  if (head) head.textContent = title;
  if (body) body.innerHTML = html;
  m.classList.add("open");
}

function closeModal() {
  document.getElementById("modal")?.classList.remove("open");
}

let access = {
  canView: false,
  canManageTransfers: false,
};

const state = {
  month: currentMonth(),
  paymentMethods: [],
  entries: [],
  transfers: [],
};

async function loadAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return access;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    access = {
      canView: isOwner || hasPerm(pset, "FINANCE_LEDGER_VIEW") || hasPerm(pset, "REVENUE_VIEW") || hasPerm(pset, "EXPENSE_VIEW"),
      canManageTransfers: isOwner || hasPerm(pset, "PAYMENT_TRANSFERS_MANAGE") || hasPerm(pset, "EXPENSE_ADD"),
    };
  } catch {
    access = { canView: false, canManageTransfers: false };
  }
  return access;
}

function renderPaymentMethodOptions() {
  const pick = document.getElementById("ledgerPaymentMethodPick");
  if (!pick) return;
  const current = pick.value || "";
  pick.innerHTML = `<option value="">Все оплаты</option>` + state.paymentMethods.map((pm) => `<option value="${pm.id}">${esc(pm.title)}</option>`).join("");
  pick.value = current;
}

function renderEntries() {
  const el = document.getElementById("ledgerEntriesList");
  if (!el) return;
  const income = state.entries.filter((x) => x.direction === "INCOME").reduce((a, x) => a + Number(x.amount_minor || 0), 0);
  const expense = state.entries.filter((x) => x.direction === "EXPENSE").reduce((a, x) => a + Number(x.amount_minor || 0), 0);
  setText("ledgerIncomeTotal", fmtMoneyMinor(income));
  setText("ledgerExpenseTotal", fmtMoneyMinor(expense));
  setText("ledgerCount", String(state.entries.length));
  setText("ledgerHint", state.entries.length ? `Период ${state.month}` : `За ${state.month} записей нет`);

  if (!state.entries.length) {
    el.innerHTML = `<div class="muted">Нет финансовых записей за выбранный период.</div>`;
    return;
  }

  el.innerHTML = state.entries.map((item) => {
    const directionText = item.direction === "INCOME" ? "Доход" : "Расход";
    const scope = item.payment_method?.title || item.department?.title || item.source_type || "—";
    const meta = item.meta_json ? `<div class="muted mt-6">${esc(JSON.stringify(item.meta_json))}</div>` : "";
    return `
      <div class="expense-row">
        <div class="expense-row__main">
          <div class="row" style="gap:8px; flex-wrap:wrap; align-items:center;">
            <div class="expense-row__title">${esc(item.kind || "—")}</div>
            <span class="badge">${esc(directionText)}</span>
            <span class="badge">${esc(scope)}</span>
          </div>
          <div class="muted mt-6">${esc(item.entry_date || "—")} · source=${esc(item.source_type || "—")} #${esc(item.source_id || "—")}</div>
          ${meta}
        </div>
        <div class="expense-row__side">
          <div class="expense-row__amount">${esc(fmtMoneyMinor(item.amount_minor || 0))}</div>
        </div>
      </div>
    `;
  }).join("");
}

function renderTransfers() {
  const el = document.getElementById("transferList");
  if (!el) return;
  setText("transferHint", state.transfers.length ? `Записей: ${state.transfers.length}` : `За ${state.month} переводов нет`);
  if (!state.transfers.length) {
    el.innerHTML = `<div class="muted">Нет переводов за выбранный период.</div>`;
    return;
  }
  el.innerHTML = state.transfers.map((item) => {
    const status = String(item.status || "CONFIRMED").toUpperCase();
    const actions = access.canManageTransfers ? `
      <div class="row gap-8 mt-10" style="justify-content:flex-end; flex-wrap:wrap;">
        ${status !== "CONFIRMED" ? `<button class="btn small" data-transfer-status="CONFIRMED" data-transfer-id="${item.id}">Подтвердить</button>` : ""}
        ${status !== "DRAFT" ? `<button class="btn ghost small" data-transfer-status="DRAFT" data-transfer-id="${item.id}">В черновик</button>` : ""}
        ${status !== "CANCELLED" ? `<button class="btn ghost small" data-transfer-status="CANCELLED" data-transfer-id="${item.id}">Отменить</button>` : ""}
        <button class="btn small" data-transfer-edit="${item.id}">Изменить</button>
        <button class="btn danger small" data-transfer-del="${item.id}">Удалить</button>
      </div>` : "";
    return `
      <div class="expense-row">
        <div class="expense-row__main">
          <div class="row" style="gap:8px; flex-wrap:wrap; align-items:center;">
            <div class="expense-row__title">${esc(item.from_payment_method?.title || "—")} → ${esc(item.to_payment_method?.title || "—")}</div>
            <span class="badge">${esc(statusLabel(status))}</span>
          </div>
          <div class="muted mt-6">${esc(item.transfer_date || "—")}</div>
          ${item.comment ? `<div class="mt-8">${esc(item.comment)}</div>` : ""}
        </div>
        <div class="expense-row__side">
          <div class="expense-row__amount">${esc(fmtMoneyMinor(item.amount_minor || 0))}</div>
          ${actions}
        </div>
      </div>
    `;
  }).join("");

  el.querySelectorAll("[data-transfer-edit]").forEach((btn) => {
    btn.onclick = () => openTransferForm(Number(btn.getAttribute("data-transfer-edit")));
  });
  el.querySelectorAll("[data-transfer-del]").forEach((btn) => {
    btn.onclick = () => deleteTransfer(Number(btn.getAttribute("data-transfer-del")));
  });
  el.querySelectorAll("[data-transfer-status]").forEach((btn) => {
    btn.onclick = () => updateTransfer(Number(btn.getAttribute("data-transfer-id")), { status: String(btn.getAttribute("data-transfer-status") || "DRAFT") });
  });
}

function buildTransferForm(item = null) {
  const fromOptions = state.paymentMethods.map((pm) => `<option value="${pm.id}" ${String(item?.from_payment_method_id || "") === String(pm.id) ? "selected" : ""}>${esc(pm.title)}</option>`).join("");
  const toOptions = state.paymentMethods.map((pm) => `<option value="${pm.id}" ${String(item?.to_payment_method_id || "") === String(pm.id) ? "selected" : ""}>${esc(pm.title)}</option>`).join("");
  const amount = item ? (Number(item.amount_minor || 0) / 100).toFixed(2) : "";
  const status = String(item?.status || "CONFIRMED").toUpperCase();
  return `
    <form id="transferForm" class="finance-form">
      <label>Из оплаты<select name="from_payment_method_id" required>${fromOptions}</select></label>
      <label>В оплату<select name="to_payment_method_id" required>${toOptions}</select></label>
      <label>Сумма, ₽<input name="amount" type="text" placeholder="1500.00" value="${esc(amount)}" required /></label>
      <label>Дата<input name="transfer_date" type="date" value="${esc(item?.transfer_date || todayISO())}" required /></label>
      <label>Статус
        <select name="status">
          <option value="DRAFT" ${status === "DRAFT" ? "selected" : ""}>Черновик</option>
          <option value="CONFIRMED" ${status === "CONFIRMED" ? "selected" : ""}>Подтверждён</option>
          <option value="CANCELLED" ${status === "CANCELLED" ? "selected" : ""}>Отменён</option>
        </select>
      </label>
      <label>Комментарий<textarea name="comment" rows="4" placeholder="Комментарий">${esc(item?.comment || "")}</textarea></label>
      <div class="row gap-8 mt-12">
        <button class="btn" type="submit">${item ? "Сохранить" : "Добавить"}</button>
        <button class="btn ghost" type="button" id="transferCancel">Отмена</button>
      </div>
    </form>
  `;
}

function openTransferForm(transferId = null) {
  if (!access.canManageTransfers) return;
  if (state.paymentMethods.length < 2) {
    toast("Нужно минимум два типа оплаты", "warn");
    return;
  }
  const item = transferId ? state.transfers.find((x) => Number(x.id) === Number(transferId)) : null;
  openHtmlModal(item ? "Изменить перевод" : "Новый перевод", buildTransferForm(item));
  const form = document.getElementById("transferForm");
  document.getElementById("transferCancel")?.addEventListener("click", closeModal);
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    try {
      const fd = new FormData(form);
      const payload = {
        from_payment_method_id: Number(fd.get("from_payment_method_id") || 0),
        to_payment_method_id: Number(fd.get("to_payment_method_id") || 0),
        amount_minor: parseMoneyToMinor(fd.get("amount")),
        transfer_date: String(fd.get("transfer_date") || ""),
        status: String(fd.get("status") || "CONFIRMED"),
        comment: String(fd.get("comment") || "").trim() || null,
      };
      if (payload.from_payment_method_id === payload.to_payment_method_id) throw new Error("Типы оплат должны отличаться");
      const venueId = getActiveVenueId();
      if (item) {
        await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers/${encodeURIComponent(item.id)}`, { method: "PATCH", body: payload });
      } else {
        await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers`, { method: "POST", body: payload });
      }
      closeModal();
      toast(item ? "Перевод обновлён" : "Перевод создан", "ok");
      await reload();
    } catch (err) {
      toast(err?.data?.detail || err.message || "Не удалось сохранить перевод", "err");
    }
  };
}

async function updateTransfer(id, payload) {
  const venueId = getActiveVenueId();
  await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers/${encodeURIComponent(id)}`, { method: "PATCH", body: payload });
  toast("Перевод обновлён", "ok");
  await reload();
}

async function deleteTransfer(id) {
  const venueId = getActiveVenueId();
  if (!confirm("Удалить перевод?")) return;
  await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers/${encodeURIComponent(id)}`, { method: "DELETE" });
  toast("Перевод удалён", "ok");
  await reload();
}

async function reload() {
  const venueId = getActiveVenueId();
  const month = document.getElementById("ledgerMonthPick")?.value || currentMonth();
  const paymentMethodId = document.getElementById("ledgerPaymentMethodPick")?.value || "";
  const kind = document.getElementById("ledgerKindPick")?.value || "";
  state.month = month;

  const qp = new URLSearchParams({ month });
  if (paymentMethodId) qp.set("payment_method_id", paymentMethodId);
  if (kind) qp.set("kind", kind);

  state.entries = access.canView ? await api(`/venues/${encodeURIComponent(venueId)}/finance/entries?${qp.toString()}`) : [];
  state.transfers = access.canView ? await api(`/venues/${encodeURIComponent(venueId)}/payment-method-transfers?month=${encodeURIComponent(month)}`) : [];
  renderEntries();
  renderTransfers();
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("venue");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId() || "";
  if (!venueId) {
    toast("Сначала выбери заведение", "err");
    return;
  }
  setActiveVenueId(venueId);
  await mountNav({ activeTab: "venue", requireVenue: true });
  await loadAccess();

  state.paymentMethods = await getPaymentMethods(venueId, { includeArchived: false });
  renderPaymentMethodOptions();
  document.getElementById("ledgerMonthPick").value = params.get("month") || currentMonth();
  document.getElementById("ledgerPaymentMethodPick").value = params.get("payment_method_id") || "";
  document.getElementById("ledgerKindPick").value = (params.get("kind") || "").toUpperCase();
  document.getElementById("ledgerMonthPick").onchange = reload;
  document.getElementById("ledgerPaymentMethodPick").onchange = reload;
  document.getElementById("ledgerKindPick").onchange = reload;
  document.getElementById("addTransferBtn").style.display = access.canManageTransfers ? "" : "none";
  document.getElementById("addTransferBtn").onclick = () => openTransferForm();
  document.querySelectorAll("[data-close], .modal__backdrop").forEach((el) => el.addEventListener("click", closeModal));

  await reload();
}

document.addEventListener("DOMContentLoaded", boot);

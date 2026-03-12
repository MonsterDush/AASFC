import {
  applyTelegramTheme,
  mountCommonUI,
  ensureLogin,
  mountNav,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  getMyVenuePermissions,
  api,
  toast,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

function fmtMoneyMinor(minor) {
  const kopecks = Number(minor || 0);
  const rub = kopecks / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return rub.toFixed(2) + " ₽";
  }
}

function fmtPercentBps(bps) {
  if (bps === null || bps === undefined) return "—";
  const pct = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(pct) + "%";
  } catch {
    return pct.toFixed(2) + "%";
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

function parseSignedMoneyToMinor(value) {
  const raw = String(value || "").trim().replace(/\s+/g, "").replace(/,/g, ".");
  if (!raw) throw new Error("Введите сумму");
  if (!/^[+-]?\d+(\.\d{1,2})?$/.test(raw)) throw new Error("Сумма должна быть числом, например 1200.50 или -350");
  const sign = raw.startsWith("-") ? -1 : 1;
  const normalized = raw.replace(/^[-+]/, "");
  const [rubStr, fracStr = ""] = normalized.split(".");
  return sign * ((Number(rubStr || 0) * 100) + Number((fracStr + "00").slice(0, 2)));
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function renderList(id, rows, emptyText) {
  const el = document.getElementById(id);
  if (!el) return;
  if (!Array.isArray(rows) || !rows.length) {
    el.innerHTML = `<div class="muted">${esc(emptyText)}</div>`;
    return;
  }
  el.innerHTML = rows.map((row) => `
    <div class="row" style="justify-content:space-between; gap:12px; align-items:flex-start; padding:8px 0; border-bottom:1px solid rgba(255,255,255,.06);">
      <div>
        <div><b>${esc(row.title || row.code || "—")}</b></div>
        ${row.code ? `<div class="muted mt-6">${esc(row.code)}</div>` : ""}
      </div>
      <div style="text-align:right; white-space:nowrap;">${esc(fmtMoneyMinor(row.amount_minor || 0))}</div>
    </div>
  `).join("");
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

let financeAccess = {
  canViewRevenue: false,
  canViewExpenses: false,
  canManageExpenses: false,
};

const state = {
  month: currentMonth(),
  incomeMode: "PAYMENTS",
  paymentMethods: [],
  adjustments: [],
};

async function loadFinanceAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return financeAccess;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    financeAccess = {
      canViewRevenue: isOwner || hasPerm(pset, "REVENUE_VIEW"),
      canViewExpenses: isOwner || hasPerm(pset, "EXPENSE_VIEW"),
      canManageExpenses: isOwner || hasPerm(pset, "EXPENSE_ADD"),
    };
  } catch {
    financeAccess = { canViewRevenue: false, canViewExpenses: false, canManageExpenses: false };
  }
  return financeAccess;
}

async function loadPaymentMethods() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  try {
    const rows = await api(`/venues/${encodeURIComponent(venueId)}/payment-methods`);
    state.paymentMethods = Array.isArray(rows) ? rows : [];
  } catch {
    state.paymentMethods = [];
  }
}

function renderPaymentBalances(rows) {
  const el = document.getElementById("summaryPaymentBalances");
  if (!el) return;
  if (!Array.isArray(rows) || !rows.length) {
    el.innerHTML = `<div class="muted">Нет данных по балансам</div>`;
    return;
  }
  el.innerHTML = rows.map((row) => `
    <div class="row" style="justify-content:space-between; gap:12px; align-items:flex-start; padding:10px 0; border-bottom:1px solid rgba(255,255,255,.06);">
      <div>
        <div><b>${esc(row.title || row.code || "—")}</b></div>
        ${row.code ? `<div class="muted mt-6">${esc(row.code)}</div>` : ""}
      </div>
      <div style="display:grid; grid-template-columns:repeat(3, minmax(96px, auto)); gap:12px; text-align:right;">
        <div><div class="muted small">Приход</div><div>${esc(fmtMoneyMinor(row.inflow_minor || 0))}</div></div>
        <div><div class="muted small">Расход</div><div>${esc(fmtMoneyMinor(row.outflow_minor || 0))}</div></div>
        <div><div class="muted small">Баланс</div><div><b>${esc(fmtMoneyMinor(row.balance_minor || 0))}</b></div></div>
      </div>
    </div>
  `).join("");
}

function renderBalanceAdjustments() {
  const el = document.getElementById("balanceAdjustmentsList");
  if (!el) return;
  setText("balanceAdjustmentsHint", state.adjustments.length ? `Записей: ${state.adjustments.length}` : `За ${state.month} корректировок нет`);
  if (!state.adjustments.length) {
    el.innerHTML = `<div class="muted">Нет корректировок за выбранный период.</div>`;
    return;
  }
  el.innerHTML = state.adjustments.map((item) => {
    const status = String(item.status || "CONFIRMED").toUpperCase();
    const actions = financeAccess.canManageExpenses ? `
      <div class="row gap-8 mt-10" style="flex-wrap:wrap; justify-content:flex-end;">
        ${status !== "CONFIRMED" ? `<button class="btn small" data-bal-status="CONFIRMED" data-bal-id="${item.id}">Подтвердить</button>` : ""}
        ${status !== "DRAFT" ? `<button class="btn ghost small" data-bal-status="DRAFT" data-bal-id="${item.id}">В черновик</button>` : ""}
        ${status !== "CANCELLED" ? `<button class="btn ghost small" data-bal-status="CANCELLED" data-bal-id="${item.id}">Отменить</button>` : ""}
        <button class="btn small" data-bal-edit="${item.id}">Изменить</button>
        <button class="btn danger small" data-bal-del="${item.id}">Удалить</button>
      </div>` : "";
    return `
      <div class="row" style="justify-content:space-between; gap:12px; align-items:flex-start; padding:10px 0; border-bottom:1px solid rgba(255,255,255,.06);">
        <div>
          <div class="row" style="gap:8px; flex-wrap:wrap; align-items:center;">
            <b>${esc(item.payment_method?.title || "—")}</b>
            <span class="badge">${esc(statusLabel(status))}</span>
          </div>
          <div class="muted mt-6">${esc(item.adjustment_date || "—")}${item.reason ? ` · ${esc(item.reason)}` : ""}</div>
          ${item.comment ? `<div class="mt-8">${esc(item.comment)}</div>` : ""}
        </div>
        <div style="text-align:right; white-space:nowrap;">
          <div><b>${esc(fmtMoneyMinor(item.delta_minor || 0))}</b></div>
          ${actions}
        </div>
      </div>
    `;
  }).join("");

  el.querySelectorAll("[data-bal-edit]").forEach((btn) => {
    btn.onclick = () => openBalanceAdjustmentForm(Number(btn.getAttribute("data-bal-edit")));
  });
  el.querySelectorAll("[data-bal-del]").forEach((btn) => {
    btn.onclick = () => deleteBalanceAdjustment(Number(btn.getAttribute("data-bal-del")));
  });
  el.querySelectorAll("[data-bal-status]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        await updateBalanceAdjustment(Number(btn.getAttribute("data-bal-id")), { status: String(btn.getAttribute("data-bal-status") || "DRAFT") });
      } catch (err) {
        toast(err?.data?.detail || err.message || "Не удалось обновить статус", "err");
      }
    };
  });
}

function buildBalanceAdjustmentForm(item = null) {
  const options = state.paymentMethods.map((pm) => `<option value="${pm.id}" ${String(item?.payment_method_id || "") === String(pm.id) ? "selected" : ""}>${esc(pm.title)}</option>`).join("");
  const delta = item ? (Number(item.delta_minor || 0) / 100).toFixed(2) : "";
  const status = String(item?.status || "CONFIRMED").toUpperCase();
  return `
    <form id="balanceAdjustmentForm" class="finance-form">
      <label>Тип оплаты<select name="payment_method_id" required>${options}</select></label>
      <label>Сумма корректировки, ₽<input name="delta" type="text" placeholder="Например: 1500.00 или -350" value="${esc(delta)}" required /></label>
      <label>Дата<input name="adjustment_date" type="date" value="${esc(item?.adjustment_date || todayISO())}" required /></label>
      <label>Статус
        <select name="status">
          <option value="DRAFT" ${status === "DRAFT" ? "selected" : ""}>Черновик</option>
          <option value="CONFIRMED" ${status === "CONFIRMED" ? "selected" : ""}>Подтверждён</option>
          <option value="CANCELLED" ${status === "CANCELLED" ? "selected" : ""}>Отменён</option>
        </select>
      </label>
      <label>Причина<input name="reason" type="text" maxlength="255" placeholder="Например: стартовый остаток" value="${esc(item?.reason || "")}" /></label>
      <label>Комментарий<textarea name="comment" rows="4" placeholder="Комментарий">${esc(item?.comment || "")}</textarea></label>
      <div class="row gap-8 mt-12">
        <button class="btn" type="submit">${item ? "Сохранить" : "Добавить"}</button>
        <button class="btn ghost" type="button" id="balanceAdjustmentCancel">Отмена</button>
      </div>
    </form>
  `;
}

function openBalanceAdjustmentForm(adjustmentId = null) {
  if (!financeAccess.canManageExpenses) return;
  if (!state.paymentMethods.length) {
    toast("Сначала создайте хотя бы один тип оплаты", "warn");
    return;
  }
  const item = adjustmentId ? state.adjustments.find((x) => Number(x.id) === Number(adjustmentId)) : null;
  openHtmlModal(adjustmentId ? "Редактировать корректировку" : "Корректировка баланса", buildBalanceAdjustmentForm(item));
  const form = document.getElementById("balanceAdjustmentForm");
  const cancelBtn = document.getElementById("balanceAdjustmentCancel");
  if (cancelBtn) cancelBtn.onclick = () => closeModal();
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const payload = {
      payment_method_id: Number(fd.get("payment_method_id")),
      adjustment_date: String(fd.get("adjustment_date") || ""),
      delta_minor: parseSignedMoneyToMinor(fd.get("delta")),
      status: String(fd.get("status") || "CONFIRMED"),
      reason: String(fd.get("reason") || "").trim() || null,
      comment: String(fd.get("comment") || "").trim() || null,
    };
    try {
      if (item) {
        await updateBalanceAdjustment(item.id, payload);
      } else {
        const venueId = getActiveVenueId();
        await api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments`, { method: "POST", body: payload });
        toast("Корректировка добавлена", "ok");
      }
      closeModal();
      await reloadCurrentState();
    } catch (err) {
      toast(err?.data?.detail || err.message || "Не удалось сохранить корректировку", "err");
    }
  };
}

async function updateBalanceAdjustment(adjustmentId, payload) {
  const venueId = getActiveVenueId();
  await api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments/${encodeURIComponent(adjustmentId)}`, { method: "PATCH", body: payload });
  toast("Корректировка обновлена", "ok");
  await reloadCurrentState();
}

async function deleteBalanceAdjustment(adjustmentId) {
  if (!financeAccess.canManageExpenses) return;
  if (!confirm("Удалить корректировку баланса?")) return;
  try {
    const venueId = getActiveVenueId();
    await api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments/${encodeURIComponent(adjustmentId)}`, { method: "DELETE" });
    toast("Корректировка удалена", "ok");
    await reloadCurrentState();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось удалить корректировку", "err");
  }
}

async function loadSummary(monthYYYYMM, incomeMode) {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  if (!financeAccess.canViewRevenue && !financeAccess.canViewExpenses) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
    setText("summaryProfit", "—");
    setText("summaryMargin", "—");
    setText("summaryHint", "Нет прав на финансовую сводку");
    renderList("summaryRevenueBreakdown", [], "Нет доступа");
    renderList("summaryExpenseBreakdown", [], "Нет доступа");
    renderPaymentBalances([]);
    return;
  }

  try {
    const summary = await api(`/venues/${encodeURIComponent(venueId)}/summary/monthly?month=${encodeURIComponent(monthYYYYMM)}&income_mode=${encodeURIComponent(incomeMode)}`);
    setText("summaryRevenue", fmtMoneyMinor(summary?.revenue_minor));
    setText("summaryExpenses", fmtMoneyMinor(summary?.expense_minor));
    setText("summaryProfit", fmtMoneyMinor(summary?.profit_minor));
    setText("summaryMargin", fmtPercentBps(summary?.margin_bps));
    setText("summaryPeriodText", `${summary?.period_start || monthYYYYMM} — ${summary?.period_end || monthYYYYMM}`);
    setText("summaryHint", `ФОТ: ${fmtMoneyMinor(summary?.payroll_minor)} · Корректировки P&L: ${fmtMoneyMinor(summary?.adjustments_minor)} · Возвраты: ${fmtMoneyMinor(summary?.refunds_minor)}`);
    setText("summaryIncomeModeText", String(summary?.income_mode || incomeMode).toUpperCase() === "DEPARTMENTS" ? "Доходы по департаментам" : "Доходы по типам оплат");
    renderList("summaryRevenueBreakdown", summary?.revenue_breakdown || [], "Нет данных по доходам за период");
    renderList("summaryExpenseBreakdown", summary?.expense_categories || [], "Нет признанных расходов за период");
    renderPaymentBalances(summary?.payment_method_balances || []);
  } catch (e) {
    setText("summaryRevenue", "—");
    setText("summaryExpenses", "—");
    setText("summaryProfit", "—");
    setText("summaryMargin", "—");
    setText("summaryHint", e?.data?.detail || e.message || "Ошибка загрузки");
    renderList("summaryRevenueBreakdown", [], "Не удалось загрузить");
    renderList("summaryExpenseBreakdown", [], "Не удалось загрузить");
    renderPaymentBalances([]);
    toast("Не удалось загрузить финансовую сводку", "err");
  }
}

async function loadBalanceAdjustments(monthYYYYMM) {
  const venueId = getActiveVenueId();
  if (!venueId || (!financeAccess.canViewRevenue && !financeAccess.canViewExpenses)) {
    state.adjustments = [];
    renderBalanceAdjustments();
    return;
  }
  try {
    const rows = await api(`/venues/${encodeURIComponent(venueId)}/balance-adjustments?month=${encodeURIComponent(monthYYYYMM)}`);
    state.adjustments = Array.isArray(rows) ? rows : [];
  } catch (e) {
    state.adjustments = [];
    toast(e?.data?.detail || e.message || "Не удалось загрузить корректировки баланса", "err");
  }
  renderBalanceAdjustments();
}

async function reloadCurrentState() {
  await loadSummary(state.month, state.incomeMode);
  await loadBalanceAdjustments(state.month);
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");

  const me = await ensureLogin();
  const venues = await getMyVenues();
  if (!getActiveVenueId() && Array.isArray(venues) && venues.length) setActiveVenueId(venues[0].id);
  await mountNav({ activeTab: "summary" });
  await loadFinanceAccess();
  await loadPaymentMethods();

  document.querySelectorAll("#modal [data-close], #modal .modal__backdrop").forEach((el) => {
    el.onclick = () => closeModal();
  });

  const venueId = getActiveVenueId();
  const openRevenueBtn = document.getElementById("openRevenueBtn");
  const openExpensesBtn = document.getElementById("openExpensesBtn");
  const addBalanceAdjustmentBtn = document.getElementById("addBalanceAdjustmentBtn");
  if (openRevenueBtn && venueId) openRevenueBtn.onclick = () => location.href = `/owner-turnover.html?venue_id=${encodeURIComponent(venueId)}`;
  if (openExpensesBtn && venueId) openExpensesBtn.onclick = () => location.href = `/owner-expenses.html?venue_id=${encodeURIComponent(venueId)}`;
  if (addBalanceAdjustmentBtn) {
    addBalanceAdjustmentBtn.style.display = financeAccess.canManageExpenses ? "" : "none";
    addBalanceAdjustmentBtn.onclick = () => openBalanceAdjustmentForm();
  }

  const params = new URLSearchParams(location.search);
  const monthPick = document.getElementById("summaryMonthPick");
  const modePick = document.getElementById("summaryIncomeMode");
  state.month = params.get("month") || currentMonth();
  state.incomeMode = (params.get("income_mode") || "PAYMENTS").toUpperCase();
  if (monthPick) monthPick.value = state.month;
  if (modePick) modePick.value = state.incomeMode;

  const reload = async () => {
    state.month = monthPick?.value || currentMonth();
    state.incomeMode = (modePick?.value || "PAYMENTS").toUpperCase();
    await reloadCurrentState();
  };

  if (monthPick) monthPick.onchange = reload;
  if (modePick) modePick.onchange = reload;

  await reload();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

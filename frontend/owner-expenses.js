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
  closeModal,
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

let access = {
  canView: false,
  canEdit: false,
  canManageCatalogs: false,
};

let state = {
  categories: [],
  suppliers: [],
  expenses: [],
  month: "",
  categoryId: "",
  supplierId: "",
};

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function fmtMinor(minor) {
  const rub = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return rub.toFixed(2) + " ₽";
  }
}

function parseMoneyToMinor(value) {
  const normalized = String(value || "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!normalized) return 0;
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) throw new Error("Введите сумму в формате 1234.56");
  return Math.round(Number(normalized) * 100);
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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

async function loadAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return access;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    access = {
      canView: isOwner || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD"),
      canEdit: isOwner || hasPerm(pset, "EXPENSE_ADD"),
      canManageCatalogs: isOwner || hasPerm(pset, "EXPENSE_CATEGORIES_MANAGE"),
    };
  } catch {
    access = { canView: false, canEdit: false, canManageCatalogs: false };
  }
  return access;
}

function fillSelect(el, items, { placeholder }) {
  if (!el) return;
  const current = el.value;
  el.innerHTML = `<option value="">${placeholder}</option>` + items.map(item => {
    return `<option value="${item.id}">${esc(item.title)}</option>`;
  }).join("");
  if (current && items.some(item => String(item.id) === String(current))) el.value = current;
}

function syncToolbar() {
  const addExpenseBtn = document.getElementById("addExpenseBtn");
  const addCategoryBtn = document.getElementById("addCategoryBtn");
  const addSupplierBtn = document.getElementById("addSupplierBtn");
  if (addExpenseBtn) addExpenseBtn.style.display = access.canEdit ? "" : "none";
  if (addCategoryBtn) addCategoryBtn.style.display = access.canManageCatalogs ? "" : "none";
  if (addSupplierBtn) addSupplierBtn.style.display = access.canManageCatalogs ? "" : "none";
}

async function loadCatalogs() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  const [categories, suppliers] = await Promise.all([
    api(`/venues/${encodeURIComponent(venueId)}/expense-categories`),
    api(`/venues/${encodeURIComponent(venueId)}/suppliers`),
  ]);
  state.categories = Array.isArray(categories) ? categories : [];
  state.suppliers = Array.isArray(suppliers) ? suppliers : [];

  fillSelect(document.getElementById("expenseCategoryFilter"), state.categories, { placeholder: "Все категории" });
  fillSelect(document.getElementById("expenseSupplierFilter"), state.suppliers, { placeholder: "Все поставщики" });
}

async function loadExpenses() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  if (!access.canView) {
    document.getElementById("expensesList").innerHTML = `<div class="muted">Нет прав на просмотр расходов.</div>`;
    document.getElementById("expensesState").textContent = "Доступ ограничен";
    document.getElementById("expensesTotalMinor").textContent = "—";
    document.getElementById("expensesCount").textContent = "—";
    return;
  }

  const qp = new URLSearchParams();
  qp.set("month", state.month || currentMonth());
  if (state.categoryId) qp.set("category_id", state.categoryId);
  if (state.supplierId) qp.set("supplier_id", state.supplierId);

  const rows = await api(`/venues/${encodeURIComponent(venueId)}/expenses?${qp.toString()}`);
  state.expenses = Array.isArray(rows) ? rows : [];
  renderExpenses();
}

function renderExpenses() {
  const list = document.getElementById("expensesList");
  const totalEl = document.getElementById("expensesTotalMinor");
  const countEl = document.getElementById("expensesCount");
  const stateEl = document.getElementById("expensesState");
  if (!list) return;

  const totalMinor = state.expenses.reduce((acc, item) => acc + Number(item.amount_minor || 0), 0);
  if (totalEl) totalEl.textContent = fmtMinor(totalMinor);
  if (countEl) countEl.textContent = String(state.expenses.length);
  if (stateEl) stateEl.textContent = state.expenses.length ? `Месяц ${state.month}` : `За ${state.month} расходов нет`;

  if (!state.expenses.length) {
    list.innerHTML = `<div class="muted">Нет расходов за выбранный период.</div>`;
    return;
  }

  list.innerHTML = state.expenses.map(item => {
    const allocs = Array.isArray(item.allocations) ? item.allocations : [];
    const allocationsHtml = allocs.map(a => `<span class="badge">${esc(a.month)} · ${esc(fmtMinor(a.amount_minor))}</span>`).join(" ");
    return `
      <div class="expense-row">
        <div class="expense-row__main">
          <div class="expense-row__title">${esc(item.category?.title || "Без категории")}</div>
          <div class="muted mt-6">${esc(item.expense_date || "—")}${item.supplier?.title ? ` · ${esc(item.supplier.title)}` : ""}</div>
          ${item.comment ? `<div class="mt-8">${esc(item.comment)}</div>` : ""}
          <div class="expense-row__allocations mt-8">${allocationsHtml || '<span class="muted">Без распределения</span>'}</div>
        </div>
        <div class="expense-row__side">
          <div class="expense-row__amount">${esc(fmtMinor(item.amount_minor))}</div>
          ${access.canEdit ? `<div class="row gap-8 mt-10"><button class="btn small" data-edit="${item.id}">Изменить</button><button class="btn danger small" data-del="${item.id}">Удалить</button></div>` : ""}
        </div>
      </div>
    `;
  }).join("");

  list.querySelectorAll("[data-edit]").forEach(btn => {
    btn.onclick = () => openExpenseForm(Number(btn.getAttribute("data-edit")));
  });
  list.querySelectorAll("[data-del]").forEach(btn => {
    btn.onclick = () => deleteExpense(Number(btn.getAttribute("data-del")));
  });
}

function buildExpenseForm(item = null) {
  const categoryOptions = state.categories.map(cat => `<option value="${cat.id}" ${String(item?.category_id || "") === String(cat.id) ? "selected" : ""}>${esc(cat.title)}</option>`).join("");
  const supplierOptions = ['<option value="">Без поставщика</option>'].concat(
    state.suppliers.map(sup => `<option value="${sup.id}" ${String(item?.supplier_id || "") === String(sup.id) ? "selected" : ""}>${esc(sup.title)}</option>`)
  ).join("");
  const amount = item ? ((Number(item.amount_minor || 0) / 100).toFixed(2)) : "";
  return `
    <form id="expenseForm" class="finance-form">
      <label>Категория<select name="category_id" required>${categoryOptions}</select></label>
      <label>Поставщик<select name="supplier_id">${supplierOptions}</select></label>
      <label>Сумма, ₽<input name="amount" type="text" placeholder="1200.00" value="${esc(amount)}" required /></label>
      <label>Дата расхода<input name="expense_date" type="date" value="${esc(item?.expense_date || `${state.month}-01`)}" required /></label>
      <label>Распределить на месяцев<input name="spread_months" type="number" min="1" max="120" value="${esc(String(item?.spread_months || 1))}" required /></label>
      <label>Комментарий<textarea name="comment" rows="4" placeholder="Комментарий">${esc(item?.comment || "")}</textarea></label>
      <div class="row gap-8 mt-12">
        <button class="btn" type="submit">${item ? "Сохранить" : "Добавить"}</button>
        <button class="btn ghost" type="button" id="expenseFormCancel">Отмена</button>
      </div>
    </form>
  `;
}

function openExpenseForm(expenseId = null) {
  if (!access.canEdit) return;
  if (!state.categories.length) {
    toast("Сначала создайте категорию расхода", "warn");
    return;
  }
  const item = expenseId ? state.expenses.find(x => Number(x.id) === Number(expenseId)) : null;
  openHtmlModal(expenseId ? "Редактировать расход" : "Добавить расход", buildExpenseForm(item));

  const form = document.getElementById("expenseForm");
  const cancelBtn = document.getElementById("expenseFormCancel");
  if (cancelBtn) cancelBtn.onclick = () => closeModal();
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const payload = {
      category_id: Number(fd.get("category_id")),
      supplier_id: fd.get("supplier_id") ? Number(fd.get("supplier_id")) : null,
      amount_minor: parseMoneyToMinor(fd.get("amount")),
      expense_date: String(fd.get("expense_date") || ""),
      spread_months: Number(fd.get("spread_months") || 1),
      comment: String(fd.get("comment") || "").trim() || null,
    };

    try {
      const venueId = getActiveVenueId();
      if (item) {
        await api(`/venues/${encodeURIComponent(venueId)}/expenses/${encodeURIComponent(item.id)}`, { method: "PATCH", body: payload });
        toast("Расход обновлён", "ok");
      } else {
        await api(`/venues/${encodeURIComponent(venueId)}/expenses`, { method: "POST", body: payload });
        toast("Расход добавлен", "ok");
      }
      closeModal();
      await loadExpenses();
    } catch (err) {
      toast(err?.data?.detail || err.message || "Не удалось сохранить расход", "err");
    }
  };
}

async function createCatalogItem(kind) {
  if (!access.canManageCatalogs) return;
  const title = prompt(kind === "category" ? "Название категории" : "Название поставщика");
  if (!title) return;
  const venueId = getActiveVenueId();
  try {
    if (kind === "category") {
      const baseCode = title.toLowerCase().trim().replace(/[^a-zа-яё0-9]+/gi, "_").replace(/^_+|_+$/g, "") || "expense";
      await api(`/venues/${encodeURIComponent(venueId)}/expense-categories`, {
        method: "POST",
        body: { code: baseCode, title: title.trim(), is_active: true, sort_order: state.categories.length },
      });
      toast("Категория добавлена", "ok");
    } else {
      const contact = prompt("Контакт поставщика", "") || "";
      await api(`/venues/${encodeURIComponent(venueId)}/suppliers`, {
        method: "POST",
        body: { title: title.trim(), contact, is_active: true, sort_order: state.suppliers.length },
      });
      toast("Поставщик добавлен", "ok");
    }
    await loadCatalogs();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось сохранить", "err");
  }
}

async function deleteExpense(expenseId) {
  if (!access.canEdit) return;
  if (!confirm("Удалить расход?")) return;
  try {
    const venueId = getActiveVenueId();
    await api(`/venues/${encodeURIComponent(venueId)}/expenses/${encodeURIComponent(expenseId)}`, { method: "DELETE" });
    toast("Расход удалён", "ok");
    await loadExpenses();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось удалить", "err");
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("expenses");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);

  await mountNav({ activeTab: "expenses", requireVenue: true });

  try {
    const venues = await getMyVenues();
    const v = venues.find(x => String(x.id) === String(getActiveVenueId()));
    if (v) document.getElementById("subtitle").textContent = v.name || "";
  } catch {}

  await loadAccess();
  syncToolbar();

  state.month = params.get("month") || currentMonth();
  const monthPick = document.getElementById("expensesMonthPick");
  if (monthPick) {
    monthPick.value = state.month;
    monthPick.onchange = async (e) => {
      state.month = e.target.value || currentMonth();
      await loadExpenses();
    };
  }

  document.getElementById("expenseCategoryFilter").onchange = async (e) => {
    state.categoryId = e.target.value || "";
    await loadExpenses();
  };
  document.getElementById("expenseSupplierFilter").onchange = async (e) => {
    state.supplierId = e.target.value || "";
    await loadExpenses();
  };
  document.getElementById("addExpenseBtn").onclick = () => openExpenseForm();
  document.getElementById("addCategoryBtn").onclick = () => createCatalogItem("category");
  document.getElementById("addSupplierBtn").onclick = () => createCatalogItem("supplier");

  try {
    await loadCatalogs();
    await loadExpenses();
  } catch (err) {
    document.getElementById("expensesList").innerHTML = `<div class="muted">${esc(err?.data?.detail || err.message || "Ошибка загрузки")}</div>`;
    document.getElementById("expensesState").textContent = "Ошибка";
  }
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

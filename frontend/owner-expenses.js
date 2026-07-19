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
  API_BASE,
  toast,
  closeModal,
  coerceDemoMonth,
  applyDemoReadonlyCaps,
  isDemoUiMode,
  getStoredDemoUiState,
  getDemoMonthLabel,
  mountDemoPageTour,
  trackDemoEvent,
} from "/app.js?v=20260719-split1";
import { permSetFromResponse, roleUpper, hasPerm, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js";

let financialValuesHidden = false;


const DEMO_EXPENSES_INTRO_DISMISSED_KEY = "axelio.demo_intro.owner_expenses.dismissed";

function renderDemoExpensesIntro() {
  const intro = document.getElementById("demoExpensesIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) { intro.classList.add("hidden"); return; }
  try { if (sessionStorage.getItem(DEMO_EXPENSES_INTRO_DISMISSED_KEY) === "1") { intro.classList.add("hidden"); return; } } catch {}
  const introText = document.getElementById("demoExpensesIntroText");
  if (introText) introText.textContent = `Подготовленные расходы за ${getDemoMonthLabel(demoState) || 'выбранный DEMO-период'}. Здесь видно признание по месяцу, категории и поставщиков.`;
  document.getElementById("demoExpensesGoSummary")?.addEventListener("click", () => { const venueId = getActiveVenueId(); if (venueId) location.href = `/owner-summary.html?venue_id=${encodeURIComponent(String(venueId))}`; });
  document.getElementById("demoExpensesGoPayroll")?.addEventListener("click", () => { const venueId = getActiveVenueId(); if (venueId) location.href = `/owner-payroll.html?venue_id=${encodeURIComponent(String(venueId))}`; });
  document.getElementById("demoExpensesIntroClose")?.addEventListener("click", () => { intro.classList.add("hidden"); try { sessionStorage.setItem(DEMO_EXPENSES_INTRO_DISMISSED_KEY, "1"); } catch {} });
  intro.classList.remove("hidden");
}

let access = {
  canView: false,
  canEdit: false,
  canManageCatalogs: false,
};

let state = {
  categories: [],
  suppliers: [],
  paymentMethods: [],
  expenses: [],
  month: "",
  categoryId: "",
  supplierId: "",
  statuses: "",
  stats: null,
};

async function openExportLink(path) {
  const data = await api(path);
  const url = data?.export_link || (data?.export_path ? `${API_BASE}${data.export_path}` : "");
  if (!url) throw new Error("export link missing");
  const tg = window.Telegram?.WebApp;
  try {
    if (tg?.openLink) {
      tg.openLink(url, { try_instant_view: false });
      return;
    }
  } catch {}
  window.location.href = url;
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return coerceDemoMonth(`${y}-${m}`, { notify: false, context: "owner-expenses" });
}

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function fmtMinor(minor) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
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

function ensureUniqueCategoryCode(baseCode) {
  const used = new Set((state.categories || []).map((it) => String(it?.code || "").trim().toLowerCase()).filter(Boolean));
  const code = String(baseCode || "").trim().toLowerCase() || "expense";
  if (!used.has(code)) return code;
  let idx = 2;
  while (used.has(`${code}_${idx}`)) idx += 1;
  return `${code}_${idx}`;
}

function slugifyCategoryCode(value) {
  const map = {
    а: "a", б: "b", в: "v", г: "g", д: "d", е: "e", ё: "e", ж: "zh", з: "z", и: "i",
    й: "y", к: "k", л: "l", м: "m", н: "n", о: "o", п: "p", р: "r", с: "s", т: "t",
    у: "u", ф: "f", х: "h", ц: "ts", ч: "ch", ш: "sh", щ: "sch", ъ: "", ы: "y",
    ь: "", э: "e", ю: "yu", я: "ya",
  };

  return String(value || "")
    .trim()
    .toLowerCase()
    .split("")
    .map((ch) => (map[ch] !== undefined ? map[ch] : ch))
    .join("")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
    .slice(0, 64) || "expense";
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

function statusLabel(status) {
  const norm = String(status || "DRAFT").toUpperCase();
  if (norm === "CONFIRMED") return "Подтверждён";
  if (norm === "CANCELLED") return "Отменён";
  return "Черновик";
}


function expenseStatusesLabel(value) {
  const norm = String(value || '').toUpperCase();
  if (!norm) return 'все статусы';
  if (norm === 'DRAFT') return 'только черновики';
  if (norm === 'CONFIRMED') return 'только подтверждённые';
  if (norm === 'CANCELLED') return 'только отменённые';
  if (norm === 'DRAFT,CONFIRMED') return 'черновики и подтверждённые';
  return norm;
}

function buildExpensesLink({ month = state.month, statuses = state.statuses } = {}) {
  const venueId = getActiveVenueId();
  const qp = new URLSearchParams();
  if (venueId) qp.set('venue_id', String(venueId));
  if (month) qp.set('month', String(month));
  if (statuses) qp.set('statuses', String(statuses));
  return `/owner-expenses.html?${qp.toString()}`;
}

function renderDraftBanner() {
  const card = document.getElementById('draftExpensesCard');
  const hint = document.getElementById('draftExpensesHint');
  const link = document.getElementById('openDraftExpensesBtn');
  const stats = state.stats || {};
  const draftCount = Number(stats.draft_count || 0);
  const draftTotalMinor = Number(stats.draft_total_minor || 0);
  if (link) link.href = buildExpensesLink({ statuses: 'DRAFT' });
  if (!card || !hint) return;
  if (draftCount <= 0) {
    card.style.display = 'none';
    hint.textContent = '—';
    return;
  }
  card.style.display = '';
  hint.textContent = `Черновиков: ${draftCount} · на сумму ${fmtMinor(draftTotalMinor)}. Они не участвуют в прибыли и сводке, пока не подтверждены.`;
}

function formatBytes(bytes) {
  const value = Number(bytes || 0);
  if (!Number.isFinite(value) || value <= 0) return "";
  if (value < 1024) return `${value} Б`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1).replace(".0", "")} КБ`;
  return `${(value / 1024 / 1024).toFixed(1).replace(".0", "")} МБ`;
}

function buildExpenseAttachmentsHtml(item) {
  const attachments = Array.isArray(item?.attachments) ? item.attachments : [];
  if (!attachments.length) return "";
  const links = attachments.map((file) => {
    const size = file.file_size ? ` · ${esc(formatBytes(file.file_size))}` : "";
    return `<button class="badge as-link" type="button" data-expense-file="${esc(item.id)}:${esc(file.id)}">📎 ${esc(file.file_name || "Файл")}${size}</button>`;
  }).join(" ");
  return `<div class="muted mt-8">Файлы</div><div class="expense-row__allocations mt-8">${links}</div>`;
}

function getExpenseAttachment(expenseId, attachmentId) {
  const expense = (state.expenses || []).find((item) => String(item.id) === String(expenseId));
  const files = Array.isArray(expense?.attachments) ? expense.attachments : [];
  return files.find((file) => String(file.id) === String(attachmentId)) || null;
}

function isPreviewableImage(contentType = "", fileName = "") {
  const ct = String(contentType || "").toLowerCase();
  const name = String(fileName || "").toLowerCase();
  return ct.startsWith("image/") || /\.(jpg|jpeg|png|webp|gif|bmp|svg)$/i.test(name);
}

function isPreviewablePdf(contentType = "", fileName = "") {
  const ct = String(contentType || "").toLowerCase();
  const name = String(fileName || "").toLowerCase();
  return ct === "application/pdf" || /\.pdf$/i.test(name);
}

async function deleteExpenseAttachment(expenseId, attachmentId) {
  const venueId = getActiveVenueId();
  await api(`/venues/${encodeURIComponent(venueId)}/expenses/${encodeURIComponent(expenseId)}/attachments/${encodeURIComponent(attachmentId)}`, {
    method: "DELETE",
  });
}

async function openExpenseAttachmentPreview(expenseId, attachmentId) {
  const venueId = getActiveVenueId();
  const file = getExpenseAttachment(expenseId, attachmentId) || {};
  try {
    const data = await api(`/venues/${encodeURIComponent(venueId)}/expenses/${encodeURIComponent(expenseId)}/attachments/${encodeURIComponent(attachmentId)}/download-link`);
    const url = data?.preview_link || data?.download_link;
    if (!url) throw new Error("download link missing");
    const name = data?.file?.file_name || file.file_name || "Файл";
    const contentType = data?.file?.content_type || file.content_type || "";
    const size = data?.file?.file_size || file.file_size || 0;
    let previewHtml = `<div class="muted">${esc(contentType || "Файл")} ${size ? `· ${esc(formatBytes(size))}` : ""}</div>`;
    if (isPreviewableImage(contentType, name)) {
      previewHtml += `<div class="file-preview"><img src="${esc(url)}" alt="${esc(name)}" /></div>`;
    } else if (isPreviewablePdf(contentType, name)) {
      previewHtml += `<div class="file-preview"><iframe src="${esc(url)}" title="${esc(name)}"></iframe></div>`;
    } else {
      previewHtml += `<div class="card subtle mt-12">Предпросмотр для этого формата может быть недоступен в браузере. Файл можно открыть или скачать по внешней ссылке.</div>`;
    }
    previewHtml += `
      <div class="file-preview-actions row gap-8 mt-12" style="flex-wrap:wrap;">
        <button class="btn primary" type="button" id="expenseFileDownloadBtn">Открыть / скачать файл</button>
        ${access.canEdit ? `<button class="btn danger" type="button" id="expenseFileDeleteBtn">Удалить файл</button>` : ""}
        <button class="btn ghost" type="button" id="expenseFileCloseBtn">Закрыть</button>
      </div>
    `;
    openHtmlModal(name, previewHtml);
    const downloadBtn = document.getElementById("expenseFileDownloadBtn");
    if (downloadBtn) downloadBtn.onclick = () => {
      const tg = window.Telegram?.WebApp;
      try { if (tg?.openLink) { tg.openLink(url, { try_instant_view: false }); return; } } catch {}
      window.open(url, "_blank", "noopener");
    };
    const deleteBtn = document.getElementById("expenseFileDeleteBtn");
    if (deleteBtn) deleteBtn.onclick = async () => {
      if (!confirm("Удалить этот файл?")) return;
      deleteBtn.disabled = true;
      try {
        await deleteExpenseAttachment(expenseId, attachmentId);
        toast("Файл удалён", "ok");
        closeModal();
        await loadExpenses();
      } catch (err) {
        deleteBtn.disabled = false;
        toast(err?.data?.detail || err.message || "Не удалось удалить файл", "err");
      }
    };
    const closeBtn = document.getElementById("expenseFileCloseBtn");
    if (closeBtn) closeBtn.onclick = () => closeModal();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось открыть файл", "err");
  }
}

async function uploadExpenseFiles(expenseId, files) {
  const selected = Array.from(files || []).filter(Boolean);
  if (!selected.length) return;
  const venueId = getActiveVenueId();
  const fd = new FormData();
  selected.forEach((file) => fd.append("files", file));
  await api(`/venues/${encodeURIComponent(venueId)}/expenses/${encodeURIComponent(expenseId)}/attachments`, {
    method: "POST",
    body: fd,
    timeoutMs: 120000,
  });
}

function buildRegularBadges(item) {
  const badges = [];
  if (item?.recurring_rule_id) badges.push('<span class="badge">Регулярный</span>');
  if (item?.generated_for_month) badges.push(`<span class="badge">${esc(`Сгенерирован ${item.generated_for_month}`)}</span>`);
  return badges.join(' ');
}

function expenseFormDraftFromItem(item = null) {
  return {
    category_id: item?.category_id ? String(item.category_id) : "",
    supplier_id: item?.supplier_id ? String(item.supplier_id) : "",
    payment_method_id: item?.payment_method_id ? String(item.payment_method_id) : "",
    amount: item ? (Number(item.amount_minor || 0) / 100).toFixed(2) : "",
    expense_date: item?.expense_date || todayISO(),
    spread_months: String(item?.spread_months || 1),
    status: String(item?.status || "DRAFT").toUpperCase(),
    comment: item?.comment || "",
  };
}

function normalizeExpenseDraft(draft = {}) {
  return {
    category_id: draft?.category_id ? String(draft.category_id) : "",
    supplier_id: draft?.supplier_id ? String(draft.supplier_id) : "",
    payment_method_id: draft?.payment_method_id ? String(draft.payment_method_id) : "",
    amount: String(draft?.amount || ""),
    expense_date: String(draft?.expense_date || todayISO()),
    spread_months: String(draft?.spread_months || 1),
    status: String(draft?.status || "DRAFT").toUpperCase(),
    comment: String(draft?.comment || ""),
  };
}

function readExpenseFormDraft(form) {
  const fd = new FormData(form);
  return normalizeExpenseDraft({
    category_id: fd.get("category_id"),
    supplier_id: fd.get("supplier_id"),
    payment_method_id: fd.get("payment_method_id"),
    amount: fd.get("amount"),
    expense_date: fd.get("expense_date"),
    spread_months: fd.get("spread_months"),
    status: fd.get("status"),
    comment: fd.get("comment"),
  });
}


async function loadAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return access;
  try {
    const permsResp = await getMyVenuePermissions(venueId);
    financialValuesHidden = isFinancialValuesHidden(permsResp);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isOwner = role === "OWNER" || role === "VENUE_OWNER";
    access = applyDemoReadonlyCaps({
      canView: isOwner || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD"),
      canEdit: isOwner || hasPerm(pset, "EXPENSE_ADD"),
      canManageCatalogs: isOwner || hasPerm(pset, "EXPENSE_CATEGORIES_MANAGE"),
    }, { source: permsResp });
  } catch {
    access = { canView: false, canEdit: false, canManageCatalogs: false };
  }
  return access;
}

function fillSelect(el, items, { placeholder }) {
  if (!el) return;
  const current = el.value;
  el.innerHTML = `<option value="">${placeholder}</option>` + items.map((item) => {
    return `<option value="${item.id}">${esc(item.title)}</option>`;
  }).join("");
  if (current && items.some((item) => String(item.id) === String(current))) el.value = current;
}

function syncToolbar() {
  const addExpenseBtn = document.getElementById("addExpenseBtn");
  const exportExpensesBtn = document.getElementById("exportExpensesBtn");
  const addCategoryBtn = document.getElementById("addCategoryBtn");
  const addSupplierBtn = document.getElementById("addSupplierBtn");
  const openRecurringExpensesBtn = document.getElementById("openRecurringExpensesBtn");
  const openExpenseCategoriesBtn = document.getElementById("openExpenseCategoriesBtn");
  const openSuppliersBtn = document.getElementById("openSuppliersBtn");
  if (addExpenseBtn) addExpenseBtn.style.display = access.canEdit ? "" : "none";
  if (exportExpensesBtn) exportExpensesBtn.style.display = access.canView ? "" : "none";
  if (addCategoryBtn) addCategoryBtn.style.display = access.canManageCatalogs ? "" : "none";
  if (addSupplierBtn) addSupplierBtn.style.display = access.canManageCatalogs ? "" : "none";
  if (openRecurringExpensesBtn) openRecurringExpensesBtn.style.display = access.canView ? "" : "none";
  if (openExpenseCategoriesBtn) openExpenseCategoriesBtn.style.display = access.canManageCatalogs ? "" : "none";
  if (openSuppliersBtn) openSuppliersBtn.style.display = access.canManageCatalogs ? "" : "none";
}

async function loadCatalogs() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  const [categories, suppliers, paymentMethods] = await Promise.all([
    api(`/venues/${encodeURIComponent(venueId)}/expense-categories`),
    api(`/venues/${encodeURIComponent(venueId)}/suppliers`),
    api(`/venues/${encodeURIComponent(venueId)}/payment-methods`).catch(() => []),
  ]);
  state.categories = Array.isArray(categories) ? categories : [];
  state.suppliers = Array.isArray(suppliers) ? suppliers : [];
  state.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];

  fillSelect(document.getElementById("expenseCategoryFilter"), state.categories, { placeholder: "Все категории" });
  fillSelect(document.getElementById("expenseSupplierFilter"), state.suppliers, { placeholder: "Все поставщики" });
}


async function loadExpenseStats() {
  const venueId = getActiveVenueId();
  if (!venueId || !access.canView) {
    state.stats = null;
    renderDraftBanner();
    return;
  }
  const qp = new URLSearchParams();
  qp.set('month', state.month || currentMonth());
  if (state.categoryId) qp.set('category_id', state.categoryId);
  if (state.supplierId) qp.set('supplier_id', state.supplierId);
  if (state.statuses) qp.set('statuses', state.statuses);
  try {
    state.stats = await api(`/venues/${encodeURIComponent(venueId)}/expenses/stats?${qp.toString()}`);
  } catch {
    state.stats = null;
  }
  renderDraftBanner();
}

async function loadExpenses() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  if (!access.canView) {
    document.getElementById("expensesList").innerHTML = `<div class="muted">Нет прав на просмотр расходов.</div>`;
    document.getElementById("expensesState").textContent = "Доступ ограничен";
    document.getElementById("expensesTotalMinor").textContent = "—";
    document.getElementById("expensesCount").textContent = "—";
    state.stats = null;
    renderDraftBanner();
    return;
  }

  const qp = new URLSearchParams();
  qp.set("month", state.month || currentMonth());
  if (state.categoryId) qp.set("category_id", state.categoryId);
  if (state.supplierId) qp.set("supplier_id", state.supplierId);
  if (state.statuses) qp.set("statuses", state.statuses);

  const [rows] = await Promise.all([
    api(`/venues/${encodeURIComponent(venueId)}/expenses?${qp.toString()}`),
    loadExpenseStats(),
  ]);
  state.expenses = Array.isArray(rows) ? rows : [];
  renderExpenses();
}

function renderExpenses() {
  const list = document.getElementById("expensesList");
  const totalEl = document.getElementById("expensesTotalMinor");
  const countEl = document.getElementById("expensesCount");
  const stateEl = document.getElementById("expensesState");
  if (!list) return;

  const recognizedTotalMinor = state.expenses.reduce((acc, item) => acc + Number(item.recognized_amount_minor_for_month || 0), 0);
  if (totalEl) totalEl.textContent = fmtMinor(recognizedTotalMinor);
  if (countEl) countEl.textContent = String(state.expenses.length);
  if (stateEl) stateEl.textContent = state.expenses.length
    ? `Месяц ${state.month} · ${expenseStatusesLabel(state.statuses)} · признано ${fmtMinor(recognizedTotalMinor)}`
    : `За ${state.month} расходов нет (${expenseStatusesLabel(state.statuses)})`;

  if (!state.expenses.length) {
    list.innerHTML = `<div class="muted">Нет расходов за выбранный период.</div>`;
    return;
  }

  list.innerHTML = state.expenses.map((item) => {
    const allocs = Array.isArray(item.allocations) ? item.allocations : [];
    const recognizedAllocs = Array.isArray(item.recognized_allocations) ? item.recognized_allocations : [];
    const allocationsHtml = allocs.map((a) => `<span class="badge">${esc(a.month)} · ${esc(fmtMinor(a.amount_minor))}</span>`).join(" ");
    const recognizedHtml = recognizedAllocs.length
      ? recognizedAllocs.map((a) => `<span class="badge">${esc(a.month)} · ${esc(fmtMinor(a.amount_minor))}</span>`).join(" ")
      : `<span class="muted">В выбранном месяце не признаётся</span>`;
    const status = String(item.status || "DRAFT").toUpperCase();
    const quickActions = access.canEdit ? `
      <div class="row gap-8 mt-10" style="flex-wrap:wrap; justify-content:flex-end;">
        ${status !== "CONFIRMED" ? `<button class="btn small" data-status="CONFIRMED" data-id="${item.id}">Подтвердить</button>` : ""}
        ${status !== "DRAFT" ? `<button class="btn ghost small" data-status="DRAFT" data-id="${item.id}">В черновик</button>` : ""}
        ${status !== "CANCELLED" ? `<button class="btn ghost small" data-status="CANCELLED" data-id="${item.id}">Отменить</button>` : ""}
        <button class="btn small" data-edit="${item.id}">Изменить</button>
        <button class="btn danger small" data-del="${item.id}">Удалить</button>
      </div>` : "";
    return `
      <div class="expense-row">
        <div class="expense-row__main">
          <div class="row" style="gap:8px; flex-wrap:wrap; align-items:center;">
            <div class="expense-row__title">${esc(item.category?.title || "Без категории")}</div>
            <span class="badge">${esc(statusLabel(status))}</span>
            ${buildRegularBadges(item)}
          </div>
          <div class="muted mt-6">${esc(item.expense_date || "—")}${item.supplier?.title ? ` · ${esc(item.supplier.title)}` : ""}${item.payment_method?.title ? ` · ${esc(item.payment_method.title)}` : ""}</div>
          ${item.comment ? `<div class="mt-8">${esc(item.comment)}</div>` : ""}
          <div class="mt-8"><b>Признано в ${esc(state.month)}:</b> ${esc(fmtMinor(item.recognized_amount_minor_for_month || 0))}</div>
          ${item.recurring_rule_id ? `<div class="muted mt-6">Это документ, созданный из правила регулярного расхода. После подтверждения он будет участвовать в расходах и сводке.</div>` : ''}
          <div class="expense-row__allocations mt-8">${recognizedHtml}</div>
          <div class="muted mt-8">Все аллокации</div>
          <div class="expense-row__allocations mt-8">${allocationsHtml || '<span class="muted">Без распределения</span>'}</div>
          ${buildExpenseAttachmentsHtml(item)}
        </div>
        <div class="expense-row__side">
          <div class="expense-row__amount">${esc(fmtMinor(item.amount_minor))}</div>
          <div class="muted mt-6">Полная сумма</div>
          ${quickActions}
        </div>
      </div>
    `;
  }).join("");

  list.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.onclick = () => openExpenseForm(Number(btn.getAttribute("data-edit")));
  });
  list.querySelectorAll("[data-del]").forEach((btn) => {
    btn.onclick = () => deleteExpense(Number(btn.getAttribute("data-del")));
  });
  list.querySelectorAll("[data-status]").forEach((btn) => {
    btn.onclick = async () => {
      try {
        const expenseId = Number(btn.getAttribute("data-id"));
        const status = String(btn.getAttribute("data-status") || "DRAFT");
        await updateExpenseStatus(expenseId, status);
      } catch (err) {
        toast(err?.data?.detail || err.message || "Не удалось обновить статус", "err");
      }
    };
  });
  list.querySelectorAll("[data-expense-file]").forEach((btn) => {
    btn.onclick = () => {
      const [expenseId, attachmentId] = String(btn.getAttribute("data-expense-file") || "").split(":");
      if (expenseId && attachmentId) openExpenseAttachmentPreview(expenseId, attachmentId);
    };
  });
}

function buildExpenseForm(draft = null) {
  const data = normalizeExpenseDraft(draft || {});
  const categoryOptions = state.categories.map((cat) => `<option value="${cat.id}" ${String(data.category_id || "") === String(cat.id) ? "selected" : ""}>${esc(cat.title)}</option>`).join("");
  const supplierOptions = ['<option value="">Без поставщика</option>'].concat(
    state.suppliers.map((sup) => `<option value="${sup.id}" ${String(data.supplier_id || "") === String(sup.id) ? "selected" : ""}>${esc(sup.title)}</option>`)
  ).join("");
  const paymentMethodOptions = ['<option value="">Не указан</option>'].concat(
    state.paymentMethods.map((pm) => `<option value="${pm.id}" ${String(data.payment_method_id || "") === String(pm.id) ? "selected" : ""}>${esc(pm.title)}</option>`)
  ).join("");
  const inlineCatalogActions = access.canManageCatalogs ? `
      <div class="inline-actions">
        <button class="btn subtle inline" type="button" id="expenseAddCategoryInline">+ Добавить категорию</button>
      </div>
      <div class="inline-actions">
        <button class="btn subtle inline" type="button" id="expenseAddSupplierInline">+ Добавить поставщика</button>
      </div>
  ` : "";
  return `
    <form id="expenseForm" class="finance-form">
      <label>Категория<select name="category_id" required>${categoryOptions}</select></label>
      ${access.canManageCatalogs ? `<div class="inline-note">Нужной категории нет? Создай её прямо из формы и продолжай ввод расхода без потери данных.</div>` : ``}
      ${access.canManageCatalogs ? `<div class="inline-actions"><button class="btn subtle inline" type="button" id="expenseAddCategoryInline">+ Добавить категорию</button></div>` : ``}
      <label>Поставщик<select name="supplier_id">${supplierOptions}</select></label>
      ${access.canManageCatalogs ? `<div class="inline-actions"><button class="btn subtle inline" type="button" id="expenseAddSupplierInline">+ Добавить поставщика</button></div>` : ``}
      <label>Оплачено через<select name="payment_method_id">${paymentMethodOptions}</select></label>
      <label>Сумма, ₽<input name="amount" type="text" placeholder="1200.00" value="${esc(data.amount)}" required /></label>
      <label>Дата расхода<input name="expense_date" type="date" value="${esc(data.expense_date)}" required /></label>
      <label>Распределить на месяцев<input name="spread_months" type="number" min="1" max="120" value="${esc(data.spread_months)}" required /></label>
      <label>Статус
        <select name="status">
          <option value="DRAFT" ${data.status === "DRAFT" ? "selected" : ""}>Черновик</option>
          <option value="CONFIRMED" ${data.status === "CONFIRMED" ? "selected" : ""}>Подтверждён</option>
          <option value="CANCELLED" ${data.status === "CANCELLED" ? "selected" : ""}>Отменён</option>
        </select>
      </label>
      <label>Комментарий<textarea name="comment" rows="4" placeholder="Комментарий">${esc(data.comment)}</textarea></label>
      <label>Файлы к расходу
        <input name="expense_files" type="file" multiple accept=".pdf,.jpg,.jpeg,.png,.webp,.heic,.doc,.docx,.xls,.xlsx,.csv,.txt,.rtf,.zip,.rar,application/pdf,image/*" />
      </label>
      <div class="muted small">Поддерживаются PDF, изображения, документы, таблицы, CSV/TXT и архивы. До 20 МБ на файл.</div>
      <div class="row gap-8 mt-12">
        <button class="btn primary" type="submit">${draft?.id ? "Сохранить" : "Добавить"}</button>
        <button class="btn ghost" type="button" id="expenseFormCancel">Отмена</button>
      </div>
    </form>
  `;
}

function openExpenseForm(expenseId = null, draftValues = null) {
  if (!access.canEdit) return;
  if (!state.categories.length) {
    toast("Сначала создайте категорию расхода", "warn");
    return;
  }
  const item = expenseId ? state.expenses.find((x) => Number(x.id) === Number(expenseId)) : null;
  const formDraft = { ...expenseFormDraftFromItem(item), ...(draftValues || {}) };
  if (item?.id) formDraft.id = item.id;
  openHtmlModal(expenseId ? "Редактировать расход" : "Добавить расход", buildExpenseForm(formDraft));

  const form = document.getElementById("expenseForm");
  const cancelBtn = document.getElementById("expenseFormCancel");
  const addCategoryInlineBtn = document.getElementById("expenseAddCategoryInline");
  const addSupplierInlineBtn = document.getElementById("expenseAddSupplierInline");
  if (cancelBtn) cancelBtn.onclick = () => closeModal();
  if (addCategoryInlineBtn && form) {
    addCategoryInlineBtn.onclick = () => openCatalogForm("category", {
      reopenExpenseForm: true,
      expenseId,
      draft: readExpenseFormDraft(form),
    });
  }
  if (addSupplierInlineBtn && form) {
    addSupplierInlineBtn.onclick = () => openCatalogForm("supplier", {
      reopenExpenseForm: true,
      expenseId,
      draft: readExpenseFormDraft(form),
    });
  }
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const payload = {
      category_id: Number(fd.get("category_id")),
      supplier_id: fd.get("supplier_id") ? Number(fd.get("supplier_id")) : null,
      payment_method_id: fd.get("payment_method_id") ? Number(fd.get("payment_method_id")) : null,
      amount_minor: parseMoneyToMinor(fd.get("amount")),
      expense_date: String(fd.get("expense_date") || ""),
      spread_months: Number(fd.get("spread_months") || 1),
      status: String(fd.get("status") || "DRAFT"),
      comment: String(fd.get("comment") || "").trim() || null,
    };

    try {
      const venueId = getActiveVenueId();
      let saved = null;
      if (item) {
        saved = await api(`/venues/${encodeURIComponent(venueId)}/expenses/${encodeURIComponent(item.id)}`, { method: "PATCH", body: payload });
      } else {
        saved = await api(`/venues/${encodeURIComponent(venueId)}/expenses`, { method: "POST", body: payload });
      }
      const targetExpenseId = Number(saved?.id || item?.id || 0);
      const filesInput = form.querySelector('input[name="expense_files"]');
      if (targetExpenseId && filesInput?.files?.length) {
        await uploadExpenseFiles(targetExpenseId, filesInput.files);
      }
      toast(item ? "Расход обновлён" : "Расход добавлен", "ok");
      closeModal();
      await loadExpenses();
    } catch (err) {
      toast(err?.data?.detail || err.message || "Не удалось сохранить расход", "err");
    }
  };
}

async function updateExpenseStatus(expenseId, status) {
  const venueId = getActiveVenueId();
  await api(`/venues/${encodeURIComponent(venueId)}/expenses/${encodeURIComponent(expenseId)}`, {
    method: "PATCH",
    body: { status },
  });
  toast("Статус расхода обновлён", "ok");
  await loadExpenses();
}

function buildCatalogForm(kind) {
  const isCategory = kind === "category";
  return `
    <form id="catalogForm" class="finance-form">
      <label>
        Название
        <input name="title" type="text" maxlength="120" placeholder="${isCategory ? "Например: Аренда" : "Например: ООО Поставщик"}" required />
      </label>

      ${isCategory
        ? `<div class="muted">Код будет сгенерирован автоматически из названия.</div>`
        : `
        <label>
          Контакт
          <input name="contact" type="text" maxlength="255" placeholder="+7..., Telegram, email" />
        </label>
      `}

      <div class="row gap-8 mt-12">
        <button class="btn" type="submit">${isCategory ? "Добавить категорию" : "Добавить поставщика"}</button>
        <button class="btn ghost" type="button" id="catalogFormCancel">Отмена</button>
      </div>
    </form>
  `;
}

function openCatalogForm(kind, options = {}) {
  if (!access.canManageCatalogs) return;
  const isCategory = kind === "category";
  openHtmlModal(isCategory ? "Добавить категорию расхода" : "Добавить поставщика", buildCatalogForm(kind));

  const form = document.getElementById("catalogForm");
  const cancelBtn = document.getElementById("catalogFormCancel");
  if (cancelBtn) cancelBtn.onclick = () => closeModal();
  if (!form) return;

  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const title = String(fd.get("title") || "").trim();
    const contact = String(fd.get("contact") || "").trim();

    if (!title) {
      toast("Введите название", "warn");
      return;
    }

    const venueId = getActiveVenueId();
    try {
      let created = null;
      if (isCategory) {
        const baseCode = ensureUniqueCategoryCode(slugifyCategoryCode(title));
        created = await api(`/venues/${encodeURIComponent(venueId)}/expense-categories`, {
          method: "POST",
          body: {
            code: baseCode,
            title,
            is_active: true,
            sort_order: state.categories.length,
          },
        });
        toast("Категория добавлена", "ok");
      } else {
        created = await api(`/venues/${encodeURIComponent(venueId)}/suppliers`, {
          method: "POST",
          body: {
            title,
            contact: contact || null,
            is_active: true,
            sort_order: state.suppliers.length,
          },
        });
        toast("Поставщик добавлен", "ok");
      }

      await loadCatalogs();

      if (options.reopenExpenseForm) {
        const catalogItems = isCategory ? state.categories : state.suppliers;
        const matched = catalogItems.find((item) => String(item.id) === String(created?.id))
          || catalogItems.find((item) => String(item.title || "").trim().toLowerCase() === title.toLowerCase());
        const nextDraft = normalizeExpenseDraft(options.draft || {});
        if (isCategory) nextDraft.category_id = matched?.id ? String(matched.id) : nextDraft.category_id;
        else nextDraft.supplier_id = matched?.id ? String(matched.id) : nextDraft.supplier_id;
        openExpenseForm(options.expenseId || null, nextDraft);
        return;
      }

      closeModal();
    } catch (err) {
      toast(err?.data?.detail || err.message || "Не удалось сохранить", "err");
    }
  };
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
  renderDemoExpensesIntro();

  try {
    const venues = await getMyVenues();
    const v = venues.find((x) => String(x.id) === String(getActiveVenueId()));
    if (v) document.getElementById("subtitle").textContent = v.name || "";
  } catch {}

  await loadAccess();
  syncToolbar();

  const activeVenueId = getActiveVenueId();
  const openRecurringExpensesBtn = document.getElementById("openRecurringExpensesBtn");
  const openExpenseCategoriesBtn = document.getElementById("openExpenseCategoriesBtn");
  const openSuppliersBtn = document.getElementById("openSuppliersBtn");
  if (openRecurringExpensesBtn) openRecurringExpensesBtn.href = `/owner-recurring-expenses.html?venue_id=${encodeURIComponent(activeVenueId)}`;
  if (openExpenseCategoriesBtn) openExpenseCategoriesBtn.href = `/owner-expense-categories.html?venue_id=${encodeURIComponent(activeVenueId)}`;
  if (openSuppliersBtn) openSuppliersBtn.href = `/owner-suppliers.html?venue_id=${encodeURIComponent(activeVenueId)}`;

  state.month = coerceDemoMonth(params.get("month") || currentMonth(), { notify: false, context: "owner-expenses" });
  state.statuses = params.get("statuses") || "";
  const monthPick = document.getElementById("expensesMonthPick");
  if (monthPick) {
    monthPick.value = state.month;
    monthPick.onchange = async (e) => {
      state.month = coerceDemoMonth(e.target.value || currentMonth(), { context: "owner-expenses" });
      await loadExpenses();
    };
  }

  const statusFilter = document.getElementById("expenseStatusFilter");
  if (statusFilter) {
    statusFilter.value = state.statuses;
    statusFilter.onchange = async (e) => {
      state.statuses = e.target.value || "";
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
  const toggleExpenseFiltersBtn = document.getElementById("toggleExpenseFiltersBtn");
  const expenseFiltersWrap = document.getElementById("expenseFiltersWrap");
  if (toggleExpenseFiltersBtn && expenseFiltersWrap) {
    toggleExpenseFiltersBtn.onclick = () => {
      expenseFiltersWrap.open = true;
      expenseFiltersWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
    };
  }
  document.getElementById("exportExpensesBtn").onclick = async () => {
    try {
      const venueId = getActiveVenueId();
      const qp = new URLSearchParams();
      qp.set("month", state.month || currentMonth());
      if (state.categoryId) qp.set("category_id", state.categoryId);
      if (state.supplierId) qp.set("supplier_id", state.supplierId);
      if (state.statuses) qp.set("statuses", state.statuses);
      await openExportLink(`/venues/${encodeURIComponent(venueId)}/expenses/export-link?${qp.toString()}`);
    } catch (err) {
      toast(err?.data?.detail || err?.message || "Не удалось начать экспорт", "err");
    }
  };
  document.getElementById("addCategoryBtn").onclick = () => openCatalogForm("category");
  document.getElementById("addSupplierBtn").onclick = () => openCatalogForm("supplier");

  try {
    await loadCatalogs();
    await loadExpenses();
  } catch (err) {
    document.getElementById("expensesList").innerHTML = `<div class="muted">${esc(err?.data?.detail || err.message || "Ошибка загрузки")}</div>`;
    document.getElementById("expensesState").textContent = "Ошибка";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  boot();
});


function mountDemoFlowTour() {
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) return;
  const venue = getActiveVenueId();
  const q = venue ? `?venue_id=${encodeURIComponent(String(venue))}` : "";
  mountDemoPageTour({
    tourId: "demo-owner-flow",
    step: 2,
    total: 4,
    title: "Продолжение DEMO-тура",
    text: "На этом шаге видно, как расходы собраны по категориям и как они влияют на экономику месяца.",
    prevPath: `/owner-summary.html${q}`,
    nextPath: `/owner-payroll.html${q}`,
  });
}

try { mountDemoFlowTour(); } catch {}

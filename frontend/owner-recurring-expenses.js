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

let access = { canView: false, canManage: false };
let state = {
  month: "",
  rules: [],
  categories: [],
  suppliers: [],
  paymentMethods: [],
  generationResult: null,
};

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function currentMonth() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
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

function openHtmlModal(title, html) {
  const m = document.getElementById("modal");
  if (!m) return;
  const head = m.querySelector(".modal__title");
  const body = m.querySelector(".modal__body");
  if (head) head.textContent = title;
  if (body) body.innerHTML = html;
  m.classList.add("open");
}

function fillSelectOptions(items, current, placeholder = "—") {
  return [`<option value="">${placeholder}</option>`].concat(
    (items || []).map((item) => `<option value="${item.id}" ${String(current || "") === String(item.id) ? "selected" : ""}>${esc(item.title)}</option>`)
  ).join("");
}

function modeLabel(mode) {
  return String(mode || "FIXED").toUpperCase() === "PERCENT" ? "Процент" : "Фикс";
}

function statusBadge(isActive) {
  return isActive ? "<span class=\"badge\">Активно</span>" : "<span class=\"badge\">Выключено</span>";
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
      canView: isOwner || hasPerm(pset, "RECURRING_EXPENSES_VIEW") || hasPerm(pset, "EXPENSE_VIEW") || hasPerm(pset, "EXPENSE_ADD"),
      canManage: isOwner || hasPerm(pset, "RECURRING_EXPENSES_MANAGE") || hasPerm(pset, "EXPENSE_ADD"),
    };
  } catch {
    access = { canView: false, canManage: false };
  }
  return access;
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
}

async function loadRules() {
  if (!access.canView) {
    document.getElementById("rulesList").innerHTML = `<div class="muted">Нет прав на просмотр правил.</div>`;
    document.getElementById("rulesState").textContent = "Доступ ограничен";
    renderGenerationResult();
    return;
  }
  const venueId = getActiveVenueId();
  state.rules = await api(`/venues/${encodeURIComponent(venueId)}/recurring-expense-rules`);
  renderRules();
}

function renderRules() {
  const list = document.getElementById("rulesList");
  const countEl = document.getElementById("rulesCount");
  const activeCountEl = document.getElementById("rulesActiveCount");
  const stateEl = document.getElementById("rulesState");
  if (!list) return;

  const rules = Array.isArray(state.rules) ? state.rules : [];
  const activeCount = rules.filter((x) => x.is_active).length;
  if (countEl) countEl.textContent = String(rules.length);
  if (activeCountEl) activeCountEl.textContent = String(activeCount);
  if (stateEl) stateEl.textContent = rules.length ? `Месяц генерации: ${state.month}` : "Правил пока нет";

  if (!rules.length) {
    list.innerHTML = `<div class="muted">Нет правил регулярных расходов.</div>`;
    renderGenerationResult();
    return;
  }

  list.innerHTML = rules.map((item) => {
    const basis = Array.isArray(item.basis_payment_methods) ? item.basis_payment_methods : [];
    const mode = String(item.generation_mode || "FIXED").toUpperCase();
    const amountText = mode === "PERCENT"
      ? `${(Number(item.percent_bps || 0) / 100).toFixed(2)}%`
      : fmtMinor(item.amount_minor || 0);
    const basisText = mode === "PERCENT"
      ? (basis.length ? basis.map((x) => esc(x.title)).join(", ") : "Все типы оплат")
      : (item.payment_method?.title ? `Списывать через ${esc(item.payment_method.title)}` : "Тип оплаты не указан");
    const actions = access.canManage ? `
      <div class="row gap-8 mt-10" style="flex-wrap:wrap; justify-content:flex-end;">
        <button class="btn small" data-generate="${item.id}">Сгенерировать</button>
        <button class="btn small" data-edit="${item.id}">Изменить</button>
        <button class="btn danger small" data-del="${item.id}">Удалить</button>
      </div>` : "";
    return `
      <div class="expense-row">
        <div class="expense-row__main">
          <div class="row" style="gap:8px; flex-wrap:wrap; align-items:center;">
            <div class="expense-row__title">${esc(item.title || "Без названия")}</div>
            <span class="badge">${esc(modeLabel(mode))}</span>
            ${statusBadge(item.is_active)}
          </div>
          <div class="muted mt-6">${esc(item.category?.title || "Без категории")}${item.supplier?.title ? ` · ${esc(item.supplier.title)}` : ""}</div>
          <div class="mt-8"><b>${mode === "PERCENT" ? "Ставка" : "Сумма"}:</b> ${esc(amountText)}</div>
          <div class="mt-8"><b>Период действия:</b> ${esc(item.start_date || "—")} → ${esc(item.end_date || "∞")}</div>
          <div class="mt-8"><b>День месяца:</b> ${esc(item.day_of_month || 1)} · <b>Размазать на:</b> ${esc(item.spread_months || 1)} мес.</div>
          <div class="mt-8"><b>База/списание:</b> ${basisText}</div>
          ${item.description ? `<div class="mt-8">${esc(item.description)}</div>` : ""}
        </div>
        <div class="expense-row__side">
          <div class="expense-row__amount">${esc(amountText)}</div>
          <div class="muted mt-6">${mode === "PERCENT" ? "Расчётный режим" : "Фиксированный режим"}</div>
          ${actions}
        </div>
      </div>
    `;
  }).join("");

  list.querySelectorAll("[data-edit]").forEach((btn) => {
    btn.onclick = () => openRuleForm(Number(btn.getAttribute("data-edit")));
  });
  list.querySelectorAll("[data-del]").forEach((btn) => {
    btn.onclick = () => deleteRule(Number(btn.getAttribute("data-del")));
  });
  list.querySelectorAll("[data-generate]").forEach((btn) => {
    btn.onclick = () => generateRules(Number(btn.getAttribute("data-generate")));
  });
  renderGenerationResult();
}

function buildBasisPaymentMethodCheckboxes(selectedIds = []) {
  const selected = new Set((selectedIds || []).map((x) => String(x)));
  if (!state.paymentMethods.length) return `<div class="muted">Нет типов оплат.</div>`;
  return state.paymentMethods.map((pm) => `
    <label style="display:flex; gap:8px; align-items:center; font-weight:600; color:inherit;">
      <input type="checkbox" name="basis_payment_method_ids" value="${pm.id}" ${selected.has(String(pm.id)) ? "checked" : ""} />
      <span>${esc(pm.title)}</span>
    </label>
  `).join("");
}

function buildRuleForm(item = null) {
  const isPercent = String(item?.generation_mode || "FIXED").toUpperCase() === "PERCENT";
  return `
    <form id="ruleForm" class="finance-form">
      <label>Название<input name="title" type="text" maxlength="160" value="${esc(item?.title || "")}" required /></label>
      <label>Категория<select name="category_id" required>${fillSelectOptions(state.categories, item?.category_id, "Выбери категорию")}</select></label>
      <label>Поставщик<select name="supplier_id">${fillSelectOptions(state.suppliers, item?.supplier_id, "Без поставщика")}</select></label>
      <label>Оплачивать через<select name="payment_method_id">${fillSelectOptions(state.paymentMethods, item?.payment_method_id, "Не указан")}</select></label>
      <label>Дата старта<input name="start_date" type="date" value="${esc(item?.start_date || todayISO())}" required /></label>
      <label>Дата окончания<input name="end_date" type="date" value="${esc(item?.end_date || "")}" /></label>
      <label>День месяца<input name="day_of_month" type="number" min="1" max="31" value="${esc(String(item?.day_of_month || 1))}" required /></label>
      <label>Распределить на месяцев<input name="spread_months" type="number" min="1" max="120" value="${esc(String(item?.spread_months || 1))}" required /></label>
      <label>Режим
        <select name="generation_mode" id="ruleMode">
          <option value="FIXED" ${!isPercent ? "selected" : ""}>Фиксированная сумма</option>
          <option value="PERCENT" ${isPercent ? "selected" : ""}>Процент от оплат</option>
        </select>
      </label>
      <label id="ruleAmountWrap">Сумма, ₽<input name="amount" type="text" placeholder="150000.00" value="${item?.amount_minor != null ? esc((Number(item.amount_minor) / 100).toFixed(2)) : ""}" /></label>
      <label id="rulePercentWrap">Процент, %<input name="percent" type="text" placeholder="2.50" value="${item?.percent_bps != null ? esc((Number(item.percent_bps) / 100).toFixed(2)) : ""}" /></label>
      <label style="display:flex; gap:8px; align-items:center; font-weight:600; color:inherit;">
        <input name="is_active" type="checkbox" ${item?.is_active === false ? "" : "checked"} />
        <span>Правило активно</span>
      </label>
      <label>Комментарий / описание<textarea name="description" rows="4" placeholder="Например: аренда помещения">${esc(item?.description || "")}</textarea></label>
      <div id="basisPaymentMethodsWrap">
        <div class="muted" style="margin-bottom:6px">База для процента</div>
        <div class="finance-form">${buildBasisPaymentMethodCheckboxes(item?.payment_method_ids || [])}</div>
      </div>
      <div class="row gap-8 mt-12">
        <button class="btn" type="submit">${item ? "Сохранить" : "Добавить"}</button>
        <button class="btn ghost" type="button" id="ruleFormCancel">Отмена</button>
      </div>
    </form>
  `;
}

function syncRuleModeVisibility() {
  const mode = String(document.getElementById("ruleMode")?.value || "FIXED").toUpperCase();
  const amountWrap = document.getElementById("ruleAmountWrap");
  const percentWrap = document.getElementById("rulePercentWrap");
  const basisWrap = document.getElementById("basisPaymentMethodsWrap");
  if (amountWrap) amountWrap.style.display = mode === "FIXED" ? "" : "none";
  if (percentWrap) percentWrap.style.display = mode === "PERCENT" ? "" : "none";
  if (basisWrap) basisWrap.style.display = mode === "PERCENT" ? "" : "none";
}

function openRuleForm(ruleId = null) {
  if (!access.canManage) return;
  if (!state.categories.length) {
    toast("Сначала создайте категорию расхода", "warn");
    return;
  }
  const item = ruleId ? state.rules.find((x) => Number(x.id) === Number(ruleId)) : null;
  openHtmlModal(ruleId ? "Редактировать правило" : "Добавить правило", buildRuleForm(item));
  const cancelBtn = document.getElementById("ruleFormCancel");
  if (cancelBtn) cancelBtn.onclick = () => closeModal();
  const modeEl = document.getElementById("ruleMode");
  if (modeEl) modeEl.onchange = syncRuleModeVisibility;
  syncRuleModeVisibility();

  const form = document.getElementById("ruleForm");
  if (!form) return;
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const generationMode = String(fd.get("generation_mode") || "FIXED").toUpperCase();
    const basisIds = Array.from(document.querySelectorAll('input[name="basis_payment_method_ids"]:checked')).map((el) => Number(el.value));
    const payload = {
      title: String(fd.get("title") || "").trim(),
      category_id: Number(fd.get("category_id")),
      supplier_id: fd.get("supplier_id") ? Number(fd.get("supplier_id")) : null,
      payment_method_id: fd.get("payment_method_id") ? Number(fd.get("payment_method_id")) : null,
      is_active: !!fd.get("is_active"),
      start_date: String(fd.get("start_date") || ""),
      end_date: String(fd.get("end_date") || "").trim() || null,
      day_of_month: Number(fd.get("day_of_month") || 1),
      spread_months: Number(fd.get("spread_months") || 1),
      generation_mode: generationMode,
      amount_minor: generationMode === "FIXED" ? parseMoneyToMinor(fd.get("amount")) : null,
      percent_bps: generationMode === "PERCENT" ? parseMoneyToMinor(fd.get("percent")) : null,
      description: String(fd.get("description") || "").trim() || null,
      payment_method_ids: generationMode === "PERCENT" ? basisIds : [],
    };
    try {
      const venueId = getActiveVenueId();
      if (item) {
        await api(`/venues/${encodeURIComponent(venueId)}/recurring-expense-rules/${encodeURIComponent(item.id)}`, { method: "PATCH", body: payload });
        toast("Правило обновлено", "ok");
      } else {
        await api(`/venues/${encodeURIComponent(venueId)}/recurring-expense-rules`, { method: "POST", body: payload });
        toast("Правило добавлено", "ok");
      }
      closeModal();
      await loadRules();
    } catch (err) {
      toast(err?.data?.detail || err.message || "Не удалось сохранить правило", "err");
    }
  };
}

async function deleteRule(ruleId) {
  if (!access.canManage) return;
  if (!confirm("Удалить правило регулярного расхода?")) return;
  try {
    const venueId = getActiveVenueId();
    await api(`/venues/${encodeURIComponent(venueId)}/recurring-expense-rules/${encodeURIComponent(ruleId)}`, { method: "DELETE" });
    toast("Правило удалено", "ok");
    await loadRules();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось удалить правило", "err");
  }
}

async function generateRules(ruleId = null) {
  if (!access.canManage) return;
  try {
    const venueId = getActiveVenueId();
    const qp = new URLSearchParams({ month: state.month || currentMonth() });
    if (ruleId) qp.set("rule_id", String(ruleId));
    const result = await api(`/venues/${encodeURIComponent(venueId)}/recurring-expense-rules/generate?${qp.toString()}`, { method: "POST" });
    state.generationResult = result || null;
    renderGenerationResult();
    toast(`Сгенерировано: ${result?.created_count || 0}, пропущено: ${result?.skipped_count || 0}`, "ok");
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось сгенерировать черновики", "err");
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
    const v = venues.find((x) => String(x.id) === String(getActiveVenueId()));
    if (v) document.getElementById("subtitle").textContent = v.name || "";
  } catch {}

  await loadAccess();
  state.month = params.get("month") || currentMonth();
  const monthPick = document.getElementById("rulesMonthPick");
  if (monthPick) {
    monthPick.value = state.month;
    monthPick.onchange = (e) => {
      state.month = e.target.value || currentMonth();
      if (openExpensesBtn) openExpensesBtn.href = buildExpensesMonthLink(state.month);
      if (openGeneratedExpensesBtn) openGeneratedExpensesBtn.href = buildExpensesMonthLink(state.month);
      renderRules();
    };
  }
  const addRuleBtn = document.getElementById("addRuleBtn");
  const generateRulesBtn = document.getElementById("generateRulesBtn");
  const openExpensesBtn = document.getElementById("openExpensesBtn");
  const openGeneratedExpensesBtn = document.getElementById("openGeneratedExpensesBtn");
  if (addRuleBtn) addRuleBtn.style.display = access.canManage ? "" : "none";
  if (openExpensesBtn) openExpensesBtn.href = buildExpensesMonthLink(state.month);
  if (openGeneratedExpensesBtn) openGeneratedExpensesBtn.href = buildExpensesMonthLink(state.month);
  if (generateRulesBtn) {
    generateRulesBtn.style.display = access.canManage ? "" : "none";
    generateRulesBtn.onclick = () => generateRules();
  }
  if (addRuleBtn) addRuleBtn.onclick = () => openRuleForm();

  try {
    await loadCatalogs();
    await loadRules();
  } catch (err) {
    document.getElementById("rulesList").innerHTML = `<div class="muted">${esc(err?.data?.detail || err.message || "Ошибка загрузки")}</div>`;
    document.getElementById("rulesState").textContent = "Ошибка";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  boot();
});

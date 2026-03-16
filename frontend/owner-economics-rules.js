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
import { roleUpper } from "/permissions.js";

const state = { access: { canManage: false } };

function todayISO() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function fmtMoneyMinor(minor) {
  if (minor === null || minor === undefined || minor === "") return "—";
  const rub = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(rub) + " ₽";
  } catch {
    return `${rub.toFixed(2)} ₽`;
  }
}

function fmtPercentBps(bps) {
  if (bps === null || bps === undefined || bps === "") return "—";
  const pct = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(pct) + "%";
  } catch {
    return `${pct.toFixed(2)}%`;
  }
}

function parseMoneyToMinor(value) {
  const raw = String(value ?? "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!raw) return null;
  const num = Number(raw);
  if (!Number.isFinite(num)) throw new Error("Неверный денежный формат");
  return Math.round(num * 100);
}

function parsePercentToBps(value) {
  const raw = String(value ?? "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!raw) return null;
  const num = Number(raw);
  if (!Number.isFinite(num)) throw new Error("Неверный процентный формат");
  return Math.round(num * 100);
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) el.textContent = value;
}

function setAllRuleToggles(form, checked) {
  [
    "enable_max_expense_ratio",
    "enable_max_payroll_ratio",
    "enable_min_revenue_per_assigned",
    "enable_min_assigned_shift_coverage",
    "enable_min_profit",
  ].forEach((name) => {
    const toggle = form?.elements?.namedItem(name);
    if (toggle) {
      toggle.checked = checked;
      toggle.dispatchEvent(new Event("change"));
    }
  });
}

function applyBaseRulePreset(form) {
  if (!form) return;
  setAllRuleToggles(form, false);
  const toggles = {
    enable_max_expense_ratio: "35",
    enable_min_revenue_per_assigned: "25000.00",
    enable_min_profit: "0.00",
  };
  Object.entries(toggles).forEach(([toggleName, value]) => {
    const toggle = form.elements.namedItem(toggleName);
    const inputName = toggleName.replace("enable_", "");
    const inputMap = {
      max_expense_ratio: "max_expense_ratio_pct",
      min_revenue_per_assigned: "min_revenue_per_assigned",
      min_profit: "min_profit",
    };
    const input = form.elements.namedItem(inputMap[inputName]);
    if (toggle) {
      toggle.checked = true;
      toggle.dispatchEvent(new Event("change"));
    }
    if (input) input.value = value;
  });
  const warn = form.elements.namedItem('warn_on_draft_expenses');
  if (warn) warn.checked = true;
}

function buildDayEconomicsLink() {
  const qp = new URLSearchParams();
  const venueId = getActiveVenueId();
  if (venueId) qp.set("venue_id", String(venueId));
  qp.set("date", todayISO());
  return `/owner-day-economics.html?${qp.toString()}`;
}

function buildPlansLink() {
  const qp = new URLSearchParams();
  const venueId = getActiveVenueId();
  if (venueId) qp.set("venue_id", String(venueId));
  qp.set("date", todayISO());
  qp.set("month", todayISO().slice(0, 7));
  return `/owner-economics-plans.html?${qp.toString()}`;
}

async function loadAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  try {
    const resp = await getMyVenuePermissions(venueId);
    const role = roleUpper(resp);
    state.access.canManage = role === "OWNER" || role === "VENUE_OWNER";
  } catch {
    state.access.canManage = false;
  }
}

function buildRulesForm(rules = {}) {
  const isEnabled = {
    expense: rules.max_expense_ratio_bps != null,
    payroll: rules.max_payroll_ratio_bps != null,
    revenuePerAssigned: rules.min_revenue_per_assigned_minor != null,
    coverage: rules.min_assigned_shift_coverage_bps != null,
    profit: rules.min_profit_minor != null,
  };
  return `
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="enable_max_expense_ratio" ${isEnabled.expense ? "checked" : ""} /> Контролировать макс. расходы / выручка</span>
      <input name="max_expense_ratio_pct" type="text" placeholder="35" value="${rules.max_expense_ratio_bps != null ? esc((Number(rules.max_expense_ratio_bps) / 100).toFixed(2)) : ""}" />
    </label>
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="enable_max_payroll_ratio" ${isEnabled.payroll ? "checked" : ""} /> Контролировать макс. ФОТ / выручка</span>
      <input name="max_payroll_ratio_pct" type="text" placeholder="20" value="${rules.max_payroll_ratio_bps != null ? esc((Number(rules.max_payroll_ratio_bps) / 100).toFixed(2)) : ""}" />
    </label>
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="enable_min_revenue_per_assigned" ${isEnabled.revenuePerAssigned ? "checked" : ""} /> Контролировать мин. выручку на сотрудника</span>
      <input name="min_revenue_per_assigned" type="text" placeholder="25000.00" value="${rules.min_revenue_per_assigned_minor != null ? esc((Number(rules.min_revenue_per_assigned_minor) / 100).toFixed(2)) : ""}" />
    </label>
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="enable_min_assigned_shift_coverage" ${isEnabled.coverage ? "checked" : ""} /> Контролировать мин. покрытие смен</span>
      <input name="min_assigned_shift_coverage_pct" type="text" placeholder="80" value="${rules.min_assigned_shift_coverage_bps != null ? esc((Number(rules.min_assigned_shift_coverage_bps) / 100).toFixed(2)) : ""}" />
    </label>
    <label>
      <span class="row" style="gap:8px; align-items:center;"><input type="checkbox" name="enable_min_profit" ${isEnabled.profit ? "checked" : ""} /> Контролировать мин. прибыль дня</span>
      <input name="min_profit" type="text" placeholder="10000.00" value="${rules.min_profit_minor != null ? esc((Number(rules.min_profit_minor) / 100).toFixed(2)) : ""}" />
    </label>
    <label class="row" style="gap:8px; align-items:center;"><input name="warn_on_draft_expenses" type="checkbox" ${rules.warn_on_draft_expenses !== false ? "checked" : ""} /> Предупреждать о черновых расходах</label>
    <div class="row gap-8 mt-12"><button class="btn" type="submit">Сохранить нормативы</button></div>
  `;
}

function bindToggle(form, toggleName, inputName) {
  const toggle = form.elements.namedItem(toggleName);
  const input = form.elements.namedItem(inputName);
  if (!toggle || !input) return;
  const sync = () => { input.disabled = !toggle.checked; };
  toggle.addEventListener("change", sync);
  sync();
}

function renderRules(rules = {}) {
  const parts = [];
  if (rules.max_expense_ratio_bps != null) parts.push(`расходы ≤ ${fmtPercentBps(rules.max_expense_ratio_bps)}`);
  if (rules.max_payroll_ratio_bps != null) parts.push(`ФОТ ≤ ${fmtPercentBps(rules.max_payroll_ratio_bps)}`);
  if (rules.min_revenue_per_assigned_minor != null) parts.push(`выручка/сотрудник ≥ ${fmtMoneyMinor(rules.min_revenue_per_assigned_minor)}`);
  if (rules.min_assigned_shift_coverage_bps != null) parts.push(`покрытие смен ≥ ${fmtPercentBps(rules.min_assigned_shift_coverage_bps)}`);
  if (rules.min_profit_minor != null) parts.push(`прибыль ≥ ${fmtMoneyMinor(rules.min_profit_minor)}`);
  if (rules.warn_on_draft_expenses) parts.push(`черновики включены в предупреждения`);
  setText("rulesSummaryHint", parts.length ? parts.join(" · ") : "Все правила выключены.");

  const form = document.getElementById("economicsRulesFormPage");
  if (!form) return;
  form.innerHTML = buildRulesForm(rules);
  form.style.display = state.access.canManage ? "" : "none";
  form.addEventListener("submit", saveRules);
  bindToggle(form, "enable_max_expense_ratio", "max_expense_ratio_pct");
  bindToggle(form, "enable_max_payroll_ratio", "max_payroll_ratio_pct");
  bindToggle(form, "enable_min_revenue_per_assigned", "min_revenue_per_assigned");
  bindToggle(form, "enable_min_assigned_shift_coverage", "min_assigned_shift_coverage_pct");
  bindToggle(form, "enable_min_profit", "min_profit");

  const enableAllBtn = document.getElementById('enableAllRulesBtn');
  if (enableAllBtn) enableAllBtn.onclick = () => setAllRuleToggles(form, true);
  const disableAllBtn = document.getElementById('disableAllRulesBtn');
  if (disableAllBtn) disableAllBtn.onclick = () => setAllRuleToggles(form, false);
  const baseBtn = document.getElementById('applyBaseRulesBtn');
  if (baseBtn) baseBtn.onclick = () => applyBaseRulePreset(form);
}

async function loadRules() {
  const venueId = getActiveVenueId();
  if (!venueId) return;
  const rules = await api(`/venues/${encodeURIComponent(venueId)}/economics/rules`);
  renderRules(rules || {});
}

async function saveRules(event) {
  event.preventDefault();
  if (!state.access.canManage) return;
  try {
    const venueId = getActiveVenueId();
    const fd = new FormData(event.currentTarget);
    const body = {
      max_expense_ratio_bps: fd.get("enable_max_expense_ratio") === "on" ? parsePercentToBps(fd.get("max_expense_ratio_pct")) : null,
      max_payroll_ratio_bps: fd.get("enable_max_payroll_ratio") === "on" ? parsePercentToBps(fd.get("max_payroll_ratio_pct")) : null,
      min_revenue_per_assigned_minor: fd.get("enable_min_revenue_per_assigned") === "on" ? parseMoneyToMinor(fd.get("min_revenue_per_assigned")) : null,
      min_assigned_shift_coverage_bps: fd.get("enable_min_assigned_shift_coverage") === "on" ? parsePercentToBps(fd.get("min_assigned_shift_coverage_pct")) : null,
      min_profit_minor: fd.get("enable_min_profit") === "on" ? parseMoneyToMinor(fd.get("min_profit")) : null,
      warn_on_draft_expenses: fd.get("warn_on_draft_expenses") === "on",
    };
    await api(`/venues/${encodeURIComponent(venueId)}/economics/rules`, { method: "PUT", body });
    toast("Нормативы сохранены", "ok");
    await loadRules();
  } catch (err) {
    toast(err?.data?.detail || err.message || "Не удалось сохранить нормативы", "err");
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin();
  const params = new URLSearchParams(location.search);
  const venues = await getMyVenues();
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);
  if (!getActiveVenueId() && Array.isArray(venues) && venues.length) setActiveVenueId(venues[0].id);

  await mountNav({ activeTab: "summary" });
  await loadAccess();

  const openDay = document.getElementById("openDayEconomicsFromRulesBtn");
  if (openDay) openDay.onclick = () => { location.href = buildDayEconomicsLink(); };
  const openPlans = document.getElementById("openPlansBtn");
  if (openPlans) openPlans.onclick = () => { location.href = buildPlansLink(); };

  const manageCard = document.getElementById("rulesManageCard");
  if (manageCard) manageCard.style.display = state.access.canManage ? "" : "none";

  await loadRules();
}

document.addEventListener("DOMContentLoaded", () => { boot(); });

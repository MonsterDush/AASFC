import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
  calculatePayroll,
  api,
  API_BASE,
  coerceDemoMonth,
  coerceDemoRange,
  applyDemoReadonlyCaps,
  isDemoUiMode,
  getStoredDemoUiState,
  getDemoMonthLabel,
  mountDemoPageTour,
  trackDemoEvent,
} from "/app.js?v=20260726-navmore1";
import { permSetFromResponse, roleUpper, hasPerm, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js";
import {
  formatComparisonRange,
  normalizeIsoRange,
  resolveAutoComparison,
  resolveComparisonRange,
} from "/app/period-comparison.js?v=20260802-financeux2";
import {
  buildPayrollTeamAnalytics,
  payrollLineShiftMetrics,
} from "/app/payroll-analytics.js?v=20260802-payrollanalytics1";

let financialValuesHidden = false;

const root = document.getElementById("root");

const DEMO_OWNER_PAYROLL_INTRO_DISMISSED_KEY = "axelio.demo_intro.owner_payroll.dismissed";

function renderDemoOwnerPayrollIntro() {
  const intro = document.getElementById("demoOwnerPayrollIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) { intro.classList.add("hidden"); return; }
  try { if (sessionStorage.getItem(DEMO_OWNER_PAYROLL_INTRO_DISMISSED_KEY) === "1") { intro.classList.add("hidden"); return; } } catch {}
  const textEl = document.getElementById("demoOwnerPayrollIntroText");
  if (textEl) textEl.textContent = `Здесь видно итоговый ФОТ и детализацию начислений за ${getDemoMonthLabel(demoState) || 'DEMO-месяц'}.`;
  document.getElementById("demoOwnerPayrollGoSummary")?.addEventListener("click", () => { const v = parseVenueId(); if (v) location.href = `/owner-summary.html?venue_id=${encodeURIComponent(String(v))}`; });
  document.getElementById("demoOwnerPayrollGoExpenses")?.addEventListener("click", () => { const v = parseVenueId(); if (v) location.href = `/owner-expenses.html?venue_id=${encodeURIComponent(String(v))}`; });
  document.getElementById("demoOwnerPayrollIntroClose")?.addEventListener("click", () => { intro.classList.add("hidden"); try { sessionStorage.setItem(DEMO_OWNER_PAYROLL_INTRO_DISMISSED_KEY, "1"); } catch {} });
  intro.classList.remove("hidden");
}


function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setVisible(element, visible) {
  element?.classList.toggle("hidden", !visible);
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const id = params.get("venue_id") || "";
  if (id) setActiveVenueId(id);
  return id;
}

function todayIso() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return coerceDemoMonth(`${y}-${m}`, { notify: false, context: "owner-payroll" });
}

function monthStartIso(month) {
  return `${month}-01`;
}

function monthEndIso(month) {
  const [yearS, monthS] = String(month || "").split("-");
  const year = Number(yearS || 0);
  const monthI = Number(monthS || 0);
  if (!year || !monthI) return todayIso();
  const lastDay = new Date(year, monthI, 0).getDate();
  return `${year}-${String(monthI).padStart(2, "0")}-${String(lastDay).padStart(2, "0")}`;
}

function formatDateRu(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(String(iso || ""))) return String(iso || "—");
  const d = new Date(`${iso}T00:00:00`);
  try {
    return d.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
  } catch {
    return iso;
  }
}

function fmtMoneyMinor(minor) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  const value = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";
  } catch {
    return value.toFixed(2) + " ₽";
  }
}

function fioInitials(fullName) {
  const parts = String(fullName || "")
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (!parts.length) return "";

  if (parts.length === 1) return parts[0];

  return [
    parts[0],
    ...parts.slice(1).map((p) => `${p.charAt(0).toUpperCase()}.`)
  ].join(" ");
}

function memberName(member) {
  if (!member) return "—";

  const shortName = (member.short_name || "").trim();
  if (shortName) return shortName;

  const fi = fioInitials(member.full_name);
  if (fi) return fi;

  const u = (member.tg_username || "").trim();
  if (u) return u.startsWith("@") ? u : `@${u}`;

  return member.user_id ? "Сотрудник" : "—";
}

const COMPONENT_LABELS = {
  SALARY_FIXED_MONTH: "Оклад за месяц",
  SALARY_HOURLY: "Почасовая ставка",
  SALARY_PER_SHIFT: "Фикс за смену",
  PERCENT_TOTAL_REVENUE: "% от общей выручки",
  PERCENT_DEPARTMENT_REVENUE: "% от выручки департамента",
  KPI_BONUS: "KPI-бонус",
  MINIMUM_PAYOUT: "Минимальная сумма к выплате",
  TIP: "Чаевые",
  BONUS: "Премия",
  PENALTY: "Штраф",
  WRITEOFF: "Списание",
};

function fmtPercentBps(bps) {
  const value = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + "%";
  } catch {
    return value.toFixed(2) + "%";
  }
}

function listTitles(value) {
  return Array.isArray(value) ? value.map((item) => String(item || '').trim()).filter(Boolean) : [];
}

function componentDepartmentLabel(component, prefix = 'department') {
  const titles = listTitles(component?.[`${prefix}_titles`]);
  if (titles.length) return titles.join(' + ');
  const title = component?.[`${prefix}_title`];
  if (title) return String(title);
  const ids = Array.isArray(component?.[`${prefix}_ids`]) ? component[`${prefix}_ids`].filter(Boolean) : [];
  return ids.length ? ids.map((id) => `#${id}`).join(' + ') : '';
}

function minimumScopeLabel(snap) {
  const raw = String(snap?.minimum_payout_scope || snap?.minimum_guarantee_scope || '').toUpperCase();
  return String(snap?.minimum_payout_scope_title || snap?.minimum_guarantee_scope_title || (raw === 'SHIFT' ? 'за каждую отработанную смену' : (raw === 'DAY' ? 'за день' : 'за месяц')));
}

function breakdownComponentMeta(component) {
  const type = String(component?.component_type || "").toUpperCase();
  const label = COMPONENT_LABELS[type] || type || "Компонент";
  if (type === "PERCENT_TOTAL_REVENUE" || type === "PERCENT_DEPARTMENT_REVENUE") {
    const parts = [label, fmtPercentBps(component?.percent_bps || 0), `база ${fmtMoneyMinor(component?.base_amount_minor || 0)}`];
    const depLabel = componentDepartmentLabel(component, 'department');
    if (depLabel) parts.push(depLabel);
    if (component?.base_scope_title) parts.push(component.base_scope_title);
    if (component?.boost_enabled && component?.boost_percent_bps != null) {
      parts.push(`boost ${fmtPercentBps(component.boost_percent_bps)}`);
      if (component?.boost_source_title) parts.push(component.boost_source_title);
      const boostDepLabel = componentDepartmentLabel(component, 'boost_department');
      if (boostDepLabel) parts.push(boostDepLabel);
      if (component?.boost_applied) parts.push('сработал');
    }
    if (component?.minimum_applied) parts.push('мин. гарантия');
    if (component?.maximum_applied) parts.push('потолок');
    return parts.join(' · ');
  }
  if (type === "MINIMUM_PAYOUT") {
    const source = component?.source_amount_minor;
    const target = component?.minimum_target_minor ?? source;
    if (source != null) return `${label} · ${fmtMoneyMinor(source)} ${minimumScopeLabel(component)}`;
    return target != null ? `${label} · до ${fmtMoneyMinor(target)}` : label;
  }
  if (type === "KPI_BONUS") {
    const metricTitle = component?.kpi_metric_title ? ` · ${component.kpi_metric_title}` : "";
    const metricValue = component?.metric_value != null ? ` · факт ${component.metric_value}` : "";
    const thresholdValue = component?.threshold_value != null ? ` · порог ${component.threshold_value}` : "";
    const matchedStep = component?.matched_step?.threshold_value != null ? ` · ступень ${component.matchedStep?.threshold_value}` : "";
    if (String(component?.kpi_calculation_mode || "FIXED").toUpperCase() === "PERCENT") {
      return `${label}${metricTitle}${metricValue} · ${fmtPercentBps(component?.percent_bps || 0)} от KPI${thresholdValue} · по закрытым сменам`;
    }
    return `${label}${metricTitle}${metricValue}${thresholdValue}${matchedStep}`;
  }
  if (type === "SALARY_FIXED_MONTH" && component?.salary_accrual_day) {
    return `${label} · начисление ${component.salary_accrual_day}-го числа`;
  }
  return label;
}

function componentSnapshot(component) {
  return component && typeof component.calculation_snapshot === 'object' && component.calculation_snapshot
    ? component.calculation_snapshot
    : (component || {});
}

function breakdownBadges(component) {
  const snap = componentSnapshot(component);
  const badges = [];
  if (snap?.boost_enabled && snap?.boost_percent_bps != null) {
    badges.push(`<span class="payroll-chip ${snap?.boost_applied ? 'payroll-chip--ok' : 'payroll-chip--muted'}">boost ${esc(fmtPercentBps(snap.boost_percent_bps))}${snap?.boost_applied ? ' ✓' : ''}</span>`);
  }
  if (snap?.boost_source_title) badges.push(`<span class="payroll-chip payroll-chip--muted">${esc(snap.boost_source_title)}</span>`);
  if (snap?.minimum_applied) badges.push(`<span class="payroll-chip payroll-chip--warn">мин. гарантия</span>`);
  if (snap?.maximum_applied) badges.push(`<span class="payroll-chip payroll-chip--warn">потолок</span>`);
  if (Array.isArray(snap?.day_rows) && snap.day_rows.length) badges.push(`<span class="payroll-chip payroll-chip--muted">по дням</span>`);
  if (Array.isArray(snap?.shift_rows) && snap.shift_rows.length) badges.push(`<span class="payroll-chip payroll-chip--muted">по сменам</span>`);
  return badges.length ? `<div class="payroll-breakdown__badges">${badges.join('')}</div>` : '';
}

function breakdownKv(component) {
  const snap = componentSnapshot(component);
  const rows = [];
  const push = (label, value) => {
    if (value == null || value === '') return;
    rows.push(`<div class="payroll-breakdown__kv-item"><span class="payroll-breakdown__kv-label">${esc(label)}</span><span class="payroll-breakdown__kv-value">${esc(value)}</span></div>`);
  };
  const type = String(component?.component_type || '').toUpperCase();
  if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
    push('База', fmtMoneyMinor(snap.base_amount_minor || component?.base_amount_minor || 0));
    if (snap.base_scope_title || component?.base_scope_title) push('База расчёта', snap.base_scope_title || component?.base_scope_title);
    if (snap.regular_percent_bps != null || component?.regular_percent_bps != null) push('Обычный %', fmtPercentBps(snap.regular_percent_bps ?? component?.regular_percent_bps ?? 0));
    if (snap.applied_percent_bps != null || component?.percent_bps != null) push('Применённый %', fmtPercentBps(snap.applied_percent_bps ?? component?.percent_bps ?? 0));
    if (snap.boost_target_minor != null) push('Цель', fmtMoneyMinor(snap.boost_target_minor));
    else if (snap.boost_target_value != null) push('Цель KPI', String(snap.boost_target_value));
    if (snap.boost_actual_minor != null) push('Факт', fmtMoneyMinor(snap.boost_actual_minor));
    else if (snap.boost_actual_value != null) push('Факт KPI', String(snap.boost_actual_value));
    if (snap.boost_recalc_mode_title) push('Режим', snap.boost_recalc_mode_title);
    if (snap.boost_recalc_mode_effective && snap.boost_recalc_mode_effective !== snap.boost_recalc_mode) push('Эффективно', snap.boost_recalc_mode_effective);
    if (snap.minimum_guarantee_minor != null) push('Мин. гарантия', `${fmtMoneyMinor(snap.minimum_guarantee_minor)} ${minimumScopeLabel(snap)}`);
    if (snap.maximum_cap_minor != null) push('Максимум', fmtMoneyMinor(snap.maximum_cap_minor));
  }
  if (type === 'KPI_BONUS') {
    if (component?.kpi_metric_title) push('KPI', component.kpi_metric_title);
    if (component?.metric_value != null) push('Факт KPI', String(component.metric_value));
    if (component?.threshold_value != null) push('Порог', String(component.threshold_value));
  }
  if (type === 'MINIMUM_PAYOUT') {
    if (component?.source_amount_minor != null) push('Правило', `${fmtMoneyMinor(component.source_amount_minor)} ${minimumScopeLabel(component)}`);
    if (component?.minimum_target_minor != null) push('Цель минимума', fmtMoneyMinor(component.minimum_target_minor));
    if (component?.amount_before_minimum_minor != null) push('Было начислено', fmtMoneyMinor(component.amount_before_minimum_minor));
    if (component?.minimum_applied_shifts_count != null) push('Смен с доплатой', `${component.minimum_applied_shifts_count} из ${component.shifts_count || 0}`);
  }
  return rows.length ? `<div class="payroll-breakdown__kv">${rows.join('')}</div>` : '';
}

function breakdownExplain(component) {
  const snap = componentSnapshot(component);
  const type = String(component?.component_type || '').toUpperCase();
  if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
    const parts = [];
    if (snap?.boost_enabled) {
      parts.push(snap?.boost_applied ? 'Повышенный процент применился.' : 'Сейчас остаётся базовый процент.');
    } else {
      parts.push('Без условия повышения.');
    }
    if (snap?.minimum_applied) parts.push('Итог поднят минимальной гарантией.');
    if (snap?.maximum_applied) parts.push('Итог ограничен потолком.');
    if (Array.isArray(snap?.day_rows) && snap.day_rows.length) parts.push('Компонент разложен по дням.');
    return parts.join(' ');
  }
  if (type === 'KPI_BONUS') {
    if (component?.matched_step?.threshold_value != null) return 'Сработала подходящая ступень KPI-бонуса.';
    return 'Фиксированный бонус за выполнение KPI.';
  }
  if (type === 'SALARY_HOURLY') return 'Компонент посчитан по фактически отработанным часам.';
  if (type === 'SALARY_PER_SHIFT') return 'Компонент посчитан по количеству смен в периоде.';
  if (type === 'SALARY_FIXED_MONTH') return 'Фиксированная часть за период.';
  if (type === 'MINIMUM_PAYOUT') {
    const snap = componentSnapshot(component);
    const scope = String(snap?.minimum_payout_scope || snap?.minimum_guarantee_scope || '').toUpperCase();
    if (component?.minimum_applied && scope === 'SHIFT') return 'Добавлена доплата по отдельным сменам, где начисление было ниже минимума.';
    return component?.minimum_applied ? 'Добавлена доплата до минимальной суммы выплаты.' : 'Минимум уже перекрыт другими компонентами.';
  }
  return 'Компонент профиля начисления.';
}

function breakdownDayRows(component) {
  const snap = componentSnapshot(component);
  const rows = Array.isArray(snap?.day_rows) ? snap.day_rows : [];
  if (!rows.length) return '';
  return `<div class="payroll-breakdown__dayrows">${rows.map((row) => {
    const meta = [];
    if (row?.base_amount_minor != null) meta.push(`база ${fmtMoneyMinor(row.base_amount_minor)}`);
    if (row?.target_amount_minor != null) meta.push(`цель ${fmtMoneyMinor(row.target_amount_minor)}`);
    if (row?.actual_amount_minor != null) meta.push(`факт ${fmtMoneyMinor(row.actual_amount_minor)}`);
    if (row?.percent_bps != null) meta.push(fmtPercentBps(row.percent_bps));
    if (row?.boost_applied) meta.push('boost ✓');
    if (row?.minimum_applied) meta.push('мин ✓');
    return `<div class="payroll-breakdown__dayrow"><div class="payroll-breakdown__dayrow-main"><div class="payroll-breakdown__dayrow-date">${esc(formatDateRu(row.date))}</div><div class="payroll-breakdown__dayrow-meta">${esc(meta.join(' · '))}</div></div><div class="payroll-breakdown__dayrow-amount">${esc(fmtMoneyMinor(row.amount_minor || 0))}</div></div>`;
  }).join('')}</div>`;
}

function breakdownShiftRows(component) {
  const snap = componentSnapshot(component);
  const rows = Array.isArray(snap?.shift_rows) ? snap.shift_rows : [];
  if (!rows.length) return '';
  return `<div class="payroll-breakdown__dayrows">${rows.map((row) => {
    const meta = [];
    if (row?.minimum_target_minor != null) meta.push(`минимум ${fmtMoneyMinor(row.minimum_target_minor)}`);
    if (row?.amount_before_minimum_minor != null) meta.push(`было ${fmtMoneyMinor(row.amount_before_minimum_minor)}`);
    if (row?.minutes != null) meta.push(`${Math.round(Number(row.minutes || 0) / 60 * 100) / 100} ч`);
    if (row?.shift_slot) meta.push(String(row.shift_slot).toLowerCase());
    if (row?.minimum_applied) meta.push('доплата ✓');
    return `<div class="payroll-breakdown__dayrow"><div class="payroll-breakdown__dayrow-main"><div class="payroll-breakdown__dayrow-date">${esc(formatDateRu(row.date))} · смена #${esc(row.shift_id || '')}</div><div class="payroll-breakdown__dayrow-meta">${esc(meta.join(' · '))}</div></div><div class="payroll-breakdown__dayrow-amount">${esc(fmtMoneyMinor(row.amount_minor || 0))}</div></div>`;
  }).join('')}</div>`;
}

let state = {
  venueId: "",
  periodMode: "month",
  month: currentMonth(),
  dateFrom: monthStartIso(currentMonth()),
  dateTo: monthEndIso(currentMonth()),
  me: null,
  perms: null,
  can: { view: false, calculate: false },
  data: null,
  comparisonData: null,
  comparisonError: null,
  compareMode: "auto",
  compareFrom: "",
  compareTo: "",
  focusPayrollLineId: null,
  focusMemberUserId: null,
  sourceTargetFocused: false,
  paymentMethods: [],
  paymentSettings: null,
  paymentSettingsError: null,
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

function computeCaps(perms, me) {
  const role = roleUpper(perms);
  const pset = permSetFromResponse(perms);
  const sysRole = String(me?.system_role || "").toUpperCase();
  const isOwner = role === "OWNER" || role === "VENUE_OWNER";
  const isAdmin = sysRole === "SUPER_ADMIN" || sysRole === "MODERATOR";
  return {
    view: isOwner || isAdmin || hasPerm(pset, "PAYROLL_VIEW") || hasPerm(pset, "PAYROLL_CALCULATE"),
    calculate: isOwner || isAdmin || hasPerm(pset, "PAYROLL_CALCULATE"),
  };
}

function periodTitle() {
  return state.periodMode === "month"
    ? "расчёт зарплаты за месяц"
    : `сводка начислений за период ${formatDateRu(state.dateFrom)} — ${formatDateRu(state.dateTo)}`;
}

function renderShell() {
  root.innerHTML = `
    <div class="topbar payroll-topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Начисления</b>
          <div class="muted" id="subtitle">ФОТ и детализация команды</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <main class="payroll-content">
      <div class="card demo-flow-card hidden" id="demoOwnerPayrollIntro">
        <div class="demo-flow-card__head">
          <div>
            <b>Что посмотреть в DEMO владельца</b>
            <div class="muted mt-6" id="demoOwnerPayrollIntroText">Здесь видно общий ФОТ и разбор начислений команды по профилям.</div>
          </div>
          <button class="btn sm subtle" id="demoOwnerPayrollIntroClose" type="button">Скрыть</button>
        </div>
        <div class="demo-flow-card__chips mt-10">
          <span class="demo-flow-card__chip">Общий ФОТ</span>
          <span class="demo-flow-card__chip">Строки начислений</span>
          <span class="demo-flow-card__chip">Детализация по сотруднику</span>
        </div>
        <div class="demo-flow-card__actions mt-12">
          <button class="btn" id="demoOwnerPayrollGoSummary" type="button">Открыть сводку</button>
          <button class="btn subtle" id="demoOwnerPayrollGoExpenses" type="button">Открыть расходы</button>
        </div>
      </div>

      <section class="card payroll-overview-card">
        <div class="screen-hero payroll-hero">
          <div class="screen-hero__head">
            <div>
              <b>Расчёт зарплаты</b>
              <div class="page-caption mt-6">Начисления по активным профилям: ставки, проценты и KPI-бонусы по закрытым отчётам выбранного периода.</div>
            </div>
            <div class="screen-hero__actions screen-hero__actions--adaptive payroll-hero__actions">
              <button class="btn subtle small" id="openProfilesBtn" type="button" data-nav-button>Профили</button>
              <button class="btn ghost" id="btnExport">Экспорт XLSX</button>
              <button class="btn primary" id="btnCalculate">Рассчитать</button>
            </div>
          </div>

          <div class="payroll-period-grid">
            <div class="itemcard payroll-period-card">
              <div class="finance-period-card__label">Период начислений</div>
              <div class="payroll-period-card__controls">
                <div class="seg seg--period finance-period-segment" id="periodSeg">
                  <button type="button" id="periodMonthBtn">Месяц</button>
                  <button type="button" id="periodRangeBtn">Период</button>
                </div>
                <div id="monthControls" class="pickers">
                  <input id="monthPick" class="finance-control" type="month" aria-label="Месяц начислений" />
                </div>
                <div id="rangeControls" class="range-pick hidden">
                  <input id="rangeFrom" type="date" aria-label="Начало периода" />
                  <input id="rangeTo" type="date" aria-label="Конец периода" />
                  <button class="btn" id="rangeApply">Показать</button>
                </div>
              </div>
            </div>
            <div class="itemcard finance-period-card payroll-run-card">
              <div class="finance-period-card__label">Последний расчёт</div>
              <div class="finance-period-card__value is-loading" id="runMeta" aria-busy="true">Загрузка…</div>
              <div class="muted">Перерасчёт обновляет ФОТ и детализацию для каждого сотрудника.</div>
            </div>
            <details class="itemcard payroll-comparison-card finance-comparison-disclosure">
              <summary class="finance-comparison-disclosure__summary">
                <span><b>Сравнение начислений</b><span class="muted">Открыть настройки сравнения</span></span>
                <span class="badge">Настроить</span>
              </summary>
              <div class="finance-comparison-disclosure__body">
              <div class="payroll-comparison-card__head">
                <div>
                  <div class="finance-period-card__label">Сравнение</div>
                  <div class="finance-period-card__value" id="payrollComparePeriodText">—</div>
                </div>
                <div class="seg" id="payrollCompareSeg">
                  <button type="button" data-compare="auto" class="active">Авто</button>
                  <button type="button" data-compare="custom">Другой период</button>
                  <button type="button" data-compare="none">Без сравнения</button>
                </div>
              </div>
              <div class="payroll-comparison-card__controls hidden" id="payrollCompareRange">
                <div class="range-pick">
                  <input id="payrollCompareFrom" type="date" aria-label="Начало периода сравнения" />
                  <input id="payrollCompareTo" type="date" aria-label="Конец периода сравнения" />
                  <button class="btn" id="payrollCompareApply" type="button">Сравнить</button>
                </div>
              </div>
              <div class="muted" id="payrollCompareHint">—</div>
              </div>
            </details>
          </div>
        </div>

        <div class="finance-kpis payroll-kpis">
          <div class="itemcard finance-stat finance-stat--hero payroll-metric payroll-metric--total">
            <div class="finance-stat__label">Фонд оплаты труда</div>
            <div class="finance-stat__value is-loading" id="totalAmount" aria-busy="true">Загрузка…</div>
            <div class="payroll-metric-delta" id="totalAmountDelta">—</div>
            <div class="finance-stat__meta">Итого начислено команде за выбранный период.</div>
          </div>
          <div class="itemcard finance-stat payroll-metric">
            <div class="finance-stat__label">Сотрудников в расчёте</div>
            <div class="finance-stat__value is-loading" id="linesCount" aria-busy="true">Загрузка…</div>
            <div class="payroll-metric-delta" id="linesCountDelta">—</div>
            <div class="finance-stat__meta">Участники, для которых сформированы строки начислений.</div>
          </div>
          <div class="itemcard finance-stat payroll-metric">
            <div class="finance-stat__label">Среднее начисление</div>
            <div class="finance-stat__value is-loading" id="averageAmount" aria-busy="true">Загрузка…</div>
            <div class="payroll-metric-delta" id="averageAmountDelta">—</div>
            <div class="finance-stat__meta">Средняя сумма на одного сотрудника в текущем расчёте.</div>
          </div>
          <div class="itemcard finance-stat payroll-metric payroll-metric--per-shift">
            <div class="finance-stat__label">Среднее за смену</div>
            <div class="finance-stat__value is-loading" id="averagePerShift" aria-busy="true">Загрузка…</div>
            <div class="payroll-metric-delta" id="averagePerShiftDelta">—</div>
            <div class="finance-stat__meta">Взвешенное среднее по сотрудникам, у которых есть отработанные смены.</div>
          </div>
        </div>
      </section>

      <section class="card section-card payroll-payment-card" id="payrollPaymentCard">
        <details class="payroll-payment-disclosure" id="payrollPaymentDisclosure">
          <summary class="payroll-payment-disclosure__summary">
            <span>
              <b>Выплаты ФОТ</b>
              <span class="muted" id="payrollPaymentSummary">Способ оплаты, даты выплат и расчётные периоды</span>
            </span>
            <span class="badge" id="payrollPaymentBadge">Настроить</span>
          </summary>
          <div class="payroll-payment-disclosure__body">
            <div class="payroll-payment-grid">
              <label class="payroll-payment-field">
                <span>Способ оплаты</span>
                <select id="payrollPaymentMethod"><option value="">Выберите способ оплаты</option></select>
              </label>
              <label class="payroll-payment-field">
                <span>Периодичность</span>
                <select id="payrollPaymentCadence">
                  <option value="DAILY">Каждый день</option>
                  <option value="WEEKLY">Раз в неделю</option>
                  <option value="MONTHLY">По датам месяца</option>
                </select>
              </label>
              <label class="payroll-payment-field hidden" id="payrollWeeklyField">
                <span>День выплаты</span>
                <select id="payrollWeeklyDay">
                  <option value="0">Понедельник</option>
                  <option value="1">Вторник</option>
                  <option value="2">Среда</option>
                  <option value="3">Четверг</option>
                  <option value="4">Пятница</option>
                  <option value="5">Суббота</option>
                  <option value="6">Воскресенье</option>
                </select>
              </label>
              <label class="payroll-payment-enabled">
                <input id="payrollPaymentEnabled" type="checkbox" />
                <span>Формировать черновики выплат</span>
              </label>
            </div>

            <div class="payroll-monthly-rules" id="payrollMonthlyRulesWrap">
              <div class="section-card__head">
                <div>
                  <b>Даты и периоды выплат</b>
                  <div class="muted mt-6">Для каждой даты укажите, начисления за какие числа попадут в черновик.</div>
                </div>
                <button class="btn subtle small" id="payrollAddPaymentRule" type="button">Добавить выплату</button>
              </div>
              <div class="payroll-monthly-rules__list" id="payrollMonthlyRules"></div>
            </div>

            <div class="itemcard payroll-payment-preview">
              <div>
                <b>Предпросмотр выплат выбранного месяца</b>
                <div class="muted mt-6">Черновик не влияет на сводку. Списание выбранного баланса произойдёт после подтверждения расхода.</div>
              </div>
              <div class="payroll-payment-preview__list" id="payrollPaymentPreview"><span class="muted">Загрузка…</span></div>
            </div>

            <div class="payroll-payment-actions">
              <button class="btn primary" id="payrollSavePaymentSettings" type="button">Сохранить настройки</button>
              <button class="btn" id="payrollGenerateDrafts" type="button">Сформировать черновики</button>
              <button class="btn subtle small" id="payrollOpenDrafts" type="button" data-nav-button>Открыть черновики расходов</button>
            </div>
            <div class="muted" id="payrollPaymentHint">—</div>
          </div>
        </details>
      </section>

      <section class="card section-card payroll-leaderboard-card" id="payrollLeaderboardCard">
        <div class="section-card__head payroll-leaderboard-head">
          <div class="section-card__title">
            <b>Лидеры по начислению за смену</b>
            <div class="muted" id="payrollLeaderboardSubtitle">Сравнение сотрудников с сопоставимой нагрузкой.</div>
          </div>
          <span class="badge" id="payrollLeaderboardThreshold">минимум 3 смены</span>
        </div>
        <div id="payrollLeaderboard" class="payroll-leaderboard payroll-loading" aria-live="polite" aria-busy="true">
          <div class="payroll-leaderboard-skeleton skeleton"></div>
        </div>
        <div class="payroll-leaderboard-note muted" id="payrollLeaderboardNote">
          Это рейтинг начислений, а не личных продаж: сумма может зависеть от оклада, ставок, KPI, премий и штрафов.
        </div>
      </section>

      <section class="card section-card payroll-lines-card">
        <div class="section-card__head">
          <div class="section-card__title">
            <b>Начисления сотрудникам</b>
            <div class="muted">Сумма, рабочая нагрузка и полный разбор компонентов профиля.</div>
          </div>
        </div>
        <div id="linesList" class="payroll-lines payroll-loading" aria-live="polite" aria-busy="true">
          <div class="payroll-line-skeleton skeleton"></div>
          <div class="payroll-line-skeleton skeleton"></div>
        </div>
      </section>

      <div class="payroll-footer">
        <button class="btn subtle inline" id="backVenue" type="button" data-nav-button>← Назад к заведению</button>
        <button class="btn subtle inline" id="openSummary" type="button" data-nav-button>Открыть сводку →</button>
      </div>
    </main>

    <div id="toast" class="toast"><div class="toast__text"></div></div>
    <div id="modal" class="modal">
      <div class="modal__backdrop"></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div class="modal__title">Детали</div>
          <button class="btn" data-close>Закрыть</button>
        </div>
        <div class="modal__body"></div>
      </div>
    </div>

    <div class="nav"><div class="wrap"><div id="nav"></div></div></div>
  `;

  mountCommonUI("none");
}

function getPeriodQuery() {
  const params = new URLSearchParams();
  if (state.periodMode === "range") {
    params.set("period_mode", "range");
    params.set("date_from", state.dateFrom);
    params.set("date_to", state.dateTo);
  } else {
    params.set("month", state.month);
  }
  params.set("compare_mode", state.compareMode);
  if (state.compareMode === "custom") {
    const comparison = currentComparison();
    if (comparison?.from) params.set("compare_from", comparison.from);
    if (comparison?.to) params.set("compare_to", comparison.to);
  }
  if (state.venueId) params.set("venue_id", state.venueId);
  return params;
}

function currentComparison() {
  return resolveComparisonRange({
    compareMode: state.compareMode,
    compareFrom: state.compareFrom,
    compareTo: state.compareTo,
    period: state.periodMode,
    month: state.month,
    from: state.dateFrom,
    to: state.dateTo,
  });
}

function syncComparisonControls() {
  const comparison = currentComparison();
  const custom = state.compareMode === "custom";
  const disabled = state.compareMode === "none";
  setVisible(document.getElementById("payrollCompareRange"), custom);
  document.querySelectorAll("#payrollCompareSeg button").forEach((button) => {
    button.classList.toggle("active", button.dataset.compare === state.compareMode);
  });
  const periodText = document.getElementById("payrollComparePeriodText");
  const hint = document.getElementById("payrollCompareHint");
  if (periodText) periodText.textContent = disabled ? "Сравнение отключено" : formatComparisonRange(comparison);
  if (hint) hint.textContent = disabled ? "Дополнительный период не загружается." : (comparison?.caption || "Выбери период сравнения");
  if (custom) {
    const from = document.getElementById("payrollCompareFrom");
    const to = document.getElementById("payrollCompareTo");
    if (from) from.value = comparison?.from || state.compareFrom || "";
    if (to) to.value = comparison?.to || state.compareTo || "";
  }
}

function syncUrl() {
  try {
    history.replaceState(null, "", `${location.pathname}?${getPeriodQuery().toString()}`);
  } catch {}
}

const DEFAULT_PAYMENT_RULES = [
  { payment_day: 5, period_start_day: 16, period_end_day: 31, period_month_offset: -1 },
  { payment_day: 20, period_start_day: 1, period_end_day: 15, period_month_offset: 0 },
];

function payrollCadenceLabel(value) {
  const cadence = String(value || "MONTHLY").toUpperCase();
  if (cadence === "DAILY") return "каждый день";
  if (cadence === "WEEKLY") return "раз в неделю";
  return "по датам месяца";
}

function paymentSettingsRules() {
  const rows = state.paymentSettings?.monthly_rules;
  return Array.isArray(rows) && rows.length ? rows : DEFAULT_PAYMENT_RULES;
}

function renderPaymentRuleRows(rules = paymentSettingsRules()) {
  const list = document.getElementById("payrollMonthlyRules");
  if (!list) return;
  const rows = Array.isArray(rules) && rules.length ? rules : [DEFAULT_PAYMENT_RULES[0]];
  list.innerHTML = rows.map((rule, index) => `
    <div class="payroll-payment-rule" data-payment-rule="${index}">
      <label><span>Выплата</span><span class="payroll-payment-rule__input"><input type="number" min="1" max="31" value="${Number(rule.payment_day || 1)}" data-rule-field="payment_day" /><span>числа</span></span></label>
      <label><span>Период с</span><input type="number" min="1" max="31" value="${Number(rule.period_start_day || 1)}" data-rule-field="period_start_day" /></label>
      <label><span>по</span><input type="number" min="1" max="31" value="${Number(rule.period_end_day || 31)}" data-rule-field="period_end_day" /></label>
      <label><span>Месяц периода</span><select data-rule-field="period_month_offset"><option value="0" ${Number(rule.period_month_offset || 0) === 0 ? "selected" : ""}>Текущий</option><option value="-1" ${Number(rule.period_month_offset || 0) === -1 ? "selected" : ""}>Предыдущий</option></select></label>
      <button class="btn subtle small payroll-payment-rule__remove" type="button" data-remove-payment-rule="${index}" aria-label="Удалить дату выплаты">Удалить</button>
    </div>
  `).join("");
}

function readPaymentRuleRows() {
  return [...document.querySelectorAll("[data-payment-rule]")].map((row) => {
    const value = (field) => Number(row.querySelector(`[data-rule-field="${field}"]`)?.value || 0);
    return {
      payment_day: value("payment_day"),
      period_start_day: value("period_start_day"),
      period_end_day: value("period_end_day"),
      period_month_offset: value("period_month_offset"),
    };
  });
}

function capturePaymentSettingsControls() {
  if (!state.paymentSettings) state.paymentSettings = {};
  state.paymentSettings.payment_method_id = Number(document.getElementById("payrollPaymentMethod")?.value || 0) || null;
  state.paymentSettings.cadence = String(document.getElementById("payrollPaymentCadence")?.value || state.paymentSettings.cadence || "MONTHLY").toUpperCase();
  state.paymentSettings.weekly_payment_weekday = Number(document.getElementById("payrollWeeklyDay")?.value || 0);
  state.paymentSettings.is_active = document.getElementById("payrollPaymentEnabled")?.checked !== false;
  state.paymentSettings.monthly_rules = readPaymentRuleRows();
}

function renderPaymentSettings() {
  const card = document.getElementById("payrollPaymentCard");
  if (!card) return;
  setVisible(card, state.can.view);
  if (!state.can.view) return;

  const settings = state.paymentSettings || {
    configured: false,
    cadence: "MONTHLY",
    weekly_payment_weekday: 0,
    monthly_rules: DEFAULT_PAYMENT_RULES,
    is_active: true,
    preview: [],
  };
  const paymentMethod = document.getElementById("payrollPaymentMethod");
  const cadence = document.getElementById("payrollPaymentCadence");
  const weeklyDay = document.getElementById("payrollWeeklyDay");
  const enabled = document.getElementById("payrollPaymentEnabled");
  const hint = document.getElementById("payrollPaymentHint");
  const badge = document.getElementById("payrollPaymentBadge");
  const summary = document.getElementById("payrollPaymentSummary");
  const configuredPaymentMethod = String(settings.payment_method_id || "");

  if (paymentMethod) {
    paymentMethod.innerHTML = '<option value="">Выберите способ оплаты</option>' + state.paymentMethods
      .filter((item) => item?.is_active !== false || String(item?.id) === configuredPaymentMethod)
      .map((item) => `<option value="${esc(item.id)}">${esc(item.title)}</option>`)
      .join("");
    paymentMethod.value = configuredPaymentMethod;
    paymentMethod.disabled = !state.can.calculate;
  }
  if (cadence) {
    cadence.value = String(settings.cadence || "MONTHLY").toUpperCase();
    cadence.disabled = !state.can.calculate;
  }
  if (weeklyDay) {
    weeklyDay.value = String(settings.weekly_payment_weekday ?? 0);
    weeklyDay.disabled = !state.can.calculate;
  }
  if (enabled) {
    enabled.checked = settings.is_active !== false;
    enabled.disabled = !state.can.calculate;
  }
  setVisible(document.getElementById("payrollWeeklyField"), String(settings.cadence).toUpperCase() === "WEEKLY");
  setVisible(document.getElementById("payrollMonthlyRulesWrap"), String(settings.cadence).toUpperCase() === "MONTHLY");
  renderPaymentRuleRows(settings.monthly_rules);
  document.querySelectorAll("#payrollMonthlyRules :is(input,select,button)").forEach((element) => {
    element.disabled = !state.can.calculate;
  });

  const preview = document.getElementById("payrollPaymentPreview");
  const previewRows = Array.isArray(settings.preview) ? settings.preview : [];
  if (preview) {
    preview.innerHTML = previewRows.length
      ? previewRows.map((item) => `<div class="payroll-payment-preview__row"><b>${esc(formatDateRu(item.payment_date))}</b><span>${esc(formatDateRu(item.period_start))} — ${esc(formatDateRu(item.period_end))}</span></div>`).join("")
      : '<span class="muted">Нет дат выплат для выбранного месяца.</span>';
  }
  const methodTitle = settings.payment_method?.title || state.paymentMethods.find((item) => String(item.id) === configuredPaymentMethod)?.title;
  if (summary) {
    summary.textContent = settings.configured
      ? `${methodTitle || "способ не выбран"} · ${payrollCadenceLabel(settings.cadence)}`
      : "Настройте способ оплаты и календарь выплат";
  }
  if (badge) badge.textContent = !settings.configured ? "Не настроено" : (settings.is_active ? "Включено" : "Выключено");
  if (hint) hint.textContent = state.paymentSettingsError
    ? `Настройки недоступны: ${state.paymentSettingsError}`
    : "Подтверждённый черновик создаёт проводку ФОТ, но не добавляет ФОТ второй раз в управленческую сводку.";
  const saveButton = document.getElementById("payrollSavePaymentSettings");
  const generateButton = document.getElementById("payrollGenerateDrafts");
  if (saveButton) saveButton.disabled = !state.can.calculate;
  if (generateButton) generateButton.disabled = !state.can.calculate || !settings.configured || settings.is_active === false;
  const draftsLink = document.getElementById("payrollOpenDrafts");
  if (draftsLink) draftsLink.href = `/owner-expenses.html?venue_id=${encodeURIComponent(state.venueId)}&month=${encodeURIComponent(state.month)}&statuses=DRAFT&expense_kind=PAYROLL`;
}

async function loadPaymentSettings() {
  if (!state.can.view) {
    renderPaymentSettings();
    return;
  }
  state.paymentSettingsError = null;
  try {
    const [paymentMethods, settings] = await Promise.all([
      api(`/venues/${encodeURIComponent(state.venueId)}/payment-methods`).catch(() => []),
      api(`/venues/${encodeURIComponent(state.venueId)}/payroll/payment-settings?month=${encodeURIComponent(state.month)}`),
    ]);
    state.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
    state.paymentSettings = settings;
  } catch (error) {
    state.paymentSettingsError = error?.data?.detail || error?.message || "не удалось загрузить";
  }
  renderPaymentSettings();
}

async function savePaymentSettings() {
  const paymentMethodId = Number(document.getElementById("payrollPaymentMethod")?.value || 0);
  if (!paymentMethodId) {
    toast("Выберите способ оплаты ФОТ", "err");
    return;
  }
  const cadence = String(document.getElementById("payrollPaymentCadence")?.value || "MONTHLY").toUpperCase();
  try {
    await api(`/venues/${encodeURIComponent(state.venueId)}/payroll/payment-settings`, {
      method: "PUT",
      body: {
        payment_method_id: paymentMethodId,
        cadence,
        weekly_payment_weekday: cadence === "WEEKLY" ? Number(document.getElementById("payrollWeeklyDay")?.value || 0) : null,
        monthly_rules: cadence === "MONTHLY" ? readPaymentRuleRows() : [],
        is_active: document.getElementById("payrollPaymentEnabled")?.checked !== false,
      },
    });
    toast("Настройки выплат сохранены", "ok");
    await loadPaymentSettings();
  } catch (error) {
    toast(error?.data?.detail || error?.message || "Не удалось сохранить настройки", "err");
  }
}

async function generatePaymentDrafts() {
  try {
    const result = await api(`/venues/${encodeURIComponent(state.venueId)}/payroll/payment-drafts/generate`, {
      method: "POST",
      body: { month: state.month },
    });
    const changed = Number(result?.created || 0) + Number(result?.updated || 0);
    toast(changed ? `Черновики ФОТ готовы: ${changed}` : "Новых черновиков ФОТ нет", changed ? "ok" : "warn");
  } catch (error) {
    toast(error?.data?.detail || error?.message || "Не удалось сформировать черновики", "err");
  }
}

function renderState() {
  const btnCalculate = document.getElementById("btnCalculate");
  const btnExport = document.getElementById("btnExport");
  const monthPick = document.getElementById("monthPick");
  const rangeFrom = document.getElementById("rangeFrom");
  const rangeTo = document.getElementById("rangeTo");
  const backVenue = document.getElementById("backVenue");
  const openSummary = document.getElementById("openSummary");
  const openProfilesBtn = document.getElementById("openProfilesBtn");
  const monthControls = document.getElementById("monthControls");
  const rangeControls = document.getElementById("rangeControls");
  const periodMonthBtn = document.getElementById("periodMonthBtn");
  const periodRangeBtn = document.getElementById("periodRangeBtn");
  const subtitle = document.getElementById("subtitle");

  if (subtitle) subtitle.textContent = periodTitle();
  if (monthPick) monthPick.value = state.month;
  if (rangeFrom) rangeFrom.value = state.dateFrom;
  if (rangeTo) rangeTo.value = state.dateTo;
  setVisible(monthControls, state.periodMode === "month");
  setVisible(rangeControls, !isDemoUiMode() && state.periodMode === "range");
  periodMonthBtn?.classList.toggle("active", state.periodMode === "month");
  periodRangeBtn?.classList.toggle("active", state.periodMode === "range");
  syncComparisonControls();

  setVisible(btnCalculate, state.can.calculate && state.periodMode === "month");
  setVisible(btnExport, state.can.view);
  if (backVenue) backVenue.href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;
  if (openSummary) {
    if (state.periodMode === "month") {
      setVisible(openSummary, true);
      openSummary.href = `/owner-summary.html?venue_id=${encodeURIComponent(state.venueId)}&month=${encodeURIComponent(state.month)}`;
    } else {
      setVisible(openSummary, false);
    }
  }
  if (openProfilesBtn) openProfilesBtn.href = `/owner-pay-profiles.html?venue_id=${encodeURIComponent(state.venueId)}`;
  syncUrl();
}

function recalculationText(latestRecalc, runCalculatedAt) {
  const reasonMap = {
    manual_calculation: "ручной расчёт",
    report_closed: "после закрытия отчёта",
    report_reopened: "после переоткрытия отчёта",
    closed_report_updated: "после правки закрытого отчёта",
    shift_assignment_added: "после назначения",
    shift_assignment_removed: "после снятия назначения",
    shift_updated: "после изменения смены",
    shift_deleted: "после удаления смены",
    member_removed_from_venue: "после удаления участника",
    member_left_venue: "после выхода участника",
  };
  const dt = runCalculatedAt ? new Date(runCalculatedAt) : null;
  const baseText = dt && !Number.isNaN(dt.getTime())
    ? `обновлено ${dt.toLocaleString("ru-RU")}`
    : (latestRecalc?.created_at ? `обновлено ${new Date(latestRecalc.created_at).toLocaleString("ru-RU")}` : "есть перерасчёт");
  const reason = String(latestRecalc?.trigger_reason || "");
  return reason ? `${baseText} · ${reasonMap[reason] || "автоперерасчёт"}` : baseText;
}

function renderPayrollLeaderboard(analytics) {
  const list = document.getElementById("payrollLeaderboard");
  const subtitle = document.getElementById("payrollLeaderboardSubtitle");
  const threshold = document.getElementById("payrollLeaderboardThreshold");
  const note = document.getElementById("payrollLeaderboardNote");
  if (!list) return;
  list.classList.remove("payroll-loading");
  list.setAttribute("aria-busy", "false");
  if (threshold) threshold.textContent = `минимум ${analytics.minimumShifts} смены`;
  if (subtitle) {
    subtitle.textContent = state.periodMode === "month"
      ? `Топ за ${state.month}: среднее начисление, количество смен и итоговая сумма.`
      : `Топ за ${formatDateRu(state.dateFrom)} — ${formatDateRu(state.dateTo)}.`;
  }
  if (note) {
    const excluded = analytics.excludedSmallSampleCount
      ? ` ${analytics.excludedSmallSampleCount} сотрудник(а) с меньшим числом смен не участвуют в ранжировании.`
      : "";
    note.textContent = `Это рейтинг начислений, а не личных продаж: сумма может зависеть от оклада, ставок, KPI, премий и штрафов.${excluded}`;
  }
  if (!state.can.view) {
    list.innerHTML = '<div class="payroll-state payroll-state--denied"><b>Нет доступа к рейтингу</b><span>Для сравнения нужны права на начисления.</span></div>';
    return;
  }
  if (financialValuesHidden) {
    list.innerHTML = `<div class="payroll-state"><b>${esc(FINANCIAL_VALUES_HIDDEN_LABEL)}</b><span>Рейтинг не строится без доступных финансовых значений.</span></div>`;
    return;
  }
  if (!analytics.rows.length) {
    list.innerHTML = `<div class="payroll-state payroll-state--empty"><b>Пока недостаточно смен для рейтинга</b><span>Нужно минимум ${esc(analytics.minimumShifts)} смены у сотрудника за выбранный период.</span></div>`;
    return;
  }
  list.innerHTML = analytics.rows.map((entry) => {
    const delta = Number(entry.deltaFromTeamAverageMinor || 0);
    const deltaText = delta === 0
      ? "на уровне среднего по команде"
      : `${fmtMoneyMinor(Math.abs(delta))} ${delta > 0 ? "выше" : "ниже"} среднего по команде`;
    return `<article class="payroll-leaderboard-row" aria-label="${esc(memberName(entry.line?.member))}: ${esc(fmtMoneyMinor(entry.averagePerShiftMinor))} за смену">
      <div class="payroll-leaderboard-rank" aria-hidden="true">${entry.rank}</div>
      <div class="payroll-leaderboard-main">
        <div class="payroll-leaderboard-row__head">
          <div>
            <div class="payroll-leaderboard-name">${esc(memberName(entry.line?.member))}</div>
            <div class="payroll-leaderboard-meta">${entry.shiftsCount} смен · ${esc(fmtMoneyMinor(entry.amountMinor))} за период</div>
          </div>
          <div class="payroll-leaderboard-value">
            <b>${esc(fmtMoneyMinor(entry.averagePerShiftMinor))}</b>
            <span>за смену</span>
          </div>
        </div>
        <svg class="payroll-leaderboard-bar" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true">
          <rect class="payroll-leaderboard-track" x="0" y="0" width="100" height="8" rx="4"></rect>
          <rect class="payroll-leaderboard-fill" x="0" y="0" width="${entry.relativeWidthPercent.toFixed(2)}" height="8" rx="4"></rect>
        </svg>
        <div class="payroll-leaderboard-delta">${esc(deltaText)}</div>
      </div>
    </article>`;
  }).join("");
}

function renderLines() {
  const totalAmount = document.getElementById("totalAmount");
  const linesCount = document.getElementById("linesCount");
  const averageAmount = document.getElementById("averageAmount");
  const averagePerShift = document.getElementById("averagePerShift");
  const runMeta = document.getElementById("runMeta");
  const linesList = document.getElementById("linesList");
  if (!linesList) return;

  const settleMetric = (element, value) => {
    if (!element) return;
    element.textContent = value;
    element.classList.remove("is-loading");
    element.setAttribute("aria-busy", "false");
  };
  linesList.classList.remove("payroll-loading");
  linesList.setAttribute("aria-busy", "false");

  if (!state.can.view) {
    linesList.innerHTML = `<div class="payroll-state payroll-state--denied"><b>Нет доступа к начислениям</b><span>Для просмотра ФОТ нужны права на начисления.</span></div>`;
    settleMetric(totalAmount, "—");
    settleMetric(linesCount, "—");
    settleMetric(averageAmount, "—");
    settleMetric(averagePerShift, "—");
    settleMetric(runMeta, "нет доступа");
    renderPayrollLeaderboard(buildPayrollTeamAnalytics([]));
    return;
  }

  const data = state.data || { lines: [], total_amount_minor: 0, lines_count: 0, run: null, latest_recalculation: null };
  const calculatedLinesCount = Number(data.lines_count || 0);
  const comparisonData = state.comparisonData || null;
  const comparisonLinesCount = Number(comparisonData?.lines_count || 0);
  const currentAverage = calculatedLinesCount ? Math.round(Number(data.total_amount_minor || 0) / calculatedLinesCount) : 0;
  const comparisonAverage = comparisonLinesCount ? Math.round(Number(comparisonData?.total_amount_minor || 0) / comparisonLinesCount) : 0;
  const lines = Array.isArray(data.lines) ? data.lines : [];
  const comparisonLines = Array.isArray(comparisonData?.lines) ? comparisonData.lines : [];
  const analytics = buildPayrollTeamAnalytics(lines, { minimumShifts: 3, maxRows: 6 });
  const comparisonAnalytics = buildPayrollTeamAnalytics(comparisonLines, { minimumShifts: 3, maxRows: 6 });
  settleMetric(totalAmount, fmtMoneyMinor(data.total_amount_minor));
  settleMetric(linesCount, String(calculatedLinesCount));
  settleMetric(
    averageAmount,
    calculatedLinesCount ? fmtMoneyMinor(currentAverage) : "—",
  );
  settleMetric(
    averagePerShift,
    analytics.teamAveragePerShiftMinor === null ? "—" : fmtMoneyMinor(analytics.teamAveragePerShiftMinor),
  );
  renderPayrollMetricDelta("totalAmountDelta", data.total_amount_minor, comparisonData?.total_amount_minor, { money: true, goodWhen: "down" });
  renderPayrollMetricDelta("linesCountDelta", calculatedLinesCount, comparisonData?.lines_count, { goodWhen: "neutral" });
  renderPayrollMetricDelta("averageAmountDelta", currentAverage, comparisonData ? comparisonAverage : null, { money: true, goodWhen: "down" });
  renderPayrollMetricDelta(
    "averagePerShiftDelta",
    analytics.teamAveragePerShiftMinor,
    comparisonData ? comparisonAnalytics.teamAveragePerShiftMinor : null,
    { money: true, goodWhen: "neutral" },
  );
  renderPayrollLeaderboard(analytics);
  if (runMeta) {
    if (data.run?.calculated_at) {
      const metaText = recalculationText(data.latest_recalculation, data.run.calculated_at);
      settleMetric(runMeta, metaText);
    } else if (data.latest_recalculation?.created_at) {
      const metaText = recalculationText(data.latest_recalculation, null);
      settleMetric(runMeta, metaText);
    } else {
      const metaText = state.periodMode === "month" ? "ещё не считалось" : "агрегация по дневным начислениям";
      settleMetric(runMeta, metaText);
    }
  }

  if (!lines.length) {
    const emptyText = state.periodMode === "month"
      ? "За выбранный месяц начислений пока нет. Нажми «Рассчитать», если профили уже назначены."
      : "За выбранный диапазон начислений пока нет.";
    linesList.innerHTML = `<div class="payroll-state payroll-state--empty"><b>Нет строк начислений</b><span>${esc(emptyText)}</span></div>`;
    return;
  }

  linesList.innerHTML = "";
  const comparisonLinesByMember = new Map(
    comparisonLines.map((line) => [
      String(line?.member_user_id ?? line?.member?.user_id ?? ""),
      line,
    ]),
  );
  lines.forEach((line) => {
    const breakdown = line.breakdown || {};
    const metrics = breakdown.metrics || {};
    const components = Array.isArray(breakdown.components) ? breakdown.components : [];
    const row = document.createElement("div");
    row.className = "payroll-person";
    row.dataset.payrollLineId = String(line?.id || "");
    row.dataset.memberUserId = String(line?.member_user_id ?? line?.member?.user_id ?? "");
    const periodState = String(line.period_state || breakdown.period_state || "").toLowerCase();
    const stateBadge = periodState === "partial"
      ? '<span class="badge">частично</span>'
      : (periodState === "ready" ? '' : '');
    const workedDatesCount = Number(metrics.worked_dates_count || 0);
    const shiftMetrics = payrollLineShiftMetrics(line);
    const comparisonLine = comparisonLinesByMember.get(String(line?.member_user_id ?? line?.member?.user_id ?? ""));
    const personDelta = comparisonLine && !financialValuesHidden
      ? payrollDeltaView(line.amount_minor, comparisonLine.amount_minor, { money: true, goodWhen: "neutral" })
      : null;
    row.innerHTML = `
      <div class="payroll-person__main">
        <div class="payroll-person__head">
          <div class="payroll-person__identity">
            <div class="payroll-person__title">
              <b>${esc(memberName(line.member))}</b>
              ${line.pay_profile_title ? `<span class="badge">${esc(line.pay_profile_title)}</span>` : ""}
              ${stateBadge}
            </div>
            <div class="payroll-person__metrics">
              <span><b>${esc(metrics.hours_total ?? 0)}</b> ч</span>
              <span><b>${esc(metrics.shifts_count ?? 0)}</b> смен</span>
              ${workedDatesCount ? `<span><b>${esc(workedDatesCount)}</b> дней</span>` : ""}
              ${shiftMetrics.averagePerShiftMinor === null ? "" : `<span class="payroll-person__metric-average"><b>${esc(fmtMoneyMinor(shiftMetrics.averagePerShiftMinor))}</b> за смену</span>`}
            </div>
          </div>
          <div>
            <div class="payroll-person__amount">${esc(fmtMoneyMinor(line.amount_minor))}</div>
            ${personDelta ? `<div class="payroll-person__delta ${personDelta.tone}">${esc(personDelta.text)}</div>` : ""}
          </div>
        </div>
        <details class="mt-12 payroll-breakdown">
          <summary>${state.periodMode === "month" ? "Показать разбор" : "Показать разбор периода"}</summary>
          <div class="payroll-breakdown__body mt-8">
            ${components.length ? components.map((c) => `
              <div class="payroll-breakdown__row">
                <div class="payroll-breakdown__meta">
                  <div class="payroll-breakdown__header">
                    <div>
                      <div class="payroll-breakdown__eyebrow">${esc(COMPONENT_LABELS[String(c.component_type || '').toUpperCase()] || c.component_type || 'Компонент')}</div>
                      <div class="payroll-breakdown__title">${esc(c.title || c.component_type || "Компонент")}</div>
                      <div class="payroll-breakdown__explain">${esc(breakdownExplain(c))}</div>
                    </div>
                    <div class="payroll-breakdown__amount">${esc(fmtMoneyMinor(c.amount_minor || 0))}</div>
                  </div>
                  <div class="mono mt-6">${esc(breakdownComponentMeta(c))}</div>
                  ${breakdownBadges(c)}
                  ${breakdownKv(c)}
                  ${breakdownDayRows(c)}
              ${breakdownShiftRows(c)}
                </div>
              </div>
            `).join("") : `<div class="muted">Нет breakdown</div>`}
          </div>
        </details>
      </div>
    `;
    linesList.appendChild(row);
  });
  focusLinkedPayrollLine();
}

function focusLinkedPayrollLine() {
  if (state.sourceTargetFocused) return;
  const target = state.focusPayrollLineId
    ? document.querySelector(`[data-payroll-line-id="${state.focusPayrollLineId}"]`)
    : (state.focusMemberUserId ? document.querySelector(`[data-member-user-id="${state.focusMemberUserId}"]`) : null);
  if (!target) return;
  state.sourceTargetFocused = true;
  target.classList.add("is-source-target");
  target.setAttribute("tabindex", "-1");
  const details = target.querySelector("details");
  if (details) details.open = true;
  requestAnimationFrame(() => {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.focus({ preventScroll: true });
  });
}

function buildPayrollPath() {
  if (state.periodMode === "range") {
    return `/venues/${encodeURIComponent(state.venueId)}/payroll?date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}`;
  }
  return `/venues/${encodeURIComponent(state.venueId)}/payroll?month=${encodeURIComponent(state.month)}`;
}

function buildComparisonPayrollPath() {
  const comparison = currentComparison();
  return `/venues/${encodeURIComponent(state.venueId)}/payroll?date_from=${encodeURIComponent(comparison?.from || todayIso())}&date_to=${encodeURIComponent(comparison?.to || comparison?.from || todayIso())}`;
}

function payrollDeltaView(currentValue, previousValue, { money = false, goodWhen = "neutral" } = {}) {
  if (previousValue === null || previousValue === undefined) return null;
  const current = Number(currentValue || 0);
  const previous = Number(previousValue || 0);
  const delta = current - previous;
  const good = (goodWhen === "up" && delta > 0) || (goodWhen === "down" && delta < 0);
  const bad = (goodWhen === "up" && delta < 0) || (goodWhen === "down" && delta > 0);
  const tone = good ? "is-good" : bad ? "is-bad" : "is-neutral";
  const absolute = money
    ? `${delta > 0 ? "+" : delta < 0 ? "−" : ""}${fmtMoneyMinor(Math.abs(delta))}`
    : `${delta > 0 ? "+" : ""}${delta.toLocaleString("ru-RU")}`;
  if (previous === 0) {
    return { text: current === 0 ? "Без изменений" : `Нет базы · ${absolute}`, tone };
  }
  const percent = delta / Math.abs(previous) * 100;
  const sign = percent > 0 ? "+" : percent < 0 ? "−" : "";
  return {
    text: `${sign}${Math.abs(percent).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% · ${absolute}`,
    tone,
  };
}

function renderPayrollMetricDelta(id, currentValue, previousValue, options) {
  const element = document.getElementById(id);
  if (!element) return;
  element.classList.remove("is-good", "is-bad", "is-neutral");
  if (financialValuesHidden || !state.comparisonData) {
    element.textContent = state.comparisonError ? "Сравнение недоступно" : "—";
    element.classList.add("is-neutral");
    return;
  }
  const view = payrollDeltaView(currentValue, previousValue, options);
  element.textContent = view ? `${view.text} ${currentComparison()?.caption || ""}`.trim() : "—";
  element.classList.add(view?.tone || "is-neutral");
}

async function load() {
  const linesList = document.getElementById("linesList");
  const leaderboard = document.getElementById("payrollLeaderboard");
  if (linesList) {
    linesList.classList.add("payroll-loading");
    linesList.setAttribute("aria-busy", "true");
    linesList.innerHTML = `<div class="payroll-line-skeleton skeleton"></div><div class="payroll-line-skeleton skeleton"></div>`;
  }
  if (leaderboard) {
    leaderboard.classList.add("payroll-loading");
    leaderboard.setAttribute("aria-busy", "true");
    leaderboard.innerHTML = '<div class="payroll-leaderboard-skeleton skeleton"></div>';
  }
  try {
    const primaryPromise = api(buildPayrollPath());
    const comparisonPromise = state.compareMode === "none"
      ? Promise.resolve({ value: null })
      : api(buildComparisonPayrollPath())
          .then((value) => ({ value }))
          .catch((error) => ({ error }));
    const [data, comparisonResult] = await Promise.all([primaryPromise, comparisonPromise]);
    state.data = data;
    state.comparisonData = comparisonResult.value || null;
    state.comparisonError = comparisonResult.error || null;
    renderLines();
  } catch (e) {
    const detail = e?.data?.detail || e?.message || "не удалось загрузить";
    if (linesList) {
      linesList.classList.remove("payroll-loading");
      linesList.setAttribute("aria-busy", "false");
      linesList.innerHTML = `<div class="payroll-state payroll-state--error"><b>Не удалось загрузить начисления</b><span>${esc(detail)}</span></div>`;
    }
    if (leaderboard) {
      leaderboard.classList.remove("payroll-loading");
      leaderboard.setAttribute("aria-busy", "false");
      leaderboard.innerHTML = `<div class="payroll-state payroll-state--error"><b>Рейтинг недоступен</b><span>${esc(detail)}</span></div>`;
    }
    toast("Не удалось загрузить начисления", "err");
  }
}

async function onCalculate() {
  try {
    await calculatePayroll(state.venueId, state.month);
    toast("Расчёт выполнен", "ok");
    await load();
  } catch (e) {
    toast("Ошибка расчёта: " + (e?.data?.detail || e?.message || "не удалось рассчитать"), "err");
  }
}

function setPeriodMode(next) {
  state.periodMode = next === "range" ? "range" : "month";
  renderState();
}

async function applyRangeFromControls() {
  const nextFrom = String(document.getElementById("rangeFrom")?.value || "").trim();
  const nextTo = String(document.getElementById("rangeTo")?.value || "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(nextFrom) || !/^\d{4}-\d{2}-\d{2}$/.test(nextTo)) {
    toast("Выбери даты периода", "err");
    return;
  }
  state.dateFrom = nextFrom <= nextTo ? nextFrom : nextTo;
  state.dateTo = nextTo >= nextFrom ? nextTo : nextFrom;
  renderState();
  if (isDemoUiMode()) {
    setVisible(document.getElementById("periodRangeBtn"), false);
    setVisible(document.getElementById("rangeControls"), false);
  }

  await load();
}

async function boot() {
  applyTelegramTheme();
  renderShell();
  await ensureLogin({ silent: true });

  state.venueId = parseVenueId();
  if (!state.venueId) {
    root.innerHTML = `<div class="card"><div class="muted">Не найден venue_id</div></div>`;
    return;
  }

  const params = new URLSearchParams(location.search);
  state.month = coerceDemoMonth(params.get("month") || currentMonth(), { notify: false, context: "owner-payroll" });
  state.focusPayrollLineId = Number(params.get("payroll_line_id") || 0) || null;
  state.focusMemberUserId = Number(params.get("member_user_id") || 0) || null;
  const hasRange = /^\d{4}-\d{2}-\d{2}$/.test(String(params.get("date_from") || "")) && /^\d{4}-\d{2}-\d{2}$/.test(String(params.get("date_to") || ""));
  state.periodMode = (params.get("period_mode") || (hasRange ? "range" : "month")).toLowerCase() === "range" ? "range" : "month";
  if (isDemoUiMode()) state.periodMode = "month";
  const demoRangePayroll = coerceDemoRange(hasRange ? String(params.get("date_from")) : monthStartIso(state.month), hasRange ? String(params.get("date_to")) : monthEndIso(state.month), { notify: false, context: "owner-payroll" });
  state.dateFrom = demoRangePayroll.from || (hasRange ? String(params.get("date_from")) : monthStartIso(state.month));
  state.dateTo = demoRangePayroll.to || (hasRange ? String(params.get("date_to")) : monthEndIso(state.month));
  if (state.dateTo < state.dateFrom) state.dateTo = state.dateFrom;
  state.compareMode = ["auto", "custom", "none"].includes(params.get("compare_mode")) ? params.get("compare_mode") : "auto";
  state.compareFrom = params.get("compare_from") || "";
  state.compareTo = params.get("compare_to") || "";

  await mountNav({ activeTab: "summary" });

  try {
    state.me = await getMe();
  } catch {
    state.me = null;
  }

  try {
    state.perms = await getMyVenuePermissions(state.venueId);
    financialValuesHidden = isFinancialValuesHidden(state.perms);
  } catch {
    state.perms = null;
  }

  state.can = applyDemoReadonlyCaps(computeCaps(state.perms, state.me), { source: state.perms });
  renderState();
  renderDemoOwnerPayrollIntro();

  document.getElementById("payrollPaymentCadence")?.addEventListener("change", (event) => {
    capturePaymentSettingsControls();
    state.paymentSettings.cadence = event.target.value || "MONTHLY";
    renderPaymentSettings();
  });
  document.getElementById("payrollAddPaymentRule")?.addEventListener("click", () => {
    capturePaymentSettingsControls();
    const rows = readPaymentRuleRows();
    const previous = rows.at(-1);
    const nextDay = Math.min(31, Math.max(1, Number(previous?.payment_day || 0) + 10));
    rows.push({ payment_day: nextDay, period_start_day: 1, period_end_day: 31, period_month_offset: 0 });
    if (!state.paymentSettings) state.paymentSettings = {};
    state.paymentSettings.monthly_rules = rows;
    renderPaymentSettings();
  });
  document.getElementById("payrollMonthlyRules")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-payment-rule]");
    if (!button) return;
    capturePaymentSettingsControls();
    const removeIndex = Number(button.dataset.removePaymentRule || -1);
    const rows = readPaymentRuleRows().filter((_item, index) => index !== removeIndex);
    if (!rows.length) {
      toast("Нужен хотя бы один период выплаты", "warn");
      return;
    }
    if (!state.paymentSettings) state.paymentSettings = {};
    state.paymentSettings.monthly_rules = rows;
    renderPaymentSettings();
  });
  document.getElementById("payrollSavePaymentSettings")?.addEventListener("click", savePaymentSettings);
  document.getElementById("payrollGenerateDrafts")?.addEventListener("click", generatePaymentDrafts);

  document.getElementById("periodMonthBtn")?.addEventListener("click", async () => {
    if (state.periodMode === "month") return;
    setPeriodMode("month");
    await load();
  });
  document.getElementById("periodRangeBtn")?.addEventListener("click", async () => {
    if (state.periodMode === "range") return;
    if (isDemoUiMode()) return;
    setPeriodMode("range");
    await load();
  });

  document.getElementById("monthPick")?.addEventListener("change", async (e) => {
    state.month = coerceDemoMonth(e.target.value || currentMonth(), { context: "owner-payroll" });
    if (!state.dateFrom || !state.dateTo) {
      state.dateFrom = monthStartIso(state.month);
      state.dateTo = monthEndIso(state.month);
    }
    renderState();
    await Promise.all([load(), loadPaymentSettings()]);
  });

  document.getElementById("rangeApply")?.addEventListener("click", async () => {
    if (isDemoUiMode()) {
      const demoRange = coerceDemoRange(state.dateFrom, state.dateTo, { context: "owner-payroll" });
      state.dateFrom = demoRange.from;
      state.dateTo = demoRange.to;
      state.periodMode = "month";
      renderState();
      await load();
      return;
    }
    await applyRangeFromControls();
  });
  document.querySelectorAll("#payrollCompareSeg button").forEach((button) => {
    button.addEventListener("click", async () => {
      const requestedMode = button.dataset.compare;
      const mode = ["auto", "custom", "none"].includes(requestedMode) ? requestedMode : "auto";
      if (mode === "custom" && state.compareMode !== "custom") {
        const automatic = resolveAutoComparison({
          period: state.periodMode,
          month: state.month,
          from: state.dateFrom,
          to: state.dateTo,
        });
        state.compareFrom = automatic?.from || todayIso();
        state.compareTo = automatic?.to || state.compareFrom;
      }
      state.compareMode = mode;
      renderState();
      if (mode !== "custom") await load();
    });
  });
  document.getElementById("payrollCompareFrom")?.addEventListener("change", (event) => {
    state.compareFrom = event.target.value || state.compareFrom;
  });
  document.getElementById("payrollCompareTo")?.addEventListener("change", (event) => {
    state.compareTo = event.target.value || state.compareTo;
  });
  document.getElementById("payrollCompareApply")?.addEventListener("click", async () => {
    const normalized = normalizeIsoRange(state.compareFrom, state.compareTo);
    if (!normalized) {
      toast("Выбери даты сравнения", "err");
      return;
    }
    state.compareFrom = normalized.from;
    state.compareTo = normalized.to;
    renderState();
    await load();
  });
  document.getElementById("btnCalculate")?.addEventListener("click", onCalculate);
  document.getElementById("btnExport")?.addEventListener("click", async () => {
    try {
      const qs = new URLSearchParams();
      if (state.periodMode === "range") {
        qs.set("date_from", state.dateFrom);
        qs.set("date_to", state.dateTo);
      } else {
        qs.set("month", state.month);
      }
      await openExportLink(`/venues/${encodeURIComponent(state.venueId)}/payroll/export-link?${qs.toString()}`);
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось начать экспорт", "err");
    }
  });

  await Promise.all([load(), loadPaymentSettings()]);
}

document.addEventListener("DOMContentLoaded", boot);


function mountDemoFlowTour() {
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) return;
  const venue = parseVenueId();
  const q = venue ? `?venue_id=${encodeURIComponent(String(venue))}` : "";
  mountDemoPageTour({
    tourId: "demo-owner-flow",
    step: 3,
    total: 4,
    title: "Продолжение DEMO-тура",
    text: "Здесь видно ФОТ и детализацию начислений. После этого открой карточку заведения как финальный экран маршрута.",
    prevPath: `/owner-expenses.html${q}`,
    nextPath: `/app-venue.html${q}`,
  });
}

try { mountDemoFlowTour(); } catch {}

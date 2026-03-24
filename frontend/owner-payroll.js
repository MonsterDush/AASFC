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
} from "/app.js";
import { permSetFromResponse, roleUpper, hasPerm } from "/permissions.js";

const root = document.getElementById("root");

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
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
  return `${y}-${m}`;
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
  const value = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";
  } catch {
    return value.toFixed(2) + " ₽";
  }
}

function memberName(member) {
  if (!member) return "—";
  return member.short_name || member.full_name || (member.tg_username ? `@${member.tg_username}` : `user #${member.user_id || ""}`);
}

const COMPONENT_LABELS = {
  SALARY_FIXED_MONTH: "Оклад за месяц",
  SALARY_HOURLY: "Почасовая ставка",
  SALARY_PER_SHIFT: "Фикс за смену",
  PERCENT_TOTAL_REVENUE: "% от общей выручки",
  PERCENT_DEPARTMENT_REVENUE: "% от выручки департамента",
  KPI_BONUS: "KPI-бонус",
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

function breakdownComponentMeta(component) {
  const type = String(component?.component_type || "").toUpperCase();
  const label = COMPONENT_LABELS[type] || type || "Компонент";
  if (type === "PERCENT_TOTAL_REVENUE" || type === "PERCENT_DEPARTMENT_REVENUE") {
    const parts = [label, fmtPercentBps(component?.percent_bps || 0), `база ${fmtMoneyMinor(component?.base_amount_minor || 0)}`];
    if (component?.department_title) parts.push(component.department_title);
    if (component?.base_scope_title) parts.push(component.base_scope_title);
    if (component?.boost_enabled && component?.boost_percent_bps != null) {
      parts.push(`boost ${fmtPercentBps(component.boost_percent_bps)}`);
      if (component?.boost_source_title) parts.push(component.boost_source_title);
      if (component?.boost_applied) parts.push('сработал');
    }
    if (component?.minimum_applied) parts.push('мин. гарантия');
    if (component?.maximum_applied) parts.push('потолок');
    return parts.join(' · ');
  }
  if (type === "KPI_BONUS") {
    const metricTitle = component?.kpi_metric_title ? ` · ${component.kpi_metric_title}` : "";
    const metricValue = component?.metric_value != null ? ` · факт ${component.metric_value}` : "";
    const thresholdValue = component?.threshold_value != null ? ` · порог ${component.threshold_value}` : "";
    const matchedStep = component?.matched_step?.threshold_value != null ? ` · ступень ${component.matchedStep?.threshold_value}` : "";
    return `${label}${metricTitle}${metricValue}${thresholdValue}${matchedStep}`;
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
    if (snap.minimum_guarantee_minor != null) push('Мин. гарантия', fmtMoneyMinor(snap.minimum_guarantee_minor));
    if (snap.maximum_cap_minor != null) push('Максимум', fmtMoneyMinor(snap.maximum_cap_minor));
  }
  if (type === 'KPI_BONUS') {
    if (component?.kpi_metric_title) push('KPI', component.kpi_metric_title);
    if (component?.metric_value != null) push('Факт KPI', String(component.metric_value));
    if (component?.threshold_value != null) push('Порог', String(component.threshold_value));
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
    return `<div class="payroll-breakdown__dayrow"><div class="payroll-breakdown__dayrow-main"><div class="payroll-breakdown__dayrow-date">${esc(formatDateRu(row.date))}</div><div class="payroll-breakdown__dayrow-meta">${esc(meta.join(' · '))}</div></div><div class="payroll-breakdown__dayrow-amount">${esc(fmtMoneyMinor(row.amount_minor || 0))}</div></div>`;
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
    : `сводка начислений за диапазон ${formatDateRu(state.dateFrom)} — ${formatDateRu(state.dateTo)}`;
}

function renderShell() {
  root.innerHTML = `
    <div class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div class="title">
          <b id="title">Начисления</b>
          <div class="muted" id="subtitle">${esc(periodTitle())}</div>
        </div>
      </div>
      <div class="userpill" data-userpill>…</div>
    </div>

    <div class="card">
      <div class="revenue-toolbar__actions">
        <div class="revenue-toolbar__caption">
          <b>Расчёт зарплаты</b>
          <div class="muted mt-6">Считается по активным назначениям профилей. Поддержаны ставки, проценты и KPI-бонусы по закрытым отчётам.</div>
        </div>
        <div class="pickers pickers--revenue">
          <div class="seg seg--period" id="periodSeg" style="min-width:220px;">
            <button type="button" id="periodMonthBtn">Месяц</button>
            <button type="button" id="periodRangeBtn">Диапазон</button>
          </div>
          <div id="monthControls" class="pickers">
            <input id="monthPick" type="month" style="width:auto; min-width:160px;" />
          </div>
          <div id="rangeControls" class="range-pick" style="display:none;">
            <input id="rangeFrom" type="date" />
            <input id="rangeTo" type="date" />
            <button class="btn" id="rangeApply">Показать</button>
          </div>
          <button class="btn primary" id="btnCalculate">Рассчитать</button>
          <button class="btn" id="btnExport">Экспорт XLSX</button>
          <a class="btn" id="openProfilesBtn" href="#">Профили</a>
        </div>
      </div>

      <div class="finance-stats finance-stats-1 mt-12" style="grid-template-columns:repeat(3,minmax(0,1fr));">
        <div class="itemcard finance-stat">
          <div class="finance-stat__label">Итого</div>
          <div class="finance-stat__value" id="totalAmount">—</div>
        </div>
        <div class="itemcard finance-stat">
          <div class="finance-stat__label">Сотрудников</div>
          <div class="finance-stat__value" id="linesCount">—</div>
        </div>
        <div class="itemcard finance-stat">
          <div class="finance-stat__label">Статус расчёта</div>
          <div class="finance-stat__value" id="runMeta">—</div>
        </div>
      </div>

      <div class="itemcard mt-12">
        <div class="section-head">
          <div class="section-title"><b>Строки начислений</b></div>
        </div>
        <div id="linesList" class="mt-12"><div class="skeleton"></div><div class="skeleton"></div></div>
      </div>

      <div class="row mt-12" style="justify-content:space-between; gap:12px; flex-wrap:wrap;">
        <a class="link" id="backVenue" href="#">← Назад к заведению</a>
        <a class="link" id="openSummary" href="#">Открыть сводку →</a>
      </div>
    </div>

    <div id="toast" class="toast"><div class="toast__text"></div></div>
    <div id="modal" class="modal">
      <div class="modal__backdrop"></div>
      <div class="modal__panel">
        <div class="modal__head">
          <div class="modal__title">JSON</div>
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
  if (state.venueId) params.set("venue_id", state.venueId);
  return params;
}

function syncUrl() {
  try {
    history.replaceState(null, "", `${location.pathname}?${getPeriodQuery().toString()}`);
  } catch {}
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
  if (monthControls) monthControls.style.display = state.periodMode === "month" ? "" : "none";
  if (rangeControls) rangeControls.style.display = state.periodMode === "range" ? "" : "none";
  periodMonthBtn?.classList.toggle("active", state.periodMode === "month");
  periodRangeBtn?.classList.toggle("active", state.periodMode === "range");

  if (btnCalculate) btnCalculate.style.display = (state.can.calculate && state.periodMode === "month") ? "" : "none";
  if (btnExport) btnExport.style.display = state.can.view ? "" : "none";
  if (backVenue) backVenue.href = `/app-venue.html?venue_id=${encodeURIComponent(state.venueId)}`;
  if (openSummary) {
    if (state.periodMode === "month") {
      openSummary.style.display = "";
      openSummary.href = `/owner-summary.html?venue_id=${encodeURIComponent(state.venueId)}&month=${encodeURIComponent(state.month)}`;
    } else {
      openSummary.style.display = "none";
    }
  }
  if (openProfilesBtn) openProfilesBtn.href = `/owner-pay-profiles.html?venue_id=${encodeURIComponent(state.venueId)}`;
  syncUrl();
}

function recalculationText(latestRecalc, runCalculatedAt) {
  const reasonMap = {
    manual_calculation: "ручной расчёт",
    report_closed: "после закрытия отчёта",
    report_reopened: "после reopen",
    closed_report_updated: "после правки CLOSED-отчёта",
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

function renderLines() {
  const totalAmount = document.getElementById("totalAmount");
  const linesCount = document.getElementById("linesCount");
  const runMeta = document.getElementById("runMeta");
  const linesList = document.getElementById("linesList");
  if (!linesList) return;

  if (!state.can.view) {
    linesList.innerHTML = `<div class="muted">Нет доступа к начислениям</div>`;
    if (totalAmount) totalAmount.textContent = "—";
    if (linesCount) linesCount.textContent = "—";
    if (runMeta) runMeta.textContent = "нет доступа";
    return;
  }

  const data = state.data || { lines: [], total_amount_minor: 0, lines_count: 0, run: null, latest_recalculation: null };
  if (totalAmount) totalAmount.textContent = fmtMoneyMinor(data.total_amount_minor);
  if (linesCount) linesCount.textContent = String(Number(data.lines_count || 0));
  if (runMeta) {
    if (data.run?.calculated_at) {
      runMeta.textContent = recalculationText(data.latest_recalculation, data.run.calculated_at);
    } else if (data.latest_recalculation?.created_at) {
      runMeta.textContent = recalculationText(data.latest_recalculation, null);
    } else {
      runMeta.textContent = state.periodMode === "month" ? "ещё не считалось" : "агрегация по дневным начислениям";
    }
  }

  const lines = Array.isArray(data.lines) ? data.lines : [];
  if (!lines.length) {
    linesList.innerHTML = `<div class="muted">${state.periodMode === "month" ? "За выбранный месяц начислений пока нет. Нажми «Рассчитать», если профили уже назначены." : "За выбранный диапазон начислений пока нет."}</div>`;
    return;
  }

  linesList.innerHTML = "";
  lines.forEach((line) => {
    const breakdown = line.breakdown || {};
    const metrics = breakdown.metrics || {};
    const components = Array.isArray(breakdown.components) ? breakdown.components : [];
    const row = document.createElement("div");
    row.className = "expense-row";
    const periodState = String(line.period_state || breakdown.period_state || "").toLowerCase();
    const stateBadge = periodState === "partial"
      ? '<span class="badge">частично</span>'
      : (periodState === "ready" ? '' : '');
    row.innerHTML = `
      <div>
        <div style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">
          <b class="expense-row__title">${esc(memberName(line.member))}</b>
          ${line.pay_profile_title ? `<span class="badge">${esc(line.pay_profile_title)}</span>` : ""}
          ${stateBadge}
        </div>
        <div class="mono mt-6">Часы: ${esc(metrics.hours_total ?? 0)} · Смены: ${esc(metrics.shifts_count ?? 0)}${Number(metrics.worked_dates_count || 0) ? ` · Дней: ${esc(metrics.worked_dates_count)}` : ""}</div>
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
                </div>
              </div>
            `).join("") : `<div class="muted">Нет breakdown</div>`}
          </div>
        </details>
      </div>
      <div class="expense-row__side">
        <div class="expense-row__amount">${esc(fmtMoneyMinor(line.amount_minor))}</div>
      </div>
    `;
    linesList.appendChild(row);
  });
}

function buildPayrollPath() {
  if (state.periodMode === "range") {
    return `/venues/${encodeURIComponent(state.venueId)}/payroll?date_from=${encodeURIComponent(state.dateFrom)}&date_to=${encodeURIComponent(state.dateTo)}`;
  }
  return `/venues/${encodeURIComponent(state.venueId)}/payroll?month=${encodeURIComponent(state.month)}`;
}

async function load() {
  const linesList = document.getElementById("linesList");
  if (linesList) linesList.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
  try {
    state.data = await api(buildPayrollPath());
    renderLines();
  } catch (e) {
    const detail = e?.data?.detail || e?.message || "не удалось загрузить";
    if (linesList) linesList.innerHTML = `<div class="muted">Ошибка: ${esc(detail)}</div>`;
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
    toast("Выбери даты диапазона", "err");
    return;
  }
  state.dateFrom = nextFrom <= nextTo ? nextFrom : nextTo;
  state.dateTo = nextTo >= nextFrom ? nextTo : nextFrom;
  renderState();
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
  state.month = params.get("month") || currentMonth();
  const hasRange = /^\d{4}-\d{2}-\d{2}$/.test(String(params.get("date_from") || "")) && /^\d{4}-\d{2}-\d{2}$/.test(String(params.get("date_to") || ""));
  state.periodMode = (params.get("period_mode") || (hasRange ? "range" : "month")).toLowerCase() === "range" ? "range" : "month";
  state.dateFrom = hasRange ? String(params.get("date_from")) : monthStartIso(state.month);
  state.dateTo = hasRange ? String(params.get("date_to")) : monthEndIso(state.month);
  if (state.dateTo < state.dateFrom) state.dateTo = state.dateFrom;

  await mountNav({ activeTab: "summary" });

  try {
    state.me = await getMe();
  } catch {
    state.me = null;
  }

  try {
    state.perms = await getMyVenuePermissions(state.venueId);
  } catch {
    state.perms = null;
  }

  state.can = computeCaps(state.perms, state.me);
  renderState();

  document.getElementById("periodMonthBtn")?.addEventListener("click", async () => {
    if (state.periodMode === "month") return;
    setPeriodMode("month");
    await load();
  });
  document.getElementById("periodRangeBtn")?.addEventListener("click", async () => {
    if (state.periodMode === "range") return;
    setPeriodMode("range");
    await load();
  });

  document.getElementById("monthPick")?.addEventListener("change", async (e) => {
    state.month = e.target.value || currentMonth();
    if (!state.dateFrom || !state.dateTo) {
      state.dateFrom = monthStartIso(state.month);
      state.dateTo = monthEndIso(state.month);
    }
    renderState();
    await load();
  });

  document.getElementById("rangeApply")?.addEventListener("click", applyRangeFromControls);
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

  await load();
}

document.addEventListener("DOMContentLoaded", boot);

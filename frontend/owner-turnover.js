// Canonical revenue page for owners. Legacy route: /owner-revenue.html -> redirect.
import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  api,
  API_BASE,
  getActiveVenueId,
  setActiveVenueId,
  getMyVenues,
  getStoredDemoUiState,
  isDemoUiMode,
  getDemoMonthLabel,
} from "/app.js?v=20260726-navmore1";
import { permSetFromResponse, roleUpper, hasPerm, isFinancialValuesHidden, FINANCIAL_VALUES_HIDDEN_LABEL } from "/permissions.js";
import {
  formatComparisonRange,
  normalizeIsoRange,
  resolveAutoComparison,
  resolveComparisonRange,
} from "/app/period-comparison.js?v=20260729-compare2";

let financialValuesHidden = false;


const DEMO_OWNER_REVENUE_INTRO_DISMISSED_KEY = "axelio.demo_intro.owner_revenue.dismissed";

function setupDemoRevenueIntro() {
  const intro = $("demoOwnerRevenueIntro");
  if (!intro) return;
  const demoState = getStoredDemoUiState();
  if (!isDemoUiMode(demoState)) { intro.classList.add("hidden"); return; }
  try {
    if (sessionStorage.getItem(DEMO_OWNER_REVENUE_INTRO_DISMISSED_KEY) === "1") {
      intro.classList.add("hidden");
      return;
    }
  } catch {}
  const textEl = $("demoOwnerRevenueIntroText");
  if (textEl) textEl.textContent = `Здесь удобно оценить структуру выручки за ${getDemoMonthLabel(demoState) || 'DEMO-месяц'}: сначала департаменты, затем оплаты и переход к финансовым движениям.`;
  const venueId = getActiveVenueId();
  $("demoOwnerRevenueGoSummary")?.addEventListener("click", () => { if (venueId) location.href = `/owner-summary.html?venue_id=${encodeURIComponent(String(venueId))}`; });
  $("demoOwnerRevenueGoLedger")?.addEventListener("click", () => { if (venueId) location.href = `/owner-finance-ledger.html?venue_id=${encodeURIComponent(String(venueId))}&month=${encodeURIComponent(state.month || currentMonth())}`; });
  $("demoOwnerRevenueGoEconomics")?.addEventListener("click", () => { if (venueId) location.href = `/owner-day-economics.html?venue_id=${encodeURIComponent(String(venueId))}`; });
  $("demoOwnerRevenueIntroClose")?.addEventListener("click", () => {
    intro.classList.add("hidden");
    try { sessionStorage.setItem(DEMO_OWNER_REVENUE_INTRO_DISMISSED_KEY, "1"); } catch {}
  });
  intro.classList.remove("hidden");
}

let state = {
  period: "month",
  mode: "DEPARTMENTS",
  month: null,
  day: null,
  from: null,
  to: null,
  canView: true,
  canExport: true,
  compareMode: "auto",
  compareFrom: null,
  compareTo: null,
};

function $(id) { return document.getElementById(id); }

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function setVisible(element, visible) {
  element?.classList.toggle("hidden", !visible);
}

function fmtMoney(n) {
  if (financialValuesHidden) return FINANCIAL_VALUES_HIDDEN_LABEL;
  const x = Math.round(Number(n || 0));
  try { return new Intl.NumberFormat("ru-RU").format(x) + " ₽"; } catch { return String(x) + " ₽"; }
}

function fmtSignedMoney(value) {
  const amount = Number(value || 0);
  const sign = amount > 0 ? "+" : amount < 0 ? "−" : "";
  return `${sign}${fmtMoney(Math.abs(amount))}`;
}

function relativeDelta(currentValue, previousValue, { goodWhen = "up" } = {}) {
  const current = Number(currentValue || 0);
  const previous = Number(previousValue || 0);
  const delta = current - previous;
  const good = (goodWhen === "up" && delta > 0) || (goodWhen === "down" && delta < 0);
  const bad = (goodWhen === "up" && delta < 0) || (goodWhen === "down" && delta > 0);
  const tone = good ? "is-good" : bad ? "is-bad" : "is-neutral";
  if (previous === 0) {
    return {
      text: current === 0 ? "Без изменений" : `Нет базы · ${fmtSignedMoney(delta)}`,
      tone,
    };
  }
  const percent = delta / Math.abs(previous) * 100;
  const sign = percent > 0 ? "+" : percent < 0 ? "−" : "";
  return {
    text: `${sign}${Math.abs(percent).toLocaleString("ru-RU", { maximumFractionDigits: 1 })}% · ${fmtSignedMoney(delta)}`,
    tone,
  };
}

function startOfWeekISO(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const day = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - day);
  return d.toISOString().slice(0, 10);
}

function addDaysISO(dateStr, days) {
  const d = new Date(dateStr + "T00:00:00");
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function currentMonth() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function todayISO() {
  return new Date().toISOString().slice(0, 10);
}

function normalizeRange() {
  if (!state.from) state.from = todayISO();
  if (!state.to) state.to = state.from;
  if (state.from > state.to) {
    const x = state.from;
    state.from = state.to;
    state.to = x;
  }
}

function syncPickers() {
  const monthPick = $("monthPick");
  const dayPick = $("dayPick");
  const rangePick = $("rangePick");

  setVisible(monthPick, state.period === "month");
  setVisible(dayPick, state.period === "day" || state.period === "week");
  setVisible(rangePick, state.period === "range");
}

function currentComparison() {
  return resolveComparisonRange({
    compareMode: state.compareMode,
    compareFrom: state.compareFrom,
    compareTo: state.compareTo,
    period: state.period,
    month: state.month,
    day: state.day,
    from: state.from,
    to: state.to,
  });
}

function syncComparisonControls() {
  const comparison = currentComparison();
  const custom = state.compareMode === "custom";
  setVisible($("revenueCompareRange"), custom);
  setActiveSeg("revenueCompareSeg", "compare", state.compareMode);
  $("revenueComparePeriodText").textContent = formatComparisonRange(comparison);
  $("revenueCompareHint").textContent = comparison?.caption || "Выбери период сравнения";
  if (custom) {
    $("revenueCompareFrom").value = comparison?.from || state.compareFrom || "";
    $("revenueCompareTo").value = comparison?.to || state.compareTo || "";
  }
}

function periodLabel() {
  if (state.period === "month") return `За ${state.month || currentMonth()}`;
  if (state.period === "day") return `За ${state.day || todayISO()}`;
  if (state.period === "week") {
    const start = startOfWeekISO(state.day || todayISO());
    return `Неделя ${start} — ${addDaysISO(start, 6)}`;
  }
  normalizeRange();
  return `Период ${state.from} — ${state.to}`;
}

function syncCaption() {
  const el = $("periodCaption");
  if (el) el.textContent = periodLabel();
}

function buildQuery() {
  const qp = new URLSearchParams();
  qp.set("mode", state.mode);
  qp.set("period", state.period);

  if (state.period === "month") {
    qp.set("month", state.month || currentMonth());
  } else if (state.period === "day") {
    qp.set("day", state.day || todayISO());
    qp.set("date_from", state.day || todayISO());
    qp.set("date_to", state.day || todayISO());
  } else if (state.period === "week") {
    const baseDay = state.day || todayISO();
    const monday = startOfWeekISO(baseDay);
    qp.set("day", baseDay);
    qp.set("date_from", monday);
    qp.set("date_to", addDaysISO(monday, 6));
  } else {
    normalizeRange();
    qp.set("date_from", state.from || todayISO());
    qp.set("date_to", state.to || todayISO());
  }

  return qp;
}

function buildComparisonQuery() {
  const comparison = currentComparison();
  const qp = new URLSearchParams();
  qp.set("mode", state.mode);
  qp.set("period", "range");
  qp.set("date_from", comparison?.from || todayISO());
  qp.set("date_to", comparison?.to || comparison?.from || todayISO());
  return qp;
}

function syncUrl() {
  const qp = buildQuery();
  qp.set("compare_mode", state.compareMode);
  if (state.compareMode === "custom") {
    const comparison = currentComparison();
    if (comparison?.from) qp.set("compare_from", comparison.from);
    if (comparison?.to) qp.set("compare_to", comparison.to);
  }
  const venueId = getActiveVenueId();
  if (venueId) qp.set("venue_id", venueId);
  const target = `${location.pathname}?${qp.toString()}`;
  history.replaceState(null, "", target);
}

async function load() {
  const venueId = getActiveVenueId();
  if (!venueId || !state.canView) return;

  normalizeRange();
  syncCaption();
  syncComparisonControls();
  syncUrl();

  const primaryPromise = api(`/venues/${encodeURIComponent(venueId)}/revenue?${buildQuery().toString()}`);
  const comparisonPromise = api(`/venues/${encodeURIComponent(venueId)}/revenue?${buildComparisonQuery().toString()}`)
    .then((value) => ({ value }))
    .catch((error) => ({ error }));
  const [data, comparisonResult] = await Promise.all([primaryPromise, comparisonPromise]);
  const comparisonData = comparisonResult.value || null;

  $("total").textContent = fmtMoney(data?.total || 0);
  const totalDelta = $("revenueTotalDelta");
  totalDelta.classList.remove("is-good", "is-bad", "is-neutral");
  if (comparisonData && !financialValuesHidden) {
    const view = relativeDelta(data?.total, comparisonData?.total, { goodWhen: "up" });
    totalDelta.textContent = `${view.text} ${currentComparison()?.caption || ""}`.trim();
    totalDelta.classList.add(view.tone);
  } else {
    totalDelta.textContent = comparisonResult.error ? "Сравнение недоступно" : "—";
    totalDelta.classList.add("is-neutral");
  }

  const rowsEl = $("rows");
  rowsEl.innerHTML = "";

  const rows = Array.isArray(data?.rows) ? data.rows : [];
  if (!rows.length) {
    const empty = document.createElement("div");
    empty.className = "muted finance-table-empty";
    empty.textContent = "Нет данных за выбранный период";
    rowsEl.appendChild(empty);
    return;
  }

  const comparisonRows = new Map(
    (Array.isArray(comparisonData?.rows) ? comparisonData.rows : []).map((row) => [
      String(row?.ref_id ?? row?.id ?? row?.code ?? row?.title ?? row?.name ?? ""),
      row,
    ]),
  );
  for (const r of rows) {
    const el = document.createElement("div");
    el.className = "row row--between finance-table-row";
    const title = r?.title || r?.name || r?.code || "—";
    const rowKey = String(r?.ref_id ?? r?.id ?? r?.code ?? r?.title ?? r?.name ?? "");
    const comparisonRow = comparisonRows.get(rowKey);
    const rowDelta = comparisonRow && !financialValuesHidden
      ? relativeDelta(r?.amount, comparisonRow?.amount, { goodWhen: "up" })
      : null;
    el.innerHTML = `
      <div>${esc(title)}</div>
      <div>
        <div class="mono">${esc(fmtMoney(r?.amount || 0))}</div>
        ${rowDelta ? `<div class="finance-row-delta ${rowDelta.tone}">${esc(rowDelta.text)}</div>` : ""}
      </div>`;
    rowsEl.appendChild(el);
  }
}

function setActiveSeg(containerId, dataKey, value) {
  document.querySelectorAll(`#${containerId} button`).forEach((b) => {
    if (b.dataset[dataKey] === value) b.classList.add("active");
    else b.classList.remove("active");
  });
}

function applySeg(containerId, key) {
  document.querySelectorAll(`#${containerId} button`).forEach((btn) => {
    btn.onclick = () => {
      const val = btn.dataset[key];
      if (!val) return;
      state[key] = val;
      setActiveSeg(containerId, key, val);
      syncPickers();
      load().catch((e) => toast("Ошибка: " + (e?.message || e), "err"));
    };
  });
}

function initFromQuery() {
  const q = new URLSearchParams(location.search);
  const nowMonth = currentMonth();
  const today = todayISO();

  state.mode = q.get("mode") || "DEPARTMENTS";
  state.period = q.get("period") || (q.get("month") ? "month" : (q.get("date_from") && q.get("date_to") ? "range" : "month"));

  state.month = (q.get("month") || nowMonth).slice(0,7);
  state.day = q.get("day") || q.get("date_from") || today;
  state.from = q.get("date_from") || today;
  state.to = q.get("date_to") || today;
  state.compareMode = q.get("compare_mode") === "custom" ? "custom" : "auto";
  state.compareFrom = q.get("compare_from") || null;
  state.compareTo = q.get("compare_to") || null;
  normalizeRange();

  $("monthPick").value = state.month || currentMonth();
  $("dayPick").value = state.day;
  $("fromPick").value = state.from;
  $("toPick").value = state.to;

  setActiveSeg("modeSeg", "mode", state.mode);
  setActiveSeg("periodSeg", "period", state.period);
  syncCaption();
  syncComparisonControls();
}

function bindPickers() {
  $("monthPick").onchange = (e) => { state.month = e.target.value || currentMonth(); load().catch(console.error); };
  $("dayPick").onchange = (e) => { state.day = e.target.value || todayISO(); load().catch(console.error); };
  $("fromPick").onchange = (e) => { state.from = e.target.value || todayISO(); load().catch(console.error); };
  $("toPick").onchange = (e) => { state.to = e.target.value || todayISO(); load().catch(console.error); };

  document.querySelectorAll("#revenueCompareSeg button").forEach((button) => {
    button.onclick = () => {
      const mode = button.dataset.compare === "custom" ? "custom" : "auto";
      if (mode === "custom" && state.compareMode !== "custom") {
        const automatic = resolveAutoComparison(state);
        state.compareFrom = automatic?.from || state.day || todayISO();
        state.compareTo = automatic?.to || state.compareFrom;
      }
      state.compareMode = mode;
      syncComparisonControls();
      if (mode === "auto") load().catch(console.error);
      else syncUrl();
    };
  });
  $("revenueCompareFrom").onchange = (event) => { state.compareFrom = event.target.value || state.compareFrom; };
  $("revenueCompareTo").onchange = (event) => { state.compareTo = event.target.value || state.compareTo; };
  $("revenueCompareApply").onclick = () => {
    const normalized = normalizeIsoRange(state.compareFrom, state.compareTo);
    if (!normalized) {
      toast("Выбери даты сравнения", "err");
      return;
    }
    state.compareFrom = normalized.from;
    state.compareTo = normalized.to;
    load().catch(console.error);
  };

  $("exportBtn").onclick = async () => {
    const venueId = getActiveVenueId();
    if (!venueId || !state.canExport) return;

    const qs = buildQuery().toString();
    try {
      const data = await api(`/venues/${encodeURIComponent(venueId)}/revenue/export-link?${qs}&fmt=xlsx`);
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
    } catch (e) {
      console.error(e);
      toast("Не удалось начать экспорт");
    }
  };
}

async function resolveRevenueAccess() {
  const venueId = getActiveVenueId();
  if (!venueId) return;

  try {
    const permsResp = await api(`/me/venues/${encodeURIComponent(venueId)}/permissions`);
    financialValuesHidden = isFinancialValuesHidden(permsResp);
    const role = roleUpper(permsResp);
    const pset = permSetFromResponse(permsResp);
    const isPrivileged = role === "OWNER" || role === "VENUE_OWNER" || role === "SUPER_ADMIN" || role === "MODERATOR";

    state.canView = isPrivileged || hasPerm(pset, "REVENUE_VIEW");
    state.canExport = isPrivileged || hasPerm(pset, "REVENUE_EXPORT");
  } catch {
    state.canView = true;
    state.canExport = true;
  }

  const exportBtn = $("exportBtn");
  setVisible(exportBtn, state.canExport);

  if (!state.canView) {
    toast("Нет доступа к выручке", "err");
    const venue = getActiveVenueId();
    const qp = venue ? `?venue_id=${encodeURIComponent(venue)}` : "";
    setTimeout(() => { location.replace(`/owner-summary.html${qp}`); }, 150);
  }
}

async function boot() {
  applyTelegramTheme();
  mountCommonUI("summary");
  await ensureLogin({ silent: true });

  const params = new URLSearchParams(location.search);
  const venueId = params.get("venue_id") || getActiveVenueId();
  if (venueId) setActiveVenueId(venueId);

  await mountNav({ activeTab: "summary" });

  try {
    const venues = await getMyVenues();
    const v = venues.find(x => String(x.id) === String(getActiveVenueId()));
    if (v) $("subtitle").textContent = v.name || "";
  } catch {}

  initFromQuery();
  syncPickers();
  syncComparisonControls();
  applySeg("modeSeg", "mode");
  applySeg("periodSeg", "period");
  bindPickers();
  await resolveRevenueAccess();
  if (!state.canView) return;
  setupDemoRevenueIntro();
  await load();
}

document.addEventListener("DOMContentLoaded", () => {
  boot().catch((e) => toast("Ошибка: " + (e?.message || e), "err"));
});

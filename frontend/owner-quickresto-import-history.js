import {
  api,
  applyTelegramTheme,
  ensureLogin,
  getVenueById,
  mountCommonUI,
  mountNav,
  setActiveVenueId,
  toast,
} from "/app.js?v=20260820-i18nmetrika1";

applyTelegramTheme();
mountCommonUI("venue");
await ensureLogin({ silent: true });
await mountNav({ activeTab: "venue", requireVenue: true });

const params = new URLSearchParams(location.search);
const venueId = params.get("venue_id") || "";
if (venueId) setActiveVenueId(venueId);

const el = {
  venueTitle: document.getElementById("venueTitle"),
  backToQuickResto: document.getElementById("backToQuickResto"),
  refreshHistory: document.getElementById("refreshHistory"),
  activeBatchSection: document.getElementById("activeBatchSection"),
  activeBatchLabel: document.getElementById("activeBatchLabel"),
  activeBatchStatus: document.getElementById("activeBatchStatus"),
  activeBatchProgress: document.getElementById("activeBatchProgress"),
  activeBatchMeta: document.getElementById("activeBatchMeta"),
  statusFilter: document.getElementById("statusFilter"),
  historyList: document.getElementById("historyList"),
  historyHint: document.getElementById("historyHint"),
};

const ACTIVE_STATUSES = new Set(["PENDING", "RUNNING"]);
const STATUS_LABELS = {
  PENDING: "В очереди",
  RUNNING: "Выполняется",
  SUCCEEDED: "Успешно",
  PARTIAL: "Нужна проверка",
  FAILED: "Ошибка",
};
const state = { batches: [], pollTimer: null, loading: false };

const esc = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

function errorMessage(error) {
  return String(error?.data?.detail || error?.message || "Не удалось выполнить действие");
}

function parseDate(value) {
  if (!value) return null;
  const parsed = new Date(`${String(value).slice(0, 10)}T12:00:00`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatDate(value) {
  const parsed = parseDate(value);
  return parsed ? new Intl.DateTimeFormat("ru-RU").format(parsed) : "—";
}

function formatMonth(value) {
  const parsed = parseDate(value);
  return parsed
    ? new Intl.DateTimeFormat("ru-RU", { month: "long", year: "numeric" }).format(parsed)
    : "период";
}

function inclusiveEnd(value) {
  const parsed = parseDate(value);
  if (!parsed) return "—";
  parsed.setDate(parsed.getDate() - 1);
  return new Intl.DateTimeFormat("ru-RU").format(parsed);
}

function progressPercent(batch) {
  const total = Math.max(Number(batch?.total_periods || 0), 1);
  return Math.min(100, Math.max(0, Math.round((Number(batch?.completed_periods || 0) / total) * 100)));
}

function totals(batch) {
  const value = batch?.summary?.totals;
  return value && typeof value === "object" ? value : {};
}

function issueIds(batch) {
  const values = batch?.issue_ids || batch?.summary?.issue_ids || [];
  return [...new Set(values.map(Number).filter((value) => Number.isInteger(value) && value > 0))];
}

function statusBadge(status) {
  const normalized = String(status || "").toUpperCase();
  return `<span class="quickresto-status quickresto-status--${esc(normalized.toLowerCase())}">${esc(STATUS_LABELS[normalized] || normalized || "—")}</span>`;
}

function periodRows(batch) {
  const periods = Array.isArray(batch?.summary?.periods) ? batch.summary.periods : [];
  if (!periods.length) {
    return '<div class="quickresto-history-period quickresto-history-period--empty">Месяцы ещё не обработаны.</div>';
  }
  return periods
    .map((period) => {
      const counts = [
        `смен: ${Number(period.shifts_imported || 0)}`,
        `создано: ${Number(period.reports_created || 0)}`,
        `обновлено: ${Number(period.reports_updated || 0)}`,
      ].join(" · ");
      return `
        <div class="quickresto-history-period">
          <div>
            <b>${esc(formatMonth(period.period_start))}</b>
            <div class="muted small">${esc(formatDate(period.period_start))} — ${esc(inclusiveEnd(period.period_end_exclusive))}</div>
          </div>
          <div class="quickresto-history-period__result">
            ${statusBadge(period.status)}
            <span class="muted small">${esc(counts)}</span>
          </div>
        </div>`;
    })
    .join("");
}

function batchCard(batch) {
  const normalized = String(batch.status || "").toUpperCase();
  const batchTotals = totals(batch);
  const issues = issueIds(batch);
  const canRetry = normalized === "FAILED";
  const completed = Number(batch.completed_periods || 0);
  const total = Number(batch.total_periods || 0);
  const actions = [
    issues.length
      ? `<button class="btn subtle inline" type="button" data-open-issue="${issues[0]}">Открыть проблему</button>`
      : "",
    canRetry
      ? `<button class="btn inline" type="button" data-retry-batch="${Number(batch.id)}">Повторить с упавшего месяца</button>`
      : "",
  ].join("");
  return `
    <article class="quickresto-history-card" data-batch-id="${Number(batch.id)}">
      <div class="quickresto-history-card__head">
        <div>
          <b>${esc(formatDate(batch.period_start))} — ${esc(inclusiveEnd(batch.period_end_exclusive))}</b>
          <div class="muted small">Запуск #${Number(batch.id)} · обработано ${completed} из ${total} месяцев</div>
        </div>
        ${statusBadge(normalized)}
      </div>
      <div class="quickresto-progress mt-12" aria-label="Обработано ${completed} из ${total} месяцев">
        <progress class="quickresto-progress__bar" max="100" value="${progressPercent(batch)}">${progressPercent(batch)}%</progress>
      </div>
      <div class="quickresto-history-stats mt-8">
        <span>Смен импортировано: <b>${Number(batchTotals.shifts_imported || 0)}</b></span>
        <span>Отчётов создано: <b>${Number(batchTotals.reports_created || 0)}</b></span>
        <span>Обновлено: <b>${Number(batchTotals.reports_updated || 0)}</b></span>
        <span>Проблем: <b>${Number(batchTotals.issue_count || issues.length || 0)}</b></span>
      </div>
      ${batch.error ? `<div class="quickresto-history-error mt-8">${esc(batch.error)}</div>` : ""}
      <div class="quickresto-history-periods mt-12">${periodRows(batch)}</div>
      ${actions ? `<div class="quickresto-history-card__actions mt-12">${actions}</div>` : ""}
    </article>`;
}

function renderActiveBatch() {
  const batch = state.batches.find((item) => ACTIVE_STATUSES.has(String(item.status || "").toUpperCase()));
  el.activeBatchSection.hidden = !batch;
  if (!batch) return;
  const completed = Number(batch.completed_periods || 0);
  const total = Number(batch.total_periods || 0);
  const current = batch.current_period_start || batch.next_period_start;
  el.activeBatchStatus.textContent = STATUS_LABELS[String(batch.status).toUpperCase()] || batch.status;
  el.activeBatchStatus.className = `quickresto-status quickresto-status--${String(batch.status).toLowerCase()}`;
  el.activeBatchLabel.textContent = current
    ? `Сейчас: ${formatMonth(current)} · месяц ${Math.min(completed + 1, total)} из ${total}`
    : `Обработано ${completed} из ${total} месяцев`;
  const activePercent = progressPercent(batch);
  el.activeBatchProgress.value = activePercent;
  el.activeBatchProgress.textContent = `${activePercent}%`;
  const batchTotals = totals(batch);
  el.activeBatchMeta.textContent = `Импортировано смен: ${Number(batchTotals.shifts_imported || 0)} · создано отчётов: ${Number(batchTotals.reports_created || 0)}`;
}

function renderHistory() {
  renderActiveBatch();
  if (!state.batches.length) {
    el.historyList.innerHTML = '<div class="quickresto-history-empty">Запусков с таким статусом пока нет.</div>';
    return;
  }
  el.historyList.innerHTML = state.batches.map(batchCard).join("");
}

function schedulePoll() {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
  if (!state.batches.some((batch) => ACTIVE_STATUSES.has(String(batch.status || "").toUpperCase()))) {
    state.pollTimer = null;
    return;
  }
  state.pollTimer = window.setTimeout(() => loadHistory({ quiet: true }), 5000);
}

async function loadHistory({ quiet = false } = {}) {
  if (state.loading) return;
  state.loading = true;
  if (!quiet) {
    el.refreshHistory.disabled = true;
    el.historyHint.textContent = "Обновляем историю…";
  }
  try {
    const status = String(el.statusFilter.value || "").toUpperCase();
    const query = new URLSearchParams({ limit: "100" });
    if (status) query.set("status", status);
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/import-batches?${query}`,
    );
    state.batches = result.batches || result.items || [];
    renderHistory();
    el.historyHint.textContent = state.batches.length
      ? `Показано запусков: ${state.batches.length}`
      : "История пока пуста.";
  } catch (error) {
    el.historyHint.textContent = errorMessage(error);
    if (!quiet) toast(errorMessage(error), "err");
  } finally {
    state.loading = false;
    el.refreshHistory.disabled = false;
    schedulePoll();
  }
}

el.backToQuickResto?.addEventListener("click", () => {
  location.href = `/owner-quickresto.html?venue_id=${encodeURIComponent(venueId)}`;
});
el.refreshHistory?.addEventListener("click", () => loadHistory());
el.statusFilter?.addEventListener("change", () => loadHistory());

el.historyList?.addEventListener("click", async (event) => {
  const issueButton = event.target.closest("[data-open-issue]");
  if (issueButton) {
    const issueId = issueButton.dataset.openIssue;
    location.href = `/owner-integration-issues.html?venue_id=${encodeURIComponent(venueId)}&provider=quickresto&issue_id=${encodeURIComponent(issueId)}`;
    return;
  }
  const retryButton = event.target.closest("[data-retry-batch]");
  if (!retryButton) return;
  retryButton.disabled = true;
  try {
    await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/import-batches/${encodeURIComponent(retryButton.dataset.retryBatch)}/retry`,
      { method: "POST" },
    );
    toast("Импорт продолжен с упавшего месяца", "ok");
    await loadHistory({ quiet: true });
  } catch (error) {
    toast(errorMessage(error), "err");
    retryButton.disabled = false;
  }
});

if (!venueId) {
  el.historyHint.textContent = "Не выбрано заведение Axelio.";
  el.historyList.innerHTML = '<div class="quickresto-history-empty">Откройте историю со страницы интеграции заведения.</div>';
} else {
  try {
    const venue = await getVenueById(venueId);
    el.venueTitle.textContent = venue?.name || `Заведение #${venueId}`;
  } catch {}
  await loadHistory();
}

window.addEventListener("pagehide", () => {
  if (state.pollTimer) window.clearTimeout(state.pollTimer);
});

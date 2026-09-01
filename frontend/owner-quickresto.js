import {
  api,
  applyTelegramTheme,
  ensureLogin,
  getDepartments,
  getPaymentMethods,
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

const el = Object.fromEntries(
  [
    "title",
    "venueTitle",
    "backToIntegrations",
    "connectionStatus",
    "syncStatus",
    "cloud",
    "apiLogin",
    "apiPassword",
    "syncFromDate",
    "cutoffHour",
    "isActive",
    "autoSync",
    "saveConnection",
    "discoverMappings",
    "runSync",
    "runFullSync",
    "connectionHint",
    "paymentMappings",
    "departmentMappings",
    "saveMappings",
    "mappingHint",
    "runHistory",
    "reportImportClosed",
    "reportImportDraft",
    "importModeHint",
    "nightShiftToggleRow",
    "nightShiftSplit",
    "nightShiftWindow",
    "nightShiftStartHour",
    "nightShiftWindowSummary",
    "connectionActions",
    "readOnlyHint",
    "issueSection",
    "issueOpenCount",
    "issueList",
    "issueHint",
    "issueDrawer",
    "issueDrawerTitle",
    "issueDrawerBody",
  ].map((id) => [id, document.getElementById(id)]),
);

const state = {
  configured: false,
  connection: null,
  mappings: { payments: [], departments: [] },
  paymentMethods: [],
  departments: [],
  runs: [],
  venueNightShiftsEnabled: false,
  canManage: true,
  issues: [],
  issueTotal: 0,
  issueOpenCount: 0,
  issueLoading: false,
  issueLoadingMore: false,
  issueLoadFailed: false,
  selectedIssue: null,
  selectedIssueId: null,
  drawerReturnFocus: null,
};

const ACTIVE_ISSUE_STATUSES = new Set(["OPEN", "RETRY_PENDING", "PROCESSING"]);

const esc = (value) =>
  String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");

function errorMessage(error) {
  return String(
    error?.data?.detail || error?.message || "Не удалось выполнить действие",
  );
}

function setBusy(button, busy, label = "Выполняется…") {
  if (!button) return;
  if (busy) {
    button.dataset.previousText = button.textContent;
    button.textContent = label;
  } else if (button.dataset.previousText) {
    button.textContent = button.dataset.previousText;
  }
  button.disabled = !!busy;
}

function options(items, selectedId, emptyLabel = "— не сопоставлено —") {
  return [
    `<option value="">${esc(emptyLabel)}</option>`,
    ...items.map(
      (item) =>
        `<option value="${item.id}"${String(item.id) === String(selectedId || "") ? " selected" : ""}>${esc(item.title)}</option>`,
    ),
  ].join("");
}

function currentLocale() {
  return document.documentElement.lang === "en" ? "en-US" : "ru-RU";
}

function formatBusinessDate(value) {
  const source = String(value || "").trim();
  if (!source) return "Дата не определена";
  const date = /^\d{4}-\d{2}-\d{2}$/.test(source)
    ? new Date(`${source}T00:00:00`)
    : new Date(source);
  if (Number.isNaN(date.getTime())) return source;
  return new Intl.DateTimeFormat(currentLocale(), {
    day: "2-digit",
    month: "long",
    year: "numeric",
  }).format(date);
}

function formatIssueDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat(currentLocale(), {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function issueStatusLabel(value) {
  const status = String(value || "").toUpperCase();
  if (status === "OPEN") return "Ожидает решения";
  if (status === "RETRY_PENDING") return "Повтор запланирован";
  if (status === "PROCESSING") return "Обрабатывается";
  if (status === "RESOLVED") return "Исправлено";
  if (status === "IGNORED") return "Игнорируется";
  return status || "—";
}

function issueShiftStatusLabel(value) {
  const status = String(value || "").toUpperCase();
  if (status === "FAILED") return "Ошибка";
  if (status === "BLOCKED") return "Ожидает решения";
  if (status === "READY") return "Готова к повтору";
  if (status === "RESOLVED") return "Исправлено";
  if (status === "IGNORED") return "Игнорируется";
  return status || "—";
}

function shiftSlotLabel(value) {
  const slot = String(value || "").toUpperCase();
  if (slot === "DAY") return "Дневная смена";
  if (slot === "NIGHT") return "Ночная смена";
  return value ? String(value) : "Слот не определён";
}

function safeIssueSummary(issue) {
  return String(
    issue?.user_summary ||
      "Импорт остановлен, чтобы данные отчёта не были сохранены неверно.",
  );
}

function issueShiftCount(issue) {
  const count = Number(issue?.shift_count ?? issue?.shifts?.length ?? 0);
  return Number.isFinite(count) ? Math.max(0, count) : 0;
}

function renderIssues() {
  el.issueOpenCount.textContent = String(state.issueOpenCount);
  el.issueSection.dataset.attention =
    state.issueOpenCount > 0 ? "true" : "false";
  el.issueHint.textContent = "";

  if (state.issueLoading) {
    el.issueList.innerHTML = `<div class="quickresto-empty">Загружаем очередь ошибок…</div>`;
    return;
  }
  if (state.issueLoadFailed) {
    el.issueList.innerHTML = `<div class="quickresto-empty quickresto-empty--error">Не удалось загрузить очередь ошибок. Обновите страницу и повторите попытку.</div>`;
    return;
  }
  if (!state.issues.length) {
    el.issueList.innerHTML = `<div class="quickresto-empty quickresto-empty--ok">Ошибок импорта, требующих внимания, нет.</div>`;
    return;
  }

  const rows = state.issues
    .map((issue) => {
      const status = String(issue.status || "OPEN").toUpperCase();
      const shifts = issueShiftCount(issue);
      return `<button class="itemcard quickresto-issue-row" type="button" data-issue-id="${esc(issue.id)}">
      <span class="quickresto-issue-row__main">
        <span class="quickresto-issue-row__head">
          <span class="quickresto-issue-status" data-status="${esc(status)}">${esc(issueStatusLabel(status))}</span>
          <span class="quickresto-issue-row__date">${esc(formatBusinessDate(issue.business_date))} · ${esc(shiftSlotLabel(issue.shift_slot))}</span>
        </span>
        <span class="quickresto-issue-row__summary">${esc(safeIssueSummary(issue))}</span>
        <span class="quickresto-issue-row__meta">
          <span>Смен: ${shifts}</span>
          <span>Попыток: ${Number(issue.attempt_count || 0)}</span>
          <span>Последняя ошибка: ${esc(formatIssueDateTime(issue.last_failed_at))}</span>
        </span>
      </span>
      <span class="quickresto-issue-row__arrow" aria-hidden="true">›</span>
    </button>`;
    })
    .join("");
  const hasMore = state.issues.length < state.issueTotal;
  const moreLabel = state.issueLoadingMore
    ? "Загружаем…"
    : `Показать ещё · ${state.issues.length} из ${state.issueTotal}`;
  const moreDisabled = state.issueLoadingMore ? " disabled" : "";
  const more = hasMore
    ? `<button class="btn ghost quickresto-issues-more" type="button" data-issues-load-more${moreDisabled}>${moreLabel}</button>`
    : "";
  el.issueList.innerHTML = `${rows}${more}`;
}

function applyPermissions() {
  const editableFields = [
    el.cloud,
    el.apiLogin,
    el.apiPassword,
    el.syncFromDate,
    el.cutoffHour,
    el.isActive,
    el.autoSync,
    el.reportImportClosed,
    el.reportImportDraft,
    el.nightShiftSplit,
    el.nightShiftStartHour,
  ];
  editableFields.forEach((field) => {
    if (field) field.disabled = !state.canManage;
  });
  el.connectionActions.hidden = !state.canManage;
  el.saveMappings.hidden = !state.canManage;
  el.readOnlyHint.hidden = state.canManage;
  el.paymentMappings.querySelectorAll("select").forEach((select) => {
    select.disabled = !state.canManage;
  });
  el.departmentMappings.querySelectorAll("select").forEach((select) => {
    select.disabled = !state.canManage;
  });
}

function renderConnection() {
  const connection = state.connection || {};
  el.cloud.value = connection.cloud || "";
  el.syncFromDate.value = connection.sync_from_date || "";
  el.cutoffHour.value = String(connection.business_day_cutoff_hour ?? 0);
  el.isActive.checked = connection.is_active !== false;
  el.autoSync.checked = !!connection.auto_sync_enabled;
  el.nightShiftSplit.checked =
    state.venueNightShiftsEnabled && !!connection.night_shift_split_enabled;
  el.nightShiftStartHour.value = String(
    connection.night_shift_start_hour ?? 22,
  );
  const importMode = String(
    connection.report_import_mode || "CLOSED",
  ).toUpperCase();
  el.reportImportClosed.checked = importMode === "CLOSED";
  el.reportImportDraft.checked = importMode === "DRAFT";
  renderImportModeHint();
  renderNightShiftSettings();
  el.connectionStatus.textContent = state.configured
    ? `Подключено к ${connection.cloud}.quickresto.ru · учетные данные сохранены зашифрованно`
    : "Укажи облако, API-логин и пароль QuickResto.";
  const status = String(connection.last_sync_status || "NEVER").toUpperCase();
  el.syncStatus.textContent = status;
  el.syncStatus.dataset.status = status;
  if (connection.last_sync_error)
    el.connectionHint.textContent = connection.last_sync_error;
  applyPermissions();
}

function selectedImportMode() {
  return el.reportImportDraft.checked ? "DRAFT" : "CLOSED";
}

function renderImportModeHint() {
  el.importModeHint.textContent =
    selectedImportMode() === "DRAFT"
      ? "Новые импортированные отчёты останутся в статусе «Черновик». Уже закрытые отчёты не переоткроются."
      : "Новые импортированные отчёты будут закрыты автоматически и запустят обычные финансовые расчёты.";
}

function hourLabel(hour) {
  return `${String(hour).padStart(2, "0")}:00`;
}

function previousMinuteLabel(hour) {
  return `${String((hour + 23) % 24).padStart(2, "0")}:59`;
}

function renderNightShiftSettings() {
  const available = !!state.venueNightShiftsEnabled;
  el.nightShiftToggleRow.hidden = !available;
  if (!available) el.nightShiftSplit.checked = false;
  const enabled = available && !!el.nightShiftSplit.checked;
  el.nightShiftWindow.hidden = !enabled;
  el.nightShiftStartHour.disabled = !enabled || !state.canManage;
  if (!enabled) return;

  const cutoff = Number(el.cutoffHour.value || 0);
  const nightStart = Number(el.nightShiftStartHour.value || 22);
  if (nightStart <= cutoff) {
    el.nightShiftWindowSummary.dataset.status = "error";
    el.nightShiftWindowSummary.textContent =
      "Начало ночной смены должно быть позже границы бизнес-дня.";
    return;
  }
  el.nightShiftWindowSummary.dataset.status = "ok";
  el.nightShiftWindowSummary.textContent = [
    `DAY ${hourLabel(cutoff)}–${previousMinuteLabel(nightStart)}`,
    `NIGHT ${hourLabel(nightStart)}–${previousMinuteLabel(cutoff)}`,
  ].join(" · ");
}

function renderMappings() {
  const payments = state.mappings.payments || [];
  const departments = state.mappings.departments || [];
  el.paymentMappings.innerHTML = payments.length
    ? payments
        .map((item) => {
          const writeoff =
            String(item.operation_type || "").toLowerCase() === "writeoff";
          return `<div class="itemcard quickresto-mapping-row">
      <div><b>${esc(item.external_name)}</b><div class="muted small">QuickResto #${item.external_id} · ${esc(item.operation_type || "—")}</div></div>
      ${
        writeoff
          ? `<div class="quickresto-excluded">Исключено из выручки</div>`
          : `<select data-payment-external-id="${item.external_id}"${state.canManage ? "" : " disabled"}>${options(state.paymentMethods, item.payment_method_id)}</select>`
      }
    </div>`;
        })
        .join("")
    : `<div class="quickresto-empty">Сначала получи справочники QuickResto.</div>`;

  el.departmentMappings.innerHTML = departments.length
    ? departments
        .map(
          (item) => `
    <div class="itemcard quickresto-mapping-row">
      <div><b>${esc(item.external_name)}</b><div class="muted small">QuickResto #${item.external_id}</div></div>
      <select data-department-external-id="${item.external_id}"${state.canManage ? "" : " disabled"}>${options(state.departments, item.department_id)}</select>
    </div>
  `,
        )
        .join("")
    : `<div class="quickresto-empty">Сначала получи справочники QuickResto.</div>`;
  applyPermissions();
}

function renderRuns() {
  el.runHistory.innerHTML = state.runs.length
    ? state.runs
        .map((run) => {
          const summary = run.summary || {};
          const time = run.started_at
            ? new Date(run.started_at).toLocaleString()
            : "—";
          return `<div class="itemcard quickresto-run-row">
      <div><b>${esc(run.status)}</b><div class="muted small">${esc(time)} · ${esc(run.trigger)}</div></div>
      <div class="quickresto-run-metrics">
        <span>Смен: ${Number(summary.shifts_seen || 0)}</span>
        <span>Создано: ${Number(summary.reports_created || 0)}</span>
        <span>Обновлено: ${Number(summary.reports_updated || 0)}</span>
      </div>
      ${run.error ? `<div class="quickresto-run-error">${esc(run.error)}</div>` : ""}
    </div>`;
        })
        .join("")
    : `<div class="quickresto-empty">Синхронизация еще не запускалась.</div>`;
}

function mappingSelect(container, datasetKey, externalId) {
  return (
    Array.from(container.querySelectorAll("select")).find(
      (select) =>
        String(select.dataset[datasetKey] || "") === String(externalId),
    ) || null
  );
}

function payloadExternalId(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : value;
}

function collectMappingsPayload({
  paymentOverrides = new Map(),
  departmentOverrides = new Map(),
} = {}) {
  const existingPaymentIds = new Set();
  const payments = (state.mappings.payments || []).map((item) => {
    const key = String(item.external_id);
    existingPaymentIds.add(key);
    const writeoff =
      String(item.operation_type || "").toLowerCase() === "writeoff";
    const mainSelect = mappingSelect(
      el.paymentMappings,
      "paymentExternalId",
      item.external_id,
    );
    const selected = paymentOverrides.has(key)
      ? paymentOverrides.get(key)
      : mainSelect?.value;
    return {
      external_id: item.external_id,
      payment_method_id: writeoff || !selected ? null : Number(selected),
      excluded_from_revenue: writeoff,
    };
  });
  for (const [externalId, selected] of paymentOverrides) {
    if (existingPaymentIds.has(String(externalId))) continue;
    payments.push({
      external_id: payloadExternalId(externalId),
      payment_method_id: selected ? Number(selected) : null,
      excluded_from_revenue: false,
    });
  }

  const existingDepartmentIds = new Set();
  const departments = (state.mappings.departments || []).map((item) => {
    const key = String(item.external_id);
    existingDepartmentIds.add(key);
    const mainSelect = mappingSelect(
      el.departmentMappings,
      "departmentExternalId",
      item.external_id,
    );
    const selected = departmentOverrides.has(key)
      ? departmentOverrides.get(key)
      : mainSelect?.value;
    return {
      external_id: item.external_id,
      department_id: selected ? Number(selected) : null,
    };
  });
  for (const [externalId, selected] of departmentOverrides) {
    if (existingDepartmentIds.has(String(externalId))) continue;
    departments.push({
      external_id: payloadExternalId(externalId),
      department_id: selected ? Number(selected) : null,
    });
  }
  return { payments, departments };
}

async function persistMappings(overrides = {}) {
  const result = await api(
    `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/mappings`,
    {
      method: "PUT",
      body: collectMappingsPayload(overrides),
    },
  );
  state.mappings = result.mappings || state.mappings;
  renderMappings();
  return result;
}

function uniqueIds(values) {
  return [
    ...new Set(
      (Array.isArray(values) ? values : []).map((value) => String(value)),
    ),
  ];
}

function issueMissingMappings(issue) {
  return {
    paymentIds: uniqueIds(issue?.details?.missing_payment_type_ids),
    departmentIds: uniqueIds(issue?.details?.missing_department_ids),
  };
}

function paymentMappingByExternalId(externalId) {
  return (
    (state.mappings.payments || []).find(
      (item) => String(item.external_id) === String(externalId),
    ) || null
  );
}

function departmentMappingByExternalId(externalId) {
  return (
    (state.mappings.departments || []).find(
      (item) => String(item.external_id) === String(externalId),
    ) || null
  );
}

function selectedPaymentMapping(externalId, mapping) {
  const mainSelect = mappingSelect(
    el.paymentMappings,
    "paymentExternalId",
    externalId,
  );
  return mainSelect?.value || mapping?.payment_method_id || "";
}

function selectedDepartmentMapping(externalId, mapping) {
  const mainSelect = mappingSelect(
    el.departmentMappings,
    "departmentExternalId",
    externalId,
  );
  return mainSelect?.value || mapping?.department_id || "";
}

function renderIssueMappingFields(issue) {
  const { paymentIds, departmentIds } = issueMissingMappings(issue);
  if (!paymentIds.length && !departmentIds.length) return "";
  const disabled =
    state.canManage && issue.can_retry !== false ? "" : " disabled";

  const paymentFields = paymentIds
    .map((externalId) => {
      const mapping = paymentMappingByExternalId(externalId);
      const label =
        mapping?.external_name || `Способ оплаты QuickResto #${externalId}`;
      return `<label class="quickresto-issue-field">
      <span>${esc(label)}</span>
      <select data-issue-payment-external-id="${esc(externalId)}"${disabled}>${options(state.paymentMethods, selectedPaymentMapping(externalId, mapping))}</select>
    </label>`;
    })
    .join("");

  const departmentFields = departmentIds
    .map((externalId) => {
      const mapping = departmentMappingByExternalId(externalId);
      const label =
        mapping?.external_name || `Группа блюд QuickResto #${externalId}`;
      return `<label class="quickresto-issue-field">
      <span>${esc(label)}</span>
      <select data-issue-department-external-id="${esc(externalId)}"${disabled}>${options(state.departments, selectedDepartmentMapping(externalId, mapping))}</select>
    </label>`;
    })
    .join("");

  return `<section class="quickresto-issue-resolution-card" aria-labelledby="issueMappingsTitle">
    <div>
      <h3 id="issueMappingsTitle">Нужно сопоставить данные</h3>
      <div class="muted small mt-4">Выберите объекты Axelio для значений QuickResto. Сначала сопоставления будут сохранены, затем смены снова встанут в очередь импорта.</div>
    </div>
    <div class="quickresto-issue-fields">${paymentFields}${departmentFields}</div>
    ${
      state.canManage && issue.can_retry !== false
        ? `<button class="btn primary" type="button" data-issue-save-retry>Сохранить сопоставления и повторить</button>`
        : ""
    }
  </section>`;
}

function shiftTitle(shift, index) {
  const externalId = shift?.external_shift_id ?? shift?.external_shift_pk;
  return externalId === null || externalId === undefined || externalId === ""
    ? `Смена ${index + 1}`
    : `Смена QuickResto #${externalId}`;
}

function shiftPeriod(shift) {
  const opened = formatIssueDateTime(shift?.local_opened_at);
  const closed = formatIssueDateTime(shift?.local_closed_at);
  if (opened === "—" && closed === "—") return "Время смены не передано";
  return `${opened} — ${closed}`;
}

function renderIssueShifts(issue) {
  const shifts = Array.isArray(issue?.shifts) ? issue.shifts : [];
  if (!shifts.length)
    return `<div class="quickresto-empty">Сведения о сменах пока не загружены.</div>`;
  return `<div class="quickresto-issue-shifts">${shifts
    .map(
      (shift, index) => `
    <div class="itemcard quickresto-issue-shift">
      <div class="quickresto-issue-shift__head">
        <b>${esc(shiftTitle(shift, index))}</b>
        <span class="quickresto-issue-shift__status">${esc(issueShiftStatusLabel(shift.item_status))}</span>
      </div>
      <div class="muted small">${esc(shiftPeriod(shift))}</div>
      ${shift.user_summary ? `<div class="quickresto-issue-shift__summary">${esc(shift.user_summary)}</div>` : ""}
    </div>`,
    )
    .join("")}</div>`;
}

function renderIssueDrawer(issue) {
  if (!issue) return;
  state.selectedIssue = issue;
  el.issueDrawerTitle.textContent = `${formatBusinessDate(issue.business_date)} · ${shiftSlotLabel(issue.shift_slot)}`;
  const status = String(issue.status || "OPEN").toUpperCase();
  const { paymentIds, departmentIds } = issueMissingMappings(issue);
  const hasMissingMappings = paymentIds.length > 0 || departmentIds.length > 0;
  const canRetry =
    state.canManage &&
    issue.can_retry !== false &&
    ACTIVE_ISSUE_STATUSES.has(status);
  const canIgnore =
    state.canManage &&
    issue.can_ignore !== false &&
    ACTIVE_ISSUE_STATUSES.has(status);

  const retryAction =
    canRetry && !hasMissingMappings
      ? `<button class="btn primary" type="button" data-issue-retry>Повторить импорт</button>`
      : "";
  const ignoreAction = canIgnore
    ? `<section class="quickresto-issue-ignore">
        <label class="quickresto-issue-field" for="issueResolutionNote">
          <span>Почему ошибку можно проигнорировать</span>
          <textarea id="issueResolutionNote" rows="3" minlength="3" maxlength="1000" placeholder="Обязательная заметка для истории решения"></textarea>
        </label>
        <button class="btn danger" type="button" data-issue-ignore>Игнорировать ошибку</button>
      </section>`
    : "";
  const readOnlyNotice = !state.canManage
    ? `<div class="quickresto-readonly">Доступ только для просмотра. Решить ошибку может владелец или администратор заведения.</div>`
    : "";
  const processingNotice =
    state.canManage && status === "PROCESSING"
      ? `<div class="quickresto-issue-processing">Повторный импорт уже выполняется. Статус обновится после обработки смен.</div>`
      : "";

  el.issueDrawerBody.innerHTML = `
    <div class="quickresto-issue-detail-head">
      <span class="quickresto-issue-status" data-status="${esc(status)}">${esc(issueStatusLabel(status))}</span>
      <p>${esc(safeIssueSummary(issue))}</p>
    </div>
    <dl class="quickresto-issue-facts">
      <div><dt>Дата отчёта</dt><dd>${esc(formatBusinessDate(issue.business_date))}</dd></div>
      <div><dt>Слот</dt><dd>${esc(shiftSlotLabel(issue.shift_slot))}</dd></div>
      <div><dt>Смен</dt><dd>${issueShiftCount(issue)}</dd></div>
      <div><dt>Попыток</dt><dd>${Number(issue.attempt_count || 0)}</dd></div>
      <div><dt>Первая ошибка</dt><dd>${esc(formatIssueDateTime(issue.first_failed_at))}</dd></div>
      <div><dt>Последняя ошибка</dt><dd>${esc(formatIssueDateTime(issue.last_failed_at))}</dd></div>
    </dl>
    <section class="quickresto-issue-detail-section">
      <h3>Смены QuickResto</h3>
      ${renderIssueShifts(issue)}
    </section>
    ${renderIssueMappingFields(issue)}
    ${readOnlyNotice}
    ${processingNotice}
    ${retryAction || ignoreAction ? `<div class="quickresto-issue-actions">${retryAction}${ignoreAction}</div>` : ""}
    <div class="muted small quickresto-issue-action-hint" id="issueActionHint" aria-live="polite"></div>`;
}

function closeIssueDrawer() {
  if (!el.issueDrawer.classList.contains("open")) return;
  el.issueDrawer.classList.remove("open");
  el.issueDrawer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("quickresto-drawer-open");
  state.selectedIssue = null;
  state.selectedIssueId = null;
  const returnFocus = state.drawerReturnFocus;
  state.drawerReturnFocus = null;
  if (returnFocus instanceof HTMLElement && returnFocus.isConnected)
    returnFocus.focus();
}

function showIssueDrawer(issueId, summary = null) {
  state.drawerReturnFocus =
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
  state.selectedIssueId = String(issueId);
  state.selectedIssue = null;
  el.issueDrawerTitle.textContent = summary
    ? `${formatBusinessDate(summary.business_date)} · ${shiftSlotLabel(summary.shift_slot)}`
    : "Ошибка импорта QuickResto";
  el.issueDrawerBody.innerHTML = `<div class="quickresto-empty">Загружаем сведения об ошибке…</div>`;
  el.issueDrawer.classList.add("open");
  el.issueDrawer.setAttribute("aria-hidden", "false");
  document.body.classList.add("quickresto-drawer-open");
  el.issueDrawer.querySelector("[data-issue-close]")?.focus();
}

async function loadIssueDetail(issueId, { showLoading = false } = {}) {
  const selectedId = String(issueId);
  if (showLoading)
    el.issueDrawerBody.innerHTML = `<div class="quickresto-empty">Загружаем сведения об ошибке…</div>`;
  try {
    const issue = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${encodeURIComponent(issueId)}`,
    );
    if (
      state.selectedIssueId !== selectedId ||
      !el.issueDrawer.classList.contains("open")
    )
      return null;
    renderIssueDrawer(issue);
    return issue;
  } catch {
    if (state.selectedIssueId === selectedId) {
      el.issueDrawerBody.innerHTML = `<div class="quickresto-empty quickresto-empty--error">Не удалось загрузить сведения об ошибке. Закройте окно и повторите попытку.</div>`;
    }
    return null;
  }
}

async function openIssue(issueId) {
  const summary =
    state.issues.find((item) => String(item.id) === String(issueId)) || null;
  showIssueDrawer(issueId, summary);
  await loadIssueDetail(issueId);
}

async function loadIssues({ silent = false, append = false } = {}) {
  if (!state.configured) {
    state.issues = [];
    state.issueTotal = 0;
    state.issueOpenCount = 0;
    state.issueLoading = false;
    state.issueLoadingMore = false;
    state.issueLoadFailed = false;
    renderIssues();
    return;
  }
  if (append) {
    state.issueLoadingMore = true;
    renderIssues();
  } else if (!silent) {
    state.issueLoading = true;
    state.issueLoadFailed = false;
    renderIssues();
  }
  let loadMoreFailed = false;
  try {
    const offset = append ? state.issues.length : 0;
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues?status=active&limit=100&offset=${offset}`,
    );
    const items = Array.isArray(result?.items) ? result.items : [];
    const activeItems = items.filter((issue) =>
      ACTIVE_ISSUE_STATUSES.has(String(issue.status || "").toUpperCase()),
    );
    if (append) {
      const merged = new Map(
        state.issues.map((issue) => [String(issue.id), issue]),
      );
      activeItems.forEach((issue) => merged.set(String(issue.id), issue));
      state.issues = Array.from(merged.values());
    } else {
      state.issues = activeItems;
    }
    const total = Number(result?.total ?? state.issues.length);
    state.issueTotal = Number.isFinite(total)
      ? Math.max(total, state.issues.length)
      : state.issues.length;
    state.issueOpenCount = Number(
      result?.open_count ??
        state.issues.filter(
          (issue) => String(issue.status).toUpperCase() === "OPEN",
        ).length,
    );
    state.issueLoadFailed = false;
  } catch {
    if (append) {
      loadMoreFailed = true;
    } else {
      state.issueLoadFailed = true;
    }
  } finally {
    state.issueLoading = false;
    state.issueLoadingMore = false;
    renderIssues();
    if (loadMoreFailed) {
      el.issueHint.textContent =
        "Не удалось загрузить следующую страницу ошибок. Повторите попытку.";
    }
  }
}

function issueActionHint(message, error = false) {
  const hint = document.getElementById("issueActionHint");
  if (!hint) return;
  hint.textContent = message || "";
  hint.dataset.status = error ? "error" : "";
}

async function retrySelectedIssue(button) {
  const issue = state.selectedIssue;
  if (!state.canManage || !issue) return;
  setBusy(button, true, "Повторяем импорт…");
  issueActionHint("");
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${encodeURIComponent(issue.id)}/retry`,
      { method: "POST" },
    );
    const succeeded =
      result?.ok === true &&
      String(result?.run?.status || "").toUpperCase() === "SUCCEEDED";
    await loadIssues({ silent: true });
    await loadIssueDetail(issue.id);
    if (succeeded) {
      toast("Повторный импорт завершён", "ok");
    } else {
      const message = String(
        result?.issue?.user_summary ||
          result?.run?.error ||
          "Повторный импорт снова требует внимания.",
      );
      issueActionHint(message, true);
      toast("Повторный импорт снова требует внимания", "err");
    }
  } catch (error) {
    issueActionHint(errorMessage(error), true);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

async function saveIssueMappingsAndRetry(button) {
  const issue = state.selectedIssue;
  if (!state.canManage || !issue) return;
  const paymentOverrides = new Map();
  const departmentOverrides = new Map();
  let missingSelection = false;
  el.issueDrawerBody
    .querySelectorAll("[data-issue-payment-external-id]")
    .forEach((select) => {
      select.removeAttribute("aria-invalid");
      if (!select.value) {
        select.setAttribute("aria-invalid", "true");
        missingSelection = true;
      }
      paymentOverrides.set(
        String(select.dataset.issuePaymentExternalId),
        select.value,
      );
    });
  el.issueDrawerBody
    .querySelectorAll("[data-issue-department-external-id]")
    .forEach((select) => {
      select.removeAttribute("aria-invalid");
      if (!select.value) {
        select.setAttribute("aria-invalid", "true");
        missingSelection = true;
      }
      departmentOverrides.set(
        String(select.dataset.issueDepartmentExternalId),
        select.value,
      );
    });
  if (missingSelection) {
    issueActionHint(
      "Выберите сопоставление для каждого значения QuickResto.",
      true,
    );
    return;
  }

  setBusy(button, true, "Сохраняем и повторяем…");
  issueActionHint("");
  try {
    await persistMappings({ paymentOverrides, departmentOverrides });
    el.mappingHint.textContent = "Сопоставления сохранены.";
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${encodeURIComponent(issue.id)}/retry`,
      { method: "POST" },
    );
    const succeeded =
      result?.ok === true &&
      String(result?.run?.status || "").toUpperCase() === "SUCCEEDED";
    await loadIssues({ silent: true });
    await loadIssueDetail(issue.id);
    if (succeeded) {
      toast("Сопоставления сохранены, повторный импорт завершён", "ok");
    } else {
      const message = String(
        result?.issue?.user_summary ||
          result?.run?.error ||
          "Повторный импорт снова требует внимания.",
      );
      issueActionHint(message, true);
      toast("Сопоставления сохранены, но импорт требует внимания", "err");
    }
  } catch (error) {
    issueActionHint(errorMessage(error), true);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

async function ignoreSelectedIssue(button) {
  const issue = state.selectedIssue;
  if (!state.canManage || !issue) return;
  const note = String(
    document.getElementById("issueResolutionNote")?.value || "",
  ).trim();
  const noteField = document.getElementById("issueResolutionNote");
  noteField?.removeAttribute("aria-invalid");
  if (note.length < 3) {
    noteField?.setAttribute("aria-invalid", "true");
    noteField?.focus();
    issueActionHint(
      "Добавьте заметку минимум из 3 символов: почему ошибку можно проигнорировать.",
      true,
    );
    return;
  }

  setBusy(button, true, "Сохраняем решение…");
  issueActionHint("");
  try {
    await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${encodeURIComponent(issue.id)}/resolve`,
      {
        method: "POST",
        body: { action: "IGNORE", note },
      },
    );
    toast("Ошибка отмечена как проигнорированная", "ok");
    closeIssueDrawer();
    await loadIssues({ silent: true });
  } catch (error) {
    issueActionHint(errorMessage(error), true);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

async function load() {
  if (!venueId) {
    toast("Сначала выбери заведение", "err");
    return;
  }
  el.backToIntegrations.dataset.href = `/owner-integrations.html?venue_id=${encodeURIComponent(venueId)}`;
  const [venue, integration, paymentMethods, departments] = await Promise.all([
    getVenueById(venueId),
    api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto`),
    getPaymentMethods(venueId, { includeArchived: false }),
    getDepartments(venueId, { includeArchived: false }),
  ]);
  state.configured = !!integration.configured;
  state.connection = integration.connection;
  state.canManage =
    integration.permissions?.can_manage ?? integration.can_manage ?? true;
  state.issueOpenCount = Number(integration.issues?.open_count || 0);
  state.venueNightShiftsEnabled = !!(
    integration.venue_night_shifts_enabled ??
    integration.connection?.venue_night_shifts_enabled ??
    venue?.night_shifts_enabled
  );
  state.mappings = integration.mappings || { payments: [], departments: [] };
  state.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
  state.departments = Array.isArray(departments) ? departments : [];
  const venueName = venue?.name || `Заведение ${venueId}`;
  el.title.textContent = `QuickResto · ${venueName}`;
  el.venueTitle.textContent = venueName;
  state.runs = state.configured
    ? await api(
        `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/runs?limit=10`,
      )
    : [];
  renderConnection();
  renderMappings();
  renderRuns();
  await loadIssues();
  if (params.get("issues") === "1") {
    el.issueSection?.scrollIntoView({ block: "start", behavior: "smooth" });
    if (state.issues.length === 1 && !state.selectedIssueId) {
      await openIssue(state.issues[0].id);
    }
  }
}

el.saveConnection?.addEventListener("click", async () => {
  if (!state.canManage) return;
  setBusy(el.saveConnection, true, "Сохраняем…");
  el.connectionHint.textContent = "";
  try {
    const body = {
      cloud: String(el.cloud.value || "").trim(),
      api_login: String(el.apiLogin.value || "").trim() || null,
      api_password: String(el.apiPassword.value || "") || null,
      is_active: !!el.isActive.checked,
      auto_sync_enabled: !!el.autoSync.checked,
      report_import_mode: selectedImportMode(),
      business_day_cutoff_hour: Number(el.cutoffHour.value || 0),
      night_shift_split_enabled:
        state.venueNightShiftsEnabled && !!el.nightShiftSplit.checked,
      night_shift_start_hour: Number(el.nightShiftStartHour.value || 22),
      sync_from_date: el.syncFromDate.value || null,
    };
    if (
      body.night_shift_split_enabled &&
      body.night_shift_start_hour <= body.business_day_cutoff_hour
    ) {
      throw new Error(
        "Начало ночной смены должно быть позже границы бизнес-дня.",
      );
    }
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto`,
      {
        method: "PUT",
        body,
      },
    );
    state.configured = true;
    state.connection = result.connection;
    el.apiLogin.value = "";
    el.apiPassword.value = "";
    renderConnection();
    toast("Подключение сохранено", "ok");
  } catch (error) {
    el.connectionHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.saveConnection, false);
  }
});

el.discoverMappings?.addEventListener("click", async () => {
  if (!state.canManage) return;
  setBusy(el.discoverMappings, true, "Проверяем…");
  el.connectionHint.textContent = "";
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/discover`,
      { method: "POST" },
    );
    state.mappings = result.mappings;
    const [paymentMethods, departments] = await Promise.all([
      getPaymentMethods(venueId, { includeArchived: false }),
      getDepartments(venueId, { includeArchived: false }),
    ]);
    state.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
    state.departments = Array.isArray(departments) ? departments : [];
    renderMappings();
    await loadIssues({ silent: true });
    const summary = result.summary || {};
    el.connectionHint.textContent = `Получено способов оплаты: ${summary.payment_types_seen || 0}; групп блюд: ${summary.departments_seen || 0}. Создано в Axelio: способов оплаты ${summary.payment_methods_created || 0}, департаментов ${summary.departments_created || 0}.`;
    toast("Соединение работает, справочники загружены", "ok");
  } catch (error) {
    el.connectionHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.discoverMappings, false);
  }
});

el.saveMappings?.addEventListener("click", async () => {
  if (!state.canManage) return;
  setBusy(el.saveMappings, true, "Сохраняем…");
  el.mappingHint.textContent = "";
  try {
    await persistMappings();
    el.mappingHint.textContent = "Сопоставления сохранены.";
    toast("Сопоставления сохранены", "ok");
  } catch (error) {
    el.mappingHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.saveMappings, false);
  }
});

async function runImport({ full = false, button = el.runSync } = {}) {
  if (!state.canManage) return;
  setBusy(button, true, full ? "Сверяем всю историю…" : "Импортируем…");
  el.connectionHint.textContent = "";
  try {
    const suffix = full ? "?full=true" : "";
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/sync${suffix}`,
      { method: "POST" },
    );
    const run = result.run || {};
    el.connectionHint.textContent =
      run.status === "PARTIAL"
        ? "Импорт завершен частично: проверь сопоставления или существующие отчеты."
        : full
          ? "Полная история от выбранной даты сверена с QuickResto."
          : selectedImportMode() === "DRAFT"
            ? "Закрытые смены импортированы в черновики отчётов."
            : "Закрытые смены импортированы и отчёты автоматически закрыты.";
    toast(
      run.status === "PARTIAL"
        ? "Импорт требует внимания"
        : full
          ? "Полная сверка завершена"
          : "Импорт завершен",
      run.status === "PARTIAL" ? "err" : "ok",
    );
    await load();
  } catch (error) {
    el.connectionHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

el.runSync?.addEventListener("click", async () => {
  await runImport({ button: el.runSync });
});

el.runFullSync?.addEventListener("click", async () => {
  await runImport({ full: true, button: el.runFullSync });
});

el.reportImportClosed?.addEventListener("change", renderImportModeHint);
el.reportImportDraft?.addEventListener("change", renderImportModeHint);
el.nightShiftSplit?.addEventListener("change", renderNightShiftSettings);
el.nightShiftStartHour?.addEventListener("change", renderNightShiftSettings);
el.cutoffHour?.addEventListener("change", renderNightShiftSettings);

el.issueList?.addEventListener("click", (event) => {
  const eventTarget = event.target instanceof Element ? event.target : null;
  const loadMore = eventTarget?.closest("[data-issues-load-more]");
  if (loadMore) {
    void loadIssues({ silent: true, append: true });
    return;
  }
  const target = eventTarget?.closest("[data-issue-id]");
  if (!target) return;
  void openIssue(target.dataset.issueId);
});

el.issueDrawer?.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  if (target.closest("[data-issue-close]")) {
    closeIssueDrawer();
    return;
  }
  const retryButton = target.closest("[data-issue-retry]");
  if (retryButton) {
    void retrySelectedIssue(retryButton);
    return;
  }
  const saveRetryButton = target.closest("[data-issue-save-retry]");
  if (saveRetryButton) {
    void saveIssueMappingsAndRetry(saveRetryButton);
    return;
  }
  const ignoreButton = target.closest("[data-issue-ignore]");
  if (ignoreButton) void ignoreSelectedIssue(ignoreButton);
});

el.issueDrawer?.addEventListener("input", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (
    !target?.matches(
      "#issueResolutionNote, [data-issue-payment-external-id], [data-issue-department-external-id]",
    )
  )
    return;
  target.removeAttribute("aria-invalid");
  issueActionHint("");
});

document.addEventListener("keydown", (event) => {
  if (!el.issueDrawer.classList.contains("open")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeIssueDrawer();
    return;
  }
  if (event.key !== "Tab") return;
  const focusable = Array.from(
    el.issueDrawer.querySelectorAll(
      'button:not([disabled]), select:not([disabled]), textarea:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((node) => node instanceof HTMLElement && node.offsetParent !== null);
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (!el.issueDrawer.contains(document.activeElement)) {
    event.preventDefault();
    (event.shiftKey ? last : first).focus();
  } else if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});

for (let hour = 0; hour < 24; hour += 1) {
  const option = document.createElement("option");
  option.value = String(hour);
  option.textContent =
    hour === 0
      ? "00:00 — календарный день"
      : `${String(hour).padStart(2, "0")}:00`;
  el.cutoffHour.append(option);

  const nightOption = document.createElement("option");
  nightOption.value = String(hour);
  nightOption.textContent = `${String(hour).padStart(2, "0")}:00`;
  el.nightShiftStartHour.append(nightOption);
}

try {
  await load();
} catch (error) {
  el.connectionHint.textContent = errorMessage(error);
  toast(errorMessage(error), "err");
}

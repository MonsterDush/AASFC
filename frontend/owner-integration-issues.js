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
const provider = String(params.get("provider") || "quickresto").toLowerCase();
if (venueId) setActiveVenueId(venueId);

const ids = [
  "title",
  "venueTitle",
  "backToQuickResto",
  "openCount",
  "affectedShiftCount",
  "oldestFailedAt",
  "activeIssues",
  "allIssues",
  "providerFilter",
  "issueDate",
  "refreshIssues",
  "issueList",
  "issueHint",
  "issueDrawer",
  "issueDrawerTitle",
  "issueDrawerBody",
];
const el = Object.fromEntries(ids.map((id) => [id, document.getElementById(id)]));

const ACTIVE_STATUSES = new Set(["OPEN", "RETRY_PENDING", "PROCESSING"]);
const state = {
  configured: false,
  canManage: false,
  filter: "active",
  items: [],
  total: 0,
  openCount: 0,
  selectedIssue: null,
  selectedIssueId: null,
  returnFocus: null,
  mappings: { payments: [], departments: [] },
  catalog: {
    selected_external_venue_id: null,
    venues: [],
    sale_places: [],
    stores: [],
  },
  paymentMethods: [],
  departments: [],
};

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
    delete button.dataset.previousText;
  }
  button.disabled = !!busy;
}

function currentLocale() {
  return document.documentElement.lang === "en" ? "en-US" : "ru-RU";
}

function formatDate(value, { withTime = false } = {}) {
  const source = String(value || "").trim();
  if (!source) return "—";
  const date = /^\d{4}-\d{2}-\d{2}$/.test(source)
    ? new Date(`${source}T00:00:00`)
    : new Date(source);
  if (Number.isNaN(date.getTime())) return source;
  return new Intl.DateTimeFormat(currentLocale(), {
    day: "2-digit",
    month: withTime ? "2-digit" : "long",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

function statusLabel(value) {
  const status = String(value || "").toUpperCase();
  if (status === "OPEN") return "Ожидает решения";
  if (status === "FAILED") return "Ошибка";
  if (status === "BLOCKED") return "Ожидает решения";
  if (status === "READY") return "Готова к повтору";
  if (status === "RETRY_PENDING") return "Повтор запланирован";
  if (status === "PROCESSING") return "Обрабатывается";
  if (status === "RESOLVED") return "Исправлено";
  if (status === "IGNORED") return "Игнорируется";
  return status || "—";
}

function slotLabel(value) {
  const slot = String(value || "").toUpperCase();
  if (slot === "DAY") return "Дневная смена";
  if (slot === "NIGHT") return "Ночная смена";
  return value ? String(value) : "Слот не определён";
}

function summary(issue) {
  return String(
    issue?.user_summary ||
      "Импорт остановлен, чтобы данные отчёта не были сохранены неверно.",
  );
}

function renderCounters(result = {}) {
  state.openCount = Number(result.open_count ?? state.openCount ?? 0);
  el.openCount.textContent = String(state.openCount);
  el.affectedShiftCount.textContent = String(
    Number(result.affected_shift_count || 0),
  );
  el.oldestFailedAt.textContent = formatDate(result.oldest_failed_at, {
    withTime: true,
  });
}

function renderFilters() {
  const active = state.filter === "active";
  el.activeIssues.classList.toggle("active", active);
  el.activeIssues.classList.toggle("subtle", !active);
  el.allIssues.classList.toggle("active", !active);
  el.allIssues.classList.toggle("subtle", active);
}

function renderList() {
  renderFilters();
  if (!state.items.length) {
    const text =
      state.filter === "active"
        ? "Активных проблем импорта нет. Все полученные смены обработаны."
        : "История проблем импорта пока пуста.";
    el.issueList.innerHTML = `<div class="integration-issues-empty" data-status="ok">${text}</div>`;
    return;
  }
  const rows = state.items
    .map((issue) => {
      const status = String(issue.status || "OPEN").toUpperCase();
      return `<button class="itemcard integration-issue-row" type="button" data-issue-id="${issue.id}">
        <span class="integration-issue-row__main">
          <span class="integration-issue-row__head">
            <span class="integration-issue-status" data-status="${esc(status)}">${esc(statusLabel(status))}</span>
            <span class="integration-issue-row__date">${esc(formatDate(issue.business_date))} · ${esc(slotLabel(issue.shift_slot))}</span>
          </span>
          <span class="integration-issue-row__summary">${esc(summary(issue))}</span>
          <span class="integration-issue-row__meta">
            <span>Смен: ${Number(issue.shift_count || 0)}</span>
            <span>Попыток: ${Number(issue.attempt_count || 0)}</span>
            <span>Последняя ошибка: ${esc(formatDate(issue.last_failed_at, { withTime: true }))}</span>
          </span>
        </span>
        <span class="integration-issue-row__arrow" aria-hidden="true">›</span>
      </button>`;
    })
    .join("");
  const more =
    state.items.length < state.total
      ? `<button class="btn subtle integration-issues-more" type="button" data-load-more>Показать ещё · ${state.items.length} из ${state.total}</button>`
      : "";
  el.issueList.innerHTML = `${rows}${more}`;
}

function mappingOptions(items, selectedId) {
  return [
    `<option value="">— выберите в Axelio —</option>`,
    ...items.map(
      (item) =>
        `<option value="${item.id}"${String(item.id) === String(selectedId || "") ? " selected" : ""}>${esc(item.title)}</option>`,
    ),
  ].join("");
}

function uniqueIds(values) {
  return [...new Set((Array.isArray(values) ? values : []).map(String))];
}

function renderMappingResolution(issue) {
  const paymentIds = uniqueIds(issue?.details?.missing_payment_type_ids);
  const departmentIds = uniqueIds(issue?.details?.missing_department_ids);
  if (!paymentIds.length && !departmentIds.length) return "";
  const disabled = state.canManage && issue.can_retry !== false ? "" : " disabled";
  const paymentFields = paymentIds
    .map((externalId) => {
      const mapping = (state.mappings.payments || []).find(
        (item) => String(item.external_id) === externalId,
      );
      return `<label class="integration-issue-field">
        <span>${esc(mapping?.external_name || `Способ оплаты QuickResto #${externalId}`)}</span>
        <select data-issue-payment-id="${esc(externalId)}"${disabled}>${mappingOptions(state.paymentMethods, mapping?.payment_method_id)}</select>
      </label>`;
    })
    .join("");
  const departmentFields = departmentIds
    .map((externalId) => {
      const mapping = (state.mappings.departments || []).find(
        (item) => String(item.external_id) === externalId,
      );
      return `<label class="integration-issue-field">
        <span>${esc(mapping?.external_name || `Группа блюд QuickResto #${externalId}`)}</span>
        <select data-issue-department-id="${esc(externalId)}"${disabled}>${mappingOptions(state.departments, mapping?.department_id)}</select>
      </label>`;
    })
    .join("");
  return `<section class="integration-issue-resolution">
    <div><h3>Нужно сопоставить данные</h3><div class="muted small mt-4">Сначала сохраните соответствия, затем Axelio повторит импорт всех смен этой проблемы.</div></div>
    <div class="integration-issue-fields">${paymentFields}${departmentFields}</div>
    ${state.canManage && issue.can_retry !== false ? `<button class="btn primary" type="button" data-save-mappings-retry>Сохранить и повторить импорт</button>` : ""}
  </section>`;
}

function renderScopeResolution(issue) {
  if (String(issue.error_category || "").toUpperCase() !== "SCOPE") return "";
  const details = issue.details || {};
  const catalog = state.catalog || {};
  const venues = (catalog.venues || []).filter((item) => item.is_available !== false);
  const salePlaces = (catalog.sale_places || []).filter(
    (item) => item.is_available !== false,
  );
  const stores = (catalog.stores || []).filter((item) => item.is_available !== false);
  const selectedVenueId = String(catalog.selected_external_venue_id || "");
  const disabled = state.canManage && issue.can_retry !== false ? "" : " disabled";
  const facts = [
    ["Выбранное заведение", details.selected_external_venue_id],
    ["Заведение смены", details.shift_external_venue_id],
    ["Место реализации", details.sale_place_id],
    ["Точка открытия смены", details.opening_sale_place_id],
    ["Заведение точки", details.resolved_sale_place_venue_id],
  ]
    .filter(([, value]) => value !== null && value !== undefined)
    .map(
      ([label, value]) =>
        `<div><dt>${esc(label)}</dt><dd>QuickResto #${esc(value)}</dd></div>`,
    )
    .join("");
  const venueOptions = venues
    .map(
      (item) =>
        `<option value="${esc(item.external_id)}"${String(item.external_id) === selectedVenueId ? " selected" : ""}>${esc(item.external_name)}</option>`,
    )
    .join("");
  const salePlaceOptions = salePlaces
    .map(
      (item) =>
        `<label class="integration-issue-scope-choice" data-scope-sale-place-row data-venue-id="${esc(item.external_venue_id)}">
          <input type="checkbox" value="${esc(item.external_id)}" data-issue-scope-sale-place${item.is_selected ? " checked" : ""}${disabled} />
          <span><b>${esc(item.external_name)}</b><small>QuickResto #${esc(item.external_id)}</small></span>
        </label>`,
    )
    .join("");
  const storeOptions = stores
    .map(
      (item) =>
        `<label class="integration-issue-scope-choice" data-scope-store-row data-source-sale-place-ids="${esc((item.source_sale_place_ids || []).join(" "))}">
          <input type="checkbox" value="${esc(item.external_id)}" data-issue-scope-store${item.is_selected ? " checked" : ""}${disabled} />
          <span><b>${esc(item.external_name)}</b><small>QuickResto #${esc(item.external_id)}</small></span>
        </label>`,
    )
    .join("");
  return `<section class="integration-issue-resolution">
    <div><h3>Исправьте область импорта</h3><div class="muted small mt-4">Обновите справочник, выберите нужное заведение и точки. После сохранения Axelio сразу повторит импорт проблемных смен.</div></div>
    ${facts ? `<dl class="integration-issue-facts">${facts}</dl>` : ""}
    ${
      venues.length
        ? `<div class="integration-issue-scope-editor">
            <label class="integration-issue-field"><span>Заведение QuickResto</span><select data-issue-scope-venue${disabled}><option value="">— выберите заведение —</option>${venueOptions}</select></label>
            <fieldset class="integration-issue-scope-group"><legend>Места реализации</legend><div class="integration-issue-scope-choices">${salePlaceOptions || '<div class="muted small">Места реализации не найдены.</div>'}</div></fieldset>
            <fieldset class="integration-issue-scope-group"><legend>Связанные склады</legend><div class="integration-issue-scope-choices">${storeOptions || '<div class="muted small">Связанные склады не найдены.</div>'}</div></fieldset>
          </div>`
        : '<div class="integration-issue-readonly">Справочник QuickResto ещё не загружен. Обновите его, чтобы выбрать заведение и точки.</div>'
    }
    ${
      state.canManage && issue.can_retry !== false
        ? `<div class="integration-issue-scope-actions">
            <button class="btn" type="button" data-refresh-scope-catalog>Обновить справочник</button>
            ${venues.length ? '<button class="btn primary" type="button" data-save-scope-retry>Сохранить область и повторить импорт</button>' : ""}
          </div>`
        : ""
    }
  </section>`;
}

function syncIssueScopeFields() {
  const venueField = el.issueDrawerBody.querySelector("[data-issue-scope-venue]");
  if (!venueField) return;
  const selectedVenueId = String(venueField.value || "");
  const selectedSalePlaceIds = new Set();
  el.issueDrawerBody.querySelectorAll("[data-scope-sale-place-row]").forEach((row) => {
    const checkbox = row.querySelector("[data-issue-scope-sale-place]");
    const visible = !!selectedVenueId && String(row.dataset.venueId || "") === selectedVenueId;
    row.hidden = !visible;
    if (!visible && checkbox) checkbox.checked = false;
    if (visible && checkbox?.checked) selectedSalePlaceIds.add(String(checkbox.value));
  });
  el.issueDrawerBody.querySelectorAll("[data-scope-store-row]").forEach((row) => {
    const checkbox = row.querySelector("[data-issue-scope-store]");
    const sourceIds = new Set(String(row.dataset.sourceSalePlaceIds || "").split(/\s+/).filter(Boolean));
    const visible =
      !!selectedVenueId &&
      (!sourceIds.size || [...sourceIds].some((value) => selectedSalePlaceIds.has(value)));
    row.hidden = !visible;
    if (!visible && checkbox) checkbox.checked = false;
  });
}

function renderShifts(issue) {
  const shifts = Array.isArray(issue?.shifts) ? issue.shifts : [];
  if (!shifts.length) {
    return `<div class="integration-issues-empty">Сведения о сменах пока не загружены.</div>`;
  }
  return `<div class="integration-issue-shifts">${shifts
    .map((shift, index) => {
      const id = shift.external_shift_id || shift.external_shift_pk || index + 1;
      const period = `${formatDate(shift.local_opened_at, { withTime: true })} — ${formatDate(shift.local_closed_at, { withTime: true })}`;
      return `<div class="itemcard integration-issue-shift">
        <div class="integration-issue-shift__head"><b>Смена QuickResto #${esc(id)}</b><span class="integration-issue-shift__status">${esc(statusLabel(shift.item_status))}</span></div>
        <div class="muted small">${esc(period)}</div>
        ${shift.user_summary ? `<div class="integration-issue-shift__summary">${esc(shift.user_summary)}</div>` : ""}
      </div>`;
    })
    .join("")}</div>`;
}

function renderHistoricalScopeMismatch(issue) {
  if (String(issue?.error_code || "").toUpperCase() !== "PREVIOUS_SCOPE_MISMATCH") return "";
  const ids = Array.isArray(issue?.details?.legacy_external_shift_ids) ? issue.details.legacy_external_shift_ids : [];
  return `<section class="integration-issue-resolution"><div><h3>Историческая проверка области</h3><div class="muted small mt-4">Axelio ничего не переписал автоматически. Проверьте старые отчёты вручную перед любыми корректировками.</div></div><dl class="integration-issue-facts"><div><dt>Затронуто ранее импортированных смен</dt><dd>${Number(issue?.details?.legacy_shift_count || issue?.shift_count || 0)}</dd></div></dl>${ids.length ? `<div class="muted small">QuickResto shift ID: ${esc(ids.join(", "))}</div>` : ""}</section>`;
}

function renderDrawer(issue) {
  state.selectedIssue = issue;
  const status = String(issue.status || "OPEN").toUpperCase();
  const actionable = ACTIVE_STATUSES.has(status);
  const canRetry = state.canManage && actionable && issue.can_retry !== false;
  const canIgnore = state.canManage && actionable && issue.can_ignore !== false;
  const hasMappingFields =
    uniqueIds(issue?.details?.missing_payment_type_ids).length > 0 ||
    uniqueIds(issue?.details?.missing_department_ids).length > 0;
  el.issueDrawerTitle.textContent = `${formatDate(issue.business_date)} · ${slotLabel(issue.shift_slot)}`;
  el.issueDrawerBody.innerHTML = `
    <div class="integration-issue-detail-head">
      <span class="integration-issue-status" data-status="${esc(status)}">${esc(statusLabel(status))}</span>
      <p>${esc(summary(issue))}</p>
    </div>
    <dl class="integration-issue-facts">
      <div><dt>Дата отчёта</dt><dd>${esc(formatDate(issue.business_date))}</dd></div>
      <div><dt>Слот</dt><dd>${esc(slotLabel(issue.shift_slot))}</dd></div>
      <div><dt>Смен</dt><dd>${Number(issue.shift_count || 0)}</dd></div>
      <div><dt>Попыток</dt><dd>${Number(issue.attempt_count || 0)}</dd></div>
      <div><dt>Код причины</dt><dd>${esc(issue.error_code || "—")}</dd></div>
      <div><dt>Последняя ошибка</dt><dd>${esc(formatDate(issue.last_failed_at, { withTime: true }))}</dd></div>
    </dl>
    ${String(issue.error_code || "").toUpperCase() === "PREVIOUS_SCOPE_MISMATCH" ? renderHistoricalScopeMismatch(issue) : `<section class="integration-issue-detail-section"><h3>Смены QuickResto</h3>${renderShifts(issue)}</section>`}
    ${renderScopeResolution(issue)}
    ${renderMappingResolution(issue)}
    ${!state.canManage ? `<div class="integration-issue-readonly">Доступ только для просмотра. Решить проблему может владелец или администратор заведения.</div>` : ""}
    ${status === "PROCESSING" ? `<div class="integration-issue-processing">Повторный импорт уже выполняется.</div>` : ""}
    ${
      canRetry && !hasMappingFields
        ? `<div class="integration-issue-actions"><button class="btn primary" type="button" data-retry>Повторить импорт</button></div>`
        : ""
    }
    ${
      canIgnore
        ? `<section class="integration-issue-ignore">
            <label class="integration-issue-field"><span>Почему проблему можно проигнорировать</span><textarea id="resolutionNote" rows="3" minlength="3" maxlength="1000" placeholder="Обязательная заметка для истории решения"></textarea></label>
            <button class="btn danger" type="button" data-ignore>Игнорировать проблему</button>
          </section>`
        : ""
    }
    <div class="muted small integration-issue-action-hint" id="actionHint" aria-live="polite"></div>`;
  syncIssueScopeFields();
}

function actionHint(message, error = false) {
  const hint = document.getElementById("actionHint");
  if (!hint) return;
  hint.textContent = message || "";
  hint.dataset.status = error ? "error" : "";
}

function showDrawer(issueId) {
  state.returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  state.selectedIssueId = String(issueId);
  state.selectedIssue = null;
  el.issueDrawerTitle.textContent = "Проблема импорта QuickResto";
  el.issueDrawerBody.innerHTML = `<div class="integration-issues-empty">Загружаем сведения…</div>`;
  el.issueDrawer.classList.add("open");
  el.issueDrawer.setAttribute("aria-hidden", "false");
  document.body.classList.add("integration-issue-drawer-open");
  el.issueDrawer.querySelector("[data-issue-close]")?.focus();
}

function closeDrawer() {
  if (!el.issueDrawer.classList.contains("open")) return;
  el.issueDrawer.classList.remove("open");
  el.issueDrawer.setAttribute("aria-hidden", "true");
  document.body.classList.remove("integration-issue-drawer-open");
  state.selectedIssue = null;
  state.selectedIssueId = null;
  if (state.returnFocus?.isConnected) state.returnFocus.focus();
  state.returnFocus = null;
}

function drawerFocusableElements() {
  return [
    ...el.issueDrawer.querySelectorAll(
      'a[href], button:not([disabled]), select:not([disabled]), textarea:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ].filter(
    (item) =>
      item instanceof HTMLElement &&
      !item.hidden &&
      !item.closest("[hidden]") &&
      item.getClientRects().length > 0,
  );
}

async function loadDetail(issueId) {
  try {
    const issue = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${encodeURIComponent(issueId)}`,
    );
    if (state.selectedIssueId === String(issueId)) renderDrawer(issue);
  } catch (error) {
    el.issueDrawerBody.innerHTML = `<div class="integration-issues-empty" data-status="error">${esc(errorMessage(error))}</div>`;
  }
}

async function openIssue(issueId) {
  showDrawer(issueId);
  await loadDetail(issueId);
}

async function loadIssues({ append = false } = {}) {
  if (!state.configured) {
    state.items = [];
    state.total = 0;
    renderList();
    return;
  }
  if (!append) {
    el.issueList.innerHTML = `<div class="integration-issues-empty">Загружаем проблемы импорта…</div>`;
  }
  el.issueHint.textContent = "";
  try {
    const offset = append ? state.items.length : 0;
    const query = new URLSearchParams({
      status: state.filter,
      limit: "100",
      offset: String(offset),
    });
    if (el.issueDate?.value) query.set("business_date", el.issueDate.value);
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues?${query}`,
    );
    const items = Array.isArray(result.items) ? result.items : [];
    state.items = append ? [...state.items, ...items] : items;
    state.total = Number(result.total ?? state.items.length);
    renderCounters(result);
    renderList();
  } catch (error) {
    el.issueList.innerHTML = `<div class="integration-issues-empty" data-status="error">${esc(errorMessage(error))}</div>`;
  }
}

function collectMappingPayload(overrides = {}) {
  const paymentOverrides = overrides.paymentOverrides || new Map();
  const departmentOverrides = overrides.departmentOverrides || new Map();
  const payments = (state.mappings.payments || [])
    .filter((item) => item.is_available !== false && item.is_applicable !== false)
    .map((item) => {
      const value = paymentOverrides.has(String(item.external_id))
        ? paymentOverrides.get(String(item.external_id))
        : item.payment_method_id;
      const writeoff = String(item.operation_type || "").toLowerCase() === "writeoff";
      return {
        external_id: item.external_id,
        payment_method_id: writeoff || !value ? null : Number(value),
        excluded_from_revenue: writeoff,
      };
    });
  const departments = (state.mappings.departments || []).map((item) => ({
    external_id: item.external_id,
    department_id: departmentOverrides.has(String(item.external_id))
      ? Number(departmentOverrides.get(String(item.external_id)))
      : item.department_id,
  }));
  return { payments, departments };
}

async function retryIssue(button) {
  const issue = state.selectedIssue;
  if (!issue || !state.canManage) return;
  setBusy(button, true, "Повторяем импорт…");
  actionHint("");
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${issue.id}/retry`,
      { method: "POST" },
    );
    await loadIssues();
    if (result.ok && String(result.run?.status).toUpperCase() === "SUCCEEDED") {
      closeDrawer();
      toast("Смены успешно импортированы", "ok");
    } else {
      renderDrawer(result.issue);
      actionHint(result.issue?.user_summary || "Проблема всё ещё требует внимания.", true);
      toast("Повторный импорт требует внимания", "err");
    }
  } catch (error) {
    actionHint(errorMessage(error), true);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

async function saveMappingsAndRetry(button) {
  const issue = state.selectedIssue;
  if (!issue || !state.canManage) return;
  const paymentOverrides = new Map();
  const departmentOverrides = new Map();
  let invalid = false;
  el.issueDrawerBody.querySelectorAll("[data-issue-payment-id]").forEach((field) => {
    field.removeAttribute("aria-invalid");
    if (!field.value) {
      field.setAttribute("aria-invalid", "true");
      invalid = true;
    }
    paymentOverrides.set(String(field.dataset.issuePaymentId), field.value);
  });
  el.issueDrawerBody.querySelectorAll("[data-issue-department-id]").forEach((field) => {
    field.removeAttribute("aria-invalid");
    if (!field.value) {
      field.setAttribute("aria-invalid", "true");
      invalid = true;
    }
    departmentOverrides.set(String(field.dataset.issueDepartmentId), field.value);
  });
  if (invalid) {
    actionHint("Выберите соответствие для каждого значения QuickResto.", true);
    return;
  }
  setBusy(button, true, "Сохраняем и повторяем…");
  try {
    const mappingResult = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/mappings`,
      {
        method: "PUT",
        body: collectMappingPayload({ paymentOverrides, departmentOverrides }),
      },
    );
    state.mappings = mappingResult.mappings || state.mappings;
    const retryResult = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${issue.id}/retry`,
      { method: "POST" },
    );
    await loadIssues();
    if (
      retryResult.ok &&
      String(retryResult.run?.status).toUpperCase() === "SUCCEEDED"
    ) {
      closeDrawer();
      toast("Сопоставления сохранены, смены импортированы", "ok");
    } else {
      renderDrawer(retryResult.issue);
      actionHint(
        retryResult.issue?.user_summary ||
          "После сопоставления проблема всё ещё требует внимания.",
        true,
      );
      toast("Импорт всё ещё требует внимания", "err");
    }
  } catch (error) {
    actionHint(errorMessage(error), true);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

async function refreshScopeCatalog(button) {
  const issue = state.selectedIssue;
  if (!issue || !state.canManage) return;
  setBusy(button, true, "Обновляем…");
  actionHint("");
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/catalog/refresh`,
      { method: "POST" },
    );
    state.catalog = result.catalog || state.catalog;
    renderDrawer(issue);
    actionHint("Справочник обновлён. Проверьте заведение и точки перед сохранением.");
  } catch (error) {
    actionHint(errorMessage(error), true);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

async function saveScopeAndRetry(button) {
  const issue = state.selectedIssue;
  if (!issue || !state.canManage) return;
  const venueField = el.issueDrawerBody.querySelector("[data-issue-scope-venue]");
  const externalVenueId = Number(venueField?.value || 0);
  const salePlaceIds = [
    ...el.issueDrawerBody.querySelectorAll(
      "[data-scope-sale-place-row]:not([hidden]) [data-issue-scope-sale-place]:checked",
    ),
  ].map((field) => Number(field.value));
  const storeIds = [
    ...el.issueDrawerBody.querySelectorAll(
      "[data-scope-store-row]:not([hidden]) [data-issue-scope-store]:checked",
    ),
  ].map((field) => Number(field.value));
  venueField?.removeAttribute("aria-invalid");
  if (!externalVenueId || !salePlaceIds.length) {
    venueField?.setAttribute("aria-invalid", "true");
    actionHint("Выберите заведение и хотя бы одно место реализации.", true);
    return;
  }
  setBusy(button, true, "Сохраняем и повторяем…");
  actionHint("");
  try {
    const scopeResult = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/scope`,
      {
        method: "PUT",
        body: {
          external_venue_id: externalVenueId,
          sale_place_ids: salePlaceIds,
          store_ids: storeIds,
        },
      },
    );
    state.catalog = scopeResult.catalog || state.catalog;
    state.mappings = scopeResult.mappings || state.mappings;
    const retryResult = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${issue.id}/retry`,
      { method: "POST" },
    );
    await loadIssues();
    if (
      retryResult.ok &&
      String(retryResult.run?.status).toUpperCase() === "SUCCEEDED"
    ) {
      closeDrawer();
      toast("Область сохранена, смены успешно импортированы", "ok");
    } else {
      renderDrawer(retryResult.issue);
      actionHint(
        retryResult.issue?.user_summary ||
          "После изменения области проблема всё ещё требует внимания.",
        true,
      );
      toast("Импорт всё ещё требует внимания", "err");
    }
  } catch (error) {
    actionHint(errorMessage(error), true);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

async function ignoreIssue(button) {
  const issue = state.selectedIssue;
  const noteField = document.getElementById("resolutionNote");
  const note = String(noteField?.value || "").trim();
  if (!issue || !state.canManage) return;
  if (note.length < 3) {
    noteField?.setAttribute("aria-invalid", "true");
    noteField?.focus();
    actionHint("Добавьте заметку минимум из 3 символов.", true);
    return;
  }
  setBusy(button, true, "Сохраняем решение…");
  try {
    await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/issues/${issue.id}/resolve`,
      { method: "POST", body: { action: "IGNORE", note } },
    );
    closeDrawer();
    await loadIssues();
    toast("Проблема отмечена как проигнорированная", "ok");
  } catch (error) {
    actionHint(errorMessage(error), true);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
  }
}

async function loadPage() {
  if (!venueId) throw new Error("Сначала выберите заведение");
  if (provider !== "quickresto") throw new Error("Этот источник интеграции пока не поддерживается");
  if (el.providerFilter) el.providerFilter.value = provider;
  el.backToQuickResto.dataset.href = `/owner-quickresto.html?venue_id=${encodeURIComponent(venueId)}`;
  const [venue, integration, paymentMethods, departments] = await Promise.all([
    getVenueById(venueId),
    api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto`),
    getPaymentMethods(venueId, { includeArchived: false }),
    getDepartments(venueId, { includeArchived: false }),
  ]);
  const venueName = venue?.name || `Заведение ${venueId}`;
  el.title.textContent = `Проблемы импорта · ${venueName}`;
  el.venueTitle.textContent = venueName;
  state.configured = !!integration.configured;
  state.canManage = integration.permissions?.can_manage !== false;
  state.mappings = integration.mappings || state.mappings;
  state.catalog = integration.catalog || state.catalog;
  state.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
  state.departments = Array.isArray(departments) ? departments : [];
  renderCounters(integration.issues || {});
  await loadIssues();
  const requestedIssueId = params.get("issue_id");
  if (requestedIssueId) await openIssue(requestedIssueId);
}

el.activeIssues?.addEventListener("click", async () => {
  state.filter = "active";
  await loadIssues();
});
el.allIssues?.addEventListener("click", async () => {
  state.filter = "all";
  await loadIssues();
});
el.providerFilter?.addEventListener("change", async () => {
  const nextProvider = String(el.providerFilter.value || "quickresto").toLowerCase();
  if (nextProvider !== "quickresto") return;
  await loadIssues();
});
el.issueDate?.addEventListener("change", async () => {
  await loadIssues();
});
el.refreshIssues?.addEventListener("click", async () => {
  setBusy(el.refreshIssues, true, "Обновляем…");
  await loadIssues();
  setBusy(el.refreshIssues, false);
});
el.issueList?.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest("[data-load-more]")) {
    void loadIssues({ append: true });
    return;
  }
  const row = target?.closest("[data-issue-id]");
  if (row) void openIssue(row.dataset.issueId);
});
el.issueDrawer?.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (target?.closest("[data-issue-close]")) closeDrawer();
  else if (target?.closest("[data-refresh-scope-catalog]"))
    void refreshScopeCatalog(target.closest("[data-refresh-scope-catalog]"));
  else if (target?.closest("[data-save-scope-retry]"))
    void saveScopeAndRetry(target.closest("[data-save-scope-retry]"));
  else if (target?.closest("[data-save-mappings-retry]"))
    void saveMappingsAndRetry(target.closest("[data-save-mappings-retry]"));
  else if (target?.closest("[data-retry]"))
    void retryIssue(target.closest("[data-retry]"));
  else if (target?.closest("[data-ignore]"))
    void ignoreIssue(target.closest("[data-ignore]"));
});
el.issueDrawer?.addEventListener("input", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  target?.removeAttribute("aria-invalid");
  actionHint("");
});
el.issueDrawer?.addEventListener("change", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (target?.matches("[data-issue-scope-venue], [data-issue-scope-sale-place]")) {
    syncIssueScopeFields();
    actionHint("");
  }
});
document.addEventListener("keydown", (event) => {
  if (!el.issueDrawer.classList.contains("open")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    closeDrawer();
    return;
  }
  if (event.key === "Tab") {
    const items = drawerFocusableElements();
    if (!items.length) return;
    const first = items[0];
    const last = items.at(-1);
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
});

try {
  await loadPage();
} catch (error) {
  el.issueList.innerHTML = `<div class="integration-issues-empty" data-status="error">${esc(errorMessage(error))}</div>`;
  toast(errorMessage(error), "err");
}

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

const elementIds = [
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
  "mappingReadinessHint",
  "paymentMappings",
  "paymentSection",
  "savePaymentMappings",
  "paymentMappingHint",
  "departmentMappings",
  "departmentSection",
  "saveMappings",
  "mappingHint",
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
  "scopeSection",
  "scopeStatus",
  "refreshScopeCatalog",
  "scopeContent",
  "externalVenue",
  "salePlaceOptions",
  "storeOptions",
  "saveScope",
  "scopeHint",
  "scopeAuditList",
  "issueSection",
  "issueOpenCount",
  "openIssues",
  "openKpiMappings",
  "importSection",
  "importHint",
  "batchStatus",
  "batchProgress",
  "batchProgressTitle",
  "batchProgressPercent",
  "batchProgressTrack",
  "batchProgressBar",
  "batchProgressMeta",
  "batchProgressError",
  "retryBatch",
  "openImportHistory",
];
const el = Object.fromEntries(
  elementIds.map((id) => [id, document.getElementById(id)]),
);

const emptyCatalog = () => ({
  scope_status: "NEEDS_SELECTION",
  scope_generation: 1,
  selected_external_venue_id: null,
  venues: [],
  sale_places: [],
  stores: [],
  payment_types: [],
});

const state = {
  configured: false,
  connection: null,
  catalog: emptyCatalog(),
  mappings: { payments: [], departments: [] },
  paymentMethods: [],
  departments: [],
  importBatch: null,
  venueNightShiftsEnabled: false,
  canManage: true,
  issueOpenCount: 0,
  activePosProvider: null,
  mappingReadiness: {
    ready: false,
    discovered: false,
    unmapped_payment_type_ids: [],
    unmapped_department_ids: [],
  },
  scopeAudit: [],
};

let batchPollTimer = null;

el.openKpiMappings.href = `/owner-quickresto-kpi.html?venue_id=${encodeURIComponent(venueId)}`;
el.openImportHistory.href = `/owner-quickresto-import-history.html?venue_id=${encodeURIComponent(venueId)}`;

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

function scrollToStep(target) {
  target?.scrollIntoView({ behavior: "smooth", block: "start" });
}

function batchIsActive(batch = state.importBatch) {
  return ["PENDING", "RUNNING"].includes(
    String(batch?.status || "").toUpperCase(),
  );
}

function batchStatusLabel(status) {
  const normalized = String(status || "").toUpperCase();
  if (normalized === "PENDING") return "В очереди";
  if (normalized === "RUNNING") return "Импортируется";
  if (normalized === "SUCCEEDED") return "Завершён";
  if (normalized === "PARTIAL") return "Требует внимания";
  if (normalized === "FAILED") return "Остановлен";
  return "Не запускался";
}

function formatMonthPeriod(start, endExclusive) {
  if (!start) return "—";
  const startDate = new Date(`${start}T00:00:00`);
  const endDate = endExclusive
    ? new Date(new Date(`${endExclusive}T00:00:00`).getTime() - 86400000)
    : startDate;
  const locale = document.documentElement.lang === "en" ? "en-US" : "ru-RU";
  const month = new Intl.DateTimeFormat(locale, {
    month: "long",
    year: "numeric",
  }).format(startDate);
  if (
    startDate.getDate() === 1 &&
    endDate.getMonth() === startDate.getMonth() &&
    endDate.getFullYear() === startDate.getFullYear()
  ) {
    return month;
  }
  return `${formatDate(start)}–${formatDate(endDate.toISOString().slice(0, 10))}`;
}

function renderBatchProgress() {
  const batch = state.importBatch;
  const status = String(batch?.status || "").toUpperCase();
  el.batchStatus.textContent = batchStatusLabel(status);
  el.batchStatus.dataset.status = status || "NEVER";
  el.batchProgress.hidden = !batch;
  if (!batch) return;
  const total = Math.max(Number(batch.total_periods || 0), 1);
  const completed = Math.min(Number(batch.completed_periods || 0), total);
  const percent = Math.round((completed / total) * 100);
  const activePeriod = batch.current_period_start || batch.next_period_start;
  const activePeriodEnd = batch.current_period_end_exclusive || null;
  el.batchProgressTitle.textContent = batchIsActive(batch)
    ? `Обрабатывается: ${formatMonthPeriod(activePeriod, activePeriodEnd)}`
    : `${formatMonthPeriod(batch.period_start, batch.period_end_exclusive)} · ${batchStatusLabel(status)}`;
  el.batchProgressPercent.textContent = `${percent}%`;
  el.batchProgressTrack.dataset.active = batchIsActive(batch) ? "true" : "false";
  el.batchProgressBar.value = percent;
  el.batchProgressBar.textContent = `${percent}%`;
  const totals = batch.summary?.totals || {};
  el.batchProgressMeta.innerHTML = [
    `<span>Месяцев: <b>${completed} из ${total}</b></span>`,
    `<span>Смен импортировано: <b>${Number(totals.shifts_imported || 0)}</b></span>`,
    `<span>Отчётов создано: <b>${Number(totals.reports_created || 0)}</b></span>`,
    Number(batch.partial_periods || 0)
      ? `<span>С вниманием: <b>${Number(batch.partial_periods)}</b></span>`
      : "",
  ]
    .filter(Boolean)
    .join("");
  el.batchProgressError.hidden = !batch.error;
  el.batchProgressError.textContent = batch.error || "";
  el.retryBatch.hidden = !(status === "FAILED" && state.canManage);
}

async function refreshBatchProgress() {
  if (!state.configured) return;
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/import-batches?limit=1`,
    );
    state.importBatch = result.items?.[0] || null;
    if (state.connection && state.importBatch) {
      state.connection.last_sync_status = state.importBatch.status;
      state.connection.last_sync_error = state.importBatch.error || null;
    }
    renderBatchProgress();
    renderConnection();
    applyPermissions();
    if (!batchIsActive()) stopBatchPolling();
  } catch {
    // Keep the last durable state visible; the next poll or reload can recover.
  }
}

function startBatchPolling() {
  if (batchPollTimer || !batchIsActive()) return;
  batchPollTimer = window.setInterval(refreshBatchProgress, 5000);
}

function stopBatchPolling() {
  if (!batchPollTimer) return;
  window.clearInterval(batchPollTimer);
  batchPollTimer = null;
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

function currentScopeStatus() {
  return String(
    state.catalog?.scope_status ||
      state.connection?.scope_status ||
      "NEEDS_SELECTION",
  ).toUpperCase();
}

function scopeReady() {
  return (
    state.configured &&
    currentScopeStatus() === "READY" &&
    !!(
      state.catalog?.selected_external_venue_id ||
      state.connection?.external_venue_id
    )
  );
}

function scopeStatusLabel(status) {
  if (status === "READY") return "Настроено";
  if (status === "STALE") return "Нужно обновить";
  return "Нужно выбрать";
}

function selectedScopeSalePlaceIds() {
  return new Set(
    Array.from(
      el.salePlaceOptions.querySelectorAll(
        'input[type="checkbox"][data-sale-place-id]:checked',
      ),
    ).map((input) => Number(input.dataset.salePlaceId)),
  );
}

function renderScopeStores() {
  const selectedSaleIds = selectedScopeSalePlaceIds();
  const stores = (state.catalog?.stores || []).filter((store) => {
    if (store.is_available === false) return false;
    const sources = Array.isArray(store.source_sale_place_ids)
      ? store.source_sale_place_ids.map(Number)
      : [];
    return (
      sources.length === 0 || sources.some((id) => selectedSaleIds.has(id))
    );
  });
  if (!selectedSaleIds.size) {
    el.storeOptions.innerHTML = `<div class="quickresto-empty">Выберите хотя бы одно место реализации.</div>`;
    return;
  }
  if (!stores.length) {
    el.storeOptions.innerHTML = `<div class="quickresto-empty">Для выбранных точек QuickResto не передал связанные склады. Можно продолжить без выбора склада.</div>`;
    return;
  }
  el.storeOptions.innerHTML = stores
    .map((store) => {
      const saleIds = Array.isArray(store.source_sale_place_ids)
        ? store.source_sale_place_ids
        : [];
      const cookingIds = Array.isArray(store.source_cooking_place_ids)
        ? store.source_cooking_place_ids
        : [];
      const relation = [
        saleIds.length ? `точки #${saleIds.join(", #")}` : "",
        cookingIds.length ? `CookingPlace #${cookingIds.join(", #")}` : "",
      ]
        .filter(Boolean)
        .join(" · ");
      return `<label class="quickresto-scope-choice">
        <input type="checkbox" data-store-id="${store.external_id}"${(store.is_pending_selected ?? store.is_selected) ? " checked" : ""}${state.canManage ? "" : " disabled"} />
        <span><b>${esc(store.external_name)}</b><small>QuickResto #${store.external_id}${relation ? ` · ${esc(relation)}` : ""}</small></span>
      </label>`;
    })
    .join("");
}

function renderScope({ preserveVenue = false } = {}) {
  const status = currentScopeStatus();
  el.scopeSection.dataset.status = status;
  el.scopeStatus.textContent = scopeStatusLabel(status);
  el.scopeStatus.dataset.status = status;

  const venues = (state.catalog?.venues || []).filter(
    (venue) => venue.is_available !== false,
  );
  const selectedVenueId = String(
    (preserveVenue ? el.externalVenue.value : "") ||
      state.catalog?.pending_scope?.external_venue_id ||
      state.catalog?.selected_external_venue_id ||
      state.connection?.external_venue_id ||
      "",
  );
  el.externalVenue.innerHTML = [
    `<option value="">— выберите заведение —</option>`,
    ...venues.map((venue) => {
      const label = venue.address
        ? `${venue.external_name} · ${venue.address}`
        : venue.external_name;
      return `<option value="${venue.external_id}"${String(venue.external_id) === selectedVenueId ? " selected" : ""}>${esc(label)}</option>`;
    }),
  ].join("");

  const activeVenueId = Number(el.externalVenue.value || 0);
  const salePlaces = (state.catalog?.sale_places || []).filter(
    (place) =>
      place.is_available !== false &&
      Number(place.external_venue_id) === activeVenueId,
  );
  el.salePlaceOptions.innerHTML = !activeVenueId
    ? `<div class="quickresto-empty">Сначала выберите заведение QuickResto.</div>`
    : salePlaces.length
      ? salePlaces
          .map(
            (place) => `<label class="quickresto-scope-choice">
              <input type="checkbox" data-sale-place-id="${place.external_id}"${(place.is_pending_selected ?? place.is_selected) ? " checked" : ""}${state.canManage ? "" : " disabled"} />
              <span><b>${esc(place.external_name)}</b><small>Место реализации #${place.external_id}</small></span>
            </label>`,
          )
          .join("")
      : `<div class="quickresto-empty">У выбранного заведения не найдены места реализации. Проверьте их в QuickResto и обновите список.</div>`;
  renderScopeStores();

  if (!state.configured) {
    el.scopeHint.textContent =
      "Сначала сохраните подключение к облаку QuickResto.";
  } else if (!venues.length) {
    el.scopeHint.textContent =
      "Получите список заведений, точек и складов из QuickResto.";
  } else if (status === "STALE") {
    el.scopeHint.textContent =
      "Справочники QuickResto изменились. Проверьте выбор и сохраните область импорта заново.";
  } else if (state.catalog?.pending_scope) {
    el.scopeHint.textContent =
      `Новая область версии ${Number(state.catalog.pending_scope.scope_generation || 0)} ожидает полной исторической сверки. ` +
      "Текущая область остаётся активной до решений по ранее импортированным сменам.";
  } else if (status === "READY") {
    el.scopeHint.textContent = `Импорт ограничен заведением «${state.connection?.external_venue_name || "QuickResto"}».`;
  } else {
    el.scopeHint.textContent =
      "Выберите конкретное заведение и хотя бы одно место реализации.";
  }
  applyPermissions();
}

function formatDate(value, { withTime = false } = {}) {
  const source = String(value || "").trim();
  if (!source) return "—";
  const date = new Date(source);
  if (Number.isNaN(date.getTime())) return source;
  return new Intl.DateTimeFormat(
    document.documentElement.lang === "en" ? "en-US" : "ru-RU",
    {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
    },
  ).format(date);
}

function requiredMappingsReady() {
  return scopeReady() && state.mappingReadiness?.ready === true;
}

function renderMappingReadiness() {
  if (!el.mappingReadinessHint) return;
  if (!scopeReady()) {
    el.mappingReadinessHint.textContent = "";
    return;
  }
  if (!state.mappingReadiness?.discovered) {
    el.mappingReadinessHint.textContent =
      "Перед импортом получите справочники и завершите обязательные сопоставления.";
    return;
  }
  el.mappingReadinessHint.textContent = state.mappingReadiness?.ready
    ? "Обязательные сопоставления заполнены — импорт доступен."
    : "Перед импортом завершите обязательные сопоставления оплат и департаментов.";
}

function renderScopeAudit() {
  if (!el.scopeAuditList) return;
  const rows = Array.isArray(state.scopeAudit) ? state.scopeAudit : [];
  if (!rows.length) {
    el.scopeAuditList.innerHTML = `<div class="quickresto-empty">История изменений пока пуста.</div>`;
    return;
  }
  el.scopeAuditList.innerHTML = rows
    .map((item) => {
      const changes = item.changes || {};
      const parts = [
        (changes.sale_places_added || []).length
          ? `+ точки: ${(changes.sale_places_added || []).join(", ")}`
          : "",
        (changes.sale_places_removed || []).length
          ? `− точки: ${(changes.sale_places_removed || []).join(", ")}`
          : "",
        (changes.stores_added || []).length
          ? `+ склады: ${(changes.stores_added || []).join(", ")}`
          : "",
        (changes.stores_removed || []).length
          ? `− склады: ${(changes.stores_removed || []).join(", ")}`
          : "",
      ].filter(Boolean);
      return `<div class="itemcard quickresto-scope-audit__row">
        <div><b>Версия области ${Number(item.scope_generation || 1)}</b><div class="muted small">${esc(formatDate(item.changed_at, { withTime: true }))} · пользователь #${esc(item.actor_user_id || "—")}</div></div>
        <div class="muted small">${esc(parts.join(" · ") || "Область подтверждена без изменения набора точек.")}</div>
      </div>`;
    })
    .join("");
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

function applyPermissions() {
  const importLocked = batchIsActive();
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
    el.externalVenue,
  ];
  editableFields.forEach((field) => {
    if (field) field.disabled = !state.canManage || importLocked;
  });
  const providerConflict =
    state.activePosProvider && state.activePosProvider !== "QUICKRESTO";
  el.isActive.disabled = !state.canManage || importLocked || !!providerConflict;
  el.connectionActions.hidden = !state.canManage;
  el.saveMappings.hidden = !state.canManage;
  el.savePaymentMappings.hidden = !state.canManage;
  el.refreshScopeCatalog.hidden = !state.canManage;
  el.saveScope.hidden = !state.canManage;
  el.readOnlyHint.hidden = state.canManage;
  el.paymentMappings.querySelectorAll("select").forEach((field) => {
    field.disabled = !state.canManage || importLocked;
  });
  el.departmentMappings
    .querySelectorAll("select, input, button")
    .forEach((field) => {
    field.disabled = !state.canManage || importLocked;
    });
  el.scopeContent.querySelectorAll("input, select").forEach((field) => {
    field.disabled = !state.canManage || importLocked;
  });
  el.saveConnection.disabled = !state.canManage || importLocked;
  el.refreshScopeCatalog.disabled = !state.configured || importLocked;
  el.saveScope.disabled =
    !state.configured || importLocked || !(state.catalog?.venues || []).length;
  const ready = scopeReady();
  const importReady = requiredMappingsReady();
  el.discoverMappings.disabled = !ready || importLocked;
  el.savePaymentMappings.disabled = !ready || importLocked;
  el.saveMappings.disabled = !ready || importLocked;
  el.runSync.disabled = !importReady || importLocked;
  el.runFullSync.disabled = !importReady || importLocked;
  renderMappingReadiness();
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
    ? `Подключено к ${connection.cloud}.quickresto.ru · учётные данные сохранены зашифрованно`
    : "Укажите облако, API-логин и пароль QuickResto.";
  const status = String(connection.last_sync_status || "NEVER").toUpperCase();
  el.syncStatus.textContent = status;
  el.syncStatus.dataset.status = status;
  if (connection.last_sync_error) {
    el.connectionHint.textContent = connection.last_sync_error;
  } else if (
    state.activePosProvider &&
    state.activePosProvider !== "QUICKRESTO"
  ) {
    el.connectionHint.textContent =
      "Для этого заведения уже активна другая POS-интеграция. Сначала отключите её в разделе интеграций.";
  }
  renderScope();
}

function departmentAllocationRows(mapping) {
  const allocations = Array.isArray(mapping?.allocations)
    ? mapping.allocations.filter(
        (item) => item?.department_id && item?.share_percent,
      )
    : [];
  if (allocations.length) return allocations;
  if (mapping?.department_id) {
    return [{ department_id: mapping.department_id, share_percent: 100 }];
  }
  return [{ department_id: "", share_percent: 100 }];
}

function renderDepartmentAllocationRow(row) {
  return `<div class="quickresto-allocation-row" data-department-allocation-row>
    <select data-department-allocation-target>${options(state.departments, row.department_id)}</select>
    <label class="quickresto-allocation-share"><input type="number" min="1" max="100" step="1" value="${esc(row.share_percent || "")}" data-department-allocation-share /><span>%</span></label>
    <button class="btn subtle" type="button" data-remove-department-allocation aria-label="Удалить долю">×</button>
  </div>`;
}

function renderMappings() {
  const payments = (state.mappings.payments || []).filter(
    (item) => item.is_available !== false && item.is_applicable !== false,
  );
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
          : `<select data-payment-external-id="${item.external_id}">${options(state.paymentMethods, item.payment_method_id)}</select>`
      }
    </div>`;
        })
        .join("")
    : `<div class="quickresto-empty">После выбора области импорта получите справочники QuickResto.</div>`;

  el.departmentMappings.innerHTML = departments.length
    ? departments
        .map((item) => {
          const sourcePositions = Array.isArray(item.source_position_names)
            ? item.source_position_names.filter(Boolean)
            : [];
          const sourceDetails = sourcePositions.length
            ? `<div class="muted small">Позиции: ${sourcePositions.map(esc).join(", ")}</div>`
            : "";
          if (item.resolved_by_kpi) {
            return `<div class="itemcard quickresto-mapping-row quickresto-mapping-row--kpi" data-department-external-id="${item.external_id}">
              <div><b>${esc(item.external_name)}</b><div class="muted small">QuickResto #${item.external_id}</div>${sourceDetails}</div>
              <div class="quickresto-kpi-route-status"><b>Учитывается как KPI</b><span>Выручка остаётся в общем итоге вне департаментов и процентных начислений.</span><a href="/owner-quickresto-kpi.html?venue_id=${encodeURIComponent(venueId)}">Изменить KPI-сопоставление</a></div>
            </div>`;
          }
          const rows = departmentAllocationRows(item)
            .map(renderDepartmentAllocationRow)
            .join("");
          return `<fieldset class="itemcard quickresto-department-allocation" data-department-external-id="${item.external_id}">
            <legend><b>${esc(item.external_name)}</b><small>QuickResto #${item.external_id}</small></legend>
            ${sourceDetails}
            <div class="muted small">Выберите один департамент (100%) или распределите выручку процентными долями.</div>
            <div class="quickresto-allocation-rows">${rows}</div>
            <button class="btn subtle" type="button" data-add-department-allocation>Добавить долю</button>
          </fieldset>`;
        })
        .join("")
    : `<div class="quickresto-empty">Сначала получите справочники QuickResto.</div>`;
  applyPermissions();
}

function collectPaymentMappingsPayload() {
  return (state.mappings.payments || [])
    .filter(
      (item) => item.is_available !== false && item.is_applicable !== false,
    )
    .map((item) => {
      const select = el.paymentMappings.querySelector(
        `[data-payment-external-id="${item.external_id}"]`,
      );
      const writeoff =
        String(item.operation_type || "").toLowerCase() === "writeoff";
      return {
        external_id: item.external_id,
        payment_method_id:
          writeoff || !select?.value ? null : Number(select.value),
        excluded_from_revenue: writeoff,
      };
    });
}

function collectDepartmentMappingsPayload() {
  let invalid = false;
  const departments = (state.mappings.departments || []).map((item) => {
    const group = el.departmentMappings.querySelector(
      `[data-department-external-id="${item.external_id}"]`,
    );
    if (item.resolved_by_kpi) {
      return {
        external_id: item.external_id,
        department_id: null,
        allocations: [],
      };
    }
    group?.removeAttribute("data-invalid");
    const rows = [
      ...(group?.querySelectorAll("[data-department-allocation-row]") || []),
    ];
    const allocations = rows.map((row) => ({
      department_id: Number(
        row.querySelector("[data-department-allocation-target]")?.value || 0,
      ),
      share_percent: Number(
        row.querySelector("[data-department-allocation-share]")?.value || 0,
      ),
    }));
    if (
      allocations.length === 1 &&
      allocations[0].department_id === 0
    ) {
      return {
        external_id: item.external_id,
        department_id: null,
        allocations: [],
      };
    }
    const departmentIds = allocations.map((row) => row.department_id);
    const valid =
      allocations.length > 0 &&
      allocations.every(
        (row) =>
          row.department_id > 0 &&
          row.share_percent >= 1 &&
          row.share_percent <= 100,
      ) &&
      new Set(departmentIds).size === departmentIds.length &&
      allocations.reduce((total, row) => total + row.share_percent, 0) === 100;
    if (!valid) {
      if (group) group.dataset.invalid = "true";
      invalid = true;
    }
    return allocations.length === 1 && allocations[0].share_percent === 100
      ? {
          external_id: item.external_id,
          department_id: allocations[0].department_id,
          allocations: [],
        }
      : { external_id: item.external_id, department_id: null, allocations };
  });
  if (invalid) {
    throw new Error(
      "Для каждой распределяемой группы выберите разные департаменты; сумма долей должна быть ровно 100%.",
    );
  }
  return departments;
}

async function refreshAxelioCatalogs() {
  const [paymentMethods, departments] = await Promise.all([
    getPaymentMethods(venueId, { includeArchived: false }),
    getDepartments(venueId, { includeArchived: false }),
  ]);
  state.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
  state.departments = Array.isArray(departments) ? departments : [];
}

async function load() {
  if (!venueId) {
    toast("Сначала выберите заведение", "err");
    return;
  }
  el.backToIntegrations.dataset.href = `/owner-integrations.html?venue_id=${encodeURIComponent(venueId)}`;
  el.openIssues.href = `/owner-integration-issues.html?venue_id=${encodeURIComponent(venueId)}&provider=quickresto`;
  el.openImportHistory.href = `/owner-quickresto-import-history.html?venue_id=${encodeURIComponent(venueId)}`;
  const [venue, integration] = await Promise.all([
    getVenueById(venueId),
    api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto`),
    refreshAxelioCatalogs(),
  ]);
  state.configured = !!integration.configured;
  state.connection = integration.connection;
  state.catalog = integration.catalog || emptyCatalog();
  state.canManage =
    integration.permissions?.can_manage ?? integration.can_manage ?? true;
  state.issueOpenCount = Number(integration.issues?.open_count || 0);
  state.activePosProvider =
    String(integration.active_pos_provider || "").toUpperCase() || null;
  state.venueNightShiftsEnabled = !!(
    integration.venue_night_shifts_enabled ??
    integration.connection?.venue_night_shifts_enabled ??
    venue?.night_shifts_enabled
  );
  state.mappings = integration.mappings || { payments: [], departments: [] };
  state.mappingReadiness =
    integration.mapping_readiness || state.mappingReadiness;
  state.importBatch = integration.import_batch || null;
  state.scopeAudit = integration.scope_audit || [];
  const venueName = venue?.name || `Заведение ${venueId}`;
  el.title.textContent = `QuickResto · ${venueName}`;
  el.venueTitle.textContent = venueName;
  el.issueOpenCount.textContent = String(state.issueOpenCount);
  el.issueSection.dataset.attention =
    state.issueOpenCount > 0 ? "true" : "false";
  renderConnection();
  renderMappings();
  renderScopeAudit();
  renderBatchProgress();
  if (batchIsActive()) startBatchPolling();
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
    if (!body.sync_from_date) {
      throw new Error("Укажите дату, начиная с которой импортировать смены.");
    }
    if (
      body.night_shift_split_enabled &&
      body.night_shift_start_hour <= body.business_day_cutoff_hour
    ) {
      throw new Error(
        "Начало ночной смены должно быть позже границы бизнес-дня.",
      );
    }
    const previousCloud = state.connection?.cloud;
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto`,
      { method: "PUT", body },
    );
    state.configured = true;
    state.connection = result.connection;
    state.activePosProvider =
      String(result.active_pos_provider || "").toUpperCase() || null;
    if (previousCloud && previousCloud !== result.connection?.cloud) {
      state.catalog = emptyCatalog();
      state.mappings = { payments: [], departments: [] };
    } else {
      state.catalog.scope_status =
        result.connection?.scope_status || state.catalog.scope_status;
      state.catalog.selected_external_venue_id =
        result.connection?.external_venue_id || null;
    }
    el.apiLogin.value = "";
    el.apiPassword.value = "";
    const catalogResult = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/catalog/refresh`,
      { method: "POST" },
    );
    state.catalog = catalogResult.catalog || state.catalog;
    if (state.connection)
      state.connection.scope_status = state.catalog.scope_status;
    renderConnection();
    renderMappings();
    toast("Подключение проверено. Выберите заведение и точки.", "ok");
    scrollToStep(el.scopeSection);
  } catch (error) {
    el.connectionHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.saveConnection, false);
    applyPermissions();
  }
});

el.refreshScopeCatalog?.addEventListener("click", async () => {
  if (!state.canManage || !state.configured) return;
  setBusy(el.refreshScopeCatalog, true, "Получаем список…");
  el.scopeHint.textContent = "";
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/catalog/refresh`,
      { method: "POST" },
    );
    state.catalog = result.catalog || emptyCatalog();
    if (state.connection)
      state.connection.scope_status = state.catalog.scope_status;
    renderScope();
    toast("Заведения, точки и склады получены", "ok");
  } catch (error) {
    el.scopeHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.refreshScopeCatalog, false);
    applyPermissions();
  }
});

el.externalVenue?.addEventListener("change", () => {
  renderScope({ preserveVenue: true });
});

el.salePlaceOptions?.addEventListener("change", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (target?.matches("[data-sale-place-id]")) renderScopeStores();
});

el.departmentMappings?.addEventListener("click", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const addButton = target?.closest("[data-add-department-allocation]");
  if (addButton) {
    const group = addButton.closest("[data-department-external-id]");
    const rows = group?.querySelector(".quickresto-allocation-rows");
    const existing = [
      ...(rows?.querySelectorAll("[data-department-allocation-row]") || []),
    ];
    if (existing.length === 1) {
      const share = existing[0].querySelector(
        "[data-department-allocation-share]",
      );
      if (share && Number(share.value) === 100) share.value = "50";
    }
    rows?.insertAdjacentHTML(
      "beforeend",
      renderDepartmentAllocationRow({
        department_id: "",
        share_percent: existing.length === 1 ? 50 : 1,
      }),
    );
    applyPermissions();
    el.mappingHint.textContent = "Есть несохранённые изменения.";
    return;
  }
  const removeButton = target?.closest("[data-remove-department-allocation]");
  if (!removeButton) return;
  const row = removeButton.closest("[data-department-allocation-row]");
  const rows = row?.parentElement;
  if ((rows?.querySelectorAll("[data-department-allocation-row]").length || 0) > 1) {
    row.remove();
  }
  const remaining = rows?.querySelectorAll(
    "[data-department-allocation-row]",
  );
  if (remaining?.length === 1) {
    const share = remaining[0].querySelector(
      "[data-department-allocation-share]",
    );
    if (share) share.value = "100";
  }
  el.mappingHint.textContent = "Есть несохранённые изменения.";
});

el.departmentMappings?.addEventListener("input", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  target?.closest("[data-department-external-id]")?.removeAttribute("data-invalid");
  el.mappingHint.textContent = "Есть несохранённые изменения.";
});

el.saveScope?.addEventListener("click", async () => {
  if (!state.canManage) return;
  const externalVenueId = Number(el.externalVenue.value || 0);
  const salePlaceIds = [...selectedScopeSalePlaceIds()];
  const storeIds = Array.from(
    el.storeOptions.querySelectorAll(
      'input[type="checkbox"][data-store-id]:checked',
    ),
  ).map((input) => Number(input.dataset.storeId));
  if (!externalVenueId || !salePlaceIds.length) {
    el.scopeHint.textContent =
      "Выберите заведение QuickResto и хотя бы одно место реализации.";
    return;
  }
  setBusy(el.saveScope, true, "Сохраняем область…");
  el.scopeHint.textContent = "";
  try {
    const result = await api(
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
    state.connection = result.connection || state.connection;
    state.catalog = result.catalog || state.catalog;
    state.mappings = result.mappings || state.mappings;
    state.mappingReadiness = result.mapping_readiness || state.mappingReadiness;
    state.scopeAudit = result.scope_audit || state.scopeAudit;
    renderScopeAudit();
    await refreshAxelioCatalogs();
    renderConnection();
    renderMappings();
    if (result.scope?.historical_reconciliation_required) {
      setBusy(el.saveScope, true, "Сверяем историю…");
      const scan = await api(
        `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/sync?full=true`,
        { method: "POST" },
      );
      const issueId = Number(
        scan.run?.summary?.historical_scope_mismatch_issue_id || 0,
      );
      if (issueId) {
        toast(
          "Новая область сохранена. Нужно проверить ранее импортированные смены.",
          "err",
        );
        location.href =
          `/owner-integration-issues.html?venue_id=${encodeURIComponent(venueId)}` +
          `&provider=quickresto&issue_id=${encodeURIComponent(issueId)}`;
        return;
      }
      await load();
      toast(
        scan.run?.status === "PARTIAL"
          ? "Область активирована, но импорт требует внимания"
          : "Новая область проверена и активирована",
        scan.run?.status === "PARTIAL" ? "err" : "ok",
      );
      scrollToStep(el.paymentSection);
    } else {
      toast("Область импорта сохранена", "ok");
      scrollToStep(el.paymentSection);
    }
  } catch (error) {
    el.scopeHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.saveScope, false);
    applyPermissions();
  }
});

el.discoverMappings?.addEventListener("click", async () => {
  if (!state.canManage || !scopeReady()) return;
  setBusy(el.discoverMappings, true, "Проверяем…");
  el.paymentMappingHint.textContent = "";
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/discover`,
      { method: "POST" },
    );
    state.catalog = result.catalog || state.catalog;
    state.mappings = result.mappings || state.mappings;
    state.mappingReadiness = result.mapping_readiness || state.mappingReadiness;
    state.scopeAudit = result.scope_audit || state.scopeAudit;
    renderScopeAudit();
    if (state.connection)
      state.connection.scope_status = state.catalog.scope_status;
    await refreshAxelioCatalogs();
    renderScope();
    renderMappings();
    const summary = result.summary || {};
    el.paymentMappingHint.textContent = `Доступных способов оплаты: ${summary.payment_types_available ?? summary.payment_types_seen ?? 0}; групп блюд: ${summary.departments_seen || 0}. Создано в Axelio: способов оплаты ${summary.payment_methods_created || 0}, департаментов ${summary.departments_created || 0}.`;
    toast("Соединение работает, справочники загружены", "ok");
  } catch (error) {
    el.paymentMappingHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.discoverMappings, false);
    applyPermissions();
  }
});

el.paymentMappings?.addEventListener("change", () => {
  el.paymentMappingHint.textContent = "Есть несохранённые изменения.";
});

el.savePaymentMappings?.addEventListener("click", async () => {
  if (!state.canManage || !scopeReady()) return;
  setBusy(el.savePaymentMappings, true, "Сохраняем оплаты…");
  el.paymentMappingHint.textContent = "";
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/mappings`,
      {
        method: "PUT",
        body: {
          payments: collectPaymentMappingsPayload(),
          departments: [],
        },
      },
    );
    state.mappings = result.mappings || state.mappings;
    state.mappingReadiness = result.mapping_readiness || state.mappingReadiness;
    renderMappings();
    renderMappingReadiness();
    el.paymentMappingHint.textContent = "Типы оплат сохранены.";
    toast("Типы оплат сохранены", "ok");
    scrollToStep(el.openKpiMappings.closest("section"));
  } catch (error) {
    el.paymentMappingHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.savePaymentMappings, false);
    applyPermissions();
  }
});

el.saveMappings?.addEventListener("click", async () => {
  if (!state.canManage || !scopeReady()) return;
  setBusy(el.saveMappings, true, "Сохраняем…");
  el.mappingHint.textContent = "";
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/mappings`,
      {
        method: "PUT",
        body: {
          payments: [],
          departments: collectDepartmentMappingsPayload(),
        },
      },
    );
    state.mappings = result.mappings || state.mappings;
    state.mappingReadiness = result.mapping_readiness || state.mappingReadiness;
    state.scopeAudit = result.scope_audit || state.scopeAudit;
    renderScopeAudit();
    renderMappings();
    el.mappingHint.textContent = "Группы блюд сохранены.";
    toast("Группы блюд сохранены", "ok");
    scrollToStep(el.importSection);
  } catch (error) {
    el.mappingHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.saveMappings, false);
    applyPermissions();
  }
});

async function runImport({ full = false, button = el.runSync } = {}) {
  if (!state.canManage || !requiredMappingsReady()) return;
  setBusy(button, true, full ? "Создаём очередь…" : "Ставим в очередь…");
  el.importHint.textContent = "";
  try {
    const suffix = full ? "?full=true" : "";
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/sync${suffix}`,
      { method: "POST" },
    );
    if (result.queued && result.batch) {
      state.importBatch = result.batch;
      if (state.connection) state.connection.last_sync_status = "QUEUED";
      renderBatchProgress();
      applyPermissions();
      startBatchPolling();
      el.importHint.textContent = `Создано месячных запусков: ${Number(result.batch.total_periods || 1)}. Обработка начнётся фоновым worker и продолжится без открытой страницы.`;
      toast(
        full
          ? "Полная сверка поставлена в очередь"
          : "Импорт поставлен в очередь",
        "ok",
      );
      return;
    }
    const run = result.run || {};
    el.importHint.textContent =
      run.status === "PARTIAL"
        ? "Импорт завершён частично. Откройте центр проблем импорта."
        : full
          ? "Полная история выбранного заведения сверена с QuickResto."
          : selectedImportMode() === "DRAFT"
            ? "Закрытые смены импортированы в черновики отчётов."
            : "Закрытые смены импортированы и отчёты автоматически закрыты.";
    toast(
      run.status === "PARTIAL"
        ? "Импорт требует внимания"
        : full
          ? "Полная сверка завершена"
          : "Импорт завершён",
      run.status === "PARTIAL" ? "err" : "ok",
    );
    await load();
  } catch (error) {
    el.importHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
    applyPermissions();
  }
}

el.retryBatch?.addEventListener("click", async () => {
  const batchId = Number(state.importBatch?.id || 0);
  if (!batchId || !state.canManage) return;
  setBusy(el.retryBatch, true, "Возобновляем…");
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/import-batches/${encodeURIComponent(batchId)}/retry`,
      { method: "POST" },
    );
    state.importBatch = result.batch || state.importBatch;
    renderBatchProgress();
    applyPermissions();
    startBatchPolling();
    toast("Импорт продолжится с месяца ошибки", "ok");
  } catch (error) {
    el.importHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.retryBatch, false);
    applyPermissions();
  }
});

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

if (params.get("issues") === "1" && venueId) {
  location.replace(
    `/owner-integration-issues.html?venue_id=${encodeURIComponent(venueId)}&provider=quickresto`,
  );
} else {
  try {
    await load();
  } catch (error) {
    el.connectionHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  }
}

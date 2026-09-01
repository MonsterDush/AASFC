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
  "scopeSection",
  "scopeStatus",
  "refreshScopeCatalog",
  "scopeContent",
  "externalVenue",
  "salePlaceOptions",
  "storeOptions",
  "saveScope",
  "scopeHint",
  "issueSection",
  "issueOpenCount",
  "openIssues",
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
  runs: [],
  venueNightShiftsEnabled: false,
  canManage: true,
  issueOpenCount: 0,
  activePosProvider: null,
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
    return sources.length === 0 || sources.some((id) => selectedSaleIds.has(id));
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
    .map(
      (store) => `<label class="quickresto-scope-choice">
        <input type="checkbox" data-store-id="${store.external_id}"${store.is_selected ? " checked" : ""}${state.canManage ? "" : " disabled"} />
        <span><b>${esc(store.external_name)}</b><small>QuickResto #${store.external_id}</small></span>
      </label>`,
    )
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
              <input type="checkbox" data-sale-place-id="${place.external_id}"${place.is_selected ? " checked" : ""}${state.canManage ? "" : " disabled"} />
              <span><b>${esc(place.external_name)}</b><small>Место реализации #${place.external_id}</small></span>
            </label>`,
          )
          .join("")
      : `<div class="quickresto-empty">У выбранного заведения не найдены места реализации. Проверьте их в QuickResto и обновите список.</div>`;
  renderScopeStores();

  if (!state.configured) {
    el.scopeHint.textContent = "Сначала сохраните подключение к облаку QuickResto.";
  } else if (!venues.length) {
    el.scopeHint.textContent =
      "Получите список заведений, точек и складов из QuickResto.";
  } else if (status === "STALE") {
    el.scopeHint.textContent =
      "Справочники QuickResto изменились. Проверьте выбор и сохраните область импорта заново.";
  } else if (status === "READY") {
    el.scopeHint.textContent = `Импорт ограничен заведением «${state.connection?.external_venue_name || "QuickResto"}».`;
  } else {
    el.scopeHint.textContent =
      "Выберите конкретное заведение и хотя бы одно место реализации.";
  }
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
    el.externalVenue,
  ];
  editableFields.forEach((field) => {
    if (field) field.disabled = !state.canManage;
  });
  const providerConflict =
    state.activePosProvider && state.activePosProvider !== "QUICKRESTO";
  el.isActive.disabled = !state.canManage || !!providerConflict;
  el.connectionActions.hidden = !state.canManage;
  el.saveMappings.hidden = !state.canManage;
  el.refreshScopeCatalog.hidden = !state.canManage;
  el.saveScope.hidden = !state.canManage;
  el.readOnlyHint.hidden = state.canManage;
  el.paymentMappings.querySelectorAll("select").forEach((field) => {
    field.disabled = !state.canManage;
  });
  el.departmentMappings.querySelectorAll("select").forEach((field) => {
    field.disabled = !state.canManage;
  });
  el.scopeContent.querySelectorAll("input, select").forEach((field) => {
    field.disabled = !state.canManage;
  });
  el.refreshScopeCatalog.disabled = !state.configured;
  el.saveScope.disabled =
    !state.configured || !(state.catalog?.venues || []).length;
  const ready = scopeReady();
  el.discoverMappings.disabled = !ready;
  el.runSync.disabled = !ready;
  el.runFullSync.disabled = !ready;
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
        .map(
          (item) => `<div class="itemcard quickresto-mapping-row">
      <div><b>${esc(item.external_name)}</b><div class="muted small">QuickResto #${item.external_id}</div></div>
      <select data-department-external-id="${item.external_id}">${options(state.departments, item.department_id)}</select>
    </div>`,
        )
        .join("")
    : `<div class="quickresto-empty">Сначала получите справочники QuickResto.</div>`;
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
        <span>Смен в облаке: ${Number(summary.cloud_closed_shifts_seen ?? summary.shifts_seen ?? 0)}</span>
        <span>В области: ${Number(summary.shifts_in_scope ?? summary.shifts_seen ?? 0)}</span>
        <span>Создано отчётов: ${Number(summary.reports_created || 0)}</span>
      </div>
      ${run.error ? `<div class="quickresto-run-error">${esc(run.error)}</div>` : ""}
    </div>`;
        })
        .join("")
    : `<div class="quickresto-empty">Синхронизация ещё не запускалась.</div>`;
}

function collectMappingsPayload() {
  const payments = (state.mappings.payments || [])
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
  const departments = (state.mappings.departments || []).map((item) => {
    const select = el.departmentMappings.querySelector(
      `[data-department-external-id="${item.external_id}"]`,
    );
    return {
      external_id: item.external_id,
      department_id: select?.value ? Number(select.value) : null,
    };
  });
  return { payments, departments };
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
  state.activePosProvider = String(
    integration.active_pos_provider || "",
  ).toUpperCase() || null;
  state.venueNightShiftsEnabled = !!(
    integration.venue_night_shifts_enabled ??
    integration.connection?.venue_night_shifts_enabled ??
    venue?.night_shifts_enabled
  );
  state.mappings = integration.mappings || { payments: [], departments: [] };
  const venueName = venue?.name || `Заведение ${venueId}`;
  el.title.textContent = `QuickResto · ${venueName}`;
  el.venueTitle.textContent = venueName;
  el.issueOpenCount.textContent = String(state.issueOpenCount);
  el.issueSection.dataset.attention = state.issueOpenCount > 0 ? "true" : "false";
  state.runs = state.configured
    ? await api(
        `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/runs?limit=10`,
      )
    : [];
  renderConnection();
  renderMappings();
  renderRuns();
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
    const previousCloud = state.connection?.cloud;
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto`,
      { method: "PUT", body },
    );
    state.configured = true;
    state.connection = result.connection;
    state.activePosProvider = String(
      result.active_pos_provider || "",
    ).toUpperCase() || null;
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
    renderConnection();
    renderMappings();
    toast("Подключение сохранено", "ok");
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
    if (state.connection) state.connection.scope_status = state.catalog.scope_status;
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
    await refreshAxelioCatalogs();
    renderConnection();
    renderMappings();
    toast("Область импорта сохранена", "ok");
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
  el.connectionHint.textContent = "";
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/discover`,
      { method: "POST" },
    );
    state.catalog = result.catalog || state.catalog;
    state.mappings = result.mappings || state.mappings;
    if (state.connection) state.connection.scope_status = state.catalog.scope_status;
    await refreshAxelioCatalogs();
    renderScope();
    renderMappings();
    const summary = result.summary || {};
    el.connectionHint.textContent = `Доступных способов оплаты: ${summary.payment_types_available ?? summary.payment_types_seen ?? 0}; групп блюд: ${summary.departments_seen || 0}. Создано в Axelio: способов оплаты ${summary.payment_methods_created || 0}, департаментов ${summary.departments_created || 0}.`;
    toast("Соединение работает, справочники загружены", "ok");
  } catch (error) {
    el.connectionHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.discoverMappings, false);
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
      { method: "PUT", body: collectMappingsPayload() },
    );
    state.mappings = result.mappings || state.mappings;
    renderMappings();
    el.mappingHint.textContent = "Сопоставления сохранены.";
    toast("Сопоставления сохранены", "ok");
  } catch (error) {
    el.mappingHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.saveMappings, false);
    applyPermissions();
  }
});

async function runImport({ full = false, button = el.runSync } = {}) {
  if (!state.canManage || !scopeReady()) return;
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
    el.connectionHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(button, false);
    applyPermissions();
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

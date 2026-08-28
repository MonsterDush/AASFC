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

const el = Object.fromEntries([
  "title", "venueTitle", "backToIntegrations", "connectionStatus", "syncStatus", "cloud", "apiLogin",
  "apiPassword", "syncFromDate", "cutoffHour", "isActive", "autoSync", "saveConnection",
  "discoverMappings", "runSync", "connectionHint", "paymentMappings", "departmentMappings",
  "saveMappings", "mappingHint", "runHistory", "reportImportClosed", "reportImportDraft", "importModeHint",
].map((id) => [id, document.getElementById(id)]));

const state = {
  configured: false,
  connection: null,
  mappings: { payments: [], departments: [] },
  paymentMethods: [],
  departments: [],
  runs: [],
};

const esc = (value) => String(value ?? "")
  .replace(/&/g, "&amp;")
  .replace(/</g, "&lt;")
  .replace(/>/g, "&gt;")
  .replace(/"/g, "&quot;")
  .replace(/'/g, "&#39;");

function errorMessage(error) {
  return String(error?.data?.detail || error?.message || "Не удалось выполнить действие");
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
    ...items.map((item) => `<option value="${item.id}"${String(item.id) === String(selectedId || "") ? " selected" : ""}>${esc(item.title)}</option>`),
  ].join("");
}

function renderConnection() {
  const connection = state.connection || {};
  el.cloud.value = connection.cloud || "";
  el.syncFromDate.value = connection.sync_from_date || "";
  el.cutoffHour.value = String(connection.business_day_cutoff_hour ?? 0);
  el.isActive.checked = connection.is_active !== false;
  el.autoSync.checked = !!connection.auto_sync_enabled;
  const importMode = String(connection.report_import_mode || "CLOSED").toUpperCase();
  el.reportImportClosed.checked = importMode === "CLOSED";
  el.reportImportDraft.checked = importMode === "DRAFT";
  renderImportModeHint();
  el.connectionStatus.textContent = state.configured
    ? `Подключено к ${connection.cloud}.quickresto.ru · учетные данные сохранены зашифрованно`
    : "Укажи облако, API-логин и пароль QuickResto.";
  const status = String(connection.last_sync_status || "NEVER").toUpperCase();
  el.syncStatus.textContent = status;
  el.syncStatus.dataset.status = status;
  if (connection.last_sync_error) el.connectionHint.textContent = connection.last_sync_error;
}

function selectedImportMode() {
  return el.reportImportDraft.checked ? "DRAFT" : "CLOSED";
}

function renderImportModeHint() {
  el.importModeHint.textContent = selectedImportMode() === "DRAFT"
    ? "Новые импортированные отчёты останутся в статусе «Черновик». Уже закрытые отчёты не переоткроются."
    : "Новые импортированные отчёты будут закрыты автоматически и запустят обычные финансовые расчёты.";
}

function renderMappings() {
  const payments = state.mappings.payments || [];
  const departments = state.mappings.departments || [];
  el.paymentMappings.innerHTML = payments.length ? payments.map((item) => {
    const writeoff = String(item.operation_type || "").toLowerCase() === "writeoff";
    return `<div class="itemcard quickresto-mapping-row">
      <div><b>${esc(item.external_name)}</b><div class="muted small">QuickResto #${item.external_id} · ${esc(item.operation_type || "—")}</div></div>
      ${writeoff
        ? `<div class="quickresto-excluded">Исключено из выручки</div>`
        : `<select data-payment-external-id="${item.external_id}">${options(state.paymentMethods, item.payment_method_id)}</select>`}
    </div>`;
  }).join("") : `<div class="quickresto-empty">Сначала получи справочники QuickResto.</div>`;

  el.departmentMappings.innerHTML = departments.length ? departments.map((item) => `
    <div class="itemcard quickresto-mapping-row">
      <div><b>${esc(item.external_name)}</b><div class="muted small">QuickResto #${item.external_id}</div></div>
      <select data-department-external-id="${item.external_id}">${options(state.departments, item.department_id)}</select>
    </div>
  `).join("") : `<div class="quickresto-empty">Сначала получи справочники QuickResto.</div>`;
}

function renderRuns() {
  el.runHistory.innerHTML = state.runs.length ? state.runs.map((run) => {
    const summary = run.summary || {};
    const time = run.started_at ? new Date(run.started_at).toLocaleString() : "—";
    return `<div class="itemcard quickresto-run-row">
      <div><b>${esc(run.status)}</b><div class="muted small">${esc(time)} · ${esc(run.trigger)}</div></div>
      <div class="quickresto-run-metrics">
        <span>Смен: ${Number(summary.shifts_seen || 0)}</span>
        <span>Создано: ${Number(summary.reports_created || 0)}</span>
        <span>Обновлено: ${Number(summary.reports_updated || 0)}</span>
      </div>
      ${run.error ? `<div class="quickresto-run-error">${esc(run.error)}</div>` : ""}
    </div>`;
  }).join("") : `<div class="quickresto-empty">Синхронизация еще не запускалась.</div>`;
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
  state.mappings = integration.mappings || { payments: [], departments: [] };
  state.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
  state.departments = Array.isArray(departments) ? departments : [];
  const venueName = venue?.name || `Заведение ${venueId}`;
  el.title.textContent = `QuickResto · ${venueName}`;
  el.venueTitle.textContent = venueName;
  state.runs = state.configured
    ? await api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto/runs?limit=10`)
    : [];
  renderConnection();
  renderMappings();
  renderRuns();
}

el.saveConnection?.addEventListener("click", async () => {
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
      sync_from_date: el.syncFromDate.value || null,
    };
    const result = await api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto`, {
      method: "PUT",
      body,
    });
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
  setBusy(el.discoverMappings, true, "Проверяем…");
  el.connectionHint.textContent = "";
  try {
    const result = await api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto/discover`, { method: "POST" });
    state.mappings = result.mappings;
    const [paymentMethods, departments] = await Promise.all([
      getPaymentMethods(venueId, { includeArchived: false }),
      getDepartments(venueId, { includeArchived: false }),
    ]);
    state.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
    state.departments = Array.isArray(departments) ? departments : [];
    renderMappings();
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
  setBusy(el.saveMappings, true, "Сохраняем…");
  el.mappingHint.textContent = "";
  try {
    const payments = (state.mappings.payments || []).map((item) => {
      const writeoff = String(item.operation_type || "").toLowerCase() === "writeoff";
      const selectEl = el.paymentMappings.querySelector(`[data-payment-external-id="${item.external_id}"]`);
      return {
        external_id: item.external_id,
        payment_method_id: writeoff || !selectEl?.value ? null : Number(selectEl.value),
        excluded_from_revenue: writeoff,
      };
    });
    const departments = (state.mappings.departments || []).map((item) => {
      const selectEl = el.departmentMappings.querySelector(`[data-department-external-id="${item.external_id}"]`);
      return {
        external_id: item.external_id,
        department_id: selectEl?.value ? Number(selectEl.value) : null,
      };
    });
    const result = await api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto/mappings`, {
      method: "PUT",
      body: { payments, departments },
    });
    state.mappings = result.mappings;
    renderMappings();
    el.mappingHint.textContent = "Сопоставления сохранены.";
    toast("Сопоставления сохранены", "ok");
  } catch (error) {
    el.mappingHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.saveMappings, false);
  }
});

el.runSync?.addEventListener("click", async () => {
  setBusy(el.runSync, true, "Импортируем…");
  el.connectionHint.textContent = "";
  try {
    const result = await api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto/sync`, { method: "POST" });
    const run = result.run || {};
    el.connectionHint.textContent = run.status === "PARTIAL"
      ? "Импорт завершен частично: проверь сопоставления или существующие отчеты."
      : selectedImportMode() === "DRAFT"
        ? "Закрытые смены импортированы в черновики отчётов."
        : "Закрытые смены импортированы и отчёты автоматически закрыты.";
    toast(run.status === "PARTIAL" ? "Импорт требует внимания" : "Импорт завершен", run.status === "PARTIAL" ? "err" : "ok");
    await load();
  } catch (error) {
    el.connectionHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.runSync, false);
  }
});

el.reportImportClosed?.addEventListener("change", renderImportModeHint);
el.reportImportDraft?.addEventListener("change", renderImportModeHint);

for (let hour = 0; hour < 24; hour += 1) {
  const option = document.createElement("option");
  option.value = String(hour);
  option.textContent = hour === 0 ? "00:00 — календарный день" : `${String(hour).padStart(2, "0")}:00`;
  el.cutoffHour.append(option);
}

try {
  await load();
} catch (error) {
  el.connectionHint.textContent = errorMessage(error);
  toast(errorMessage(error), "err");
}

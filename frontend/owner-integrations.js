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

const el = Object.fromEntries([
  "title", "venueTitle", "backToVenue", "quickrestoTab", "iikoTab", "quickrestoPanel", "iikoPanel",
  "quickrestoTabStatus", "quickrestoStatus", "quickrestoDescription", "configureQuickResto", "integrationHint",
  "openQuickRestoIssues", "quickrestoIssueCount", "iikoTabStatus", "iikoStatus", "iikoDescription",
  "iikoForm", "iikoApiLogin", "iikoOrganizationId", "iikoSalesEndpoint", "iikoEmployeesEndpoint", "iikoExtendedEndpoints",
  "iikoActive", "saveIiko", "probeIiko", "historicalIiko", "incrementalIiko", "iikoCapabilityHint",
  "iikoHistoryHint", "iikoReadMode",
  "iikoOperations", "iikoSalesFreshness", "iikoQuarantineHint", "iikoJobsHint",
].map((id) => [id, document.getElementById(id)]));

const P0_CAPABILITIES = ["VENUES", "TERMINALS", "EMPLOYEES", "PRODUCT_GROUPS", "PRODUCTS", "SALES"];
const CAPABILITY_NAMES = {
  VENUES: "заведения",
  TERMINALS: "кассы",
  EMPLOYEES: "сотрудники",
  PRODUCT_GROUPS: "группы",
  PRODUCTS: "позиции",
  SALES: "продажи",
};
const state = {
  canManageIiko: false,
  activeProvider: "",
  iiko: { configured: false, connection: null },
  operations: null,
};

function errorMessage(error) {
  const detail = error?.data?.detail;
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object") {
    const missing = Array.isArray(detail.missing) ? `: ${detail.missing.join(", ")}` : "";
    return `${detail.message || "Операция не выполнена"}${missing}`;
  }
  return String(error?.message || "Не удалось загрузить интеграции");
}

function selectProvider(provider, { focus = false } = {}) {
  const quickrestoSelected = provider !== "iiko";
  const pairs = [
    [el.quickrestoTab, el.quickrestoPanel, quickrestoSelected],
    [el.iikoTab, el.iikoPanel, !quickrestoSelected],
  ];
  for (const [tab, panel, selected] of pairs) {
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
    panel.hidden = !selected;
    panel.classList.toggle("hidden", !selected);
  }
  if (focus) (quickrestoSelected ? el.quickrestoTab : el.iikoTab).focus();
}

for (const tab of [el.quickrestoTab, el.iikoTab]) {
  tab.addEventListener("click", () => selectProvider(tab.dataset.provider));
  tab.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const provider = event.key === "ArrowLeft" || event.key === "Home" ? "quickresto" : "iiko";
    selectProvider(provider, { focus: true });
  });
}

function renderQuickResto(integration) {
  const canManage = integration.permissions?.can_manage !== false;
  el.configureQuickResto.textContent = canManage ? "Настроить QuickResto" : "Открыть QuickResto";
  if (!integration.configured) {
    el.quickrestoTabStatus.textContent = "Не подключено";
    el.quickrestoStatus.textContent = "Не подключено";
    el.quickrestoStatus.dataset.status = "EMPTY";
    return;
  }

  const openIssueCount = Number(integration.issues?.open_count || 0);
  el.quickrestoIssueCount.textContent = String(openIssueCount);
  el.openQuickRestoIssues.hidden = false;
  el.openQuickRestoIssues.classList.remove("hidden");
  el.openQuickRestoIssues.dataset.attention = String(openIssueCount > 0);

  const connection = integration.connection || {};
  const active = connection.is_active !== false;
  const syncStatus = String(connection.last_sync_status || "NEVER").toUpperCase();
  el.quickrestoTabStatus.textContent = active ? "Подключено" : "Приостановлено";
  el.quickrestoStatus.textContent = active ? "Подключено" : "Приостановлено";
  el.quickrestoStatus.dataset.status = active ? "ACTIVE" : "PAUSED";
  const mode = String(connection.report_import_mode || "CLOSED").toUpperCase() === "DRAFT"
    ? "оставлять отчёты черновиками"
    : "закрывать отчёты автоматически";
  el.quickrestoDescription.textContent = `${connection.cloud}.quickresto.ru · ${mode} · последний статус: ${syncStatus}`;
}

function capabilityStatus(connection, capability) {
  return String(connection?.capabilities?.[capability]?.status || "").toUpperCase();
}

function renderIiko() {
  const connection = state.iiko.connection || {};
  const configured = state.iiko.configured;
  const active = state.activeProvider === "IIKO";
  const blockedByQuickResto = state.activeProvider === "QUICKRESTO";
  const status = String(connection.status || "").toUpperCase();
  const statusLabel = !configured
    ? "Не подключено"
    : active && status === "ACTIVE"
      ? "Подключено"
      : active
        ? "Требует проверки"
        : "Приостановлено";
  el.iikoTabStatus.textContent = statusLabel;
  el.iikoStatus.textContent = statusLabel;
  el.iikoStatus.dataset.status = active && status === "ACTIVE" ? "ACTIVE" : configured ? "PAUSED" : "EMPTY";

  if (connection.external_organization_id) el.iikoOrganizationId.value = connection.external_organization_id;
  el.iikoApiLogin.placeholder = configured
    ? "Сохранено · оставьте пустым без изменений"
    : "Вставьте новый API Login";
  el.iikoActive.checked = active;
  el.iikoActive.disabled = !state.canManageIiko || blockedByQuickResto;
  if (blockedByQuickResto) {
    el.iikoDescription.textContent =
      "Сейчас активна QuickResto. Данные iiko можно сохранить, но для активации сначала отключите QuickResto.";
  } else if (active) {
    el.iikoDescription.textContent = "iiko выбрана активной POS-интеграцией этого заведения.";
  } else {
    el.iikoDescription.textContent = "Подключение справочников и истории продаж через API iiko.";
  }

  const missing = P0_CAPABILITIES.filter((capability) => capabilityStatus(connection, capability) !== "AVAILABLE");
  const available = P0_CAPABILITIES.filter((capability) => capabilityStatus(connection, capability) === "AVAILABLE");
  if (!configured) {
    el.iikoCapabilityHint.textContent = "Сначала сохраните и проверьте подключение.";
  } else if (!Object.keys(connection.capabilities || {}).length) {
    el.iikoCapabilityHint.textContent = "Подключение сохранено · запустите проверку возможностей API.";
  } else if (!missing.length) {
    el.iikoCapabilityHint.textContent = "Все данные P0 доступны · исторический импорт разрешён.";
  } else {
    const names = missing.map((item) => CAPABILITY_NAMES[item] || item).join(", ");
    el.iikoCapabilityHint.textContent = `Недоступны: ${names}. Импорт не будет запущен частично.`;
  }

  const historyLabels = {
    NOT_STARTED: "Не запускался",
    RUNNING: "Выполняется",
    PARTIAL: "Завершён частично",
    COMPLETED: "Завершён",
    FAILED: "Ошибка",
  };
  const historyStatus = String(connection.historical_sync_status || "NOT_STARTED").toUpperCase();
  const coverage = connection.coverage_start && connection.coverage_end
    ? ` · ${connection.coverage_start} — ${connection.coverage_end}`
    : "";
  el.iikoHistoryHint.textContent = `${historyLabels[historyStatus] || historyStatus}${coverage}`;
  el.iikoReadMode.textContent = String(connection.read_mode || "LEGACY").toUpperCase() === "CANONICAL"
    ? "Canonical · после успешной сверки"
    : "Legacy · текущая логика Axelio";

  const canOperate = state.canManageIiko && configured;
  el.saveIiko.disabled = !state.canManageIiko;
  el.probeIiko.disabled = !canOperate;
  el.historicalIiko.disabled = !canOperate || !active || missing.length > 0;
  el.incrementalIiko.disabled = !canOperate || !active || !available.includes("SALES");

  el.iikoOperations.hidden = !configured;
  if (configured && state.operations) {
    const sales = state.operations.freshness?.SALES || {};
    const freshnessLabels = {
      FRESH: "Данные актуальны",
      STALE: "Данные устарели",
      UNKNOWN: "Нет успешной синхронизации",
      UNAVAILABLE: "Недоступно через API",
    };
    const observedAt = sales.data_updated_at ? new Date(sales.data_updated_at).toLocaleString() : "";
    el.iikoSalesFreshness.textContent = `${freshnessLabels[sales.status] || sales.status || "Нет данных"}${observedAt ? ` · ${observedAt}` : ""}`;
    const quarantineCount = (state.operations.quarantine || []).reduce((sum, item) => sum + Number(item.count || 0), 0);
    el.iikoQuarantineHint.textContent = quarantineCount ? `Требуют проверки: ${quarantineCount}` : "Нет ошибок";
    const latestJob = state.operations.jobs?.[0];
    el.iikoJobsHint.textContent = latestJob
      ? `${latestJob.job_type} · ${latestJob.status}`
      : "Нет запусков";
  }
}

async function loadIikoOperations() {
  if (!state.iiko.configured) {
    state.operations = null;
    return;
  }
  try {
    state.operations = await api(`/venues/${encodeURIComponent(venueId)}/integrations/iiko/operations`);
  } catch {
    state.operations = null;
  }
}

async function load() {
  if (!venueId) throw new Error("Сначала выбери заведение");
  el.backToVenue.dataset.href = `/app-venue.html?venue_id=${encodeURIComponent(venueId)}`;
  el.configureQuickResto.href = `/owner-quickresto.html?venue_id=${encodeURIComponent(venueId)}`;
  el.openQuickRestoIssues.href = `/owner-integration-issues.html?venue_id=${encodeURIComponent(venueId)}&provider=quickresto`;
  const [venue, quickresto, iiko] = await Promise.all([
    getVenueById(venueId),
    api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto`),
    api(`/venues/${encodeURIComponent(venueId)}/integrations/iiko`),
  ]);
  const venueName = venue?.name || `Заведение ${venueId}`;
  el.title.textContent = `Интеграции · ${venueName}`;
  el.venueTitle.textContent = venueName;
  state.activeProvider = String(iiko.active_pos_provider || quickresto.active_pos_provider || "").toUpperCase();
  state.canManageIiko = iiko.permissions?.can_manage !== false;
  state.iiko = { configured: Boolean(iiko.configured), connection: iiko.connection || null };
  await loadIikoOperations();
  renderQuickResto(quickresto);
  renderIiko();
  if (params.get("provider") === "iiko" || state.activeProvider === "IIKO") selectProvider("iiko");
}

function iikoPayload() {
  const payload = {
    organization_id: el.iikoOrganizationId.value.trim() || null,
    is_active: Boolean(el.iikoActive.checked),
  };
  const apiLogin = el.iikoApiLogin.value.trim();
  const salesEndpoint = el.iikoSalesEndpoint.value.trim();
  const employeesEndpoint = el.iikoEmployeesEndpoint.value.trim();
  const extendedEndpoints = el.iikoExtendedEndpoints.value.trim();
  if (apiLogin) payload.api_login = apiLogin;
  if (salesEndpoint) payload.sales_endpoint = salesEndpoint;
  if (employeesEndpoint) payload.employees_endpoint = employeesEndpoint;
  if (extendedEndpoints) {
    let parsed;
    try {
      parsed = JSON.parse(extendedEndpoints);
    } catch {
      throw new Error("Расширенные endpoints должны быть корректным JSON");
    }
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error("Расширенные endpoints должны быть JSON-объектом");
    }
    payload.extended_endpoints = parsed;
  }
  return payload;
}

async function withBusy(button, action) {
  const buttons = [el.saveIiko, el.probeIiko, el.historicalIiko, el.incrementalIiko];
  buttons.forEach((item) => { item.disabled = true; });
  button.setAttribute("aria-busy", "true");
  try {
    return await action();
  } finally {
    button.removeAttribute("aria-busy");
    renderIiko();
  }
}

el.iikoForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await withBusy(el.saveIiko, () => api(
      `/venues/${encodeURIComponent(venueId)}/integrations/iiko`,
      { method: "PUT", body: iikoPayload() },
    ));
    state.iiko = { configured: true, connection: result.connection };
    state.activeProvider = String(result.active_pos_provider || "").toUpperCase();
    el.iikoApiLogin.value = "";
    el.iikoExtendedEndpoints.value = "";
    await loadIikoOperations();
    renderIiko();
    toast("Настройки iiko сохранены", "ok");
  } catch (error) {
    toast(errorMessage(error), "err");
  }
});

el.probeIiko.addEventListener("click", async () => {
  try {
    const result = await withBusy(el.probeIiko, () => api(
      `/venues/${encodeURIComponent(venueId)}/integrations/iiko/probe`,
      { method: "POST" },
    ));
    state.iiko.connection = result.connection;
    await loadIikoOperations();
    renderIiko();
    toast(result.ok ? "Подключение iiko работает" : "iiko отклонила подключение", result.ok ? "ok" : "err");
  } catch (error) {
    toast(errorMessage(error), "err");
  }
});

el.historicalIiko.addEventListener("click", async () => {
  try {
    const result = await withBusy(el.historicalIiko, () => api(
      `/venues/${encodeURIComponent(venueId)}/integrations/iiko/sync/historical/enqueue`,
      { method: "POST", body: { months: 12 } },
    ));
    await loadIikoOperations();
    renderIiko();
    toast(`Исторический импорт iiko поставлен в очередь · #${result.job_id}`, "ok");
  } catch (error) {
    toast(errorMessage(error), "err");
  }
});

el.incrementalIiko.addEventListener("click", async () => {
  try {
    const result = await withBusy(el.incrementalIiko, () => api(
      `/venues/${encodeURIComponent(venueId)}/integrations/iiko/sync/incremental`,
      { method: "POST", timeoutMs: 10 * 60 * 1000 },
    ));
    state.iiko.connection = result.connection;
    await loadIikoOperations();
    renderIiko();
    toast("Данные iiko обновлены", "ok");
  } catch (error) {
    toast(errorMessage(error), "err");
  }
});

try {
  await load();
} catch (error) {
  el.integrationHint.textContent = errorMessage(error);
  toast(errorMessage(error), "err");
}

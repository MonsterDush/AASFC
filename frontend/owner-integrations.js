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
  "openQuickRestoIssues", "quickrestoIssueCount", "iikoDescription",
].map((id) => [id, document.getElementById(id)]));

function errorMessage(error) {
  return String(error?.data?.detail || error?.message || "Не удалось загрузить интеграции");
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

async function load() {
  if (!venueId) {
    throw new Error("Сначала выбери заведение");
  }
  el.backToVenue.dataset.href = `/app-venue.html?venue_id=${encodeURIComponent(venueId)}`;
  el.configureQuickResto.href = `/owner-quickresto.html?venue_id=${encodeURIComponent(venueId)}`;
  el.openQuickRestoIssues.href = `/owner-integration-issues.html?venue_id=${encodeURIComponent(venueId)}&provider=quickresto`;
  const [venue, integration] = await Promise.all([
    getVenueById(venueId),
    api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto`),
  ]);
  const venueName = venue?.name || `Заведение ${venueId}`;
  el.title.textContent = `Интеграции · ${venueName}`;
  el.venueTitle.textContent = venueName;
  const canManage = integration.permissions?.can_manage !== false;
  const activeProvider = String(integration.active_pos_provider || "").toUpperCase();
  if (activeProvider === "QUICKRESTO") {
    el.iikoDescription.textContent =
      "Сейчас для заведения активна QuickResto. Перед будущим подключением iiko её потребуется отключить.";
  }
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

try {
  await load();
} catch (error) {
  el.integrationHint.textContent = errorMessage(error);
  toast(errorMessage(error), "err");
}

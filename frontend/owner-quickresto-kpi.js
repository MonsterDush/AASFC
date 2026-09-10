import {
  api,
  applyTelegramTheme,
  ensureLogin,
  getKpiMetrics,
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

const ids = [
  "title",
  "venueTitle",
  "backToQuickResto",
  "openKpiCatalog",
  "refreshProducts",
  "saveMappings",
  "productSearch",
  "mappingFilter",
  "groupFilter",
  "mappingSummary",
  "productList",
  "mappingHint",
  "openFullSync",
  "readOnlyHint",
];
const el = Object.fromEntries(
  ids.map((id) => [id, document.getElementById(id)]),
);

const state = {
  configured: false,
  canManage: false,
  products: [],
  kpis: [],
};
const MAX_VISIBLE_PRODUCTS = 250;

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

function groupKey(product) {
  return String(product.external_group_id || "ungrouped");
}

function groupTitle(product) {
  return (
    String(product.external_group_name || "").trim() ||
    (product.external_group_id
      ? `Группа QuickResto #${product.external_group_id}`
      : "Без группы QuickResto")
  );
}

function kpiOptions(selectedId) {
  return [
    '<option value="">— не увеличивать KPI —</option>',
    ...state.kpis.map(
      (item) =>
        `<option value="${item.id}"${String(item.id) === String(selectedId || "") ? " selected" : ""}>${esc(item.title)}</option>`,
    ),
  ].join("");
}

function renderGroupFilter() {
  const previous = el.groupFilter.value || "all";
  const groups = new Map();
  state.products.forEach((product) => {
    groups.set(groupKey(product), groupTitle(product));
  });
  el.groupFilter.innerHTML = [
    '<option value="all">Все группы</option>',
    ...[...groups.entries()]
      .sort((left, right) => left[1].localeCompare(right[1], "ru"))
      .map(
        ([key, title]) =>
          `<option value="${esc(key)}">${esc(title)}</option>`,
      ),
  ].join("");
  if ([...el.groupFilter.options].some((option) => option.value === previous)) {
    el.groupFilter.value = previous;
  }
}

function filteredProducts() {
  const query = String(el.productSearch.value || "").trim().toLocaleLowerCase();
  const filter = el.mappingFilter.value || "all";
  const group = el.groupFilter.value || "all";
  return state.products.filter((product) => {
    const mapped = !!product.kpi_metric_id;
    if (filter === "mapped" && !mapped) return false;
    if (filter === "unmapped" && mapped) return false;
    if (group !== "all" && groupKey(product) !== group) return false;
    if (!query) return true;
    return `${product.external_name} ${product.external_product_id} ${groupTitle(product)}`
      .toLocaleLowerCase()
      .includes(query);
  });
}

function renderSummary() {
  const mapped = state.products.filter((item) => item.kpi_metric_id).length;
  el.mappingSummary.textContent = state.products.length
    ? `Получено позиций: ${state.products.length} · сопоставлено с KPI: ${mapped}`
    : "Позиции ещё не получены из закрытых смен QuickResto.";
}

function renderProducts() {
  renderSummary();
  const filtered = filteredProducts();
  const visible = filtered.slice(0, MAX_VISIBLE_PRODUCTS);
  if (!state.products.length) {
    el.productList.innerHTML = `<div class="quickresto-kpi-empty">Позиции пока не найдены. Нажмите «Обновить позиции»: Axelio прочитает сохранённые зашифрованные смены, не меняя отчёты.</div>`;
    return;
  }
  if (!filtered.length) {
    el.productList.innerHTML = `<div class="quickresto-kpi-empty">По выбранным фильтрам позиций нет.</div>`;
    return;
  }
  el.productList.innerHTML = visible
    .map((product) => {
      const mapped = !!product.kpi_metric_id;
      const disabled = state.canManage ? "" : " disabled";
      return `<article class="itemcard quickresto-kpi-row" data-product-id="${product.external_product_id}" data-mapped="${mapped}">
        <div class="quickresto-kpi-row__source">
          <b>${esc(product.external_name)}</b>
          <span>${esc(groupTitle(product))} · QuickResto #${product.external_product_id}</span>
        </div>
        <label class="quickresto-kpi-row__metric"><span>Счётчик KPI Axelio</span><select data-kpi-metric${disabled}>${kpiOptions(product.kpi_metric_id)}</select></label>
        ${mapped ? '<div class="quickresto-kpi-row__exclude"><span><b>Вне департаментов и процентных начислений</b><small>Выручка останется в общем итоге отчёта и финансах, а количество увеличит выбранный KPI.</small></span></div>' : ""}
      </article>`;
    })
    .join("");
  el.mappingHint.textContent =
    filtered.length > visible.length
      ? `Показаны первые ${visible.length} из ${filtered.length}. Уточните поиск или группу.`
      : "";
}

function applyProducts(products) {
  state.products = (Array.isArray(products) ? products : []).map((item) => ({
    ...item,
    kpi_metric_id: item.kpi_metric_id || null,
    exclude_from_percentage_base:
      item.exclude_from_percentage_base !== false,
  }));
  renderGroupFilter();
  renderProducts();
}

async function refreshProducts() {
  if (!state.canManage) return;
  setBusy(el.refreshProducts, true, "Читаем смены…");
  el.mappingHint.textContent = "Получаем названия позиций из сохранённых смен…";
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/kpi-mappings/refresh`,
      { method: "POST" },
    );
    applyProducts(result.products);
    const count = Number(result.summary?.products_seen || 0);
    el.mappingHint.textContent = `Справочник обновлён: найдено ${count} позиций в сохранённых сменах.`;
    toast("Позиции QuickResto обновлены", "ok");
  } catch (error) {
    el.mappingHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.refreshProducts, false);
  }
}

async function saveMappings() {
  if (!state.canManage) return;
  setBusy(el.saveMappings, true, "Сохраняем…");
  el.mappingHint.textContent = "";
  try {
    const result = await api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/kpi-mappings`,
      {
        method: "PUT",
        body: {
          products: state.products.map((product) => ({
            external_product_id: Number(product.external_product_id),
            kpi_metric_id: product.kpi_metric_id
              ? Number(product.kpi_metric_id)
              : null,
            exclude_from_percentage_base: !!product.kpi_metric_id,
          })),
        },
      },
    );
    applyProducts(result.products);
    el.mappingHint.textContent =
      "Сопоставления сохранены. Новые смены получат KPI автоматически; для истории запустите полную сверку.";
    toast("Сопоставления KPI сохранены", "ok");
  } catch (error) {
    el.mappingHint.textContent = errorMessage(error);
    toast(errorMessage(error), "err");
  } finally {
    setBusy(el.saveMappings, false);
  }
}

async function loadPage() {
  if (!venueId) throw new Error("Сначала выберите заведение");
  const [venue, integration, mappingResult, kpis] = await Promise.all([
    getVenueById(venueId),
    api(`/venues/${encodeURIComponent(venueId)}/integrations/quickresto`),
    api(
      `/venues/${encodeURIComponent(venueId)}/integrations/quickresto/kpi-mappings`,
    ),
    getKpiMetrics(venueId, { includeArchived: false }),
  ]);
  if (!integration.configured)
    throw new Error("Сначала настройте подключение QuickResto");
  const venueName = venue?.name || `Заведение ${venueId}`;
  el.title.textContent = `KPI из QuickResto · ${venueName}`;
  el.venueTitle.textContent = venueName;
  const quickRestoUrl = `/owner-quickresto.html?venue_id=${encodeURIComponent(venueId)}`;
  el.backToQuickResto.dataset.href = quickRestoUrl;
  el.openFullSync.dataset.href = `${quickRestoUrl}#sync`;
  el.openKpiCatalog.href = `/owner-kpi.html?venue_id=${encodeURIComponent(venueId)}`;
  state.configured = true;
  state.canManage = mappingResult.permissions?.can_manage !== false;
  state.kpis = (Array.isArray(kpis) ? kpis : []).filter(
    (item) => String(item.unit || "").toUpperCase() === "QTY",
  );
  applyProducts(mappingResult.products);
  el.saveMappings.hidden = !state.canManage;
  el.refreshProducts.hidden = !state.canManage;
  el.readOnlyHint.hidden = state.canManage;
  if (!state.kpis.length) {
    el.mappingHint.textContent =
      "Сначала создайте хотя бы один активный KPI с единицей измерения «Количество».";
  }
}

el.productSearch?.addEventListener("input", renderProducts);
el.mappingFilter?.addEventListener("change", renderProducts);
el.groupFilter?.addEventListener("change", renderProducts);
el.productList?.addEventListener("change", (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const row = target?.closest("[data-product-id]");
  const product = state.products.find(
    (item) => String(item.external_product_id) === String(row?.dataset.productId),
  );
  if (!product) return;
  if (target.matches("[data-kpi-metric]")) {
    product.kpi_metric_id = target.value ? Number(target.value) : null;
    renderProducts();
  }
  el.mappingHint.textContent = "Есть несохранённые изменения.";
});
el.refreshProducts?.addEventListener("click", refreshProducts);
el.saveMappings?.addEventListener("click", saveMappings);

try {
  await loadPage();
} catch (error) {
  el.productList.innerHTML = `<div class="quickresto-kpi-empty" data-status="error">${esc(errorMessage(error))}</div>`;
  toast(errorMessage(error), "err");
}

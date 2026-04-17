import {
  applyTelegramTheme,
  ensureLogin,
  mountNav,
  mountCommonUI,
  toast,
  confirmModal,
  api,
  setActiveVenueId,
  getMe,
  getMyVenuePermissions,
  getVenueById,
  getVenueMembers,
  getDepartments,
  createDepartment,
  updateDepartment,
  getPaymentMethods,
  createPaymentMethod,
  updatePaymentMethod,
  getKpiMetrics,
  createKpiMetric,
  updateKpiMetric,
  getPayProfiles,
  getPayProfile,
  createPayProfile,
  updatePayProfile,
  deletePayProfile,
  createPayComponent,
  updatePayComponent,
  deletePayComponent,
  patchInviteDefaultPosition,
} from "/app.js";

import {
  roleUpper,
  isOwnerRole,
  isSysAdminRole,
  getBillingAccessMode,
  getSetupPhase,
  getSetupProgress,
  getSetupResumeStep,
  getSetupStatus,
  isSetupDone,
  isSetupPrepareDone,
} from "/permissions.js?v=20260409-setup2";
import { normalizePermissionTemplates, getPermissionTemplateById as getSharedPositionTemplateById, buildPermissionTemplateOptions, renderPermissionTemplateSummaryById, applyPermissionTemplateToCheckboxHost } from "/position-template-ui.js?v=20260409-setup-polish1";

applyTelegramTheme();
mountCommonUI("venue");
await ensureLogin({ silent: true });
await mountNav({ activeTab: "venue" });

const root = document.getElementById("root");

const UNIT_LABEL = {
  QTY: "Штуки",
  RUB: "Рубли",
  PERCENT: "Проценты",
  CUSTOM: "Другое",
};

const COMPONENT_LABELS = {
  SALARY_FIXED_MONTH: "Оклад за месяц",
  SALARY_HOURLY: "Почасовая ставка",
  SALARY_PER_SHIFT: "Фикс за смену",
  PERCENT_TOTAL_REVENUE: "% от общей выручки",
  PERCENT_DEPARTMENT_REVENUE: "% от выручки департамента",
  KPI_BONUS: "KPI-бонус",
};

function fmtMoneyMinor(minor) {
  const value = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";
  } catch {
    return value.toFixed(2) + " ₽";
  }
}

function fmtPercentBps(bps) {
  const value = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat("ru-RU", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + "%";
  } catch {
    return value.toFixed(2) + "%";
  }
}

function percentInputFromBps(bps) {
  if (bps == null || bps === "") return "";
  const value = Number(bps || 0) / 100;
  if (!Number.isFinite(value)) return "";
  return String(value).replace('.', ',');
}

function moneyInputFromMinor(minor) {
  if (minor == null || minor === "") return "";
  const value = Number(minor) / 100;
  if (!Number.isFinite(value)) return "";
  return String(value).replace(/\.0+$/, "");
}

function parseMoneyRubToMinor(value) {
  const normalized = String(value || "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!normalized) return null;
  const num = Number(normalized);
  if (!Number.isFinite(num) || num < 0) return null;
  return Math.round(num * 100);
}

function parsePercentInputToBps(value) {
  const normalized = String(value || "").trim().replace(",", ".");
  if (!normalized) return null;
  const num = Number(normalized);
  if (!Number.isFinite(num) || num < 0) return null;
  return Math.round(num * 100);
}

const STEP_CONTENT = {
  welcome: {
    title: "Приветствие и название",
    subtitle: "Подтверди текущее название или переименуй заведение до старта настройки.",
    what: "Это базовая карточка заведения, с которой начинается дальнейшая настройка.",
    where: "Название показывается в навигации, в списке заведений и в командных сценариях.",
    later: "Можно оставить как есть и вернуться к редактированию позже.",
    primaryLabel: "Открыть карточку заведения",
    primaryHref: (venueId) => `/app-venue.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  payment_methods: {
    title: "Способы оплат",
    subtitle: "Настрой, какие оплаты доступны в заведении и будут участвовать в закрытии смены.",
    what: "Это список способов оплаты: наличные, безналичные и любые твои дополнительные варианты.",
    where: "Используются в закрытии смены, выручке и месячной сводке.",
    later: "Лучше не откладывать, потому что это основа отчётов.",
    primaryLabel: "Открыть полную страницу",
    primaryHref: (venueId) => `/owner-payment-methods.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  departments: {
    title: "Департаменты",
    subtitle: "Определи направления выручки внутри заведения.",
    what: "Обычно это кальяны, бар, кухня и другие внутренние направления дохода.",
    where: "Используются в закрытии смены, аналитике и процентах в зарплатах.",
    later: "Лучше заполнить на старте, чтобы сразу вести корректную детализацию.",
    primaryLabel: "Открыть полную страницу",
    primaryHref: (venueId) => `/owner-departments.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  kpi: {
    title: "KPI и доп. продажи",
    subtitle: "Реши, нужны ли дополнительные показатели уже сейчас.",
    what: "Это счётчики и суммы, которые можно собирать при закрытии смены: допродажи, штуки, KPI.",
    where: "Используются в отчётах и KPI-бонусах в зарплатных профилях.",
    later: "Да, этот шаг можно спокойно отложить и вернуться позже.",
    primaryLabel: "Открыть полную страницу",
    primaryHref: (venueId) => `/owner-kpi.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  pay_profiles: {
    title: "Профили зарплат",
    subtitle: "Создай базовые профили начислений без привязки к конкретным сотрудникам.",
    what: "Профиль зарплаты — это набор правил, по которым потом считаются начисления.",
    where: "Используется в должностях, начислениях, ФОТ и сводке.",
    later: "Нежелательно откладывать, если хочешь быстро привязать должности к понятным правилам.",
    primaryLabel: "Открыть профили зарплаты",
    primaryHref: (venueId) => `/owner-pay-profiles.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  positions: {
    title: "Должности и права",
    subtitle: "Создай должности, привяжи к ним профиль зарплаты и стартовый набор прав.",
    what: "Это роли сотрудников внутри заведения: кто за что отвечает и что видит в приложении.",
    where: "Используется в приглашениях, графике, зарплатах и ограничении доступа.",
    later: "Лучше завершить до приглашения команды.",
    primaryLabel: "Открыть должности",
    primaryHref: (venueId) => `/positions.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  invites: {
    title: "Приглашение участников",
    subtitle: "Добавь команду и сразу назначь людям подходящие должности.",
    what: "Приглашения позволяют заранее подготовить состав команды ещё до принятия приглашения.",
    where: "Используется для запуска графика, отчётов и распределения ролей.",
    later: "Да, можно пригласить людей позже, если сначала настраиваешь всё один.",
    primaryLabel: "Открыть приглашения",
    primaryHref: (venueId) => `/invites.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  shift_intervals: {
    title: "Интервалы смен",
    subtitle: "Собери интервалы, из которых потом строится график и часть расчётов.",
    what: "Это типовые временные отрезки смен: утро, день, вечер и любые свои варианты.",
    where: "Используется в графике, закрытии смены и начислениях.",
    later: "Не стоит откладывать, если сразу планируешь работу команды.",
    primaryLabel: "Открыть интервалы",
    primaryHref: (venueId) => `/shift-intervals.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  expense_categories: {
    title: "Категории расходов",
    subtitle: "Разложи будущие траты по понятным категориям.",
    what: "Категории нужны для чистой структуры расходов и сводки по месяцам.",
    where: "Используется в расходах и месячной аналитике.",
    later: "Да, это уже дополнительная настройка.",
    primaryLabel: "Открыть категории расходов",
    primaryHref: (venueId) => `/owner-expense-categories.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  suppliers: {
    title: "Поставщики",
    subtitle: "Заведи контрагентов, чтобы расходные операции было удобнее оформлять.",
    what: "Это справочник поставщиков, который ускоряет занесение расходов.",
    where: "Используется в расходах и истории закупок.",
    later: "Да, можно добавить после базового запуска.",
    primaryLabel: "Открыть поставщиков",
    primaryHref: (venueId) => `/owner-suppliers.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
  recurring_expenses: {
    title: "Регулярные настройки",
    subtitle: "Подготовь регулярные расходы и повторяющиеся финансовые правила.",
    what: "Это автоматизация однотипных ежемесячных расходов и повторяющихся финансовых записей.",
    where: "Используется для регулярных расходов и дальнейшей сводки.",
    later: "Да, это уже этап полировки после базового запуска.",
    primaryLabel: "Открыть регулярные расходы",
    primaryHref: (venueId) => `/owner-recurring-expenses.html?venue_id=${encodeURIComponent(String(venueId))}`,
  },
};

const STATUS_LABELS = {
  AVAILABLE: "Доступно",
  COMPLETED: "Готово",
  SKIPPED: "Позже",
  REQUIRES_ATTENTION: "Проверить",
  LOCKED: "Недоступно",
};

const INLINE_STEP_KEYS = new Set(["welcome", "payment_methods", "departments", "kpi", "pay_profiles", "positions", "invites", "shift_intervals", "expense_categories", "suppliers", "recurring_expenses"]);

const CATALOG_CONFIG = {
  payment_methods: {
    title: "способ оплаты",
    titlePlural: "способы оплат",
    listLabel: "Настроенные способы оплат",
    emptyText: "Пока пусто. При первом открытии будут доступны базовые оплаты, а дальше можно добавить свои.",
    createCta: "+ Добавить способ оплаты",
    activeHint: "Участвует в закрытии смены",
    archivedHint: "Скрыт из списка оплат",
    load: async (venueId) => getPaymentMethods(venueId, { includeArchived: true }),
    create: async (venueId, payload) => createPaymentMethod(venueId, payload),
    update: async (venueId, itemId, payload) => updatePaymentMethod(venueId, itemId, payload),
    includeUnit: false,
    skippableInline: false,
  },
  departments: {
    title: "департамент",
    titlePlural: "департаменты",
    listLabel: "Настроенные департаменты",
    emptyText: "Пока нет ни одного департамента. Обычно начинают с кальянов, бара, кухни и прочего.",
    createCta: "+ Добавить департамент",
    activeHint: "Участвует в отчётах и сводке",
    archivedHint: "Скрыт из выбора",
    load: async (venueId) => getDepartments(venueId, { includeArchived: true }),
    create: async (venueId, payload) => createDepartment(venueId, payload),
    update: async (venueId, itemId, payload) => updateDepartment(venueId, itemId, payload),
    includeUnit: false,
    skippableInline: false,
  },
  kpi: {
    title: "KPI",
    titlePlural: "KPI",
    listLabel: "Настроенные KPI",
    emptyText: "Пока нет KPI. Этот шаг можно отложить, если сначала хочешь запустить базовые процессы без дополнительных показателей.",
    createCta: "+ Добавить KPI",
    activeHint: "Будет доступен в закрытии смены",
    archivedHint: "Скрыт из формы закрытия смены",
    load: async (venueId) => getKpiMetrics(venueId, { includeArchived: true }),
    create: async (venueId, payload) => createKpiMetric(venueId, payload),
    update: async (venueId, itemId, payload) => updateKpiMetric(venueId, itemId, payload),
    includeUnit: true,
    skippableInline: true,
    skipLabel: "KPI пока не нужны",
    skipConfirmTitle: "Отложить KPI?",
    skipConfirmText: "Этот шаг будет помечен как отложенный. К нему можно будет вернутьcя в любой момент.",
  },
  expense_categories: {
    title: "категорию",
    titlePlural: "категории расходов",
    listLabel: "Настроенные категории расходов",
    emptyText: "Пока нет категорий расходов. Можно добавить базовые категории сейчас или отложить шаг на потом.",
    createCta: "+ Добавить категорию",
    activeHint: "Доступна при создании расхода",
    archivedHint: "Скрыта из списка расходов",
    load: async (venueId) => api(`/venues/${encodeURIComponent(venueId)}/expense-categories?include_archived=true`),
    create: async (venueId, payload) => api(`/venues/${encodeURIComponent(venueId)}/expense-categories`, { method: "POST", body: payload }),
    update: async (venueId, itemId, payload) => api(`/venues/${encodeURIComponent(venueId)}/expense-categories/${encodeURIComponent(itemId)}`, { method: "PATCH", body: payload }),
    includeUnit: false,
    createTitle: "Новая категория расходов",
    editTitle: "Изменить категорию расходов",
    skippableInline: true,
    skipLabel: "Категории добавлю позже",
    skipConfirmTitle: "Отложить категории расходов?",
    skipConfirmText: "Шаг будет помечен как отложенный. Категории можно будет добавить позже без потери прогресса.",
  },
};

const state = {
  venueId: "",
  me: null,
  venue: null,
  perms: null,
  setup: null,
  selectedStepKey: "",
  selectedPhase: "PREPARE",
  accessError: "",
  inline: {
    payment_methods: { items: null, showArchived: false, editor: { mode: "create", id: null }, loading: false },
    departments: { items: null, showArchived: false, editor: { mode: "create", id: null }, loading: false },
    kpi: { items: null, showArchived: false, editor: { mode: "create", id: null }, loading: false },
    pay_profiles: { items: null, showInactive: false, editor: { mode: "create", id: null }, selectedProfileId: null, details: {}, componentEditor: { mode: "create", id: null }, loading: false },
    positions: { presets: null, editorId: null, loading: false },
    invites: { data: null, loading: false },
    shift_intervals: { items: null, showArchived: false, editor: { mode: "create", id: null }, loading: false },
    expense_categories: { items: null, showArchived: false, editor: { mode: "create", id: null }, loading: false },
    suppliers: { items: null, showArchived: false, editor: { mode: "create", id: null }, loading: false },
    recurring_expenses: { items: null, categories: null, suppliers: null, paymentMethods: null, showInactive: false, editor: { mode: "create", id: null }, loading: false },
  },
  permissionsCatalog: null,
  positionPermissionTemplates: null,
  viewMode: "overview",
};

const SETUP_DISMISS_PREFIX = "axelio.setup.dismissed.";
const STEP_DEPENDENCIES = {
  positions: ["pay_profiles"],
  invites: ["positions"],
};

function navTo(url) {
  if (!url) return;
  location.href = url;
}

function setupDismissKey() {
  return `${SETUP_DISMISS_PREFIX}${String(state.venueId || "")}`;
}

function dismissSetupBanner() {
  try { localStorage.setItem(setupDismissKey(), "1"); } catch {}
}

function clearDismissedSetupBanner() {
  try { localStorage.removeItem(setupDismissKey()); } catch {}
}

function russianSetupStatusLabel(value) {
  const code = String(value || "NOT_STARTED").toUpperCase();
  if (code === "NOT_STARTED") return "Не начата";
  if (code === "IN_PROGRESS") return "В процессе";
  if (code === "PREPARE_DONE") return "Базовая настройка завершена";
  if (code === "EXTRA_IN_PROGRESS") return "Дополнительная настройка";
  if (code === "DONE") return "Завершена";
  return value || "—";
}

function findStep(key) {
  return (state.setup?.steps || []).find((step) => String(step.key) === String(key)) || null;
}

function isStepResolved(stepOrKey) {
  const step = typeof stepOrKey === "string" ? findStep(stepOrKey) : stepOrKey;
  return !!(step && (step.completed || step.skipped || step.status === "COMPLETED" || step.status === "SKIPPED"));
}

function getStepUiInfo(step) {
  const deps = STEP_DEPENDENCIES[String(step?.key || "")] || [];
  const unmet = deps.map((key) => findStep(key)).filter((dep) => dep && !isStepResolved(dep));
  const locked = unmet.length > 0;
  const firstUnmet = unmet[0] || null;
  const lockedReason = firstUnmet ? `Сначала нужно пройти шаг «${firstUnmet.title}».` : "";
  const uiStatus = locked ? "LOCKED" : String(step?.status || "AVAILABLE").toUpperCase();
  return { locked, unmet, lockedReason, uiStatus };
}

function getStepSummaryText(step, ui = getStepUiInfo(step)) {
  if (!step) return "";
  if (ui.locked) return ui.lockedReason || "Этот шаг пока недоступен.";
  if (step.completed) return "Шаг завершён";
  if (step.skipped) return "Можно вернуться позже";
  if (step.requires_attention || String(step.status || "").toUpperCase() === "REQUIRES_ATTENTION") return "Нужно проверить настройки";
  if (step.data_ready) return "Можно переходить дальше";
  if (step.key === "welcome") return "Подтверди название заведения";
  if (step.key === "pay_profiles") return "Собери базовые профили начислений";
  if (step.key === "positions") return "Создай роли и права команды";
  if (step.key === "invites") return "Добавь команду и назначь должности";
  return "Открой шаг и настрой его";
}

function defaultPayComponentTitle(type) {
  const code = String(type || "SALARY_FIXED_MONTH").toUpperCase();
  return COMPONENT_LABELS[code] || "Компонент";
}

function payComponentValueLabel(item) {
  const type = String(item?.component_type || "").toUpperCase();
  if (type === "SALARY_FIXED_MONTH") return item?.amount_minor != null ? `${fmtMoneyMinor(item.amount_minor)} в месяц` : "Без суммы";
  if (type === "SALARY_HOURLY") return item?.rate_minor != null ? `${fmtMoneyMinor(item.rate_minor)} в час` : "Без ставки";
  if (type === "SALARY_PER_SHIFT") return item?.amount_minor != null ? `${fmtMoneyMinor(item.amount_minor)} за смену` : "Без суммы";
  if (type === "PERCENT_TOTAL_REVENUE") return item?.percent_bps != null ? `${fmtPercentBps(item.percent_bps)} от общей выручки` : "Без процента";
  if (type === "PERCENT_DEPARTMENT_REVENUE") {
    const dep = item?.department_title ? ` · ${item.department_title}` : "";
    return item?.percent_bps != null ? `${fmtPercentBps(item.percent_bps)} от департамента${dep}` : `Процент по департаменту${dep}`;
  }
  if (type === "KPI_BONUS") {
    const kpi = item?.kpi_metric_title ? ` · ${item.kpi_metric_title}` : "";
    const amount = item?.amount_minor != null ? ` · ${fmtMoneyMinor(item.amount_minor)}` : "";
    return `Бонус по KPI${kpi}${amount}`;
  }
  return "Компонент";
}

function payComponentTypeOptions(selected = "SALARY_FIXED_MONTH") {
  const value = String(selected || "SALARY_FIXED_MONTH").toUpperCase();
  return [
    ["SALARY_FIXED_MONTH", "Оклад за месяц"],
    ["SALARY_HOURLY", "Почасовая ставка"],
    ["SALARY_PER_SHIFT", "Фикс за смену"],
    ["PERCENT_TOTAL_REVENUE", "% от общей выручки"],
    ["PERCENT_DEPARTMENT_REVENUE", "% от выручки департамента"],
    ["KPI_BONUS", "KPI-бонус"],
  ].map(([code, title]) => `<option value="${code}" ${value === code ? "selected" : ""}>${title}</option>`).join("");
}

function buildSimpleOptions(items = [], selected = "", placeholder = "Не выбрано") {
  const value = String(selected || "");
  return [`<option value="">${esc(placeholder)}</option>`]
    .concat((Array.isArray(items) ? items : []).filter((item) => item?.is_active !== false).map((item) => `<option value="${esc(item.id)}" ${String(item.id) === value ? "selected" : ""}>${esc(item.title || item.name || `#${item.id}`)}</option>`))
    .join("");
}

function syncInlinePayComponentFields() {
  const type = String(document.getElementById('inlineComponentType')?.value || 'SALARY_FIXED_MONTH').toUpperCase();
  const amountRow = document.getElementById('inlineComponentAmountRow');
  const rateRow = document.getElementById('inlineComponentRateRow');
  const percentRow = document.getElementById('inlineComponentPercentRow');
  const depRow = document.getElementById('inlineComponentDepartmentRow');
  const kpiRow = document.getElementById('inlineComponentKpiRow');
  if (amountRow) amountRow.style.display = ['SALARY_FIXED_MONTH', 'SALARY_PER_SHIFT', 'KPI_BONUS'].includes(type) ? '' : 'none';
  if (rateRow) rateRow.style.display = type === 'SALARY_HOURLY' ? '' : 'none';
  if (percentRow) percentRow.style.display = ['PERCENT_TOTAL_REVENUE', 'PERCENT_DEPARTMENT_REVENUE'].includes(type) ? '' : 'none';
  if (depRow) depRow.style.display = type === 'PERCENT_DEPARTMENT_REVENUE' ? '' : 'none';
  if (kpiRow) kpiRow.style.display = type === 'KPI_BONUS' ? '' : 'none';
}

async function renameVenue(venueId, name) {
  const trimmed = String(name || "").trim();
  if (!trimmed) throw new Error("Введите название заведения");
  return await api(`/venues/${encodeURIComponent(venueId)}/setup/venue`, {
    method: "PATCH",
    body: { name: trimmed },
  });
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function slugifyCode(value, fallback = "item") {
  const map = { а:"a", б:"b", в:"v", г:"g", д:"d", е:"e", ё:"e", ж:"zh", з:"z", и:"i", й:"y", к:"k", л:"l", м:"m", н:"n", о:"o", п:"p", р:"r", с:"s", т:"t", у:"u", ф:"f", х:"h", ц:"ts", ч:"ch", ш:"sh", щ:"sch", ъ:"", ы:"y", ь:"", э:"e", ю:"yu", я:"ya" };
  return String(value || "")
    .trim()
    .toLowerCase()
    .split("")
    .map((ch) => (map[ch] !== undefined ? map[ch] : ch))
    .join("")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/_+/g, "_")
    .slice(0, 64) || fallback;
}

function ensureUniqueCode(baseCode, items = [], currentId = null) {
  const used = new Set((Array.isArray(items) ? items : [])
    .filter((it) => currentId == null || String(it?.id ?? "") !== String(currentId))
    .map((it) => String(it?.code || "").trim().toLowerCase())
    .filter(Boolean));
  let code = String(baseCode || "").trim().toLowerCase();
  if (!code) code = "item";
  if (!used.has(code)) return code;
  let idx = 2;
  while (used.has(`${code}_${idx}`)) idx += 1;
  return `${code}_${idx}`;
}



function todayIso() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function parseMoneyToMinor(value) {
  const normalized = String(value ?? "").trim().replace(/\s+/g, "").replace(",", ".");
  if (!normalized) return 0;
  if (!/^\d+(?:\.\d{1,2})?$/.test(normalized)) throw new Error("Введите сумму в формате 1234.56");
  return Math.round(Number(normalized) * 100);
}

function minorToMoneyInput(minor) {
  if (minor == null || minor === "") return "";
  return (Number(minor || 0) / 100).toFixed(2);
}

function buildSelectOptions(items = [], current = "", placeholder = "—") {
  const currentValue = String(current ?? "");
  return [`<option value="">${esc(placeholder)}</option>`]
    .concat((Array.isArray(items) ? items : []).map((item) => `<option value="${esc(item.id)}" ${String(item.id) === currentValue ? "selected" : ""}>${esc(item.title || `#${item.id}`)}</option>`))
    .join("");
}

function recurringModeLabel(value) {
  return String(value || "FIXED").toUpperCase() === "PERCENT" ? "Процент" : "Фикс";
}

function buildBasisPaymentMethodCheckboxes(items = [], selectedIds = []) {
  const selected = new Set((selectedIds || []).map((x) => String(x)));
  if (!Array.isArray(items) || !items.length) return `<div class="muted">Нет доступных типов оплат.</div>`;
  return items.map((pm) => `
    <label class="checkline checkline--block">
      <input type="checkbox" name="recurringBasisPaymentMethod" value="${esc(pm.id)}" ${selected.has(String(pm.id)) ? "checked" : ""} />
      <span class="checkline__text">${esc(pm.title)}</span>
    </label>
  `).join("");
}

function fmtDateTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function roleLabel(value) {
  const code = String(value || "").toUpperCase();
  if (code === "OWNER") return "Владелец";
  if (code === "STAFF") return "Сотрудник";
  return value || "—";
}

function memberDisplayName(member) {
  if (!member) return "—";
  return String(member.display_name || member.short_name || member.full_name || member.tg_username || member.phone || member.user_id || "—");
}

function buildDefaultPermissionsCatalog() {
  return [
    {
      key: "reports",
      title: "Отчёты и финансы",
      hint: "Закрытие смены, финансы и сводка",
      items: [
        { code: "SHIFT_REPORT_VIEW", title: "Отчёты: просмотр" },
        { code: "SHIFT_REPORT_CLOSE", title: "Отчёты: закрытие" },
        { code: "SHIFT_REPORT_EDIT", title: "Отчёты: редактирование" },
        { code: "MONTHLY_SUMMARY_VIEW", title: "Сводка: просмотр" },
        { code: "PAYROLL_VIEW", title: "Начисления: просмотр" },
      ],
    },
    {
      key: "shifts",
      title: "Смены",
      hint: "График и управление сменами",
      items: [
        { code: "SHIFTS_VIEW", title: "График: просмотр" },
        { code: "SHIFTS_MANAGE", title: "График: управление" },
      ],
    },
    {
      key: "staff",
      title: "Команда",
      hint: "Сотрудники, должности и права",
      items: [
        { code: "STAFF_VIEW", title: "Сотрудники: просмотр" },
        { code: "STAFF_MANAGE", title: "Сотрудники: управление" },
        { code: "POSITIONS_VIEW", title: "Должности: просмотр" },
        { code: "POSITIONS_MANAGE", title: "Должности: управление" },
        { code: "POSITION_PERMISSIONS_MANAGE", title: "Права должностей" },
        { code: "POSITIONS_ASSIGN", title: "Назначение должностей" },
      ],
    },
    {
      key: "catalogs",
      title: "Справочники",
      hint: "Департаменты, оплаты и KPI",
      items: [
        { code: "DEPARTMENTS_VIEW", title: "Департаменты: просмотр" },
        { code: "DEPARTMENTS_CREATE", title: "Департаменты: создание" },
        { code: "DEPARTMENTS_EDIT", title: "Департаменты: редактирование" },
        { code: "PAYMENT_METHODS_VIEW", title: "Оплаты: просмотр" },
        { code: "PAYMENT_METHODS_CREATE", title: "Оплаты: создание" },
        { code: "PAYMENT_METHODS_EDIT", title: "Оплаты: редактирование" },
        { code: "KPI_METRICS_VIEW", title: "KPI: просмотр" },
        { code: "KPI_METRICS_CREATE", title: "KPI: создание" },
        { code: "KPI_METRICS_EDIT", title: "KPI: редактирование" },
      ],
    },
    {
      key: "venue",
      title: "Заведение",
      hint: "Карточка, настройки и расходы",
      items: [
        { code: "VENUE_VIEW", title: "Открывать заведение" },
        { code: "VENUE_SETTINGS_EDIT", title: "Настройки заведения" },
        { code: "EXPENSES_VIEW", title: "Расходы: просмотр" },
        { code: "EXPENSES_CREATE", title: "Расходы: создание" },
      ],
    },
  ];
}

const PERM_GROUP_META = {
  Reports: { key: "reports", title: "Отчёты и финансы", hint: "Закрытие смены, финансы и сводка" },
  Adjustments: { key: "adjustments", title: "Штрафы и споры", hint: "Штрафы, списания и споры" },
  Expenses: { key: "expenses", title: "Расходы", hint: "Расходы и категории" },
  Shifts: { key: "shifts", title: "Смены", hint: "График и смены" },
  Staff: { key: "staff", title: "Команда", hint: "Сотрудники и должности" },
  Positions: { key: "positions", title: "Должности", hint: "Должности и права" },
  Venue: { key: "venue", title: "Заведение", hint: "Карточка и настройки" },
  Catalogs: { key: "catalogs", title: "Справочники", hint: "Департаменты, оплаты и KPI" },
};

function normalizePermissionCatalog(items = []) {
  const groups = [];
  const byKey = new Map();
  for (const raw of Array.isArray(items) ? items : []) {
    const code = String(raw?.code || "").trim().toUpperCase();
    if (!code) continue;
    const sourceGroup = String(raw?.group || "Other").trim() || "Other";
    const meta = PERM_GROUP_META[sourceGroup] || {
      key: sourceGroup.toLowerCase().replace(/[^a-z0-9]+/g, "-") || "other",
      title: sourceGroup,
      hint: "",
    };
    let group = byKey.get(meta.key);
    if (!group) {
      group = { key: meta.key, title: meta.title, hint: meta.hint, items: [] };
      byKey.set(meta.key, group);
      groups.push(group);
    }
    group.items.push({
      code,
      title: String(raw?.title || raw?.description || code).trim(),
      description: String(raw?.description || "").trim(),
    });
  }
  groups.forEach((group) => group.items.sort((a, b) => a.title.localeCompare(b.title, "ru")));
  return groups.length ? groups : buildDefaultPermissionsCatalog();
}

async function ensurePermissionsCatalog() {
  if (Array.isArray(state.permissionsCatalog) && state.permissionsCatalog.length) return state.permissionsCatalog;
  try {
    const resp = await api("/me/permissions/catalog");
    state.permissionsCatalog = normalizePermissionCatalog(resp?.items || []);
  } catch {
    state.permissionsCatalog = buildDefaultPermissionsCatalog();
  }
  return state.permissionsCatalog;
}

async function ensurePositionPermissionTemplates() {
  if (Array.isArray(state.positionPermissionTemplates)) return state.positionPermissionTemplates;
  try {
    const resp = await api("/position-permission-templates");
    state.positionPermissionTemplates = normalizePermissionTemplates(resp?.items || []);
  } catch {
    state.positionPermissionTemplates = normalizePermissionTemplates([]);
  }
  return state.positionPermissionTemplates;
}

function getPositionTemplateById(templateId) {
  return getSharedPositionTemplateById(state.positionPermissionTemplates, templateId);
}

function buildPositionTemplateOptions(selectedId = "") {
  return buildPermissionTemplateOptions(state.positionPermissionTemplates, {
    selectedId,
    emptyLabel: "Без шаблона",
    includeSystemBadge: true,
  });
}

function renderPositionTemplateSummary(templateId = "") {
  return renderPermissionTemplateSummaryById(state.positionPermissionTemplates, templateId, {
    emptyText: "Шаблон не выбран. Можно собрать права вручную ниже.",
    noDescriptionText: "Шаблон без описания",
  });
}

function applyPositionTemplateSelection(host, templateId) {
  return applyPermissionTemplateToCheckboxHost({
    templates: state.positionPermissionTemplates,
    templateId,
    checkboxSelector: 'input[data-preset-perm-code]',
    checkboxAttr: 'data-preset-perm-code',
    summaryHost: host.querySelector('#positionPresetTemplateSummary'),
    summaryOptions: {
      emptyText: "Шаблон не выбран. Можно собрать права вручную ниже.",
      noDescriptionText: "Шаблон без описания",
    },
  });
}

function parsePermissionCodes(value) {
  if (Array.isArray(value)) return value.map((item) => String(item || "").trim().toUpperCase()).filter(Boolean);
  if (!value) return [];
  if (typeof value === "string") {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsePermissionCodes(parsed);
    } catch {}
  }
  return [];
}

function defaultPositionPresetMeta() {
  const raw = state.setup?.step_meta?.positions;
  return raw && typeof raw === "object" ? raw : { presets: [], seq: 0 };
}

function getPositionPresets() {
  const raw = defaultPositionPresetMeta().presets;
  return Array.isArray(raw) ? raw.map((item, idx) => ({
    id: String(item?.id || `preset-${idx + 1}`),
    title: String(item?.title || "").trim(),
    pay_profile_id: item?.pay_profile_id ? Number(item.pay_profile_id) : null,
    pay_profile_title: String(item?.pay_profile_title || "").trim(),
    template_id: item?.template_id ? String(item.template_id) : "",
    template_title: String(item?.template_title || "").trim(),
    permission_codes: parsePermissionCodes(item?.permission_codes),
    rate: Number(item?.rate || 0) || 0,
    percent: Number(item?.percent || 0) || 0,
    is_active: item?.is_active !== false,
  })).filter((item) => item.title) : [];
}

async function savePositionPresets(presets) {
  const meta = defaultPositionPresetMeta();
  const next = {
    presets,
    seq: Math.max(Number(meta.seq || 0) || 0, presets.length),
    updated_at: new Date().toISOString(),
  };
  await api(`/venues/${encodeURIComponent(state.venueId)}/setup`, {
    method: "PATCH",
    body: { current_step_key: "positions", step_meta: { positions: next } },
  });
}

function buildPresetOptionList(selectedId = "") {
  const current = String(selectedId || "");
  const presets = getPositionPresets().filter((item) => item.is_active);
  return ['<option value="">Без должности</option>']
    .concat(presets.map((item) => `<option value="${esc(item.id)}" ${String(item.id) === current ? "selected" : ""}>${esc(item.title)}${item.pay_profile_title ? ` · ${esc(item.pay_profile_title)}` : ""}</option>`))
    .join("");
}

function buildPayProfileOptions(selectedId = "") {
  const current = String(selectedId || "");
  const items = Array.isArray(state.inline?.pay_profiles?.items) ? state.inline.pay_profiles.items : [];
  return ['<option value="">Без профиля</option>']
    .concat(items.filter((item) => item.is_active !== false).map((item) => `<option value="${esc(item.id)}" ${String(item.id) === current ? "selected" : ""}>${esc(item.title)}</option>`))
    .join("");
}

function parseVenueId() {
  const params = new URLSearchParams(location.search);
  const id = params.get("venue_id") || "";
  if (id) setActiveVenueId(id);
  return id;
}

function getStepFromUrl() {
  const params = new URLSearchParams(location.search);
  return String(params.get("step") || "").trim();
}

function getPhaseFromUrl() {
  const params = new URLSearchParams(location.search);
  const raw = String(params.get("phase") || "").trim().toUpperCase();
  return raw === "EXTRA" ? "EXTRA" : (raw === "PREPARE" ? "PREPARE" : "");
}

function setStepInUrl(stepKey, phase) {
  const url = new URL(location.href);
  if (stepKey) url.searchParams.set("step", stepKey);
  else url.searchParams.delete("step");
  if (phase) url.searchParams.set("phase", String(phase).toLowerCase());
  else url.searchParams.delete("phase");
  history.replaceState({}, "", url.pathname + url.search + url.hash);
}

function toStepStatusClass(status) {
  switch (String(status || "").toUpperCase()) {
    case "COMPLETED": return "setup-status setup-status--completed";
    case "SKIPPED": return "setup-status setup-status--skipped";
    case "REQUIRES_ATTENTION": return "setup-status setup-status--attention";
    case "LOCKED": return "setup-status setup-status--locked";
    default: return "setup-status setup-status--available";
  }
}

function getVisibleSteps() {
  const phase = String(state.selectedPhase || getSetupPhase(state.setup) || "PREPARE").toUpperCase();
  return Array.isArray(state.setup?.steps) ? state.setup.steps.filter((step) => String(step.phase || "").toUpperCase() === phase) : [];
}

function getCurrentStep() {
  const steps = Array.isArray(state.setup?.steps) ? state.setup.steps : [];
  const fallbackKey = getStepFromUrl() || state.selectedStepKey || getPhaseResumeStep(state.selectedPhase)?.key || steps[0]?.key || "";
  const selected = steps.find((step) => step.key === fallbackKey) || null;
  if (selected && String(selected.phase || '').toUpperCase() === String(state.selectedPhase || '').toUpperCase()) return selected;
  return steps.find((step) => String(step.phase || '').toUpperCase() === String(state.selectedPhase || 'PREPARE').toUpperCase() && !getStepUiInfo(step).locked)
    || steps.find((step) => String(step.phase || '').toUpperCase() === String(state.selectedPhase || 'PREPARE').toUpperCase())
    || selected
    || steps[0]
    || null;
}

function getStepByKey(stepKey) {
  return (state.setup?.steps || []).find((step) => step.key === stepKey) || null;
}

function phaseTitle() {
  return String(state.selectedPhase || "PREPARE").toUpperCase() === "EXTRA" ? "Дополнительная настройка" : "Базовая настройка";
}

function shouldUseInlineEditor(stepKey) {
  return INLINE_STEP_KEYS.has(String(stepKey || ""));
}

function getInlineCatalogState(stepKey) {
  const key = String(stepKey || "");
  if (!state.inline[key]) {
    state.inline[key] = { items: null, showArchived: false, editor: { mode: "create", id: null }, loading: false };
  }
  return state.inline[key];
}

function buildUnitOptions(selected = "QTY") {
  const current = String(selected || "QTY").toUpperCase();
  return ["QTY", "RUB", "PERCENT", "CUSTOM"]
    .map((unit) => `<option value="${unit}" ${unit === current ? "selected" : ""}>${esc(UNIT_LABEL[unit] || unit)}</option>`)
    .join("");
}

function getNextStepKey(currentStepKey) {
  const next = getAdjacentUnlockedStep(getVisibleSteps(), currentStepKey, 1);
  return next?.key || "";
}

function getAdjacentUnlockedStep(steps, currentStepKey, direction = 1) {
  const list = Array.isArray(steps) ? steps : [];
  const idx = list.findIndex((step) => String(step.key) === String(currentStepKey || ""));
  if (idx < 0) return null;
  if (direction < 0) {
    for (let i = idx - 1; i >= 0; i -= 1) {
      const candidate = list[i];
      if (!getStepUiInfo(candidate).locked) return candidate;
    }
    return null;
  }
  for (let i = idx + 1; i < list.length; i += 1) {
    const candidate = list[i];
    if (!getStepUiInfo(candidate).locked) return candidate;
  }
  return null;
}

function buildQuickStepOptions(steps, currentStepKey) {
  return ['<option value="">Перейти к шагу…</option>']
    .concat((Array.isArray(steps) ? steps : []).map((step) => {
      const ui = getStepUiInfo(step);
      const statusLabel = STATUS_LABELS[ui.uiStatus] || STATUS_LABELS[String(step.status || "AVAILABLE").toUpperCase()] || step.status || "";
      return `<option value="${esc(step.key)}" ${String(step.key) === String(currentStepKey || "") ? 'selected' : ''} ${ui.locked ? 'disabled' : ''}>${esc(step.title)}${statusLabel ? ` · ${esc(statusLabel)}` : ''}</option>`;
    }))
    .join('');
}

function moveToStep(stepKey) {
  const target = getStepByKey(stepKey);
  if (!target) return;
  const ui = getStepUiInfo(target);
  if (ui.locked) {
    toast(ui.lockedReason || "Этот шаг пока недоступен", "warn");
    return;
  }
  state.selectedPhase = String(target.phase || state.selectedPhase || "PREPARE").toUpperCase();
  state.selectedStepKey = target.key;
  state.viewMode = "step";
  setStepInUrl(target.key, state.selectedPhase);
  renderSetup();
}

function moveToPhase(phase) {
  state.selectedPhase = String(phase || "PREPARE").toUpperCase() === "EXTRA" ? "EXTRA" : "PREPARE";
  state.viewMode = "phase";
  const visibleSteps = getVisibleSteps();
  if (!visibleSteps.some((step) => String(step.key) === String(state.selectedStepKey || ""))) {
    state.selectedStepKey = getPhaseResumeStep(state.selectedPhase)?.key || visibleSteps.find((step) => !getStepUiInfo(step).locked)?.key || visibleSteps[0]?.key || "";
  }
  setStepInUrl("", state.selectedPhase);
  renderSetup();
}

function moveToOverview() {
  state.viewMode = "overview";
  setStepInUrl("", state.selectedPhase);
  renderSetup();
}

function renderAccessError(message) {
  root.innerHTML = `
    <div class="itemcard section-card">
      <b>Быстрая настройка недоступна</b>
      <div class="muted mt-8">${esc(message || "Открыть мастер настройки можно только владельцу заведения с полным доступом.")}</div>
      <div class="setup-actionbar">
        <button class="btn" id="btnBackToVenue" type="button">К заведению</button>
        <button class="btn subtle" id="btnBackToVenues" type="button">К списку заведений</button>
      </div>
    </div>
  `;
  document.getElementById("btnBackToVenue")?.addEventListener("click", () => navTo(`/app-venue.html?venue_id=${encodeURIComponent(String(state.venueId || ""))}`));
  document.getElementById("btnBackToVenues")?.addEventListener("click", () => navTo('/app-venues.html'));
}

function renderLoading() {
  root.innerHTML = `
    <div class="skeleton"></div>
    <div class="skeleton"></div>
    <div class="skeleton"></div>
  `;
}

function renderStartScreen() {
  const venueName = state.venue?.name || `Заведение #${state.venueId}`;
  root.innerHTML = `
    <div class="itemcard section-card">
      <div class="section-card__head">
        <div class="section-card__title">
          <b>Подготовим ${esc(venueName)}</b>
          <div class="muted">Мастер поможет пройти основные шаги, а затем при желании добить дополнительную настройку.</div>
        </div>
      </div>
      <div class="setup-summary">
        <div class="setup-kpi">
          <div class="setup-kpi__value">8 шагов</div>
          <div class="setup-kpi__hint">Базовая настройка: оплаты, департаменты, KPI, профили, должности, команда и интервалы.</div>
        </div>
        <div class="setup-kpi">
          <div class="setup-kpi__value">3 шага</div>
          <div class="setup-kpi__hint">Дополнительная настройка: категории расходов, поставщики и регулярные правила.</div>
        </div>
        <div class="setup-kpi">
          <div class="setup-kpi__value">Гибко</div>
          <div class="setup-kpi__hint">Часть шагов можно отложить и вернуться к ним позже без потери прогресса.</div>
        </div>
      </div>
      <div class="setup-actionbar">
        <button class="btn primary" id="btnStartSetup" type="button">Начать настройку</button>
        <button class="btn subtle" id="btnStartBack" type="button">К заведению</button>
      </div>
      <div class="setup-inline-note">Базовая настройка нужна для корректной работы графика, закрытия смены, сводки и зарплатных сценариев.</div>
    </div>
  `;
  document.getElementById("btnStartSetup")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/start`, { method: "POST" });
      clearDismissedSetupBanner();
      await loadSetup({ preserveSelection: false });
      state.viewMode = "overview";
      toast("Настройка начата", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось начать настройку", "err");
    }
  });
  document.getElementById("btnStartBack")?.addEventListener("click", () => navTo(`/app-venue.html?venue_id=${encodeURIComponent(String(state.venueId))}`));
}

function renderInlineEditorHost(currentStep) {
  if (!shouldUseInlineEditor(currentStep?.key)) return "";
  return `
    <div class="setup-editor mt-14">
      <div class="setup-editor__head">
        <div>
          <b>Настройка прямо в мастере</b>
          <div class="muted mt-6">Здесь можно быстро пройти шаг, а при необходимости открыть полный экран модуля.</div>
        </div>
      </div>
      <div id="setupInlineEditor" class="setup-editor__body">
        <div class="skeleton"></div>
        <div class="skeleton"></div>
      </div>
    </div>
  `;
}

function getPhaseResumeStep(phase) {
  const normalized = String(phase || state.selectedPhase || "PREPARE").toUpperCase();
  const visible = (Array.isArray(state.setup?.steps) ? state.setup.steps : [])
    .filter((step) => String(step.phase || "").toUpperCase() === normalized)
    .map((step) => ({ step, ui: getStepUiInfo(step) }));
  const actionable = visible.find(({ step, ui }) => !ui.locked && !step.completed && !step.skipped)
    || visible.find(({ step, ui }) => !ui.locked && (step.requires_attention || step.status === "REQUIRES_ATTENTION"))
    || visible.find(({ ui }) => !ui.locked)
    || visible[0]
    || null;
  return actionable?.step || null;
}

function renderOverview() {
  const venueName = state.venue?.name || `Заведение #${state.venueId}`;
  const status = russianSetupStatusLabel(getSetupStatus(state.setup));
  const progress = getSetupProgress(state.setup);
  const prepareResolved = Number(state.setup?.prepare_resolved || 0);
  const prepareTotal = Number(state.setup?.prepare_total || 0);
  const extraResolved = Number(state.setup?.extra_resolved || 0);
  const extraTotal = Number(state.setup?.extra_total || 0);
  const percent = progress.total > 0 ? Math.round((progress.resolved / progress.total) * 100) : 0;
  const resumeStep = getPhaseResumeStep(state.selectedPhase || getSetupPhase(state.setup));
  const nextTitle = resumeStep?.title || "Готово";
  const prepareDone = isSetupPrepareDone(state.setup);
  const extraDisabled = !prepareDone;

  root.innerHTML = `
    <div class="itemcard section-card">
      <div class="section-card__head">
        <div class="section-card__title">
          <b>${esc(venueName)}</b>
          <div class="muted">Базовая настройка · статус: ${esc(status)}</div>
        </div>
      </div>

      <div class="setup-inline-list">
        <span class="setup-chip">Готово: ${progress.done} из ${progress.total}</span>
        <span class="setup-chip">Решено: ${progress.resolved} из ${progress.total}</span>
        <span class="setup-chip">Следующий шаг: ${esc(nextTitle)}</span>
      </div>

      <div class="setup-progressbar"><span style="width:${percent}%"></span></div>

      <div class="setup-summary">
        <div class="setup-kpi">
          <div class="setup-kpi__value">${prepareResolved}/${prepareTotal}</div>
          <div class="setup-kpi__hint">Базовая настройка</div>
        </div>
        <div class="setup-kpi">
          <div class="setup-kpi__value">${extraResolved}/${extraTotal}</div>
          <div class="setup-kpi__hint">Дополнительная настройка</div>
        </div>
        <div class="setup-kpi">
          <div class="setup-kpi__value">${percent}%</div>
          <div class="setup-kpi__hint">Общий прогресс мастера</div>
        </div>
      </div>

      <div class="setup-phase-switch">
        <button class="btn ${state.selectedPhase === "PREPARE" ? "primary" : "subtle"}" id="btnOverviewPrepare" type="button">Базовая настройка</button>
        <button class="btn ${state.selectedPhase === "EXTRA" ? "primary" : "subtle"}" id="btnOverviewExtra" type="button" ${extraDisabled ? "disabled" : ""}>Дополнительная настройка</button>
      </div>

      <div class="setup-actionbar mt-14">
        <button class="btn" id="btnOverviewVenue" type="button">К заведению</button>
        <button class="btn subtle" id="btnSkipSetupAll" type="button">Пропустить настройку</button>
      </div>
    </div>
  `;

  document.getElementById("btnOverviewPrepare")?.addEventListener("click", () => moveToPhase("PREPARE"));
  document.getElementById("btnOverviewExtra")?.addEventListener("click", () => {
    if (extraDisabled) { toast("Сначала заверши базовую настройку", "warn"); return; }
    moveToPhase("EXTRA");
  });
  document.getElementById("btnOverviewVenue")?.addEventListener("click", () => navTo(`/app-venue.html?venue_id=${encodeURIComponent(String(state.venueId))}`));
  document.getElementById("btnSkipSetupAll")?.addEventListener("click", async () => {
    const ok = await confirmModal({
      title: "Пропустить настройку?",
      text: "Мастер можно будет открыть позже с карточки заведения. Баннер с предложением настройки будет скрыт.",
      confirmText: "Пропустить",
    });
    if (!ok) return;
    dismissSetupBanner();
    navTo(`/app-venue.html?venue_id=${encodeURIComponent(String(state.venueId))}`);
  });
}

function renderPhaseScreen() {
  const prepareDone = isSetupPrepareDone(state.setup);
  const visibleSteps = getVisibleSteps();
  const resumeStep = getPhaseResumeStep(state.selectedPhase);
  const isExtra = state.selectedPhase === "EXTRA";

  root.innerHTML = `
    <div class="itemcard section-card">
      <div class="section-card__head">
        <div class="section-card__title">
          <b>${esc(phaseTitle())}</b>
          <div class="muted">Шаги можно проходить по порядку или возвращаться к уже доступным позже.</div>
        </div>
      </div>

      <div class="setup-steps">
        ${visibleSteps.map((step) => {
          const ui = getStepUiInfo(step);
          const statusLabel = STATUS_LABELS[ui.uiStatus] || STATUS_LABELS[String(step.status || "AVAILABLE").toUpperCase()] || step.status;
          const countText = getStepSummaryText(step, ui);
          return `
            <button class="setup-step ${String(step.key) === String(state.selectedStepKey || "") ? "is-active" : ""}" type="button" data-step-key="${esc(step.key)}" ${ui.locked ? "disabled" : ""}>
              <div class="setup-step__top">
                <div>
                  <div class="setup-step__title">${esc(step.title)}</div>
                  <div class="setup-step__meta">${esc(countText)}</div>
                </div>
                <span class="${toStepStatusClass(ui.uiStatus)}">${esc(statusLabel)}</span>
              </div>
            </button>
          `;
        }).join("")}
      </div>

      <div class="setup-footer">
        <div class="setup-actionbar">
          <button class="btn subtle" id="btnPhaseBack" type="button">← Назад</button>
          <button class="btn" id="btnPhaseResume" type="button">Продолжить</button>
        </div>
        <div class="setup-actionbar">
          ${isExtra ? `<button class="btn subtle" id="btnPhasePrevPhase" type="button">К базовой настройке</button>` : ``}
          ${!isExtra && prepareDone ? `<button class="btn subtle" id="btnPhaseNextPhase" type="button">К дополнительной настройке</button>` : ``}
        </div>
      </div>
    </div>
  `;

  document.querySelectorAll('[data-step-key]').forEach((btn) => {
    btn.addEventListener('click', () => moveToStep(btn.getAttribute('data-step-key') || ''));
  });
  document.getElementById('btnPhaseBack')?.addEventListener('click', () => moveToOverview());
  document.getElementById('btnPhaseResume')?.addEventListener('click', () => {
    if (!resumeStep) { toast('Все шаги этой части уже просмотрены', 'ok'); return; }
    moveToStep(resumeStep.key);
  });
  document.getElementById('btnPhasePrevPhase')?.addEventListener('click', () => moveToPhase('PREPARE'));
  document.getElementById('btnPhaseNextPhase')?.addEventListener('click', () => moveToPhase('EXTRA'));
}

function renderStepDetail() {
  const currentStepRaw = getCurrentStep();
  if (!currentStepRaw) {
    root.innerHTML = `<div class="setup-empty">Не удалось определить шаг настройки.</div>`;
    return;
  }
  const currentStep = currentStepRaw;
  const ui = getStepUiInfo(currentStep);
  state.selectedStepKey = currentStep.key;
  state.selectedPhase = String(currentStep.phase || state.selectedPhase || "PREPARE").toUpperCase();
  setStepInUrl(currentStep.key, state.selectedPhase);

  const meta = STEP_CONTENT[currentStep.key] || {
    title: currentStep.title,
    subtitle: "Этот шаг уже добавлен в мастер, но текст-помощник для него пока не заполнен.",
    what: "Настрой параметры шага на целевой странице.",
    where: "Используется внутри заведения и связанных модулей.",
    later: currentStep.skippable ? "Этот шаг можно отложить." : "Этот шаг лучше не откладывать.",
  };

  const useInlineEditor = shouldUseInlineEditor(currentStep.key) && !ui.locked;
  const visibleSteps = getVisibleSteps();
  const prevStep = getAdjacentUnlockedStep(visibleSteps, currentStep.key, -1);
  const nextStep = getAdjacentUnlockedStep(visibleSteps, currentStep.key, 1);

  root.innerHTML = `
    <div class="itemcard section-card">
      <div class="setup-detail__head">
        <div>
          <b>${esc(meta.title || currentStep.title)}</b>
          <div class="muted mt-6">${esc(meta.subtitle || "")}</div>
        </div>
        <span class="${toStepStatusClass(ui.uiStatus)}">${esc(STATUS_LABELS[ui.uiStatus] || currentStep.status)}</span>
      </div>

      ${ui.locked ? `<div class="setup-inline-list"><span class="setup-chip">${esc(ui.lockedReason)}</span></div>` : ``}

      <div class="setup-detail__grid">
        <div class="setup-helper"><b>Что это</b>${esc(meta.what || "")}</div>
        <div class="setup-helper"><b>Где используется</b>${esc(meta.where || "")}</div>
        <div class="setup-helper"><b>Можно ли позже</b>${esc(meta.later || "")}</div>
      </div>

      ${ui.locked ? `<div class="setup-empty mt-14">${esc(ui.lockedReason)}</div>` : renderInlineEditorHost(currentStep)}

      <div class="setup-actionbar">
        ${typeof meta.primaryHref === "function" ? `<button class="btn ${useInlineEditor ? "subtle" : "primary"}" id="btnOpenFullPage" type="button">${esc(meta.primaryLabel || "Открыть")}</button>` : ""}
        <select class="input setup-jump-select" id="setupStepJumpSelect">${buildQuickStepOptions(visibleSteps, currentStep.key)}</select>
        ${currentStep.skippable && !currentStep.completed && !currentStep.skipped && !ui.locked ? `<button class="btn subtle" id="btnSkipStep" type="button">Вернуться позже</button>` : ""}
      </div>

      <div class="setup-inline-note">
        ${ui.locked ? esc(ui.lockedReason) : (currentStep.completed ? "Шаг завершён и уже учитывается в прогрессе настройки." : (currentStep.skipped ? "Шаг отложен. К нему можно вернуться в любой момент." : "Сохраняй изменения прямо в мастере или открой полный экран модуля, если нужен расширенный режим."))}
      </div>

      <div class="setup-footer">
        <div class="setup-actionbar">
          <button class="btn subtle" id="btnBackToPhase" type="button">← К списку шагов</button>
          <button class="btn subtle" id="btnPrevStep" type="button" ${prevStep ? '' : 'disabled'}>← Назад</button>
          <button class="btn subtle" id="btnNextStep" type="button" ${nextStep ? '' : 'disabled'}>Дальше →</button>
        </div>
        <div class="setup-actionbar">
          ${state.selectedPhase === "PREPARE" && isSetupPrepareDone(state.setup) && !isSetupDone(state.setup) ? `<button class="btn primary" id="btnFinishPrepare" type="button">Завершить базовую настройку</button>` : ""}
          ${state.selectedPhase === "EXTRA" && isSetupPrepareDone(state.setup) && (state.setup?.extra_resolved === state.setup?.extra_total) && !isSetupDone(state.setup) ? `<button class="btn primary" id="btnFinishExtra" type="button">Завершить весь мастер</button>` : ""}
        </div>
      </div>
    </div>
  `;

  if (typeof meta.primaryHref === "function") {
    document.getElementById('btnOpenFullPage')?.addEventListener('click', () => navTo(meta.primaryHref(state.venueId, state)));
  }

  wireSetupActions(currentStep, visibleSteps);
}

function renderSetup() {
  if (state.accessError) { renderAccessError(state.accessError); return; }
  if (!state.setup) { renderLoading(); return; }
  if (state.viewMode === 'phase') { renderPhaseScreen(); return; }
  if (state.viewMode === 'step') { renderStepDetail(); return; }
  renderOverview();
}

function renderCatalogListItems(stepKey, items, currentStep) {
  const cfg = CATALOG_CONFIG[stepKey];
  const inlineState = getInlineCatalogState(stepKey);
  const visibleItems = inlineState.showArchived ? items : items.filter((item) => item.is_active);
  if (!visibleItems.length) {
    return `<div class="setup-empty">${esc(cfg.emptyText)}</div>`;
  }
  return visibleItems.map((item) => {
    const unit = cfg.includeUnit ? String(item.unit || "QTY").toUpperCase() : "";
    return `
      <div class="setup-minirow">
        <div class="setup-minirow__main">
          <div class="setup-minirow__titlewrap">
            <b>${esc(item.title)}</b>
            ${item.is_active ? "" : `<span class="badge">архив</span>`}
            ${cfg.includeUnit ? `<span class="badge">${esc(UNIT_LABEL[unit] || unit)}</span>` : ""}
          </div>
          <div class="setup-minirow__meta">${esc(item.is_active ? cfg.activeHint : cfg.archivedHint)}</div>
        </div>
        <div class="setup-minirow__actions">
          <button class="btn sm" type="button" data-inline-edit="${esc(stepKey)}" data-item-id="${esc(item.id)}">Изменить</button>
          <button class="btn sm ${item.is_active ? "danger" : ""}" type="button" data-inline-toggle="${esc(stepKey)}" data-item-id="${esc(item.id)}">${item.is_active ? "В архив" : "Вернуть"}</button>
        </div>
      </div>
    `;
  }).join("");
}

function renderCatalogEditor(stepKey, items, currentStep) {
  const cfg = CATALOG_CONFIG[stepKey];
  const inlineState = getInlineCatalogState(stepKey);
  const activeCount = items.filter((item) => item.is_active).length;
  const editingId = inlineState.editor?.id;
  const editingItem = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
  const mode = editingItem ? "edit" : "create";
  const initialTitle = editingItem?.title || "";
  const initialCode = editingItem?.code || "";
  const initialUnit = String(editingItem?.unit || "QTY").toUpperCase();

  return `
    <div class="setup-editor__panel">
      <div class="setup-editor__toolbar">
        <div class="setup-editor__title">${esc(cfg.listLabel)}</div>
        <label class="setup-toggle">
          <input type="checkbox" id="inlineShowArchived" ${inlineState.showArchived ? "checked" : ""} />
          <span>Показывать архив</span>
        </label>
      </div>

      <div class="setup-editor__grid mt-12">
        <div>
          <div class="setup-minirows">${renderCatalogListItems(stepKey, items, currentStep)}</div>
        </div>

        <div class="setup-formcard">
          <div class="setup-editor__title">${mode === "edit" ? (cfg.editTitle || `Изменить ${cfg.title}`) : (cfg.createTitle || `Новый ${cfg.title}`)}</div>
          <div class="muted mt-6">${mode === "edit" ? "Сохрани изменения и шаг останется завершённым." : "Можно создать базовые элементы прямо здесь и сразу продолжить настройку."}</div>
          <div class="setup-formgrid mt-12">
            <label>
              <span>Название</span>
              <input class="input" id="inlineTitle" placeholder="Введите название" value="${esc(initialTitle)}" />
            </label>
            <label>
              <span>Код</span>
              <input class="input" id="inlineCode" placeholder="Будет сгенерирован автоматически" value="${esc(initialCode)}" />
            </label>
            ${cfg.includeUnit ? `
              <label>
                <span>Единица</span>
                <select class="input" id="inlineUnit">${buildUnitOptions(initialUnit)}</select>
              </label>
            ` : ""}
          </div>

          <div class="setup-actionbar mt-12">
            <button class="btn primary" id="btnInlineSave" type="button">${mode === "edit" ? "Сохранить" : "Создать"}</button>
            ${mode === "edit" ? `<button class="btn subtle" id="btnInlineCancelEdit" type="button">Отмена</button>` : ""}
          </div>

          <div class="setup-inline-note">Код нужен для внутренней логики. Если не менять его вручную, он соберётся автоматически из названия.</div>
        </div>
      </div>

      <div class="setup-actionbar mt-14">
        ${activeCount > 0 && !currentStep.completed ? `<button class="btn" id="btnInlineComplete" type="button">Подтвердить шаг</button>` : ""}
        ${activeCount > 0 && !currentStep.completed ? `<button class="btn subtle" id="btnInlineCompleteNext" type="button">Подтвердить и дальше</button>` : ""}
        ${cfg.skippableInline && !currentStep.completed && !currentStep.skipped ? `<button class="btn subtle" id="btnInlineSkip" type="button">${esc(cfg.skipLabel || "Вернуться позже")}</button>` : ""}
      </div>
    </div>
  `;
}

async function mountWelcomeEditor(currentStep) {
  const host = document.getElementById("setupInlineEditor");
  if (!host) return;
  const currentName = String(state.venue?.name || "").trim();
  host.innerHTML = `
    <div class="setup-editor__panel">
      <div class="setup-formcard">
        <div class="setup-editor__title">Как будет называться заведение</div>
        <div class="muted mt-6">Название можно подтвердить как есть или поменять прямо сейчас. Это не блокирует дальнейшую работу и позже его тоже можно будет изменить.</div>
        <div class="setup-formgrid mt-12">
          <label>
            <span>Название заведения</span>
            <input class="input" id="welcomeVenueName" placeholder="Введите название" value="${esc(currentName)}" />
          </label>
        </div>
        <div class="setup-actionbar mt-14">
          <button class="btn primary" id="btnWelcomeSave" type="button">Сохранить и продолжить</button>
          ${!currentStep.completed ? `<button class="btn subtle" id="btnWelcomeKeep" type="button">Оставить как есть</button>` : ""}
        </div>
      </div>
    </div>
  `;

  document.getElementById("btnWelcomeSave")?.addEventListener("click", async () => {
    const input = document.getElementById("welcomeVenueName");
    const name = String(input?.value || "").trim();
    if (!name) {
      toast("Введите название заведения", "err");
      input?.focus();
      return;
    }
    try {
      await renameVenue(state.venueId, name);
      if (!currentStep.completed) {
        await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: "POST", body: { step_key: currentStep.key } });
      }
      state.venue = await getVenueById(state.venueId);
      await loadSetup({ preserveSelection: true });
      toast("Название сохранено", "ok");
      const next = getNextStepKey(currentStep.key);
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось сохранить название", "err");
    }
  });

  document.getElementById("btnWelcomeKeep")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: "POST", body: { step_key: currentStep.key } });
      await loadSetup({ preserveSelection: true });
      toast("Название подтверждено", "ok");
      const next = getNextStepKey(currentStep.key);
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось завершить шаг", "err");
    }
  });
}

async function loadInlineCatalogItems(stepKey, { force = false } = {}) {
  const cfg = CATALOG_CONFIG[stepKey];
  const inlineState = getInlineCatalogState(stepKey);
  if (!cfg) return [];
  if (!force && Array.isArray(inlineState.items)) return inlineState.items;
  inlineState.loading = true;
  try {
    const items = await cfg.load(state.venueId);
    inlineState.items = Array.isArray(items) ? items : [];
    return inlineState.items;
  } finally {
    inlineState.loading = false;
  }
}

async function refreshCatalogStepAndSetup(stepKey, currentStep, { tryNext = false } = {}) {
  await loadInlineCatalogItems(stepKey, { force: true });
  await loadSetup({ preserveSelection: true });
  if (tryNext) {
    const next = getNextStepKey(currentStep.key);
    if (next) moveToStep(next);
  }
}

async function mountCatalogEditor(currentStep) {
  const stepKey = currentStep.key;
  const host = document.getElementById("setupInlineEditor");
  if (!host) return;
  const cfg = CATALOG_CONFIG[stepKey];
  if (!cfg) {
    host.innerHTML = "";
    return;
  }

  host.innerHTML = `<div class="skeleton"></div><div class="skeleton"></div>`;
  const items = await loadInlineCatalogItems(stepKey);
  const activeCount = items.filter((item) => item.is_active).length;
  if (stepKey in CATALOG_CONFIG && Number(currentStep.count || 0) !== activeCount && !(cfg.skippableInline && currentStep.skipped)) {
    await loadSetup({ preserveSelection: true });
    return;
  }

  host.innerHTML = renderCatalogEditor(stepKey, items, getStepByKey(stepKey) || currentStep);
  const inlineState = getInlineCatalogState(stepKey);
  const titleInput = document.getElementById("inlineTitle");
  const codeInput = document.getElementById("inlineCode");
  const unitInput = document.getElementById("inlineUnit");

  const applyAutoCode = () => {
    if (!codeInput || codeInput.dataset.touched === "1") return;
    codeInput.value = ensureUniqueCode(slugifyCode(titleInput?.value || "", stepKey === "kpi" ? "kpi" : "item"), items, inlineState.editor?.id || null);
  };
  titleInput?.addEventListener("input", applyAutoCode);
  codeInput?.addEventListener("input", () => { if (codeInput) codeInput.dataset.touched = codeInput.value ? "1" : ""; });
  if (titleInput && !codeInput?.value) applyAutoCode();

  document.getElementById("inlineShowArchived")?.addEventListener("change", async (e) => {
    inlineState.showArchived = !!e.target?.checked;
    await mountCatalogEditor(getStepByKey(stepKey) || currentStep);
  });

  document.getElementById("btnInlineCancelEdit")?.addEventListener("click", async () => {
    inlineState.editor = { mode: "create", id: null };
    await mountCatalogEditor(getStepByKey(stepKey) || currentStep);
  });

  document.getElementById("btnInlineSave")?.addEventListener("click", async () => {
    const title = String(titleInput?.value || "").trim();
    let code = String(codeInput?.value || "").trim().toLowerCase();
    if (!title) {
      toast("Заполни название", "err");
      titleInput?.focus();
      return;
    }
    if (!code) code = ensureUniqueCode(slugifyCode(title, stepKey === "kpi" ? "kpi" : "item"), items, inlineState.editor?.id || null);
    const payload = {
      title,
      code,
      is_active: true,
      sort_order: (Math.max(0, ...items.map((item) => Number(item.sort_order || 0))) || 0) + 10,
    };
    if (cfg.includeUnit) payload.unit = String(unitInput?.value || "QTY").toUpperCase();
    try {
      const wasEdit = Boolean(inlineState.editor?.id);
      if (wasEdit) await cfg.update(state.venueId, inlineState.editor.id, payload);
      else await cfg.create(state.venueId, payload);
      inlineState.editor = { mode: "create", id: null };
      await refreshCatalogStepAndSetup(stepKey, currentStep);
      if (!currentStep.completed) {
        try {
          await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: "POST", body: { step_key: stepKey } });
          await loadSetup({ preserveSelection: true });
        } catch {}
      }
      toast(wasEdit ? "Изменения сохранены" : "Элемент создан", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось сохранить", "err");
    }
  });

  document.querySelectorAll(`[data-inline-edit="${stepKey}"]`).forEach((btn) => {
    btn.addEventListener("click", async () => {
      inlineState.editor = { mode: "edit", id: btn.getAttribute("data-item-id") || null };
      await mountCatalogEditor(getStepByKey(stepKey) || currentStep);
    });
  });

  document.querySelectorAll(`[data-inline-toggle="${stepKey}"]`).forEach((btn) => {
    btn.addEventListener("click", async () => {
      const itemId = btn.getAttribute("data-item-id") || "";
      const item = items.find((row) => String(row.id) === String(itemId));
      if (!item) return;
      const makeActive = !item.is_active;
      const ok = await confirmModal({
        title: makeActive ? `Вернуть ${cfg.title}?` : `Архивировать ${cfg.title}?`,
        text: `${makeActive ? "Вернуть" : "Убрать"} «${item.title}»?`,
        confirmText: makeActive ? "Вернуть" : "В архив",
        danger: !makeActive,
      });
      if (!ok) return;
      try {
        await cfg.update(state.venueId, item.id, { is_active: makeActive });
        await refreshCatalogStepAndSetup(stepKey, currentStep);
        toast(makeActive ? "Элемент восстановлен" : "Элемент архивирован", "ok");
      } catch (e) {
        toast(e?.data?.detail || e?.message || "Не удалось изменить состояние", "err");
      }
    });
  });

  document.getElementById("btnInlineComplete")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: "POST", body: { step_key: stepKey } });
      await loadSetup({ preserveSelection: true });
      toast("Шаг подтверждён", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось завершить шаг", "err");
    }
  });

  document.getElementById("btnInlineCompleteNext")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: "POST", body: { step_key: stepKey } });
      await loadSetup({ preserveSelection: true });
      toast("Шаг подтверждён", "ok");
      const next = getNextStepKey(stepKey);
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось завершить шаг", "err");
    }
  });

  document.getElementById("btnInlineSkip")?.addEventListener("click", async () => {
    const ok = await confirmModal({
      title: cfg.skipConfirmTitle || "Отложить шаг?",
      text: cfg.skipConfirmText || "Этот шаг будет помечен как отложенный. К нему можно будет вернуться в любой момент.",
      confirmText: "Отложить",
      danger: false,
    });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, { method: "POST", body: { step_key: stepKey } });
      await loadSetup({ preserveSelection: true });
      toast("Шаг отложен", "ok");
      const next = getNextStepKey(stepKey);
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось отложить шаг", "err");
    }
  });
}

async function mountInlineEditor(currentStep) {
  if (!shouldUseInlineEditor(currentStep?.key)) return;
  if (currentStep.key === "welcome") {
    await mountWelcomeEditor(getStepByKey("welcome") || currentStep);
    return;
  }
  if (currentStep.key === "pay_profiles") {
    await mountPayProfilesEditor(getStepByKey("pay_profiles") || currentStep);
    return;
  }
  if (currentStep.key === "positions") {
    await mountPositionsEditor(getStepByKey("positions") || currentStep);
    return;
  }
  if (currentStep.key === "invites") {
    await mountInvitesEditor(getStepByKey("invites") || currentStep);
    return;
  }
  if (currentStep.key === "shift_intervals") {
    await mountShiftIntervalsEditor(getStepByKey("shift_intervals") || currentStep);
    return;
  }
  if (currentStep.key === "suppliers") {
    await mountSuppliersEditor(getStepByKey("suppliers") || currentStep);
    return;
  }
  if (currentStep.key === "recurring_expenses") {
    await mountRecurringExpensesEditor(getStepByKey("recurring_expenses") || currentStep);
    return;
  }
  await mountCatalogEditor(getStepByKey(currentStep.key) || currentStep);
}


async function ensurePayProfileAuxData() {
  if (!Array.isArray(state.departments)) {
    try { state.departments = await getDepartments(state.venueId, { includeArchived: false }); } catch { state.departments = []; }
  }
  if (!Array.isArray(state.kpiMetrics)) {
    try { state.kpiMetrics = await getKpiMetrics(state.venueId, { includeArchived: false }); } catch { state.kpiMetrics = []; }
  }
}

async function loadInlinePayProfileDetail(profileId, { force = false } = {}) {
  const inlineState = state.inline.pay_profiles;
  if (!profileId) return null;
  const key = String(profileId);
  if (!force && inlineState.details && inlineState.details[key]) return inlineState.details[key];
  const detail = await getPayProfile(state.venueId, profileId);
  inlineState.details = inlineState.details || {};
  inlineState.details[key] = detail;
  return detail;
}

function buildPayProfileComponentEditor(detail, editingComponent = null) {
  const type = String(editingComponent?.component_type || 'SALARY_FIXED_MONTH').toUpperCase();
  return `
    <div class="setup-formgrid mt-12">
      <label>
        <span>Тип компонента</span>
        <select class="input" id="inlineComponentType">${payComponentTypeOptions(type)}</select>
      </label>
      <label>
        <span>Название</span>
        <input class="input" id="inlineComponentTitle" placeholder="Например, Ставка за час" value="${esc(editingComponent?.title || defaultPayComponentTitle(type))}" />
      </label>
      <label id="inlineComponentAmountRow" style="display:${['SALARY_FIXED_MONTH','SALARY_PER_SHIFT','KPI_BONUS'].includes(type) ? '' : 'none'}">
        <span>Сумма, ₽</span>
        <input class="input" id="inlineComponentAmount" inputmode="decimal" placeholder="0" value="${esc(moneyInputFromMinor(editingComponent?.amount_minor))}" />
      </label>
      <label id="inlineComponentRateRow" style="display:${type === 'SALARY_HOURLY' ? '' : 'none'}">
        <span>Ставка в час, ₽</span>
        <input class="input" id="inlineComponentRate" inputmode="decimal" placeholder="0" value="${esc(moneyInputFromMinor(editingComponent?.rate_minor))}" />
      </label>
      <label id="inlineComponentPercentRow" style="display:${['PERCENT_TOTAL_REVENUE','PERCENT_DEPARTMENT_REVENUE'].includes(type) ? '' : 'none'}">
        <span>Процент</span>
        <input class="input" id="inlineComponentPercent" inputmode="decimal" placeholder="0" value="${esc(percentInputFromBps(editingComponent?.percent_bps))}" />
      </label>
      <label id="inlineComponentDepartmentRow" style="display:${type === 'PERCENT_DEPARTMENT_REVENUE' ? '' : 'none'}">
        <span>Департамент</span>
        <select class="input" id="inlineComponentDepartmentId">${buildSimpleOptions(state.departments || [], editingComponent?.department_id, 'Выбери департамент')}</select>
      </label>
      <label id="inlineComponentKpiRow" style="display:${type === 'KPI_BONUS' ? '' : 'none'}">
        <span>KPI</span>
        <select class="input" id="inlineComponentKpiMetricId">${buildSimpleOptions(state.kpiMetrics || [], editingComponent?.kpi_metric_id, 'Выбери KPI')}</select>
      </label>
      <label>
        <span>Активность</span>
        <select class="input" id="inlineComponentActive">
          <option value="1" ${(editingComponent?.is_active === false) ? '' : 'selected'}>Активен</option>
          <option value="0" ${(editingComponent?.is_active === false) ? 'selected' : ''}>Неактивен</option>
        </select>
      </label>
    </div>
  `;
}

function renderPayProfileComponentsBlock(detail, inlineState) {
  const selectedProfile = detail?.title || 'Профиль';
  const components = Array.isArray(detail?.components) ? detail.components : [];
  const editingId = inlineState.componentEditor?.id || null;
  const editingComponent = editingId ? components.find((item) => String(item.id) === String(editingId)) : null;
  const mode = editingComponent ? 'edit' : 'create';
  return `
    <div class="setup-formcard mt-12">
      <div class="setup-editor__title">Компоненты профиля «${esc(selectedProfile)}»</div>
      <div class="muted mt-6">Здесь можно сразу собрать правила начисления для выбранного профиля.</div>
      <div class="setup-minirows mt-12">
        ${components.length ? components.map((item) => `
          <div class="setup-minirow">
            <div class="setup-minirow__main">
              <div class="setup-minirow__titlewrap">
                <b>${esc(item.title || defaultPayComponentTitle(item.component_type))}</b>
                ${item.is_active === false ? '<span class="badge">неактивен</span>' : ''}
              </div>
              <div class="setup-minirow__meta">${esc(payComponentValueLabel(item))}</div>
            </div>
            <div class="setup-minirow__actions">
              <button class="btn sm" type="button" data-inline-edit-component="${esc(item.id)}">Изменить</button>
              <button class="btn sm danger" type="button" data-inline-delete-component="${esc(item.id)}">Удалить</button>
            </div>
          </div>
        `).join('') : '<div class="setup-empty">Компоненты ещё не добавлены. Создай хотя бы один, чтобы профиль был готов к работе.</div>'}
      </div>
      <div class="setup-editor__title mt-12">${mode === 'edit' ? 'Редактирование компонента' : 'Новый компонент'}</div>
      ${buildPayProfileComponentEditor(detail, editingComponent)}
      <div class="setup-actionbar mt-12">
        <button class="btn primary" id="btnInlineSaveComponent" type="button">${mode === 'edit' ? 'Сохранить компонент' : 'Добавить компонент'}</button>
        ${mode === 'edit' ? '<button class="btn subtle" id="btnInlineCancelComponentEdit" type="button">Отмена</button>' : ''}
      </div>
    </div>
  `;
}

async function loadInlinePayProfiles({ force = false } = {}) {
  const inlineState = state.inline.pay_profiles;
  if (!force && Array.isArray(inlineState.items)) return inlineState.items;
  inlineState.loading = true;
  try {
    const items = await getPayProfiles(state.venueId, { includeInactive: true });
    inlineState.items = Array.isArray(items) ? items : [];
    return inlineState.items;
  } finally {
    inlineState.loading = false;
  }
}

function renderPayProfilesEditor(items, currentStep) {
  const inlineState = state.inline.pay_profiles;
  const visibleItems = inlineState.showInactive ? items : items.filter((item) => item.is_active !== false);
  const editingId = inlineState.editor?.id || null;
  const editingItem = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
  const mode = editingItem ? "edit" : "create";
  const selectedProfileId = inlineState.selectedProfileId || editingId || "";
  const detail = selectedProfileId ? (inlineState.details?.[String(selectedProfileId)] || null) : null;
  const activeCount = items.filter((item) => item.is_active !== false).length;
  return `
    <div class="setup-editor__panel">
      <div class="setup-editor__toolbar">
        <div class="setup-editor__title">Профили зарплаты</div>
        <label class="setup-toggle">
          <input type="checkbox" id="inlineShowInactiveProfiles" ${inlineState.showInactive ? "checked" : ""} />
          <span>Показывать неактивные</span>
        </label>
      </div>
      <div class="setup-editor__grid mt-12">
        <div>
          <div class="setup-minirows">
            ${visibleItems.length ? visibleItems.map((item) => `
              <div class="setup-minirow">
                <div class="setup-minirow__main">
                  <div class="setup-minirow__titlewrap">
                    <b>${esc(item.title)}</b>
                    ${item.is_active === false ? '<span class="badge">неактивен</span>' : ''}
                    ${String(selectedProfileId) === String(item.id) ? '<span class="badge">выбран</span>' : ''}
                  </div>
                  <div class="setup-minirow__meta">${esc(item.description || 'Без описания')}${Number(item.components_count || 0) > 0 ? ' · Компоненты настроены' : ' · Компоненты пока не добавлены'}</div>
                </div>
                <div class="setup-minirow__actions">
                  <button class="btn sm" type="button" data-inline-select-profile="${esc(item.id)}">Компоненты</button>
                  <button class="btn sm" type="button" data-inline-edit-profile="${esc(item.id)}">Изменить</button>
                  <button class="btn sm ${item.is_active === false ? '' : 'danger'}" type="button" data-inline-toggle-profile="${esc(item.id)}">${item.is_active === false ? 'Включить' : 'Отключить'}</button>
                  <button class="btn sm danger" type="button" data-inline-delete-profile="${esc(item.id)}">Удалить</button>
                </div>
              </div>
            `).join('') : '<div class="setup-empty">Пока нет профилей зарплаты. Создай хотя бы один базовый профиль, чтобы потом связать его с должностями.</div>'}
          </div>
        </div>
        <div>
          <div class="setup-formcard">
            <div class="setup-editor__title">${mode === 'edit' ? 'Редактирование профиля' : 'Новый профиль'}</div>
            <div class="muted mt-6">Профили создаются без назначения на сотрудников. Сейчас важно собрать базовые шаблоны.</div>
            <div class="setup-formgrid mt-12">
              <label>
                <span>Название</span>
                <input class="input" id="inlineProfileTitle" placeholder="Например, Официант / Бар" value="${esc(editingItem?.title || '')}" />
              </label>
              <label>
                <span>Активность</span>
                <select class="input" id="inlineProfileActive">
                  <option value="1" ${(editingItem?.is_active === false) ? '' : 'selected'}>Активен</option>
                  <option value="0" ${(editingItem?.is_active === false) ? 'selected' : ''}>Неактивен</option>
                </select>
              </label>
              <label style="grid-column:1 / -1">
                <span>Описание</span>
                <textarea class="input" id="inlineProfileDescription" rows="4" placeholder="Коротко опиши, для какой роли нужен этот профиль">${esc(editingItem?.description || '')}</textarea>
              </label>
            </div>
            <div class="setup-actionbar mt-12">
              <button class="btn primary" id="btnInlineSaveProfile" type="button">${mode === 'edit' ? 'Сохранить' : 'Создать'}</button>
              ${mode === 'edit' ? '<button class="btn subtle" id="btnInlineCancelProfileEdit" type="button">Отмена</button>' : ''}
            </div>
          </div>
          ${detail ? renderPayProfileComponentsBlock(detail, inlineState) : (activeCount > 0 ? '<div class="setup-inline-note">Выбери профиль слева, чтобы сразу настроить его компоненты.</div>' : '')}
        </div>
      </div>
      <div class="setup-actionbar mt-14">
        ${activeCount > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteProfiles" type="button">Подтвердить шаг</button>' : ''}
        ${activeCount > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteProfilesNext" type="button">Подтвердить и дальше</button>' : ''}
      </div>
    </div>
  `;
}

async function mountPayProfilesEditor(currentStep) {
  const host = document.getElementById('setupInlineEditor');
  if (!host) return;
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  await ensurePayProfileAuxData();
  const items = await loadInlinePayProfiles();
  const inlineState = state.inline.pay_profiles;
  if (Number(currentStep.count || 0) !== items.filter((item) => item.is_active !== false).length) {
    await loadSetup({ preserveSelection: true });
    return;
  }
  if (inlineState.selectedProfileId && !items.some((item) => String(item.id) === String(inlineState.selectedProfileId))) {
    inlineState.selectedProfileId = null;
    inlineState.componentEditor = { mode: 'create', id: null };
  }
  if (inlineState.selectedProfileId) {
    try { await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true }); } catch {}
  }
  host.innerHTML = renderPayProfilesEditor(items, getStepByKey('pay_profiles') || currentStep);

  document.getElementById('inlineShowInactiveProfiles')?.addEventListener('change', async (e) => {
    inlineState.showInactive = !!e.target?.checked;
    await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
  });

  document.getElementById('btnInlineCancelProfileEdit')?.addEventListener('click', async () => {
    inlineState.editor = { mode: 'create', id: null };
    await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
  });

  document.getElementById('btnInlineSaveProfile')?.addEventListener('click', async () => {
    const title = String(document.getElementById('inlineProfileTitle')?.value || '').trim();
    const description = String(document.getElementById('inlineProfileDescription')?.value || '').trim();
    const is_active = String(document.getElementById('inlineProfileActive')?.value || '1') === '1';
    if (!title) return toast('Укажи название профиля', 'err');
    try {
      let saved = null;
      if (inlineState.editor?.id) saved = await updatePayProfile(state.venueId, inlineState.editor.id, { title, description: description || null, is_active });
      else saved = await createPayProfile(state.venueId, { title, description: description || null, is_active });
      inlineState.editor = { mode: 'create', id: null };
      if (saved?.id) inlineState.selectedProfileId = saved.id;
      await loadInlinePayProfiles({ force: true });
      if (inlineState.selectedProfileId) await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
      await loadSetup({ preserveSelection: true });
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
      if (!currentStep.completed) {
        try {
          await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'pay_profiles' } });
          await loadSetup({ preserveSelection: true });
        } catch {}
      }
      toast('Профиль сохранён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось сохранить профиль', 'err');
    }
  });

  host.querySelectorAll('[data-inline-select-profile]').forEach((btn) => btn.addEventListener('click', async () => {
    inlineState.selectedProfileId = btn.getAttribute('data-inline-select-profile') || null;
    inlineState.componentEditor = { mode: 'create', id: null };
    await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
    await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
  }));

  host.querySelectorAll('[data-inline-edit-profile]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-inline-edit-profile') || null;
    inlineState.editor = { mode: 'edit', id };
    inlineState.selectedProfileId = id;
    await loadInlinePayProfileDetail(id, { force: true });
    await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
  }));

  host.querySelectorAll('[data-inline-toggle-profile]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-inline-toggle-profile') || '';
    const item = (state.inline.pay_profiles.items || []).find((row) => String(row.id) === String(id));
    if (!item) return;
    try {
      await updatePayProfile(state.venueId, item.id, { is_active: !(item.is_active !== false) });
      await loadInlinePayProfiles({ force: true });
      if (inlineState.selectedProfileId) await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
      await loadSetup({ preserveSelection: true });
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
      toast('Состояние профиля обновлено', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось изменить профиль', 'err');
    }
  }));

  host.querySelectorAll('[data-inline-delete-profile]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-inline-delete-profile') || '';
    const item = (state.inline.pay_profiles.items || []).find((row) => String(row.id) === String(id));
    if (!item) return;
    const ok = await confirmModal({ title: 'Удалить профиль?', text: `Профиль «${item.title}» будет удалён безвозвратно.`, confirmText: 'Удалить', danger: true });
    if (!ok) return;
    try {
      await deletePayProfile(state.venueId, item.id);
      if (String(inlineState.selectedProfileId || '') === String(item.id)) inlineState.selectedProfileId = null;
      await loadInlinePayProfiles({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
      toast('Профиль удалён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось удалить профиль', 'err');
    }
  }));

  document.getElementById('inlineComponentType')?.addEventListener('change', () => {
    const titleEl = document.getElementById('inlineComponentTitle');
    if (titleEl && !String(titleEl.value || '').trim()) titleEl.value = defaultPayComponentTitle(document.getElementById('inlineComponentType')?.value || '');
    syncInlinePayComponentFields();
  });
  syncInlinePayComponentFields();

  document.getElementById('btnInlineCancelComponentEdit')?.addEventListener('click', async () => {
    inlineState.componentEditor = { mode: 'create', id: null };
    await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
  });

  host.querySelectorAll('[data-inline-edit-component]').forEach((btn) => btn.addEventListener('click', async () => {
    inlineState.componentEditor = { mode: 'edit', id: btn.getAttribute('data-inline-edit-component') || null };
    await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
  }));

  host.querySelectorAll('[data-inline-delete-component]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-inline-delete-component') || '';
    if (!inlineState.selectedProfileId) return;
    const detail = await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
    const item = (detail?.components || []).find((row) => String(row.id) === String(id));
    if (!item) return;
    const ok = await confirmModal({ title: 'Удалить компонент?', text: `Компонент «${item.title || defaultPayComponentTitle(item.component_type)}» будет удалён.`, confirmText: 'Удалить', danger: true });
    if (!ok) return;
    try {
      await deletePayComponent(state.venueId, item.id);
      inlineState.componentEditor = { mode: 'create', id: null };
      await loadInlinePayProfiles({ force: true });
      await loadInlinePayProfileDetail(inlineState.selectedProfileId, { force: true });
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
      toast('Компонент удалён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось удалить компонент', 'err');
    }
  }));

  document.getElementById('btnInlineSaveComponent')?.addEventListener('click', async () => {
    const profileId = inlineState.selectedProfileId;
    if (!profileId) return toast('Сначала выбери профиль', 'err');
    const type = String(document.getElementById('inlineComponentType')?.value || 'SALARY_FIXED_MONTH').toUpperCase();
    const title = String(document.getElementById('inlineComponentTitle')?.value || '').trim() || defaultPayComponentTitle(type);
    const is_active = String(document.getElementById('inlineComponentActive')?.value || '1') === '1';
    const payload = { component_type: type, title, is_active };
    try {
      if (type === 'SALARY_FIXED_MONTH' || type === 'SALARY_PER_SHIFT' || type === 'KPI_BONUS') {
        const amount_minor = parseMoneyRubToMinor(document.getElementById('inlineComponentAmount')?.value || '');
        if (amount_minor == null) return toast('Укажи сумму', 'err');
        payload.amount_minor = amount_minor;
      }
      if (type === 'SALARY_HOURLY') {
        const rate_minor = parseMoneyRubToMinor(document.getElementById('inlineComponentRate')?.value || '');
        if (rate_minor == null) return toast('Укажи ставку', 'err');
        payload.rate_minor = rate_minor;
      }
      if (type === 'PERCENT_TOTAL_REVENUE' || type === 'PERCENT_DEPARTMENT_REVENUE') {
        const percent_bps = parsePercentInputToBps(document.getElementById('inlineComponentPercent')?.value || '');
        if (percent_bps == null) return toast('Укажи процент', 'err');
        payload.percent_bps = percent_bps;
      }
      if (type === 'PERCENT_DEPARTMENT_REVENUE') {
        const departmentId = Number(document.getElementById('inlineComponentDepartmentId')?.value || 0);
        if (!departmentId) return toast('Выбери департамент', 'err');
        payload.department_id = departmentId;
      }
      if (type === 'KPI_BONUS') {
        const kpiMetricId = Number(document.getElementById('inlineComponentKpiMetricId')?.value || 0);
        if (!kpiMetricId) return toast('Выбери KPI', 'err');
        payload.kpi_metric_id = kpiMetricId;
      }
      if (inlineState.componentEditor?.id) await updatePayComponent(state.venueId, inlineState.componentEditor.id, payload);
      else await createPayComponent(state.venueId, profileId, payload);
      inlineState.componentEditor = { mode: 'create', id: null };
      await loadInlinePayProfiles({ force: true });
      await loadInlinePayProfileDetail(profileId, { force: true });
      await mountPayProfilesEditor(getStepByKey('pay_profiles') || currentStep);
      toast('Компонент сохранён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось сохранить компонент', 'err');
    }
  });

  document.getElementById('btnInlineCompleteProfiles')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'pay_profiles' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineCompleteProfilesNext')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'pay_profiles' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
      const next = getAdjacentUnlockedStep(getVisibleSteps(), 'pay_profiles', 1);
      if (next) moveToStep(next.key);
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });
}

function renderPermissionChecklist(selectedCodes = []) {
  const groups = Array.isArray(state.permissionsCatalog) && state.permissionsCatalog.length ? state.permissionsCatalog : buildDefaultPermissionsCatalog();
  const selected = new Set(parsePermissionCodes(selectedCodes));
  return groups.map((group) => `
    <div class="card" style="padding:12px">
      <div class="perm-group-title">
        <div>
          <b>${esc(group.title)}</b>
          ${group.hint ? `<div class="muted mt-6" style="font-size:12px">${esc(group.hint)}</div>` : ''}
        </div>
        <div class="row" style="gap:6px; flex:0 0 auto">
          <button class="btn sm" type="button" data-preset-group="${esc(group.key)}" data-value="1">Все</button>
          <button class="btn sm" type="button" data-preset-group="${esc(group.key)}" data-value="0">Ничего</button>
        </div>
      </div>
      ${(group.items || []).map((item) => `
        <div class="perm-row">
          <div class="perm-text">
            <div class="perm-title">${esc(item.title)}</div>
            ${item.description ? `<div class="perm-desc">${esc(item.description)}</div>` : ''}
          </div>
          <label class="switch">
            <input type="checkbox" data-preset-perm-code="${esc(item.code)}" data-preset-perm-group="${esc(group.key)}" ${selected.has(String(item.code).toUpperCase()) ? 'checked' : ''} />
            <span class="slider"></span>
          </label>
        </div>
      `).join('')}
    </div>
  `).join('');
}

function collectPresetPermissionCodes(host) {
  return Array.from(host.querySelectorAll('input[data-preset-perm-code]:checked'))
    .map((el) => String(el.getAttribute('data-preset-perm-code') || '').trim().toUpperCase())
    .filter(Boolean);
}

function renderPositionPresetForm(preset) {
  const templateId = preset?.template_id || "";
  return `
    <div class="setup-formgrid mt-12">
      <label>
        <span>Название должности</span>
        <input class="input" id="positionPresetTitle" placeholder="Например, Бармен" value="${esc(preset?.title || '')}" />
      </label>
      <label>
        <span>Профиль зарплаты</span>
        <select class="input" id="positionPresetPayProfile">${buildPayProfileOptions(preset?.pay_profile_id || '')}</select>
      </label>
      <label style="grid-column:1 / -1">
        <span>Шаблон прав</span>
        <select class="input" id="positionPresetTemplate">${buildPositionTemplateOptions(templateId)}</select>
      </label>
    </div>
    <div id="positionPresetTemplateSummary" class="itemcard" style="margin-top:12px; padding:10px 12px">${renderPositionTemplateSummary(templateId)}</div>
    <div class="setup-inline-note">На этом этапе ты создаёшь именно заготовки должностей. Людей на них назначим на следующем шаге через приглашения.</div>
    <div style="margin-top:12px; display:grid; grid-template-columns:1fr; gap:10px">${renderPermissionChecklist(preset?.permission_codes || [])}</div>
  `;
}

function renderPositionsEditor(currentStep) {
  const presets = getPositionPresets();
  const inlineState = state.inline.positions;
  const editingId = inlineState.editorId || '';
  const editing = presets.find((item) => String(item.id) === String(editingId)) || null;
  return `
    <div class="setup-editor__panel">
      <div class="setup-editor__toolbar">
        <div class="setup-editor__title">Заготовки должностей</div>
      </div>
      <div class="setup-editor__grid mt-12">
        <div>
          <div class="setup-editor__title">Заготовки должностей</div>
          <div class="setup-minirows mt-8">
            ${presets.length ? presets.map((item) => `
              <div class="setup-minirow">
                <div class="setup-minirow__main">
                  <div class="setup-minirow__titlewrap">
                    <b>${esc(item.title)}</b>
                    ${item.is_active ? '' : '<span class="badge">архив</span>'}
                  </div>
                  <div class="setup-minirow__meta">${item.pay_profile_title ? `Профиль: ${esc(item.pay_profile_title)}` : 'Профиль пока не выбран'}${item.template_title ? ` · Шаблон: ${esc(item.template_title)}` : ''}</div>
                </div>
                <div class="setup-minirow__actions">
                  <button class="btn sm" type="button" data-edit-preset="${esc(item.id)}">Изменить</button>
                  <button class="btn sm ${item.is_active ? 'danger' : ''}" type="button" data-toggle-preset="${esc(item.id)}">${item.is_active ? 'В архив' : 'Вернуть'}</button>
                  <button class="btn sm danger" type="button" data-delete-preset="${esc(item.id)}">Удалить</button>
                </div>
              </div>
            `).join('') : '<div class="setup-empty">Пока нет заготовок должностей. Создай хотя бы одну должность, чтобы потом быстро назначать её приглашённым сотрудникам.</div>'}
          </div>
        </div>
        <div class="setup-formcard">
          <div class="setup-editor__title">${editing ? 'Редактирование должности' : 'Новая должность'}</div>
          <div class="muted mt-6">На этом шаге должности создаются без привязки к конкретным людям. На следующем шаге их можно будет назначать прямо в приглашении.</div>
          ${renderPositionPresetForm(editing)}
          <div class="setup-actionbar mt-12">
            <button class="btn primary" id="btnSavePreset" type="button">${editing ? 'Сохранить' : 'Создать'}</button>
            ${editing ? '<button class="btn subtle" id="btnCancelPresetEdit" type="button">Отмена</button>' : ''}
          </div>
        </div>
      </div>
      <div class="setup-actionbar mt-14">
        ${presets.filter((item) => item.is_active).length > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompletePositions" type="button">Подтвердить шаг</button>' : ''}
        ${presets.filter((item) => item.is_active).length > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompletePositionsNext" type="button">Подтвердить и дальше</button>' : ''}
      </div>
    </div>
  `;
}

async function mountPositionsEditor(currentStep) {
  const host = document.getElementById('setupInlineEditor');
  if (!host) return;
  await Promise.all([ensurePermissionsCatalog(), ensurePositionPermissionTemplates()]);
  await loadInlinePayProfiles();
  host.innerHTML = renderPositionsEditor(getStepByKey('positions') || currentStep);
  const presets = getPositionPresets();

  host.querySelectorAll('[data-preset-group]').forEach((btn) => btn.addEventListener('click', () => {
    const group = btn.getAttribute('data-preset-group') || '';
    const turnOn = btn.getAttribute('data-value') === '1';
    host.querySelectorAll(`input[data-preset-perm-group="${group}"]`).forEach((el) => { el.checked = turnOn; });
  }));

  host.querySelector('#positionPresetTemplate')?.addEventListener('change', (e) => {
    const templateId = String(e?.target?.value || '').trim();
    if (!templateId) { const summary = host.querySelector('#positionPresetTemplateSummary'); if (summary) summary.innerHTML = renderPositionTemplateSummary(''); return; }
    if (applyPositionTemplateSelection(host, templateId)) toast('Шаблон применён', 'ok');
  });

  document.getElementById('btnCancelPresetEdit')?.addEventListener('click', async () => {
    state.inline.positions.editorId = null;
    await mountPositionsEditor(getStepByKey('positions') || currentStep);
  });

  document.getElementById('btnSavePreset')?.addEventListener('click', async () => {
    const title = String(document.getElementById('positionPresetTitle')?.value || '').trim();
    const payProfileIdRaw = String(document.getElementById('positionPresetPayProfile')?.value || '').trim();
    if (!title) return toast('Укажи название должности', 'err');
    const selectedProfile = (state.inline.pay_profiles.items || []).find((item) => String(item.id) === payProfileIdRaw) || null;
    const next = [...presets];
    const payload = {
      id: state.inline.positions.editorId || `preset-${Date.now()}`,
      title,
      pay_profile_id: payProfileIdRaw ? Number(payProfileIdRaw) : null,
      pay_profile_title: selectedProfile?.title || '',
      template_id: String(document.getElementById('positionPresetTemplate')?.value || '').trim() || null,
      template_title: getPositionTemplateById(String(document.getElementById('positionPresetTemplate')?.value || '').trim())?.title || null,
      permission_codes: collectPresetPermissionCodes(host),
      rate: 0,
      percent: 0,
      is_active: true,
    };
    const idx = next.findIndex((item) => String(item.id) === String(payload.id));
    if (idx >= 0) next[idx] = { ...next[idx], ...payload };
    else next.push(payload);
    try {
      await savePositionPresets(next);
      state.inline.positions.editorId = null;
      await loadSetup({ preserveSelection: true });
      await mountPositionsEditor(getStepByKey('positions') || currentStep);
      toast('Заготовка должности сохранена', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось сохранить должность', 'err');
    }
  });

  host.querySelectorAll('[data-edit-preset]').forEach((btn) => btn.addEventListener('click', async () => {
    state.inline.positions.editorId = btn.getAttribute('data-edit-preset') || null;
    await mountPositionsEditor(getStepByKey('positions') || currentStep);
  }));

  host.querySelectorAll('[data-toggle-preset]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-toggle-preset') || '';
    const next = presets.map((item) => String(item.id) === String(id) ? { ...item, is_active: !item.is_active } : item);
    try {
      await savePositionPresets(next);
      await loadSetup({ preserveSelection: true });
      await mountPositionsEditor(getStepByKey('positions') || currentStep);
      toast('Состояние должности обновлено', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось обновить должность', 'err');
    }
  }));

  host.querySelectorAll('[data-delete-preset]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-delete-preset') || '';
    const target = presets.find((item) => String(item.id) === String(id));
    if (!target) return;
    const ok = await confirmModal({ title: 'Удалить заготовку?', text: `Заготовка «${target.title}» будет удалена из мастера настройки.`, confirmText: 'Удалить', danger: true });
    if (!ok) return;
    try {
      await savePositionPresets(presets.filter((item) => String(item.id) !== String(id)));
      await loadSetup({ preserveSelection: true });
      await mountPositionsEditor(getStepByKey('positions') || currentStep);
      toast('Заготовка удалена', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось удалить заготовку', 'err');
    }
  }));

  document.getElementById('btnInlineCompletePositions')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'positions' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineCompletePositionsNext')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'positions' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
      const next = getNextStepKey('positions');
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });
}

async function loadInlineInvites({ force = false } = {}) {
  const inlineState = state.inline.invites;
  if (!force && inlineState.data) return inlineState.data;
  inlineState.loading = true;
  try {
    const data = await getVenueMembers(state.venueId);
    inlineState.data = data || { members: [], pending_invites: [] };
    return inlineState.data;
  } finally {
    inlineState.loading = false;
  }
}

function renderInvitesEditor(data, currentStep) {
  const pending = Array.isArray(data?.pending_invites) ? data.pending_invites : [];
  const members = Array.isArray(data?.members) ? data.members : [];
  return `
    <div class="setup-editor__panel">
      <div class="setup-editor__toolbar">
        <div class="setup-inline-list setup-inline-list--compact">
          <span class="setup-chip">Участников: ${members.length}</span>
          <span class="setup-chip">Ожидают: ${pending.length}</span>
        </div>
      </div>
      <div class="setup-editor__grid mt-12">
        <div>
          <div class="setup-editor__title">Ожидающие приглашения</div>
          <div class="setup-minirows mt-8">
            ${pending.length ? pending.map((item) => `
              <div class="setup-minirow">
                <div class="setup-minirow__main">
                  <div class="setup-minirow__titlewrap">
                    <b>${esc(item.contact_label || item.tg_username || item.phone || 'Приглашение')}</b>
                    <span class="badge">${esc(roleLabel(item.venue_role))}</span>
                  </div>
                  <div class="setup-minirow__meta">${esc(item.channel === 'PHONE' ? (item.phone || 'Телефон') : (item.tg_username || 'Telegram'))} · ${esc(item.default_position?.title || 'Без должности')} · Создано: ${esc(fmtDateTime(item.created_at))}</div>
                </div>
                <div class="setup-minirow__actions">
                  <select class="input" data-invite-preset="${esc(item.id)}" style="max-width:220px">${buildPresetOptionList(item.default_position?.id || '')}</select>
                  <button class="btn sm" type="button" data-apply-invite-preset="${esc(item.id)}">Назначить</button>
                  <button class="btn sm danger" type="button" data-delete-invite="${esc(item.id)}">Отменить</button>
                </div>
              </div>
            `).join('') : '<div class="setup-empty">Пока нет приглашений. Можно пригласить людей сейчас или отложить этот шаг.</div>'}
          </div>
          ${members.length ? `<div class="setup-inline-note">Уже в заведении: ${members.map((item) => esc(memberDisplayName(item))).join(', ')}</div>` : ''}
        </div>
        <div class="setup-formcard">
          <div class="setup-editor__title">Новое приглашение</div>
          <div class="muted mt-6">Можно пригласить по Telegram или по телефону и сразу заранее назначить должность.</div>
          <div class="setup-formgrid mt-12">
            <label>
              <span>Канал</span>
              <select class="input" id="inviteChannel">
                <option value="TELEGRAM">Telegram</option>
                <option value="PHONE">Телефон</option>
              </select>
            </label>
            <label>
              <span>Роль</span>
              <select class="input" id="inviteRole">
                <option value="STAFF">Сотрудник</option>
                <option value="OWNER">Владелец</option>
              </select>
            </label>
            <label id="inviteTelegramWrap">
              <span>Ник в Telegram</span>
              <input class="input" id="inviteTelegram" placeholder="@username" />
            </label>
            <label id="invitePhoneWrap" style="display:none">
              <span>Телефон</span>
              <input class="input" id="invitePhone" placeholder="+7 ..." />
            </label>
            <label>
              <span>Контакт / имя</span>
              <input class="input" id="inviteContactLabel" placeholder="Например, Иван" />
            </label>
            <label>
              <span>Назначить должность</span>
              <select class="input" id="invitePresetSelect">${buildPresetOptionList('')}</select>
            </label>
          </div>
          <div class="setup-actionbar mt-12">
            <button class="btn primary" id="btnCreateInviteInline" type="button">Создать приглашение</button>
            <button class="btn subtle" id="btnReloadInvitesInline" type="button">Обновить список</button>
          </div>
        </div>
      </div>
      <div class="setup-actionbar mt-14">
        ${pending.length > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteInvites" type="button">Подтвердить шаг</button>' : ''}
        ${pending.length > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteInvitesNext" type="button">Подтвердить и дальше</button>' : ''}
        ${!currentStep.completed && !currentStep.skipped ? '<button class="btn subtle" id="btnInlineSkipInvites" type="button">Приглашу позже</button>' : ''}
      </div>
    </div>
  `;
}

async function mountInvitesEditor(currentStep) {
  const host = document.getElementById('setupInlineEditor');
  if (!host) return;
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  const data = await loadInlineInvites();
  host.innerHTML = renderInvitesEditor(data, getStepByKey('invites') || currentStep);
  const syncChannel = () => {
    const channel = String(document.getElementById('inviteChannel')?.value || 'TELEGRAM').toUpperCase();
    const tgWrap = document.getElementById('inviteTelegramWrap');
    const phWrap = document.getElementById('invitePhoneWrap');
    if (tgWrap) tgWrap.style.display = channel === 'TELEGRAM' ? '' : 'none';
    if (phWrap) phWrap.style.display = channel === 'PHONE' ? '' : 'none';
  };
  document.getElementById('inviteChannel')?.addEventListener('change', syncChannel);
  syncChannel();

  document.getElementById('btnReloadInvitesInline')?.addEventListener('click', async () => {
    await loadInlineInvites({ force: true });
    await loadSetup({ preserveSelection: true });
    await mountInvitesEditor(getStepByKey('invites') || currentStep);
    toast('Список обновлён', 'ok');
  });

  document.getElementById('btnCreateInviteInline')?.addEventListener('click', async () => {
    const channel = String(document.getElementById('inviteChannel')?.value || 'TELEGRAM').toUpperCase();
    const venue_role = String(document.getElementById('inviteRole')?.value || 'STAFF').toUpperCase();
    const contact_label = String(document.getElementById('inviteContactLabel')?.value || '').trim() || null;
    const body = { invite_channel: channel, venue_role, contact_label };
    if (channel === 'PHONE') {
      const phone = String(document.getElementById('invitePhone')?.value || '').trim();
      if (!phone) return toast('Укажи телефон', 'err');
      body.phone = phone;
    } else {
      const tg = String(document.getElementById('inviteTelegram')?.value || '').trim();
      if (!tg) return toast('Укажи Telegram', 'err');
      body.tg_username = tg;
    }
    const selectedPresetId = String(document.getElementById('invitePresetSelect')?.value || '').trim();
    const selectedPreset = getPositionPresets().find((item) => String(item.id) === selectedPresetId) || null;
    try {
      const out = await api(`/venues/${encodeURIComponent(state.venueId)}/invites`, { method: 'POST', body });
      if (out?.invite_id && selectedPreset) {
        await patchInviteDefaultPosition(state.venueId, out.invite_id, {
          title: selectedPreset.title,
          rate: Number(selectedPreset.rate || 0) || 0,
          percent: Number(selectedPreset.percent || 0) || 0,
          pay_profile_id: selectedPreset.pay_profile_id || null,
          pay_profile_title: selectedPreset.pay_profile_title || null,
          permission_codes: selectedPreset.permission_codes || [],
        });
      }
      await loadInlineInvites({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountInvitesEditor(getStepByKey('invites') || currentStep);
      toast(out?.mode === 'member_added' ? 'Участник добавлен' : 'Приглашение создано', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось создать приглашение', 'err');
    }
  });

  host.querySelectorAll('[data-apply-invite-preset]').forEach((btn) => btn.addEventListener('click', async () => {
    const inviteId = btn.getAttribute('data-apply-invite-preset') || '';
    const select = host.querySelector(`[data-invite-preset="${inviteId}"]`);
    const presetId = String(select?.value || '').trim();
    const selectedPreset = getPositionPresets().find((item) => String(item.id) === presetId) || null;
    try {
      await patchInviteDefaultPosition(state.venueId, inviteId, selectedPreset ? {
        title: selectedPreset.title,
        rate: Number(selectedPreset.rate || 0) || 0,
        percent: Number(selectedPreset.percent || 0) || 0,
        pay_profile_id: selectedPreset.pay_profile_id || null,
        pay_profile_title: selectedPreset.pay_profile_title || null,
        permission_codes: selectedPreset.permission_codes || [],
      } : null);
      await loadInlineInvites({ force: true });
      await mountInvitesEditor(getStepByKey('invites') || currentStep);
      toast(selectedPreset ? 'Должность назначена приглашению' : 'Должность снята', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось обновить приглашение', 'err');
    }
  }));

  host.querySelectorAll('[data-delete-invite]').forEach((btn) => btn.addEventListener('click', async () => {
    const inviteId = btn.getAttribute('data-delete-invite') || '';
    const ok = await confirmModal({ title: 'Отменить приглашение?', text: 'Приглашение станет недействительным.', confirmText: 'Отменить', danger: true });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/invites/${encodeURIComponent(inviteId)}`, { method: 'DELETE' });
      await loadInlineInvites({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountInvitesEditor(getStepByKey('invites') || currentStep);
      toast('Приглашение отменено', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось отменить приглашение', 'err');
    }
  }));

  document.getElementById('btnInlineCompleteInvites')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'invites' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineCompleteInvitesNext')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'invites' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
      const next = getNextStepKey('invites');
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineSkipInvites')?.addEventListener('click', async () => {
    const ok = await confirmModal({ title: 'Пригласить позже?', text: 'Этот шаг будет помечен как отложенный. К нему можно вернуться в любой момент.', confirmText: 'Отложить', danger: false });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, { method: 'POST', body: { step_key: 'invites' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг отложен', 'ok');
      const next = getNextStepKey('invites');
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось отложить шаг', 'err');
    }
  });
}

async function loadInlineShiftIntervals({ force = false } = {}) {
  const inlineState = state.inline.shift_intervals;
  if (!force && Array.isArray(inlineState.items)) return inlineState.items;
  inlineState.loading = true;
  try {
    const items = await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals?include_inactive=true`);
    inlineState.items = Array.isArray(items) ? items : [];
    return inlineState.items;
  } finally {
    inlineState.loading = false;
  }
}

function renderShiftIntervalsEditor(items, currentStep) {
  const inlineState = state.inline.shift_intervals;
  const cfg = { listLabel: "Настроенные интервалы смен" };
  const visibleItems = inlineState.showArchived ? items : items.filter((item) => item.is_active !== false);
  const editingId = inlineState.editor?.id || null;
  const editing = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
  const activeCount = items.filter((item) => item.is_active !== false).length;
  return `
    <div class="setup-editor__panel">
      <div class="setup-editor__toolbar">
        <div class="setup-editor__title">${esc(cfg.listLabel)}</div>
        <label class="setup-toggle">
          <input type="checkbox" id="inlineShowArchivedIntervals" ${inlineState.showArchived ? 'checked' : ''} />
          <span>Показывать архив</span>
        </label>
      </div>
      <div class="setup-editor__grid mt-12">
        <div>
          <div class="setup-editor__title">Интервалы смен</div>
          <div class="setup-minirows mt-8">
            ${visibleItems.length ? visibleItems.map((item) => `
              <div class="setup-minirow">
                <div class="setup-minirow__main">
                  <div class="setup-minirow__titlewrap">
                    <b>${esc(item.title)}</b>
                    ${item.is_active === false ? '<span class="badge">архив</span>' : ''}
                  </div>
                  <div class="setup-minirow__meta">${esc(item.start_time)}–${esc(item.end_time)} · Смен: ${Number(item.usage_count || 0)}</div>
                </div>
                <div class="setup-minirow__actions">
                  <button class="btn sm" type="button" data-edit-interval="${esc(item.id)}">Изменить</button>
                  <button class="btn sm ${item.is_active === false ? '' : 'danger'}" type="button" data-toggle-interval="${esc(item.id)}">${item.is_active === false ? 'Вернуть' : 'В архив'}</button>
                  ${item.can_delete ? `<button class="btn sm danger" type="button" data-delete-interval="${esc(item.id)}">Удалить</button>` : ''}
                </div>
              </div>
            `).join('') : '<div class="setup-empty">Пока нет интервалов. Добавь хотя бы один, чтобы график и часть зарплатной логики были готовы к работе.</div>'}
          </div>
        </div>
        <div class="setup-formcard">
          <div class="setup-editor__title">${editing ? 'Редактирование интервала' : 'Новый интервал'}</div>
          <div class="muted mt-6">Интервалы используются в графике и могут участвовать в расчётах начислений.</div>
          <div class="setup-formgrid mt-12">
            <label>
              <span>Название</span>
              <input class="input" id="intervalTitle" placeholder="Например, Вечер" value="${esc(editing?.title || '')}" />
            </label>
            <label>
              <span>Активность</span>
              <select class="input" id="intervalActive">
                <option value="1" ${(editing?.is_active === false) ? '' : 'selected'}>Активен</option>
                <option value="0" ${(editing?.is_active === false) ? 'selected' : ''}>Неактивен</option>
              </select>
            </label>
            <label>
              <span>Начало</span>
              <input class="input" id="intervalStart" type="time" value="${esc(editing?.start_time || '')}" />
            </label>
            <label>
              <span>Окончание</span>
              <input class="input" id="intervalEnd" type="time" value="${esc(editing?.end_time || '')}" />
            </label>
          </div>
          <div class="setup-actionbar mt-12">
            <button class="btn primary" id="btnSaveIntervalInline" type="button">${editing ? 'Сохранить' : 'Создать'}</button>
            ${editing ? '<button class="btn subtle" id="btnCancelIntervalEdit" type="button">Отмена</button>' : ''}
            <button class="btn subtle" id="btnReloadIntervalsInline" type="button">Обновить список</button>
          </div>
        </div>
      </div>
      <div class="setup-actionbar mt-14">
        ${activeCount > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteIntervals" type="button">Подтвердить шаг</button>' : ''}
        ${activeCount > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteIntervalsNext" type="button">Подтвердить и дальше</button>' : ''}
      </div>
    </div>
  `;
}

async function mountShiftIntervalsEditor(currentStep) {
  const host = document.getElementById('setupInlineEditor');
  if (!host) return;
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  const items = await loadInlineShiftIntervals();
  if (Number(currentStep.count || 0) !== items.filter((item) => item.is_active !== false).length) {
    await loadSetup({ preserveSelection: true });
    return;
  }
  host.innerHTML = renderShiftIntervalsEditor(items, getStepByKey('shift_intervals') || currentStep);
  const inlineState = state.inline.shift_intervals;

  document.getElementById('inlineShowArchivedIntervals')?.addEventListener('change', async (e) => {
    inlineState.showArchived = !!e.target?.checked;
    await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
  });

  document.getElementById('btnReloadIntervalsInline')?.addEventListener('click', async () => {
    await loadInlineShiftIntervals({ force: true });
    await loadSetup({ preserveSelection: true });
    await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
    toast('Список обновлён', 'ok');
  });

  document.getElementById('btnCancelIntervalEdit')?.addEventListener('click', async () => {
    inlineState.editor = { mode: 'create', id: null };
    await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
  });

  document.getElementById('btnSaveIntervalInline')?.addEventListener('click', async () => {
    const title = String(document.getElementById('intervalTitle')?.value || '').trim();
    const start_time = String(document.getElementById('intervalStart')?.value || '').trim();
    const end_time = String(document.getElementById('intervalEnd')?.value || '').trim();
    const is_active = String(document.getElementById('intervalActive')?.value || '1') === '1';
    if (!title) return toast('Укажи название интервала', 'err');
    if (!/^\d{2}:\d{2}$/.test(start_time)) return toast('Укажи время начала', 'err');
    if (!/^\d{2}:\d{2}$/.test(end_time)) return toast('Укажи время окончания', 'err');
    try {
      if (inlineState.editor?.id) {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(inlineState.editor.id)}`, { method: 'PATCH', body: { title, start_time, end_time, is_active } });
      } else {
        await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals`, { method: 'POST', body: { title, start_time, end_time, is_active } });
      }
      inlineState.editor = { mode: 'create', id: null };
      await loadInlineShiftIntervals({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
      if (!currentStep.completed) {
        try {
          await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'shift_intervals' } });
          await loadSetup({ preserveSelection: true });
        } catch {}
      }
      toast('Интервал сохранён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось сохранить интервал', 'err');
    }
  });

  host.querySelectorAll('[data-edit-interval]').forEach((btn) => btn.addEventListener('click', async () => {
    inlineState.editor = { mode: 'edit', id: btn.getAttribute('data-edit-interval') || null };
    await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
  }));

  host.querySelectorAll('[data-toggle-interval]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-toggle-interval') || '';
    const item = (state.inline.shift_intervals.items || []).find((row) => String(row.id) === String(id));
    if (!item) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: { is_active: !(item.is_active !== false) } });
      await loadInlineShiftIntervals({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
      toast('Интервал обновлён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось обновить интервал', 'err');
    }
  }));

  host.querySelectorAll('[data-delete-interval]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-delete-interval') || '';
    const ok = await confirmModal({ title: 'Удалить интервал?', text: 'Интервал будет удалён без возможности восстановления.', confirmText: 'Удалить', danger: true });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/shift-intervals/${encodeURIComponent(id)}`, { method: 'DELETE' });
      await loadInlineShiftIntervals({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountShiftIntervalsEditor(getStepByKey('shift_intervals') || currentStep);
      toast('Интервал удалён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось удалить интервал', 'err');
    }
  }));

  document.getElementById('btnInlineCompleteIntervals')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'shift_intervals' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineCompleteIntervalsNext')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'shift_intervals' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
      const next = getNextStepKey('shift_intervals');
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });
}


async function loadInlineSuppliers({ force = false } = {}) {
  const inlineState = state.inline.suppliers;
  if (!force && Array.isArray(inlineState.items)) return inlineState.items;
  inlineState.loading = true;
  try {
    const items = await api(`/venues/${encodeURIComponent(state.venueId)}/suppliers?include_archived=true`);
    inlineState.items = Array.isArray(items) ? items : [];
    return inlineState.items;
  } finally {
    inlineState.loading = false;
  }
}

function renderSuppliersEditor(items, currentStep) {
  const inlineState = state.inline.suppliers;
  const cfg = { listLabel: "Настроенные поставщики" };
  const showArchived = !!inlineState.showArchived;
  const visibleItems = showArchived ? items : items.filter((item) => item.is_active !== false);
  const activeCount = items.filter((item) => item.is_active !== false).length;
  const editingId = inlineState.editor?.id;
  const editing = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
  return `
    <div class="setup-editor__panel">
      <div class="setup-editor__toolbar">
        <div class="setup-editor__title">${esc(cfg.listLabel)}</div>
        <label class="setup-toggle">
          <input type="checkbox" id="inlineShowArchivedSuppliers" ${showArchived ? "checked" : ""} />
          <span>Показывать архив</span>
        </label>
      </div>
      <div class="setup-editor__grid mt-12">
        <div>
          <div class="setup-editor__title">Настроенные поставщики</div>
          <div class="setup-minirows mt-8">
            ${visibleItems.length ? visibleItems.map((item) => `
              <div class="setup-minirow">
                <div class="setup-minirow__main">
                  <div class="setup-minirow__titlewrap">
                    <b>${esc(item.title)}</b>
                    ${item.is_active === false ? '<span class="badge">архив</span>' : ''}
                  </div>
                  <div class="setup-minirow__meta">${esc(item.contact || 'Контакты не указаны')}</div>
                </div>
                <div class="setup-minirow__actions">
                  <button class="btn sm" type="button" data-edit-supplier="${esc(item.id)}">Изменить</button>
                  <button class="btn sm ${item.is_active === false ? '' : 'danger'}" type="button" data-toggle-supplier="${esc(item.id)}">${item.is_active === false ? 'Вернуть' : 'В архив'}</button>
                </div>
              </div>`).join('') : '<div class="setup-empty">Пока нет поставщиков. Этот шаг можно отложить и вернуться позже.</div>'}
          </div>
        </div>
        <div class="setup-formcard">
          <div class="setup-editor__title">${editing ? 'Редактировать поставщика' : 'Новый поставщик'}</div>
          <div class="muted mt-6">Поставщики ускоряют занесение расходов и помогают держать закупки в порядке.</div>
          <div class="setup-formgrid mt-12">
            <label>
              <span>Название</span>
              <input class="input" id="supplierTitle" placeholder="Например, ООО Поставщик" value="${esc(editing?.title || '')}" />
            </label>
            <label>
              <span>Контакт</span>
              <input class="input" id="supplierContact" placeholder="Телефон, Telegram, email" value="${esc(editing?.contact || '')}" />
            </label>
            <label>
              <span>Активность</span>
              <select class="input" id="supplierActive">
                <option value="1" ${editing?.is_active === false ? '' : 'selected'}>Активен</option>
                <option value="0" ${editing?.is_active === false ? 'selected' : ''}>Неактивен</option>
              </select>
            </label>
          </div>
          <div class="setup-actionbar mt-12">
            <button class="btn primary" id="btnSaveSupplierInline" type="button">${editing ? 'Сохранить' : 'Создать'}</button>
            ${editing ? '<button class="btn subtle" id="btnCancelSupplierEdit" type="button">Отмена</button>' : ''}
            <button class="btn subtle" id="btnReloadSuppliersInline" type="button">Обновить список</button>
          </div>
        </div>
      </div>
      <div class="setup-actionbar mt-14">
        ${activeCount > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteSuppliers" type="button">Подтвердить шаг</button>' : ''}
        ${activeCount > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteSuppliersNext" type="button">Подтвердить и дальше</button>' : ''}
        ${!currentStep.completed && !currentStep.skipped ? '<button class="btn subtle" id="btnInlineSkipSuppliers" type="button">Поставщиков добавлю позже</button>' : ''}
      </div>
    </div>
  `;
}

async function mountSuppliersEditor(currentStep) {
  const host = document.getElementById('setupInlineEditor');
  if (!host) return;
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  const items = await loadInlineSuppliers();
  if (Number(currentStep.count || 0) !== items.filter((item) => item.is_active !== false).length && !currentStep.skipped) {
    await loadSetup({ preserveSelection: true });
    return;
  }
  host.innerHTML = renderSuppliersEditor(items, getStepByKey('suppliers') || currentStep);
  const inlineState = state.inline.suppliers;

  document.getElementById('inlineShowArchivedSuppliers')?.addEventListener('change', async (e) => {
    inlineState.showArchived = !!e.target?.checked;
    await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
  });

  document.getElementById('btnReloadSuppliersInline')?.addEventListener('click', async () => {
    await loadInlineSuppliers({ force: true });
    await loadSetup({ preserveSelection: true });
    await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
    toast('Список обновлён', 'ok');
  });

  document.getElementById('btnCancelSupplierEdit')?.addEventListener('click', async () => {
    inlineState.editor = { mode: 'create', id: null };
    await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
  });

  document.getElementById('btnSaveSupplierInline')?.addEventListener('click', async () => {
    const title = String(document.getElementById('supplierTitle')?.value || '').trim();
    const contact = String(document.getElementById('supplierContact')?.value || '').trim() || null;
    const is_active = String(document.getElementById('supplierActive')?.value || '1') === '1';
    if (!title) return toast('Укажи название поставщика', 'err');
    const sortOrderBase = Math.max(0, ...(items || []).map((item) => Number(item.sort_order || 0))) || 0;
    const payload = { title, contact, is_active, sort_order: inlineState.editor?.id ? undefined : (sortOrderBase + 10) };
    try {
      if (inlineState.editor?.id) await api(`/venues/${encodeURIComponent(state.venueId)}/suppliers/${encodeURIComponent(inlineState.editor.id)}`, { method: 'PATCH', body: payload });
      else await api(`/venues/${encodeURIComponent(state.venueId)}/suppliers`, { method: 'POST', body: payload });
      inlineState.editor = { mode: 'create', id: null };
      await loadInlineSuppliers({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
      if (!currentStep.completed) {
        try {
          await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'suppliers' } });
          await loadSetup({ preserveSelection: true });
        } catch {}
      }
      toast('Поставщик сохранён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось сохранить поставщика', 'err');
    }
  });

  host.querySelectorAll('[data-edit-supplier]').forEach((btn) => btn.addEventListener('click', async () => {
    inlineState.editor = { mode: 'edit', id: btn.getAttribute('data-edit-supplier') || null };
    await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
  }));

  host.querySelectorAll('[data-toggle-supplier]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-toggle-supplier') || '';
    const item = (state.inline.suppliers.items || []).find((row) => String(row.id) === String(id));
    if (!item) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/suppliers/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: { is_active: !(item.is_active !== false) } });
      await loadInlineSuppliers({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountSuppliersEditor(getStepByKey('suppliers') || currentStep);
      toast('Поставщик обновлён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось обновить поставщика', 'err');
    }
  }));

  document.getElementById('btnInlineCompleteSuppliers')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'suppliers' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineCompleteSuppliersNext')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'suppliers' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
      const next = getNextStepKey('suppliers');
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineSkipSuppliers')?.addEventListener('click', async () => {
    const ok = await confirmModal({ title: 'Отложить поставщиков?', text: 'Этот шаг можно завершить позже без потери прогресса мастера.', confirmText: 'Отложить', danger: false });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, { method: 'POST', body: { step_key: 'suppliers' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг отложен', 'ok');
      const next = getNextStepKey('suppliers');
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось отложить шаг', 'err');
    }
  });
}

async function loadInlineRecurringExpenses({ force = false } = {}) {
  const inlineState = state.inline.recurring_expenses;
  if (!force && Array.isArray(inlineState.items) && Array.isArray(inlineState.categories) && Array.isArray(inlineState.suppliers) && Array.isArray(inlineState.paymentMethods)) return inlineState;
  inlineState.loading = true;
  try {
    const [items, categories, suppliers, paymentMethods] = await Promise.all([
      api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules`),
      api(`/venues/${encodeURIComponent(state.venueId)}/expense-categories`),
      api(`/venues/${encodeURIComponent(state.venueId)}/suppliers`),
      getPaymentMethods(state.venueId, { includeArchived: false }).catch(() => []),
    ]);
    inlineState.items = Array.isArray(items) ? items : [];
    inlineState.categories = Array.isArray(categories) ? categories : [];
    inlineState.suppliers = Array.isArray(suppliers) ? suppliers : [];
    inlineState.paymentMethods = Array.isArray(paymentMethods) ? paymentMethods : [];
    return inlineState;
  } finally {
    inlineState.loading = false;
  }
}

function renderRecurringExpensesEditor(data, currentStep) {
  const items = Array.isArray(data?.items) ? data.items : [];
  const categories = Array.isArray(data?.categories) ? data.categories : [];
  const suppliers = Array.isArray(data?.suppliers) ? data.suppliers : [];
  const paymentMethods = Array.isArray(data?.paymentMethods) ? data.paymentMethods : [];
  const inlineState = state.inline.recurring_expenses;
  const showInactive = !!inlineState.showInactive;
  const visibleItems = showInactive ? items : items.filter((item) => item.is_active !== false);
  const activeCount = items.filter((item) => item.is_active !== false).length;
  const editingId = inlineState.editor?.id;
  const editing = editingId ? items.find((item) => String(item.id) === String(editingId)) : null;
  const isPercent = String(editing?.generation_mode || 'FIXED').toUpperCase() === 'PERCENT';
  return `
    <div class="setup-editor__panel">
      <div class="setup-editor__toolbar">
        <div class="setup-editor__title">Правила регулярных расходов</div>
        <label class="setup-toggle">
          <input type="checkbox" id="inlineShowInactiveRecurring" ${showInactive ? 'checked' : ''} />
          <span>Показывать неактивные</span>
        </label>
      </div>
      <div class="setup-editor__grid mt-12">
        <div>
          <div class="setup-editor__title">Правила регулярных расходов</div>
          <div class="setup-minirows mt-8">
            ${visibleItems.length ? visibleItems.map((item) => `
              <div class="setup-minirow">
                <div class="setup-minirow__main">
                  <div class="setup-minirow__titlewrap">
                    <b>${esc(item.title || 'Без названия')}</b>
                    <span class="badge">${esc(recurringModeLabel(item.generation_mode))}</span>
                    ${item.is_active === false ? '<span class="badge">выключено</span>' : ''}
                  </div>
                  <div class="setup-minirow__meta">${esc(item.category?.title || 'Без категории')} · день ${esc(item.day_of_month || 1)} · ${String(item.generation_mode || 'FIXED').toUpperCase() === 'PERCENT' ? `${esc(minorToMoneyInput(item.percent_bps || 0))}%` : `${esc(minorToMoneyInput(item.amount_minor || 0))} ₽`}</div>
                </div>
                <div class="setup-minirow__actions">
                  <button class="btn sm" type="button" data-edit-recurring="${esc(item.id)}">Изменить</button>
                  <button class="btn sm ${item.is_active === false ? '' : 'danger'}" type="button" data-toggle-recurring="${esc(item.id)}">${item.is_active === false ? 'Включить' : 'Выключить'}</button>
                  <button class="btn sm danger" type="button" data-delete-recurring="${esc(item.id)}">Удалить</button>
                </div>
              </div>`).join('') : '<div class="setup-empty">Пока нет правил. Можно добавить первое правило прямо здесь или отложить шаг на потом.</div>'}
          </div>
        </div>
        <div class="setup-formcard">
          <div class="setup-editor__title">${editing ? 'Редактировать правило' : 'Новое правило'}</div>
          <div class="muted mt-6">Регулярные расходы помогают автоматизировать повторяющиеся траты без ручного ввода каждый месяц.</div>
          ${!categories.length ? '<div class="setup-inline-note mt-12">Сначала создай хотя бы одну категорию расходов, иначе правило не получится сохранить.</div>' : `
          <div class="setup-formgrid mt-12">
            <label><span>Название</span><input class="input" id="recurringTitle" placeholder="Например, аренда" value="${esc(editing?.title || '')}" /></label>
            <label><span>Категория</span><select class="input" id="recurringCategoryId">${buildSelectOptions(categories, editing?.category_id, 'Выбери категорию')}</select></label>
            <label><span>Поставщик</span><select class="input" id="recurringSupplierId">${buildSelectOptions(suppliers, editing?.supplier_id, 'Без поставщика')}</select></label>
            <label><span>Оплачивать через</span><select class="input" id="recurringPaymentMethodId">${buildSelectOptions(paymentMethods, editing?.payment_method_id, 'Не указано')}</select></label>
            <label><span>Дата старта</span><input class="input" id="recurringStartDate" type="date" value="${esc(editing?.start_date || todayIso())}" /></label>
            <label><span>Дата окончания</span><input class="input" id="recurringEndDate" type="date" value="${esc(editing?.end_date || '')}" /></label>
            <label><span>День месяца</span><input class="input" id="recurringDayOfMonth" type="number" min="1" max="31" value="${esc(editing?.day_of_month || 1)}" /></label>
            <label><span>Размазать на месяцев</span><input class="input" id="recurringSpreadMonths" type="number" min="1" max="120" value="${esc(editing?.spread_months || 1)}" /></label>
            <label><span>Режим</span><select class="input" id="recurringGenerationMode"><option value="FIXED" ${isPercent ? '' : 'selected'}>Фиксированная сумма</option><option value="PERCENT" ${isPercent ? 'selected' : ''}>Процент от оплат</option></select></label>
            <label id="recurringAmountWrap"><span>Сумма, ₽</span><input class="input" id="recurringAmount" placeholder="150000.00" value="${esc(minorToMoneyInput(editing?.amount_minor))}" /></label>
            <label id="recurringPercentWrap"><span>Процент, %</span><input class="input" id="recurringPercent" placeholder="2.50" value="${esc(minorToMoneyInput(editing?.percent_bps))}" /></label>
            <label><span>Активность</span><select class="input" id="recurringActive"><option value="1" ${editing?.is_active === false ? '' : 'selected'}>Активно</option><option value="0" ${editing?.is_active === false ? 'selected' : ''}>Неактивно</option></select></label>
            <label class="setup-formgrid__full"><span>Комментарий</span><textarea class="input" id="recurringDescription" rows="3" placeholder="Например, аренда помещения">${esc(editing?.description || '')}</textarea></label>
            <div class="setup-formgrid__full" id="recurringBasisWrap">
              <span>База для процента</span>
              <div class="finance-form mt-8">${buildBasisPaymentMethodCheckboxes(paymentMethods, editing?.payment_method_ids || [])}</div>
            </div>
          </div>
          <div class="setup-actionbar mt-12">
            <button class="btn primary" id="btnSaveRecurringInline" type="button">${editing ? 'Сохранить' : 'Создать'}</button>
            ${editing ? '<button class="btn subtle" id="btnCancelRecurringEdit" type="button">Отмена</button>' : ''}
            <button class="btn subtle" id="btnReloadRecurringInline" type="button">Обновить список</button>
          </div>`}
        </div>
      </div>
      <div class="setup-actionbar mt-14">
        ${activeCount > 0 && !currentStep.completed ? '<button class="btn" id="btnInlineCompleteRecurring" type="button">Подтвердить шаг</button>' : ''}
        ${activeCount > 0 && !currentStep.completed ? '<button class="btn subtle" id="btnInlineCompleteRecurringNext" type="button">Подтвердить и дальше</button>' : ''}
        ${!currentStep.completed && !currentStep.skipped ? '<button class="btn subtle" id="btnInlineSkipRecurring" type="button">Регулярные правила добавлю позже</button>' : ''}
      </div>
    </div>
  `;
}

function syncRecurringModeVisibility() {
  const mode = String(document.getElementById('recurringGenerationMode')?.value || 'FIXED').toUpperCase();
  const amountWrap = document.getElementById('recurringAmountWrap');
  const percentWrap = document.getElementById('recurringPercentWrap');
  const basisWrap = document.getElementById('recurringBasisWrap');
  if (amountWrap) amountWrap.style.display = mode === 'FIXED' ? '' : 'none';
  if (percentWrap) percentWrap.style.display = mode === 'PERCENT' ? '' : 'none';
  if (basisWrap) basisWrap.style.display = mode === 'PERCENT' ? '' : 'none';
}

async function mountRecurringExpensesEditor(currentStep) {
  const host = document.getElementById('setupInlineEditor');
  if (!host) return;
  host.innerHTML = '<div class="skeleton"></div><div class="skeleton"></div>';
  const data = await loadInlineRecurringExpenses();
  if (Number(currentStep.count || 0) !== (data.items || []).filter((item) => item.is_active !== false).length && !currentStep.skipped) {
    await loadSetup({ preserveSelection: true });
    return;
  }
  host.innerHTML = renderRecurringExpensesEditor(data, getStepByKey('recurring_expenses') || currentStep);
  const inlineState = state.inline.recurring_expenses;

  document.getElementById('inlineShowInactiveRecurring')?.addEventListener('change', async (e) => {
    inlineState.showInactive = !!e.target?.checked;
    await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
  });

  document.getElementById('btnReloadRecurringInline')?.addEventListener('click', async () => {
    await loadInlineRecurringExpenses({ force: true });
    await loadSetup({ preserveSelection: true });
    await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
    toast('Список обновлён', 'ok');
  });

  document.getElementById('btnCancelRecurringEdit')?.addEventListener('click', async () => {
    inlineState.editor = { mode: 'create', id: null };
    await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
  });

  document.getElementById('recurringGenerationMode')?.addEventListener('change', syncRecurringModeVisibility);
  syncRecurringModeVisibility();

  document.getElementById('btnSaveRecurringInline')?.addEventListener('click', async () => {
    if (!(data.categories || []).length) {
      toast('Сначала создай категорию расходов', 'err');
      return;
    }
    const title = String(document.getElementById('recurringTitle')?.value || '').trim();
    if (!title) return toast('Укажи название правила', 'err');
    const generationMode = String(document.getElementById('recurringGenerationMode')?.value || 'FIXED').toUpperCase();
    const payload = {
      title,
      category_id: Number(document.getElementById('recurringCategoryId')?.value || 0),
      supplier_id: document.getElementById('recurringSupplierId')?.value ? Number(document.getElementById('recurringSupplierId')?.value) : null,
      payment_method_id: document.getElementById('recurringPaymentMethodId')?.value ? Number(document.getElementById('recurringPaymentMethodId')?.value) : null,
      is_active: String(document.getElementById('recurringActive')?.value || '1') === '1',
      start_date: String(document.getElementById('recurringStartDate')?.value || todayIso()),
      end_date: String(document.getElementById('recurringEndDate')?.value || '').trim() || null,
      frequency: 'MONTHLY',
      day_of_month: Number(document.getElementById('recurringDayOfMonth')?.value || 1),
      spread_months: Number(document.getElementById('recurringSpreadMonths')?.value || 1),
      generation_mode: generationMode,
      amount_minor: generationMode === 'FIXED' ? parseMoneyToMinor(document.getElementById('recurringAmount')?.value || '') : null,
      percent_bps: generationMode === 'PERCENT' ? parseMoneyToMinor(document.getElementById('recurringPercent')?.value || '') : null,
      description: String(document.getElementById('recurringDescription')?.value || '').trim() || null,
      payment_method_ids: generationMode === 'PERCENT' ? Array.from(host.querySelectorAll('input[name="recurringBasisPaymentMethod"]:checked')).map((el) => Number(el.value)).filter((x) => Number.isFinite(x) && x > 0) : [],
    };
    if (!payload.category_id) return toast('Выбери категорию расхода', 'err');
    try {
      if (inlineState.editor?.id) await api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules/${encodeURIComponent(inlineState.editor.id)}`, { method: 'PATCH', body: payload });
      else await api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules`, { method: 'POST', body: payload });
      inlineState.editor = { mode: 'create', id: null };
      await loadInlineRecurringExpenses({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
      if (!currentStep.completed) {
        try {
          await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'recurring_expenses' } });
          await loadSetup({ preserveSelection: true });
        } catch {}
      }
      toast('Правило сохранено', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось сохранить правило', 'err');
    }
  });

  host.querySelectorAll('[data-edit-recurring]').forEach((btn) => btn.addEventListener('click', async () => {
    inlineState.editor = { mode: 'edit', id: btn.getAttribute('data-edit-recurring') || null };
    await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
  }));

  host.querySelectorAll('[data-toggle-recurring]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-toggle-recurring') || '';
    const item = (state.inline.recurring_expenses.items || []).find((row) => String(row.id) === String(id));
    if (!item) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules/${encodeURIComponent(item.id)}`, { method: 'PATCH', body: { is_active: !(item.is_active !== false) } });
      await loadInlineRecurringExpenses({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
      toast('Правило обновлено', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось обновить правило', 'err');
    }
  }));

  host.querySelectorAll('[data-delete-recurring]').forEach((btn) => btn.addEventListener('click', async () => {
    const id = btn.getAttribute('data-delete-recurring') || '';
    const ok = await confirmModal({ title: 'Удалить правило?', text: 'Правило регулярных расходов будет удалено без возможности восстановления.', confirmText: 'Удалить', danger: true });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/recurring-expense-rules/${encodeURIComponent(id)}`, { method: 'DELETE' });
      await loadInlineRecurringExpenses({ force: true });
      await loadSetup({ preserveSelection: true });
      await mountRecurringExpensesEditor(getStepByKey('recurring_expenses') || currentStep);
      toast('Правило удалено', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось удалить правило', 'err');
    }
  }));

  document.getElementById('btnInlineCompleteRecurring')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'recurring_expenses' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineCompleteRecurringNext')?.addEventListener('click', async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/complete-step`, { method: 'POST', body: { step_key: 'recurring_expenses' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг подтверждён', 'ok');
      const next = getNextStepKey('recurring_expenses');
      if (next) moveToStep(next);
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось завершить шаг', 'err');
    }
  });

  document.getElementById('btnInlineSkipRecurring')?.addEventListener('click', async () => {
    const ok = await confirmModal({ title: 'Отложить регулярные настройки?', text: 'К этому шагу можно будет спокойно вернуться после запуска заведения.', confirmText: 'Отложить', danger: false });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, { method: 'POST', body: { step_key: 'recurring_expenses' } });
      await loadSetup({ preserveSelection: true });
      toast('Шаг отложен', 'ok');
    } catch (e) {
      toast(e?.data?.detail || e?.message || 'Не удалось отложить шаг', 'err');
    }
  });
}

function wireSetupActions(currentStep, visibleSteps) {
  document.getElementById("btnSkipStep")?.addEventListener("click", async () => {
    const ok = await confirmModal({
      title: "Вернуться позже?",
      text: "Этот шаг будет помечен как отложенный. Ты сможешь вернуться к нему в любой момент.",
      confirmText: "Отложить",
      danger: false,
    });
    if (!ok) return;
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/skip-step`, {
        method: "POST",
        body: { step_key: currentStep.key },
      });
      await loadSetup({ preserveSelection: true });
      toast("Шаг отложен", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось отложить шаг", "err");
    }
  });

  document.getElementById("btnBackToPhase")?.addEventListener("click", () => {
    moveToPhase(state.selectedPhase);
  });

  document.getElementById("setupStepJumpSelect")?.addEventListener("change", (e) => {
    const value = String(e?.target?.value || "");
    if (!value || value === String(currentStep.key)) return;
    moveToStep(value);
  });

  document.getElementById("btnPrevStep")?.addEventListener("click", () => {
    const prev = getAdjacentUnlockedStep(visibleSteps, currentStep.key, -1);
    if (prev) {
      moveToStep(prev.key);
    } else {
      toast('Это первый доступный шаг этого этапа', 'warn');
    }
  });

  document.getElementById("btnNextStep")?.addEventListener("click", () => {
    const next = getAdjacentUnlockedStep(visibleSteps, currentStep.key, 1);
    if (next) {
      moveToStep(next.key);
      return;
    }
    toast('Дальше доступных шагов пока нет', 'warn');
  });

  document.getElementById("btnFinishPrepare")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/finish-prepare`, { method: "POST" });
      await loadSetup({ preserveSelection: false });
      state.selectedPhase = "EXTRA";
      moveToOverview();
      toast("Базовая настройка завершена", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось завершить базовую настройку", "err");
    }
  });

  document.getElementById("btnFinishExtra")?.addEventListener("click", async () => {
    try {
      await api(`/venues/${encodeURIComponent(state.venueId)}/setup/finish-extra`, { method: "POST" });
      await loadSetup({ preserveSelection: false });
      moveToOverview();
      toast("Мастер настройки завершён", "ok");
    } catch (e) {
      toast(e?.data?.detail || e?.message || "Не удалось завершить мастер", "err");
    }
  });

  Promise.resolve().then(() => mountInlineEditor(currentStep)).catch((e) => {
    console.error(e);
    const host = document.getElementById("setupInlineEditor");
    if (host) host.innerHTML = `<div class="setup-empty">Не удалось загрузить встроенный редактор для этого шага.</div>`;
  });
}

async function loadSetup({ preserveSelection = true } = {}) {
  if (!state.venueId) {
    state.accessError = "Заведение не выбрано.";
    renderAccessError(state.accessError);
    return;
  }
  const prevStep = preserveSelection ? state.selectedStepKey : "";
  const prevPhase = preserveSelection ? state.selectedPhase : "";
  state.setup = await api(`/venues/${encodeURIComponent(state.venueId)}/setup`);
  const urlPhase = getPhaseFromUrl();
  state.selectedPhase = String(urlPhase || prevPhase || getSetupPhase(state.setup) || "PREPARE").toUpperCase();
  const urlStep = getStepFromUrl();
  state.selectedStepKey = urlStep || prevStep || getPhaseResumeStep(state.selectedPhase)?.key || state.setup?.steps?.[0]?.key || "";
  if (getSetupStatus(state.setup) === "NOT_STARTED") {
    renderStartScreen();
    return;
  }
  renderSetup();
}

window.addEventListener("popstate", () => {
  const urlPhase = getPhaseFromUrl();
  const urlStep = getStepFromUrl();
  if (urlPhase) state.selectedPhase = urlPhase;
  if (urlStep) {
    state.selectedStepKey = urlStep;
    state.viewMode = "step";
  } else if (urlPhase) {
    state.viewMode = "phase";
  } else {
    state.viewMode = "overview";
  }
  renderSetup();
});

async function bootstrap() {
  try {
    renderLoading();
    state.venueId = parseVenueId();
    state.me = await getMe();
    state.venue = state.venueId ? await getVenueById(state.venueId) : null;
    state.perms = state.venueId ? await getMyVenuePermissions(state.venueId) : null;

    const venueRole = roleUpper(state.perms) || roleUpper(state.venue) || "";
    const sysRole = String(state.me?.system_role || "").toUpperCase();
    const isOwner = isOwnerRole(venueRole);
    const isAdmin = isSysAdminRole(sysRole);
    const billingMode = getBillingAccessMode(state.perms || state.venue || {});

    if (!state.venueId) {
      renderAccessError("Сначала выбери заведение, а потом открой мастер настройки.");
      return;
    }
    if (!(isOwner || isAdmin)) {
      renderAccessError("Открыть мастер настройки может только владелец заведения или суперадмин.");
      return;
    }
    if (billingMode && String(billingMode).toUpperCase() !== "FULL") {
      renderAccessError("При ограниченном доступе по подписке мастер настройки недоступен. Сначала продли доступ к заведению.");
      return;
    }

    await loadSetup({ preserveSelection: false });
  } catch (e) {
    const detail = e?.data?.detail || e?.message || "Не удалось открыть мастер настройки";
    renderAccessError(detail);
  }
}

await bootstrap();

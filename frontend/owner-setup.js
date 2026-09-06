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
} from "/app.js?v=20260820-i18nmetrika1";

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
import { normalizePermissionTemplates, getPermissionTemplateById as getSharedPositionTemplateById, buildPermissionTemplateOptions, renderPermissionTemplateSummaryById, applyPermissionTemplateToCheckboxHost } from "/position-template-ui.js?v=20260726-navmore1";

import { createCatalogSetupController } from "/owner-setup/catalog-editor.js?v=20260810-setup1";
import { createPayProfileSetupController } from "/owner-setup/pay-profile-editor.js?v=20260729-payroll1";
import { createPositionSetupController } from "/owner-setup/position-editor.js?v=20260720-unified10";
import { createInviteSetupController } from "/owner-setup/invite-editor.js?v=20260720-unified10";
import { createShiftIntervalSetupController } from "/owner-setup/shift-interval-editor.js?v=20260906-names-scopes1";
import { createSupplierSetupController } from "/owner-setup/supplier-editor.js?v=20260720-unified10";
import { createRecurringExpenseSetupController } from "/owner-setup/recurring-expense-editor.js?v=20260729-slotecon1";

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
  MINIMUM_PAYOUT: "Минимальная сумма к выплате",
};

function fmtMoneyMinor(minor) {
  const value = Number(minor || 0) / 100;
  try {
    return new Intl.NumberFormat((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + " ₽";
  } catch {
    return value.toFixed(2) + " ₽";
  }
}

function fmtPercentBps(bps) {
  const value = Number(bps || 0) / 100;
  try {
    return new Intl.NumberFormat((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value) + "%";
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

const INLINE_STEP_KEYS = new Set(["payment_methods", "departments", "kpi", "pay_profiles", "positions", "invites", "shift_intervals", "expense_categories", "suppliers", "recurring_expenses"]);

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
  if (step.key === "pay_profiles") return "Собери базовые профили начислений";
  if (step.key === "positions") return "Создай роли и права команды";
  if (step.key === "invites") return "Добавь команду и назначь должности";
  return "Открой шаг и настрой его";
}

function defaultPayComponentTitle(type) {
  const code = String(type || "SALARY_FIXED_MONTH").toUpperCase();
  return COMPONENT_LABELS[code] || "Компонент";
}

function minimumPayoutScopeLabel(scope) {
  const value = String(scope || "MONTH").toUpperCase();
  return value === "SHIFT" || value === "DAY" ? "за каждую отработанную смену" : "за месяц";
}

function payComponentValueLabel(item) {
  const type = String(item?.component_type || "").toUpperCase();
  if (type === "SALARY_FIXED_MONTH") {
    const accrual = item?.salary_accrual_day ? ` · начисление ${item.salary_accrual_day}-го числа` : "";
    return item?.amount_minor != null ? `${fmtMoneyMinor(item.amount_minor)} в месяц${accrual}` : "Без суммы";
  }
  if (type === "SALARY_HOURLY") return item?.rate_minor != null ? `${fmtMoneyMinor(item.rate_minor)} в час` : "Без ставки";
  if (type === "SALARY_PER_SHIFT") return item?.amount_minor != null ? `${fmtMoneyMinor(item.amount_minor)} за смену` : "Без суммы";
  if (type === "MINIMUM_PAYOUT") return item?.amount_minor != null ? `Доплата до ${fmtMoneyMinor(item.amount_minor)} ${minimumPayoutScopeLabel(item?.effective_minimum_guarantee_scope || item?.minimum_guarantee_scope)}` : "Без минимума";
  if (type === "PERCENT_TOTAL_REVENUE") return item?.percent_bps != null ? `${fmtPercentBps(item.percent_bps)} от общей выручки` : "Без процента";
  if (type === "PERCENT_DEPARTMENT_REVENUE") {
    const dep = item?.department_title ? ` · ${item.department_title}` : "";
    return item?.percent_bps != null ? `${fmtPercentBps(item.percent_bps)} от департамента${dep}` : `Процент по департаменту${dep}`;
  }
  if (type === "KPI_BONUS") {
    const kpi = item?.kpi_metric_title ? ` · ${item.kpi_metric_title}` : "";
    if (String(item?.kpi_calculation_mode || "FIXED").toUpperCase() === "PERCENT") {
      return `KPI${kpi} · ${fmtPercentBps(item?.percent_bps || 0)} от значения · по закрытым сменам`;
    }
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
    ["MINIMUM_PAYOUT", "Минимальная сумма к выплате"],
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
  const kpiMode = String(document.getElementById('inlineComponentKpiCalculationMode')?.value || 'FIXED').toUpperCase();
  const amountRow = document.getElementById('inlineComponentAmountRow');
  const rateRow = document.getElementById('inlineComponentRateRow');
  const percentRow = document.getElementById('inlineComponentPercentRow');
  const depRow = document.getElementById('inlineComponentDepartmentRow');
  const kpiRow = document.getElementById('inlineComponentKpiRow');
  const minScopeRow = document.getElementById('inlineComponentMinimumScopeRow');
  const salaryAccrualDayRow = document.getElementById('inlineComponentSalaryAccrualDayRow');
  const kpiModeRow = document.getElementById('inlineComponentKpiCalculationModeRow');
  setVisible(amountRow, ['SALARY_FIXED_MONTH', 'SALARY_PER_SHIFT', 'MINIMUM_PAYOUT'].includes(type) || (type === 'KPI_BONUS' && kpiMode === 'FIXED'));
  setVisible(rateRow, type === 'SALARY_HOURLY');
  setVisible(percentRow, ['PERCENT_TOTAL_REVENUE', 'PERCENT_DEPARTMENT_REVENUE'].includes(type) || (type === 'KPI_BONUS' && kpiMode === 'PERCENT'));
  setVisible(depRow, type === 'PERCENT_DEPARTMENT_REVENUE');
  setVisible(kpiRow, type === 'KPI_BONUS');
  setVisible(kpiModeRow, type === 'KPI_BONUS');
  setVisible(salaryAccrualDayRow, type === 'SALARY_FIXED_MONTH');
  setVisible(minScopeRow, type === 'MINIMUM_PAYOUT');
}

function setVisible(element, visible) {
  element?.classList.toggle('hidden', !visible);
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
  return d.toLocaleString((globalThis.window?.AxelioI18n?.localeTag?.() || "ru-RU"), { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
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
    venue_position_id: Number(item?.venue_position_id || 0) || null,
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
  const previous = getPositionPresets();
  const previousById = new Map(previous.map((item) => [String(item.id), item]));
  const nextIds = new Set((presets || []).map((item) => String(item?.id || "")));
  const synced = [];

  for (const raw of presets || []) {
    const presetId = String(raw?.id || "").trim();
    const previousPreset = previousById.get(presetId) || null;
    let venuePositionId = Number(raw?.venue_position_id || previousPreset?.venue_position_id || 0) || null;
    const positionPayload = {
      title: String(raw?.title || "").trim(),
      pay_profile_id: raw?.pay_profile_id ? Number(raw.pay_profile_id) : null,
      is_active: raw?.is_active !== false,
      permission_codes: parsePermissionCodes(raw?.permission_codes),
      rate: Number(raw?.rate || 0) || 0,
      percent: Number(raw?.percent || 0) || 0,
    };

    if (!positionPayload.title) continue;

    if (venuePositionId) {
      try {
        await api(
          `/venues/${encodeURIComponent(state.venueId)}/positions/${encodeURIComponent(venuePositionId)}`,
          { method: "PATCH", body: positionPayload },
        );
      } catch (e) {
        if (Number(e?.status || 0) !== 404) throw e;
        venuePositionId = null;
      }
    }

    if (!venuePositionId) {
      const created = await api(`/venues/${encodeURIComponent(state.venueId)}/positions`, {
        method: "POST",
        body: { ...positionPayload, member_user_id: null },
      });
      venuePositionId = Number(created?.id || 0) || null;
    }

    synced.push({
      ...raw,
      venue_position_id: venuePositionId,
    });
  }

  for (const oldPreset of previous) {
    if (!oldPreset?.venue_position_id || nextIds.has(String(oldPreset.id))) continue;
    await api(
      `/venues/${encodeURIComponent(state.venueId)}/positions/${encodeURIComponent(oldPreset.venue_position_id)}`,
      { method: "DELETE" },
    );
  }

  const next = {
    presets: synced,
    seq: Math.max(Number(meta.seq || 0) || 0, synced.length),
    updated_at: new Date().toISOString(),
  };
  await api(`/venues/${encodeURIComponent(state.venueId)}/setup`, {
    method: "PATCH",
    body: { current_step_key: "positions", step_meta: { positions: next } },
  });
}

function resolvePresetSelection(value) {
  if (!value) return "";
  if (typeof value === "string" || typeof value === "number") return String(value || "");
  const rawId = String(value?.id || "").trim();
  if (rawId) return rawId;
  const rawTitle = String(value?.title || "").trim();
  if (!rawTitle) return "";
  const match = getPositionPresets().find((item) => item.is_active && String(item.title || "").trim() === rawTitle);
  return match ? String(match.id || "") : "";
}

function buildPresetOptionList(selectedId = "") {
  const current = resolvePresetSelection(selectedId);
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
    <div class="itemcard section-card setup-card setup-state-card">
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
    <div class="itemcard section-card setup-loading" aria-label="Загрузка мастера настройки">
      <div class="skeleton skeleton--text"></div>
      <div class="skeleton skeleton--card"></div>
      <div class="skeleton skeleton--control"></div>
    </div>
  `;
}

function renderStartScreen() {
  const venueName = state.venue?.name || `Заведение #${state.venueId}`;
  root.innerHTML = `
    <div class="itemcard section-card setup-card setup-start-card">
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
  const resumeChip = resumeStep
    ? `Следующий шаг: ${esc(resumeStep.title)}`
    : (isSetupDone(state.setup) ? "Настройка завершена" : "Все шаги раздела завершены");
  const prepareDone = isSetupPrepareDone(state.setup);
  const extraDisabled = !prepareDone;

  root.innerHTML = `
    <div class="itemcard section-card setup-card setup-overview-card">
      <div class="section-card__head">
        <div class="section-card__title">
          <b>${esc(venueName)}</b>
          <div class="muted">Базовая настройка · статус: ${esc(status)}</div>
        </div>
      </div>

      <div class="setup-inline-list">
        <span class="setup-chip">Готово: ${progress.done} из ${progress.total}</span>
        <span class="setup-chip">Решено: ${progress.resolved} из ${progress.total}</span>
        <span class="setup-chip">${resumeChip}</span>
      </div>

      <progress class="setup-progressbar" value="${percent}" max="100" aria-label="Общий прогресс мастера: ${percent}%">${percent}%</progress>

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
    <div class="itemcard section-card setup-card setup-phase-card">
      <div class="section-card__head">
        <div class="section-card__title">
          <b>${esc(phaseTitle())}</b>
          <div class="muted">Шаги можно проходить по порядку или возвращаться к уже доступным позже.</div>
        </div>
      </div>

      <div class="setup-steps">
        ${visibleSteps.map((step, index) => {
          const ui = getStepUiInfo(step);
          const statusLabel = STATUS_LABELS[ui.uiStatus] || STATUS_LABELS[String(step.status || "AVAILABLE").toUpperCase()] || step.status;
          const countText = getStepSummaryText(step, ui);
          return `
            <button class="setup-step ${String(step.key) === String(state.selectedStepKey || "") ? "is-active" : ""}" type="button" data-step-key="${esc(step.key)}" ${ui.locked ? "disabled" : ""}>
              <span class="setup-step__index" aria-hidden="true">${index + 1}</span>
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
    <div class="itemcard section-card setup-card setup-detail-card">
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

const editorContext = {
  toast,
  confirmModal,
  api,
  getVenueById,
  getVenueMembers,
  getPaymentMethods,
  patchInviteDefaultPosition,
  getDepartments,
  getKpiMetrics,
  getPayProfiles,
  getPayProfile,
  createPayProfile,
  updatePayProfile,
  deletePayProfile,
  createPayComponent,
  updatePayComponent,
  deletePayComponent,
  UNIT_LABEL,
  CATALOG_CONFIG,
  state,
  esc,
  slugifyCode,
  ensureUniqueCode,
  getStepByKey,
  getInlineCatalogState,
  buildUnitOptions,
  getNextStepKey,
  moveToStep,
  loadSetup,
  fmtDateTime,
  roleLabel,
  memberDisplayName,
  getPositionPresets,
  buildPresetOptionList,
  percentInputFromBps,
  moneyInputFromMinor,
  parseMoneyRubToMinor,
  parsePercentInputToBps,
  defaultPayComponentTitle,
  payComponentValueLabel,
  payComponentTypeOptions,
  buildSimpleOptions,
  syncInlinePayComponentFields,
  getVisibleSteps,
  getAdjacentUnlockedStep,
  buildDefaultPermissionsCatalog,
  ensurePermissionsCatalog,
  ensurePositionPermissionTemplates,
  getPositionTemplateById,
  buildPositionTemplateOptions,
  renderPositionTemplateSummary,
  applyPositionTemplateSelection,
  parsePermissionCodes,
  savePositionPresets,
  buildPayProfileOptions,
  todayIso,
  parseMoneyToMinor,
  minorToMoneyInput,
  buildSelectOptions,
  recurringModeLabel,
  buildBasisPaymentMethodCheckboxes,
  setVisible,
};
const { mountCatalogEditor } = createCatalogSetupController(editorContext);
const { mountPayProfilesEditor, loadInlinePayProfiles } = createPayProfileSetupController(editorContext);
editorContext.loadInlinePayProfiles = loadInlinePayProfiles;
const { mountPositionsEditor } = createPositionSetupController(editorContext);
const { mountInvitesEditor } = createInviteSetupController(editorContext);
const { mountShiftIntervalsEditor } = createShiftIntervalSetupController(editorContext);
const { mountSuppliersEditor } = createSupplierSetupController(editorContext);
const { mountRecurringExpensesEditor } = createRecurringExpenseSetupController(editorContext);
async function mountInlineEditor(currentStep) {
  if (!shouldUseInlineEditor(currentStep?.key)) return;
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

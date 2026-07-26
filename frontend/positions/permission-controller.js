
import {
  normalizePermissionTemplates,
  getPermissionTemplateById as getSharedPermissionTemplateById,
  buildPermissionTemplateOptions,
  renderPermissionTemplateSummaryById,
  applyPermissionTemplateToCheckboxHost,
} from "/position-template-ui.js?v=20260726-navmore1";

export function createPositionPermissionController({ state, api }) {
function buildDefaultPermissionsCatalog() {
  return [
    {
      key: "reports",
      title: "Отчёты и финансы",
      hint: "Отчёты за день, закрытие смены и выручка",
      items: [
        { code: "REPORTS_VIEW_DAILY", title: "Отчёты за день" },
        { code: "REPORTS_VIEW_MONTHLY", title: "Отчёты за месяц" },
        { code: "REPORTS_VIEW_PNL", title: "P&L" },
        { code: "SHIFT_REPORT_VIEW", title: "Закрытие смены: просмотр" },
        { code: "SHIFT_REPORT_CLOSE", title: "Закрытие смены: закрыть" },
        { code: "SHIFT_REPORT_EDIT", title: "Закрытие смены: правка закрытых" },
        { code: "SHIFT_REPORT_REOPEN", title: "Закрытие смены: переоткрыть" },
        { code: "REVENUE_VIEW", title: "Выручка: просмотр" },
        { code: "REVENUE_EXPORT", title: "Выручка: экспорт" },
      ],
    },
    {
      key: "adjustments",
      title: "Штрафы и споры",
      hint: "Штрафы, списания, премии и споры",
      items: [
        { code: "ADJUSTMENTS_VIEW", title: "Просмотр штрафов/премий/списаний" },
        { code: "ADJUSTMENTS_MANAGE", title: "Управление штрафами/премиями/списаниями" },
        { code: "DISPUTES_RESOLVE", title: "Разбор оспариваний" },
      ],
    },
    {
      key: "expenses",
      title: "Расходы",
      hint: "Просмотр и добавление расходов",
      items: [
        { code: "EXPENSE_VIEW", title: "Просмотр расходов" },
        { code: "EXPENSE_ADD", title: "Добавление расходов" },
        { code: "EXPENSE_CATEGORIES_MANAGE", title: "Статьи расходов" },
      ],
    },
    {
      key: "shifts",
      title: "Смены",
      hint: "Просмотр графика и управление сменами",
      items: [
        { code: "SHIFTS_VIEW", title: "Просмотр смен" },
        { code: "SHIFTS_MANAGE", title: "Управление сменами" },
      ],
    },
    {
      key: "staff",
      title: "Сотрудники",
      hint: "Просмотр и управление командой",
      items: [
        { code: "STAFF_VIEW", title: "Просмотр сотрудников" },
        { code: "STAFF_MANAGE", title: "Управление сотрудниками" },
      ],
    },
    {
      key: "positions",
      title: "Должности",
      hint: "Должности, назначения и права",
      items: [
        { code: "POSITIONS_VIEW", title: "Просмотр должностей" },
        { code: "POSITIONS_MANAGE", title: "Управление должностями" },
        { code: "POSITION_PERMISSIONS_MANAGE", title: "Права должностей" },
        { code: "POSITIONS_ASSIGN", title: "Назначение должностей" },
      ],
    },
    {
      key: "venue",
      title: "Заведение",
      hint: "Доступ к карточке заведения и настройкам",
      items: [
        { code: "VENUE_VIEW", title: "Открывать заведение" },
        { code: "VENUE_SETTINGS_EDIT", title: "Настройки заведения" },
      ],
    },
    {
      key: "catalogs",
      title: "Справочники",
      hint: "Департаменты, способы оплаты и KPI",
      items: [
        { code: "DEPARTMENTS_VIEW", title: "Департаменты: просмотр" },
        { code: "DEPARTMENTS_CREATE", title: "Департаменты: создание" },
        { code: "DEPARTMENTS_EDIT", title: "Департаменты: редактирование" },
        { code: "DEPARTMENTS_ARCHIVE", title: "Департаменты: архив" },
        { code: "PAYMENT_METHODS_VIEW", title: "Оплаты: просмотр" },
        { code: "PAYMENT_METHODS_CREATE", title: "Оплаты: создание" },
        { code: "PAYMENT_METHODS_EDIT", title: "Оплаты: редактирование" },
        { code: "PAYMENT_METHODS_ARCHIVE", title: "Оплаты: архив" },
        { code: "KPI_METRICS_VIEW", title: "KPI: просмотр" },
        { code: "KPI_METRICS_CREATE", title: "KPI: создание" },
        { code: "KPI_METRICS_EDIT", title: "KPI: редактирование" },
        { code: "KPI_METRICS_ARCHIVE", title: "KPI: архив" },
      ],
    },
  ];
}

const PERM_GROUP_META = {
  Reports: {
    key: "reports",
    title: "Отчёты и финансы",
    hint: "Отчёты за день, закрытие смены и выручка",
  },
  Adjustments: {
    key: "adjustments",
    title: "Штрафы и споры",
    hint: "Штрафы, списания, премии и споры",
  },
  Expenses: {
    key: "expenses",
    title: "Расходы",
    hint: "Просмотр и добавление расходов",
  },
  Shifts: {
    key: "shifts",
    title: "Смены",
    hint: "Просмотр графика и управление сменами",
  },
  Staff: {
    key: "staff",
    title: "Сотрудники",
    hint: "Просмотр и управление командой",
  },
  Positions: {
    key: "positions",
    title: "Должности",
    hint: "Должности, назначения и права",
  },
  Venue: {
    key: "venue",
    title: "Заведение",
    hint: "Доступ к карточке заведения и настройкам",
  },
  Catalogs: {
    key: "catalogs",
    title: "Справочники",
    hint: "Департаменты, способы оплаты и KPI",
  },
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

  groups.forEach((g) => {
    g.items.sort((a, b) => a.title.localeCompare(b.title, "ru"));
  });

  return groups.length ? groups : buildDefaultPermissionsCatalog();
}

async function ensurePermissionsCatalog() {
  if (Array.isArray(state.permissionsCatalog) && state.permissionsCatalog.length) return state.permissionsCatalog;
  try {
    const resp = await api('/me/permissions/catalog');
    state.permissionsCatalog = normalizePermissionCatalog(resp?.items || []);
  } catch {
    state.permissionsCatalog = buildDefaultPermissionsCatalog();
  }
  return state.permissionsCatalog;
}

async function ensurePermissionTemplates() {
  if (Array.isArray(state.permissionTemplates)) return state.permissionTemplates;
  try {
    const resp = await api('/position-permission-templates');
    state.permissionTemplates = normalizePermissionTemplates(resp?.items || []);
  } catch {
    state.permissionTemplates = normalizePermissionTemplates([]);
  }
  return state.permissionTemplates;
}

function getPermissionTemplateById(templateId) {
  return getSharedPermissionTemplateById(state.permissionTemplates, templateId);
}

function renderPermissionTemplateSelect(selectedId = "") {
  return buildPermissionTemplateOptions(state.permissionTemplates, {
    selectedId,
    emptyLabel: "— выбрать шаблон прав —",
    includeSystemBadge: true,
  });
}

function renderTemplateSummaryBlock(templateId = "") {
  return renderPermissionTemplateSummaryById(state.permissionTemplates, templateId, {
    emptyText: "Шаблон не выбран. Можно включить права вручную ниже.",
    noDescriptionText: "Шаблон без описания",
    wrapId: "f_perm_template_summary",
  });
}

function applyPermissionTemplateToModal(templateId) {
  return applyPermissionTemplateToCheckboxHost({
    templates: state.permissionTemplates,
    templateId,
    checkboxSelector: 'input[data-perm-code]',
    checkboxAttr: 'data-perm-code',
    summaryHost: document.getElementById('f_perm_template_summary_wrap'),
    titleInput: document.getElementById('f_title'),
    fillTitleWhenEmpty: true,
    summaryOptions: {
      emptyText: "Шаблон не выбран. Можно включить права вручную ниже.",
      noDescriptionText: "Шаблон без описания",
      wrapId: "f_perm_template_summary",
    },
  });
}

return {
  buildDefaultPermissionsCatalog,
  normalizePermissionCatalog,
  ensurePermissionsCatalog,
  ensurePermissionTemplates,
  getPermissionTemplateById,
  renderPermissionTemplateSelect,
  renderTemplateSummaryBlock,
  applyPermissionTemplateToModal,
};
}

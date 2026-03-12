from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDef:
    code: str
    group: str
    title: str
    description: str | None = None


# Тут будет весь список функций приложения.
# Добавил новую функцию -> добавь сюда -> она появится в БД после sync.
PERMISSIONS: list[PermissionDef] = [
    # Positions
    PermissionDef("POSITIONS_VIEW", "Positions", "Просмотр должностей", "Видеть список должностей"),
    PermissionDef("POSITIONS_MANAGE", "Positions", "Управление должностями", "Создавать/редактировать/удалять должности"),
    PermissionDef("POSITION_PERMISSIONS_MANAGE", "Positions", "Права должностей", "Настраивать права у должностей"),
    PermissionDef("POSITIONS_ASSIGN", "Positions", "Назначение должностей", "Назначать/менять должность сотруднику (в т.ч. приглашённому)"),

    # Staff
    PermissionDef("STAFF_VIEW", "Staff", "Просмотр сотрудников", "Видеть список сотрудников"),
    PermissionDef("STAFF_MANAGE", "Staff", "Управление сотрудниками", "Добавлять/изменять/увольнять сотрудников"),

    # Shifts
    PermissionDef("SHIFTS_VIEW", "Shifts", "Просмотр смен", "Видеть список смен и расписание"),
    PermissionDef("SHIFTS_MANAGE", "Shifts", "Управление сменами", "Создавать/редактировать смены и промежутки"),

    # Venue settings
    PermissionDef("VENUE_VIEW", "Venue", "Открытие заведения", "Открывать страницу заведения/управления"),
    PermissionDef("VENUE_SETTINGS_EDIT", "Venue", "Настройки заведения", "Изменять настройки заведения (например, чаевые)"),

    # Expenses
    PermissionDef("EXPENSE_ADD", "Expenses", "Добавление расходов", "Вносить расход"),
    PermissionDef("EXPENSE_VIEW", "Expenses", "Просмотр расходов", "Видеть список расходов"),
    PermissionDef("EXPENSE_CATEGORIES_MANAGE", "Expenses", "Статьи расходов", "Настраивать статьи расходов"),
    PermissionDef("RECURRING_EXPENSES_VIEW", "Expenses", "Регулярные расходы: просмотр", "Видеть правила регулярных расходов"),
    PermissionDef("RECURRING_EXPENSES_MANAGE", "Expenses", "Регулярные расходы: управление", "Создавать и редактировать правила регулярных расходов и генерировать черновики"),

    # Reports
    PermissionDef("REPORTS_VIEW_DAILY", "Reports", "Отчёты за день", "Просматривать отчёт за выбранный день"),
    PermissionDef("REPORTS_VIEW_MONTHLY", "Reports", "Отчёты за месяц", "Просматривать отчёты за месяц"),
    PermissionDef("REPORTS_VIEW_PNL", "Reports", "P&L", "Просматривать прибыль/убытки"),

    PermissionDef("SHIFT_REPORT_VIEW", "Reports", "Закрытие смены: просмотр", "Просматривать отчёт закрытия смены"),
    PermissionDef("SHIFT_REPORT_EDIT", "Reports", "Закрытие смены: правка закрытых", "Редактировать закрытые отчёты (с аудитом)"),
    PermissionDef("SHIFT_REPORT_CLOSE", "Reports", "Закрытие смены: закрыть", "Закрывать смену (переводить отчёт в статус CLOSED)"),
    PermissionDef("SHIFT_REPORT_REOPEN", "Reports", "Закрытие смены: переоткрыть", "Переоткрывать закрытые отчёты (CLOSED -> DRAFT)"),
    PermissionDef("REVENUE_VIEW", "Reports", "Выручка: просмотр", "Открывать страницу выручки и видеть суммы"),
    PermissionDef("REVENUE_EXPORT", "Reports", "Выручка: экспорт", "Выгружать выручку в XLSX/CSV"),

    # Adjustments
    PermissionDef("ADJUSTMENTS_VIEW", "Adjustments", "Просмотр штрафов/премий/списаний", "Видеть штрафы/премии/списания"),
    PermissionDef("ADJUSTMENTS_MANAGE", "Adjustments", "Управление штрафами/премиями/списаниями", "Создавать/редактировать штрафы/премии/списания"),
    PermissionDef("DISPUTES_RESOLVE", "Adjustments", "Разбор оспариваний", "Видеть и закрывать оспаривания"),

    # Catalogs (dynamic)
    PermissionDef("DEPARTMENTS_VIEW", "Catalogs", "Просмотр департаментов", "Видеть список департаментов"),
    PermissionDef("DEPARTMENTS_CREATE", "Catalogs", "Создание департаментов", "Создавать департаменты"),
    PermissionDef("DEPARTMENTS_EDIT", "Catalogs", "Редактирование департаментов", "Редактировать департаменты"),
    PermissionDef("DEPARTMENTS_ARCHIVE", "Catalogs", "Архивирование департаментов", "Архивировать/восстанавливать департаменты"),

    PermissionDef("PAYMENT_METHODS_VIEW", "Catalogs", "Просмотр способов оплат", "Видеть список способов оплат"),
    PermissionDef("PAYMENT_METHODS_CREATE", "Catalogs", "Создание способов оплат", "Создавать способы оплат"),
    PermissionDef("PAYMENT_METHODS_EDIT", "Catalogs", "Редактирование способов оплат", "Редактировать способы оплат"),
    PermissionDef("PAYMENT_METHODS_ARCHIVE", "Catalogs", "Архивирование способов оплат", "Архивировать/восстанавливать способы оплат"),

    PermissionDef("KPI_METRICS_VIEW", "Catalogs", "Просмотр KPI", "Видеть список KPI/допродаж"),
    PermissionDef("KPI_METRICS_CREATE", "Catalogs", "Создание KPI", "Создавать KPI/допродажи"),
    PermissionDef("KPI_METRICS_EDIT", "Catalogs", "Редактирование KPI", "Редактировать KPI/допродажи"),
    PermissionDef("KPI_METRICS_ARCHIVE", "Catalogs", "Архивирование KPI", "Архивировать/восстанавливать KPI/допродажи"),

]


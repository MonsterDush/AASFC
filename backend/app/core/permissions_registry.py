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

    # Staff
    PermissionDef("STAFF_VIEW", "Staff", "Просмотр сотрудников", "Видеть список сотрудников"),
    PermissionDef("STAFF_MANAGE", "Staff", "Управление сотрудниками", "Добавлять/изменять/увольнять сотрудников"),

    # Shifts
    PermissionDef("SHIFTS_VIEW", "Shifts", "Просмотр смен", "Видеть список смен и расписание"),
    PermissionDef("SHIFTS_MANAGE", "Shifts", "Управление сменами", "Создавать/редактировать смены и промежутки"),

    # Expenses
    PermissionDef("EXPENSE_ADD", "Expenses", "Добавление расходов", "Вносить расход"),
    PermissionDef("EXPENSE_VIEW", "Expenses", "Просмотр расходов", "Видеть список расходов"),
    PermissionDef("EXPENSE_CATEGORIES_MANAGE", "Expenses", "Статьи расходов", "Настраивать статьи расходов"),

    # Reports
    PermissionDef("REPORTS_VIEW_DAILY", "Reports", "Отчёты за день", "Просматривать отчёт за выбранный день"),
    PermissionDef("REPORTS_VIEW_MONTHLY", "Reports", "Отчёты за месяц", "Просматривать отчёты за месяц"),
    PermissionDef("REPORTS_VIEW_PNL", "Reports", "P&L", "Просматривать прибыль/убытки"),
]


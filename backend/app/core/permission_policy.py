from __future__ import annotations

from collections.abc import Iterable

from app.core.permissions_registry import PERMISSIONS

ALL_PERMISSION_CODES: set[str] = {
    str(p.code or "").strip().upper()
    for p in PERMISSIONS
    if str(p.code or "").strip()
}

_SHIFT_REPORT_CODES: set[str] = {
    "SHIFT_REPORT_VIEW",
    "SHIFT_REPORT_CLOSE",
    "SHIFT_REPORT_EDIT",
    "SHIFT_REPORT_REOPEN",
}

_CATALOG_VIEW_CODES: set[str] = {
    "DEPARTMENTS_VIEW",
    "PAYMENT_METHODS_VIEW",
    "KPI_METRICS_VIEW",
}

_IMPLIED_PERMISSIONS: dict[str, set[str]] = {
    "SHIFTS_MANAGE": {"SHIFTS_VIEW"},
    "ADJUSTMENTS_MANAGE": {"ADJUSTMENTS_VIEW"},
    "DISPUTES_RESOLVE": {"ADJUSTMENTS_VIEW"},
    "STAFF_MANAGE": {"STAFF_VIEW"},
    "POSITIONS_MANAGE": {"POSITIONS_VIEW"},
    "POSITION_PERMISSIONS_MANAGE": {"POSITIONS_VIEW"},
    "POSITIONS_ASSIGN": {"POSITIONS_VIEW"},
    "EXPENSE_ADD": {"EXPENSE_VIEW"},
    "EXPENSE_CATEGORIES_MANAGE": {"EXPENSE_VIEW"},
    "PAYROLL_CALCULATE": {"PAYROLL_VIEW"},
    "DEPARTMENTS_CREATE": {"DEPARTMENTS_VIEW"},
    "DEPARTMENTS_EDIT": {"DEPARTMENTS_VIEW"},
    "DEPARTMENTS_ARCHIVE": {"DEPARTMENTS_VIEW"},
    "PAYMENT_METHODS_CREATE": {"PAYMENT_METHODS_VIEW"},
    "PAYMENT_METHODS_EDIT": {"PAYMENT_METHODS_VIEW"},
    "PAYMENT_METHODS_ARCHIVE": {"PAYMENT_METHODS_VIEW"},
    "KPI_METRICS_CREATE": {"KPI_METRICS_VIEW"},
    "KPI_METRICS_EDIT": {"KPI_METRICS_VIEW"},
    "KPI_METRICS_ARCHIVE": {"KPI_METRICS_VIEW"},
    "SHIFT_REPORT_CLOSE": {"SHIFT_REPORT_VIEW", *_CATALOG_VIEW_CODES},
    "SHIFT_REPORT_EDIT": {"SHIFT_REPORT_VIEW", *_CATALOG_VIEW_CODES},
    "SHIFT_REPORT_REOPEN": {"SHIFT_REPORT_VIEW", *_CATALOG_VIEW_CODES},
    "SHIFT_REPORT_VIEW": set(_CATALOG_VIEW_CODES),
}

# Минимальные безопасные дефолты ролей.
# OWNER отдельно всё равно имеет полный доступ внутри venue,
# но здесь фиксируем матрицу, чтобы не было "пустых" дефолтов в БД.
_ROLE_DEFAULT_BASE_CODES: dict[str, set[str]] = {
    "VENUE_MANAGER": {
        "VENUE_VIEW",
        "SHIFTS_VIEW",
        "STAFF_VIEW",
        "POSITIONS_VIEW",
        "SHIFT_REPORT_CLOSE",
    },
    "STAFF": {
        "VENUE_VIEW",
        "SHIFTS_VIEW",
    },
}


def normalize_permission_code(code: str | None) -> str:
    return str(code or "").strip().upper()


def expand_permission_codes(codes: Iterable[str] | None) -> set[str]:
    result = {
        normalize_permission_code(code)
        for code in (codes or [])
        if normalize_permission_code(code)
    }
    if not result:
        return set()

    changed = True
    while changed:
        changed = False
        for code in tuple(result):
            for implied in _IMPLIED_PERMISSIONS.get(code, set()):
                norm = normalize_permission_code(implied)
                if norm and norm not in result:
                    result.add(norm)
                    changed = True
    return result


def get_default_permission_codes_for_role(role: str | None) -> set[str]:
    norm_role = normalize_permission_code(role)
    if norm_role in {"MODERATOR", "VENUE_OWNER"}:
        return set(ALL_PERMISSION_CODES)
    return expand_permission_codes(_ROLE_DEFAULT_BASE_CODES.get(norm_role, set()))


def role_has_built_in_default(role: str | None, permission_code: str | None) -> bool:
    norm_perm = normalize_permission_code(permission_code)
    if not norm_perm:
        return False
    return norm_perm in get_default_permission_codes_for_role(role)


def is_shift_report_permission(code: str | None) -> bool:
    return normalize_permission_code(code) in _SHIFT_REPORT_CODES

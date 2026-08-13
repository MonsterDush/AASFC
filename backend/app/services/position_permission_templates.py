from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permission_codes import normalize_known_permission_codes, parse_permission_codes
from app.core.permissions_registry import PERMISSIONS
from app.models.position_permission_template import PositionPermissionTemplate


@dataclass(frozen=True)
class DefaultPositionPermissionTemplate:
    code: str
    title: str
    description: str
    sort_order: int
    permission_codes: tuple[str, ...]


DEFAULT_POSITION_PERMISSION_TEMPLATES: tuple[DefaultPositionPermissionTemplate, ...] = (
    DefaultPositionPermissionTemplate(
        code="staff_basic",
        title="Базовый сотрудник",
        description="Видит свой график, начисления и собственные корректировки без управленческих прав.",
        sort_order=10,
        permission_codes=(
            "SHIFTS_VIEW",
            "PAYROLL_VIEW",
            "ADJUSTMENTS_VIEW",
        ),
    ),
    DefaultPositionPermissionTemplate(
        code="report_operator",
        title="Касса и закрытие смены",
        description="Закрывает смены и видит нужные справочники, но без широкого доступа к команде и расходам.",
        sort_order=20,
        permission_codes=(
            "VENUE_VIEW",
            "SHIFTS_VIEW",
            "SHIFT_REPORT_VIEW",
            "SHIFT_REPORT_CLOSE",
            "REPORTS_VIEW_DAILY",
            "DEPARTMENTS_VIEW",
            "PAYMENT_METHODS_VIEW",
            "KPI_METRICS_VIEW",
            "PAYROLL_VIEW",
            "ADJUSTMENTS_VIEW",
        ),
    ),
    DefaultPositionPermissionTemplate(
        code="shift_manager",
        title="Менеджер смены",
        description="Управляет сменами, видит команду и работает с ежедневными операционными задачами.",
        sort_order=30,
        permission_codes=(
            "VENUE_VIEW",
            "SHIFTS_VIEW",
            "SHIFTS_MANAGE",
            "STAFF_VIEW",
            "POSITIONS_VIEW",
            "POSITIONS_ASSIGN",
            "SHIFT_REPORT_VIEW",
            "SHIFT_REPORT_CLOSE",
            "REPORTS_VIEW_DAILY",
            "DEPARTMENTS_VIEW",
            "PAYMENT_METHODS_VIEW",
            "KPI_METRICS_VIEW",
            "ADJUSTMENTS_VIEW",
            "ADJUSTMENTS_MANAGE",
            "PAYROLL_VIEW",
        ),
    ),
    DefaultPositionPermissionTemplate(
        code="finance_manager",
        title="Финансы и аналитика",
        description="Работает с выручкой, расходами, сводкой и начислениями без управления персоналом.",
        sort_order=40,
        permission_codes=(
            "VENUE_VIEW",
            "REPORTS_VIEW_DAILY",
            "REPORTS_VIEW_MONTHLY",
            "REPORTS_VIEW_PNL",
            "SHIFT_REPORT_VIEW",
            "REVENUE_VIEW",
            "REVENUE_EXPORT",
            "EXPENSE_VIEW",
            "EXPENSE_ADD",
            "EXPENSE_CATEGORIES_MANAGE",
            "RECURRING_EXPENSES_VIEW",
            "FINANCE_LEDGER_VIEW",
            "PAYROLL_VIEW",
            "MONTHLY_SUMMARY_VIEW",
            "DEPARTMENTS_VIEW",
            "PAYMENT_METHODS_VIEW",
            "KPI_METRICS_VIEW",
        ),
    ),
    DefaultPositionPermissionTemplate(
        code="operations_manager",
        title="Операционный менеджер",
        description="Широкий пресет для управляющего заведением без системных прав супер-админа.",
        sort_order=50,
        permission_codes=(
            "VENUE_VIEW",
            "VENUE_SETTINGS_EDIT",
            "STAFF_VIEW",
            "STAFF_MANAGE",
            "POSITIONS_VIEW",
            "POSITIONS_MANAGE",
            "POSITION_PERMISSIONS_MANAGE",
            "POSITIONS_ASSIGN",
            "SHIFTS_VIEW",
            "SHIFTS_MANAGE",
            "REPORTS_VIEW_DAILY",
            "REPORTS_VIEW_MONTHLY",
            "SHIFT_REPORT_VIEW",
            "SHIFT_REPORT_CLOSE",
            "SHIFT_REPORT_EDIT",
            "REVENUE_VIEW",
            "EXPENSE_VIEW",
            "EXPENSE_ADD",
            "EXPENSE_CATEGORIES_MANAGE",
            "RECURRING_EXPENSES_VIEW",
            "RECURRING_EXPENSES_MANAGE",
            "FINANCE_LEDGER_VIEW",
            "PAYROLL_VIEW",
            "MONTHLY_SUMMARY_VIEW",
            "DEPARTMENTS_VIEW",
            "DEPARTMENTS_CREATE",
            "DEPARTMENTS_EDIT",
            "PAYMENT_METHODS_VIEW",
            "PAYMENT_METHODS_CREATE",
            "PAYMENT_METHODS_EDIT",
            "KPI_METRICS_VIEW",
            "KPI_METRICS_CREATE",
            "KPI_METRICS_EDIT",
            "ADJUSTMENTS_VIEW",
            "ADJUSTMENTS_MANAGE",
            "DISPUTES_RESOLVE",
            "PAY_PROFILES_VIEW",
        ),
    ),
)

PERMISSION_GROUP_META = {
    "REPORTS": {"key": "reports", "title": "Отчёты и финансы"},
    "ADJUSTMENTS": {"key": "adjustments", "title": "Штрафы и споры"},
    "EXPENSES": {"key": "expenses", "title": "Расходы"},
    "SHIFTS": {"key": "shifts", "title": "Смены"},
    "STAFF": {"key": "staff", "title": "Команда"},
    "POSITIONS": {"key": "positions", "title": "Должности"},
    "VENUE": {"key": "venue", "title": "Заведение"},
    "CATALOGS": {"key": "catalogs", "title": "Справочники"},
    "PAYROLL": {"key": "payroll", "title": "Зарплаты"},
}

PERMISSION_DEF_BY_CODE = {str(item.code).upper(): item for item in PERMISSIONS}


def utcnow() -> datetime:
    return datetime.utcnow()


def next_sort_order(db: Session) -> int:
    current = db.execute(select(func.max(PositionPermissionTemplate.sort_order))).scalar_one_or_none()
    base = int(current or 0)
    return base + 10 if base >= 0 else 10


def summarize_permission_codes(codes: Iterable[str] | None) -> dict:
    normalized = [str(code or "").strip().upper() for code in (codes or []) if str(code or "").strip()]
    groups: dict[str, dict] = {}
    for code in normalized:
        perm = PERMISSION_DEF_BY_CODE.get(code)
        raw_group = str(getattr(perm, "group", "OTHER") or "OTHER").upper()
        meta = PERMISSION_GROUP_META.get(raw_group, {"key": raw_group.lower(), "title": raw_group.title()})
        bucket = groups.setdefault(meta["key"], {"key": meta["key"], "title": meta["title"], "count": 0, "codes": []})
        bucket["count"] += 1
        bucket["codes"].append(code)
    group_items = sorted(groups.values(), key=lambda item: (item["title"], item["key"]))
    summary_labels = [f"{item['title']} · {item['count']}" for item in group_items]
    return {
        "permission_count": len(normalized),
        "groups": group_items,
        "summary_labels": summary_labels,
    }


def serialize_template(row: PositionPermissionTemplate) -> dict:
    codes = parse_permission_codes(getattr(row, "permission_codes_json", None))
    summary = summarize_permission_codes(codes)
    return {
        "id": int(row.id),
        "code": str(getattr(row, "code", "") or "").strip(),
        "title": str(row.title or "").strip(),
        "description": str(row.description or "").strip() or None,
        "permission_codes": codes,
        "permission_summary": summary,
        "sort_order": int(getattr(row, "sort_order", 0) or 0),
        "is_active": bool(getattr(row, "is_active", True)),
        "is_system": bool(getattr(row, "is_system", False)),
        "scope": str(getattr(row, "scope", "GLOBAL") or "GLOBAL").upper(),
        "created_by_user_id": int(row.created_by_user_id)
        if getattr(row, "created_by_user_id", None) is not None
        else None,
        "updated_by_user_id": int(row.updated_by_user_id)
        if getattr(row, "updated_by_user_id", None) is not None
        else None,
        "created_at": row.created_at.isoformat() if getattr(row, "created_at", None) else None,
        "updated_at": row.updated_at.isoformat() if getattr(row, "updated_at", None) else None,
    }


def ensure_default_templates(
    db: Session, *, actor_user_id: int | None = None, reactivate: bool = False
) -> dict[str, int]:
    existing_rows = (
        db.execute(select(PositionPermissionTemplate).where(PositionPermissionTemplate.scope == "GLOBAL"))
        .scalars()
        .all()
    )
    by_code = {
        str(row.code or "").strip().lower(): row for row in existing_rows if str(getattr(row, "code", "") or "").strip()
    }
    created = 0
    updated = 0
    for item in DEFAULT_POSITION_PERMISSION_TEMPLATES:
        row = by_code.get(item.code.lower())
        normalized_codes = normalize_known_permission_codes(db, item.permission_codes)
        if row is None:
            db.add(
                PositionPermissionTemplate(
                    code=item.code,
                    title=item.title,
                    description=item.description,
                    permission_codes_json=normalized_codes,
                    sort_order=item.sort_order,
                    is_active=True,
                    is_system=True,
                    scope="GLOBAL",
                    created_by_user_id=actor_user_id,
                    updated_by_user_id=actor_user_id,
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
            created += 1
            continue
        changed = False
        if row.is_system is not True:
            row.is_system = True
            changed = True
        if row.title != item.title:
            row.title = item.title
            changed = True
        if (row.description or None) != item.description:
            row.description = item.description
            changed = True
        if int(row.sort_order or 0) != int(item.sort_order):
            row.sort_order = int(item.sort_order)
            changed = True
        if parse_permission_codes(row.permission_codes_json) != normalized_codes:
            row.permission_codes_json = normalized_codes
            changed = True
        if reactivate and row.is_active is not True:
            row.is_active = True
            changed = True
        if changed:
            row.updated_by_user_id = actor_user_id
            row.updated_at = utcnow()
            updated += 1
    if created or updated:
        db.flush()
    return {"created": created, "updated": updated}

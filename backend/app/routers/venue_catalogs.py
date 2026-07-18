from __future__ import annotations

from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.venue_permissions import require_venue_permission
from app.core.db import get_db
from app.models.department import Department
from app.models.expense_category import ExpenseCategory
from app.models.kpi_metric import KpiMetric
from app.models.pay_component import PayComponent
from app.models.pay_profile import PayProfile
from app.models.payment_method import PaymentMethod
from app.models.supplier import Supplier
from app.models.user import User
from app.schemas.venue_catalogs import (
    CatalogItemCreateIn,
    CatalogItemUpdateIn,
    KpiMetricCreateIn,
    KpiMetricUpdateIn,
    SupplierCreateIn,
    SupplierUpdateIn,
)
from app.services.payroll.calculator import BOOST_SOURCE_KPI_METRIC


router = APIRouter()


_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def _normalize_code(code: str) -> str:
    c = (code or "").strip().lower().replace(" ", "_")
    if not _CODE_RE.match(c):
        raise HTTPException(
            status_code=400,
            detail="Bad code format. Use латиницу/цифры и символы _- (пример: hookah, cashless, fruit_bowl)",
        )
    return c


def _get_expense_category_or_404(db: Session, *, venue_id: int, category_id: int) -> ExpenseCategory:
    obj = db.execute(
        select(ExpenseCategory).where(ExpenseCategory.id == category_id, ExpenseCategory.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Expense category not found")
    return obj


def _get_supplier_or_404(db: Session, *, venue_id: int, supplier_id: int) -> Supplier:
    obj = db.execute(
        select(Supplier).where(Supplier.id == supplier_id, Supplier.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Supplier not found")
    return obj


def _get_payment_method_or_404(db: Session, *, venue_id: int, payment_method_id: int) -> PaymentMethod:
    obj = db.execute(
        select(PaymentMethod).where(PaymentMethod.id == payment_method_id, PaymentMethod.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Payment method not found")
    return obj


def _build_kpi_usage_map(db: Session, *, venue_id: int) -> dict[int, dict]:
    result: dict[int, dict] = {}

    bonus_rows = db.execute(
        select(
            PayComponent.kpi_metric_id,
            func.count(PayComponent.id),
            func.count(func.distinct(PayComponent.pay_profile_id)),
        )
        .join(PayProfile, PayProfile.id == PayComponent.pay_profile_id)
        .where(
            PayComponent.venue_id == int(venue_id),
            PayComponent.is_active.is_(True),
            PayProfile.is_active.is_(True),
            PayComponent.component_type == "KPI_BONUS",
            PayComponent.kpi_metric_id.is_not(None),
        )
        .group_by(PayComponent.kpi_metric_id)
    ).all()
    for metric_id, component_count, profile_count in bonus_rows:
        key = int(metric_id or 0)
        if key <= 0:
            continue
        bucket = result.setdefault(key, {
            "usage_component_count": 0,
            "usage_bonus_component_count": 0,
            "usage_boost_component_count": 0,
            "usage_bonus_profile_count": 0,
            "usage_boost_profile_count": 0,
        })
        bucket["usage_component_count"] += int(component_count or 0)
        bucket["usage_bonus_component_count"] += int(component_count or 0)
        bucket["usage_bonus_profile_count"] += int(profile_count or 0)

    boost_rows = db.execute(
        select(
            PayComponent.boost_kpi_metric_id,
            func.count(PayComponent.id),
            func.count(func.distinct(PayComponent.pay_profile_id)),
        )
        .join(PayProfile, PayProfile.id == PayComponent.pay_profile_id)
        .where(
            PayComponent.venue_id == int(venue_id),
            PayComponent.is_active.is_(True),
            PayProfile.is_active.is_(True),
            PayComponent.component_type.in_(["PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"]),
            PayComponent.boost_enabled.is_(True),
            PayComponent.boost_source_type == BOOST_SOURCE_KPI_METRIC,
            PayComponent.boost_kpi_metric_id.is_not(None),
        )
        .group_by(PayComponent.boost_kpi_metric_id)
    ).all()
    for metric_id, component_count, profile_count in boost_rows:
        key = int(metric_id or 0)
        if key <= 0:
            continue
        bucket = result.setdefault(key, {
            "usage_component_count": 0,
            "usage_bonus_component_count": 0,
            "usage_boost_component_count": 0,
            "usage_bonus_profile_count": 0,
            "usage_boost_profile_count": 0,
        })
        bucket["usage_component_count"] += int(component_count or 0)
        bucket["usage_boost_component_count"] += int(component_count or 0)
        bucket["usage_boost_profile_count"] += int(profile_count or 0)

    return result


# ---------------- Catalogs: Departments / Payment Methods / KPI Metrics ----------------


@router.get("/{venue_id}/departments")
def list_departments(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DEPARTMENTS_VIEW")
    stmt = select(Department).where(Department.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(Department.is_active.is_(True))
    rows = db.scalars(stmt.order_by(Department.sort_order.asc(), Department.id.asc())).all()
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
        }
        for r in rows
    ]


@router.post("/{venue_id}/departments")
def create_department(
    venue_id: int,
    payload: CatalogItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DEPARTMENTS_CREATE")
    obj = Department(
        venue_id=venue_id,
        code=_normalize_code(payload.code),
        title=payload.title.strip(),
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department code already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/departments/{department_id}")
def update_department(
    venue_id: int,
    department_id: int,
    payload: CatalogItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DEPARTMENTS_EDIT")
    obj = db.execute(
        select(Department).where(Department.id == department_id, Department.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Department not found")

    if payload.is_active is not None and bool(payload.is_active) != bool(obj.is_active):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="DEPARTMENTS_ARCHIVE")
        obj.is_active = bool(payload.is_active)

    if payload.code is not None:
        obj.code = _normalize_code(payload.code)

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department code already exists")
    return {"ok": True}


def _ensure_default_payment_methods(db: Session, venue_id: int) -> None:
    cnt = db.scalar(select(func.count()).select_from(PaymentMethod).where(PaymentMethod.venue_id == venue_id)) or 0
    if cnt:
        return
    defaults = [
        ("cash", "Наличные", 0),
        ("cashless", "Безналичные", 10),
        ("sbp", "СБП", 20),
        ("other", "Прочее", 90),
    ]
    for code, title, order in defaults:
        db.add(
            PaymentMethod(
                venue_id=venue_id,
                code=code,
                title=title,
                is_active=True,
                sort_order=order,
                created_at=datetime.utcnow(),
            )
        )
    db.commit()


@router.get("/{venue_id}/payment-methods")
def list_payment_methods(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_METHODS_VIEW")
    _ensure_default_payment_methods(db, venue_id)
    stmt = select(PaymentMethod).where(PaymentMethod.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(PaymentMethod.is_active.is_(True))
    rows = db.scalars(stmt.order_by(PaymentMethod.sort_order.asc(), PaymentMethod.id.asc())).all()
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
        }
        for r in rows
    ]


@router.post("/{venue_id}/payment-methods")
def create_payment_method(
    venue_id: int,
    payload: CatalogItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_METHODS_CREATE")
    obj = PaymentMethod(
        venue_id=venue_id,
        code=_normalize_code(payload.code),
        title=payload.title.strip(),
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment method code already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/payment-methods/{payment_method_id}")
def update_payment_method(
    venue_id: int,
    payment_method_id: int,
    payload: CatalogItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_METHODS_EDIT")
    obj = db.execute(
        select(PaymentMethod).where(PaymentMethod.id == payment_method_id, PaymentMethod.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Payment method not found")

    if payload.is_active is not None and bool(payload.is_active) != bool(obj.is_active):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAYMENT_METHODS_ARCHIVE")
        obj.is_active = bool(payload.is_active)
    if payload.code is not None:
        obj.code = _normalize_code(payload.code)

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Payment method code already exists")
    return {"ok": True}


@router.get("/{venue_id}/kpi-metrics")
def list_kpi_metrics(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="KPI_METRICS_VIEW")
    stmt = select(KpiMetric).where(KpiMetric.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(KpiMetric.is_active.is_(True))
    rows = db.scalars(stmt.order_by(KpiMetric.sort_order.asc(), KpiMetric.id.asc())).all()
    usage_by_metric = _build_kpi_usage_map(db, venue_id=venue_id)
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "unit": r.unit,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
            **usage_by_metric.get(int(r.id), {
                "usage_component_count": 0,
                "usage_bonus_component_count": 0,
                "usage_boost_component_count": 0,
                "usage_bonus_profile_count": 0,
                "usage_boost_profile_count": 0,
            }),
        }
        for r in rows
    ]


@router.post("/{venue_id}/kpi-metrics")
def create_kpi_metric(
    venue_id: int,
    payload: KpiMetricCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="KPI_METRICS_CREATE")
    unit = (payload.unit or "QTY").strip().upper()
    obj = KpiMetric(
        venue_id=venue_id,
        code=_normalize_code(payload.code),
        title=payload.title.strip(),
        unit=unit,
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="KPI code already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/kpi-metrics/{kpi_metric_id}")
def update_kpi_metric(
    venue_id: int,
    kpi_metric_id: int,
    payload: KpiMetricUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="KPI_METRICS_EDIT")
    obj = db.execute(
        select(KpiMetric).where(KpiMetric.id == kpi_metric_id, KpiMetric.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="KPI metric not found")

    if payload.is_active is not None and bool(payload.is_active) != bool(obj.is_active):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="KPI_METRICS_ARCHIVE")
        obj.is_active = bool(payload.is_active)
    if payload.code is not None:
        obj.code = _normalize_code(payload.code)

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.unit is not None:
        obj.unit = (payload.unit or "QTY").strip().upper()
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="KPI code already exists")
    return {"ok": True}


@router.get("/{venue_id}/expense-categories")
def list_expense_categories(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    stmt = select(ExpenseCategory).where(ExpenseCategory.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(ExpenseCategory.is_active.is_(True))
    rows = db.scalars(stmt.order_by(ExpenseCategory.sort_order.asc(), ExpenseCategory.id.asc())).all()
    return [
        {
            "id": r.id,
            "code": r.code,
            "title": r.title,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
        }
        for r in rows
    ]


@router.post("/{venue_id}/expense-categories")
def create_expense_category(
    venue_id: int,
    payload: CatalogItemCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    obj = ExpenseCategory(
        venue_id=venue_id,
        code=_normalize_code(payload.code),
        title=payload.title.strip(),
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Expense category code already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/expense-categories/{category_id}")
def update_expense_category(
    venue_id: int,
    category_id: int,
    payload: CatalogItemUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    obj = _get_expense_category_or_404(db, venue_id=venue_id, category_id=category_id)

    if payload.code is not None:
        obj.code = _normalize_code(payload.code)
    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.is_active is not None:
        obj.is_active = bool(payload.is_active)
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Expense category code already exists")
    return {"ok": True}


@router.get("/{venue_id}/suppliers")
def list_suppliers(
    venue_id: int,
    include_archived: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    stmt = select(Supplier).where(Supplier.venue_id == venue_id)
    if not include_archived:
        stmt = stmt.where(Supplier.is_active.is_(True))
    rows = db.scalars(stmt.order_by(Supplier.sort_order.asc(), Supplier.id.asc())).all()
    return [
        {
            "id": r.id,
            "title": r.title,
            "contact": r.contact,
            "is_active": bool(r.is_active),
            "sort_order": int(r.sort_order or 0),
        }
        for r in rows
    ]


@router.post("/{venue_id}/suppliers")
def create_supplier(
    venue_id: int,
    payload: SupplierCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    obj = Supplier(
        venue_id=venue_id,
        title=payload.title.strip(),
        contact=(payload.contact or None),
        is_active=bool(payload.is_active),
        sort_order=int(payload.sort_order or 0),
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Supplier title already exists")
    db.refresh(obj)
    return {"id": obj.id}


@router.patch("/{venue_id}/suppliers/{supplier_id}")
def update_supplier(
    venue_id: int,
    supplier_id: int,
    payload: SupplierUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_CATEGORIES_MANAGE")
    obj = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=supplier_id)

    if payload.title is not None:
        obj.title = payload.title.strip()
    if payload.contact is not None:
        obj.contact = payload.contact or None
    if payload.is_active is not None:
        obj.is_active = bool(payload.is_active)
    if payload.sort_order is not None:
        obj.sort_order = int(payload.sort_order)
    obj.updated_at = datetime.utcnow()

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="Supplier title already exists")
    return {"ok": True}




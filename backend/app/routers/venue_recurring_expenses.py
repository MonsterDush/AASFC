from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.venue_permissions import require_venue_permission
from app.core.db import get_db
from app.models.expense import Expense
from app.models.expense_category import ExpenseCategory
from app.models.payment_method import PaymentMethod
from app.models.recurring_expense_accrual import RecurringExpenseAccrual
from app.models.recurring_expense_rule import RecurringExpenseRule
from app.models.supplier import Supplier
from app.models.user import User
from app.routers.venue_access import (
    is_owner_or_super_admin as _is_owner_or_super_admin,
    require_active_member_or_admin as _require_active_member_or_admin,
)
from app.routers.venue_catalogs import (
    _get_expense_category_or_404,
    _get_payment_method_or_404,
    _get_supplier_or_404,
)
from app.routers.venue_expenses import _serialize_expense
from app.schemas.finance import RecurringExpenseRuleCreateIn, RecurringExpenseRuleUpdateIn
from app.services.finance.expenses import list_expense_allocations
from app.services.finance.recurring_expenses import (
    generate_draft_expenses_for_month,
    list_rule_payment_method_ids,
    normalize_rule_fields,
    replace_rule_payment_methods,
)


router = APIRouter()


def _serialize_recurring_expense_rule(
    rule: RecurringExpenseRule,
    category: ExpenseCategory | None = None,
    supplier: Supplier | None = None,
    payment_method: PaymentMethod | None = None,
    basis_payment_methods: list[PaymentMethod] | None = None,
) -> dict:
    cat = category or getattr(rule, "category", None)
    sup = supplier or getattr(rule, "supplier", None)
    pm = payment_method or getattr(rule, "payment_method", None)
    basis = basis_payment_methods
    if basis is None:
        basis = [getattr(link, "payment_method", None) for link in (getattr(rule, "payment_method_links", []) or [])]
        basis = [x for x in basis if x is not None]
    return {
        "id": rule.id,
        "venue_id": rule.venue_id,
        "title": rule.title,
        "shift_slot": str(getattr(rule, "shift_slot", "TOTAL") or "TOTAL").upper(),
        "category_id": rule.category_id,
        "supplier_id": rule.supplier_id,
        "payment_method_id": rule.payment_method_id,
        "is_active": bool(rule.is_active),
        "start_date": rule.start_date.isoformat() if rule.start_date else None,
        "end_date": rule.end_date.isoformat() if rule.end_date else None,
        "frequency": str(rule.frequency or "MONTHLY").upper(),
        "day_of_month": int(rule.day_of_month or 1),
        "generation_mode": str(rule.generation_mode or "FIXED").upper(),
        "amount_minor": int(rule.amount_minor or 0) if rule.amount_minor is not None else None,
        "percent_bps": int(rule.percent_bps or 0) if rule.percent_bps is not None else None,
        "spread_months": int(rule.spread_months or 1),
        "description": rule.description,
        "created_by_user_id": rule.created_by_user_id,
        "created_at": rule.created_at.isoformat() if rule.created_at else None,
        "updated_at": rule.updated_at.isoformat() if rule.updated_at else None,
        "category": {
            "id": cat.id,
            "code": cat.code,
            "title": cat.title,
        }
        if cat is not None
        else None,
        "supplier": {
            "id": sup.id,
            "title": sup.title,
            "contact": sup.contact,
        }
        if sup is not None
        else None,
        "payment_method": {
            "id": pm.id,
            "code": pm.code,
            "title": pm.title,
        }
        if pm is not None
        else None,
        "basis_payment_methods": [{"id": item.id, "code": item.code, "title": item.title} for item in basis],
        "payment_method_ids": [int(item.id) for item in basis],
    }


def _require_recurring_expenses_view(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="RECURRING_EXPENSES_VIEW")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")


def _require_recurring_expenses_manage(db: Session, *, venue_id: int, user: User) -> None:
    if _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        return
    try:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="RECURRING_EXPENSES_MANAGE")
        return
    except HTTPException:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")


@router.get("/{venue_id}/recurring-expense-rules")
def list_recurring_expense_rules(
    venue_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_recurring_expenses_view(db, venue_id=venue_id, user=user)

    rows = (
        db.execute(
            select(RecurringExpenseRule)
            .where(RecurringExpenseRule.venue_id == venue_id)
            .order_by(
                RecurringExpenseRule.is_active.desc(), RecurringExpenseRule.title.asc(), RecurringExpenseRule.id.asc()
            )
        )
        .scalars()
        .all()
    )

    out = []
    for rule in rows:
        category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=rule.category_id)
        supplier = (
            _get_supplier_or_404(db, venue_id=venue_id, supplier_id=rule.supplier_id) if rule.supplier_id else None
        )
        payment_method = (
            _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=rule.payment_method_id)
            if rule.payment_method_id
            else None
        )
        basis_ids = list_rule_payment_method_ids(db=db, rule_id=rule.id)
        basis_payment_methods = []
        if basis_ids:
            basis_payment_methods = (
                db.execute(
                    select(PaymentMethod).where(PaymentMethod.id.in_(basis_ids)).order_by(PaymentMethod.title.asc())
                )
                .scalars()
                .all()
            )
        out.append(_serialize_recurring_expense_rule(rule, category, supplier, payment_method, basis_payment_methods))
    return out


@router.post("/{venue_id}/recurring-expense-rules")
def create_recurring_expense_rule(
    venue_id: int,
    payload: RecurringExpenseRuleCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recurring_expenses_manage(db, venue_id=venue_id, user=user)
    _get_expense_category_or_404(db, venue_id=venue_id, category_id=payload.category_id)
    if payload.supplier_id is not None:
        _get_supplier_or_404(db, venue_id=venue_id, supplier_id=payload.supplier_id)
    if payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
    for payment_method_id in payload.payment_method_ids:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payment_method_id)

    mode, freq, amount_minor, percent_bps = normalize_rule_fields(
        generation_mode=payload.generation_mode,
        frequency=payload.frequency,
        amount_minor=payload.amount_minor,
        percent_bps=payload.percent_bps,
    )
    rule = RecurringExpenseRule(
        venue_id=venue_id,
        title=payload.title.strip(),
        shift_slot=str(payload.shift_slot or "TOTAL").upper(),
        category_id=int(payload.category_id),
        supplier_id=int(payload.supplier_id) if payload.supplier_id is not None else None,
        payment_method_id=int(payload.payment_method_id) if payload.payment_method_id is not None else None,
        is_active=bool(payload.is_active),
        start_date=payload.start_date,
        end_date=payload.end_date,
        frequency=freq,
        day_of_month=int(payload.day_of_month or 1),
        generation_mode=mode,
        amount_minor=amount_minor,
        percent_bps=percent_bps,
        spread_months=int(payload.spread_months or 1),
        description=(payload.description or None),
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(rule)
    db.flush()
    replace_rule_payment_methods(db=db, rule_id=rule.id, payment_method_ids=payload.payment_method_ids)
    db.commit()
    db.refresh(rule)
    category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=rule.category_id)
    supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=rule.supplier_id) if rule.supplier_id else None
    payment_method = (
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=rule.payment_method_id)
        if rule.payment_method_id
        else None
    )
    basis_payment_methods = (
        db.execute(
            select(PaymentMethod)
            .where(PaymentMethod.id.in_(payload.payment_method_ids))
            .order_by(PaymentMethod.title.asc())
        )
        .scalars()
        .all()
        if payload.payment_method_ids
        else []
    )
    return _serialize_recurring_expense_rule(rule, category, supplier, payment_method, basis_payment_methods)


@router.patch("/{venue_id}/recurring-expense-rules/{rule_id}")
def update_recurring_expense_rule(
    venue_id: int,
    rule_id: int,
    payload: RecurringExpenseRuleUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recurring_expenses_manage(db, venue_id=venue_id, user=user)
    rule = db.execute(
        select(RecurringExpenseRule).where(
            RecurringExpenseRule.id == rule_id, RecurringExpenseRule.venue_id == venue_id
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Recurring expense rule not found")

    if payload.title is not None:
        rule.title = payload.title.strip()
    if payload.shift_slot is not None:
        rule.shift_slot = str(payload.shift_slot or "TOTAL").upper()
    if payload.category_id is not None:
        _get_expense_category_or_404(db, venue_id=venue_id, category_id=payload.category_id)
        rule.category_id = int(payload.category_id)
    if payload.clear_supplier:
        rule.supplier_id = None
    elif payload.supplier_id is not None:
        _get_supplier_or_404(db, venue_id=venue_id, supplier_id=payload.supplier_id)
        rule.supplier_id = int(payload.supplier_id)
    if payload.clear_payment_method:
        rule.payment_method_id = None
    elif payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
        rule.payment_method_id = int(payload.payment_method_id)
    if payload.is_active is not None:
        rule.is_active = bool(payload.is_active)
    if payload.start_date is not None:
        rule.start_date = payload.start_date
    if payload.clear_end_date:
        rule.end_date = None
    elif payload.end_date is not None:
        rule.end_date = payload.end_date
    if payload.day_of_month is not None:
        rule.day_of_month = int(payload.day_of_month)
    if payload.spread_months is not None:
        rule.spread_months = int(payload.spread_months)
    if payload.description is not None:
        rule.description = payload.description or None

    mode_value = payload.generation_mode if payload.generation_mode is not None else rule.generation_mode
    freq_value = payload.frequency if payload.frequency is not None else rule.frequency
    amount_value = payload.amount_minor if payload.amount_minor is not None else rule.amount_minor
    percent_value = payload.percent_bps if payload.percent_bps is not None else rule.percent_bps
    mode, freq, amount_minor, percent_bps = normalize_rule_fields(
        generation_mode=mode_value,
        frequency=freq_value,
        amount_minor=amount_value,
        percent_bps=percent_value,
    )
    rule.generation_mode = mode
    rule.frequency = freq
    rule.amount_minor = amount_minor
    rule.percent_bps = percent_bps
    rule.updated_at = datetime.utcnow()

    if payload.payment_method_ids is not None:
        for payment_method_id in payload.payment_method_ids:
            _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payment_method_id)
        replace_rule_payment_methods(db=db, rule_id=rule.id, payment_method_ids=payload.payment_method_ids)

    db.commit()
    db.refresh(rule)
    category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=rule.category_id)
    supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=rule.supplier_id) if rule.supplier_id else None
    payment_method = (
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=rule.payment_method_id)
        if rule.payment_method_id
        else None
    )
    basis_ids = list_rule_payment_method_ids(db=db, rule_id=rule.id)
    basis_payment_methods = (
        db.execute(select(PaymentMethod).where(PaymentMethod.id.in_(basis_ids)).order_by(PaymentMethod.title.asc()))
        .scalars()
        .all()
        if basis_ids
        else []
    )
    return _serialize_recurring_expense_rule(rule, category, supplier, payment_method, basis_payment_methods)


@router.delete("/{venue_id}/recurring-expense-rules/{rule_id}")
def delete_recurring_expense_rule(
    venue_id: int,
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recurring_expenses_manage(db, venue_id=venue_id, user=user)
    rule = db.execute(
        select(RecurringExpenseRule).where(
            RecurringExpenseRule.id == rule_id, RecurringExpenseRule.venue_id == venue_id
        )
    ).scalar_one_or_none()
    if rule is None:
        raise HTTPException(status_code=404, detail="Recurring expense rule not found")
    db.execute(
        update(Expense)
        .where(Expense.venue_id == venue_id, Expense.recurring_rule_id == int(rule.id))
        .values(recurring_rule_id=None)
    )
    db.execute(delete(RecurringExpenseAccrual).where(RecurringExpenseAccrual.rule_id == int(rule.id)))
    db.delete(rule)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/recurring-expense-rules/generate")
def generate_recurring_expense_drafts(
    venue_id: int,
    month: str = Query(..., description="YYYY-MM"),
    rule_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_recurring_expenses_manage(db, venue_id=venue_id, user=user)
    try:
        result = generate_draft_expenses_for_month(
            db=db,
            venue_id=venue_id,
            month=month,
            created_by_user_id=user.id,
            rule_id=rule_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    created_payload = []
    for expense in result["created"]:
        category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=expense.category_id)
        supplier = (
            _get_supplier_or_404(db, venue_id=venue_id, supplier_id=expense.supplier_id)
            if expense.supplier_id
            else None
        )
        payment_method = (
            _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=expense.payment_method_id)
            if expense.payment_method_id
            else None
        )
        allocations = list_expense_allocations(db=db, expense_id=expense.id)
        created_payload.append(_serialize_expense(expense, category, supplier, payment_method, allocations))

    updated_payload = []
    for expense in result.get("updated", []):
        category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=expense.category_id)
        supplier = (
            _get_supplier_or_404(db, venue_id=venue_id, supplier_id=expense.supplier_id)
            if expense.supplier_id
            else None
        )
        payment_method = (
            _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=expense.payment_method_id)
            if expense.payment_method_id
            else None
        )
        allocations = list_expense_allocations(db=db, expense_id=expense.id)
        updated_payload.append(_serialize_expense(expense, category, supplier, payment_method, allocations))

    db.commit()
    return {
        "month": result["month"],
        "created_count": result["created_count"],
        "updated_count": result.get("updated_count", 0),
        "skipped_count": result["skipped_count"],
        "created": created_payload,
        "updated": updated_payload,
        "skipped": result["skipped"],
    }

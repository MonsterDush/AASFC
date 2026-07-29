from __future__ import annotations

import calendar
from datetime import date, datetime
import os
import re
from urllib.parse import quote
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, get_current_user_optional
from app.auth.venue_permissions import require_venue_permission
from app.core.db import get_db
from app.models.expense import Expense
from app.models.expense_allocation import ExpenseAllocation
from app.models.expense_attachment import ExpenseAttachment
from app.models.expense_category import ExpenseCategory
from app.models.payment_method import PaymentMethod
from app.models.supplier import Supplier
from app.models.user import User
from app.routers.venue_catalogs import (
    _get_expense_category_or_404,
    _get_payment_method_or_404,
    _get_supplier_or_404,
)
from app.schemas.finance import ExpenseCreateIn, ExpenseUpdateIn
from app.services.finance.expenses import (
    delete_expense_allocations_for_expense,
    list_expense_allocations,
    rebuild_expense_allocations_for_expense,
)
from app.services.financial_privacy import sanitize_financial_payload_for_user
from app.services.signed_links import make_signed_token, verify_signed_token
from app.settings import settings


router = APIRouter()


def _serialize_expense_allocation(allocation: ExpenseAllocation) -> dict:
    return {
        "id": allocation.id,
        "expense_id": allocation.expense_id,
        "venue_id": allocation.venue_id,
        "month": allocation.month.isoformat() if allocation.month else None,
        "amount_minor": int(allocation.amount_minor or 0),
        "created_at": allocation.created_at.isoformat() if allocation.created_at else None,
    }


def _serialize_expense_attachment(attachment: ExpenseAttachment) -> dict:
    path = f"/venues/{attachment.venue_id}/expenses/{attachment.expense_id}/attachments/{attachment.id}"
    return {
        "id": attachment.id,
        "expense_id": attachment.expense_id,
        "file_name": attachment.file_name,
        "content_type": attachment.content_type,
        "file_size": int(getattr(attachment, "file_size", 0) or 0),
        "created_at": attachment.created_at.isoformat() if attachment.created_at else None,
        "url": path,
        "download_link_url": f"{path}/download-link",
    }


def _expense_attachment_token_payload(attachment: ExpenseAttachment) -> dict:
    return {
        "action": "expense_attachment_download",
        "venue_id": int(attachment.venue_id),
        "expense_id": int(attachment.expense_id),
        "attachment_id": int(attachment.id),
    }


def _expense_attachment_signed_url(base_url: str, attachment: ExpenseAttachment) -> str:
    token = make_signed_token(_expense_attachment_token_payload(attachment))
    base = str(base_url or "").rstrip("/")
    path = f"/venues/{attachment.venue_id}/expenses/{attachment.expense_id}/attachments/{attachment.id}"
    return f"{base}{path}?token={quote(token)}"


def _get_expense_attachment_or_404(
    db: Session,
    *,
    venue_id: int,
    expense_id: int,
    attachment_id: int,
) -> ExpenseAttachment:
    attachment = db.execute(
        select(ExpenseAttachment).where(
            ExpenseAttachment.id == int(attachment_id),
            ExpenseAttachment.venue_id == int(venue_id),
            ExpenseAttachment.expense_id == int(expense_id),
            ExpenseAttachment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    return attachment


def _verify_expense_attachment_token(token: str | None, *, venue_id: int, expense_id: int, attachment_id: int) -> None:
    if not token:
        raise HTTPException(status_code=401, detail="Invalid attachment token")
    try:
        payload = verify_signed_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid attachment token")
    if str(payload.get("action") or "") != "expense_attachment_download":
        raise HTTPException(status_code=401, detail="Invalid attachment token")
    if int(payload.get("venue_id") or 0) != int(venue_id):
        raise HTTPException(status_code=401, detail="Invalid attachment token")
    if int(payload.get("expense_id") or 0) != int(expense_id):
        raise HTTPException(status_code=401, detail="Invalid attachment token")
    if int(payload.get("attachment_id") or 0) != int(attachment_id):
        raise HTTPException(status_code=401, detail="Invalid attachment token")


def _expense_attachment_file_response(attachment: ExpenseAttachment) -> FileResponse:
    if not attachment.storage_path or not os.path.exists(attachment.storage_path):
        raise HTTPException(status_code=404, detail="File missing")
    return FileResponse(
        attachment.storage_path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.file_name,
    )


def _list_active_expense_attachments(db: Session, *, venue_id: int, expense_id: int) -> list[ExpenseAttachment]:
    return list(
        db.execute(
            select(ExpenseAttachment)
            .where(
                ExpenseAttachment.venue_id == venue_id,
                ExpenseAttachment.expense_id == expense_id,
                ExpenseAttachment.is_active.is_(True),
            )
            .order_by(ExpenseAttachment.id.asc())
        ).scalars().all()
    )


def _get_expense_or_404(db: Session, *, venue_id: int, expense_id: int) -> Expense:
    obj = db.execute(
        select(Expense).where(Expense.id == expense_id, Expense.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    return obj


_EXPENSE_ATTACHMENT_ALLOWED_EXTENSIONS = {
    ".pdf",
    ".jpg", ".jpeg", ".png", ".webp", ".heic",
    ".doc", ".docx", ".xls", ".xlsx", ".csv",
    ".txt", ".rtf",
    ".zip", ".rar",
}
_EXPENSE_ATTACHMENT_MAX_BYTES = 20 * 1024 * 1024


def _safe_upload_filename(filename: str | None) -> str:
    raw = os.path.basename(str(filename or "file")).strip() or "file"
    return re.sub(r"[^0-9A-Za-zА-Яа-яЁё._()\- ]+", "_", raw)[:180] or "file"


def _serialize_expense(
    expense: Expense,
    category: ExpenseCategory | None = None,
    supplier: Supplier | None = None,
    payment_method: PaymentMethod | None = None,
    allocations: list[ExpenseAllocation] | None = None,
) -> dict:
    cat = category or getattr(expense, "category", None)
    sup = supplier or getattr(expense, "supplier", None)
    pm = payment_method or getattr(expense, "payment_method", None)
    allocs = allocations if allocations is not None else list(getattr(expense, "allocations", []) or [])
    attachments = [a for a in list(getattr(expense, "attachments", []) or []) if getattr(a, "is_active", True)]
    return {
        "id": expense.id,
        "venue_id": expense.venue_id,
        "category_id": expense.category_id,
        "supplier_id": expense.supplier_id,
        "payment_method_id": expense.payment_method_id,
        "recurring_rule_id": expense.recurring_rule_id,
        "amount_minor": int(expense.amount_minor or 0),
        "expense_date": expense.expense_date.isoformat() if expense.expense_date else None,
        "shift_slot": str(getattr(expense, "shift_slot", "TOTAL") or "TOTAL").upper(),
        "generated_for_month": expense.generated_for_month.isoformat() if expense.generated_for_month else None,
        "spread_months": int(expense.spread_months or 1),
        "status": str(getattr(expense, 'status', 'CONFIRMED') or 'CONFIRMED').upper(),
        "comment": expense.comment,
        "created_by_user_id": expense.created_by_user_id,
        "created_at": expense.created_at.isoformat() if expense.created_at else None,
        "updated_at": expense.updated_at.isoformat() if expense.updated_at else None,
        "category": {
            "id": cat.id,
            "code": cat.code,
            "title": cat.title,
        } if cat is not None else None,
        "supplier": {
            "id": sup.id,
            "title": sup.title,
            "contact": sup.contact,
        } if sup is not None else None,
        "payment_method": {
            "id": pm.id,
            "code": pm.code,
            "title": pm.title,
        } if pm is not None else None,
        "allocations": [_serialize_expense_allocation(a) for a in allocs],
        "attachments": [_serialize_expense_attachment(a) for a in attachments],
        "attachments_count": len(attachments),
    }


def _parse_expense_statuses_filter(statuses: str | None) -> list[str] | None:
    if statuses is None:
        return None
    normalized = []
    for raw in str(statuses).split(','):
        value = raw.strip().upper()
        if not value:
            continue
        if value not in {'DRAFT', 'CONFIRMED', 'CANCELLED'}:
            raise HTTPException(status_code=400, detail='Bad status filter, expected DRAFT, CONFIRMED, CANCELLED')
        if value not in normalized:
            normalized.append(value)
    return normalized or None


def _collect_expense_status_stats(*, rows: list[tuple[Expense, ExpenseCategory, Supplier | None, PaymentMethod | None]], statuses: list[str] | None = None) -> dict:
    counts: dict[str, int] = {'DRAFT': 0, 'CONFIRMED': 0, 'CANCELLED': 0}
    totals: dict[str, int] = {'DRAFT': 0, 'CONFIRMED': 0, 'CANCELLED': 0}
    filtered_count = 0
    filtered_total = 0
    for expense, *_ in rows:
        status = str(getattr(expense, 'status', 'DRAFT') or 'DRAFT').upper()
        counts[status] = counts.get(status, 0) + 1
        totals[status] = totals.get(status, 0) + int(getattr(expense, 'amount_minor', 0) or 0)
        if statuses is None or status in statuses:
            filtered_count += 1
            filtered_total += int(getattr(expense, 'amount_minor', 0) or 0)
    return {
        'count': filtered_count,
        'total_minor': filtered_total,
        'draft_count': counts.get('DRAFT', 0),
        'draft_total_minor': totals.get('DRAFT', 0),
        'confirmed_count': counts.get('CONFIRMED', 0),
        'confirmed_total_minor': totals.get('CONFIRMED', 0),
        'cancelled_count': counts.get('CANCELLED', 0),
        'cancelled_total_minor': totals.get('CANCELLED', 0),
    }


@router.get("/{venue_id}/expenses")
def list_expenses(
    venue_id: int,
    month: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    statuses: str | None = Query(default=None, description='Comma-separated statuses: DRAFT,CONFIRMED,CANCELLED'),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")

    stmt = select(Expense, ExpenseCategory, Supplier, PaymentMethod).join(
        ExpenseCategory, ExpenseCategory.id == Expense.category_id
    ).outerjoin(
        Supplier, Supplier.id == Expense.supplier_id
    ).outerjoin(
        PaymentMethod, PaymentMethod.id == Expense.payment_method_id
    ).where(Expense.venue_id == venue_id)

    recognized_month = None
    period_start = None
    period_end = None
    if month:
        try:
            recognized_month = datetime.strptime(month, "%Y-%m").date().replace(day=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        _, last_day = calendar.monthrange(recognized_month.year, recognized_month.month)
        period_start = recognized_month
        period_end = recognized_month.replace(day=last_day)
        stmt = stmt.outerjoin(ExpenseAllocation, ExpenseAllocation.expense_id == Expense.id).where(
            (ExpenseAllocation.month == recognized_month)
            | ((Expense.status != 'CONFIRMED') & (Expense.generated_for_month == recognized_month))
            | ((Expense.status != 'CONFIRMED') & (Expense.expense_date >= period_start) & (Expense.expense_date <= period_end))
        )

    if category_id is not None:
        stmt = stmt.where(Expense.category_id == category_id)
    if supplier_id is not None:
        stmt = stmt.where(Expense.supplier_id == supplier_id)

    rows = db.execute(stmt.distinct().order_by(Expense.expense_date.desc(), Expense.id.desc())).all()
    status_filter = _parse_expense_statuses_filter(statuses)
    if status_filter:
        rows = [row for row in rows if str(getattr(row[0], 'status', 'DRAFT') or 'DRAFT').upper() in status_filter]
    result = []
    for expense, category, supplier, payment_method in rows:
        allocations = list_expense_allocations(db=db, expense_id=expense.id)
        recognized_allocations = [a for a in allocations if recognized_month is not None and a.month == recognized_month]
        payload = _serialize_expense(expense, category, supplier, payment_method, allocations)
        payload["recognized_allocations"] = [_serialize_expense_allocation(a) for a in recognized_allocations]
        payload["recognized_amount_minor_for_month"] = int(sum(int(a.amount_minor or 0) for a in recognized_allocations))
        result.append(payload)
    return sanitize_financial_payload_for_user(user, result)


@router.get("/{venue_id}/expenses/stats")
def get_expense_stats(
    venue_id: int,
    month: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    supplier_id: int | None = Query(default=None),
    statuses: str | None = Query(default=None, description='Comma-separated statuses: DRAFT,CONFIRMED,CANCELLED'),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")

    stmt = select(Expense, ExpenseCategory, Supplier, PaymentMethod).join(
        ExpenseCategory, ExpenseCategory.id == Expense.category_id
    ).outerjoin(
        Supplier, Supplier.id == Expense.supplier_id
    ).outerjoin(
        PaymentMethod, PaymentMethod.id == Expense.payment_method_id
    ).where(Expense.venue_id == venue_id)

    recognized_month = None
    period_start = None
    period_end = None
    if month:
        try:
            recognized_month = datetime.strptime(month, "%Y-%m").date().replace(day=1)
        except ValueError:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
        _, last_day = calendar.monthrange(recognized_month.year, recognized_month.month)
        period_start = recognized_month
        period_end = recognized_month.replace(day=last_day)
        stmt = stmt.outerjoin(ExpenseAllocation, ExpenseAllocation.expense_id == Expense.id).where(
            (ExpenseAllocation.month == recognized_month)
            | ((Expense.status != 'CONFIRMED') & (Expense.generated_for_month == recognized_month))
            | ((Expense.status != 'CONFIRMED') & (Expense.expense_date >= period_start) & (Expense.expense_date <= period_end))
        )

    if category_id is not None:
        stmt = stmt.where(Expense.category_id == category_id)
    if supplier_id is not None:
        stmt = stmt.where(Expense.supplier_id == supplier_id)

    rows = db.execute(stmt.distinct().order_by(Expense.expense_date.desc(), Expense.id.desc())).all()
    status_filter = _parse_expense_statuses_filter(statuses)
    stats = _collect_expense_status_stats(rows=rows, statuses=status_filter)
    return sanitize_financial_payload_for_user(user, {
        'month': recognized_month.isoformat() if recognized_month is not None else None,
        'statuses': status_filter or ['DRAFT', 'CONFIRMED', 'CANCELLED'],
        **stats,
    })


@router.post("/{venue_id}/expenses")
def create_expense(
    venue_id: int,
    payload: ExpenseCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    _get_expense_category_or_404(db, venue_id=venue_id, category_id=payload.category_id)
    if payload.supplier_id is not None:
        _get_supplier_or_404(db, venue_id=venue_id, supplier_id=payload.supplier_id)
    if payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)

    obj = Expense(
        venue_id=venue_id,
        category_id=int(payload.category_id),
        supplier_id=int(payload.supplier_id) if payload.supplier_id is not None else None,
        payment_method_id=int(payload.payment_method_id) if payload.payment_method_id is not None else None,
        amount_minor=int(payload.amount_minor),
        expense_date=payload.expense_date,
        shift_slot=str(payload.shift_slot or "TOTAL").upper(),
        spread_months=int(payload.spread_months or 1),
        status=str(payload.status or 'DRAFT').upper(),
        comment=(payload.comment or None),
        created_by_user_id=user.id,
        created_at=datetime.utcnow(),
    )
    db.add(obj)
    db.flush()
    allocations = rebuild_expense_allocations_for_expense(db=db, expense=obj)
    db.commit()
    db.refresh(obj)
    category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=obj.category_id)
    supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=obj.supplier_id) if obj.supplier_id else None
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.payment_method_id) if obj.payment_method_id else None
    return _serialize_expense(obj, category, supplier, payment_method, allocations)


@router.patch("/{venue_id}/expenses/{expense_id}")
def update_expense(
    venue_id: int,
    expense_id: int,
    payload: ExpenseUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    obj = db.execute(
        select(Expense).where(Expense.id == expense_id, Expense.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Expense not found")

    if payload.category_id is not None:
        _get_expense_category_or_404(db, venue_id=venue_id, category_id=payload.category_id)
        obj.category_id = int(payload.category_id)

    if payload.clear_supplier:
        obj.supplier_id = None
    elif payload.supplier_id is not None:
        _get_supplier_or_404(db, venue_id=venue_id, supplier_id=payload.supplier_id)
        obj.supplier_id = int(payload.supplier_id)

    if payload.clear_payment_method:
        obj.payment_method_id = None
    elif payload.payment_method_id is not None:
        _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=payload.payment_method_id)
        obj.payment_method_id = int(payload.payment_method_id)

    if payload.amount_minor is not None:
        obj.amount_minor = int(payload.amount_minor)
    if payload.expense_date is not None:
        obj.expense_date = payload.expense_date
    if payload.shift_slot is not None:
        obj.shift_slot = str(payload.shift_slot or "TOTAL").upper()
    if payload.spread_months is not None:
        obj.spread_months = int(payload.spread_months)
    if payload.comment is not None:
        obj.comment = payload.comment or None
    if payload.status is not None:
        obj.status = str(payload.status or 'DRAFT').upper()
    obj.updated_at = datetime.utcnow()

    allocations = rebuild_expense_allocations_for_expense(db=db, expense=obj)
    db.commit()
    db.refresh(obj)
    category = _get_expense_category_or_404(db, venue_id=venue_id, category_id=obj.category_id)
    supplier = _get_supplier_or_404(db, venue_id=venue_id, supplier_id=obj.supplier_id) if obj.supplier_id else None
    payment_method = _get_payment_method_or_404(db, venue_id=venue_id, payment_method_id=obj.payment_method_id) if obj.payment_method_id else None
    return _serialize_expense(obj, category, supplier, payment_method, allocations)


@router.delete("/{venue_id}/expenses/{expense_id}")
def delete_expense(
    venue_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    obj = db.execute(
        select(Expense).where(Expense.id == expense_id, Expense.venue_id == venue_id)
    ).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail="Expense not found")
    delete_expense_allocations_for_expense(db=db, expense_id=obj.id)
    db.delete(obj)
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/expenses/{expense_id}/attachments")
def list_expense_attachments(
    venue_id: int,
    expense_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")
    _get_expense_or_404(db, venue_id=venue_id, expense_id=expense_id)
    rows = _list_active_expense_attachments(db, venue_id=venue_id, expense_id=expense_id)
    return {"items": [_serialize_expense_attachment(a) for a in rows]}


@router.get("/{venue_id}/expenses/{expense_id}/attachments/{attachment_id}/download-link")
def get_expense_attachment_download_link(
    venue_id: int,
    expense_id: int,
    attachment_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")
    _get_expense_or_404(db, venue_id=venue_id, expense_id=expense_id)
    attachment = _get_expense_attachment_or_404(db, venue_id=venue_id, expense_id=expense_id, attachment_id=attachment_id)
    url = _expense_attachment_signed_url(str(request.base_url).rstrip("/"), attachment)
    return {
        "download_link": url,
        "preview_link": url,
        "expires_in": int(getattr(settings, 'EXPORT_LINK_TTL_SECONDS', 600) or 600),
        "file": _serialize_expense_attachment(attachment),
    }


@router.get("/{venue_id}/expenses/{expense_id}/attachments/{attachment_id}")
def download_expense_attachment(
    venue_id: int,
    expense_id: int,
    attachment_id: int,
    token: str | None = Query(None),
    db: Session = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
):
    if token:
        _verify_expense_attachment_token(token, venue_id=venue_id, expense_id=expense_id, attachment_id=attachment_id)
    else:
        if user is None:
            raise HTTPException(status_code=401, detail="Not authenticated")
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_VIEW")
    _get_expense_or_404(db, venue_id=venue_id, expense_id=expense_id)
    attachment = _get_expense_attachment_or_404(db, venue_id=venue_id, expense_id=expense_id, attachment_id=attachment_id)
    return _expense_attachment_file_response(attachment)


@router.delete("/{venue_id}/expenses/{expense_id}/attachments/{attachment_id}")
def delete_expense_attachment(
    venue_id: int,
    expense_id: int,
    attachment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    _get_expense_or_404(db, venue_id=venue_id, expense_id=expense_id)
    attachment = db.execute(
        select(ExpenseAttachment).where(
            ExpenseAttachment.id == attachment_id,
            ExpenseAttachment.venue_id == venue_id,
            ExpenseAttachment.expense_id == expense_id,
            ExpenseAttachment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    attachment.is_active = False
    db.commit()
    try:
        if attachment.storage_path and os.path.exists(attachment.storage_path):
            os.remove(attachment.storage_path)
    except Exception:
        pass
    return {"ok": True}


@router.post("/{venue_id}/expenses/{expense_id}/attachments")
def upload_expense_attachments(
    venue_id: int,
    expense_id: int,
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    require_venue_permission(db, venue_id=venue_id, user=user, permission_code="EXPENSE_ADD")
    _get_expense_or_404(db, venue_id=venue_id, expense_id=expense_id)

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "uploads", "expenses"))
    os.makedirs(base_dir, exist_ok=True)

    created: list[ExpenseAttachment] = []
    for upload in files:
        if upload is None:
            continue
        safe_name = _safe_upload_filename(upload.filename)
        ext = os.path.splitext(safe_name.lower())[1]
        if ext not in _EXPENSE_ATTACHMENT_ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=415, detail=f"Неподдерживаемый формат файла: {ext or 'без расширения'}")

        uid = uuid.uuid4().hex
        dst = os.path.join(base_dir, f"{venue_id}_{expense_id}_{uid}_{safe_name}")
        total = 0
        try:
            with open(dst, "wb") as out:
                while True:
                    chunk = upload.file.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _EXPENSE_ATTACHMENT_MAX_BYTES:
                        raise HTTPException(status_code=413, detail="Файл слишком большой: максимум 20 МБ")
                    out.write(chunk)
        except HTTPException:
            try:
                if os.path.exists(dst):
                    os.remove(dst)
            except Exception:
                pass
            raise

        obj = ExpenseAttachment(
            venue_id=venue_id,
            expense_id=expense_id,
            file_name=safe_name,
            content_type=upload.content_type,
            file_size=total,
            storage_path=dst,
            uploaded_by_user_id=user.id,
            is_active=True,
            created_at=datetime.utcnow(),
        )
        db.add(obj)
        db.flush()
        created.append(obj)

    db.commit()
    return {"ok": True, "items": [_serialize_expense_attachment(a) for a in created]}



from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing_reconciliation_issue import BillingReconciliationIssue
from app.models.venue import Venue
from app.models.venue_billing_event import VenueBillingEvent
from app.models.venue_billing_transaction import VenueBillingTransaction
from .manager import get_checkout_expires_at

ISSUE_STATUS_OPEN = "OPEN"
ISSUE_STATUS_RESOLVED = "RESOLVED"
ISSUE_STATUS_IGNORED = "IGNORED"

ISSUE_LABELS = {
    "STALE_PENDING_CHECKOUT": "Зависший checkout",
    "INVALID_SIGNATURE": "Неверная подпись callback",
    "AMOUNT_MISMATCH": "Расхождение суммы",
    "FAILED_PAYMENT": "Ошибка оплаты",
    "DUPLICATE_CALLBACK": "Повторный callback",
    "SUCCEEDED_NOT_APPLIED": "Оплата не применена",
    "REFUND_PROCESSING_TOO_LONG": "Возврат слишком долго в обработке",
    "REFUND_CANCELED": "Возврат отменён",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _stale_pending_minutes() -> int:
    try:
        value = int(getattr(settings, "BILLING_ALERT_STALE_PENDING_MINUTES", 180) or 180)
    except (TypeError, ValueError):
        value = 180
    return max(15, value)


def _issue_severity(code: str) -> str:
    if code in {"INVALID_SIGNATURE", "AMOUNT_MISMATCH", "SUCCEEDED_NOT_APPLIED"}:
        return "critical"
    if code in {"STALE_PENDING_CHECKOUT", "FAILED_PAYMENT", "REFUND_PROCESSING_TOO_LONG", "REFUND_CANCELED"}:
        return "warning"
    return "info"


def _issue_fingerprint(*, issue_code: str, venue_id: int, transaction_id: int | None, event_id: int | None) -> str:
    return f"{str(issue_code).upper()}:{int(venue_id)}:{int(transaction_id or 0)}:{int(event_id or 0)}"


def _issue_item(
    *,
    issue_code: str,
    venue_id: int,
    venue_name: str | None,
    transaction_id: int | None = None,
    event_id: int | None = None,
    created_at: datetime | None = None,
    title: str | None = None,
    message: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_code_norm = str(issue_code or "").upper()
    return {
        "issue_code": issue_code_norm,
        "label": title or ISSUE_LABELS.get(issue_code_norm, issue_code_norm),
        "severity": _issue_severity(issue_code_norm),
        "venue_id": int(venue_id),
        "venue_name": venue_name or f"Заведение #{int(venue_id)}",
        "transaction_id": int(transaction_id) if transaction_id is not None else None,
        "event_id": int(event_id) if event_id is not None else None,
        "created_at": _ensure_aware(created_at) or _utc_now(),
        "message": message,
        "details": message,
        "raw": raw or {},
    }


def derive_billing_reconciliation_issues(
    db: Session,
    *,
    venue_id: int | None = None,
    search: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 500), 1000))
    venue_map = {
        int(v.id): str(v.name or f"Заведение #{int(v.id)}")
        for v in db.execute(select(Venue)).scalars().all()
    }
    now = _utc_now()
    issues: list[dict[str, Any]] = []

    tx_stmt = select(VenueBillingTransaction).order_by(VenueBillingTransaction.created_at.desc(), VenueBillingTransaction.id.desc())
    if venue_id is not None:
        tx_stmt = tx_stmt.where(VenueBillingTransaction.venue_id == int(venue_id))
    txs = list(db.execute(tx_stmt).scalars().all())

    event_stmt = select(VenueBillingEvent).order_by(VenueBillingEvent.created_at.desc(), VenueBillingEvent.id.desc())
    if venue_id is not None:
        event_stmt = event_stmt.where(VenueBillingEvent.venue_id == int(venue_id))
    events = list(db.execute(event_stmt).scalars().all())
    event_by_tx: dict[int, list[VenueBillingEvent]] = {}
    for event in events:
        meta = event.meta_json if isinstance(event.meta_json, dict) else {}
        tx_id = meta.get("transaction_id")
        if tx_id is None:
            continue
        try:
            tx_key = int(tx_id)
        except (TypeError, ValueError):
            continue
        event_by_tx.setdefault(tx_key, []).append(event)

    stale_cutoff = now - timedelta(minutes=_stale_pending_minutes())

    for tx in txs:
        tx_status = str(tx.status or "").upper()
        tx_type = str(tx.type or "").upper()
        v_id = int(tx.venue_id)
        v_name = venue_map.get(v_id)
        created_at = _ensure_aware(tx.created_at)
        payload = tx.provider_payload_json if isinstance(tx.provider_payload_json, dict) else {}
        if tx_type == "PAYMENT" and tx_status == "PENDING":
            expires_at = get_checkout_expires_at(tx)
            if (expires_at and expires_at <= now) or (created_at and created_at <= stale_cutoff):
                issues.append(_issue_item(
                    issue_code="STALE_PENDING_CHECKOUT",
                    venue_id=v_id,
                    venue_name=v_name,
                    transaction_id=int(tx.id),
                    created_at=expires_at or created_at,
                    message="Checkout висит слишком долго и требует проверки.",
                    raw={"status": tx_status, "expires_at": expires_at.isoformat() if expires_at else None},
                ))
        if tx_type == "PAYMENT" and tx_status == "FAILED":
            issues.append(_issue_item(
                issue_code="FAILED_PAYMENT",
                venue_id=v_id,
                venue_name=v_name,
                transaction_id=int(tx.id),
                created_at=created_at,
                message=str(tx.comment or payload.get("comment") or "Платёж завершился ошибкой."),
                raw={"status": tx_status},
            ))
        if tx_type == "PAYMENT" and tx_status == "SUCCEEDED":
            linked_events = event_by_tx.get(int(tx.id), [])
            has_success = any(str(ev.event_type or "").upper() == "ROBOKASSA_PAYMENT_SUCCEEDED" for ev in linked_events)
            if not has_success:
                issues.append(_issue_item(
                    issue_code="SUCCEEDED_NOT_APPLIED",
                    venue_id=v_id,
                    venue_name=v_name,
                    transaction_id=int(tx.id),
                    created_at=created_at,
                    message="Транзакция успешна, но событие применения продления не найдено.",
                    raw={"status": tx_status},
                ))
        if tx_type == "REFUND" and tx_status == "PENDING":
            if created_at and created_at <= stale_cutoff:
                issues.append(_issue_item(
                    issue_code="REFUND_PROCESSING_TOO_LONG",
                    venue_id=v_id,
                    venue_name=v_name,
                    transaction_id=int(tx.id),
                    created_at=created_at,
                    message="Запрос возврата слишком долго остаётся в processing.",
                    raw={"status": tx_status},
                ))
        if tx_type == "REFUND" and tx_status == "CANCELED":
            issues.append(_issue_item(
                issue_code="REFUND_CANCELED",
                venue_id=v_id,
                venue_name=v_name,
                transaction_id=int(tx.id),
                created_at=created_at,
                message=str(tx.comment or "Возврат отменён на стороне платёжного провайдера."),
                raw={"status": tx_status},
            ))

    issue_event_codes = {
        "ROBOKASSA_RESULT_SIGNATURE_INVALID": "INVALID_SIGNATURE",
        "ROBOKASSA_AMOUNT_MISMATCH": "AMOUNT_MISMATCH",
        "ROBOKASSA_RESULT_DUPLICATE": "DUPLICATE_CALLBACK",
    }
    for event in events:
        issue_code = issue_event_codes.get(str(event.event_type or "").upper())
        if not issue_code:
            continue
        meta = event.meta_json if isinstance(event.meta_json, dict) else {}
        tx_id_val = meta.get("transaction_id")
        tx_id = None
        try:
            if tx_id_val is not None:
                tx_id = int(tx_id_val)
        except (TypeError, ValueError):
            tx_id = None
        issues.append(_issue_item(
            issue_code=issue_code,
            venue_id=int(event.venue_id),
            venue_name=venue_map.get(int(event.venue_id)),
            transaction_id=tx_id,
            event_id=int(event.id),
            created_at=_ensure_aware(event.created_at),
            message=str(meta.get("details") or event.event_type),
            raw=meta,
        ))

    if search:
        needle = str(search).strip().lower()
        if needle:
            issues = [
                item for item in issues
                if needle in str(item.get("venue_name") or "").lower()
                or needle in str(item.get("message") or "").lower()
                or needle in str(item.get("issue_code") or "").lower()
            ]

    issues.sort(key=lambda item: item.get("created_at") or now, reverse=True)
    return issues[:limit]


def sync_billing_reconciliation_issues(db: Session, *, venue_id: int | None = None) -> dict[str, int]:
    now = _utc_now()
    candidates = derive_billing_reconciliation_issues(db, venue_id=venue_id, limit=1000)
    candidate_map = {
        _issue_fingerprint(
            issue_code=item["issue_code"],
            venue_id=item["venue_id"],
            transaction_id=item.get("transaction_id"),
            event_id=item.get("event_id"),
        ): item
        for item in candidates
    }

    stmt = select(BillingReconciliationIssue)
    if venue_id is not None:
        stmt = stmt.where(BillingReconciliationIssue.venue_id == int(venue_id))
    existing_rows = list(db.execute(stmt).scalars().all())
    existing_by_fp = {str(row.fingerprint): row for row in existing_rows}

    created = 0
    reopened = 0
    refreshed = 0
    auto_resolved = 0

    for fingerprint, item in candidate_map.items():
        row = existing_by_fp.get(fingerprint)
        details_json = {
            "message": item.get("message"),
            "label": item.get("label"),
            "raw": item.get("raw") or {},
            "venue_name": item.get("venue_name"),
        }
        detected_at = _ensure_aware(item.get("created_at")) or now
        if row is None:
            row = BillingReconciliationIssue(
                venue_id=int(item["venue_id"]),
                transaction_id=item.get("transaction_id"),
                event_id=item.get("event_id"),
                issue_code=str(item["issue_code"]),
                severity=str(item["severity"]),
                status=ISSUE_STATUS_OPEN,
                fingerprint=fingerprint,
                title=str(item.get("label") or ISSUE_LABELS.get(str(item["issue_code"]), item["issue_code"])),
                details_json=details_json,
                first_detected_at=detected_at,
                last_seen_at=now,
                resolved_at=None,
                resolved_by_user_id=None,
                resolution_comment=None,
            )
            db.add(row)
            created += 1
            continue

        row.venue_id = int(item["venue_id"])
        row.transaction_id = item.get("transaction_id")
        row.event_id = item.get("event_id")
        row.issue_code = str(item["issue_code"])
        row.severity = str(item["severity"])
        row.title = str(item.get("label") or row.title or item["issue_code"])
        row.details_json = details_json
        row.last_seen_at = now
        if row.status == ISSUE_STATUS_RESOLVED:
            row.status = ISSUE_STATUS_OPEN
            row.resolved_at = None
            row.resolved_by_user_id = None
            row.resolution_comment = None
            reopened += 1
        else:
            refreshed += 1

    for row in existing_rows:
        if str(row.fingerprint) in candidate_map:
            continue
        if str(row.status or ISSUE_STATUS_OPEN).upper() != ISSUE_STATUS_OPEN:
            continue
        row.status = ISSUE_STATUS_RESOLVED
        row.resolved_at = now
        row.resolution_comment = row.resolution_comment or "Автоматически закрыто системой"
        auto_resolved += 1

    db.flush()
    return {
        "created": created,
        "reopened": reopened,
        "refreshed": refreshed,
        "auto_resolved": auto_resolved,
        "open_total": int(db.execute(select(func.count()).select_from(BillingReconciliationIssue).where(BillingReconciliationIssue.status == ISSUE_STATUS_OPEN)).scalar() or 0),
    }


def _serialize_issue_row(row: BillingReconciliationIssue, *, venue_name: str | None = None) -> dict[str, Any]:
    details = row.details_json if isinstance(row.details_json, dict) else {}
    message = details.get("message") or row.title or ISSUE_LABELS.get(str(row.issue_code or "").upper(), row.issue_code)
    return {
        "id": int(row.id),
        "venue_id": int(row.venue_id),
        "venue_name": venue_name or details.get("venue_name") or f"Заведение #{int(row.venue_id)}",
        "transaction_id": int(row.transaction_id) if row.transaction_id is not None else None,
        "event_id": int(row.event_id) if row.event_id is not None else None,
        "issue_code": row.issue_code,
        "severity": row.severity,
        "status": row.status,
        "label": row.title or ISSUE_LABELS.get(str(row.issue_code or "").upper(), row.issue_code),
        "message": message,
        "details": message,
        "fingerprint": row.fingerprint,
        "created_at": (row.first_detected_at.isoformat() if row.first_detected_at else None),
        "first_detected_at": (row.first_detected_at.isoformat() if row.first_detected_at else None),
        "last_seen_at": (row.last_seen_at.isoformat() if row.last_seen_at else None),
        "resolved_at": (row.resolved_at.isoformat() if row.resolved_at else None),
        "resolved_by_user_id": int(row.resolved_by_user_id) if row.resolved_by_user_id is not None else None,
        "resolution_comment": row.resolution_comment,
        "raw": details.get("raw") or {},
    }


def list_billing_reconciliation_issues(
    db: Session,
    *,
    venue_id: int | None = None,
    search: str | None = None,
    status: str | None = ISSUE_STATUS_OPEN,
    page: int = 1,
    page_size: int = 50,
) -> tuple[list[dict[str, Any]], int]:
    stmt = select(BillingReconciliationIssue, Venue.name).join(Venue, Venue.id == BillingReconciliationIssue.venue_id)
    if venue_id is not None:
        stmt = stmt.where(BillingReconciliationIssue.venue_id == int(venue_id))
    status_norm = str(status or "").strip().upper()
    if status_norm and status_norm != "ALL":
        stmt = stmt.where(BillingReconciliationIssue.status == status_norm)
    if search:
        term = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Venue.name.ilike(term),
                BillingReconciliationIssue.issue_code.ilike(term),
                BillingReconciliationIssue.title.ilike(term),
                BillingReconciliationIssue.resolution_comment.ilike(term),
            )
        )
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int(db.execute(count_stmt).scalar() or 0)
    page_norm = max(1, int(page or 1))
    size_norm = max(1, min(500, int(page_size or 50)))
    rows = db.execute(
        stmt.order_by(BillingReconciliationIssue.last_seen_at.desc(), BillingReconciliationIssue.id.desc())
        .offset((page_norm - 1) * size_norm)
        .limit(size_norm)
    ).all()
    return [_serialize_issue_row(row, venue_name=venue_name) for row, venue_name in rows], total


def set_billing_reconciliation_issue_status(
    db: Session,
    *,
    issue_id: int,
    new_status: str,
    acted_by_user_id: int | None,
    comment: str | None = None,
) -> BillingReconciliationIssue:
    row = db.execute(select(BillingReconciliationIssue).where(BillingReconciliationIssue.id == int(issue_id))).scalar_one_or_none()
    if row is None:
        raise ValueError("Billing reconciliation issue not found")
    now = _utc_now()
    status_norm = str(new_status or ISSUE_STATUS_OPEN).strip().upper()
    if status_norm not in {ISSUE_STATUS_OPEN, ISSUE_STATUS_RESOLVED, ISSUE_STATUS_IGNORED}:
        raise ValueError("Unsupported billing reconciliation issue status")
    row.status = status_norm
    row.resolution_comment = comment
    if status_norm == ISSUE_STATUS_OPEN:
        row.resolved_at = None
        row.resolved_by_user_id = None
    else:
        row.resolved_at = now
        row.resolved_by_user_id = acted_by_user_id
    db.flush()
    return row


def get_billing_health_summary(db: Session) -> dict[str, Any]:
    open_rows = list(
        db.execute(
            select(BillingReconciliationIssue)
            .where(BillingReconciliationIssue.status == ISSUE_STATUS_OPEN)
            .order_by(BillingReconciliationIssue.last_seen_at.desc(), BillingReconciliationIssue.id.desc())
        ).scalars().all()
    )
    counts = {"critical": 0, "warning": 0, "info": 0}
    code_counts: dict[str, int] = {}
    for row in open_rows:
        severity = str(row.severity or "info")
        counts[severity] = counts.get(severity, 0) + 1
        code = str(row.issue_code or "UNKNOWN")
        code_counts[code] = code_counts.get(code, 0) + 1
    recent_failed = db.execute(
        select(VenueBillingTransaction)
        .where(
            VenueBillingTransaction.type == "PAYMENT",
            VenueBillingTransaction.status == "FAILED",
            VenueBillingTransaction.created_at >= _utc_now() - timedelta(hours=24),
        )
        .order_by(VenueBillingTransaction.created_at.desc())
    ).scalars().all()
    stale_pending = sum(1 for row in open_rows if str(row.issue_code or "").upper() == "STALE_PENDING_CHECKOUT")
    recent_issues, _ = list_billing_reconciliation_issues(db, status=ISSUE_STATUS_OPEN, page=1, page_size=10)
    return {
        "totals": {
            "issues_total": len(open_rows),
            "critical": counts.get("critical", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
            "failed_payments_24h": len(recent_failed),
            "stale_pending": stale_pending,
        },
        "severity": counts,
        "failed_checkout_24h": len(recent_failed),
        "issues_total": len(open_rows),
        "by_issue_code": code_counts,
        "top_issue_codes": [{"code": code, "count": count} for code, count in sorted(code_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]],
        "recent_issues": recent_issues,
    }

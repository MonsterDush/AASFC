from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.venue import Venue
from app.models.venue_billing_event import VenueBillingEvent
from app.models.venue_billing_transaction import VenueBillingTransaction
from .manager import get_checkout_expires_at


ISSUE_LABELS = {
    "STALE_PENDING_CHECKOUT": "Зависший checkout",
    "INVALID_SIGNATURE": "Неверная подпись callback",
    "AMOUNT_MISMATCH": "Расхождение суммы",
    "FAILED_PAYMENT": "Ошибка оплаты",
    "DUPLICATE_CALLBACK": "Повторный callback",
    "SUCCEEDED_NOT_APPLIED": "Оплата не применена",
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
    if code in {"STALE_PENDING_CHECKOUT", "FAILED_PAYMENT"}:
        return "warning"
    return "info"


def _issue_item(
    *,
    issue_code: str,
    venue_id: int,
    venue_name: str | None,
    transaction_id: int | None = None,
    event_id: int | None = None,
    created_at: datetime | None = None,
    title: str | None = None,
    details: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "issue_code": issue_code,
        "label": title or ISSUE_LABELS.get(issue_code, issue_code),
        "severity": _issue_severity(issue_code),
        "venue_id": int(venue_id),
        "venue_name": venue_name or f"Заведение #{int(venue_id)}",
        "transaction_id": int(transaction_id) if transaction_id is not None else None,
        "event_id": int(event_id) if event_id is not None else None,
        "created_at": created_at.isoformat() if created_at else None,
        "details": details,
        "raw": raw or {},
    }


def derive_billing_reconciliation_issues(
    db: Session,
    *,
    venue_id: int | None = None,
    search: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 200), 500))
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
                    details="Checkout висит слишком долго и требует проверки.",
                    raw={"status": tx_status, "expires_at": expires_at.isoformat() if expires_at else None},
                ))
        if tx_type == "PAYMENT" and tx_status == "FAILED":
            issues.append(_issue_item(
                issue_code="FAILED_PAYMENT",
                venue_id=v_id,
                venue_name=v_name,
                transaction_id=int(tx.id),
                created_at=created_at,
                details=str(tx.comment or payload.get("comment") or "Платёж завершился ошибкой."),
                raw={"status": tx_status},
            ))
        if tx_status == "SUCCEEDED":
            linked_events = event_by_tx.get(int(tx.id), [])
            has_success = any(str(ev.event_type or "").upper() == "ROBOKASSA_PAYMENT_SUCCEEDED" for ev in linked_events)
            if not has_success:
                issues.append(_issue_item(
                    issue_code="SUCCEEDED_NOT_APPLIED",
                    venue_id=v_id,
                    venue_name=v_name,
                    transaction_id=int(tx.id),
                    created_at=created_at,
                    details="Транзакция успешна, но событие применения продления не найдено.",
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
        issues.append(_issue_item(
            issue_code=issue_code,
            venue_id=int(event.venue_id),
            venue_name=venue_map.get(int(event.venue_id)),
            transaction_id=int(meta.get("transaction_id")) if str(meta.get("transaction_id") or "").isdigit() else None,
            event_id=int(event.id),
            created_at=_ensure_aware(event.created_at),
            details=str(meta.get("details") or event.event_type),
            raw=meta,
        ))

    if search:
        needle = str(search).strip().lower()
        if needle:
            issues = [
                item for item in issues
                if needle in str(item.get("venue_name") or "").lower()
                or needle in str(item.get("details") or "").lower()
                or needle in str(item.get("issue_code") or "").lower()
            ]

    issues.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return issues[:limit]


def get_billing_health_summary(db: Session) -> dict[str, Any]:
    issues = derive_billing_reconciliation_issues(db, limit=500)
    counts = {
        "critical": 0,
        "warning": 0,
        "info": 0,
    }
    code_counts: dict[str, int] = {}
    for item in issues:
        severity = str(item.get("severity") or "info")
        counts[severity] = counts.get(severity, 0) + 1
        code = str(item.get("issue_code") or "UNKNOWN")
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
    stale_pending = sum(1 for item in issues if item.get("issue_code") == "STALE_PENDING_CHECKOUT")
    return {
        "totals": {
            "issues_total": len(issues),
            "critical": counts.get("critical", 0),
            "warning": counts.get("warning", 0),
            "info": counts.get("info", 0),
            "failed_payments_24h": len(recent_failed),
            "stale_pending": stale_pending,
        },
        "by_issue_code": code_counts,
        "recent_issues": issues[:10],
    }

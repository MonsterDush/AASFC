from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Iterable, Mapping, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.base.dto import CanonicalDTO
from app.models.integration_common import utc_now
from app.models.integration_quarantine import IntegrationQuarantine


class CapabilityStateLike(Protocol):
    capability: str
    state: str
    last_success_at: datetime | None


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    code: str
    severity: str
    summary: str
    entity_type: str
    external_id: str


@dataclass(frozen=True, slots=True)
class CapabilityFreshness:
    capability: str
    state: str
    freshness: str
    age_seconds: int | None


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _issue(dto: CanonicalDTO, code: str, severity: str, summary: str) -> DataQualityIssue:
    return DataQualityIssue(
        code=code,
        severity=severity,
        summary=summary,
        entity_type=dto.entity_type,
        external_id=dto.external_id,
    )


def validate_canonical_dto(dto: CanonicalDTO) -> tuple[DataQualityIssue, ...]:
    """Apply provider-neutral business validation before a canonical write."""

    entity_type = dto.entity_type.upper()
    attrs: Mapping[str, Any] = dto.attributes
    issues: list[DataQualityIssue] = []

    if entity_type in {"ORDER", "BUSINESS_SHIFT"}:
        revenue = _decimal(attrs.get("net_amount", attrs.get("revenue_amount")))
        if revenue is not None and revenue < 0:
            issues.append(_issue(dto, "NEGATIVE_REVENUE", "ERROR", "Revenue cannot be negative"))

    if entity_type == "ORDER":
        status = str(attrs.get("status") or "").upper()
        payment = _decimal(attrs.get("payment_amount"))
        if status == "CLOSED" and (payment is None or payment <= 0):
            issues.append(_issue(dto, "CLOSED_ORDER_WITHOUT_PAYMENT", "ERROR", "Closed order has no positive payment"))
        if attrs.get("employee_external_id") and attrs.get("employee_id") is None:
            issues.append(_issue(dto, "UNKNOWN_EMPLOYEE", "WARNING", "Order employee is not mapped"))
        item_count = attrs.get("items_count")
        if item_count is not None and int(item_count) <= 0:
            issues.append(_issue(dto, "ORDER_WITHOUT_ITEMS", "ERROR", "Order has no item rows"))

    if entity_type in {"ORDER_ITEM", "PURCHASE_ITEM", "WRITEOFF_ITEM", "INVENTORY_ITEM"}:
        if attrs.get("product_external_id") and attrs.get("product_id") is None:
            code = "INVENTORY_UNKNOWN_PRODUCT" if entity_type == "INVENTORY_ITEM" else "UNKNOWN_PRODUCT"
            issues.append(_issue(dto, code, "ERROR", "Source product is not mapped"))

    if entity_type == "PURCHASE":
        if attrs.get("supplier_external_id") and attrs.get("supplier_id") is None:
            issues.append(_issue(dto, "PURCHASE_WITHOUT_SUPPLIER", "ERROR", "Purchase supplier is not mapped"))

    return tuple(issues)


def validate_and_quarantine(
    db: Session,
    *,
    connection_id: int,
    dto: CanonicalDTO,
    raw_object_id: int | None = None,
    sync_run_id: int | None = None,
    affected_report_keys: Iterable[str] = (),
) -> tuple[IntegrationQuarantine, ...]:
    rows: list[IntegrationQuarantine] = []
    now = utc_now()
    for issue in validate_canonical_dto(dto):
        identity = json.dumps(
            {
                "connection_id": int(connection_id),
                "entity_type": issue.entity_type,
                "external_id": issue.external_id,
                "code": issue.code,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        issue_key = hashlib.sha256(identity).hexdigest()
        row = db.execute(
            select(IntegrationQuarantine).where(
                IntegrationQuarantine.connection_id == int(connection_id),
                IntegrationQuarantine.issue_key == issue_key,
            )
        ).scalar_one_or_none()
        if row is None:
            row = IntegrationQuarantine(
                connection_id=int(connection_id),
                issue_key=issue_key,
                entity_type=issue.entity_type,
                external_id=issue.external_id,
                error_class="VALIDATION",
                error_code=issue.code,
                severity=issue.severity,
                status="OPEN",
                user_summary=issue.summary,
                opened_at=now,
            )
            db.add(row)
        row.raw_object_id = raw_object_id
        row.sync_run_id = sync_run_id
        row.status = "OPEN"
        row.resolved_at = None
        row.updated_at = now
        row.affected_report_keys_json = sorted({str(value) for value in affected_report_keys if str(value)})
        rows.append(row)
    return tuple(rows)


def assess_capability_freshness(
    states: Iterable[CapabilityStateLike],
    *,
    stale_after_seconds: int,
    now: datetime | None = None,
) -> tuple[CapabilityFreshness, ...]:
    if stale_after_seconds <= 0:
        raise ValueError("stale_after_seconds must be positive")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    output: list[CapabilityFreshness] = []
    for row in states:
        source_state = str(row.state or "UNKNOWN").upper()
        last_success_at = row.last_success_at
        if source_state == "UNAVAILABLE":
            freshness = "NOT_APPLICABLE"
            age_seconds = None
        elif last_success_at is None:
            freshness = "NO_DATA"
            age_seconds = None
        else:
            observed_at = last_success_at
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=timezone.utc)
            age_seconds = max(0, int((current - observed_at).total_seconds()))
            freshness = "STALE" if age_seconds > stale_after_seconds else "FRESH"
        output.append(
            CapabilityFreshness(
                capability=str(row.capability),
                state=source_state,
                freshness=freshness,
                age_seconds=age_seconds,
            )
        )
    return tuple(sorted(output, key=lambda item: item.capability))

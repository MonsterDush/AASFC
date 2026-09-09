from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.canonical import (
    CanonicalAttendance,
    CanonicalInventory,
    CanonicalOrder,
    CanonicalPurchase,
    CanonicalRecipe,
    CanonicalStockMovement,
    CanonicalStockSnapshot,
    CanonicalWriteoff,
)
from app.integrations.normalization.contracts import NormalizationContext
from app.models.integration_quarantine import IntegrationQuarantine
from app.models.pos_canonical import POSEmployee, POSProduct
from app.models.pos_inventory import POSSupplier, POSWarehouse


@dataclass(frozen=True)
class DataQualityIssue:
    code: str
    message: str
    severity: str = "ERROR"

    @property
    def blocking(self) -> bool:
        return self.severity == "ERROR"


def validate_canonical_batch(
    db: Session,
    values: Iterable[object],
    *,
    context: NormalizationContext,
) -> tuple[DataQualityIssue, ...]:
    rows = tuple(values)
    issues: list[DataQualityIssue] = []
    identities = [(type(row), str(getattr(row, "external_id", ""))) for row in rows]
    if len(identities) != len(set(identities)):
        issues.append(DataQualityIssue("duplicate_external_id", "Normalizer returned duplicate external IDs"))
    for row in rows:
        if isinstance(row, CanonicalOrder):
            issues.extend(_validate_order(db, row, context=context))
        elif isinstance(row, CanonicalPurchase):
            if not row.supplier_external_id:
                issues.append(DataQualityIssue("purchase_without_supplier", "Purchase has no supplier"))
            elif not _exists(db, POSSupplier, context, row.supplier_external_id):
                issues.append(DataQualityIssue("unknown_supplier", "Purchase references an unknown supplier", "WARNING"))
            issues.extend(_unknown_products(db, context, (item.product_external_id for item in row.items)))
            issues.extend(_unknown_warehouses(db, context, (row.warehouse_external_id,)))
        elif isinstance(row, CanonicalInventory):
            if any(not item.product_external_id for item in row.items):
                issues.append(DataQualityIssue("inventory_unknown_product", "Inventory row has no product identity"))
            issues.extend(_unknown_products(db, context, (item.product_external_id for item in row.items)))
            issues.extend(_unknown_warehouses(db, context, (row.warehouse_external_id,)))
        elif isinstance(row, CanonicalRecipe):
            issues.extend(
                _unknown_products(
                    db,
                    context,
                    (row.product_external_id, *(item.ingredient_external_id for item in row.items)),
                )
            )
        elif isinstance(row, (CanonicalStockSnapshot, CanonicalStockMovement)):
            issues.extend(_unknown_products(db, context, (row.product_external_id,)))
            issues.extend(_unknown_warehouses(db, context, (row.warehouse_external_id,)))
        elif isinstance(row, CanonicalWriteoff):
            issues.extend(_unknown_warehouses(db, context, (row.warehouse_external_id,)))
            issues.extend(_unknown_products(db, context, (item.product_external_id for item in row.items)))
        elif isinstance(row, CanonicalAttendance):
            if row.employee_external_id and not _exists(db, POSEmployee, context, row.employee_external_id):
                issues.append(DataQualityIssue("unknown_employee", "Attendance references an unknown employee", "WARNING"))
    return tuple(_deduplicate(issues))


def record_quarantine_issues(
    db: Session,
    *,
    connection_id: int,
    capability: str,
    entity_type: str,
    external_id: str,
    payload: Mapping | list,
    issues: Iterable[DataQualityIssue],
) -> int:
    now = datetime.now(timezone.utc)
    count = 0
    active_codes: set[str] = set()
    for issue in issues:
        active_codes.add(issue.code)
        row = db.execute(
            select(IntegrationQuarantine).where(
                IntegrationQuarantine.integration_connection_id == int(connection_id),
                IntegrationQuarantine.entity_type == str(entity_type),
                IntegrationQuarantine.external_id == str(external_id),
                IntegrationQuarantine.error_code == issue.code,
            )
        ).scalar_one_or_none()
        if row is None:
            row = IntegrationQuarantine(
                integration_connection_id=int(connection_id),
                capability=str(capability),
                entity_type=str(entity_type),
                external_id=str(external_id),
                payload_json=dict(payload) if isinstance(payload, Mapping) else list(payload),
                error_code=issue.code,
                error_message=issue.message[:2000],
                severity=issue.severity,
            )
            db.add(row)
        else:
            row.capability = str(capability)
            row.payload_json = dict(payload) if isinstance(payload, Mapping) else list(payload)
            row.error_message = issue.message[:2000]
            row.severity = issue.severity
            row.status = "OPEN"
            row.attempts = int(row.attempts or 0) + 1
            row.last_seen_at = now
            row.resolved_at = None
        count += 1
    _resolve_absent_issues(
        db,
        connection_id=connection_id,
        entity_type=entity_type,
        external_id=external_id,
        active_codes=active_codes,
        now=now,
    )
    return count


def _validate_order(db: Session, row: CanonicalOrder, *, context: NormalizationContext) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []
    if row.total_amount < 0 or row.refund_amount < 0:
        issues.append(DataQualityIssue("negative_revenue", "Order revenue or refund is negative"))
    if row.status in {"CLOSED", "PARTIALLY_REFUNDED"} and row.total_amount > 0 and not row.payments:
        issues.append(DataQualityIssue("closed_order_without_payment", "Closed order has no payment"))
    if row.total_amount > 0 and not row.items:
        issues.append(DataQualityIssue("order_without_items", "Non-zero order has no items"))
    for external_id in (row.cashier_external_id, row.waiter_external_id):
        if external_id and not _exists(db, POSEmployee, context, external_id):
            issues.append(DataQualityIssue("unknown_employee", "Order references an unknown employee", "WARNING"))
    issues.extend(_unknown_products(db, context, (item.product_external_id for item in row.items)))
    return issues


def _unknown_products(db: Session, context: NormalizationContext, external_ids: Iterable[str | None]):
    if any(external_id and not _exists(db, POSProduct, context, external_id) for external_id in external_ids):
        return [DataQualityIssue("unknown_product", "Object references an unknown product", "WARNING")]
    return []


def _unknown_warehouses(db: Session, context: NormalizationContext, external_ids: Iterable[str | None]):
    if any(external_id and not _exists(db, POSWarehouse, context, external_id) for external_id in external_ids):
        return [DataQualityIssue("unknown_warehouse", "Object references an unknown warehouse", "WARNING")]
    return []


def _exists(db: Session, model, context: NormalizationContext, external_id: str) -> bool:
    return db.execute(
        select(model.id).where(
            model.connection_id == int(context.integration_connection_id),
            model.external_id == str(external_id),
        )
    ).first() is not None


def _resolve_absent_issues(
    db: Session,
    *,
    connection_id: int,
    entity_type: str,
    external_id: str,
    active_codes: set[str],
    now: datetime,
) -> None:
    rows = db.execute(
        select(IntegrationQuarantine).where(
            IntegrationQuarantine.integration_connection_id == int(connection_id),
            IntegrationQuarantine.entity_type == str(entity_type),
            IntegrationQuarantine.external_id == str(external_id),
            IntegrationQuarantine.status.in_(("OPEN", "RETRYING")),
        )
    ).scalars()
    for row in rows:
        if row.error_code not in active_codes:
            row.status = "RESOLVED"
            row.resolved_at = now


def _deduplicate(issues: Iterable[DataQualityIssue]) -> list[DataQualityIssue]:
    output: list[DataQualityIssue] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        identity = (issue.code, issue.severity)
        if identity not in seen:
            output.append(issue)
            seen.add(identity)
    return output

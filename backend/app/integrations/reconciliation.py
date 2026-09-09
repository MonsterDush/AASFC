from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection
from app.models.integration_raw_object import IntegrationRawObject
from app.models.integration_reconciliation_run import IntegrationReconciliationRun
from app.models.pos_canonical import (
    POSEmployee,
    POSEmployeeMapping,
    POSOrder,
    POSOrderItem,
    POSPayment,
    POSRefund,
)


class CanonicalReadSwitchError(ValueError):
    pass


@dataclass(frozen=True)
class SourceReconciliationMetrics:
    revenue: Decimal
    refunds: Decimal
    counts: dict[str, int] = field(default_factory=dict)
    coverage_start: date | None = None
    coverage_end: date | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "revenue", Decimal(str(self.revenue or 0)))
        object.__setattr__(self, "refunds", Decimal(str(self.refunds or 0)))
        object.__setattr__(self, "counts", {str(key): int(value) for key, value in self.counts.items()})


def canonical_metrics(
    db: Session,
    *,
    connection_id: int,
    period_start: date,
    period_end: date,
) -> SourceReconciliationMetrics:
    order_scope = (
        POSOrder.connection_id == int(connection_id),
        POSOrder.business_date >= period_start,
        POSOrder.business_date <= period_end,
    )
    revenue, refunds, orders, first_date, last_date = db.execute(
        select(
            func.coalesce(func.sum(POSOrder.total_amount), 0),
            func.coalesce(func.sum(POSOrder.refund_amount), 0),
            func.count(POSOrder.id),
            func.min(POSOrder.business_date),
            func.max(POSOrder.business_date),
        ).where(*order_scope)
    ).one()
    counts = {
        "orders": int(orders or 0),
        "items": _child_count(db, POSOrderItem, connection_id, period_start, period_end),
        "payments": _child_count(db, POSPayment, connection_id, period_start, period_end),
        "refunds": _child_count(db, POSRefund, connection_id, period_start, period_end),
        "employees": int(
            db.scalar(select(func.count(POSEmployee.id)).where(POSEmployee.connection_id == int(connection_id))) or 0
        ),
        "employee_mappings": int(
            db.scalar(
                select(func.count(POSEmployeeMapping.id))
                .join(POSEmployee, POSEmployee.id == POSEmployeeMapping.pos_employee_id)
                .where(POSEmployee.connection_id == int(connection_id))
            )
            or 0
        ),
        "confirmed_employee_mappings": int(
            db.scalar(
                select(func.count(POSEmployeeMapping.id))
                .join(POSEmployee, POSEmployee.id == POSEmployeeMapping.pos_employee_id)
                .where(
                    POSEmployee.connection_id == int(connection_id),
                    POSEmployeeMapping.confirmed.is_(True),
                )
            )
            or 0
        ),
    }
    return SourceReconciliationMetrics(
        revenue=Decimal(str(revenue or 0)),
        refunds=Decimal(str(refunds or 0)),
        counts=counts,
        coverage_start=first_date,
        coverage_end=last_date,
    )


def reconcile_connection(
    db: Session,
    *,
    connection: IntegrationConnection,
    period_start: date,
    period_end: date,
    source: SourceReconciliationMetrics,
    note: str | None = None,
) -> IntegrationReconciliationRun:
    if period_start > period_end:
        raise ValueError("Reconciliation period start must not exceed period end")
    canonical = canonical_metrics(
        db,
        connection_id=int(connection.id),
        period_start=period_start,
        period_end=period_end,
    )
    revenue_difference = canonical.revenue - source.revenue
    refund_difference = canonical.refunds - source.refunds
    count_differences = {
        key: canonical.counts.get(key, 0) - source.counts.get(key, 0)
        for key in sorted(source.counts)
        if canonical.counts.get(key, 0) != source.counts.get(key, 0)
    }
    coverage_difference = {
        "source_start": source.coverage_start.isoformat() if source.coverage_start else None,
        "source_end": source.coverage_end.isoformat() if source.coverage_end else None,
        "canonical_start": canonical.coverage_start.isoformat() if canonical.coverage_start else None,
        "canonical_end": canonical.coverage_end.isoformat() if canonical.coverage_end else None,
    }
    coverage_matches = (
        source.coverage_start == canonical.coverage_start and source.coverage_end == canonical.coverage_end
    )
    money_matches = revenue_difference == 0 and refund_difference == 0
    if money_matches and not count_differences and coverage_matches:
        status = "OK"
    elif money_matches:
        status = "WARNING"
    else:
        status = "FAILED"
    run = IntegrationReconciliationRun(
        integration_connection_id=int(connection.id),
        period_start=period_start,
        period_end=period_end,
        status=status,
        source_revenue=source.revenue,
        canonical_revenue=canonical.revenue,
        revenue_difference=revenue_difference,
        source_refunds=source.refunds,
        canonical_refunds=canonical.refunds,
        refund_difference=refund_difference,
        source_counts_json=source.counts,
        canonical_counts_json=canonical.counts,
        discrepancies_json={
            "counts": count_differences,
            "coverage": {} if coverage_matches else coverage_difference,
        },
        note=(str(note).strip()[:2000] if note else None),
        completed_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()
    return run


def raw_layer_metrics(
    db: Session,
    *,
    connection: IntegrationConnection,
    normalizer,
    period_start: date,
    period_end: date,
) -> SourceReconciliationMetrics:
    from app.integrations.base import ProviderRecord
    from app.integrations.canonical import CanonicalOrder
    from app.integrations.sync.p0 import synchronization_context

    context = synchronization_context(db, connection, normalizer)
    revenue = Decimal("0")
    refunds = Decimal("0")
    counts = {"orders": 0, "items": 0, "payments": 0, "refunds": 0}
    first_date = last_date = None
    raw_orders = db.execute(
        select(IntegrationRawObject).where(
            IntegrationRawObject.integration_connection_id == int(connection.id),
            IntegrationRawObject.entity_type == "ORDER",
        )
    ).scalars()
    for raw in raw_orders:
        normalized = tuple(
            normalizer.normalize_orders(
                ProviderRecord(
                    external_id=raw.external_id,
                    payload=raw.payload_json,
                    source_updated_at=raw.source_updated_at,
                ),
                context=context,
            )
        )
        for order in normalized:
            if not isinstance(order, CanonicalOrder):
                continue
            if not period_start <= order.business_date <= period_end:
                continue
            revenue += order.total_amount
            refunds += order.refund_amount
            counts["orders"] += 1
            counts["items"] += len(order.items)
            counts["payments"] += len(order.payments)
            counts["refunds"] += len(order.refunds)
            first_date = order.business_date if first_date is None else min(first_date, order.business_date)
            last_date = order.business_date if last_date is None else max(last_date, order.business_date)
    return SourceReconciliationMetrics(
        revenue=revenue,
        refunds=refunds,
        counts=counts,
        coverage_start=first_date,
        coverage_end=last_date,
    )


def reconcile_raw_to_canonical(
    db: Session,
    *,
    connection: IntegrationConnection,
    normalizer,
    period_start: date,
    period_end: date,
    note: str = "Automated Raw Layer to ACDM reconciliation",
) -> IntegrationReconciliationRun:
    return reconcile_connection(
        db,
        connection=connection,
        period_start=period_start,
        period_end=period_end,
        source=raw_layer_metrics(
            db,
            connection=connection,
            normalizer=normalizer,
            period_start=period_start,
            period_end=period_end,
        ),
        note=note,
    )


def enable_canonical_reads(db: Session, *, connection: IntegrationConnection) -> IntegrationConnection:
    latest = db.execute(
        select(IntegrationReconciliationRun)
        .where(IntegrationReconciliationRun.integration_connection_id == int(connection.id))
        .order_by(IntegrationReconciliationRun.completed_at.desc(), IntegrationReconciliationRun.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    if latest is None or latest.status != "OK":
        raise CanonicalReadSwitchError("Canonical reads require the latest reconciliation status to be OK")
    if connection.historical_sync_status != "COMPLETED" or connection.last_successful_sync_at is None:
        raise CanonicalReadSwitchError("Canonical reads require a completed historical sync and a successful sync")
    if (
        connection.coverage_start is None
        or connection.coverage_end is None
        or connection.coverage_start > latest.period_start
        or connection.coverage_end < latest.period_end
    ):
        raise CanonicalReadSwitchError("Canonical reads require reconciled historical coverage")
    referenced_employees = {
        int(employee_id)
        for cashier_id, waiter_id in db.execute(
            select(POSOrder.cashier_pos_employee_id, POSOrder.waiter_pos_employee_id).where(
                POSOrder.connection_id == int(connection.id)
            )
        )
        for employee_id in (cashier_id, waiter_id)
        if employee_id is not None
    }
    referenced_employees.update(
        int(employee_id)
        for employee_id in db.scalars(
            select(POSRefund.pos_employee_id)
            .join(POSOrder, POSOrder.id == POSRefund.order_id)
            .where(
                POSOrder.connection_id == int(connection.id),
                POSRefund.pos_employee_id.is_not(None),
            )
        )
        if employee_id is not None
    )
    confirmed_employees = set(
        db.scalars(
            select(POSEmployeeMapping.pos_employee_id).where(
                POSEmployeeMapping.pos_employee_id.in_(sorted(referenced_employees)),
                POSEmployeeMapping.confirmed.is_(True),
            )
        )
    ) if referenced_employees else set()
    unresolved = referenced_employees - {int(value) for value in confirmed_employees}
    if unresolved:
        raise CanonicalReadSwitchError(
            f"Canonical reads require confirmed mappings for {len(unresolved)} referenced POS employees"
        )
    connection.read_mode = "CANONICAL"
    connection.canonical_read_enabled_at = datetime.now(timezone.utc)
    db.flush()
    return connection


def rollback_to_legacy_reads(connection: IntegrationConnection) -> IntegrationConnection:
    connection.read_mode = "LEGACY"
    connection.canonical_read_enabled_at = None
    return connection


def _child_count(db: Session, model, connection_id: int, period_start: date, period_end: date) -> int:
    return int(
        db.scalar(
            select(func.count(model.id))
            .join(POSOrder, POSOrder.id == model.order_id)
            .where(
                POSOrder.connection_id == int(connection_id),
                POSOrder.business_date >= period_start,
                POSOrder.business_date <= period_end,
            )
        )
        or 0
    )

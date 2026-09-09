from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection
from app.models.pos_canonical import POSOrder, POSOrderItem


def canonical_sales_metrics(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
) -> dict:
    if period_start > period_end:
        raise ValueError("Canonical sales period start must not exceed period end")
    connection_ids = select(IntegrationConnection.id).where(
        IntegrationConnection.venue_id == int(venue_id),
        IntegrationConnection.read_mode == "CANONICAL",
    )
    scope = (
        POSOrder.connection_id.in_(connection_ids),
        POSOrder.business_date >= period_start,
        POSOrder.business_date <= period_end,
        POSOrder.status.in_(("CLOSED", "REFUNDED", "PARTIALLY_REFUNDED")),
    )
    gross, refunds, orders, guests = db.execute(
        select(
            func.coalesce(func.sum(POSOrder.total_amount), 0),
            func.coalesce(func.sum(POSOrder.refund_amount), 0),
            func.count(POSOrder.id),
            func.coalesce(func.sum(POSOrder.guest_count), 0),
        ).where(*scope)
    ).one()
    cost = db.scalar(
        select(func.coalesce(func.sum(POSOrderItem.cost_amount), 0))
        .join(POSOrder, POSOrder.id == POSOrderItem.order_id)
        .where(
            *scope,
            POSOrderItem.is_deleted.is_(False),
            POSOrderItem.is_refunded.is_(False),
        )
    )
    gross_value = Decimal(str(gross or 0))
    refund_value = Decimal(str(refunds or 0))
    net_value = gross_value - refund_value
    cost_value = Decimal(str(cost or 0))
    guest_count = int(guests or 0)
    return {
        "period_start": period_start,
        "period_end": period_end,
        "gross_revenue": gross_value,
        "refunds": refund_value,
        "net_revenue": net_value,
        "orders": int(orders or 0),
        "guests": guest_count,
        "cost": cost_value,
        "food_cost_percent": (
            (cost_value * Decimal("100") / net_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if net_value > 0
            else None
        ),
        "average_guest_spend": (
            (net_value / Decimal(guest_count)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if guest_count > 0
            else None
        ),
    }

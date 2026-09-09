from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.base import POSCapability
from app.models.integration_capability_state import IntegrationCapabilityState


_FRESHNESS_MINUTES = {
    POSCapability.SALES: 15,
    POSCapability.ORDER_ITEMS: 15,
    POSCapability.ORDER_EVENTS: 15,
    POSCapability.PAYMENTS: 15,
    POSCapability.DISCOUNTS: 15,
    POSCapability.REFUNDS: 15,
    POSCapability.GUEST_COUNT: 15,
    POSCapability.STOCK_BALANCES: 90,
    POSCapability.STOCK_MOVEMENTS: 90,
    POSCapability.PURCHASES: 90,
    POSCapability.WRITEOFFS: 90,
    POSCapability.INVENTORY: 90,
    POSCapability.EMPLOYEE_ATTENDANCE: 180,
    POSCapability.EMPLOYEES: 720,
    POSCapability.PRODUCTS: 720,
    POSCapability.PRODUCT_GROUPS: 720,
    POSCapability.MODIFIERS: 720,
    POSCapability.RECIPES: 720,
    POSCapability.ORGANIZATIONS: 1440,
    POSCapability.VENUES: 1440,
    POSCapability.TERMINALS: 1440,
    POSCapability.WAREHOUSES: 1440,
    POSCapability.SUPPLIERS: 1440,
}


def capability_freshness(
    db: Session,
    *,
    connection_id: int,
    now: datetime | None = None,
) -> dict[str, dict]:
    observed_at = now or datetime.now(timezone.utc)
    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("Freshness reference time must be timezone-aware")
    states = {
        row.capability: row
        for row in db.execute(
            select(IntegrationCapabilityState).where(
                IntegrationCapabilityState.integration_connection_id == int(connection_id)
            )
        ).scalars()
    }
    output: dict[str, dict] = {}
    for capability in POSCapability:
        row = states.get(capability.value)
        threshold_minutes = _FRESHNESS_MINUTES[capability]
        data_at = _parse_data_at((row.details_json or {}).get("last_data_at")) if row is not None else None
        if row is not None and row.status == "UNAVAILABLE":
            status = "UNAVAILABLE"
        elif data_at is None:
            status = "UNKNOWN"
        elif data_at < observed_at - timedelta(minutes=threshold_minutes):
            status = "STALE"
        else:
            status = "FRESH"
        output[capability.value] = {
            "status": status,
            "data_updated_at": data_at.isoformat() if data_at else None,
            "stale_after_minutes": threshold_minutes,
            "capability_status": row.status if row is not None else "UNKNOWN",
        }
    return output


def _parse_data_at(value) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

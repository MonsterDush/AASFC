from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import POSOperationalSnapshot
from app.services.integrations.credentials import encrypt_operational_payload


def store_operational_snapshot(
    db: Session,
    *,
    connection_id: int,
    venue_id: int,
    object_type: str,
    external_id: str,
    payload: Mapping[str, Any],
    observed_at: datetime,
    source_status: str | None = None,
    current_amount: Decimal | None = None,
    fresh_until: datetime | None = None,
    business_shift_id: int | None = None,
    open_orders_count: int | None = None,
    open_tables_count: int | None = None,
    open_orders_amount: Decimal | None = None,
    closed_orders_count: int | None = None,
    closed_revenue_amount: Decimal | None = None,
) -> tuple[POSOperationalSnapshot, bool]:
    """Store a state change only; this projection must not feed closed revenue."""

    state = {
        "payload": dict(payload),
        "projection": {
            "source_status": source_status,
            "current_amount": current_amount,
            "business_shift_id": business_shift_id,
            "open_orders_count": open_orders_count,
            "open_tables_count": open_tables_count,
            "open_orders_amount": open_orders_amount,
            "closed_orders_count": closed_orders_count,
            "closed_revenue_amount": closed_revenue_amount,
        },
    }
    serialized = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    previous = db.scalar(
        select(POSOperationalSnapshot)
        .where(
            POSOperationalSnapshot.connection_id == connection_id,
            POSOperationalSnapshot.object_type == object_type,
            POSOperationalSnapshot.external_id == external_id,
        )
        .order_by(POSOperationalSnapshot.observed_at.desc(), POSOperationalSnapshot.id.desc())
        .limit(1)
    )
    if previous is not None and previous.payload_hash == payload_hash:
        previous.last_seen_at = observed_at
        previous.fresh_until = fresh_until
        return previous, False

    if previous is not None and previous.superseded_at is None:
        previous.superseded_at = observed_at
    snapshot = POSOperationalSnapshot(
        connection_id=connection_id,
        venue_id=venue_id,
        object_type=object_type.strip().upper(),
        external_id=external_id,
        source_status=source_status,
        payload_hash=payload_hash,
        payload_encrypted=encrypt_operational_payload(serialized),
        current_amount=current_amount,
        observed_at=observed_at,
        fresh_until=fresh_until,
        business_shift_id=business_shift_id,
        open_orders_count=open_orders_count,
        open_tables_count=open_tables_count,
        open_orders_amount=open_orders_amount,
        closed_orders_count=closed_orders_count,
        closed_revenue_amount=closed_revenue_amount,
        last_seen_at=observed_at,
    )
    db.add(snapshot)
    db.flush()
    return snapshot, True

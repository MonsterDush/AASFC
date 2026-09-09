from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Iterable, Mapping

from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from app.integrations.base import POSProviderCode, ProviderRecord
from app.integrations.canonical import (
    CanonicalEmployee,
    CanonicalOrder,
    CanonicalProduct,
    CanonicalProductGroup,
    persist_canonical_batch,
)
from app.integrations.employee_mapping import suggest_employee_mappings
from app.integrations.normalization import NormalizationContext, QuickRestoP0Normalizer
from app.integrations.normalization.common import identifier, label
from app.integrations.raw import mark_raw_object_normalized, store_raw_object
from app.integrations.reconciliation import SourceReconciliationMetrics, reconcile_connection
from app.models.integration_connection import IntegrationConnection
from app.models.venue import Venue
from app.services.integrations.quickresto_normalize import business_date_for_shift


def shadow_write_quickresto_batch(
    db: Session,
    *,
    legacy_connection,
    shifts: Iterable[Mapping[str, Any]],
    orders_by_shift: Mapping[str, Iterable[Mapping[str, Any]]],
    full_reconciliation: bool,
) -> dict[str, Any]:
    bind = db.get_bind()
    inspector = inspect(bind)
    required = {"integration_connections", "integration_raw_objects", "pos_orders"}
    if any(not inspector.has_table(table) for table in required):
        return {"status": "DISABLED", "reason": "canonical_schema_unavailable"}
    connections = list(
        db.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.venue_id == int(legacy_connection.venue_id),
                IntegrationConnection.provider == POSProviderCode.QUICK_RESTO.value,
                IntegrationConnection.shadow_sync_enabled.is_(True),
            )
        ).scalars()
    )
    if legacy_connection.external_venue_id is not None:
        exact = [
            item for item in connections if str(item.external_venue_id or "") == str(legacy_connection.external_venue_id)
        ]
        if exact:
            connections = exact
    if len(connections) != 1:
        return {
            "status": "DISABLED",
            "reason": "canonical_connection_not_linked" if not connections else "canonical_connection_ambiguous",
        }
    connection = connections[0]
    venue = db.get(Venue, int(connection.venue_id))
    if venue is None:
        return {"status": "FAILED", "error": "VenueMissing"}
    normalizer = QuickRestoP0Normalizer()
    context = NormalizationContext(
        integration_connection_id=int(connection.id),
        venue_id=int(connection.venue_id),
        provider=POSProviderCode.QUICK_RESTO,
        normalization_version=normalizer.VERSION,
        timezone=str(venue.timezone or "Europe/Moscow"),
        business_day_cutoff_hour=int(legacy_connection.business_day_cutoff_hour or 0),
    )
    records_seen = canonical_rows = 0
    source_orders = source_items = source_payments = source_refunds = 0
    source_revenue = source_refund_amount = Decimal("0")
    business_dates: list[date] = []
    try:
        for shift in shifts:
            shift_id = str(shift.get("frontId") or shift.get("_id") or "").strip()
            if not shift_id:
                continue
            target_date = business_date_for_shift(shift, cutoff_hour=context.business_day_cutoff_hour)
            business_dates.append(target_date)
            for raw_order in orders_by_shift.get(shift_id, ()):
                if not isinstance(raw_order, Mapping):
                    continue
                payload = dict(raw_order)
                payload["_axelio_business_date"] = target_date.isoformat()
                payload.setdefault("localOpenedTime", shift.get("localOpenedTime") or shift.get("opened"))
                payload.setdefault("localClosedTime", shift.get("localClosedTime") or shift.get("closed"))
                external_id = str(payload.get("frontId") or payload.get("_id") or payload.get("id") or "").strip()
                if not external_id:
                    raise ValueError("QuickResto shadow order has no stable identifier")
                _persist_inline_references(db, payload=payload, context=context)
                record = ProviderRecord(
                    external_id=external_id,
                    payload=payload,
                    source_updated_at=_source_updated_at(payload),
                )
                raw, _changed = store_raw_object(
                    db,
                    integration_connection_id=int(connection.id),
                    entity_type="ORDER",
                    external_id=external_id,
                    payload=payload,
                    source_updated_at=record.source_updated_at,
                )
                normalized = tuple(normalizer.normalize_orders(record, context=context))
                canonical_rows += persist_canonical_batch(db, normalized, context=context)
                mark_raw_object_normalized(raw, normalization_version=context.normalization_version)
                records_seen += 1
                normalized_orders = tuple(item for item in normalized if isinstance(item, CanonicalOrder))
                source_orders += len(normalized_orders)
                source_items += sum(len(item.items) for item in normalized_orders)
                source_payments += sum(len(item.payments) for item in normalized_orders)
                source_refunds += sum(len(item.refunds) for item in normalized_orders)
                source_revenue += sum((item.total_amount for item in normalized_orders), Decimal("0"))
                source_refund_amount += sum((item.refund_amount for item in normalized_orders), Decimal("0"))
        suggest_employee_mappings(
            db,
            connection_id=int(connection.id),
            venue_id=int(connection.venue_id),
        )
        completed_at = datetime.now(timezone.utc)
        connection.last_sync_at = completed_at
        connection.last_successful_sync_at = completed_at
        connection.status = "ACTIVE"
        if business_dates:
            batch_start, batch_end = min(business_dates), max(business_dates)
            connection.coverage_start = min(filter(None, (connection.coverage_start, batch_start)))
            connection.coverage_end = max(filter(None, (connection.coverage_end, batch_end)))
            if full_reconciliation:
                connection.historical_sync_status = "COMPLETED"
                reconcile_connection(
                    db,
                    connection=connection,
                    period_start=batch_start,
                    period_end=batch_end,
                    source=SourceReconciliationMetrics(
                        revenue=source_revenue,
                        refunds=source_refund_amount,
                        counts={
                            "orders": source_orders,
                            "items": source_items,
                            "payments": source_payments,
                            "refunds": source_refunds,
                        },
                        coverage_start=batch_start,
                        coverage_end=batch_end,
                    ),
                    note="Automatic comparison with the completed legacy QuickResto batch",
                )
        db.commit()
        return {
            "status": "SUCCEEDED",
            "records_seen": records_seen,
            "canonical_rows": canonical_rows,
            "full_reconciliation": bool(full_reconciliation),
        }
    except Exception as exc:
        db.rollback()
        try:
            refreshed = db.get(IntegrationConnection, int(connection.id))
            if refreshed is not None:
                refreshed.status = "DEGRADED"
                db.commit()
        except Exception:
            db.rollback()
        return {"status": "FAILED", "error": type(exc).__name__, "records_seen": records_seen}


def _persist_inline_references(db: Session, *, payload: Mapping[str, Any], context: NormalizationContext) -> None:
    references = []
    for value in (payload.get("cashier"), payload.get("waiter"), payload.get("employee")):
        external_id = identifier(value)
        if external_id:
            references.append(
                CanonicalEmployee(
                    external_id=external_id,
                    name=label(value, default=f"Сотрудник {external_id}") or external_id,
                )
            )
    groups = {}
    products = {}
    for raw in payload.get("orderItemList") or payload.get("items") or ():
        if not isinstance(raw, Mapping):
            continue
        product = raw.get("product") if isinstance(raw.get("product"), Mapping) else {}
        product_id = identifier(product or raw.get("productId"))
        group_id = identifier(product.get("parent") or product.get("parentId")) if product else None
        if group_id:
            groups[group_id] = CanonicalProductGroup(
                external_id=group_id,
                name=label(product.get("parent"), default=f"Группа {group_id}") or f"Группа {group_id}",
                kind="CATEGORY",
            )
        if product_id:
            products[product_id] = CanonicalProduct(
                external_id=product_id,
                name=label(product, default=f"Позиция {product_id}") or product_id,
                type="DISH",
                category_external_id=group_id,
            )
    persist_canonical_batch(db, (*references, *groups.values(), *products.values()), context=context)


def _source_updated_at(payload: Mapping[str, Any]) -> datetime | None:
    for key in ("updated", "updatedAt", "localClosedTime", "closed"):
        raw = str(payload.get(key) or "").strip()
        if not raw:
            continue
        try:
            value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return None

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.base import POSCapability, POSProvider, normalize_provider_code
from app.integrations.canonical import persist_canonical_batch
from app.integrations.data_quality import DataQualityIssue, record_quarantine_issues, validate_canonical_batch
from app.integrations.employee_mapping import suggest_employee_mappings
from app.integrations.normalization import NormalizationContext, P0Normalizer
from app.integrations.raw import mark_raw_object_normalized, store_raw_object
from app.models.integration_capability_state import IntegrationCapabilityState
from app.models.integration_connection import IntegrationConnection
from app.models.integration_sync_cursor import IntegrationSyncCursor
from app.models.venue import Venue


P0_SYNC_ORDER = (
    POSCapability.VENUES,
    POSCapability.TERMINALS,
    POSCapability.EMPLOYEES,
    POSCapability.PRODUCT_GROUPS,
    POSCapability.PRODUCTS,
    POSCapability.SALES,
)

EXTENDED_SYNC_ORDER = (
    POSCapability.RECIPES,
    POSCapability.WAREHOUSES,
    POSCapability.STOCK_BALANCES,
    POSCapability.STOCK_MOVEMENTS,
    POSCapability.SUPPLIERS,
    POSCapability.PURCHASES,
    POSCapability.WRITEOFFS,
    POSCapability.INVENTORY,
    POSCapability.EMPLOYEE_ATTENDANCE,
)
ALL_SYNC_ORDER = (*P0_SYNC_ORDER, *EXTENDED_SYNC_ORDER)
_INCREMENTAL_CAPABILITIES = {
    POSCapability.SALES,
    POSCapability.STOCK_MOVEMENTS,
    POSCapability.PURCHASES,
    POSCapability.WRITEOFFS,
    POSCapability.INVENTORY,
    POSCapability.EMPLOYEE_ATTENDANCE,
}
_FRESHNESS_FANOUT = {
    POSCapability.SALES: (
        POSCapability.SALES,
        POSCapability.ORDER_ITEMS,
        POSCapability.ORDER_EVENTS,
        POSCapability.PAYMENTS,
        POSCapability.DISCOUNTS,
        POSCapability.REFUNDS,
        POSCapability.GUEST_COUNT,
    ),
    POSCapability.PRODUCTS: (POSCapability.PRODUCTS, POSCapability.MODIFIERS),
}


@dataclass(frozen=True)
class CapabilitySyncResult:
    capability: POSCapability
    pages: int
    records_seen: int
    records_changed: int
    canonical_rows: int
    quarantined_records: int
    watermark_at: datetime | None


_SYNC_HANDLERS: dict[POSCapability, tuple[str, str, str]] = {
    POSCapability.VENUES: ("get_venues", "normalize_venues", "VENUE"),
    POSCapability.TERMINALS: ("get_terminals", "normalize_terminals", "TERMINAL"),
    POSCapability.EMPLOYEES: ("get_employees", "normalize_employees", "EMPLOYEE"),
    POSCapability.PRODUCT_GROUPS: ("get_product_groups", "normalize_product_groups", "PRODUCT_GROUP"),
    POSCapability.PRODUCTS: ("get_products", "normalize_products", "PRODUCT"),
    POSCapability.SALES: ("get_orders", "normalize_orders", "ORDER"),
    POSCapability.RECIPES: ("get_recipes", "normalize_recipes", "RECIPE"),
    POSCapability.WAREHOUSES: ("get_warehouses", "normalize_warehouses", "WAREHOUSE"),
    POSCapability.STOCK_BALANCES: ("get_stock_balances", "normalize_stock_balances", "STOCK_BALANCE"),
    POSCapability.STOCK_MOVEMENTS: ("get_stock_movements", "normalize_stock_movements", "STOCK_MOVEMENT"),
    POSCapability.SUPPLIERS: ("get_suppliers", "normalize_suppliers", "SUPPLIER"),
    POSCapability.PURCHASES: ("get_purchases", "normalize_purchases", "PURCHASE"),
    POSCapability.WRITEOFFS: ("get_writeoffs", "normalize_writeoffs", "WRITEOFF"),
    POSCapability.INVENTORY: ("get_inventories", "normalize_inventories", "INVENTORY"),
    POSCapability.EMPLOYEE_ATTENDANCE: ("get_attendance", "normalize_attendance", "ATTENDANCE"),
}


def synchronization_context(db: Session, connection: IntegrationConnection, normalizer: P0Normalizer) -> NormalizationContext:
    venue = db.get(Venue, int(connection.venue_id))
    if venue is None:
        raise ValueError("Integration venue no longer exists")
    return NormalizationContext(
        integration_connection_id=int(connection.id),
        venue_id=int(connection.venue_id),
        provider=normalize_provider_code(connection.provider),
        normalization_version=str(getattr(normalizer, "VERSION", "p0-v1")),
        timezone=str(venue.timezone or "Europe/Moscow"),
        business_day_cutoff_hour=0,
    )


def persist_capability_audit(db: Session, connection: IntegrationConnection, provider: POSProvider) -> None:
    now = datetime.now(timezone.utc)
    audit = provider.detect_capabilities()
    serialized = {}
    for capability, result in audit.items():
        row = db.execute(
            select(IntegrationCapabilityState).where(
                IntegrationCapabilityState.integration_connection_id == int(connection.id),
                IntegrationCapabilityState.capability == capability.value,
            )
        ).scalar_one_or_none()
        if row is None:
            row = IntegrationCapabilityState(
                integration_connection_id=int(connection.id),
                capability=capability.value,
            )
            db.add(row)
        row.status = result.status.value
        row.last_updated_at = result.checked_at
        row.last_error = None
        row.details_json = dict(result.details)
        serialized[capability.value] = result.as_dict()
    connection.capabilities = serialized
    connection.updated_at = now
    db.flush()


def synchronize_capability(
    db: Session,
    *,
    connection: IntegrationConnection,
    provider: POSProvider,
    normalizer: P0Normalizer,
    capability: POSCapability,
    updated_since: datetime | None = None,
    max_pages: int = 1000,
    commit_each_page: bool = True,
) -> CapabilitySyncResult:
    if capability not in _SYNC_HANDLERS:
        raise ValueError(f"Unsupported P0 sync capability: {capability.value}")
    if not 1 <= int(max_pages) <= 10000:
        raise ValueError("max_pages must be between 1 and 10000")
    provider_method_name, normalizer_method_name, entity_type = _SYNC_HANDLERS[capability]
    provider_method: Callable = getattr(provider, provider_method_name)
    normalizer_method: Callable = getattr(normalizer, normalizer_method_name)
    cursor_row = _cursor_row(db, connection_id=int(connection.id), capability=capability)
    started_at = datetime.now(timezone.utc)
    cursor_row.status = "RUNNING"
    cursor_row.last_started_at = started_at
    cursor_row.last_error = None
    connection.last_sync_at = started_at
    db.flush()
    if commit_each_page:
        db.commit()

    context = synchronization_context(db, connection, normalizer)
    cursor = cursor_row.cursor
    seen_cursors = {cursor} if cursor else set()
    pages = records_seen = records_changed = canonical_rows = quarantined_records = 0
    watermark = _as_utc(cursor_row.watermark_at)
    effective_since = updated_since
    if effective_since is None and watermark is not None and capability in _INCREMENTAL_CAPABILITIES:
        normalized_watermark = watermark if watermark.tzinfo is not None else watermark.replace(tzinfo=timezone.utc)
        effective_since = normalized_watermark - timedelta(hours=int(cursor_row.rolling_window_hours or 72))

    try:
        while pages < int(max_pages):
            kwargs = {"cursor": cursor}
            if capability in _INCREMENTAL_CAPABILITIES:
                kwargs["updated_since"] = effective_since
            page = provider_method(**kwargs)
            pages += 1
            for record in page.records:
                raw, changed = store_raw_object(
                    db,
                    integration_connection_id=int(connection.id),
                    entity_type=entity_type,
                    external_id=record.external_id,
                    payload=dict(record.payload),
                    source_updated_at=record.source_updated_at,
                )
                records_seen += 1
                records_changed += int(changed)
                try:
                    normalized = tuple(normalizer_method(record, context=context))
                    issues = validate_canonical_batch(db, normalized, context=context)
                except Exception as exc:
                    record_quarantine_issues(
                        db,
                        connection_id=int(connection.id),
                        capability=capability.value,
                        entity_type=entity_type,
                        external_id=record.external_id,
                        payload=record.payload,
                        issues=(DataQualityIssue("normalization_error", type(exc).__name__),),
                    )
                    quarantined_records += 1
                    continue
                record_quarantine_issues(
                    db,
                    connection_id=int(connection.id),
                    capability=capability.value,
                    entity_type=entity_type,
                    external_id=record.external_id,
                    payload=record.payload,
                    issues=issues,
                )
                if any(issue.blocking for issue in issues):
                    quarantined_records += 1
                    continue
                try:
                    with db.begin_nested():
                        persisted_rows = persist_canonical_batch(db, normalized, context=context)
                        db.flush()
                except Exception as exc:
                    record_quarantine_issues(
                        db,
                        connection_id=int(connection.id),
                        capability=capability.value,
                        entity_type=entity_type,
                        external_id=record.external_id,
                        payload=record.payload,
                        issues=(DataQualityIssue("persistence_error", type(exc).__name__),),
                    )
                    quarantined_records += 1
                    continue
                canonical_rows += persisted_rows
                mark_raw_object_normalized(raw, normalization_version=context.normalization_version)
                source_updated_at = _as_utc(record.source_updated_at)
                if source_updated_at is not None and (watermark is None or source_updated_at > watermark):
                    watermark = source_updated_at

            cursor_row = _cursor_row(db, connection_id=int(connection.id), capability=capability)
            cursor_row.cursor = page.next_cursor
            cursor_row.watermark_at = watermark
            cursor_row.status = "RUNNING" if page.next_cursor else "PARTIAL" if quarantined_records else "SUCCEEDED"
            if not page.next_cursor:
                completed_at = datetime.now(timezone.utc)
                if not quarantined_records:
                    cursor_row.last_successful_at = completed_at
                    connection.last_successful_sync_at = completed_at
                    _mark_capability_fresh(db, connection_id=int(connection.id), capability=capability, at=completed_at)
                else:
                    connection.status = "DEGRADED"
            db.flush()
            if commit_each_page:
                db.commit()
            if not page.next_cursor:
                break
            if page.next_cursor in seen_cursors:
                raise RuntimeError(f"Provider repeated pagination cursor for {capability.value}")
            seen_cursors.add(page.next_cursor)
            cursor = page.next_cursor
        else:
            raise RuntimeError(f"Provider pagination exceeded max_pages for {capability.value}")
    except Exception as exc:
        db.rollback()
        cursor_row = _cursor_row(db, connection_id=int(connection.id), capability=capability)
        cursor_row.status = "FAILED"
        cursor_row.last_error = type(exc).__name__[:255]
        connection.status = "DEGRADED"
        db.flush()
        if commit_each_page:
            db.commit()
        raise

    return CapabilitySyncResult(
        capability=capability,
        pages=pages,
        records_seen=records_seen,
        records_changed=records_changed,
        canonical_rows=canonical_rows,
        quarantined_records=quarantined_records,
        watermark_at=watermark,
    )


def historical_backfill(
    db: Session,
    *,
    connection: IntegrationConnection,
    provider: POSProvider,
    normalizer: P0Normalizer,
    months: int = 12,
    capabilities: tuple[POSCapability, ...] = P0_SYNC_ORDER,
) -> tuple[CapabilitySyncResult, ...]:
    if not 1 <= int(months) <= 24:
        raise ValueError("Historical backfill must cover between 1 and 24 months")
    end = datetime.now(timezone.utc).date()
    start = _subtract_months(end, int(months))
    connection.historical_sync_status = "RUNNING"
    connection.coverage_start = start
    connection.coverage_end = end
    db.commit()
    source_from = datetime.combine(start, time.min, tzinfo=timezone.utc)
    results = []
    try:
        for capability in capabilities:
            results.append(
                synchronize_capability(
                    db,
                    connection=connection,
                    provider=provider,
                    normalizer=normalizer,
                    capability=capability,
                    updated_since=source_from if capability in _INCREMENTAL_CAPABILITIES else None,
                )
            )
        suggest_employee_mappings(
            db,
            connection_id=int(connection.id),
            venue_id=int(connection.venue_id),
        )
        has_quarantine = any(result.quarantined_records for result in results)
        connection.historical_sync_status = "PARTIAL" if has_quarantine else "COMPLETED"
        connection.status = "DEGRADED" if has_quarantine else "ACTIVE"
        db.commit()
    except Exception:
        db.rollback()
        connection.historical_sync_status = "PARTIAL" if results else "FAILED"
        connection.status = "DEGRADED"
        db.commit()
        raise
    return tuple(results)


def incremental_sync(
    db: Session,
    *,
    connection: IntegrationConnection,
    provider: POSProvider,
    normalizer: P0Normalizer,
    capabilities: tuple[POSCapability, ...] = P0_SYNC_ORDER,
) -> tuple[CapabilitySyncResult, ...]:
    results = tuple(
        synchronize_capability(
            db,
            connection=connection,
            provider=provider,
            normalizer=normalizer,
            capability=capability,
        )
        for capability in capabilities
    )
    suggest_employee_mappings(
        db,
        connection_id=int(connection.id),
        venue_id=int(connection.venue_id),
    )
    connection.status = "DEGRADED" if any(result.quarantined_records for result in results) else "ACTIVE"
    db.commit()
    return results


def _cursor_row(db: Session, *, connection_id: int, capability: POSCapability) -> IntegrationSyncCursor:
    row = db.execute(
        select(IntegrationSyncCursor).where(
            IntegrationSyncCursor.integration_connection_id == int(connection_id),
            IntegrationSyncCursor.capability == capability.value,
        )
    ).scalar_one_or_none()
    if row is None:
        row = IntegrationSyncCursor(
            integration_connection_id=int(connection_id),
            capability=capability.value,
            rolling_window_hours=72 if capability == POSCapability.SALES else 0,
        )
        db.add(row)
        db.flush()
    return row


def _subtract_months(value: date, months: int) -> date:
    zero_based = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(zero_based, 12)
    month = month_index + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mark_capability_fresh(
    db: Session,
    *,
    connection_id: int,
    capability: POSCapability,
    at: datetime,
) -> None:
    for affected in _FRESHNESS_FANOUT.get(capability, (capability,)):
        row = db.execute(
            select(IntegrationCapabilityState).where(
                IntegrationCapabilityState.integration_connection_id == int(connection_id),
                IntegrationCapabilityState.capability == affected.value,
            )
        ).scalar_one_or_none()
        if row is None:
            row = IntegrationCapabilityState(
                integration_connection_id=int(connection_id),
                capability=affected.value,
                status="AVAILABLE",
            )
            db.add(row)
        row.last_updated_at = at
        row.last_error = None
        row.details_json = {**(row.details_json or {}), "last_data_at": at.isoformat()}

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.base.capabilities import Capability, CapabilityState
from app.integrations.base.dto import ProviderRecord
from app.integrations.base.errors import ProviderCapabilityError
from app.integrations.providers.quickresto.canonical_sync import ensure_quickresto_integration_connection
from app.integrations.providers.quickresto.provider import QuickRestoProviderAdapter
from app.integrations.raw.storage import record_raw_object, replay_raw_object
from app.models.integration_connection import IntegrationConnection
from app.models.integration_raw_object import IntegrationRawObject
from app.models.quickresto_connection import QuickRestoConnection
from app.models.pos_canonical import (
    POSBusinessShift,
    POSEmployee,
    POSInventoryDocument,
    POSInventoryItem,
    POSProduct,
    POSPurchaseDocument,
    POSPurchaseItem,
    POSRestaurantSection,
    POSStockMovement,
    POSSupplier,
    POSTable,
    POSWarehouse,
    POSWriteoff,
    POSWriteoffItem,
)
from app.services.integrations.operational import store_operational_snapshot
from app.services.integrations.credentials import decrypt_credential
from app.services.integrations.quickresto import QuickRestoClient, QuickRestoConfig
from app.services.integrations.quickresto_normalize import business_date_for_shift
from app.models.venue import Venue


NORMALIZATION_VERSION = "quickresto-v04-stage3-1"

_RAW_ALLOWLISTS: dict[str, tuple[str, ...]] = {
    "QR_CURRENT_SHIFT": (
        "id",
        "frontId",
        "version",
        "status",
        "opened",
        "localOpenedTime",
        "closed",
        "localClosedTime",
        "shiftNumber",
        "ordersCount",
        "salePlace",
        "tableScheme",
    ),
    "QR_RESTAURANT_SECTION": (
        "id",
        "frontId",
        "version",
        "name",
        "itemTitle",
        "title",
        "blocked",
        "active",
        "deleted",
        "tableSchemeId",
        "tables",
        "webTables",
    ),
    "QR_TABLE": (
        "id",
        "frontId",
        "version",
        "name",
        "itemTitle",
        "title",
        "number",
        "capacity",
        "minCapacity",
        "maxCapacity",
        "places",
        "seats",
        "blocked",
        "active",
        "deleted",
        "tableSchemeId",
        "restaurantSectionId",
        "hall",
        "section",
        "x",
        "y",
        "width",
        "height",
        "shape",
    ),
    "QR_EMPLOYEE": (
        "id",
        "frontId",
        "version",
        "name",
        "firstName",
        "lastName",
        "fullName",
        "shortName",
        "middleName",
        "position",
        "role",
        "blocked",
        "active",
        "systemEmployee",
    ),
    "QR_INVENTORY_DOCUMENT": (
        "id",
        "frontId",
        "version",
        "documentSurface",
        "documentSourceId",
        "invoiceDate",
        "date",
        "documentDate",
        "created",
        "number",
        "documentNumber",
        "invoiceNumber",
        "lastUpdateDate",
        "processed",
        "paid",
        "deleted",
        "cancelled",
        "comment",
        "description",
        "store",
        "fromStore",
        "storeFrom",
        "storeTo",
        "provider",
        "supplier",
        "discardReason",
        "shortfallSum",
        "surplusSum",
        "totalAmount",
        "totalNds",
        "totalSum",
        "totalSumWoNds",
        "costPriceSum",
        "sum",
        "amount",
        "positions",
        "items",
        "documentItems",
        "rows",
        "products",
        "invoiceItems",
        "invoiceComponents",
        "sourceItems",
        "resultComponents",
        "measureUnit",
    ),
}

_DOCUMENT_TYPE = {
    "inventory_documents": "INVENTORY",
    "incoming_invoices": "PURCHASE",
    "outgoing_invoices": "OUTGOING_INVOICE",
    "discard_invoices": "WRITEOFF",
    "exchange_invoices": "TRANSFER",
    "cooking_invoices": "PRODUCTION",
    "decomposition_invoices": "TRANSFORMATION",
    "processing_invoices": "TRANSFORMATION",
}


@dataclass(slots=True)
class QuickRestoExpandedSyncResult:
    counts: dict[str, int] = field(default_factory=dict)
    raw_object_ids: list[int] = field(default_factory=list)

    def add(self, key: str, amount: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + amount


def sync_quickresto_expanded_connection(
    db: Session,
    *,
    connection: QuickRestoConnection,
    period_start: date,
    period_end_exclusive: date,
    client: QuickRestoClient | None = None,
) -> QuickRestoExpandedSyncResult:
    """Run the isolated Stage 3 sync for one configured legacy connection."""

    if not connection.is_active:
        raise ValueError("QuickResto connection is disabled")
    if str(connection.scope_status or "").upper() != "READY":
        raise ValueError("QuickResto scope must be confirmed before expanded sync")
    if connection.external_venue_id is None:
        raise ValueError("QuickResto external venue id is required")
    venue = db.get(Venue, int(connection.venue_id))
    if venue is None:
        raise ValueError("Axelio venue no longer exists")
    canonical_connection = ensure_quickresto_integration_connection(db, connection=connection)
    db.commit()
    managed_client = client is None
    active_client = client or QuickRestoClient(
        QuickRestoConfig(
            cloud=connection.cloud,
            login=decrypt_credential(connection.api_login_encrypted),
            password=decrypt_credential(connection.api_password_encrypted),
        )
    )
    try:
        adapter = QuickRestoProviderAdapter(
            active_client,
            business_day_cutoff_hour=int(connection.business_day_cutoff_hour),
        )
        report = adapter.probe_extended_capabilities()
        required = {
            Capability.CURRENT_BUSINESS_SHIFT,
            Capability.TABLES,
            Capability.RESTAURANT_SECTIONS,
            Capability.EMPLOYEES,
            Capability.INVENTORY,
            Capability.PURCHASES,
            Capability.WRITEOFFS,
            Capability.STOCK_MOVEMENTS,
        }
        unavailable = sorted(
            capability.value
            for capability in required
            if report.capabilities[capability].state not in {CapabilityState.SUPPORTED, CapabilityState.DERIVED}
        )
        if unavailable:
            raise ProviderCapabilityError(
                "QuickResto Stage 3 capability probe did not confirm: " + ", ".join(unavailable)
            )
        return sync_quickresto_expanded_capabilities(
            db,
            connection=canonical_connection,
            adapter=adapter,
            period_start=period_start,
            period_end_exclusive=period_end_exclusive,
            timezone_name=str(venue.timezone or "Europe/Moscow"),
            business_day_cutoff_hour=int(connection.business_day_cutoff_hour),
        )
    finally:
        if managed_client:
            active_client.close()


def sync_quickresto_expanded_capabilities(
    db: Session,
    *,
    connection: IntegrationConnection,
    adapter: QuickRestoProviderAdapter,
    period_start: date,
    period_end_exclusive: date,
    timezone_name: str,
    import_run_id: int | None = None,
    observed_at: datetime | None = None,
    business_day_cutoff_hour: int = 0,
) -> QuickRestoExpandedSyncResult:
    """Persist only live-proven Quick Resto v0.4 capabilities.

    This is intentionally separate from the historical closed-shift worker.
    It cannot project revenue, payroll, payments, or reports.
    """

    if str(connection.provider).upper() != "QUICKRESTO":
        raise ValueError("QuickResto expanded sync requires a QUICKRESTO integration connection")
    if period_end_exclusive <= period_start:
        raise ValueError("period_end_exclusive must be later than period_start")
    external_venue_id = str(connection.external_venue_id or "").strip()
    if not external_venue_id:
        raise ValueError("QuickResto external venue id is required")
    observed_at = observed_at or datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")

    result = QuickRestoExpandedSyncResult()
    shift = adapter.get_current_business_shift(external_venue_id=external_venue_id)
    if shift is not None:
        raw = _record_raw(
            db,
            connection=connection,
            entity_type="QR_CURRENT_SHIFT",
            record=shift,
            import_run_id=import_run_id,
        )
        canonical = _replay_and_apply(
            db,
            raw=raw,
            venue_id=connection.venue_id,
            timezone_name=timezone_name,
            business_day_cutoff_hour=business_day_cutoff_hour,
        )
        result.raw_object_ids.append(int(raw.id))
        result.add("current_business_shifts")
        store_operational_snapshot(
            db,
            connection_id=int(connection.id),
            venue_id=int(connection.venue_id),
            object_type="BUSINESS_SHIFT",
            external_id=shift.external_id,
            payload={"status": "OPEN", "external_id": shift.external_id},
            observed_at=observed_at,
            source_status="OPEN",
            business_shift_id=int(canonical.id),
        )

    for entity_type, records, count_key in (
        (
            "QR_RESTAURANT_SECTION",
            adapter.iter_restaurant_sections(external_venue_id=external_venue_id),
            "restaurant_sections",
        ),
        ("QR_TABLE", adapter.iter_tables(external_venue_id=external_venue_id), "tables"),
        ("QR_EMPLOYEE", adapter.iter_employees(), "employees"),
    ):
        _apply_records(
            db,
            connection=connection,
            entity_type=entity_type,
            records=records,
            result=result,
            count_key=count_key,
            timezone_name=timezone_name,
            import_run_id=import_run_id,
        )

    # A single generic document stream avoids duplicate provider reads while
    # still materializing purchase/write-off specializations and movements.
    _apply_records(
        db,
        connection=connection,
        entity_type="QR_INVENTORY_DOCUMENT",
        records=adapter.iter_stock_movements(
            period_start=period_start,
            period_end_exclusive=period_end_exclusive,
        ),
        result=result,
        count_key="inventory_documents",
        timezone_name=timezone_name,
        import_run_id=import_run_id,
    )
    db.commit()
    return result


def replay_quickresto_expanded_raw(
    db: Session,
    *,
    raw: IntegrationRawObject,
    venue_id: int,
    timezone_name: str,
    business_day_cutoff_hour: int = 0,
) -> Any:
    """Rebuild one Stage 3 canonical object without calling Quick Resto."""

    return _replay_and_apply(
        db,
        raw=raw,
        venue_id=venue_id,
        timezone_name=timezone_name,
        business_day_cutoff_hour=business_day_cutoff_hour,
    )


def _apply_records(
    db: Session,
    *,
    connection: IntegrationConnection,
    entity_type: str,
    records: Iterable[ProviderRecord],
    result: QuickRestoExpandedSyncResult,
    count_key: str,
    timezone_name: str,
    import_run_id: int | None,
) -> None:
    for record in records:
        raw = _record_raw(
            db,
            connection=connection,
            entity_type=entity_type,
            record=record,
            import_run_id=import_run_id,
        )
        applied = _replay_and_apply(
            db,
            raw=raw,
            venue_id=connection.venue_id,
            timezone_name=timezone_name,
        )
        result.raw_object_ids.append(int(raw.id))
        result.add(count_key)
        if entity_type == "QR_INVENTORY_DOCUMENT":
            result.add("stock_movements", len(applied.get("stock_movements", ())))
            if applied.get("purchase") is not None:
                result.add("purchases")
            if applied.get("writeoff") is not None:
                result.add("writeoffs")


def _record_raw(
    db: Session,
    *,
    connection: IntegrationConnection,
    entity_type: str,
    record: ProviderRecord,
    import_run_id: int | None,
) -> IntegrationRawObject:
    return record_raw_object(
        db,
        connection_id=int(connection.id),
        entity_type=entity_type,
        record=record,
        allowed_fields=_RAW_ALLOWLISTS[entity_type],
        import_run_id=import_run_id,
    )


def _replay_and_apply(
    db: Session,
    *,
    raw: IntegrationRawObject,
    venue_id: int,
    timezone_name: str,
    business_day_cutoff_hour: int = 0,
) -> Any:
    entity_type = str(raw.entity_type).upper()
    normalizers = {
        "QR_CURRENT_SHIFT": _normalize_shift,
        "QR_RESTAURANT_SECTION": _normalize_section,
        "QR_TABLE": _normalize_table,
        "QR_EMPLOYEE": _normalize_employee,
        "QR_INVENTORY_DOCUMENT": _normalize_document,
    }
    normalizer = normalizers.get(entity_type)
    if normalizer is None:
        raise ValueError(f"Unsupported QuickResto Stage 3 raw entity type: {entity_type}")
    normalized = replay_raw_object(raw, normalizer=normalizer)
    if entity_type == "QR_CURRENT_SHIFT":
        canonical = _apply_shift(
            db,
            raw,
            normalized,
            venue_id=venue_id,
            timezone_name=timezone_name,
            business_day_cutoff_hour=business_day_cutoff_hour,
        )
    elif entity_type == "QR_RESTAURANT_SECTION":
        canonical = _apply_section(db, raw, normalized, venue_id=venue_id)
    elif entity_type == "QR_TABLE":
        canonical = _apply_table(db, raw, normalized, venue_id=venue_id)
    elif entity_type == "QR_EMPLOYEE":
        canonical = _apply_employee(db, raw, normalized)
    else:
        canonical = _apply_document(db, raw, normalized, venue_id=venue_id, timezone_name=timezone_name)
    raw.normalization_version = NORMALIZATION_VERSION
    raw.normalized_at = datetime.now(timezone.utc)
    db.add(raw)
    db.flush()
    return canonical


def _normalize_shift(record: ProviderRecord) -> dict[str, Any]:
    payload = dict(record.payload)
    status = str(payload.get("status") or "").strip().upper()
    if status not in {"OPEN", "OPENED"}:
        raise ValueError("QuickResto current shift replay requires an explicit OPEN or OPENED status")
    return {"external_id": record.external_id, "payload": payload, "source_version": record.source_version}


def _normalize_section(record: ProviderRecord) -> dict[str, Any]:
    payload = dict(record.payload)
    return {
        "external_id": record.external_id,
        "name": _text(payload.get("name") or payload.get("title") or payload.get("itemTitle"))
        or f"Зал {record.external_id}",
        "is_active": _is_active(payload),
        "source_version": record.source_version,
    }


def _normalize_table(record: ProviderRecord) -> dict[str, Any]:
    payload = dict(record.payload)
    number = _text(payload.get("number"))
    return {
        "external_id": record.external_id,
        "section_external_id": _ref_id(
            payload.get("restaurantSectionId") or payload.get("hall") or payload.get("section")
        ),
        "number": number,
        "name": _text(payload.get("name") or payload.get("title") or payload.get("itemTitle"))
        or number
        or f"Стол {record.external_id}",
        "capacity": _positive_int(
            payload.get("capacity") or payload.get("maxCapacity") or payload.get("places") or payload.get("seats")
        ),
        "is_active": _is_active(payload),
        "source_version": record.source_version,
    }


def _normalize_employee(record: ProviderRecord) -> dict[str, Any]:
    payload = dict(record.payload)
    name_parts = [
        _text(payload.get("lastName")),
        _text(payload.get("firstName")),
        _text(payload.get("middleName")),
    ]
    position = payload.get("position") or payload.get("role")
    return {
        "external_id": record.external_id,
        "name": _text(payload.get("fullName") or payload.get("name"))
        or " ".join(part for part in name_parts if part)
        or f"Сотрудник {record.external_id}",
        "position_name": _text(position.get("name") if isinstance(position, Mapping) else position),
        "is_active": _is_active(payload),
        "source_version": record.source_version,
    }


def _normalize_document(record: ProviderRecord) -> dict[str, Any]:
    payload = dict(record.payload)
    surface = str(payload.get("documentSurface") or "").strip()
    if surface not in _DOCUMENT_TYPE:
        raise ValueError(f"Unsupported QuickResto inventory document surface: {surface or 'missing'}")
    document_date = _date_value(
        payload.get("invoiceDate") or payload.get("documentDate") or payload.get("date") or payload.get("created")
    )
    if document_date is None:
        raise ValueError("QuickResto inventory document has no usable date")
    lines = []
    for collection, index, line in _line_rows(payload):
        source_line_id = _ref_id(line) or str(index)
        line_external_id = f"{collection}:{source_line_id}"
        quantity = _decimal(_first_present(line, "quantity", "actualAmount", "amount", "count", "actualQuantity"))
        book_quantity = _decimal(_first_present(line, "bookQuantity", "accountingQuantity"))
        actual_quantity = _decimal(line.get("actualQuantity"), default=quantity)
        difference_quantity = _decimal(
            line.get("differenceQuantity"),
            default=actual_quantity - book_quantity if surface == "inventory_documents" else quantity,
        )
        lines.append(
            {
                "external_id": line_external_id,
                "collection": collection,
                "product_external_id": _ref_id(
                    line.get("product") or line.get("dish") or line.get("nomenclature") or line.get("goods")
                ),
                "warehouse_external_id": _ref_id(line.get("store")),
                "quantity": quantity,
                "book_quantity": book_quantity,
                "actual_quantity": actual_quantity,
                "difference_quantity": difference_quantity,
                "unit": _unit(line),
                "price_per_unit": _optional_decimal(_first_present(line, "price", "pricePerUnit")),
                "cost_per_unit": _optional_decimal(_first_present(line, "cost", "costPerUnit", "costPrice")),
                "total_amount": _optional_decimal(
                    _first_present(
                        line,
                        "total",
                        "sum",
                        "amountSum",
                        "calculatedTotalSum",
                        "costPriceSum",
                        "fixedTotalSum",
                    )
                ),
            }
        )
    return {
        "external_id": record.external_id,
        "surface": surface,
        "document_type": _DOCUMENT_TYPE[surface],
        "document_date": document_date,
        "document_number": _text(
            payload.get("documentNumber") or payload.get("number") or payload.get("invoiceNumber")
        ),
        "status": _document_status(payload),
        "comment": _text(payload.get("comment") or payload.get("description")),
        "warehouse_external_id": _ref_id(payload.get("store")),
        "warehouse_from_external_id": _ref_id(payload.get("fromStore") or payload.get("storeFrom")),
        "warehouse_to_external_id": _ref_id(
            payload.get("storeTo")
            or (
                payload.get("store")
                if surface
                in {
                    "exchange_invoices",
                    "cooking_invoices",
                    "decomposition_invoices",
                    "processing_invoices",
                }
                else None
            )
        ),
        "supplier": payload.get("provider") or payload.get("supplier"),
        "reason": _label(payload.get("discardReason")),
        "total_amount": _optional_decimal(_first_present(payload, "totalSum", "totalAmount", "sum", "amount")),
        "lines": lines,
        "source_version": record.source_version,
    }


def _apply_shift(
    db: Session,
    raw: IntegrationRawObject,
    value: Mapping[str, Any],
    *,
    venue_id: int,
    timezone_name: str,
    business_day_cutoff_hour: int,
) -> POSBusinessShift:
    payload = value["payload"]
    opened_at = _datetime_value(payload.get("localOpenedTime") or payload.get("opened"), timezone_name)
    business_date_payload = dict(payload)
    business_date_payload.setdefault("localOpenedTime", payload.get("opened"))
    business_date = business_date_for_shift(business_date_payload, cutoff_hour=business_day_cutoff_hour)
    row = _upsert(
        db,
        POSBusinessShift,
        connection_id=raw.integration_connection_id,
        external_id=value["external_id"],
        values={
            "venue_id": int(venue_id),
            "shift_number": _text(payload.get("shiftNumber")),
            "business_date": business_date,
            "calendar_date": opened_at.astimezone(ZoneInfo(timezone_name)).date() if opened_at else business_date,
            "shift_slot": "DAY",
            "opened_at": opened_at,
            "closed_at": None,
            "status": "OPEN",
            "orders_count": int(payload.get("ordersCount") or 0),
            "current_orders_count": int(payload.get("ordersCount") or 0),
            "revenue_amount": Decimal("0"),
            "refund_amount": Decimal("0"),
            "writeoff_amount": Decimal("0"),
            "currency": "RUB",
            **_source_values(raw),
        },
    )
    raw.canonical_identity = f"POSBusinessShift:{int(row.id)}"
    return row


def _apply_section(
    db: Session,
    raw: IntegrationRawObject,
    value: Mapping[str, Any],
    *,
    venue_id: int,
) -> POSRestaurantSection:
    row = _upsert(
        db,
        POSRestaurantSection,
        connection_id=raw.integration_connection_id,
        external_id=value["external_id"],
        values={
            "venue_id": int(venue_id),
            "name": value["name"],
            "is_active": value["is_active"],
            **_source_values(raw),
        },
    )
    raw.canonical_identity = f"POSRestaurantSection:{int(row.id)}"
    return row


def _apply_table(
    db: Session,
    raw: IntegrationRawObject,
    value: Mapping[str, Any],
    *,
    venue_id: int,
) -> POSTable:
    section = _by_external_id(db, POSRestaurantSection, raw.integration_connection_id, value["section_external_id"])
    row = _upsert(
        db,
        POSTable,
        connection_id=raw.integration_connection_id,
        external_id=value["external_id"],
        values={
            "venue_id": int(venue_id),
            "restaurant_section_id": int(section.id) if section else None,
            "number": value["number"],
            "name": value["name"],
            "capacity": value["capacity"],
            "is_active": value["is_active"],
            **_source_values(raw),
        },
    )
    raw.canonical_identity = f"POSTable:{int(row.id)}"
    return row


def _apply_employee(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any]) -> POSEmployee:
    row = _upsert(
        db,
        POSEmployee,
        connection_id=raw.integration_connection_id,
        external_id=value["external_id"],
        values={
            "name": value["name"],
            "position_name": value["position_name"],
            "is_active": value["is_active"],
            **_source_values(raw),
        },
    )
    raw.canonical_identity = f"POSEmployee:{int(row.id)}"
    return row


def _apply_document(
    db: Session,
    raw: IntegrationRawObject,
    value: Mapping[str, Any],
    *,
    venue_id: int,
    timezone_name: str,
) -> dict[str, Any]:
    connection_id = int(raw.integration_connection_id)
    warehouse = _by_external_id(db, POSWarehouse, connection_id, value["warehouse_external_id"])
    warehouse_from = _by_external_id(db, POSWarehouse, connection_id, value["warehouse_from_external_id"])
    warehouse_to = _by_external_id(db, POSWarehouse, connection_id, value["warehouse_to_external_id"])
    supplier = _supplier(db, connection_id, value["supplier"])
    document = _upsert(
        db,
        POSInventoryDocument,
        connection_id=connection_id,
        external_id=value["external_id"],
        values={
            "venue_id": int(venue_id),
            "warehouse_id": int(warehouse.id) if warehouse else None,
            "warehouse_from_id": int(warehouse_from.id) if warehouse_from else None,
            "warehouse_to_id": int(warehouse_to.id) if warehouse_to else None,
            "supplier_id": int(supplier.id) if supplier else None,
            "document_type": value["document_type"],
            "document_date": value["document_date"],
            "document_number": value["document_number"],
            "status": value["status"],
            "comment": value["comment"],
            "total_amount": value["total_amount"],
            "currency": "RUB",
            **_source_values(raw),
        },
    )
    purchase = None
    if value["surface"] == "incoming_invoices":
        purchase = _upsert(
            db,
            POSPurchaseDocument,
            connection_id=connection_id,
            external_id=value["external_id"],
            values={
                "venue_id": int(venue_id),
                "supplier_id": int(supplier.id) if supplier else None,
                "warehouse_id": int(warehouse.id) if warehouse else None,
                "document_date": value["document_date"],
                "document_number": value["document_number"],
                "total_amount": value["total_amount"] or Decimal("0"),
                "status": value["status"],
                "currency": "RUB",
                **_source_values(raw),
            },
        )
    writeoff = None
    if value["surface"] == "discard_invoices":
        writeoff = _upsert(
            db,
            POSWriteoff,
            connection_id=connection_id,
            external_id=value["external_id"],
            values={
                "venue_id": int(venue_id),
                "warehouse_id": int(warehouse.id) if warehouse else None,
                "occurred_at": datetime.combine(value["document_date"], datetime.min.time(), ZoneInfo(timezone_name)),
                "canonical_reason": "OTHER",
                "source_reason": value["reason"],
                "total_cost": value["total_amount"] or Decimal("0"),
                "status": value["status"],
                "currency": "RUB",
                **_source_values(raw),
            },
        )

    stock_movements: list[POSStockMovement] = []
    for line in value["lines"]:
        product = _by_external_id(db, POSProduct, connection_id, line["product_external_id"])
        line_warehouse = (
            _by_external_id(db, POSWarehouse, connection_id, line["warehouse_external_id"])
            or warehouse
            or warehouse_from
            or warehouse_to
        )
        inventory_item = _upsert(
            db,
            POSInventoryItem,
            connection_id=connection_id,
            external_id=f"{value['external_id']}:{line['external_id']}",
            values={
                "document_id": int(document.id),
                "product_id": int(product.id) if product else None,
                "book_quantity": line["book_quantity"],
                "actual_quantity": line["actual_quantity"],
                "difference_quantity": line["difference_quantity"],
                "cost_per_unit": line["cost_per_unit"],
                "difference_cost": None,
                "cost_amount": line["total_amount"],
                "quantity": line["quantity"],
                "price_per_unit": line["price_per_unit"],
                "total_amount": line["total_amount"],
                "unit": line["unit"],
                "currency": "RUB",
                **_source_values(raw),
            },
        )
        if product is not None:
            for suffix, movement_type, movement_quantity, movement_warehouse in _movement_specs(
                value["surface"],
                line,
                warehouse=line_warehouse,
                warehouse_from=warehouse_from,
                warehouse_to=warehouse_to,
            ):
                if movement_warehouse is None or movement_quantity == 0:
                    continue
                movement = _upsert(
                    db,
                    POSStockMovement,
                    connection_id=connection_id,
                    external_id=f"{value['external_id']}:{line['external_id']}:{suffix}",
                    values={
                        "warehouse_id": int(movement_warehouse.id),
                        "product_id": int(product.id),
                        "movement_type": movement_type,
                        "quantity": movement_quantity,
                        "unit": line["unit"],
                        "amount": line["total_amount"],
                        "occurred_at": datetime.combine(
                            value["document_date"], datetime.min.time(), ZoneInfo(timezone_name)
                        ),
                        "source_reason": value["reason"],
                        "source_document_external_id": value["external_id"],
                        "currency": "RUB",
                        **_source_values(raw),
                    },
                )
                stock_movements.append(movement)
        if purchase is not None and line["quantity"] > 0:
            _upsert(
                db,
                POSPurchaseItem,
                connection_id=connection_id,
                external_id=f"{value['external_id']}:{line['external_id']}",
                values={
                    "document_id": int(purchase.id),
                    "product_id": int(product.id) if product else None,
                    "quantity": line["quantity"],
                    "unit": line["unit"],
                    "price_per_unit": line["price_per_unit"] or Decimal("0"),
                    "total_amount": line["total_amount"] or Decimal("0"),
                    "currency": "RUB",
                    **_source_values(raw),
                },
            )
        if writeoff is not None and abs(line["quantity"]) > 0:
            _upsert(
                db,
                POSWriteoffItem,
                connection_id=connection_id,
                external_id=f"{value['external_id']}:{line['external_id']}",
                values={
                    "writeoff_id": int(writeoff.id),
                    "product_id": int(product.id) if product else None,
                    "quantity": abs(line["quantity"]),
                    "unit": line["unit"],
                    "cost_amount": abs(line["total_amount"] or Decimal("0")),
                    "currency": "RUB",
                    **_source_values(raw),
                },
            )
        _ = inventory_item
    raw.canonical_identity = f"POSInventoryDocument:{int(document.id)}"
    return {"document": document, "purchase": purchase, "writeoff": writeoff, "stock_movements": stock_movements}


def _upsert(db: Session, model, *, connection_id: int, external_id: str, values: Mapping[str, Any]):
    row = db.scalar(
        select(model).where(model.connection_id == int(connection_id), model.external_id == str(external_id))
    )
    if row is None:
        row = model(connection_id=int(connection_id), external_id=str(external_id), **dict(values))
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    row.synced_at = datetime.now(timezone.utc)
    row.is_deleted = False
    row.deleted_at = None
    db.flush()
    return row


def _by_external_id(db: Session, model, connection_id: int, external_id: str | None):
    if not external_id:
        return None
    return db.scalar(
        select(model).where(model.connection_id == int(connection_id), model.external_id == str(external_id))
    )


def _supplier(db: Session, connection_id: int, value: Any) -> POSSupplier | None:
    external_id = _ref_id(value)
    if not external_id:
        return None
    name = _label(value) or f"Поставщик {external_id}"
    return _upsert(
        db,
        POSSupplier,
        connection_id=connection_id,
        external_id=external_id,
        values={"name": name, "is_active": True},
    )


def _source_values(raw: IntegrationRawObject) -> dict[str, Any]:
    return {
        "source_version": raw.source_version,
        "payload_hash": raw.payload_hash,
        "source_updated_at": raw.source_updated_at,
        "source_metadata_json": {"raw_object_id": int(raw.id), "normalization_version": NORMALIZATION_VERSION},
    }


def _ref_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("frontId") or value.get("_id") or value.get("id")
    raw = str(value or "").strip()
    return raw or None


def _text(value: Any) -> str | None:
    raw = str(value or "").strip()
    return raw or None


def _label(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _text(_first_present(value, "description", "name", "title", "shortName", "fullName", "refId"))
    return _text(value)


def _first_present(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value and value[key] is not None and value[key] != "":
            return value[key]
    return None


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _is_active(payload: Mapping[str, Any]) -> bool:
    if payload.get("deleted") is not None:
        return not bool(payload.get("deleted"))
    if payload.get("blocked") is not None:
        return not bool(payload.get("blocked"))
    if payload.get("active") is not None:
        return bool(payload.get("active"))
    return True


def _decimal(value: Any, *, default: Decimal = Decimal("0")) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid QuickResto decimal value: {value!r}") from exc


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return _decimal(value)


def _date_value(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None


def _datetime_value(value: Any, timezone_name: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
    return parsed.astimezone(timezone.utc)


def _line_rows(payload: Mapping[str, Any]) -> list[tuple[str, int, dict[str, Any]]]:
    rows: list[tuple[str, int, dict[str, Any]]] = []
    for key in (
        "positions",
        "items",
        "documentItems",
        "rows",
        "products",
        "invoiceItems",
        "invoiceComponents",
        "sourceItems",
        "resultComponents",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            rows.extend((key, index, item) for index, item in enumerate(value) if isinstance(item, dict))
    return rows


def _unit(line: Mapping[str, Any]) -> str:
    value = line.get("unit") or line.get("measureUnit")
    if isinstance(value, Mapping):
        value = value.get("name") or value.get("shortName") or value.get("code")
    return _text(value) or "UNIT"


def _document_status(payload: Mapping[str, Any]) -> str:
    if bool(payload.get("deleted")):
        return "DELETED"
    if bool(payload.get("cancelled")):
        return "CANCELLED"
    if payload.get("processed") is True:
        return "POSTED"
    if payload.get("processed") is False:
        return "DRAFT"
    return "UNKNOWN"


def _movement_specs(
    surface: str,
    line: Mapping[str, Any],
    *,
    warehouse: POSWarehouse | None,
    warehouse_from: POSWarehouse | None,
    warehouse_to: POSWarehouse | None,
) -> list[tuple[str, str, Decimal, POSWarehouse | None]]:
    quantity = line["difference_quantity"] if surface == "inventory_documents" else line["quantity"]
    absolute_quantity = abs(quantity)
    collection = str(line.get("collection") or "")
    if surface == "inventory_documents":
        return [("inventory", "INVENTORY_CORRECTION", quantity, warehouse)]
    if surface == "incoming_invoices":
        return [("purchase", "PURCHASE", absolute_quantity, warehouse)]
    if surface == "outgoing_invoices":
        return [("outgoing", "OTHER", -absolute_quantity, warehouse_from or warehouse)]
    if surface == "discard_invoices":
        return [("writeoff", "WRITEOFF", -absolute_quantity, warehouse)]
    if surface == "exchange_invoices":
        return [
            ("transfer-out", "TRANSFER_OUT", -absolute_quantity, warehouse_from or warehouse),
            ("transfer-in", "TRANSFER_IN", absolute_quantity, warehouse_to or warehouse),
        ]
    if surface in {"cooking_invoices", "decomposition_invoices", "processing_invoices"}:
        source_collections = {"sourceItems", "invoiceComponents"}
        is_source = collection in source_collections
        return [
            (
                "production-source" if is_source else "production-result",
                "PRODUCTION",
                -absolute_quantity if is_source else absolute_quantity,
                (warehouse_from or warehouse) if is_source else (warehouse_to or warehouse),
            )
        ]
    return []

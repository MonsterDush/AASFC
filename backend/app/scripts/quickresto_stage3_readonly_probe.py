from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Mapping
import json
from typing import Any

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.quickresto_connection import QuickRestoConnection
from app.services.integrations.quickresto import QUICKRESTO_OBJECT_TYPES, QuickRestoHTTPError
from app.services.integrations.quickresto_sync import build_quickresto_client


# Keep the probe streamable to an older production checkout which may not yet
# contain the Stage 2 candidate types. Values are public API class identifiers,
# never connection-specific data.
_STAGE3_OBJECT_TYPES = {
    "employees": (
        "personnel.employee",
        "ru.edgex.quickresto.modules.personnel.employee.Employee",
    ),
    "inventory_documents": (
        "warehouse.inventory.document.v2",
        "ru.edgex.quickresto.modules.warehouse.inventory.document.InventoryDocument2",
    ),
    "incoming_invoices": (
        "warehouse.documents.incoming",
        "ru.edgex.quickresto.modules.warehouse.documents.incoming.IncomingInvoice",
    ),
    "outgoing_invoices": (
        "warehouse.documents.outgoing",
        "ru.edgex.quickresto.modules.warehouse.documents.outgoing.OutgoingInvoice",
    ),
    "discard_invoices": (
        "warehouse.documents.discard",
        "ru.edgex.quickresto.modules.warehouse.documents.discard.DiscardInvoice",
    ),
    "exchange_invoices": (
        "warehouse.documents.exchange",
        "ru.edgex.quickresto.modules.warehouse.documents.exchange.ExchangeInvoice",
    ),
    "cooking_invoices": (
        "warehouse.documents.cooking",
        "ru.edgex.quickresto.modules.warehouse.documents.cooking.CookingInvoice",
    ),
    "decomposition_invoices": (
        "warehouse.documents.decomposition",
        "ru.edgex.quickresto.modules.warehouse.documents.decomposition.DecompositionInvoice",
    ),
    "processing_invoices": (
        "warehouse.documents.processing",
        "ru.edgex.quickresto.modules.warehouse.documents.processing.ProcessingInvoice",
    ),
}

_LINE_KEYS = (
    "positions",
    "items",
    "documentItems",
    "rows",
    "products",
    "invoiceItems",
    "invoiceComponents",
    "sourceItems",
    "resultComponents",
)
_PRODUCT_REFERENCE_KEYS = ("product", "dish", "nomenclature", "goods")
_QUANTITY_KEYS = (
    "quantity",
    "actualAmount",
    "amount",
    "count",
    "bookQuantity",
    "accountingQuantity",
    "actualQuantity",
    "differenceQuantity",
)


def _paths(value: Any, *, prefix: str = "", depth: int = 0) -> set[str]:
    if depth > 5:
        return set()
    output: set[str] = set()
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            output.add(path)
            output.update(_paths(child, prefix=path, depth=depth + 1))
    elif isinstance(value, list) and value:
        output.update(_paths(value[0], prefix=f"{prefix}[]", depth=depth + 1))
    return output


def _shape(rows: list[dict[str, Any]], detail: dict[str, Any] | None = None) -> dict[str, Any]:
    paths: set[str] = set()
    for row in rows:
        paths.update(_paths(row))
    if detail:
        paths.update(_paths(detail))
    collections = sorted(path for path in paths if "[]" in path)
    line_keys = sorted(key for key in _LINE_KEYS if isinstance((detail or {}).get(key), list))
    line_fields: set[str] = set()
    collection_fields: dict[str, list[str]] = {}
    for key, values in (detail or {}).items():
        if not isinstance(values, list):
            continue
        fields = sorted({str(field) for item in values[:3] if isinstance(item, Mapping) for field in item})
        collection_fields[str(key)] = fields
    for key in line_keys:
        values = (detail or {}).get(key) or []
        for item in values[:3]:
            if isinstance(item, Mapping):
                line_fields.update(str(field) for field in item)
    return {
        "rows_observed": len(rows),
        "list_fields": sorted({str(key) for row in rows for key in row}),
        "detail_fields": sorted(str(key) for key in (detail or {})),
        "structural_paths": sorted(paths),
        "collection_paths": collections,
        "recognized_line_collections": line_keys,
        "line_fields": sorted(line_fields),
        "collection_fields": collection_fields,
        "recognized_product_reference_fields": sorted(set(line_fields) & set(_PRODUCT_REFERENCE_KEYS)),
        "recognized_quantity_fields": sorted(set(line_fields) & set(_QUANTITY_KEYS)),
    }


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, QuickRestoHTTPError):
        return f"HTTP_{int(exc.status_code)}"
    return type(exc).__name__.upper()


def _read_sample(client, object_type: tuple[str, str], *, limit: int = 5) -> tuple[list[dict], dict | None]:
    module_name, class_name = object_type
    rows = client.list_objects(module_name=module_name, class_name=class_name, limit=limit, offset=0)
    detail = None
    if rows:
        try:
            object_id = int(rows[0].get("id") or 0)
        except (TypeError, ValueError):
            object_id = 0
        if object_id > 0:
            detail = client.read_object(module_name=module_name, class_name=class_name, object_id=object_id)
    return rows, detail


def run_probe(*, venue_id: int, compact: bool = False) -> dict[str, Any]:
    object_types = {**QUICKRESTO_OBJECT_TYPES, **_STAGE3_OBJECT_TYPES}
    with SessionLocal() as db:
        connection = db.execute(
            select(QuickRestoConnection).where(QuickRestoConnection.venue_id == int(venue_id))
        ).scalar_one_or_none()
        if connection is None:
            raise ValueError("QuickResto connection was not found")
        if connection.external_venue_id is None:
            raise ValueError("QuickResto external venue is not selected")
        selected_scheme_id = int(connection.external_venue_id)
        connection_id = int(connection.id)

        surfaces: dict[str, Any] = {}
        with build_quickresto_client(connection) as client:
            try:
                module_name, class_name = object_types["shifts"]
                shift_rows = client.list_all_objects(module_name=module_name, class_name=class_name)
                scoped_rows = []
                for row in shift_rows:
                    reference = row.get("tableScheme")
                    if isinstance(reference, Mapping):
                        reference = reference.get("id")
                    if reference is None or str(reference) == str(selected_scheme_id):
                        scoped_rows.append(row)
                statuses = Counter(str(row.get("status") or "MISSING").upper() for row in scoped_rows)
                surfaces["current_business_shift"] = {
                    **_shape(scoped_rows[:5]),
                    "scoped_rows": len(scoped_rows),
                    "status_counts": dict(sorted(statuses.items())),
                    "open_rows": int(statuses.get("OPEN", 0) + statuses.get("OPENED", 0)),
                }
            except Exception as exc:
                surfaces["current_business_shift"] = {"error_code": _safe_error(exc)}

            try:
                module_name, class_name = object_types["venues"]
                detail = client.read_object(
                    module_name=module_name,
                    class_name=class_name,
                    object_id=selected_scheme_id,
                )
                surfaces["selected_table_scheme"] = _shape([], detail)
            except Exception as exc:
                surfaces["selected_table_scheme"] = {"error_code": _safe_error(exc)}

            for surface in (
                "employees",
                "inventory_documents",
                "incoming_invoices",
                "outgoing_invoices",
                "discard_invoices",
                "exchange_invoices",
                "cooking_invoices",
                "decomposition_invoices",
                "processing_invoices",
            ):
                try:
                    rows, detail = _read_sample(client, object_types[surface])
                    surfaces[surface] = _shape(rows, detail)
                except Exception as exc:
                    surfaces[surface] = {"error_code": _safe_error(exc)}

    result = {
        "schema_version": 1,
        "provider": "QUICKRESTO",
        "probe": "STAGE3_READ_ONLY_SHAPE",
        "contains_payload_values": False,
        "venue_id": int(venue_id),
        "connection_id": connection_id,
        "database_writes": 0,
        "provider_methods": ["GET /api/list", "GET /api/read"],
        "surfaces": surfaces,
    }
    if compact:
        result["surfaces"] = {
            name: {
                key: value
                for key, value in shape.items()
                if key
                in {
                    "error_code",
                    "rows_observed",
                    "scoped_rows",
                    "status_counts",
                    "open_rows",
                    "detail_fields",
                    "collection_fields",
                    "recognized_line_collections",
                    "line_fields",
                    "recognized_product_reference_fields",
                    "recognized_quantity_fields",
                }
            }
            for name, shape in surfaces.items()
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect Quick Resto Stage 3 response shapes without retaining values")
    parser.add_argument("--venue-id", type=int, required=True)
    parser.add_argument("--compact", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(run_probe(venue_id=args.venue_id, compact=args.compact), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

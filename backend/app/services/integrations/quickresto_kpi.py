from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.quickresto_kpi_product_mapping import QuickRestoKpiProductMapping


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _product_title(product: Mapping[str, Any], external_id: int) -> str:
    title = str(product.get("name") or product.get("itemTitle") or "").strip()
    return (title or f"Позиция QuickResto #{int(external_id)}")[:160]


def _fallback_product_title(external_id: int) -> str:
    return f"Позиция QuickResto #{int(external_id)}"


def _is_fallback_product_title(value: Any, external_id: int) -> bool:
    title = str(value or "").strip()
    return not title or title == _fallback_product_title(external_id)


def _product_group_title(product: Mapping[str, Any]) -> str | None:
    parent = product.get("parentItem")
    parent_title = ""
    if isinstance(parent, Mapping):
        parent_title = str(parent.get("name") or parent.get("itemTitle") or "").strip()
    title = str(product.get("parentName") or parent_title or "").strip()
    return title[:160] or None


def _is_writeoff_order(order: Mapping[str, Any]) -> bool:
    operation_types: set[str] = set()
    payments = order.get("payments")
    for payment in payments if isinstance(payments, list) else ():
        if not isinstance(payment, Mapping):
            continue
        payment_type = payment.get("paymentType")
        embedded_type = payment_type if isinstance(payment_type, Mapping) else {}
        operation_type = str(payment.get("operationType") or embedded_type.get("operationType") or "").strip().lower()
        if operation_type:
            operation_types.add(operation_type)
    return bool(operation_types) and operation_types == {"writeoff"}


def product_catalog_from_sources(
    sources: Iterable[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    products: dict[int, dict[str, Any]] = {}
    for source in sources:
        orders = source.get("orders") if isinstance(source, Mapping) else None
        for order in orders if isinstance(orders, list) else ():
            if not isinstance(order, Mapping) or bool(order.get("returned")) or _is_writeoff_order(order):
                continue
            items = order.get("orderItemList")
            for item in items if isinstance(items, list) else ():
                if not isinstance(item, Mapping):
                    continue
                product = item.get("product")
                if not isinstance(product, Mapping):
                    continue
                external_id = int(product.get("id") or 0)
                if external_id <= 0:
                    continue
                group_id = int(product.get("parentId") or 0)
                candidate = {
                    "external_product_id": external_id,
                    "external_name": _product_title(product, external_id),
                    "external_group_id": group_id if group_id > 0 else None,
                    "external_group_name": _product_group_title(product),
                }
                current = products.get(external_id)
                if current is not None:
                    if _is_fallback_product_title(candidate["external_name"], external_id):
                        candidate["external_name"] = current["external_name"]
                    if candidate["external_group_id"] is None:
                        candidate["external_group_id"] = current["external_group_id"]
                    if candidate["external_group_name"] is None:
                        candidate["external_group_name"] = current["external_group_name"]
                products[external_id] = candidate
    return products


def refresh_quickresto_product_catalog(
    db: Session,
    *,
    connection_id: int,
    sources: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    products = product_catalog_from_sources(sources)
    if not products:
        return {"products_seen": 0, "products_created": 0, "products_updated": 0}
    existing = {
        int(row.external_product_id): row
        for row in db.execute(
            select(QuickRestoKpiProductMapping).where(
                QuickRestoKpiProductMapping.connection_id == int(connection_id),
                QuickRestoKpiProductMapping.external_product_id.in_(sorted(products)),
            )
        ).scalars()
    }
    created = 0
    updated = 0
    now = _utcnow()
    for external_id, product in products.items():
        row = existing.get(external_id)
        if row is None:
            row = QuickRestoKpiProductMapping(
                connection_id=int(connection_id),
                external_product_id=external_id,
                external_name=str(product["external_name"]),
                external_group_id=product["external_group_id"],
                external_group_name=product["external_group_name"],
                kpi_metric_id=None,
                exclude_from_percentage_base=True,
                last_seen_at=now,
                updated_at=now,
            )
            db.add(row)
            created += 1
            continue
        external_name = str(product["external_name"])
        if _is_fallback_product_title(external_name, external_id) and not _is_fallback_product_title(
            row.external_name,
            external_id,
        ):
            external_name = str(row.external_name)
        external_group_id = product["external_group_id"]
        if external_group_id is None and row.external_group_id is not None:
            external_group_id = int(row.external_group_id)
        external_group_name = product["external_group_name"]
        if not external_group_name and row.external_group_name:
            external_group_name = str(row.external_group_name)
        changed = bool(
            str(row.external_name) != external_name
            or row.external_group_id != external_group_id
            or row.external_group_name != external_group_name
        )
        row.external_name = external_name
        row.external_group_id = external_group_id
        row.external_group_name = external_group_name
        row.last_seen_at = now
        row.updated_at = now
        updated += int(changed)
    db.flush()
    return {
        "products_seen": len(products),
        "products_created": created,
        "products_updated": updated,
    }


def product_directory_group_ids(
    rows: Iterable[Mapping[str, Any]],
    *,
    external_product_ids: Iterable[int],
) -> set[int]:
    product_ids = {int(value) for value in external_product_ids if int(value) > 0}
    output: set[int] = set()
    for item in rows:
        external_id = int(item.get("id") or 0)
        if external_id not in product_ids:
            continue
        parent = item.get("parentItem")
        embedded_parent_id = int(parent.get("id") or 0) if isinstance(parent, Mapping) else 0
        group_id = int(item.get("parentId") or embedded_parent_id or 0)
        if group_id > 0:
            output.add(group_id)
    return output


def product_directory_group_names(
    rows: Iterable[Mapping[str, Any]],
    *,
    external_group_ids: Iterable[int],
) -> dict[int, str]:
    group_ids = {int(value) for value in external_group_ids if int(value) > 0}
    output: dict[int, str] = {}
    for item in rows:
        external_id = int(item.get("id") or 0)
        if external_id not in group_ids:
            continue
        title = str(item.get("name") or item.get("itemTitle") or "").strip()[:160]
        if title:
            output[external_id] = title
    return output


def enrich_quickresto_product_catalog_from_directory(
    db: Session,
    *,
    connection_id: int,
    rows: Iterable[Mapping[str, Any]],
    group_names: Mapping[int, str] | None = None,
) -> dict[str, int]:
    """Restore names for sold products without adding the whole cloud catalog."""

    existing = {
        int(row.external_product_id): row
        for row in db.execute(
            select(QuickRestoKpiProductMapping).where(QuickRestoKpiProductMapping.connection_id == int(connection_id))
        ).scalars()
    }
    names_by_group = {
        int(external_id): str(title).strip()[:160]
        for external_id, title in (group_names or {}).items()
        if int(external_id) > 0 and str(title or "").strip()
    }
    directory_rows_seen = 0
    matched_product_ids: set[int] = set()
    product_names_refreshed = 0
    product_groups_refreshed = 0
    now = _utcnow()
    for item in rows:
        external_id = int(item.get("id") or 0)
        if external_id <= 0:
            continue
        directory_rows_seen += 1
        mapping = existing.get(external_id)
        if mapping is None:
            continue
        matched_product_ids.add(external_id)
        title = str(item.get("name") or item.get("itemTitle") or "").strip()[:160]
        parent = item.get("parentItem")
        embedded_parent = parent if isinstance(parent, Mapping) else {}
        group_id = int(item.get("parentId") or embedded_parent.get("id") or 0)
        group_name = str(
            item.get("parentName")
            or embedded_parent.get("name")
            or embedded_parent.get("itemTitle")
            or names_by_group.get(group_id)
            or ""
        ).strip()[:160]
        changed = False
        if title and str(mapping.external_name) != title:
            mapping.external_name = title
            product_names_refreshed += 1
            changed = True
        if group_id > 0 and mapping.external_group_id != group_id:
            mapping.external_group_id = group_id
            changed = True
        if group_name and str(mapping.external_group_name or "") != group_name:
            mapping.external_group_name = group_name
            product_groups_refreshed += 1
            changed = True
        if changed:
            mapping.updated_at = now
    db.flush()
    products_matched = len(matched_product_ids)
    products_unresolved = sum(
        int(_is_fallback_product_title(mapping.external_name, external_id)) for external_id, mapping in existing.items()
    )
    return {
        "directory_rows_seen": directory_rows_seen,
        "directory_products_matched": products_matched,
        "directory_products_unresolved": products_unresolved,
        "product_names_refreshed": product_names_refreshed,
        "product_group_names_refreshed": product_groups_refreshed,
    }


def serialize_quickresto_kpi_product_mappings(
    db: Session,
    *,
    connection_id: int,
) -> list[dict[str, Any]]:
    rows = list(
        db.execute(
            select(QuickRestoKpiProductMapping)
            .where(QuickRestoKpiProductMapping.connection_id == int(connection_id))
            .order_by(
                QuickRestoKpiProductMapping.external_name,
                QuickRestoKpiProductMapping.external_product_id,
            )
        ).scalars()
    )
    return [
        {
            "external_product_id": int(row.external_product_id),
            "external_name": row.external_name,
            "external_group_id": int(row.external_group_id) if row.external_group_id else None,
            "external_group_name": row.external_group_name,
            "kpi_metric_id": int(row.kpi_metric_id) if row.kpi_metric_id else None,
            "exclude_from_percentage_base": bool(row.exclude_from_percentage_base),
            "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        }
        for row in rows
    ]


def product_names_by_group(
    db: Session,
    *,
    connection_id: int,
    external_group_ids: Iterable[int],
    limit_per_group: int = 5,
) -> dict[int, list[str]]:
    group_ids = sorted({int(value) for value in external_group_ids if int(value) > 0})
    if not group_ids:
        return {}
    rows = list(
        db.execute(
            select(QuickRestoKpiProductMapping).where(
                QuickRestoKpiProductMapping.connection_id == int(connection_id),
                QuickRestoKpiProductMapping.external_group_id.in_(group_ids),
            )
        ).scalars()
    )
    output: dict[int, list[str]] = {}
    for row in sorted(rows, key=lambda item: (str(item.external_name).casefold(), int(item.external_product_id))):
        group_id = int(row.external_group_id or 0)
        values = output.setdefault(group_id, [])
        title = str(row.external_name or "").strip()
        if title and title not in values and len(values) < int(limit_per_group):
            values.append(title)
    return output


def product_group_names(
    db: Session,
    *,
    connection_id: int,
    external_group_ids: Iterable[int],
) -> dict[int, str]:
    group_ids = sorted({int(value) for value in external_group_ids if int(value) > 0})
    if not group_ids:
        return {}
    rows = list(
        db.execute(
            select(QuickRestoKpiProductMapping).where(
                QuickRestoKpiProductMapping.connection_id == int(connection_id),
                QuickRestoKpiProductMapping.external_group_id.in_(group_ids),
                QuickRestoKpiProductMapping.external_group_name.is_not(None),
            )
        ).scalars()
    )
    output: dict[int, str] = {}
    for row in rows:
        title = str(row.external_group_name or "").strip()
        if title:
            output.setdefault(int(row.external_group_id), title)
    return output

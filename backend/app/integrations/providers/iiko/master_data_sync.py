from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.base.dto import ProviderRecord
from app.integrations.providers.iiko.provider import IIKOProviderAdapter
from app.integrations.raw.storage import record_raw_object, replay_raw_object
from app.models.integration_connection import IntegrationConnection
from app.models.integration_raw_object import IntegrationRawObject
from app.models.pos_canonical import (
    POSModifier,
    POSModifierGroup,
    POSOrganization,
    POSPaymentType,
    POSProduct,
    POSProductGroup,
    POSProductModifierRule,
    POSProductVariant,
    POSRestaurantSection,
    POSStopListEntry,
    POSTable,
    POSTerminalGroup,
    POSVenue,
)
from app.models.venue import Venue


NORMALIZATION_VERSION = "iiko-v04-stage4-master-data-1"

_RAW_ALLOWLISTS: dict[str, tuple[str, ...]] = {
    "IIKO_ORGANIZATION": ("id", "name", "responseType", "isActive", "isDeleted"),
    "IIKO_TERMINAL_GROUP": (
        "id",
        "organizationId",
        "name",
        "timeZone",
        "isAlive",
        "isActive",
        "isDeleted",
    ),
    "IIKO_PRODUCT_GROUP": (
        "id",
        "name",
        "description",
        "parentGroup",
        "parentGroupId",
        "isDeleted",
        "isGroupModifier",
        "canonicalKind",
    ),
    "IIKO_PRODUCT": (
        "id",
        "name",
        "code",
        "sku",
        "barcode",
        "barcodes",
        "type",
        "groupId",
        "productCategoryId",
        "measureUnit",
        "isDeleted",
        "sizePrices",
        "modifiers",
        "groupModifiers",
    ),
    "IIKO_PRODUCT_VARIANT": (
        "id",
        "productId",
        "sizeId",
        "size",
        "price",
        "sku",
        "code",
        "isDeleted",
    ),
    "IIKO_MODIFIER_GROUP": (
        "id",
        "name",
        "code",
        "type",
        "minAmount",
        "maxAmount",
        "defaultAmount",
        "required",
        "freeOfChargeAmount",
        "childModifiers",
        "isDeleted",
    ),
    "IIKO_MODIFIER": (
        "id",
        "name",
        "code",
        "type",
        "groupId",
        "modifierGroupId",
        "sizePrices",
        "isDeleted",
    ),
    "IIKO_PRODUCT_MODIFIER_RULE": (
        "id",
        "productId",
        "modifierId",
        "modifierGroupId",
        "minAmount",
        "maxAmount",
        "defaultAmount",
        "freeOfChargeAmount",
        "groupMinAmount",
        "groupMaxAmount",
        "required",
        "price",
    ),
    "IIKO_PAYMENT_TYPE": (
        "id",
        "name",
        "paymentProcessingType",
        "paymentTypeKind",
        "isDeleted",
        "terminalGroups",
    ),
    "IIKO_RESTAURANT_SECTION": (
        "id",
        "terminalGroupId",
        "name",
        "tables",
        "isDeleted",
    ),
    "IIKO_TABLE": (
        "id",
        "restaurantSectionId",
        "number",
        "name",
        "seatingCapacity",
        "revision",
        "isDeleted",
        "posId",
    ),
    "IIKO_STOP_LIST_ENTRY": (
        "id",
        "organizationId",
        "terminalGroupId",
        "productId",
        "sizeId",
        "balance",
        "dateAdd",
        "dateDelete",
    ),
}


@dataclass(slots=True)
class IIKOMasterDataSyncResult:
    counts: dict[str, int] = field(default_factory=dict)
    raw_object_ids: list[int] = field(default_factory=list)

    def add(self, key: str) -> None:
        self.counts[key] = self.counts.get(key, 0) + 1


def sync_iiko_master_data(
    db: Session,
    *,
    connection: IntegrationConnection,
    adapter: IIKOProviderAdapter,
    import_run_id: int | None = None,
) -> IIKOMasterDataSyncResult:
    """Persist the selected iiko scope through encrypted Raw into ACDM.

    The function deliberately handles only Stage 4 read-only entities. It does
    not change the connection read mode and cannot write financial or payroll
    projections.
    """

    if str(connection.provider or "").upper() != "IIKO":
        raise ValueError("iiko master-data sync requires an IIKO integration connection")
    if str(connection.status or "").upper() not in {"ACTIVE", "CONNECTING", "DEGRADED"}:
        raise ValueError("iiko integration connection is not available for synchronization")
    venue_exists = db.scalar(select(Venue.id).where(Venue.id == int(connection.venue_id)))
    if venue_exists is None:
        raise ValueError("Axelio venue no longer exists")

    scope = adapter.discover_scope()
    selected_organization_id = _selected_organization_id(connection, adapter)
    organizations = [record for record in scope.organizations if record.external_id == selected_organization_id]
    if len(organizations) != 1:
        raise ValueError("selected iiko organization is not available to the supplied API key")

    selected_terminal_group_ids = set(adapter.terminal_group_ids)
    terminal_groups = [
        record
        for record in scope.terminal_groups
        if str(record.payload.get("organizationId") or "").strip() == selected_organization_id
        and (not selected_terminal_group_ids or record.external_id in selected_terminal_group_ids)
    ]
    if selected_terminal_group_ids != {record.external_id for record in terminal_groups}:
        raise ValueError("one or more selected iiko terminal groups are outside the selected organization")

    result = IIKOMasterDataSyncResult()
    streams: tuple[tuple[str, Iterable[ProviderRecord], str], ...] = (
        ("IIKO_ORGANIZATION", organizations, "organizations"),
        ("IIKO_TERMINAL_GROUP", terminal_groups, "terminal_groups"),
        ("IIKO_PRODUCT_GROUP", adapter.iter_product_groups(), "product_groups"),
        ("IIKO_PRODUCT", adapter.iter_products(), "products"),
        ("IIKO_PRODUCT_VARIANT", adapter.iter_product_variants(), "product_variants"),
        ("IIKO_MODIFIER_GROUP", adapter.iter_modifier_groups(), "modifier_groups"),
        ("IIKO_MODIFIER", adapter.iter_modifiers(), "modifiers"),
        ("IIKO_PRODUCT_MODIFIER_RULE", adapter.iter_product_modifier_rules(), "modifier_rules"),
        ("IIKO_PAYMENT_TYPE", adapter.iter_payment_types(), "payment_types"),
        (
            "IIKO_RESTAURANT_SECTION",
            adapter.iter_restaurant_sections(external_venue_id=selected_organization_id),
            "restaurant_sections",
        ),
        (
            "IIKO_TABLE",
            adapter.iter_tables(external_venue_id=selected_organization_id),
            "tables",
        ),
        ("IIKO_STOP_LIST_ENTRY", adapter.iter_stop_list_entries(), "stop_list_entries"),
    )
    for entity_type, records, count_key in streams:
        for record in records:
            raw = record_raw_object(
                db,
                connection_id=int(connection.id),
                entity_type=entity_type,
                record=record,
                allowed_fields=_RAW_ALLOWLISTS[entity_type],
                import_run_id=import_run_id,
            )
            replay_iiko_master_data_raw(db, raw=raw, venue_id=int(connection.venue_id))
            result.raw_object_ids.append(int(raw.id))
            result.add(count_key)
    db.commit()
    return result


def replay_iiko_master_data_raw(
    db: Session,
    *,
    raw: IntegrationRawObject,
    venue_id: int,
) -> Any:
    """Rebuild one Stage 4 canonical entity without calling iikoCloud."""

    entity_type = str(raw.entity_type or "").upper()
    normalizer = _NORMALIZERS.get(entity_type)
    applier = _APPLIERS.get(entity_type)
    if normalizer is None or applier is None:
        raise ValueError(f"unsupported iiko Stage 4 raw entity type: {entity_type}")
    normalized = replay_raw_object(raw, normalizer=normalizer)
    canonical = applier(db, raw, normalized, venue_id=venue_id)
    raw.normalization_version = NORMALIZATION_VERSION
    raw.normalized_at = datetime.now(timezone.utc)
    db.add(raw)
    db.flush()
    return canonical


def _selected_organization_id(
    connection: IntegrationConnection,
    adapter: IIKOProviderAdapter,
) -> str:
    candidates = {
        value
        for value in (
            str(connection.external_organization_id or "").strip(),
            str(connection.external_venue_id or "").strip(),
            str(adapter.organization_id or "").strip(),
        )
        if value
    }
    if not candidates:
        raise ValueError("iiko organization scope must be selected before synchronization")
    if len(candidates) != 1:
        raise ValueError("iiko connection and adapter organization scopes do not match")
    return candidates.pop()


def _active(payload: Mapping[str, Any]) -> bool:
    if payload.get("isDeleted") is not None:
        return not bool(payload["isDeleted"])
    if payload.get("isActive") is not None:
        return bool(payload["isActive"])
    return True


def _required_text(payload: Mapping[str, Any], key: str, *, fallback: str | None = None) -> str:
    value = str(payload.get(key) or fallback or "").strip()
    if not value:
        raise ValueError(f"iiko payload field {key} is required")
    return value


def _optional_text(payload: Mapping[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return None


def _decimal(value: Any, *, default: str = "0") -> Decimal:
    try:
        return Decimal(str(default if value is None or value == "" else value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError(f"invalid iiko decimal value: {value!r}") from exc


def _integer(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid iiko integer value: {value!r}") from exc


def _datetime(value: Any, *, fallback: datetime) -> datetime:
    if value is None or value == "":
        parsed = fallback
    elif isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError(f"invalid iiko datetime value: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _normalize_organization(record: ProviderRecord) -> dict[str, Any]:
    return {
        "name": _required_text(record.payload, "name", fallback=record.external_id),
        "is_active": _active(record.payload),
    }


def _normalize_terminal_group(record: ProviderRecord) -> dict[str, Any]:
    is_alive = record.payload.get("isAlive")
    return {
        "organization_external_id": _required_text(record.payload, "organizationId"),
        "name": _required_text(record.payload, "name", fallback=record.external_id),
        "status": None if is_alive is None else ("ALIVE" if bool(is_alive) else "OFFLINE"),
        "is_alive": None if is_alive is None else bool(is_alive),
        "is_active": _active(record.payload),
    }


def _normalize_product_group(record: ProviderRecord) -> dict[str, Any]:
    parent = record.payload.get("parentGroup")
    parent_id = _optional_text(record.payload, "parentGroupId")
    if parent_id is None and isinstance(parent, Mapping):
        parent_id = _optional_text(parent, "id")
    kind = str(record.payload.get("canonicalKind") or "GROUP").upper()
    if kind not in {"GROUP", "CATEGORY"}:
        raise ValueError(f"unsupported iiko product-group kind: {kind}")
    return {
        "name": _required_text(record.payload, "name", fallback=record.external_id),
        "parent_external_id": parent_id,
        "kind": kind,
        "is_active": _active(record.payload),
    }


def _normalize_product(record: ProviderRecord) -> dict[str, Any]:
    barcodes = record.payload.get("barcodes")
    barcode = _optional_text(record.payload, "barcode")
    if barcode is None and isinstance(barcodes, list) and barcodes:
        first = barcodes[0]
        barcode = _optional_text(first, "barcode", "value") if isinstance(first, Mapping) else str(first)
    return {
        "name": _required_text(record.payload, "name", fallback=record.external_id),
        "group_external_id": _optional_text(record.payload, "groupId"),
        "category_external_id": _optional_text(record.payload, "productCategoryId"),
        "code": _optional_text(record.payload, "code", "sku"),
        "barcode": barcode,
        "product_type": _optional_text(record.payload, "type"),
        "unit": _optional_text(record.payload, "measureUnit"),
        "is_active": _active(record.payload),
    }


def _normalize_variant(record: ProviderRecord) -> dict[str, Any]:
    size = record.payload.get("size")
    size_name = _optional_text(size, "name") if isinstance(size, Mapping) else None
    return {
        "product_external_id": _required_text(record.payload, "productId"),
        "size_external_id": _required_text(record.payload, "sizeId"),
        "name": size_name or _required_text(record.payload, "sizeId"),
        "code": _optional_text(record.payload, "code", "sku"),
        "is_active": _active(record.payload),
    }


def _normalize_modifier_group(record: ProviderRecord) -> dict[str, Any]:
    return {
        "name": _required_text(record.payload, "name", fallback=record.external_id),
        "min_quantity": int(_decimal(record.payload.get("minAmount"))),
        "max_quantity": _integer(record.payload.get("maxAmount")),
        "is_active": _active(record.payload),
    }


def _normalize_modifier(record: ProviderRecord) -> dict[str, Any]:
    return {
        "name": _required_text(record.payload, "name", fallback=record.external_id),
        "modifier_group_external_id": _optional_text(record.payload, "modifierGroupId", "groupId"),
        "code": _optional_text(record.payload, "code"),
        "price_delta": Decimal("0"),
        "is_active": _active(record.payload),
    }


def _normalize_modifier_rule(record: ProviderRecord) -> dict[str, Any]:
    group_min = record.payload.get("groupMinAmount")
    group_max = record.payload.get("groupMaxAmount")
    return {
        "product_external_id": _required_text(record.payload, "productId"),
        "modifier_external_id": _required_text(record.payload, "modifierId"),
        "modifier_group_external_id": _optional_text(record.payload, "modifierGroupId"),
        "min_amount": _decimal(group_min if group_min is not None else record.payload.get("minAmount")),
        "max_amount": (
            None
            if group_max is None and record.payload.get("maxAmount") is None
            else _decimal(group_max if group_max is not None else record.payload.get("maxAmount"))
        ),
        "default_amount": _decimal(record.payload.get("defaultAmount")),
        "free_amount": _decimal(record.payload.get("freeOfChargeAmount")),
        "is_required": bool(record.payload.get("required")),
    }


def _normalize_payment_type(record: ProviderRecord) -> dict[str, Any]:
    return {
        "name": _required_text(record.payload, "name", fallback=record.external_id),
        "source_operation_type": _optional_text(record.payload, "paymentProcessingType", "paymentTypeKind"),
        "is_active": _active(record.payload),
    }


def _normalize_section(record: ProviderRecord) -> dict[str, Any]:
    return {
        "name": _required_text(record.payload, "name", fallback=record.external_id),
        "is_active": _active(record.payload),
    }


def _normalize_table(record: ProviderRecord) -> dict[str, Any]:
    number = record.payload.get("number")
    return {
        "section_external_id": _required_text(record.payload, "restaurantSectionId"),
        "number": None if number is None else str(number),
        "name": _required_text(record.payload, "name", fallback=str(number or record.external_id)),
        "capacity": _integer(record.payload.get("seatingCapacity")),
        "is_active": _active(record.payload),
    }


def _normalize_stop_list_entry(record: ProviderRecord) -> dict[str, Any]:
    return {
        "terminal_group_external_id": _required_text(record.payload, "terminalGroupId"),
        "product_external_id": _required_text(record.payload, "productId"),
        "size_external_id": _optional_text(record.payload, "sizeId"),
        "balance": _decimal(record.payload.get("balance")),
        "started_at": record.payload.get("dateAdd"),
        "ended_at": record.payload.get("dateDelete"),
    }


def _by_external_id(
    db: Session,
    model,
    raw: IntegrationRawObject,
    external_id: str | None,
    *,
    required: bool = False,
):
    if not external_id:
        if required:
            raise ValueError(f"{model.__name__} external id is required")
        return None
    row = db.scalar(
        select(model).where(
            model.connection_id == int(raw.integration_connection_id),
            model.external_id == str(external_id),
        )
    )
    if row is None and required:
        raise ValueError(f"iiko dependency {model.__name__}:{external_id} was not normalized")
    return row


def _upsert(db: Session, model, raw: IntegrationRawObject, values: Mapping[str, Any]):
    row = _by_external_id(db, model, raw, raw.external_id)
    if row is None:
        row = model(
            connection_id=int(raw.integration_connection_id),
            external_id=str(raw.external_id),
        )
    for key, value in values.items():
        setattr(row, key, value)
    now = datetime.now(timezone.utc)
    row.source_version = raw.source_version
    row.payload_hash = raw.payload_hash
    row.source_updated_at = raw.source_updated_at
    row.synced_at = now
    row.source_metadata_json = {
        "provider": "IIKO",
        "raw_object_id": int(raw.id),
        "raw_entity_type": str(raw.entity_type),
    }
    is_active = bool(values.get("is_active", True))
    row.is_deleted = not is_active
    row.deleted_at = (row.deleted_at or now) if not is_active else None
    db.add(row)
    db.flush()
    return row


def _finalize_raw(db: Session, raw: IntegrationRawObject, *canonical: Any) -> None:
    raw.canonical_identity = ",".join(f"{type(row).__name__}:{int(row.id)}" for row in canonical)
    db.add(raw)


def _apply_organization(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    venue_timezone = db.scalar(select(Venue.timezone).where(Venue.id == int(venue_id)))
    if venue_timezone is None:
        raise ValueError("Axelio venue no longer exists")
    organization = _upsert(db, POSOrganization, raw, value)
    pos_venue = _upsert(
        db,
        POSVenue,
        raw,
        {
            "venue_id": int(venue_id),
            "organization_id": int(organization.id),
            "name": value["name"],
            "address": None,
            "timezone": str(venue_timezone or "Europe/Moscow"),
            "is_active": value["is_active"],
        },
    )
    _finalize_raw(db, raw, organization, pos_venue)
    return organization


def _apply_terminal_group(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    pos_venue = _by_external_id(db, POSVenue, raw, value["organization_external_id"], required=True)
    row = _upsert(
        db,
        POSTerminalGroup,
        raw,
        {
            "venue_id": int(venue_id),
            "pos_venue_id": int(pos_venue.id),
            "name": value["name"],
            "status": value["status"],
            "is_alive": value["is_alive"],
            "last_alive_at": None,
            "is_active": value["is_active"],
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _apply_product_group(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    del venue_id
    parent = _by_external_id(db, POSProductGroup, raw, value["parent_external_id"])
    row = _upsert(
        db,
        POSProductGroup,
        raw,
        {
            "parent_id": None if parent is None else int(parent.id),
            "name": value["name"],
            "kind": value["kind"],
            "is_active": value["is_active"],
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _apply_product(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    del venue_id
    group = _by_external_id(db, POSProductGroup, raw, value["group_external_id"])
    category = _by_external_id(db, POSProductGroup, raw, value["category_external_id"])
    row = _upsert(
        db,
        POSProduct,
        raw,
        {
            "group_id": None if group is None else int(group.id),
            "category_id": None if category is None else int(category.id),
            "name": value["name"],
            "code": value["code"],
            "barcode": value["barcode"],
            "product_type": value["product_type"],
            "unit": value["unit"],
            "is_active": value["is_active"],
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _apply_variant(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    del venue_id
    product = _by_external_id(db, POSProduct, raw, value["product_external_id"], required=True)
    row = _upsert(
        db,
        POSProductVariant,
        raw,
        {
            "product_id": int(product.id),
            "name": value["name"],
            "code": value["code"],
            "option_signature_json": {"size_id": value["size_external_id"]},
            "is_active": value["is_active"],
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _apply_modifier_group(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    del venue_id
    row = _upsert(db, POSModifierGroup, raw, value)
    _finalize_raw(db, raw, row)
    return row


def _apply_modifier(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    del venue_id
    group = _by_external_id(db, POSModifierGroup, raw, value["modifier_group_external_id"])
    row = _upsert(
        db,
        POSModifier,
        raw,
        {
            "modifier_group_id": None if group is None else int(group.id),
            "product_id": None,
            "name": value["name"],
            "code": value["code"],
            "price_delta": value["price_delta"],
            "is_active": value["is_active"],
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _apply_modifier_rule(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    del venue_id
    product = _by_external_id(db, POSProduct, raw, value["product_external_id"], required=True)
    modifier = _by_external_id(db, POSModifier, raw, value["modifier_external_id"], required=True)
    group = _by_external_id(db, POSModifierGroup, raw, value["modifier_group_external_id"])
    if group is not None and modifier.modifier_group_id is None:
        modifier.modifier_group_id = int(group.id)
        db.add(modifier)
    row = _upsert(
        db,
        POSProductModifierRule,
        raw,
        {
            "product_id": int(product.id),
            "variant_id": None,
            "modifier_group_id": None if group is None else int(group.id),
            "modifier_id": int(modifier.id),
            "min_amount": value["min_amount"],
            "max_amount": value["max_amount"],
            "default_amount": value["default_amount"],
            "free_amount": value["free_amount"],
            "is_required": value["is_required"],
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _apply_payment_type(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    del venue_id
    row = _upsert(
        db,
        POSPaymentType,
        raw,
        {
            **value,
            "canonical_hint": None,
            "last_seen_at": _aware(raw.received_at),
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _apply_section(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    row = _upsert(db, POSRestaurantSection, raw, {**value, "venue_id": int(venue_id)})
    _finalize_raw(db, raw, row)
    return row


def _apply_table(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    section = _by_external_id(db, POSRestaurantSection, raw, value["section_external_id"], required=True)
    row = _upsert(
        db,
        POSTable,
        raw,
        {
            "venue_id": int(venue_id),
            "restaurant_section_id": int(section.id),
            "number": value["number"],
            "name": value["name"],
            "capacity": value["capacity"],
            "is_active": value["is_active"],
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _apply_stop_list_entry(db: Session, raw: IntegrationRawObject, value: Mapping[str, Any], *, venue_id: int):
    terminal_group = _by_external_id(
        db,
        POSTerminalGroup,
        raw,
        value["terminal_group_external_id"],
        required=True,
    )
    product = _by_external_id(db, POSProduct, raw, value["product_external_id"], required=True)
    variant_external_id = (
        f"{value['product_external_id']}:{value['size_external_id']}" if value["size_external_id"] else None
    )
    variant = _by_external_id(db, POSProductVariant, raw, variant_external_id)
    row = _upsert(
        db,
        POSStopListEntry,
        raw,
        {
            "venue_id": int(venue_id),
            "terminal_group_id": int(terminal_group.id),
            "product_id": int(product.id),
            "variant_id": None if variant is None else int(variant.id),
            "modifier_id": None,
            "balance": value["balance"],
            "started_at": _datetime(value["started_at"], fallback=_aware(raw.received_at)),
            "ended_at": (
                None if value["ended_at"] is None else _datetime(value["ended_at"], fallback=_aware(raw.received_at))
            ),
        },
    )
    _finalize_raw(db, raw, row)
    return row


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


_NORMALIZERS = {
    "IIKO_ORGANIZATION": _normalize_organization,
    "IIKO_TERMINAL_GROUP": _normalize_terminal_group,
    "IIKO_PRODUCT_GROUP": _normalize_product_group,
    "IIKO_PRODUCT": _normalize_product,
    "IIKO_PRODUCT_VARIANT": _normalize_variant,
    "IIKO_MODIFIER_GROUP": _normalize_modifier_group,
    "IIKO_MODIFIER": _normalize_modifier,
    "IIKO_PRODUCT_MODIFIER_RULE": _normalize_modifier_rule,
    "IIKO_PAYMENT_TYPE": _normalize_payment_type,
    "IIKO_RESTAURANT_SECTION": _normalize_section,
    "IIKO_TABLE": _normalize_table,
    "IIKO_STOP_LIST_ENTRY": _normalize_stop_list_entry,
}

_APPLIERS = {
    "IIKO_ORGANIZATION": _apply_organization,
    "IIKO_TERMINAL_GROUP": _apply_terminal_group,
    "IIKO_PRODUCT_GROUP": _apply_product_group,
    "IIKO_PRODUCT": _apply_product,
    "IIKO_PRODUCT_VARIANT": _apply_variant,
    "IIKO_MODIFIER_GROUP": _apply_modifier_group,
    "IIKO_MODIFIER": _apply_modifier,
    "IIKO_PRODUCT_MODIFIER_RULE": _apply_modifier_rule,
    "IIKO_PAYMENT_TYPE": _apply_payment_type,
    "IIKO_RESTAURANT_SECTION": _apply_section,
    "IIKO_TABLE": _apply_table,
    "IIKO_STOP_LIST_ENTRY": _apply_stop_list_entry,
}

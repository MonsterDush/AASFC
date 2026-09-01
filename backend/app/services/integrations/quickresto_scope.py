from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_external_venue import QuickRestoExternalVenue
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_sale_place_scope import QuickRestoSalePlaceScope
from app.models.quickresto_scope_audit import QuickRestoScopeAudit
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_store_scope import QuickRestoStoreScope
from app.services.integrations.quickresto import QUICKRESTO_OBJECT_TYPES, QuickRestoClient


LEGACY_SCOPE_SELECTION_REQUIRED_MESSAGE = (
    "После обновления QuickResto требуется выбрать конкретное заведение и места реализации. Автос"
    "инхронизация приостановлена до сохранения области импорта."
)


class QuickRestoScopeError(ValueError):
    """Raised when a QuickResto venue scope is incomplete or invalid."""


class QuickRestoScopeConflictError(QuickRestoScopeError):
    """Raised when changing a scope could reinterpret already imported shifts."""


class QuickRestoLocationScopeError(QuickRestoScopeError):
    def __init__(self, *, error_code: str, user_summary: str, technical_summary: str, details: dict[str, Any]):
        super().__init__(technical_summary)
        self.error_code = str(error_code)
        self.user_summary = str(user_summary)
        self.details = dict(details)


@dataclass(frozen=True)
class QuickRestoShiftScopeDecision:
    action: str
    external_venue_id: int | None
    sale_place_id: int | None
    error: QuickRestoLocationScopeError | None = None


@dataclass(frozen=True)
class QuickRestoScopeIndex:
    external_venue_id: int
    sale_places: dict[int, QuickRestoSalePlaceScope]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _positive_int(value: Any) -> int | None:
    try:
        result = int(value or 0)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _bounded_title(value: Any, *, fallback: str, limit: int = 160) -> str:
    normalized = " ".join(str(value or "").split()).strip()
    return (normalized or fallback)[:limit]


def _nested_id(row: Mapping[str, Any], field: str) -> int | None:
    value = row.get(field)
    if isinstance(value, Mapping):
        return _positive_int(value.get("id"))
    return _positive_int(value)


def load_quickresto_scope_index(db: Session, *, connection: QuickRestoConnection) -> QuickRestoScopeIndex:
    ensure_quickresto_scope_ready(connection)
    rows = db.execute(
        select(QuickRestoSalePlaceScope).where(
            QuickRestoSalePlaceScope.connection_id == int(connection.id),
            QuickRestoSalePlaceScope.is_available.is_(True),
        )
    ).scalars()
    return QuickRestoScopeIndex(
        external_venue_id=int(connection.external_venue_id),
        sale_places={int(row.external_id): row for row in rows},
    )


def evaluate_quickresto_shift_scope(
    shift: Mapping[str, Any],
    *,
    scope: QuickRestoScopeIndex,
) -> QuickRestoShiftScopeDecision:
    direct_venue_id = _nested_id(shift, "tableScheme")
    sale_place_id = _nested_id(shift, "salePlace")
    opening_sale_place_id = _nested_id(shift, "createTerminalSalePlace")
    details = {
        "selected_external_venue_id": scope.external_venue_id,
        "shift_external_venue_id": direct_venue_id,
        "sale_place_id": sale_place_id,
        "opening_sale_place_id": opening_sale_place_id,
    }
    if sale_place_id and opening_sale_place_id and sale_place_id != opening_sale_place_id:
        return QuickRestoShiftScopeDecision(
            action="ISSUE",
            external_venue_id=direct_venue_id,
            sale_place_id=sale_place_id,
            error=QuickRestoLocationScopeError(
                error_code="LOCATION_SCOPE_CONFLICT",
                user_summary="В смене QuickResto указаны противоречащие друг другу места реализации.",
                technical_summary="QuickResto shift salePlace conflicts with createTerminalSalePlace",
                details=details,
            ),
        )
    effective_sale_place_id = sale_place_id or opening_sale_place_id
    sale_place = scope.sale_places.get(effective_sale_place_id or 0)
    sale_place_venue_id = int(sale_place.external_venue_id) if sale_place and sale_place.external_venue_id else None
    details["resolved_sale_place_venue_id"] = sale_place_venue_id

    if direct_venue_id and sale_place_venue_id and direct_venue_id != sale_place_venue_id:
        return QuickRestoShiftScopeDecision(
            action="ISSUE",
            external_venue_id=direct_venue_id,
            sale_place_id=effective_sale_place_id,
            error=QuickRestoLocationScopeError(
                error_code="LOCATION_SCOPE_CONFLICT",
                user_summary="Заведение и место реализации в смене QuickResto не совпадают.",
                technical_summary="QuickResto shift tableScheme conflicts with salePlace venue",
                details=details,
            ),
        )
    if direct_venue_id and direct_venue_id != scope.external_venue_id:
        if sale_place and sale_place.is_selected:
            return QuickRestoShiftScopeDecision(
                action="ISSUE",
                external_venue_id=direct_venue_id,
                sale_place_id=effective_sale_place_id,
                error=QuickRestoLocationScopeError(
                    error_code="LOCATION_SCOPE_CONFLICT",
                    user_summary="Смена ссылается на другое заведение QuickResto, но на выбранное место реализации.",
                    technical_summary="QuickResto shift venue is outside scope while salePlace is selected",
                    details=details,
                ),
            )
        return QuickRestoShiftScopeDecision(
            action="SKIP_OTHER_VENUE",
            external_venue_id=direct_venue_id,
            sale_place_id=effective_sale_place_id,
        )

    if effective_sale_place_id is None:
        return QuickRestoShiftScopeDecision(
            action="ISSUE",
            external_venue_id=direct_venue_id,
            sale_place_id=None,
            error=QuickRestoLocationScopeError(
                error_code="LOCATION_UNRESOLVED",
                user_summary="Не удалось определить место реализации кассовой смены QuickResto.",
                technical_summary="QuickResto shift has no salePlace reference",
                details=details,
            ),
        )
    if sale_place is None or sale_place_venue_id is None:
        return QuickRestoShiftScopeDecision(
            action="ISSUE",
            external_venue_id=direct_venue_id,
            sale_place_id=effective_sale_place_id,
            error=QuickRestoLocationScopeError(
                error_code="LOCATION_SCOPE_CHANGED",
                user_summary="В QuickResto обнаружено новое или неизвестное место реализации.",
                technical_summary="QuickResto shift salePlace is absent from the confirmed catalog",
                details=details,
            ),
        )
    if sale_place_venue_id != scope.external_venue_id:
        return QuickRestoShiftScopeDecision(
            action="SKIP_OTHER_VENUE",
            external_venue_id=direct_venue_id or sale_place_venue_id,
            sale_place_id=effective_sale_place_id,
        )
    if sale_place.is_selected:
        return QuickRestoShiftScopeDecision(
            action="IMPORT",
            external_venue_id=direct_venue_id or sale_place_venue_id,
            sale_place_id=effective_sale_place_id,
        )
    if sale_place.is_confirmed:
        return QuickRestoShiftScopeDecision(
            action="SKIP_UNSELECTED_SALE_PLACE",
            external_venue_id=direct_venue_id or sale_place_venue_id,
            sale_place_id=effective_sale_place_id,
        )
    return QuickRestoShiftScopeDecision(
        action="ISSUE",
        external_venue_id=direct_venue_id or sale_place_venue_id,
        sale_place_id=effective_sale_place_id,
        error=QuickRestoLocationScopeError(
            error_code="LOCATION_SCOPE_CHANGED",
            user_summary="В выбранном заведении QuickResto появилось новое место реализации.",
            technical_summary="QuickResto shift salePlace has not been confirmed for this scope",
            details=details,
        ),
    )


def _address_label(row: Mapping[str, Any]) -> str | None:
    address = row.get("address")
    if not isinstance(address, Mapping):
        return None
    for field in ("fullAddress", "formatted", "value", "itemTitle", "title"):
        text = _bounded_title(address.get(field), fallback="", limit=500)
        if text:
            return text
    parts: list[str] = []
    for field in ("city", "street", "house", "building"):
        value = address.get(field)
        if isinstance(value, Mapping):
            value = value.get("name") or value.get("title") or value.get("itemTitle")
        text = _bounded_title(value, fallback="", limit=160)
        if text:
            parts.append(text)
    return ", ".join(parts)[:500] or None


def _object_rows(client: QuickRestoClient, key: str) -> list[dict[str, Any]]:
    module_name, class_name = QUICKRESTO_OBJECT_TYPES[key]
    return client.list_all_objects(module_name=module_name, class_name=class_name)


def _object_detail(client: QuickRestoClient, key: str, object_id: int) -> dict[str, Any]:
    module_name, class_name = QUICKRESTO_OBJECT_TYPES[key]
    return client.read_object(module_name=module_name, class_name=class_name, object_id=object_id)


def _rows_with_details(
    client: QuickRestoClient,
    key: str,
    *,
    nested_fields: Iterable[str],
) -> list[dict[str, Any]]:
    fields = tuple(nested_fields)
    output: list[dict[str, Any]] = []
    for row in _object_rows(client, key):
        object_id = _positive_int(row.get("id"))
        if object_id is None:
            continue
        if any(field not in row for field in fields):
            detail = _object_detail(client, key, object_id)
            output.append(detail if isinstance(detail, dict) else row)
        else:
            output.append(row)
    return output


def selected_store_ids(db: Session, *, connection_id: int) -> set[int]:
    return {
        int(value)
        for value in db.execute(
            select(QuickRestoStoreScope.external_id).where(
                QuickRestoStoreScope.connection_id == int(connection_id),
                QuickRestoStoreScope.is_selected.is_(True),
                QuickRestoStoreScope.is_available.is_(True),
            )
        ).scalars()
    }


def selected_sale_place_ids(db: Session, *, connection_id: int) -> set[int]:
    return {
        int(value)
        for value in db.execute(
            select(QuickRestoSalePlaceScope.external_id).where(
                QuickRestoSalePlaceScope.connection_id == int(connection_id),
                QuickRestoSalePlaceScope.is_selected.is_(True),
                QuickRestoSalePlaceScope.is_available.is_(True),
            )
        ).scalars()
    }


def payment_type_is_applicable(*, allowed_sale_place_ids: Iterable[int], selected_ids: set[int]) -> bool:
    allowed = {int(value) for value in allowed_sale_place_ids if _positive_int(value) is not None}
    return bool(selected_ids) and (not allowed or bool(allowed & selected_ids))


def recompute_payment_applicability(db: Session, *, connection_id: int) -> None:
    selected_ids = selected_sale_place_ids(db, connection_id=connection_id)
    rows = db.execute(
        select(QuickRestoPaymentMapping).where(QuickRestoPaymentMapping.connection_id == int(connection_id))
    ).scalars()
    for row in rows:
        row.is_applicable = bool(
            row.is_available
            and payment_type_is_applicable(
                allowed_sale_place_ids=row.allowed_sale_place_ids_json or (),
                selected_ids=selected_ids,
            )
        )


def refresh_quickresto_catalog(
    db: Session,
    *,
    connection: QuickRestoConnection,
    client: QuickRestoClient,
) -> dict[str, Any]:
    now = _utcnow()
    venue_rows = _rows_with_details(client, "venues", nested_fields=("address",))
    sale_place_rows = _rows_with_details(
        client,
        "sale_places",
        nested_fields=("tableScheme", "defaultCookingPlace"),
    )
    cooking_place_rows = _rows_with_details(client, "cooking_places", nested_fields=("store",))
    store_rows = _object_rows(client, "stores")
    payment_rows = _rows_with_details(client, "payment_types", nested_fields=("allowedSalePlacesWeb",))

    existing_venues = {
        int(row.external_id): row
        for row in db.execute(
            select(QuickRestoExternalVenue).where(QuickRestoExternalVenue.connection_id == connection.id)
        ).scalars()
    }
    existing_sale_places = {
        int(row.external_id): row
        for row in db.execute(
            select(QuickRestoSalePlaceScope).where(QuickRestoSalePlaceScope.connection_id == connection.id)
        ).scalars()
    }
    existing_stores = {
        int(row.external_id): row
        for row in db.execute(
            select(QuickRestoStoreScope).where(QuickRestoStoreScope.connection_id == connection.id)
        ).scalars()
    }
    existing_payments = {
        int(row.external_id): row
        for row in db.execute(
            select(QuickRestoPaymentMapping).where(QuickRestoPaymentMapping.connection_id == connection.id)
        ).scalars()
    }
    for row in (*existing_venues.values(), *existing_sale_places.values(), *existing_stores.values()):
        row.is_available = False
    for row in existing_payments.values():
        row.is_available = False
        row.is_applicable = False

    for source in venue_rows:
        external_id = _positive_int(source.get("id"))
        if external_id is None:
            continue
        row = existing_venues.get(external_id)
        if row is None:
            row = QuickRestoExternalVenue(connection_id=connection.id, external_id=external_id)
            db.add(row)
            existing_venues[external_id] = row
        row.external_name = _bounded_title(
            source.get("name") or source.get("itemTitle"),
            fallback=f"Заведение #{external_id}",
        )
        row.address_label = _address_label(source)
        row.external_version = _positive_int(source.get("version"))
        row.is_available = True
        row.last_seen_at = now

    cooking_to_store: dict[int, int] = {}
    for source in cooking_place_rows:
        cooking_id = _positive_int(source.get("id"))
        store_id = _nested_id(source, "store")
        if cooking_id is not None and store_id is not None:
            cooking_to_store[cooking_id] = store_id

    store_sale_places: dict[int, set[int]] = defaultdict(set)
    store_cooking_places: dict[int, set[int]] = defaultdict(set)
    for source in sale_place_rows:
        external_id = _positive_int(source.get("id"))
        if external_id is None:
            continue
        venue_id = _nested_id(source, "tableScheme")
        cooking_id = _nested_id(source, "defaultCookingPlace")
        row = existing_sale_places.get(external_id)
        if row is None:
            row = QuickRestoSalePlaceScope(connection_id=connection.id, external_id=external_id)
            # On the very first setup show discovered points as preselected.
            # Once a scope has ever been confirmed, new points stay unselected
            # until the owner explicitly reviews them.
            row.is_selected = bool(connection.external_venue_id is None and connection.scope_status == "NEEDS_SELECTION")
            db.add(row)
            existing_sale_places[external_id] = row
        row.external_name = _bounded_title(
            source.get("title") or source.get("itemTitle"),
            fallback=f"Место реализации #{external_id}",
        )
        row.external_venue_id = venue_id
        row.default_cooking_place_id = cooking_id
        row.is_available = True
        row.last_seen_at = now
        store_id = cooking_to_store.get(cooking_id or 0)
        if store_id is not None:
            store_sale_places[store_id].add(external_id)
            if cooking_id is not None:
                store_cooking_places[store_id].add(cooking_id)

    store_sources = {
        int(source_id): source for source in store_rows if (source_id := _positive_int(source.get("id"))) is not None
    }
    for external_id in sorted(set(store_sources) | set(store_sale_places)):
        source = store_sources.get(external_id, {})
        row = existing_stores.get(external_id)
        if row is None:
            row = QuickRestoStoreScope(connection_id=connection.id, external_id=external_id)
            db.add(row)
            existing_stores[external_id] = row
        sale_place_ids = sorted(store_sale_places.get(external_id, set()))
        cooking_place_ids = sorted(store_cooking_places.get(external_id, set()))
        row.external_name = _bounded_title(
            source.get("title") or source.get("itemTitle"),
            fallback=f"Склад #{external_id}",
        )
        row.source_sale_place_ids_json = sale_place_ids
        row.source_cooking_place_ids_json = cooking_place_ids
        row.discovered_via_sale_place_id = sale_place_ids[0] if sale_place_ids else None
        row.discovered_via_cooking_place_id = cooking_place_ids[0] if cooking_place_ids else None
        row.is_available = True
        row.last_seen_at = now

    for source in payment_rows:
        external_id = _positive_int(source.get("id"))
        if external_id is None:
            continue
        operation_type = str(source.get("operationType") or "").strip().lower()
        allowed_ids = sorted(
            {
                allowed_id
                for item in (source.get("allowedSalePlacesWeb") or ())
                if isinstance(item, Mapping) and (allowed_id := _positive_int(item.get("id"))) is not None
            }
        )
        row = existing_payments.get(external_id)
        if row is None:
            row = QuickRestoPaymentMapping(
                connection_id=connection.id,
                external_id=external_id,
                payment_method_id=None,
            )
            db.add(row)
            existing_payments[external_id] = row
        row.external_name = _bounded_title(
            source.get("name") or source.get("itemTitle"),
            fallback=f"Тип оплаты #{external_id}",
        )
        row.operation_type = operation_type
        row.payment_mechanism = str(source.get("paymentMechanismWeb") or "").strip().lower() or None
        row.excluded_from_revenue = operation_type == "writeoff"
        if row.excluded_from_revenue:
            row.payment_method_id = None
        row.allowed_sale_place_ids_json = allowed_ids
        row.is_available = True
        row.last_seen_at = now
        row.updated_at = now

    db.flush()
    recompute_payment_applicability(db, connection_id=int(connection.id))
    selected_venue_available = bool(
        connection.external_venue_id
        and existing_venues.get(int(connection.external_venue_id))
        and existing_venues[int(connection.external_venue_id)].is_available
    )
    selected_places_available = all(row.is_available for row in existing_sale_places.values() if row.is_selected)
    if connection.scope_status == "READY" and (not selected_venue_available or not selected_places_available):
        connection.scope_status = "STALE"
    db.flush()
    return {
        "venues_seen": sum(int(row.is_available) for row in existing_venues.values()),
        "sale_places_seen": sum(int(row.is_available) for row in existing_sale_places.values()),
        "stores_seen": sum(int(row.is_available) for row in existing_stores.values()),
        "payment_types_seen": sum(int(row.is_available) for row in existing_payments.values()),
        "scope_status": connection.scope_status,
    }


def apply_quickresto_scope(
    db: Session,
    *,
    connection: QuickRestoConnection,
    external_venue_id: int,
    sale_place_ids: Iterable[int],
    store_ids: Iterable[int],
    actor_user_id: int | None = None,
) -> dict[str, Any]:
    venue_id = int(external_venue_id)
    selected_sale_ids = {int(value) for value in sale_place_ids}
    selected_store_ids = {int(value) for value in store_ids}
    if venue_id <= 0:
        raise QuickRestoScopeError("Выберите заведение QuickResto")
    if not selected_sale_ids:
        raise QuickRestoScopeError("Выберите хотя бы одно место реализации QuickResto")

    venue = db.execute(
        select(QuickRestoExternalVenue).where(
            QuickRestoExternalVenue.connection_id == connection.id,
            QuickRestoExternalVenue.external_id == venue_id,
            QuickRestoExternalVenue.is_available.is_(True),
        )
    ).scalar_one_or_none()
    if venue is None:
        raise QuickRestoScopeError("Выбранное заведение QuickResto отсутствует в актуальном каталоге")
    duplicate = db.execute(
        select(QuickRestoConnection.id).where(
            QuickRestoConnection.id != connection.id,
            QuickRestoConnection.cloud == connection.cloud,
            QuickRestoConnection.external_venue_id == venue_id,
        )
    ).scalar_one_or_none()
    if duplicate is not None:
        raise QuickRestoScopeConflictError("Это заведение QuickResto уже подключено к другому заведению Axelio")

    sale_places = list(
        db.execute(
            select(QuickRestoSalePlaceScope).where(QuickRestoSalePlaceScope.connection_id == connection.id)
        ).scalars()
    )
    selected_sale_places = {row.external_id: row for row in sale_places if row.external_id in selected_sale_ids}
    if set(selected_sale_places) != selected_sale_ids:
        raise QuickRestoScopeError("Одно из мест реализации отсутствует в актуальном каталоге QuickResto")
    if any(not row.is_available or row.external_venue_id != venue_id for row in selected_sale_places.values()):
        raise QuickRestoScopeError("Место реализации не относится к выбранному заведению QuickResto")

    stores = list(
        db.execute(select(QuickRestoStoreScope).where(QuickRestoStoreScope.connection_id == connection.id)).scalars()
    )
    selected_stores = {row.external_id: row for row in stores if row.external_id in selected_store_ids}
    if set(selected_stores) != selected_store_ids or any(not row.is_available for row in selected_stores.values()):
        raise QuickRestoScopeError("Один из складов отсутствует в актуальном каталоге QuickResto")
    for row in selected_stores.values():
        source_sale_ids = {int(value) for value in row.source_sale_place_ids_json or ()}
        if source_sale_ids and not source_sale_ids.intersection(selected_sale_ids):
            raise QuickRestoScopeError("Склад не связан с выбранными местами реализации QuickResto")

    previous_venue_id = connection.external_venue_id
    previous_sale_ids = {int(row.external_id) for row in sale_places if row.is_selected}
    previous_store_ids = {int(row.external_id) for row in stores if row.is_selected}
    scope_identity_changed = bool(
        previous_venue_id is not None and (int(previous_venue_id) != venue_id or previous_sale_ids != selected_sale_ids)
    )
    if scope_identity_changed:
        imported_count = int(
            db.execute(
                select(func.count(QuickRestoShiftImport.id)).where(QuickRestoShiftImport.connection_id == connection.id)
            ).scalar_one()
        )
        if imported_count:
            raise QuickRestoScopeConflictError(
                "Нельзя менять заведение или места реализации QuickResto после импорта смен; "
                "требуется отдельное переподключение"
            )
    changed = (
        previous_venue_id != venue_id
        or previous_sale_ids != selected_sale_ids
        or previous_store_ids != selected_store_ids
        or connection.scope_status != "READY"
    )
    confirmed_at = _utcnow()
    for row in sale_places:
        row.is_selected = bool(row.is_available and row.external_id in selected_sale_ids)
        if row.is_available and row.external_venue_id == venue_id:
            row.is_confirmed = True
            row.confirmed_by_user_id = int(actor_user_id) if actor_user_id is not None else None
            row.confirmed_at = confirmed_at
    for row in stores:
        row.is_selected = bool(row.is_available and row.external_id in selected_store_ids)
    connection.external_venue_id = venue_id
    connection.external_venue_name = venue.external_name
    connection.external_venue_version = venue.external_version
    connection.scope_status = "READY"
    connection.scope_confirmed_at = confirmed_at
    connection.scope_confirmed_by_user_id = int(actor_user_id) if actor_user_id is not None else None
    if connection.last_sync_error == LEGACY_SCOPE_SELECTION_REQUIRED_MESSAGE:
        connection.last_sync_error = None
    if changed and previous_venue_id is not None:
        connection.scope_generation = int(connection.scope_generation or 1) + 1
    if changed:
        connection.incremental_cursor_closed_at = None
        connection.last_full_reconciliation_at = None
        db.add(
            QuickRestoScopeAudit(
                connection_id=int(connection.id),
                actor_user_id=int(actor_user_id) if actor_user_id is not None else None,
                scope_generation=int(connection.scope_generation or 1),
                previous_scope_json={
                    "external_venue_id": int(previous_venue_id) if previous_venue_id is not None else None,
                    "sale_place_ids": sorted(previous_sale_ids),
                    "store_ids": sorted(previous_store_ids),
                },
                current_scope_json={
                    "external_venue_id": venue_id,
                    "sale_place_ids": sorted(selected_sale_ids),
                    "store_ids": sorted(selected_store_ids),
                },
                changes_json={
                    "sale_places_added": sorted(selected_sale_ids - previous_sale_ids),
                    "sale_places_removed": sorted(previous_sale_ids - selected_sale_ids),
                    "stores_added": sorted(selected_store_ids - previous_store_ids),
                    "stores_removed": sorted(previous_store_ids - selected_store_ids),
                },
                changed_at=confirmed_at,
            )
        )
    recompute_payment_applicability(db, connection_id=int(connection.id))
    db.flush()
    return {
        "external_venue_id": venue_id,
        "external_venue_name": venue.external_name,
        "sale_place_ids": sorted(selected_sale_ids),
        "store_ids": sorted(selected_store_ids),
        "scope_status": connection.scope_status,
        "scope_generation": int(connection.scope_generation or 1),
        "changed": changed,
    }


def serialize_quickresto_catalog(db: Session, *, connection: QuickRestoConnection) -> dict[str, Any]:
    venues = list(
        db.execute(
            select(QuickRestoExternalVenue)
            .where(QuickRestoExternalVenue.connection_id == connection.id)
            .order_by(QuickRestoExternalVenue.external_name, QuickRestoExternalVenue.external_id)
        ).scalars()
    )
    sale_places = list(
        db.execute(
            select(QuickRestoSalePlaceScope)
            .where(QuickRestoSalePlaceScope.connection_id == connection.id)
            .order_by(QuickRestoSalePlaceScope.external_name, QuickRestoSalePlaceScope.external_id)
        ).scalars()
    )
    stores = list(
        db.execute(
            select(QuickRestoStoreScope)
            .where(QuickRestoStoreScope.connection_id == connection.id)
            .order_by(QuickRestoStoreScope.external_name, QuickRestoStoreScope.external_id)
        ).scalars()
    )
    payments = list(
        db.execute(
            select(QuickRestoPaymentMapping)
            .where(QuickRestoPaymentMapping.connection_id == connection.id)
            .order_by(QuickRestoPaymentMapping.external_name, QuickRestoPaymentMapping.external_id)
        ).scalars()
    )
    return {
        "scope_status": str(connection.scope_status or "NEEDS_SELECTION"),
        "scope_generation": int(connection.scope_generation or 1),
        "selected_external_venue_id": connection.external_venue_id,
        "venues": [
            {
                "external_id": int(row.external_id),
                "external_name": row.external_name,
                "address": row.address_label,
                "is_available": bool(row.is_available),
                "is_selected": int(row.external_id) == int(connection.external_venue_id or 0),
            }
            for row in venues
        ],
        "sale_places": [
            {
                "external_id": int(row.external_id),
                "external_name": row.external_name,
                "external_venue_id": row.external_venue_id,
                "default_cooking_place_id": row.default_cooking_place_id,
                "is_available": bool(row.is_available),
                "is_selected": bool(row.is_selected),
                "is_confirmed": bool(row.is_confirmed),
                "confirmed_by_user_id": row.confirmed_by_user_id,
                "confirmed_at": row.confirmed_at.isoformat() if row.confirmed_at else None,
            }
            for row in sale_places
        ],
        "stores": [
            {
                "external_id": int(row.external_id),
                "external_name": row.external_name,
                "source_sale_place_ids": sorted(int(value) for value in row.source_sale_place_ids_json or ()),
                "source_cooking_place_ids": sorted(int(value) for value in row.source_cooking_place_ids_json or ()),
                "is_available": bool(row.is_available),
                "is_selected": bool(row.is_selected),
            }
            for row in stores
        ],
        "payment_types": [
            {
                "external_id": int(row.external_id),
                "external_name": row.external_name,
                "operation_type": row.operation_type,
                "payment_mechanism": row.payment_mechanism,
                "allowed_sale_place_ids": sorted(int(value) for value in row.allowed_sale_place_ids_json or ()),
                "is_available": bool(row.is_available),
                "is_applicable": bool(row.is_applicable),
                "payment_method_id": row.payment_method_id,
                "excluded_from_revenue": bool(row.excluded_from_revenue),
            }
            for row in payments
        ],
    }


def ensure_quickresto_scope_ready(connection: QuickRestoConnection) -> None:
    if str(connection.scope_status or "NEEDS_SELECTION").upper() != "READY" or not connection.external_venue_id:
        raise QuickRestoScopeError("Сначала выберите заведение и места реализации QuickResto")

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from app.integrations.base.capabilities import Capability, CapabilityProbe, CapabilityState
from app.integrations.base.credentials import ProviderCredentials
from app.integrations.base.dto import ProviderRecord
from app.integrations.base.errors import (
    ProviderAuthenticationError,
    ProviderCapabilityError,
    ProviderRateLimitError,
    ProviderTemporaryError,
    ProviderValidationError,
)
from app.integrations.base.provider import ProviderHealth, ProviderLimits, ProviderScope
from app.integrations.registry import ProviderRegistry, provider_registry
from app.services.integrations.quickresto import (
    QUICKRESTO_OBJECT_TYPES,
    QuickRestoAuthenticationError,
    QuickRestoClient,
    QuickRestoConfig,
    QuickRestoError,
    QuickRestoHTTPError,
)
from app.services.integrations.quickresto_discovery import (
    QuickRestoDiscoveryReport,
    discover_quickresto_capabilities,
)
from app.services.integrations.quickresto_normalize import QuickRestoDataError, business_date_for_shift


_UNAVAILABLE_CAPABILITIES = {
    Capability.EMPLOYEES,
    Capability.EMPLOYEE_ATTENDANCE,
    Capability.EMPLOYEE_ROLES,
    Capability.RECIPES,
    Capability.SUPPLIERS,
    Capability.PURCHASES,
    Capability.WRITEOFFS,
    Capability.STOCK_BALANCES,
    Capability.STOCK_MOVEMENTS,
    Capability.INVENTORY,
}

_DOCUMENT_CAPABILITIES = {
    "inventory_documents": Capability.INVENTORY,
    "incoming_invoices": Capability.PURCHASES,
    "discard_invoices": Capability.WRITEOFFS,
}

_STOCK_DOCUMENT_TYPES = (
    "inventory_documents",
    "incoming_invoices",
    "outgoing_invoices",
    "discard_invoices",
    "exchange_invoices",
    "cooking_invoices",
    "decomposition_invoices",
    "processing_invoices",
)


class QuickRestoProviderAdapter:
    provider_code = "QUICKRESTO"

    def __init__(self, client: QuickRestoClient, *, business_day_cutoff_hour: int = 0) -> None:
        self.client = client
        self.business_day_cutoff_hour = int(business_day_cutoff_hour)
        self._successful_probes: set[Capability] = set()
        self._last_probe_at: datetime | None = None
        self._server_filter_verified = False
        self._extended_capability_probes: dict[Capability, CapabilityProbe] = {}

    @classmethod
    def from_credentials(cls, credentials: ProviderCredentials) -> QuickRestoProviderAdapter:
        timeout = float(credentials.values.get("timeout_seconds") or 20)
        return cls(
            QuickRestoClient(
                QuickRestoConfig(
                    cloud=credentials.require("cloud"),
                    login=credentials.require("login"),
                    password=credentials.require("password"),
                    timeout_seconds=timeout,
                )
            ),
            business_day_cutoff_hour=int(credentials.values.get("business_day_cutoff_hour") or 0),
        )

    def close(self) -> None:
        self.client.close()

    def health_check(self) -> ProviderHealth:
        checked_at = datetime.now(timezone.utc)
        try:
            self._probe_object_type("venues")
        except Exception as exc:
            translated = self._translate_error(exc)
            return ProviderHealth(healthy=False, checked_at=checked_at, message=str(translated))
        return ProviderHealth(healthy=True, checked_at=checked_at, message="QuickResto read-only API responded")

    def verify_credentials(self) -> ProviderHealth:
        return self.health_check()

    def probe_extended_capabilities(self, *, sample_limit: int = 5) -> QuickRestoDiscoveryReport:
        report = discover_quickresto_capabilities(self.client, sample_limit=sample_limit)
        self._extended_capability_probes = dict(report.capabilities)
        return report

    def get_capabilities(self) -> Mapping[Capability, CapabilityProbe]:
        checked_at = datetime.now(timezone.utc)
        direct = {
            Capability.EXTERNAL_VENUES: "venues",
            Capability.SALE_PLACES: "sale_places",
            Capability.STORES: "stores",
            Capability.BUSINESS_SHIFTS: "shifts",
            Capability.ORDERS: "orders",
            Capability.PAYMENTS: "payment_types",
            Capability.PRODUCTS: "dishes",
            Capability.PRODUCT_GROUPS: "dish_categories",
        }
        results: dict[Capability, CapabilityProbe] = {}
        for capability, object_type in direct.items():
            try:
                self._probe_object_type(object_type)
            except Exception as exc:
                translated = self._translate_error(exc)
                results[capability] = CapabilityProbe(
                    capability=capability,
                    state=CapabilityState.DEGRADED,
                    checked_at=checked_at,
                    last_error_code=translated.code.value,
                    evidence_summary=str(translated),
                )
            else:
                results[capability] = CapabilityProbe(
                    capability=capability,
                    state=CapabilityState.SUPPORTED,
                    checked_at=checked_at,
                    last_success_at=checked_at,
                    evidence_summary=f"QuickResto {object_type} endpoint returned a valid list",
                )
        derived_from_orders = {
            Capability.SALES,
            Capability.ORDER_ITEMS,
            Capability.RETURNS,
            Capability.DISCOUNTS,
            Capability.ORDER_EVENTS,
            Capability.GUEST_COUNT,
        }
        orders_available = results[Capability.ORDERS].state is CapabilityState.SUPPORTED
        for capability in derived_from_orders:
            results[capability] = CapabilityProbe(
                capability=capability,
                state=CapabilityState.DERIVED if orders_available else CapabilityState.DEGRADED,
                checked_at=checked_at,
                last_success_at=checked_at if orders_available else None,
                evidence_summary="Derived from probed QuickResto OrderInfo records",
            )
        for capability, source_capability, evidence in (
            (Capability.TERMINALS, Capability.SALE_PLACES, "Derived from probed QuickResto sale places"),
            (Capability.WAREHOUSES, Capability.STORES, "Derived from probed QuickResto stores"),
        ):
            available = results[source_capability].state is CapabilityState.SUPPORTED
            results[capability] = CapabilityProbe(
                capability=capability,
                state=CapabilityState.DERIVED if available else CapabilityState.DEGRADED,
                checked_at=checked_at,
                last_success_at=checked_at if available else None,
                evidence_summary=evidence,
            )
        results[Capability.PAGINATION] = CapabilityProbe(
            capability=Capability.PAGINATION,
            state=CapabilityState.SUPPORTED if self._successful_probes else CapabilityState.UNKNOWN,
            checked_at=checked_at,
            last_success_at=checked_at if self._successful_probes else None,
            evidence_summary="QuickResto list probe used limit and offset" if self._successful_probes else None,
        )
        diagnostics = self.client.fallback_diagnostics()
        filter_state = (
            CapabilityState.DEGRADED
            if diagnostics
            else CapabilityState.SUPPORTED
            if self._server_filter_verified
            else CapabilityState.UNKNOWN
        )
        results[Capability.SERVER_TIME_FILTER] = CapabilityProbe(
            capability=Capability.SERVER_TIME_FILTER,
            state=filter_state,
            checked_at=checked_at,
            last_success_at=checked_at if filter_state is CapabilityState.SUPPORTED else None,
            evidence_summary=(
                "Filtered shift request returned only rows inside the requested interval"
                if filter_state is CapabilityState.SUPPORTED
                else "QuickResto server filtering required a recorded local fallback"
                if filter_state is CapabilityState.DEGRADED
                else None
            ),
        )
        for capability in Capability:
            if capability in results:
                continue
            state = CapabilityState.UNAVAILABLE if capability in _UNAVAILABLE_CAPABILITIES else CapabilityState.UNKNOWN
            results[capability] = CapabilityProbe(
                capability=capability,
                state=state,
                checked_at=checked_at,
                evidence_summary=(
                    "QuickResto adapter has no verified read-only source for this capability"
                    if state is CapabilityState.UNAVAILABLE
                    else None
                ),
            )
        results.update(self._extended_capability_probes)
        self._last_probe_at = checked_at
        return results

    def get_limits(self) -> ProviderLimits:
        return ProviderLimits(
            max_page_size=1000,
            max_pages=100,
            timeout_seconds=float(self.client.config.timeout_seconds),
            evidence={"pagination": "QuickResto list contract", "range_mode": "monthly half-open packages"},
        )

    def discover_scope(self) -> ProviderScope:
        return ProviderScope(
            external_venues=tuple(self._records_for("venues")),
            sale_places=tuple(self._records_for("sale_places")),
            terminals=tuple(self._records_for("sale_places")),
            stores=tuple(self._records_for("stores")),
        )

    def iter_business_shifts(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]:
        if period_end_exclusive <= period_start:
            raise ProviderValidationError("QuickResto period end must be later than its start")
        closed_since = datetime.combine(period_start - timedelta(days=2), time.min, tzinfo=timezone.utc)
        closed_before = datetime.combine(period_end_exclusive + timedelta(days=2), time.min, tzinfo=timezone.utc)
        used_server_filter = hasattr(self.client, "list_closed_shifts")
        try:
            if used_server_filter:
                rows = self.client.list_closed_shifts(closed_since=closed_since, closed_before=closed_before)
            else:
                module_name, class_name = QUICKRESTO_OBJECT_TYPES["shifts"]
                rows = self.client.list_all_objects(module_name=module_name, class_name=class_name)
        except Exception as exc:
            raise self._translate_error(exc) from exc
        self._successful_probes.add(Capability.BUSINESS_SHIFTS)
        before = len(rows)
        output = []
        for row in rows:
            if str(row.get("status") or "").upper() != "CLOSED":
                continue
            try:
                business_date = business_date_for_shift(row, cutoff_hour=self.business_day_cutoff_hour)
            except (QuickRestoDataError, ValueError):
                # Keep undated/malformed records in the stream so the raw and
                # quarantine layers can retain them instead of losing evidence.
                output.append(self._record(row))
                continue
            if period_start <= business_date < period_end_exclusive:
                output.append(self._record(row))
        record_filter = getattr(self.client, "record_business_date_filter_result", None)
        if callable(record_filter):
            record_filter(
                rows_before=before,
                rows_after=len(output),
                period_start=period_start.isoformat(),
                period_end_exclusive=period_end_exclusive.isoformat(),
            )
        fallback_diagnostics = getattr(self.client, "fallback_diagnostics", None)
        self._server_filter_verified = bool(
            used_server_filter and callable(fallback_diagnostics) and not fallback_diagnostics()
        )
        return tuple(output)

    def iter_orders(
        self,
        *,
        business_shift_ids: Iterable[str],
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]:
        try:
            shift_ids = {str(value) for value in business_shift_ids if str(value)}
            if hasattr(self.client, "list_orders_for_shift_ids"):
                rows = self.client.list_orders_for_shift_ids(shift_ids)
            else:
                module_name, class_name = QUICKRESTO_OBJECT_TYPES["orders"]
                rows = [
                    row
                    for row in self.client.list_all_objects(module_name=module_name, class_name=class_name)
                    if str(row.get("shiftId") or "") in shift_ids
                ]
        except Exception as exc:
            raise self._translate_error(exc) from exc
        self._successful_probes.add(Capability.ORDERS)
        return tuple(self._record(row) for row in rows)

    def iter_payment_types(self) -> Iterable[ProviderRecord]:
        return tuple(self._records_for("payment_types"))

    def iter_products(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        return tuple(self._records_for("dishes"))

    def iter_product_groups(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        return tuple(self._records_for("dish_categories"))

    def iter_employees(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        return tuple(self._records_for("employees"))

    def iter_recipes(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        raise ProviderCapabilityError("QuickResto recipes capability is unavailable")

    def iter_warehouses(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        return tuple(self._records_for("stores"))

    def iter_stock_balances(self, *, at: datetime | None = None) -> Iterable[ProviderRecord]:
        raise ProviderCapabilityError("QuickResto stock balances capability is unavailable")

    def iter_stock_movements(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]:
        output: list[ProviderRecord] = []
        for object_type in _STOCK_DOCUMENT_TYPES:
            output.extend(self._document_records(object_type, period_start, period_end_exclusive))
        self._successful_probes.add(Capability.STOCK_MOVEMENTS)
        return tuple(output)

    def iter_suppliers(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        raise ProviderCapabilityError("QuickResto suppliers capability is unavailable")

    def iter_purchases(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]:
        return tuple(self._document_records("incoming_invoices", period_start, period_end_exclusive))

    def iter_writeoffs(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]:
        return tuple(self._document_records("discard_invoices", period_start, period_end_exclusive))

    def iter_inventory(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]:
        return tuple(self._document_records("inventory_documents", period_start, period_end_exclusive))

    def iter_attendance(
        self, *, period_start: date, period_end_exclusive: date, cursor: str | None = None
    ) -> Iterable[ProviderRecord]:
        raise ProviderCapabilityError("QuickResto attendance capability is unavailable")

    def get_current_business_shift(self, *, external_venue_id: str) -> ProviderRecord | None:
        """Return a locally verified OPEN shift.

        The live Quick Resto cloud ignored the server-side ``status=OPEN``
        filter, so this method deliberately scans the paginated surface and
        applies the exact status predicate locally.
        """

        rows = self._rows_for("shifts")
        scoped = [row for row in rows if self._belongs_to_venue(row, external_venue_id)]
        opened = [row for row in scoped if str(row.get("status") or "").strip().upper() in {"OPEN", "OPENED"}]
        if not opened:
            return None
        opened.sort(key=lambda row: (str(row.get("opened") or row.get("localOpenedTime") or ""), self._row_id(row)))
        self._successful_probes.add(Capability.CURRENT_BUSINESS_SHIFT)
        return self._record(opened[-1])

    def iter_open_orders(self, *, external_venue_id: str) -> Iterable[ProviderRecord]:
        raise ProviderCapabilityError(
            "QuickResto open orders capability is not verified: OrderInfo has no evidenced open/closed state"
        )

    def get_open_order(self, *, external_venue_id: str, external_order_id: str) -> ProviderRecord | None:
        raise ProviderCapabilityError(
            "QuickResto open orders capability is not verified: OrderInfo has no evidenced open/closed state"
        )

    def iter_restaurant_sections(self, *, external_venue_id: str) -> Iterable[ProviderRecord]:
        scheme = self._table_scheme(external_venue_id)
        if scheme is None:
            return ()
        records = []
        for index, hall in enumerate(self._hall_rows(scheme)):
            hall_id = self._nested_id(hall) or f"{external_venue_id}:hall:{index}"
            payload = dict(hall)
            payload.setdefault("tableSchemeId", str(external_venue_id))
            payload.setdefault("id", hall_id)
            records.append(self._record(payload))
        self._successful_probes.add(Capability.RESTAURANT_SECTIONS)
        return tuple(records)

    def iter_tables(self, *, external_venue_id: str) -> Iterable[ProviderRecord]:
        scheme = self._table_scheme(external_venue_id)
        if scheme is None:
            return ()
        records: list[ProviderRecord] = []
        seen: set[str] = set()
        halls = self._hall_rows(scheme)
        table_sources: list[tuple[dict[str, Any], str | None]] = []
        for hall in halls:
            hall_id = self._nested_id(hall)
            for table in self._nested_rows(hall, "tables", "webTables"):
                table_sources.append((table, hall_id))
        for table in self._nested_rows(scheme, "tables", "webTables"):
            table_sources.append((table, self._nested_id(table.get("hall") or table.get("section"))))
        for index, (table, hall_id) in enumerate(table_sources):
            table_id = self._nested_id(table) or f"{external_venue_id}:table:{index}"
            if table_id in seen:
                continue
            seen.add(table_id)
            payload = dict(table)
            payload.setdefault("tableSchemeId", str(external_venue_id))
            if hall_id:
                payload.setdefault("restaurantSectionId", hall_id)
            payload.setdefault("id", table_id)
            records.append(self._record(payload))
        self._successful_probes.add(Capability.TABLES)
        return tuple(records)

    def _document_records(
        self,
        object_type: str,
        period_start: date,
        period_end_exclusive: date,
    ) -> tuple[ProviderRecord, ...]:
        if period_end_exclusive <= period_start:
            raise ProviderValidationError("QuickResto period end must be later than its start")
        rows = self._rows_for(object_type)
        output: list[ProviderRecord] = []
        module_name, class_name = QUICKRESTO_OBJECT_TYPES[object_type]
        for row in rows:
            document_date = self._document_date(row)
            if document_date is not None and not (period_start <= document_date < period_end_exclusive):
                continue
            detail = row
            object_id = self._numeric_id(row)
            if object_id is not None:
                try:
                    read_detail = self.client.read_object(
                        module_name=module_name,
                        class_name=class_name,
                        object_id=object_id,
                    )
                    detail = {**row, **read_detail}
                except Exception as exc:
                    raise self._translate_error(exc) from exc
            payload = dict(detail)
            payload.setdefault("documentSurface", object_type)
            payload.setdefault("documentSourceId", self._row_id(payload) or self._row_id(row))
            source_record = self._record(payload)
            output.append(
                ProviderRecord(
                    external_id=f"{object_type}:{source_record.external_id}",
                    payload=source_record.payload,
                    source_version=source_record.source_version,
                    source_updated_at=source_record.source_updated_at,
                )
            )
        capability = _DOCUMENT_CAPABILITIES.get(object_type)
        if capability is not None:
            self._successful_probes.add(capability)
        return tuple(output)

    def _table_scheme(self, external_venue_id: str) -> dict[str, Any] | None:
        rows = self._rows_for("venues")
        expected = str(external_venue_id or "").strip()
        selected = next((row for row in rows if self._row_id(row) == expected), None)
        if selected is None:
            return None
        object_id = self._numeric_id(selected)
        if object_id is None:
            return selected
        module_name, class_name = QUICKRESTO_OBJECT_TYPES["venues"]
        try:
            detail = self.client.read_object(module_name=module_name, class_name=class_name, object_id=object_id)
            return {**selected, **detail}
        except Exception as exc:
            raise self._translate_error(exc) from exc

    def _rows_for(self, object_type: str) -> list[dict[str, Any]]:
        module_name, class_name = QUICKRESTO_OBJECT_TYPES[object_type]
        try:
            return self.client.list_all_objects(module_name=module_name, class_name=class_name)
        except Exception as exc:
            raise self._translate_error(exc) from exc

    @staticmethod
    def _nested_rows(value: Mapping[str, Any], *keys: str) -> list[dict[str, Any]]:
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, list):
                return [item for item in candidate if isinstance(item, dict)]
        return []

    @classmethod
    def _hall_rows(cls, scheme: Mapping[str, Any]) -> list[dict[str, Any]]:
        return cls._nested_rows(scheme, "webHalls", "halls", "sections", "rooms")

    @staticmethod
    def _nested_id(value: Any) -> str | None:
        if isinstance(value, Mapping):
            value = value.get("frontId") or value.get("_id") or value.get("id")
        raw = str(value or "").strip()
        return raw or None

    @classmethod
    def _row_id(cls, row: Mapping[str, Any]) -> str:
        return cls._nested_id(row) or ""

    @staticmethod
    def _numeric_id(row: Mapping[str, Any]) -> int | None:
        value = row.get("id")
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @classmethod
    def _belongs_to_venue(cls, row: Mapping[str, Any], external_venue_id: str) -> bool:
        expected = str(external_venue_id or "").strip()
        if not expected:
            return True
        references = [row.get(key) for key in ("tableScheme", "venue", "restaurant", "department")]
        present = [cls._nested_id(value) for value in references if value is not None]
        return not present or expected in present

    @staticmethod
    def _document_date(row: Mapping[str, Any]) -> date | None:
        value = row.get("invoiceDate") or row.get("date") or row.get("documentDate") or row.get("created")
        if isinstance(value, date) and not isinstance(value, datetime):
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

    def _records_for(self, object_type: str) -> Iterable[ProviderRecord]:
        rows = self._rows_for(object_type)
        capability = {
            "venues": Capability.EXTERNAL_VENUES,
            "sale_places": Capability.SALE_PLACES,
            "stores": Capability.STORES,
            "payment_types": Capability.PAYMENTS,
            "dishes": Capability.PRODUCTS,
            "dish_categories": Capability.PRODUCT_GROUPS,
            "employees": Capability.EMPLOYEES,
        }.get(object_type)
        if capability is not None:
            self._successful_probes.add(capability)
        return tuple(self._record(row) for row in rows)

    def _probe_object_type(self, object_type: str) -> None:
        module_name, class_name = QUICKRESTO_OBJECT_TYPES[object_type]
        self.client.list_objects(module_name=module_name, class_name=class_name, limit=1, offset=0)
        capability = {
            "venues": Capability.EXTERNAL_VENUES,
            "sale_places": Capability.SALE_PLACES,
            "stores": Capability.STORES,
            "shifts": Capability.BUSINESS_SHIFTS,
            "orders": Capability.ORDERS,
            "payment_types": Capability.PAYMENTS,
            "dishes": Capability.PRODUCTS,
            "dish_categories": Capability.PRODUCT_GROUPS,
        }[object_type]
        self._successful_probes.add(capability)

    @staticmethod
    def _record(row: dict[str, Any]) -> ProviderRecord:
        external_id = str(row.get("frontId") or row.get("_id") or row.get("id") or "").strip()
        if not external_id:
            raise ProviderValidationError("QuickResto record has no stable external id")
        version = row.get("version")
        return ProviderRecord(
            external_id=external_id,
            payload=row,
            source_version=str(version) if version is not None else None,
        )

    @staticmethod
    def _translate_error(exc: BaseException):
        if isinstance(exc, QuickRestoAuthenticationError):
            return ProviderAuthenticationError(str(exc))
        if isinstance(exc, QuickRestoHTTPError):
            if exc.status_code in {401, 403}:
                return ProviderAuthenticationError(str(exc))
            if exc.status_code == 429:
                return ProviderRateLimitError(str(exc))
            if exc.status_code >= 500:
                return ProviderTemporaryError(str(exc))
            return ProviderValidationError(str(exc))
        if isinstance(exc, QuickRestoError):
            return ProviderTemporaryError(str(exc))
        if isinstance(exc, (ValueError, TypeError)):
            return ProviderValidationError(str(exc))
        return ProviderTemporaryError("QuickResto provider request failed")


def quickresto_provider_factory(credentials: ProviderCredentials) -> QuickRestoProviderAdapter:
    return QuickRestoProviderAdapter.from_credentials(credentials)


def register_quickresto_provider(registry: ProviderRegistry = provider_registry) -> None:
    if "QUICKRESTO" not in registry.registered_providers():
        registry.register("QUICKRESTO", quickresto_provider_factory)

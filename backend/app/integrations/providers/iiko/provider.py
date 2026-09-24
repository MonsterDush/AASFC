from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import date, datetime, timezone
from typing import Any, TypeVar

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
from app.integrations.base.provider import ProviderAdapters, ProviderHealth, ProviderLimits, ProviderScope
from app.integrations.registry import ProviderRegistry, provider_registry
from app.services.integrations.iiko import (
    IIKOAuthenticationError,
    IIKOClient,
    IIKOConfig,
    IIKOError,
    IIKOHTTPError,
    IIKOResponseError,
)


T = TypeVar("T")


class IIKOProviderAdapter:
    provider_code = "IIKO"

    def __init__(
        self,
        client: IIKOClient,
        *,
        organization_id: str | None = None,
        terminal_group_ids: Iterable[str] = (),
    ) -> None:
        self.client = client
        self.organization_id = str(organization_id or "").strip() or None
        self.terminal_group_ids = tuple(
            normalized for value in terminal_group_ids if (normalized := str(value or "").strip())
        )
        self._nomenclature_cache: dict[str, Any] | None = None
        self._sections_cache: dict[str, Any] | None = None

    @classmethod
    def from_credentials(cls, credentials: ProviderCredentials) -> IIKOProviderAdapter:
        terminal_group_ids = tuple(
            item.strip() for item in str(credentials.values.get("terminal_group_ids") or "").split(",") if item.strip()
        )
        return cls(
            IIKOClient(
                IIKOConfig(
                    api_login=credentials.values.get("api_login") or credentials.values.get("apiLogin"),
                    api_key=credentials.values.get("api_key") or credentials.values.get("apiKey"),
                    app_id=credentials.values.get("app_id") or credentials.values.get("appId"),
                    client_secret=credentials.values.get("client_secret") or credentials.values.get("clientSecret"),
                    base_url=credentials.values.get("base_url") or "https://api-ru.iiko.services",
                    timeout_seconds=float(credentials.values.get("timeout_seconds") or 20),
                )
            ),
            organization_id=credentials.values.get("organization_id"),
            terminal_group_ids=terminal_group_ids,
        )

    def close(self) -> None:
        self.client.close()

    def health_check(self) -> ProviderHealth:
        checked_at = datetime.now(timezone.utc)
        try:
            self._invoke(self.client.organizations)
        except Exception as exc:
            return ProviderHealth(healthy=False, checked_at=checked_at, message=str(exc))
        return ProviderHealth(healthy=True, checked_at=checked_at, message="iikoCloud read-only API responded")

    def verify_credentials(self) -> ProviderHealth:
        return self.health_check()

    def get_limits(self) -> ProviderLimits:
        return ProviderLimits(
            timeout_seconds=float(self.client.config.timeout_seconds),
            evidence={
                "authentication": f"Bearer token ({self.client.config.auth_version})",
                "token_lifetime_seconds": 3600,
                "source": "iikoCloud official OpenAPI",
            },
        )

    def discover_scope(self) -> ProviderScope:
        organizations = self._invoke(self.client.organizations, include_disabled=True)
        organization_ids = [self._external_id(item) for item in organizations]
        terminal_groups = (
            self._invoke(self.client.terminal_groups, organization_ids, include_disabled=True)
            if organization_ids
            else []
        )
        alive_by_id: dict[str, bool] = {}
        terminal_group_ids = [self._external_id(item) for item in terminal_groups]
        if organization_ids and terminal_group_ids:
            alive_rows = self._invoke(
                self.client.terminal_groups_alive,
                organization_ids,
                terminal_group_ids,
            )
            alive_by_id = {
                str(row.get("terminalGroupId") or "").strip(): bool(row.get("isAlive")) for row in alive_rows
            }

        organization_records = tuple(self._record(item) for item in organizations)
        terminal_group_records = tuple(
            self._record(
                {
                    **item,
                    "isAlive": alive_by_id.get(self._external_id(item)),
                }
            )
            for item in terminal_groups
        )
        return ProviderScope(
            organizations=organization_records,
            external_venues=organization_records,
            terminal_groups=terminal_group_records,
        )

    def get_capabilities(self) -> Mapping[Capability, CapabilityProbe]:
        checked_at = datetime.now(timezone.utc)
        results = {
            capability: CapabilityProbe(
                capability=capability,
                state=CapabilityState.UNKNOWN,
                checked_at=checked_at,
            )
            for capability in Capability
        }
        try:
            organizations = self._invoke(self.client.organizations)
        except Exception as exc:
            results[Capability.EXTERNAL_VENUES] = self._failed_probe(
                Capability.EXTERNAL_VENUES,
                checked_at,
                exc,
            )
            return results

        results[Capability.EXTERNAL_VENUES] = self._supported_probe(
            Capability.EXTERNAL_VENUES,
            checked_at,
            "iikoCloud /api/1/organizations returned a valid response",
        )
        organization_ids = [self._external_id(item) for item in organizations]
        if not organization_ids:
            return results

        try:
            terminal_groups = self._invoke(self.client.terminal_groups, organization_ids)
        except Exception as exc:
            results[Capability.TERMINALS] = self._failed_probe(Capability.TERMINALS, checked_at, exc)
            terminal_groups = []
        else:
            results[Capability.TERMINALS] = self._derived_probe(
                Capability.TERMINALS,
                checked_at,
                "iikoCloud terminal groups were read successfully; individual terminals are not exposed by this endpoint",
            )

        selected_organization_id = self.organization_id or organization_ids[0]
        try:
            nomenclature = self._invoke(self.client.nomenclature, selected_organization_id, start_revision=0)
        except Exception as exc:
            for capability in (
                Capability.PRODUCTS,
                Capability.PRODUCT_GROUPS,
                Capability.PRODUCT_VARIANTS,
                Capability.MODIFIERS,
                Capability.REVISION_SYNC,
            ):
                results[capability] = self._failed_probe(capability, checked_at, exc)
        else:
            self._nomenclature_cache = nomenclature
            for capability, evidence in (
                (Capability.PRODUCTS, "iikoCloud nomenclature returned products"),
                (Capability.PRODUCT_GROUPS, "iikoCloud nomenclature returned groups and categories"),
                (Capability.PRODUCT_VARIANTS, "iikoCloud nomenclature returned sizes and size prices"),
                (Capability.MODIFIERS, "iikoCloud nomenclature returned modifier products and rules"),
                (Capability.REVISION_SYNC, "iikoCloud nomenclature returned a revision cursor"),
            ):
                results[capability] = self._supported_probe(capability, checked_at, evidence)

        try:
            self._invoke(self.client.payment_types, [selected_organization_id])
        except Exception as exc:
            results[Capability.PAYMENTS] = self._failed_probe(Capability.PAYMENTS, checked_at, exc)
        else:
            results[Capability.PAYMENTS] = self._supported_probe(
                Capability.PAYMENTS,
                checked_at,
                "iikoCloud /api/1/payment_types returned a valid response",
            )

        try:
            self._invoke(self.client.stop_lists, [selected_organization_id], return_size=True)
        except Exception as exc:
            results[Capability.STOP_LISTS] = self._failed_probe(Capability.STOP_LISTS, checked_at, exc)
        else:
            results[Capability.STOP_LISTS] = self._supported_probe(
                Capability.STOP_LISTS,
                checked_at,
                "iikoCloud /api/1/stop_lists returned a valid response",
            )

        group_ids = self.terminal_group_ids or tuple(self._external_id(item) for item in terminal_groups)
        if group_ids:
            try:
                sections = self._invoke(self.client.restaurant_sections, group_ids)
            except Exception as exc:
                for capability in (Capability.RESTAURANT_SECTIONS, Capability.TABLES):
                    results[capability] = self._failed_probe(capability, checked_at, exc)
            else:
                self._sections_cache = sections
                results[Capability.RESTAURANT_SECTIONS] = self._supported_probe(
                    Capability.RESTAURANT_SECTIONS,
                    checked_at,
                    "iikoCloud reserve restaurant sections returned a valid response",
                )
                results[Capability.TABLES] = self._supported_probe(
                    Capability.TABLES,
                    checked_at,
                    "iikoCloud restaurant sections returned nested tables",
                )
        return results

    def iter_products(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        del updated_since
        payload = self._nomenclature()
        revision = str(payload["revision"])
        return tuple(
            self._record(item, source_version=revision)
            for item in payload["products"]
            if str(item.get("type") or "").lower() != "modifier"
        )

    def iter_product_groups(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        del updated_since
        payload = self._nomenclature()
        revision = str(payload["revision"])
        records = [
            self._record({**item, "canonicalKind": "GROUP"}, source_version=revision) for item in payload["groups"]
        ]
        records.extend(
            self._record({**item, "canonicalKind": "CATEGORY"}, source_version=revision)
            for item in payload["productCategories"]
        )
        return tuple(records)

    def iter_product_variants(self) -> Iterable[ProviderRecord]:
        payload = self._nomenclature()
        revision = str(payload["revision"])
        sizes = {self._external_id(item): item for item in payload["sizes"] if item.get("id")}
        records: list[ProviderRecord] = []
        for product in payload["products"]:
            product_id = self._external_id(product)
            for size_price in product.get("sizePrices") or []:
                if not isinstance(size_price, Mapping):
                    continue
                size_id = str(size_price.get("sizeId") or "").strip()
                if not size_id:
                    continue
                records.append(
                    self._record(
                        {
                            **dict(size_price),
                            "id": f"{product_id}:{size_id}",
                            "productId": product_id,
                            "sizeId": size_id,
                            "size": sizes.get(size_id),
                        },
                        source_version=revision,
                    )
                )
        return tuple(records)

    def iter_modifier_groups(self) -> Iterable[ProviderRecord]:
        payload = self._nomenclature()
        revision = str(payload["revision"])
        products = {self._external_id(item): item for item in payload["products"]}
        found: dict[str, dict[str, Any]] = {}
        for product in payload["products"]:
            for rule in product.get("groupModifiers") or []:
                if not isinstance(rule, Mapping):
                    continue
                group_id = str(rule.get("id") or "").strip()
                if group_id:
                    found[group_id] = {**products.get(group_id, {}), **dict(rule), "id": group_id}
        return tuple(self._record(item, source_version=revision) for item in found.values())

    def iter_modifiers(self) -> Iterable[ProviderRecord]:
        payload = self._nomenclature()
        revision = str(payload["revision"])
        group_ids = {
            str(rule.get("id"))
            for product in payload["products"]
            for rule in product.get("groupModifiers") or []
            if isinstance(rule, Mapping) and rule.get("id")
        }
        return tuple(
            self._record(item, source_version=revision)
            for item in payload["products"]
            if str(item.get("type") or "").lower() == "modifier" and self._external_id(item) not in group_ids
        )

    def iter_product_modifier_rules(self) -> Iterable[ProviderRecord]:
        payload = self._nomenclature()
        revision = str(payload["revision"])
        records: list[ProviderRecord] = []
        for product in payload["products"]:
            product_id = self._external_id(product)
            if str(product.get("type") or "").lower() == "modifier":
                continue
            for rule in product.get("modifiers") or []:
                if isinstance(rule, Mapping) and rule.get("id"):
                    modifier_id = str(rule["id"])
                    records.append(
                        self._record(
                            {
                                **dict(rule),
                                "id": f"{product_id}:modifier:{modifier_id}",
                                "productId": product_id,
                                "modifierId": modifier_id,
                            },
                            source_version=revision,
                        )
                    )
            for group_rule in product.get("groupModifiers") or []:
                if not isinstance(group_rule, Mapping) or not group_rule.get("id"):
                    continue
                group_id = str(group_rule["id"])
                for child in group_rule.get("childModifiers") or []:
                    if not isinstance(child, Mapping) or not child.get("id"):
                        continue
                    modifier_id = str(child["id"])
                    records.append(
                        self._record(
                            {
                                **dict(group_rule),
                                **dict(child),
                                "id": f"{product_id}:group:{group_id}:modifier:{modifier_id}",
                                "productId": product_id,
                                "modifierGroupId": group_id,
                                "modifierId": modifier_id,
                                "groupMinAmount": group_rule.get("minAmount"),
                                "groupMaxAmount": group_rule.get("maxAmount"),
                            },
                            source_version=revision,
                        )
                    )
        return tuple(records)

    def iter_payment_types(self) -> Iterable[ProviderRecord]:
        organization_id = self._selected_organization_id()
        return tuple(self._record(item) for item in self._invoke(self.client.payment_types, [organization_id]))

    def iter_stop_list_entries(self) -> Iterable[ProviderRecord]:
        organization_id = self._selected_organization_id()
        terminal_group_ids = self._selected_terminal_group_ids()
        rows = self._invoke(
            self.client.stop_lists,
            [organization_id],
            terminal_group_ids=terminal_group_ids,
            return_size=True,
        )
        return tuple(
            self._record(
                {
                    **item,
                    "id": ":".join(
                        (
                            str(item.get("terminalGroupId") or "all"),
                            str(item.get("productId") or "unknown"),
                            str(item.get("sizeId") or "default"),
                        )
                    ),
                }
            )
            for item in rows
        )

    def iter_restaurant_sections(self, *, external_venue_id: str) -> Iterable[ProviderRecord]:
        self._validate_external_venue(external_venue_id)
        payload = self._sections()
        revision = str(payload["revision"])
        return tuple(self._record(item, source_version=revision) for item in payload["restaurantSections"])

    def iter_tables(self, *, external_venue_id: str) -> Iterable[ProviderRecord]:
        self._validate_external_venue(external_venue_id)
        payload = self._sections()
        revision = str(payload["revision"])
        records = []
        for section in payload["restaurantSections"]:
            section_id = self._external_id(section)
            for table in section.get("tables") or []:
                if isinstance(table, Mapping):
                    records.append(
                        self._record(
                            {**dict(table), "restaurantSectionId": section_id},
                            source_version=revision,
                        )
                    )
        return tuple(records)

    def iter_dictionaries(self) -> Mapping[str, tuple[ProviderRecord, ...]]:
        organization_id = self._selected_organization_id()
        organization_ids = [organization_id]
        readers: dict[str, Callable[[], list[dict[str, Any]]]] = {
            "payment_types": lambda: self.client.payment_types(organization_ids),
            "order_types": lambda: self.client.order_types(organization_ids),
            "discounts": lambda: self.client.discounts(organization_ids),
            "cancel_causes": lambda: self.client.cancel_causes(organization_ids),
            "removal_types": lambda: self.client.removal_types(organization_ids),
            "tips_types": self.client.tips_types,
            "marketing_sources": lambda: self.client.marketing_sources(organization_ids),
        }
        return {name: tuple(self._record(item) for item in self._invoke(reader)) for name, reader in readers.items()}

    def get_current_business_shift(self, *, external_venue_id: str) -> ProviderRecord | None:
        del external_venue_id
        raise ProviderCapabilityError("iiko current business shift belongs to Stage 5")

    def iter_open_orders(self, *, external_venue_id: str) -> Iterable[ProviderRecord]:
        del external_venue_id
        raise ProviderCapabilityError("iiko open orders belong to Stage 5")

    def get_open_order(self, *, external_venue_id: str, external_order_id: str) -> ProviderRecord | None:
        del external_venue_id, external_order_id
        raise ProviderCapabilityError("iiko open orders belong to Stage 5")

    def iter_business_shifts(
        self,
        *,
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]:
        del period_start, period_end_exclusive, cursor
        raise ProviderCapabilityError("iiko historical shifts belong to Stage 6")

    def iter_orders(
        self,
        *,
        business_shift_ids: Iterable[str],
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]:
        del business_shift_ids, period_start, period_end_exclusive, cursor
        raise ProviderCapabilityError("iiko historical orders belong to Stage 6")

    def iter_employees(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        del updated_since
        raise ProviderCapabilityError("iiko employees belong to Stage 8")

    def iter_recipes(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        del updated_since
        raise ProviderCapabilityError("iiko recipes are not implemented in Stage 4")

    def iter_warehouses(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        del updated_since
        raise ProviderCapabilityError("iiko warehouses belong to Stage 9")

    def iter_stock_balances(self, *, at: datetime | None = None) -> Iterable[ProviderRecord]:
        del at
        raise ProviderCapabilityError("iiko stock balances belong to Stage 9")

    def iter_stock_movements(
        self,
        *,
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]:
        del period_start, period_end_exclusive, cursor
        raise ProviderCapabilityError("iiko stock movements belong to Stage 9")

    def iter_suppliers(self, *, updated_since: datetime | None = None) -> Iterable[ProviderRecord]:
        del updated_since
        raise ProviderCapabilityError("iiko suppliers belong to Stage 9")

    def iter_purchases(
        self,
        *,
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]:
        del period_start, period_end_exclusive, cursor
        raise ProviderCapabilityError("iiko purchases belong to Stage 9")

    def iter_writeoffs(
        self,
        *,
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]:
        del period_start, period_end_exclusive, cursor
        raise ProviderCapabilityError("iiko writeoffs belong to Stage 9")

    def iter_inventory(
        self,
        *,
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]:
        del period_start, period_end_exclusive, cursor
        raise ProviderCapabilityError("iiko inventory belongs to Stage 9")

    def iter_attendance(
        self,
        *,
        period_start: date,
        period_end_exclusive: date,
        cursor: str | None = None,
    ) -> Iterable[ProviderRecord]:
        del period_start, period_end_exclusive, cursor
        raise ProviderCapabilityError("iiko attendance belongs to Stage 8")

    def _nomenclature(self) -> dict[str, Any]:
        if self._nomenclature_cache is None:
            self._nomenclature_cache = self._invoke(
                self.client.nomenclature,
                self._selected_organization_id(),
                start_revision=0,
            )
        return self._nomenclature_cache

    def _sections(self) -> dict[str, Any]:
        if self._sections_cache is None:
            terminal_group_ids = self._selected_terminal_group_ids()
            if not terminal_group_ids:
                return {"restaurantSections": [], "revision": 0}
            self._sections_cache = self._invoke(self.client.restaurant_sections, terminal_group_ids)
        return self._sections_cache

    def _selected_organization_id(self) -> str:
        if self.organization_id:
            return self.organization_id
        organizations = self._invoke(self.client.organizations)
        if len(organizations) != 1:
            raise ProviderValidationError("iiko organization scope must be selected explicitly")
        self.organization_id = self._external_id(organizations[0])
        return self.organization_id

    def _selected_terminal_group_ids(self) -> tuple[str, ...]:
        if self.terminal_group_ids:
            return self.terminal_group_ids
        organization_id = self._selected_organization_id()
        groups = self._invoke(self.client.terminal_groups, [organization_id])
        self.terminal_group_ids = tuple(self._external_id(item) for item in groups)
        return self.terminal_group_ids

    def _validate_external_venue(self, external_venue_id: str) -> None:
        expected = self._selected_organization_id()
        if str(external_venue_id or "").strip() != expected:
            raise ProviderValidationError("iiko external venue does not match the selected organization")

    def _invoke(self, operation: Callable[..., T], *args, **kwargs) -> T:
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            raise self._translate_error(exc) from exc

    @staticmethod
    def _record(row: Mapping[str, Any], *, source_version: str | None = None) -> ProviderRecord:
        external_id = IIKOProviderAdapter._external_id(row)
        return ProviderRecord(
            external_id=external_id,
            payload=dict(row),
            source_version=source_version,
        )

    @staticmethod
    def _external_id(row: Mapping[str, Any]) -> str:
        external_id = str(row.get("id") or row.get("organizationId") or "").strip()
        if not external_id:
            raise ProviderValidationError("iiko record has no stable external id")
        return external_id

    @staticmethod
    def _supported_probe(
        capability: Capability,
        checked_at: datetime,
        evidence: str,
    ) -> CapabilityProbe:
        return CapabilityProbe(
            capability=capability,
            state=CapabilityState.SUPPORTED,
            checked_at=checked_at,
            last_success_at=checked_at,
            evidence_summary=evidence,
        )

    @staticmethod
    def _derived_probe(
        capability: Capability,
        checked_at: datetime,
        evidence: str,
    ) -> CapabilityProbe:
        return CapabilityProbe(
            capability=capability,
            state=CapabilityState.DERIVED,
            checked_at=checked_at,
            last_success_at=checked_at,
            evidence_summary=evidence,
        )

    @staticmethod
    def _failed_probe(capability: Capability, checked_at: datetime, exc: BaseException) -> CapabilityProbe:
        code = getattr(exc, "code", None)
        return CapabilityProbe(
            capability=capability,
            state=CapabilityState.DEGRADED,
            checked_at=checked_at,
            last_error_code=getattr(code, "value", None),
            evidence_summary=str(exc),
        )

    @staticmethod
    def _translate_error(exc: BaseException):
        if isinstance(exc, (ProviderAuthenticationError, ProviderCapabilityError, ProviderValidationError)):
            return exc
        if isinstance(exc, IIKOAuthenticationError):
            return ProviderAuthenticationError(str(exc))
        if isinstance(exc, IIKOHTTPError):
            if exc.status_code in {401, 403}:
                return ProviderAuthenticationError(str(exc))
            if exc.status_code == 429:
                return ProviderRateLimitError(str(exc))
            if exc.status_code >= 500:
                return ProviderTemporaryError(str(exc))
            return ProviderValidationError(str(exc))
        if isinstance(exc, IIKOResponseError):
            return ProviderValidationError(str(exc))
        if isinstance(exc, IIKOError):
            return ProviderTemporaryError(str(exc))
        if isinstance(exc, (ValueError, TypeError, KeyError)):
            return ProviderValidationError(str(exc))
        return ProviderTemporaryError("iiko provider request failed")


def iiko_provider_factory(credentials: ProviderCredentials) -> ProviderAdapters:
    adapter = IIKOProviderAdapter.from_credentials(credentials)
    return ProviderAdapters(discovery=adapter, reader=adapter, operational=adapter)


def register_iiko_provider(registry: ProviderRegistry = provider_registry) -> None:
    if "IIKO" not in registry.registered_providers():
        registry.register("IIKO", iiko_provider_factory)

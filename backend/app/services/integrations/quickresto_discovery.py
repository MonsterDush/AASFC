from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any

from app.integrations.base.capabilities import Capability, CapabilityProbe, CapabilityState
from app.services.integrations.quickresto import (
    QUICKRESTO_OBJECT_TYPES,
    QuickRestoAuthenticationError,
    QuickRestoClient,
    QuickRestoError,
    QuickRestoHTTPError,
)


@dataclass(frozen=True, slots=True)
class QuickRestoSurfaceEvidence:
    surface: str
    module_name: str | None
    class_name: str | None
    state: CapabilityState
    rows_observed: int
    list_fields: tuple[str, ...] = ()
    detail_fields: tuple[str, ...] = ()
    structural_paths: tuple[str, ...] = ()
    error_code: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["state"] = self.state.value
        return value


@dataclass(frozen=True, slots=True)
class QuickRestoDiscoveryReport:
    checked_at: datetime
    surfaces: tuple[QuickRestoSurfaceEvidence, ...]
    capabilities: dict[Capability, CapabilityProbe]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "provider": "QUICKRESTO",
            "checked_at": self.checked_at.isoformat(),
            "contains_payload_values": False,
            "surfaces": [surface.to_dict() for surface in self.surfaces],
            "capabilities": {
                capability.value: {
                    "state": probe.state.value,
                    "last_success_at": probe.last_success_at.isoformat() if probe.last_success_at else None,
                    "last_error_code": probe.last_error_code,
                    "evidence_summary": probe.evidence_summary,
                }
                for capability, probe in sorted(self.capabilities.items(), key=lambda item: item[0].value)
            },
        }


def _safe_error_code(exc: BaseException) -> str:
    if isinstance(exc, QuickRestoAuthenticationError):
        return "AUTHENTICATION"
    if isinstance(exc, QuickRestoHTTPError):
        return f"HTTP_{exc.status_code}"
    if isinstance(exc, QuickRestoError):
        cause = exc.__cause__
        cause_name = type(cause).__name__.lower() if cause is not None else ""
        if "timeout" in cause_name:
            return "TIMEOUT"
        if "ssl" in cause_name:
            return "TLS_ERROR"
        if "connection" in cause_name:
            return "CONNECTION"
        return "PROVIDER_REQUEST"
    if isinstance(exc, (TypeError, ValueError)):
        return "INVALID_RESPONSE"
    return "UNEXPECTED"


def _shape_paths(value: Any, *, prefix: str = "", depth: int = 0) -> set[str]:
    if depth > 4:
        return set()
    paths: set[str] = set()
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key)
            path = f"{prefix}.{key}" if prefix else key
            paths.add(path)
            paths.update(_shape_paths(item, prefix=path, depth=depth + 1))
    elif isinstance(value, list) and value:
        paths.update(_shape_paths(value[0], prefix=f"{prefix}[]", depth=depth + 1))
    return paths


def _fields(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(sorted({str(key) for row in rows for key in row}))


def _probe_list(
    client: QuickRestoClient,
    surface: str,
    object_type: str,
    *,
    limit: int,
    filters: tuple[dict[str, Any], ...] = (),
    include_detail: bool = False,
) -> tuple[QuickRestoSurfaceEvidence, list[dict[str, Any]], dict[str, Any] | None]:
    module_name, class_name = QUICKRESTO_OBJECT_TYPES[object_type]
    try:
        rows = client.list_objects(
            module_name=module_name,
            class_name=class_name,
            limit=limit,
            offset=0,
            filters=filters,
        )
        detail = None
        if include_detail and rows:
            object_id = int(rows[0].get("id") or 0)
            if object_id > 0:
                detail = client.read_object(module_name=module_name, class_name=class_name, object_id=object_id)
        paths = set()
        for row in rows:
            paths.update(_shape_paths(row))
        if detail is not None:
            paths.update(_shape_paths(detail))
        evidence = QuickRestoSurfaceEvidence(
            surface=surface,
            module_name=module_name,
            class_name=class_name,
            state=CapabilityState.SUPPORTED,
            rows_observed=len(rows),
            list_fields=_fields(rows),
            detail_fields=tuple(sorted(str(key) for key in (detail or {}))),
            structural_paths=tuple(sorted(paths)),
            note="Read-only /api/list probe succeeded",
        )
        return evidence, rows, detail
    except Exception as exc:
        error_code = _safe_error_code(exc)
        return (
            QuickRestoSurfaceEvidence(
                surface=surface,
                module_name=module_name,
                class_name=class_name,
                state=CapabilityState.DEGRADED,
                rows_observed=0,
                error_code=error_code,
                note="Read-only probe failed; no payload or exception text was retained",
            ),
            [],
            None,
        )


class _ProbeRunner:
    _GLOBAL_FAILURE_CODES = {"AUTHENTICATION", "TIMEOUT", "TLS_ERROR", "CONNECTION"}

    def __init__(self, client: QuickRestoClient) -> None:
        self.client = client
        self.global_error_code: str | None = None

    def probe(
        self,
        surface: str,
        object_type: str,
        *,
        limit: int,
        filters: tuple[dict[str, Any], ...] = (),
        include_detail: bool = False,
    ) -> tuple[QuickRestoSurfaceEvidence, list[dict[str, Any]], dict[str, Any] | None]:
        if self.global_error_code is not None:
            module_name, class_name = QUICKRESTO_OBJECT_TYPES[object_type]
            return (
                QuickRestoSurfaceEvidence(
                    surface=surface,
                    module_name=module_name,
                    class_name=class_name,
                    state=CapabilityState.DEGRADED,
                    rows_observed=0,
                    error_code=self.global_error_code,
                    note="Probe skipped after a global authentication or transport failure",
                ),
                [],
                None,
            )
        result = _probe_list(
            self.client,
            surface,
            object_type,
            limit=limit,
            filters=filters,
            include_detail=include_detail,
        )
        if result[0].error_code in self._GLOBAL_FAILURE_CODES:
            self.global_error_code = result[0].error_code
        return result


def _contains_path(evidence: QuickRestoSurfaceEvidence, fragments: tuple[str, ...]) -> bool:
    return any(any(fragment in path.lower() for fragment in fragments) for path in evidence.structural_paths)


def _contains_collection_path(evidence: QuickRestoSurfaceEvidence, fragments: tuple[str, ...]) -> bool:
    return any(
        "[]" in path and any(fragment in path.lower() for fragment in fragments)
        for path in evidence.structural_paths
    )


def _probe_for_capability(
    capability: Capability,
    state: CapabilityState,
    checked_at: datetime,
    evidence: str,
    *,
    error_code: str | None = None,
) -> CapabilityProbe:
    return CapabilityProbe(
        capability=capability,
        state=state,
        checked_at=checked_at,
        last_success_at=checked_at if state in {CapabilityState.SUPPORTED, CapabilityState.DERIVED} else None,
        last_error_code=error_code,
        evidence_summary=evidence,
    )


def discover_quickresto_capabilities(
    client: QuickRestoClient,
    *,
    sample_limit: int = 5,
) -> QuickRestoDiscoveryReport:
    """Probe documented Quick Resto read surfaces without retaining values or PII."""

    if not 1 <= int(sample_limit) <= 20:
        raise ValueError("QuickResto discovery sample_limit must be between 1 and 20")
    checked_at = datetime.now(timezone.utc)
    surfaces: list[QuickRestoSurfaceEvidence] = []
    capabilities: dict[Capability, CapabilityProbe] = {}
    runner = _ProbeRunner(client)

    open_shift, shift_rows, _ = runner.probe(
        "open_business_shift",
        "shifts",
        limit=sample_limit,
        filters=({"field": "status", "operation": "eq", "value": "OPEN"},),
    )
    if open_shift.state is CapabilityState.SUPPORTED and shift_rows:
        shift_statuses = {str(row.get("status") or "").upper() for row in shift_rows}
        if not shift_statuses or shift_statuses != {"OPEN"}:
            open_shift = replace(
                open_shift,
                state=CapabilityState.DEGRADED,
                error_code="FILTER_NOT_VERIFIED",
                note="OPEN filter returned rows outside the requested status",
            )
    surfaces.append(open_shift)
    capabilities[Capability.CURRENT_BUSINESS_SHIFT] = _probe_for_capability(
        Capability.CURRENT_BUSINESS_SHIFT,
        open_shift.state,
        checked_at,
        "QuickResto Shift /api/list accepted a read-only OPEN-status probe"
        if open_shift.state is CapabilityState.SUPPORTED
        else "QuickResto open-shift probe or its server-side filter could not be verified",
        error_code=open_shift.error_code,
    )

    open_orders, order_rows, _ = runner.probe(
        "open_orders",
        "orders",
        limit=sample_limit,
        filters=({"field": "status", "operation": "eq", "value": "OPEN"},),
    )
    if open_orders.state is CapabilityState.SUPPORTED and order_rows:
        explicit_statuses = {
            str(row.get("status") or "").upper()
            for row in order_rows
            if row.get("status") is not None
        }
        if explicit_statuses and explicit_statuses != {"OPEN"}:
            open_orders = replace(
                open_orders,
                state=CapabilityState.DEGRADED,
                error_code="FILTER_NOT_VERIFIED",
                note="OPEN filter returned orders outside the requested status",
            )
    surfaces.append(open_orders)
    order_status_paths = ("status", "closed", "open", "paid", "orderstate")
    can_identify_open = _contains_path(open_orders, order_status_paths)
    open_order_state = (
        open_orders.state
        if open_orders.state is not CapabilityState.SUPPORTED
        else CapabilityState.SUPPORTED
        if order_rows and can_identify_open
        else CapabilityState.UNKNOWN
    )
    capabilities[Capability.OPEN_ORDERS] = _probe_for_capability(
        Capability.OPEN_ORDERS,
        open_order_state,
        checked_at,
        "OrderInfo rows expose an identifiable operational status"
        if open_order_state is CapabilityState.SUPPORTED
        else "OrderInfo endpoint responded, but open-order state was not evidenced by sampled structure"
        if open_orders.state is CapabilityState.SUPPORTED
        else "QuickResto OrderInfo read-only probe failed",
        error_code=open_orders.error_code,
    )
    current_total_derived = open_order_state is CapabilityState.SUPPORTED and _contains_path(
        open_orders, ("total", "amount", "price")
    )
    current_total_state = (
        CapabilityState.DERIVED
        if current_total_derived
        else open_order_state
        if open_order_state is CapabilityState.DEGRADED
        else CapabilityState.UNKNOWN
    )
    capabilities[Capability.CURRENT_ORDER_TOTAL] = _probe_for_capability(
        Capability.CURRENT_ORDER_TOTAL,
        current_total_state,
        checked_at,
        "Derived from a sampled open OrderInfo total field"
        if current_total_derived
        else "No verified open OrderInfo amount structure",
        error_code=open_orders.error_code,
    )

    schemes, _, _ = runner.probe(
        "table_schemes",
        "venues",
        limit=sample_limit,
        include_detail=True,
    )
    surfaces.append(schemes)
    for capability, fragments, label in (
        (Capability.TABLES, ("table",), "table"),
        (Capability.RESTAURANT_SECTIONS, ("section", "hall", "room"), "restaurant section"),
    ):
        state = (
            CapabilityState.SUPPORTED
            if schemes.state is CapabilityState.SUPPORTED
            and _contains_collection_path(schemes, fragments)
            else CapabilityState.UNKNOWN
            if schemes.state is CapabilityState.SUPPORTED
            else schemes.state
        )
        capabilities[capability] = _probe_for_capability(
            capability,
            state,
            checked_at,
            f"TableScheme detail exposes a {label} structure"
            if state is CapabilityState.SUPPORTED
            else f"TableScheme responded without sampled {label} structural evidence"
            if schemes.state is CapabilityState.SUPPORTED
            else "QuickResto TableScheme read-only probe failed",
            error_code=schemes.error_code,
        )

    modifier_evidence = []
    for surface, object_type in (("modifier_groups", "modifier_groups"), ("modifiers", "modifiers")):
        evidence, _, _ = runner.probe(surface, object_type, limit=sample_limit, include_detail=True)
        surfaces.append(evidence)
        modifier_evidence.append(evidence)
    modifier_state = (
        CapabilityState.SUPPORTED
        if all(item.state is CapabilityState.SUPPORTED for item in modifier_evidence)
        else CapabilityState.DEGRADED
    )
    capabilities[Capability.MODIFIERS] = _probe_for_capability(
        Capability.MODIFIERS,
        modifier_state,
        checked_at,
        "Both Modifier and ModifierGroup read-only endpoints responded"
        if modifier_state is CapabilityState.SUPPORTED
        else "Modifier discovery is incomplete",
        error_code=next((item.error_code for item in modifier_evidence if item.error_code), None),
    )

    dishes, _, _ = runner.probe(
        "dish_configurations",
        "dishes",
        limit=sample_limit,
        include_detail=True,
    )
    surfaces.append(dishes)
    configuration_evidenced = _contains_path(dishes, ("config", "variant", "option"))
    capabilities[Capability.PRODUCT_VARIANTS] = _probe_for_capability(
        Capability.PRODUCT_VARIANTS,
        CapabilityState.SUPPORTED
        if dishes.state is CapabilityState.SUPPORTED and configuration_evidenced
        else CapabilityState.UNKNOWN
        if dishes.state is CapabilityState.SUPPORTED
        else dishes.state,
        checked_at,
        "Dish detail exposes configuration/variant/option structure"
        if configuration_evidenced
        else "Dish endpoint did not provide sampled configuration structure",
        error_code=dishes.error_code,
    )

    employees, _, _ = runner.probe("employees", "employees", limit=sample_limit)
    surfaces.append(employees)
    capabilities[Capability.EMPLOYEES] = _probe_for_capability(
        Capability.EMPLOYEES,
        employees.state,
        checked_at,
        "QuickResto Employee read-only endpoint responded"
        if employees.state is CapabilityState.SUPPORTED
        else "QuickResto Employee read-only probe failed",
        error_code=employees.error_code,
    )

    document_specs = (
        ("inventory_documents", "inventory_documents", Capability.INVENTORY),
        ("incoming_invoices", "incoming_invoices", Capability.PURCHASES),
        ("discard_invoices", "discard_invoices", Capability.WRITEOFFS),
        ("outgoing_invoices", "outgoing_invoices", None),
        ("exchange_invoices", "exchange_invoices", None),
        ("cooking_invoices", "cooking_invoices", None),
        ("decomposition_invoices", "decomposition_invoices", None),
        ("processing_invoices", "processing_invoices", None),
    )
    document_evidence: list[QuickRestoSurfaceEvidence] = []
    for surface, object_type, capability in document_specs:
        evidence, _, _ = runner.probe(surface, object_type, limit=sample_limit)
        surfaces.append(evidence)
        document_evidence.append(evidence)
        if capability is not None:
            capabilities[capability] = _probe_for_capability(
                capability,
                evidence.state,
                checked_at,
                f"QuickResto {object_type} read-only endpoint responded"
                if evidence.state is CapabilityState.SUPPORTED
                else f"QuickResto {object_type} read-only probe failed",
                error_code=evidence.error_code,
            )
    successful_documents = sum(item.state is CapabilityState.SUPPORTED for item in document_evidence)
    stock_movement_state = (
        CapabilityState.DERIVED
        if successful_documents
        else CapabilityState.DEGRADED
        if any(item.state is CapabilityState.DEGRADED for item in document_evidence)
        else CapabilityState.UNKNOWN
    )
    capabilities[Capability.STOCK_MOVEMENTS] = _probe_for_capability(
        Capability.STOCK_MOVEMENTS,
        stock_movement_state,
        checked_at,
        "Can be derived from successfully probed inventory document endpoints"
        if successful_documents
        else "No inventory document endpoint was successfully probed",
        error_code=next((item.error_code for item in document_evidence if item.error_code), None),
    )
    capabilities[Capability.STOCK_BALANCES] = _probe_for_capability(
        Capability.STOCK_BALANCES,
        CapabilityState.UNKNOWN,
        checked_at,
        "Official API 2.92 has no dedicated stock-balance list endpoint; requires live structural evidence",
    )
    capabilities[Capability.STOP_LISTS] = _probe_for_capability(
        Capability.STOP_LISTS,
        CapabilityState.UNKNOWN,
        checked_at,
        "Quick Resto product supports stop lists, but API 2.92 exposes no documented read endpoint",
    )

    return QuickRestoDiscoveryReport(
        checked_at=checked_at,
        surfaces=tuple(surfaces),
        capabilities=capabilities,
    )

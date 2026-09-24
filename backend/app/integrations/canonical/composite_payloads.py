from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping


@dataclass(frozen=True, slots=True)
class CanonicalCompositeLine:
    external_id: str
    parent_external_id: str | None
    item_role: str
    component_role: str | None
    product_external_id: str | None
    name: str
    quantity: Decimal
    net_amount: Decimal
    attributed_net_amount: Decimal | None
    included_in_parent: bool


def _first(source: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in source and source[key] is not None:
            return source[key]
    return default


def _decimal(value: Any, *, default: str = "0") -> Decimal:
    try:
        return Decimal(str(default if value is None else value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Invalid decimal value: {value!r}") from exc


def _identifier(source: Mapping[str, Any], *, fallback: str = "") -> str:
    value = _first(source, "external_id", "externalId", "id", "Id", "productId", "ProductId", default=fallback)
    return str(value or "").strip()


def _product_identifier(source: Mapping[str, Any]) -> str | None:
    product = _first(source, "product", "Product", "dish", "Dish")
    if isinstance(product, Mapping):
        value = _identifier(product)
    else:
        value = str(_first(source, "productId", "ProductId", "dishId", "DishId", default="") or "").strip()
    return value or None


def _name(source: Mapping[str, Any]) -> str:
    product = _first(source, "product", "Product", "dish", "Dish")
    if isinstance(product, Mapping):
        nested = _first(product, "name", "Name")
        if nested:
            return str(nested)
    return str(_first(source, "name", "Name", "productName", "ProductName", default="") or "")


def _children(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        yield value
    elif isinstance(value, (list, tuple)):
        yield from (item for item in value if isinstance(item, Mapping))


def _flatten_compound(
    payload: Mapping[str, Any],
    *,
    component_groups: Iterable[tuple[str, Any]],
) -> tuple[CanonicalCompositeLine, ...]:
    parent_id = _identifier(payload)
    if not parent_id:
        raise ValueError("Compound order item requires a stable external id")
    components: list[tuple[str, Mapping[str, Any]]] = []
    for role, value in component_groups:
        components.extend((role, child) for child in _children(value))
    total = _decimal(_first(payload, "netAmount", "resultSum", "ResultSum", "total", "sum", default=0))
    quantity = _decimal(_first(payload, "quantity", "amount", "Amount", default=1), default="1")
    output = [
        CanonicalCompositeLine(
            external_id=parent_id,
            parent_external_id=None,
            item_role="COMPOUND" if components else "PRODUCT",
            component_role=None,
            product_external_id=_product_identifier(payload),
            name=_name(payload),
            quantity=quantity,
            net_amount=total,
            attributed_net_amount=total,
            included_in_parent=False,
        )
    ]
    for index, (role, component) in enumerate(components, start=1):
        external_id = _identifier(component, fallback=f"{parent_id}:{role}:{index}")
        output.append(
            CanonicalCompositeLine(
                external_id=external_id,
                parent_external_id=parent_id,
                item_role="MODIFIER" if role == "MODIFIER" else "COMPONENT",
                component_role=role,
                product_external_id=_product_identifier(component),
                name=_name(component),
                quantity=_decimal(
                    _first(component, "quantity", "amount", "Amount", default=1),
                    default="1",
                ),
                net_amount=Decimal("0"),
                attributed_net_amount=None,
                included_in_parent=True,
            )
        )
    return tuple(output)


def normalize_quickresto_composite(payload: Mapping[str, Any]) -> tuple[CanonicalCompositeLine, ...]:
    return _flatten_compound(
        payload,
        component_groups=(
            ("PRIMARY", payload.get("primaryComponents")),
            ("SECONDARY", payload.get("secondaryComponents")),
            ("COMMON", payload.get("components")),
            ("MODIFIER", payload.get("modifiers")),
        ),
    )


def normalize_iiko_composite(payload: Mapping[str, Any]) -> tuple[CanonicalCompositeLine, ...]:
    """Flatten iiko compound-item DTOs without double-counting the parent charge."""

    return _flatten_compound(
        payload,
        component_groups=(
            ("PRIMARY", _first(payload, "primaryComponent", "PrimaryComponent")),
            ("SECONDARY", _first(payload, "secondaryComponent", "SecondaryComponent")),
            ("COMMON", _first(payload, "commonComponents", "CommonComponents")),
            ("MODIFIER", _first(payload, "commonModifiers", "CommonModifiers")),
        ),
    )

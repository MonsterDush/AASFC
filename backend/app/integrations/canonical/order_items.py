from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Protocol


class CanonicalOrderItem(Protocol):
    parent_item_id: int | None
    included_in_parent: bool
    net_amount: Decimal
    attributed_net_amount: Decimal | None


def _money_to_minor(value: object) -> int:
    return int((Decimal(str(value or 0)) * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def attribution_minor_for_item(item: CanonicalOrderItem) -> int:
    """Return category/KPI attribution without counting a compound charge twice."""

    if item.attributed_net_amount is not None:
        return _money_to_minor(item.attributed_net_amount)
    if item.parent_item_id is not None and bool(item.included_in_parent):
        return 0
    return _money_to_minor(item.net_amount)

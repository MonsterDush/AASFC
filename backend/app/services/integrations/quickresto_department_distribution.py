from __future__ import annotations

from collections.abc import Iterable

from app.models.quickresto_department_mapping import (
    QuickRestoDepartmentAllocation,
    QuickRestoDepartmentMapping,
)


def mapping_department_distribution(mapping: QuickRestoDepartmentMapping | None) -> dict[int, int]:
    if mapping is None:
        return {}
    allocations = {
        int(item.department_id): int(item.share_percent)
        for item in mapping.allocations
        if int(item.department_id or 0) > 0 and int(item.share_percent or 0) > 0
    }
    if allocations:
        return allocations if mapping.department_id is None and sum(allocations.values()) == 100 else {}
    if mapping.department_id is not None:
        return {int(mapping.department_id): 100}
    return {}


def mapping_is_resolved(mapping: QuickRestoDepartmentMapping | None) -> bool:
    return bool(mapping_department_distribution(mapping))


def replace_mapping_distribution(
    mapping: QuickRestoDepartmentMapping,
    *,
    department_id: int | None,
    allocations: Iterable[tuple[int, int]],
) -> None:
    normalized = [(int(target_id), int(share)) for target_id, share in allocations]
    mapping.allocations.clear()
    if normalized:
        mapping.department_id = None
        mapping.allocations.extend(
            QuickRestoDepartmentAllocation(department_id=target_id, share_percent=share)
            for target_id, share in normalized
        )
        return
    mapping.department_id = int(department_id) if department_id is not None else None


def allocate_integer_total(total: int, distribution: dict[int, int]) -> dict[int, int]:
    """Split an integer-ruble total exactly, using deterministic largest remainders."""
    value = int(total)
    normalized = {int(key): int(share) for key, share in distribution.items() if int(share) > 0}
    if not normalized or sum(normalized.values()) != 100:
        raise ValueError("QuickResto department allocation must total 100 percent")
    sign = -1 if value < 0 else 1
    absolute = abs(value)
    output = {key: absolute * share // 100 for key, share in normalized.items()}
    remainder = absolute - sum(output.values())
    ranked = sorted(
        normalized,
        key=lambda key: (-(absolute * normalized[key] % 100), key),
    )
    for key in ranked[:remainder]:
        output[key] += 1
    return {key: sign * amount for key, amount in sorted(output.items())}

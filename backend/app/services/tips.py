from __future__ import annotations

from collections.abc import Iterable

from app.models.daily_report_tip_allocation import DailyReportTipAllocation


def build_equal_tip_allocations(*, report_id: int, tips_total: int, assigned_user_ids: Iterable[int | None]) -> list[DailyReportTipAllocation]:
    """Build equal tip allocations for unique assigned users.

    The remainder is distributed one-by-one to the first users in stable sorted order.
    Returns unsaved model instances.
    """
    safe_total = int(tips_total or 0)
    if safe_total <= 0:
        return []

    uniq_user_ids = sorted({int(user_id) for user_id in assigned_user_ids if user_id is not None})
    count = len(uniq_user_ids)
    if count == 0:
        return []

    share = safe_total // count
    remainder = safe_total - share * count

    allocations: list[DailyReportTipAllocation] = []
    for index, user_id in enumerate(uniq_user_ids):
        amount = share + (1 if index < remainder else 0)
        allocations.append(
            DailyReportTipAllocation(
                report_id=report_id,
                user_id=user_id,
                amount=int(amount),
                split_mode="EQUAL",
            )
        )
    return allocations

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.models.daily_report_tip_allocation import DailyReportTipAllocation


def normalize_position_title(value: str | None) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _split_equal_amount(total: int, count: int) -> list[int]:
    safe_total = int(total or 0)
    safe_count = int(count or 0)
    if safe_total <= 0 or safe_count <= 0:
        return []
    share = safe_total // safe_count
    remainder = safe_total - share * safe_count
    return [share + (1 if i < remainder else 0) for i in range(safe_count)]


def _allocate_percent_amounts(total: int, percents: list[int]) -> list[int]:
    """Allocate floor(total * percent / 100) with largest-remainder tie-break.

    The returned list sums to floor(total * sum(percents) / 100).
    """
    safe_total = int(total or 0)
    if safe_total <= 0 or not percents:
        return [0 for _ in percents]

    numerators = [safe_total * max(0, int(p or 0)) for p in percents]
    base = [n // 100 for n in numerators]
    target_total = sum(numerators) // 100
    extra = target_total - sum(base)
    if extra > 0:
        order = sorted(range(len(percents)), key=lambda idx: (numerators[idx] % 100, -idx), reverse=True)
        for idx in order[:extra]:
            base[idx] += 1
    return base


def parse_position_percent_map(tips_weights: Any) -> dict[str, dict[str, Any]]:
    """Parse venue tips_weights into mapping by normalized position title.

    Supported payload examples:
    - {"rows": [{"title": "Бармен", "percent": 10}]}
    - {"by_position": [{"title": "Бармен", "percent": 10}]}
    - {"position_percents": {"Бармен": 10}}
    - [{"title": "Бармен", "percent": 10}]
    """
    rows: list[Any] = []
    if isinstance(tips_weights, dict):
        if isinstance(tips_weights.get("rows"), list):
            rows = list(tips_weights.get("rows") or [])
        elif isinstance(tips_weights.get("by_position"), list):
            rows = list(tips_weights.get("by_position") or [])
        elif isinstance(tips_weights.get("position_percents"), dict):
            rows = [
                {"title": title, "percent": percent}
                for title, percent in (tips_weights.get("position_percents") or {}).items()
            ]
        elif isinstance(tips_weights.get("positions"), list):
            rows = list(tips_weights.get("positions") or [])
    elif isinstance(tips_weights, list):
        rows = list(tips_weights)

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = row.get("title") or row.get("position_title") or row.get("position") or row.get("name")
        norm = normalize_position_title(title)
        if not norm:
            continue
        try:
            percent = int(row.get("percent") or 0)
        except Exception:
            percent = 0
        percent = max(0, min(100, percent))
        out[norm] = {
            "title": " ".join(str(title or "").strip().split()) or str(title or ""),
            "percent": percent,
        }
    return out


def build_equal_tip_allocations(
    *, report_id: int, tips_total: int, assigned_user_ids: Iterable[int | None]
) -> list[DailyReportTipAllocation]:
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

    amounts = _split_equal_amount(safe_total, count)
    allocations: list[DailyReportTipAllocation] = []
    for index, user_id in enumerate(uniq_user_ids):
        allocations.append(
            DailyReportTipAllocation(
                report_id=report_id,
                user_id=user_id,
                amount=int(amounts[index]),
                split_mode="EQUAL",
                meta_json=None,
            )
        )
    return allocations


def build_weighted_by_position_tip_allocations(
    *,
    report_id: int,
    tips_total: int,
    assigned_members: Iterable[tuple[int | None, str | None]],
    tips_weights: Any,
) -> list[DailyReportTipAllocation]:
    """Allocate tips using per-person fixed percentages by position title.

    Configured positions receive their fixed percent for each assigned person with that title.
    The remaining pool is split equally between assignees without explicit config.
    If all assignees are configured and some remainder is still left, the remainder is split
    equally between all assigned users so no tip amount disappears due to config gaps/rounding.
    """
    safe_total = int(tips_total or 0)
    if safe_total <= 0:
        return []

    uniq_members: list[tuple[int, str | None]] = []
    seen_user_ids: set[int] = set()
    for user_id, position_title in assigned_members:
        if user_id is None:
            continue
        uid = int(user_id)
        if uid in seen_user_ids:
            continue
        seen_user_ids.add(uid)
        uniq_members.append((uid, position_title))

    if not uniq_members:
        return []

    config = parse_position_percent_map(tips_weights)
    explicit_members: list[tuple[int, str | None, int]] = []
    fallback_members: list[tuple[int, str | None]] = []
    for uid, position_title in uniq_members:
        percent = int((config.get(normalize_position_title(position_title)) or {}).get("percent") or 0)
        if percent > 0:
            explicit_members.append((uid, position_title, percent))
        else:
            fallback_members.append((uid, position_title))

    if sum(percent for _uid, _title, percent in explicit_members) > 100:
        raise ValueError("Сумма долей чаевых для назначенных сотрудников превышает 100%")

    final_amounts: dict[int, int] = {uid: 0 for uid, _title in uniq_members}

    if explicit_members:
        fixed_amounts = _allocate_percent_amounts(safe_total, [percent for _uid, _title, percent in explicit_members])
        for idx, (uid, position_title, percent) in enumerate(explicit_members):
            final_amounts[uid] += int(fixed_amounts[idx])

    remaining_total = safe_total - sum(final_amounts.values())
    if remaining_total > 0:
        pool_members = fallback_members or [(uid, title) for uid, title in uniq_members]
        equal_amounts = _split_equal_amount(remaining_total, len(pool_members))
        for idx, (uid, _title) in enumerate(pool_members):
            final_amounts[uid] += int(equal_amounts[idx])

    allocations: list[DailyReportTipAllocation] = []
    for uid, position_title in uniq_members:
        percent = int((config.get(normalize_position_title(position_title)) or {}).get("percent") or 0)
        allocations.append(
            DailyReportTipAllocation(
                report_id=report_id,
                user_id=uid,
                amount=int(final_amounts.get(uid, 0)),
                split_mode="WEIGHTED_BY_POSITION",
                meta_json={
                    "position_title": position_title,
                    "configured_percent": percent if percent > 0 else None,
                    "used_fallback_pool": bool(percent <= 0),
                },
            )
        )
    return allocations

from __future__ import annotations

from datetime import date

from .component_calculations import _allocate_minor_by_keys


def reconcile_percent_day_rows(
    *,
    day_rows: list[dict],
    amount_minor: int,
    base_by_date: dict[date, int],
    allocation_dates: set[date] | list[date] | None,
    percent_bps: int,
    boost_applied: bool,
) -> list[dict]:
    """Make a percent component's daily rows add up to its stored month total."""
    rows = [dict(row) for row in (day_rows or []) if isinstance(row, dict)]
    if rows and sum(int(row.get("amount_minor") or 0) for row in rows) == int(amount_minor):
        return rows

    rows_by_date = {str(row.get("date") or ""): row for row in rows if row.get("date")}
    if rows_by_date:
        dates = sorted(date.fromisoformat(raw_date) for raw_date in rows_by_date)
        weights = {
            target_date: max(0, int(rows_by_date[target_date.isoformat()].get("amount_minor") or 0))
            for target_date in dates
        }
    else:
        dates = sorted(base_by_date) or sorted(set(allocation_dates or []))
        weights = {target_date: max(0, int(base_by_date.get(target_date, 0) or 0)) for target_date in dates}
    if not dates:
        return rows

    allocation = _allocate_minor_by_keys(int(amount_minor), dates, weights)
    reconciled: list[dict] = []
    for target_date in dates:
        raw_date = target_date.isoformat()
        row = rows_by_date.get(raw_date)
        if row is None:
            base_amount_minor = int(base_by_date.get(target_date, 0) or 0)
            row = {
                "date": raw_date,
                "base_amount_minor": base_amount_minor,
                "actual_amount_minor": base_amount_minor,
                "target_amount_minor": None,
                "boost_applied": bool(boost_applied),
                "percent_bps": int(percent_bps),
            }
        row["amount_minor"] = int(allocation.get(target_date, 0))
        row["monthly_allocation"] = True
        reconciled.append(row)
    return reconciled

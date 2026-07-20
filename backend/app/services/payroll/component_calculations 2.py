from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json

from app.models import PayComponent

from .payroll_types import (
    MINIMUM_GUARANTEE_DAY,
    MINIMUM_GUARANTEE_MONTH,
    MINIMUM_GUARANTEE_SHIFT,
    PAY_COMPONENT_TYPES,
    PayrollKpiBonusDecision,
    PayrollMemberMetrics,
    PayrollPercentDecision,
    PayrollRevenueMetrics,
    PayrollVenuePlanMetrics,
    PayrollWorkedShift,
)


def parse_month_start(month: str) -> date:
    try:
        y_s, m_s = str(month or "").split("-")
        y = int(y_s)
        m = int(m_s)
        return date(y, m, 1)
    except Exception as exc:
        raise ValueError("Bad month format, expected YYYY-MM") from exc


def next_month_start(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year + 1, 1, 1)
    return date(month_start.year, month_start.month + 1, 1)


def interval_duration_minutes(start_time: time, end_time: time) -> int:
    start_dt = datetime.combine(date(2000, 1, 1), start_time)
    end_dt = datetime.combine(date(2000, 1, 1), end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    return int((end_dt - start_dt).total_seconds() // 60)


def _rub_to_minor(value: object) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, str):
        normalized = value.strip().replace(",", ".")
        if not normalized:
            return None
        try:
            num = float(normalized)
        except Exception:
            return None
    else:
        try:
            num = float(value)
        except Exception:
            return None
    if num < 0:
        return None
    return int(round(num * 100))


def _parse_steps_json(raw: object) -> list[dict]:
    if raw is None:
        return []
    value = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except Exception:
            return []

    if isinstance(value, dict):
        candidate = value.get("steps")
        if isinstance(candidate, list):
            value = candidate
        else:
            return []

    if not isinstance(value, list):
        return []

    out: list[dict] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        threshold_value = item.get("threshold_value")
        amount_minor = item.get("amount_minor")
        if amount_minor in (None, ""):
            amount_minor = _rub_to_minor(item.get("amount_rub"))
        try:
            threshold_value = int(threshold_value)
            amount_minor = int(amount_minor)
        except Exception:
            continue
        if threshold_value < 0 or amount_minor < 0:
            continue
        normalized = {
            "threshold_value": threshold_value,
            "amount_minor": amount_minor,
        }
        if item.get("title") not in (None, ""):
            normalized["title"] = str(item.get("title"))
        out.append(normalized)

    out.sort(key=lambda row: (int(row.get("threshold_value") or 0), int(row.get("amount_minor") or 0)))
    return out


def calculate_kpi_bonus(
    component: PayComponent,
    *,
    kpi_metric_value: int = 0,
) -> PayrollKpiBonusDecision:
    metric_value = int(kpi_metric_value or 0)
    steps = _parse_steps_json(getattr(component, "steps_json", None))
    threshold_value = getattr(component, "threshold_value", None)
    threshold_value = int(threshold_value) if threshold_value is not None else None

    if steps:
        matched_step = None
        for step in steps:
            if metric_value >= int(step.get("threshold_value") or 0):
                matched_step = step
            else:
                break
        return PayrollKpiBonusDecision(
            amount_minor=int(matched_step.get("amount_minor") or 0) if matched_step is not None else 0,
            metric_value=metric_value,
            threshold_value=threshold_value,
            matched_step=matched_step,
            steps=steps,
        )

    amount_minor = int(getattr(component, "amount_minor", 0) or 0)
    if threshold_value is None or metric_value >= threshold_value:
        return PayrollKpiBonusDecision(
            amount_minor=amount_minor,
            metric_value=metric_value,
            threshold_value=threshold_value,
            matched_step=None,
            steps=[],
        )
    return PayrollKpiBonusDecision(
        amount_minor=0,
        metric_value=metric_value,
        threshold_value=threshold_value,
        matched_step=None,
        steps=[],
    )


def calculate_component_amount_minor(
    component: PayComponent,
    *,
    minutes_total: int,
    shifts_count: int,
    total_revenue_minor: int = 0,
    department_revenue_minor: int = 0,
    kpi_metric_value: int = 0,
) -> int:
    component_type = str(component.component_type or "").strip().upper()
    if component_type not in PAY_COMPONENT_TYPES:
        raise ValueError(f"Unsupported pay component type: {component.component_type}")

    if component_type == "SALARY_FIXED_MONTH":
        return int(component.amount_minor or 0)

    if component_type == "SALARY_HOURLY":
        rate_minor = int(component.rate_minor or 0)
        return int((rate_minor * int(minutes_total) + 30) // 60)

    if component_type == "SALARY_PER_SHIFT":
        amount_minor = int(component.amount_minor or 0)
        return int(amount_minor * int(shifts_count))

    if component_type == "PERCENT_TOTAL_REVENUE":
        percent_bps = int(component.percent_bps or 0)
        return int((int(total_revenue_minor) * percent_bps + 5000) // 10000)

    if component_type == "PERCENT_DEPARTMENT_REVENUE":
        percent_bps = int(component.percent_bps or 0)
        return int((int(department_revenue_minor) * percent_bps + 5000) // 10000)

    if component_type == "KPI_BONUS":
        return int(calculate_kpi_bonus(component, kpi_metric_value=kpi_metric_value).amount_minor)

    # MINIMUM_PAYOUT is not a direct earning. It is calculated after all
    # other components as a top-up to the configured monthly or per-shift minimum.
    return 0



def _round_percent_amount(base_amount_minor: int, percent_bps: int) -> int:
    return int((int(base_amount_minor) * int(percent_bps) + 5000) // 10000)



def _normalize_int_ids(value: object) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            value = json.loads(raw)
        except Exception:
            return []
    if not isinstance(value, list):
        return []
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        try:
            item_id = int(item)
        except Exception:
            continue
        if item_id <= 0 or item_id in seen:
            continue
        seen.add(item_id)
        result.append(item_id)
    return result


def _component_department_ids(component: PayComponent) -> list[int]:
    ids = _normalize_int_ids(getattr(component, "department_ids_json", None))
    legacy_id = int(getattr(component, "department_id", 0) or 0)
    if legacy_id > 0 and legacy_id not in ids:
        ids.insert(0, legacy_id)
    return ids


def _component_boost_department_ids(component: PayComponent, *, fallback_department_ids: list[int] | None = None) -> list[int]:
    ids = _normalize_int_ids(getattr(component, "boost_department_ids_json", None))
    legacy_id = int(getattr(component, "boost_department_id", 0) or 0)
    if legacy_id > 0 and legacy_id not in ids:
        ids.insert(0, legacy_id)
    if not ids and fallback_department_ids:
        ids = [int(item) for item in fallback_department_ids if int(item) > 0]
    return ids


def _department_title_for(component: PayComponent, dep_id: int) -> str:
    titles_by_id = getattr(component, "_department_titles_by_id", None)
    if isinstance(titles_by_id, dict) and int(dep_id) in titles_by_id:
        return str(titles_by_id.get(int(dep_id)) or f"#{int(dep_id)}")
    for relationship_name in ("department", "boost_department"):
        department = getattr(component, relationship_name, None)
        if department is not None and int(getattr(department, "id", 0) or 0) == int(dep_id):
            title = getattr(department, "title", None)
            if title:
                return str(title)
    return f"#{int(dep_id)}"


def _department_titles_for_ids(component: PayComponent, ids: list[int]) -> list[str]:
    return [_department_title_for(component, int(dep_id)) for dep_id in ids]


def _sum_department_revenue_minor(revenue_metrics: PayrollRevenueMetrics, department_ids: list[int]) -> int:
    return int(sum(int(revenue_metrics.department_revenue_minor.get(int(dep_id), 0) or 0) for dep_id in department_ids))


def _sum_department_revenue_by_date_minor(revenue_metrics: PayrollRevenueMetrics, department_ids: list[int]) -> dict[date, int]:
    out: dict[date, int] = {}
    for dep_id in department_ids:
        for day, amount in revenue_metrics.department_revenue_by_date_minor.get(int(dep_id), {}).items():
            out[day] = int(out.get(day, 0) or 0) + int(amount or 0)
    return out


def _sum_optional_targets(values: list[int | None]) -> int | None:
    if not values or any(value is None for value in values):
        return None
    return int(sum(int(value or 0) for value in values))


def _sum_department_month_target_minor(venue_plan_metrics: PayrollVenuePlanMetrics, department_ids: list[int]) -> int | None:
    return _sum_optional_targets([
        venue_plan_metrics.department_month_revenue_target_minor.get(int(dep_id))
        for dep_id in department_ids
    ])


def _sum_department_day_target_minor(venue_plan_metrics: PayrollVenuePlanMetrics, department_ids: list[int], target_date: date) -> int | None:
    return _sum_optional_targets([
        venue_plan_metrics.department_day_revenue_target_by_date_minor.get(int(dep_id), {}).get(target_date)
        for dep_id in department_ids
    ])


def _minimum_guarantee_scope(component: PayComponent) -> str:
    raw = str(getattr(component, "minimum_guarantee_scope", "") or "").strip().upper()
    if raw == MINIMUM_GUARANTEE_DAY:
        return MINIMUM_GUARANTEE_DAY
    return MINIMUM_GUARANTEE_MONTH


def _minimum_payout_scope(component: PayComponent) -> str:
    raw = str(getattr(component, "minimum_guarantee_scope", "") or "").strip().upper()
    if raw in {MINIMUM_GUARANTEE_SHIFT, MINIMUM_GUARANTEE_DAY}:
        # DAY existed in the earlier draft of this component. Treat it as a
        # per-worked-shift minimum so old saved drafts do not become monthly.
        return MINIMUM_GUARANTEE_SHIFT
    return MINIMUM_GUARANTEE_MONTH


def _minimum_payout_scope_title(scope: str) -> str:
    return "за каждую отработанную смену" if scope == MINIMUM_GUARANTEE_SHIFT else "за месяц"


def _minimum_payout_target_minor(component: PayComponent, metrics: PayrollMemberMetrics) -> int:
    amount_minor = int(getattr(component, "amount_minor", 0) or 0)
    scope = _minimum_payout_scope(component)
    if scope == MINIMUM_GUARANTEE_SHIFT:
        return int(amount_minor * max(0, int(metrics.shifts_count or 0)))
    return int(amount_minor)


def _ordered_worked_shifts(metrics: PayrollMemberMetrics) -> list[PayrollWorkedShift]:
    return sorted(
        list(getattr(metrics, "worked_shifts", []) or []),
        key=lambda item: (item.shift_date, str(item.shift_slot or ""), int(item.shift_id)),
    )


def _allocate_minor_by_keys(total_minor: int, ordered_keys: list, weights_by_key: dict | None = None) -> dict:
    keys = list(ordered_keys or [])
    if not keys:
        return {}

    sign = -1 if int(total_minor or 0) < 0 else 1
    abs_total = abs(int(total_minor or 0))

    prepared_weights: dict = {}
    for key in keys:
        weight = int((weights_by_key or {}).get(key, 0) or 0)
        prepared_weights[key] = max(weight, 0)

    weight_total = sum(prepared_weights.values())
    if weight_total <= 0:
        prepared_weights = {key: 1 for key in keys}
        weight_total = len(keys)

    allocated: dict = {}
    used = 0
    for key in keys:
        part = (abs_total * prepared_weights[key]) // weight_total
        allocated[key] = int(part)
        used += int(part)

    remainder = abs_total - used
    for key in keys:
        if remainder <= 0:
            break
        allocated[key] += 1
        remainder -= 1

    return {key: sign * int(value) for key, value in allocated.items()}


def _shift_ids(metrics: PayrollMemberMetrics) -> list[int]:
    return [int(item.shift_id) for item in _ordered_worked_shifts(metrics)]


def _month_dates(month_start: date, month_end_excl: date) -> list[date]:
    out: list[date] = []
    cursor = month_start
    while cursor < month_end_excl:
        out.append(cursor)
        cursor += timedelta(days=1)
    return out


def _split_date_amounts_to_shifts(
    metrics: PayrollMemberMetrics,
    amounts_by_date: dict[date, int],
    *,
    weight_by_minutes: bool = False,
) -> dict[int, int]:
    shifts_by_date: dict[date, list[PayrollWorkedShift]] = {}
    for shift in _ordered_worked_shifts(metrics):
        shifts_by_date.setdefault(shift.shift_date, []).append(shift)

    out: dict[int, int] = {}
    for target_date, total_minor in (amounts_by_date or {}).items():
        shifts = shifts_by_date.get(target_date) or []
        if not shifts:
            continue
        ids = [int(shift.shift_id) for shift in shifts]
        weights = {
            int(shift.shift_id): (max(1, int(shift.minutes or 0)) if weight_by_minutes else 1)
            for shift in shifts
        }
        out.update(_allocate_minor_by_keys(int(total_minor or 0), ids, weights))
    return out


def _percent_decision_amounts_by_date(decision: PayrollPercentDecision | None) -> dict[date, int]:
    out: dict[date, int] = {}
    if decision is None:
        return out
    for row in decision.day_rows or []:
        if not isinstance(row, dict):
            continue
        raw_date = row.get("date")
        try:
            target_date = date.fromisoformat(str(raw_date))
        except Exception:
            continue
        out[target_date] = int(out.get(target_date, 0) or 0) + int(row.get("amount_minor") or 0)
    return out


def _component_shift_allocations(
    *,
    component: PayComponent,
    amount_minor: int,
    metrics: PayrollMemberMetrics,
    month_start: date,
    month_end_excl: date,
    revenue_metrics: PayrollRevenueMetrics,
    percent_decision: PayrollPercentDecision | None = None,
) -> dict[int, int]:
    shifts = _ordered_worked_shifts(metrics)
    if not shifts:
        return {}
    component_type = str(getattr(component, "component_type", "") or "").strip().upper()
    shift_ids = [int(shift.shift_id) for shift in shifts]

    if component_type == "SALARY_HOURLY":
        weights = {int(shift.shift_id): max(1, int(shift.minutes or 0)) for shift in shifts}
        return _allocate_minor_by_keys(int(amount_minor), shift_ids, weights)

    if component_type == "SALARY_PER_SHIFT":
        weights = {int(shift.shift_id): 1 for shift in shifts}
        return _allocate_minor_by_keys(int(amount_minor), shift_ids, weights)

    if component_type == "SALARY_FIXED_MONTH":
        # Месячную ставку в суточной детализации делим по календарным дням месяца,
        # затем долю конкретных суток делим между сменами этого дня.
        dates = _month_dates(month_start, month_end_excl)
        date_amounts = _allocate_minor_by_keys(int(amount_minor), dates, {day: 1 for day in dates})
        return _split_date_amounts_to_shifts(metrics, date_amounts, weight_by_minutes=False)

    if component_type == "PERCENT_TOTAL_REVENUE":
        date_amounts = _percent_decision_amounts_by_date(percent_decision)
        if not date_amounts:
            worked_dates = sorted({shift.shift_date for shift in shifts})
            weights = {day: int(revenue_metrics.total_revenue_by_date_minor.get(day, 0) or 0) for day in worked_dates}
            date_amounts = _allocate_minor_by_keys(int(amount_minor), worked_dates, weights)
        return _split_date_amounts_to_shifts(metrics, date_amounts, weight_by_minutes=False)

    if component_type == "PERCENT_DEPARTMENT_REVENUE":
        date_amounts = _percent_decision_amounts_by_date(percent_decision)
        if not date_amounts:
            worked_dates = sorted({shift.shift_date for shift in shifts})
            department_ids = _component_department_ids(component)
            weights = _sum_department_revenue_by_date_minor(revenue_metrics, department_ids) if department_ids else {}
            date_weights = {day: int(weights.get(day, 0) or 0) for day in worked_dates}
            date_amounts = _allocate_minor_by_keys(int(amount_minor), worked_dates, date_weights)
        return _split_date_amounts_to_shifts(metrics, date_amounts, weight_by_minutes=False)

    return _allocate_minor_by_keys(int(amount_minor), shift_ids, {int(shift.shift_id): 1 for shift in shifts})


def _minimum_payout_shift_top_up(
    *,
    component: PayComponent,
    metrics: PayrollMemberMetrics,
    earnings_by_shift_minor: dict[int, int],
) -> tuple[int, list[dict]]:
    minimum_per_shift_minor = int(getattr(component, "amount_minor", 0) or 0)
    rows: list[dict] = []
    total_top_up_minor = 0
    for shift in _ordered_worked_shifts(metrics):
        before_minor = int(earnings_by_shift_minor.get(int(shift.shift_id), 0) or 0)
        top_up_minor = max(0, minimum_per_shift_minor - before_minor)
        rows.append(
            {
                "shift_id": int(shift.shift_id),
                "date": shift.shift_date.isoformat(),
                "shift_slot": shift.shift_slot,
                "minutes": int(shift.minutes),
                "minimum_target_minor": int(minimum_per_shift_minor),
                "amount_before_minimum_minor": int(before_minor),
                "amount_minor": int(top_up_minor),
                "minimum_applied": bool(top_up_minor > 0),
            }
        )
        total_top_up_minor += int(top_up_minor)
    return int(total_top_up_minor), rows


def _apply_daily_minimum_to_rows(day_rows: list[dict], minimum_guarantee_minor: int | None) -> tuple[list[dict], bool]:
    if minimum_guarantee_minor is None:
        return day_rows, False
    applied = False
    result: list[dict] = []
    for row in day_rows:
        next_row = dict(row)
        amount_minor = int(next_row.get("amount_minor") or 0)
        if amount_minor < int(minimum_guarantee_minor):
            next_row["amount_before_minimum_minor"] = amount_minor
            next_row["amount_minor"] = int(minimum_guarantee_minor)
            next_row["minimum_applied"] = True
            applied = True
        else:
            next_row["minimum_applied"] = False
        result.append(next_row)
    return result, applied

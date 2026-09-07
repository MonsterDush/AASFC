from decimal import Decimal

from fastapi import HTTPException

from app.models.pay_component import PayComponentPercentTier

SOURCES = {"VENUE_MONTH_PLAN", "VENUE_DAY_PLAN", "DEPARTMENT_MONTH_PLAN", "DEPARTMENT_DAY_PLAN", "KPI_METRIC"}


def tier_dict(tier):
    return {
        "threshold_value": float(tier.threshold_value),
        "percent_bps": int(tier.percent_bps),
        "sort_order": int(tier.sort_order or 0),
    }


def excess_compatible(component_type, base_scope, source, departments, boost_departments):
    if source == "KPI_METRIC":
        return False
    if source.endswith("MONTH_PLAN") and base_scope != "FULL_PERIOD":
        return False
    if source.startswith("VENUE_"):
        return component_type == "PERCENT_TOTAL_REVENUE"
    return (
        component_type == "PERCENT_DEPARTMENT_REVENUE"
        and bool(departments)
        and set(departments) == set(boost_departments)
    )


def validate_tiers(tiers, *, base_percent, component_type, source, mode, base_scope, departments, boost_departments):
    if not tiers:
        return []
    if component_type not in {"PERCENT_TOTAL_REVENUE", "PERCENT_DEPARTMENT_REVENUE"} or source not in SOURCES:
        raise HTTPException(400, "Ступени доступны только для процента с выбранным источником порога")
    ordered = sorted(tiers, key=lambda row: Decimal(str(row.threshold_value)))
    seen, previous = set(), int(base_percent or 0)
    for row in ordered:
        threshold = Decimal(str(row.threshold_value))
        if threshold < 0 or threshold in seen or int(row.percent_bps) < previous:
            raise HTTPException(400, "Пороги должны быть уникальными и неотрицательными; процент не должен снижаться")
        seen.add(threshold)
        previous = int(row.percent_bps)
    if mode == "EXCESS_ONLY" and not excess_compatible(
        component_type, base_scope, source, departments, boost_departments
    ):
        raise HTTPException(400, "Для процента только на превышение база начисления должна совпадать с базой плана")
    return ordered


def normalize_payload_tiers(payload):
    """The old scalar fields remain readable, but explicit tiers are authoritative."""
    if "percent_tiers" not in payload.model_fields_set:
        return
    tiers = payload.percent_tiers or []
    payload.boost_enabled = bool(tiers)
    first = min(tiers, key=lambda row: row.threshold_value) if tiers else None
    payload.boost_percent_bps = first.percent_bps if first else None
    if first and payload.boost_source_type == "KPI_METRIC":
        payload.boost_threshold_value = int(first.threshold_value)


def sync_component_tiers(component, payload):
    from .component_calculations import _component_department_ids, _component_boost_department_ids
    from .percent_calculations import _component_base_scope

    fields = payload.model_fields_set
    existing = list(getattr(component, "percent_tiers", []) or [])
    explicit = "percent_tiers" in fields
    if explicit:
        tiers = payload.percent_tiers or []
    elif {"boost_percent_bps", "boost_threshold_value"} & fields or (not existing and component.boost_enabled):
        if len(existing) > 1:
            raise HTTPException(400, "Для изменения нескольких ступеней передайте percent_tiers")
        threshold = component.boost_threshold_value if component.boost_source_type == "KPI_METRIC" else 100
        tiers = (
            [PayComponentPercentTier(threshold_value=threshold, percent_bps=component.boost_percent_bps)]
            if component.boost_enabled and threshold is not None and component.boost_percent_bps is not None
            else []
        )
    else:
        tiers = existing
    departments = _component_department_ids(component)
    tiers = validate_tiers(
        tiers,
        base_percent=component.percent_bps,
        component_type=component.component_type,
        source=component.boost_source_type,
        mode=component.boost_recalc_mode,
        base_scope=_component_base_scope(component),
        departments=departments,
        boost_departments=_component_boost_department_ids(component, fallback_department_ids=departments),
    )
    # Reuse rows by threshold to avoid unique-key collisions on ordinary edits.
    by_threshold = {Decimal(str(row.threshold_value)): row for row in existing}
    rows = []
    for index, tier in enumerate(tiers):
        threshold = Decimal(str(tier.threshold_value))
        row = by_threshold.get(threshold) or PayComponentPercentTier(threshold_value=threshold)
        row.percent_bps = int(tier.percent_bps)
        row.sort_order = index
        rows.append(row)
    component.percent_tiers = rows
    if explicit:
        component.boost_enabled = bool(rows)
    if rows:
        component.boost_percent_bps = rows[0].percent_bps
        if component.boost_source_type == "KPI_METRIC":
            component.boost_threshold_value = int(rows[0].threshold_value)

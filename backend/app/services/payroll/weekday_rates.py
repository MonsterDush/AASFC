from __future__ import annotations

import json


WEEKDAY_TITLES = {
    0: "Понедельник",
    1: "Вторник",
    2: "Среда",
    3: "Четверг",
    4: "Пятница",
    5: "Суббота",
    6: "Воскресенье",
}

WEEKDAY_RATE_COMPONENT_TYPES = {"SALARY_HOURLY", "SALARY_PER_SHIFT"}


def normalize_weekday_rates(value: object) -> list[dict]:
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

    normalized_by_weekday: dict[int, dict] = {}
    for raw_item in value:
        item = raw_item
        if hasattr(item, "model_dump"):
            item = item.model_dump()
        elif hasattr(item, "dict"):
            item = item.dict()
        if not isinstance(item, dict):
            continue
        try:
            weekday = int(item.get("weekday"))
            rate_minor = int(item.get("rate_minor"))
        except (TypeError, ValueError):
            continue
        if weekday not in WEEKDAY_TITLES or rate_minor < 0:
            continue
        normalized_by_weekday[weekday] = {
            "weekday": weekday,
            "weekday_title": WEEKDAY_TITLES[weekday],
            "rate_minor": rate_minor,
        }
    return [normalized_by_weekday[weekday] for weekday in sorted(normalized_by_weekday)]


def dump_weekday_rates(value: object) -> str | None:
    rows = normalize_weekday_rates(value)
    if not rows:
        return None
    stored_rows = [{"weekday": row["weekday"], "rate_minor": row["rate_minor"]} for row in rows]
    return json.dumps(stored_rows, ensure_ascii=False)


def weekday_rates_map(value: object) -> dict[int, int]:
    return {int(row["weekday"]): int(row["rate_minor"]) for row in normalize_weekday_rates(value)}


def component_weekday_rates(component: object) -> list[dict]:
    return normalize_weekday_rates(getattr(component, "weekday_rates_json", None))


def salary_shift_rows(component: object, worked_shifts: list[object] | None) -> list[dict]:
    component_type = str(getattr(component, "component_type", "") or "").strip().upper()
    if component_type not in WEEKDAY_RATE_COMPONENT_TYPES:
        return []
    overrides = weekday_rates_map(getattr(component, "weekday_rates_json", None))
    if not overrides:
        return []
    base_rate_value = (
        getattr(component, "rate_minor", 0)
        if component_type == "SALARY_HOURLY"
        else getattr(component, "amount_minor", 0)
    )
    base_rate_minor = int(base_rate_value or 0)
    rows: list[dict] = []
    for shift in sorted(
        list(worked_shifts or []),
        key=lambda item: (item.shift_date, str(item.shift_slot or ""), int(item.shift_id)),
    ):
        weekday = int(shift.shift_date.weekday())
        applied_rate_minor = int(overrides.get(weekday, base_rate_minor))
        minutes = int(getattr(shift, "minutes", 0) or 0)
        amount_minor = (
            int((applied_rate_minor * minutes + 30) // 60) if component_type == "SALARY_HOURLY" else applied_rate_minor
        )
        rows.append(
            {
                "shift_id": int(shift.shift_id),
                "date": shift.shift_date.isoformat(),
                "shift_slot": str(shift.shift_slot or "DAY").upper(),
                "minutes": minutes,
                "weekday": weekday,
                "weekday_title": WEEKDAY_TITLES[weekday],
                "base_rate_minor": base_rate_minor,
                "applied_rate_minor": applied_rate_minor,
                "weekday_override_applied": weekday in overrides,
                "amount_minor": amount_minor,
            }
        )
    return rows


def calculate_weekday_rate_amount_minor(component: object, worked_shifts: list[object] | None) -> int:
    return int(sum(int(row["amount_minor"]) for row in salary_shift_rows(component, worked_shifts)))

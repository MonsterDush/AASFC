from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Adjustment


PAYROLL_ADJUSTMENT_TYPES = {"bonus", "penalty", "writeoff"}


def payroll_adjustment_signed_minor(adjustment_type: str | None, amount_rub: int | None) -> int:
    adjustment_type_norm = str(adjustment_type or "").strip().lower()
    if adjustment_type_norm not in PAYROLL_ADJUSTMENT_TYPES:
        return 0
    amount_minor = max(int(amount_rub or 0), 0) * 100
    return amount_minor if adjustment_type_norm == "bonus" else -amount_minor


def load_member_payroll_adjustments(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
) -> dict[int, list[dict]]:
    rows = db.execute(
        select(
            Adjustment.id,
            Adjustment.member_user_id,
            Adjustment.type,
            Adjustment.amount,
            Adjustment.date,
            Adjustment.reason,
        )
        .where(
            Adjustment.venue_id == int(venue_id),
            Adjustment.is_active.is_(True),
            Adjustment.member_user_id.is_not(None),
            Adjustment.date >= period_start,
            Adjustment.date <= period_end,
            Adjustment.type.in_(sorted(PAYROLL_ADJUSTMENT_TYPES)),
        )
        .order_by(Adjustment.date.asc(), Adjustment.id.asc())
    ).all()

    grouped: dict[int, list[dict]] = defaultdict(list)
    titles = {"bonus": "Премия", "penalty": "Штраф", "writeoff": "Списание"}
    for adjustment_id, member_user_id, adjustment_type, amount_rub, adjustment_date, reason in rows:
        adjustment_type_norm = str(adjustment_type or "").strip().lower()
        signed_minor = payroll_adjustment_signed_minor(adjustment_type_norm, amount_rub)
        if member_user_id is None or signed_minor == 0:
            continue
        grouped[int(member_user_id)].append(
            {
                "category": adjustment_type_norm,
                "source": "adjustment",
                "adjustment_id": int(adjustment_id),
                "component_type": adjustment_type_norm.upper(),
                "title": titles[adjustment_type_norm],
                "base_text": adjustment_date.strftime("%d.%m.%Y"),
                "formula_text": str(reason or "Добавлено вручную").strip()[:500],
                "amount_minor": int(signed_minor),
                "date": adjustment_date.isoformat(),
                "is_estimated": False,
            }
        )
    return dict(grouped)


def group_payroll_adjustment_net_by_date(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end: date,
) -> dict[date, int]:
    grouped = load_member_payroll_adjustments(
        db,
        venue_id=venue_id,
        period_start=period_start,
        period_end=period_end,
    )
    totals: dict[date, int] = defaultdict(int)
    for items in grouped.values():
        for item in items:
            totals[date.fromisoformat(str(item["date"]))] += int(item.get("amount_minor") or 0)
    return dict(totals)

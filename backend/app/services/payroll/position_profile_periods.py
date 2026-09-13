from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import PositionPayProfilePeriod, VenuePosition


class PositionPayProfilePeriodError(ValueError):
    pass


def period_contains(day: date, period: PositionPayProfilePeriod) -> bool:
    if not bool(period.is_active):
        return False
    if period.valid_from is not None and day < period.valid_from:
        return False
    if period.valid_to is not None and day > period.valid_to:
        return False
    return True


def load_position_profile_periods(
    db: Session,
    *,
    venue_id: int,
    position_ids: list[int] | None = None,
    include_inactive: bool = False,
) -> list[PositionPayProfilePeriod]:
    stmt = (
        select(PositionPayProfilePeriod)
        .options(selectinload(PositionPayProfilePeriod.pay_profile))
        .where(PositionPayProfilePeriod.venue_id == int(venue_id))
    )
    if position_ids is not None:
        if not position_ids:
            return []
        stmt = stmt.where(PositionPayProfilePeriod.venue_position_id.in_([int(item) for item in position_ids]))
    if not include_inactive:
        stmt = stmt.where(PositionPayProfilePeriod.is_active.is_(True))
    return (
        db.execute(
            stmt.order_by(
                PositionPayProfilePeriod.venue_position_id.asc(),
                PositionPayProfilePeriod.valid_from.asc().nullsfirst(),
                PositionPayProfilePeriod.id.asc(),
            )
        )
        .scalars()
        .all()
    )


def serialize_position_profile_period(period: PositionPayProfilePeriod) -> dict:
    profile = getattr(period, "pay_profile", None)
    return {
        "id": int(period.id),
        "pay_profile_id": int(period.pay_profile_id),
        "pay_profile_title": str(profile.title) if profile is not None else None,
        "valid_from": period.valid_from.isoformat() if period.valid_from is not None else None,
        "valid_to": period.valid_to.isoformat() if period.valid_to is not None else None,
        "is_active": bool(period.is_active),
    }


def _close_periods_from(
    periods: list[PositionPayProfilePeriod],
    *,
    effective_from: date,
) -> None:
    previous_day = effective_from - timedelta(days=1)
    now = datetime.utcnow()
    for period in periods:
        if not period.is_active:
            continue
        starts_before = period.valid_from is None or period.valid_from < effective_from
        reaches_effective_date = period.valid_to is None or period.valid_to >= effective_from
        if not reaches_effective_date:
            continue
        if starts_before:
            period.valid_to = previous_day
        else:
            # A period starting on/after the replacement date has never become
            # historical truth for the new schedule and is superseded.
            period.is_active = False
        period.updated_at = now


def set_position_pay_profile(
    db: Session,
    *,
    position: VenuePosition,
    pay_profile_id: int | None,
    effective_from: date | None,
    previous_member_user_id: int | None = None,
) -> PositionPayProfilePeriod | None:
    """Replace a position's payroll profile from one inclusive date.

    Stored payroll lines are intentionally left untouched. A later explicit
    payroll recalculation will pick up these periods.
    """

    if position.id is None:
        db.flush()
    if position.member_user_id is None:
        position.pay_profile_id = pay_profile_id
        return None

    start = effective_from or date.today()
    if start > date.today():
        raise PositionPayProfilePeriodError("Дата начала профиля не может быть в будущем")

    periods = load_position_profile_periods(
        db,
        venue_id=int(position.venue_id),
        position_ids=[int(position.id)],
    )
    current_member_id = int(position.member_user_id)
    old_member_id = int(previous_member_user_id) if previous_member_user_id is not None else current_member_id

    matching = next(
        (
            period
            for period in periods
            if int(period.member_user_id) == current_member_id
            and int(period.pay_profile_id) == int(pay_profile_id or 0)
            and period_contains(start, period)
            and period.valid_to is None
            and previous_member_user_id in (None, current_member_id)
        ),
        None,
    )
    has_later_period = any(
        period.is_active and period.valid_from is not None and period.valid_from > start for period in periods
    )
    if matching is not None and not has_later_period:
        position.pay_profile_id = pay_profile_id
        return matching

    relevant_periods = [period for period in periods if int(period.member_user_id) == old_member_id]
    _close_periods_from(relevant_periods, effective_from=start)

    position.pay_profile_id = pay_profile_id
    if pay_profile_id is None:
        return None

    created = PositionPayProfilePeriod(
        venue_id=int(position.venue_id),
        venue_position_id=int(position.id),
        member_user_id=current_member_id,
        pay_profile_id=int(pay_profile_id),
        valid_from=start,
        valid_to=None,
        is_active=True,
    )
    db.add(created)
    db.flush()
    return created


def close_position_pay_profile(
    db: Session,
    *,
    position: VenuePosition,
    valid_to: date | None = None,
) -> None:
    if position.id is None:
        return
    end = valid_to or date.today()
    periods = load_position_profile_periods(
        db,
        venue_id=int(position.venue_id),
        position_ids=[int(position.id)],
    )
    now = datetime.utcnow()
    for period in periods:
        if period.valid_to is not None and period.valid_to <= end:
            continue
        if period.valid_from is not None and period.valid_from > end:
            period.is_active = False
        else:
            period.valid_to = end
        period.updated_at = now

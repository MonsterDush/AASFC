from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import (
    DailyReport,
    PayProfile,
    PositionPayProfilePeriod,
    Shift,
    ShiftAssignment,
    ShiftInterval,
    User,
    VenuePosition,
)
from app.services.shifts import normalize_shift_slot

from .metric_loaders import interval_duration_minutes
from .payroll_types import PayrollMemberMetrics, PayrollWorkedShift
from .position_profile_periods import period_contains


@dataclass
class PayrollPositionContext:
    assignment: object | None
    profile: PayProfile
    member_user: User
    metrics: PayrollMemberMetrics = field(default_factory=PayrollMemberMetrics)
    position_ids: set[int] = field(default_factory=set)
    position_titles: set[str] = field(default_factory=set)
    profile_active_dates: set[date] = field(default_factory=set)
    profile_period_ids: set[int] = field(default_factory=set)
    assignment_ids: set[int] = field(default_factory=set)
    profile_sources: set[str] = field(default_factory=set)
    uses_effective_periods: bool = False


def _dates_between(start: date, end_excl: date) -> set[date]:
    dates: set[date] = set()
    cursor = start
    while cursor < end_excl:
        dates.add(cursor)
        cursor += timedelta(days=1)
    return dates


def _period_dates(
    period: PositionPayProfilePeriod,
    *,
    month_start: date,
    month_end_excl: date,
) -> set[date]:
    start = max(month_start, period.valid_from or month_start)
    end_excl = min(month_end_excl, (period.valid_to + timedelta(days=1)) if period.valid_to else month_end_excl)
    return _dates_between(start, end_excl) if start < end_excl else set()


def load_position_payroll_contexts(
    db: Session,
    *,
    venue_id: int,
    month_start: date,
    month_end_excl: date,
    fallback_assignments: list[tuple],
    warnings: list[dict] | None = None,
) -> list[PayrollPositionContext]:
    """Split metrics by the profile effective for every employee-position date."""

    fallback_by_member: dict[int, list[tuple]] = {}
    for assignment, profile, member_user in fallback_assignments:
        fallback_by_member.setdefault(int(assignment.member_user_id), []).append(
            (assignment, profile, member_user)
        )
    profile_by_id = {int(profile.id): profile for _assignment, profile, _member in fallback_assignments}
    member_by_id = {int(member.id): member for _assignment, _profile, member in fallback_assignments}

    active_position_rows = db.execute(
        select(VenuePosition, User)
        .join(User, User.id == VenuePosition.member_user_id)
        .where(
            VenuePosition.venue_id == int(venue_id),
            VenuePosition.member_user_id.is_not(None),
            VenuePosition.is_active.is_(True),
        )
        .order_by(VenuePosition.id.asc())
    ).all()
    member_by_id.update({int(member.id): member for _position, member in active_position_rows})
    active_position_member_ids = {int(member.id) for _position, member in active_position_rows}

    position_ids_with_periods = {
        int(position_id)
        for position_id in db.execute(
            select(PositionPayProfilePeriod.venue_position_id)
            .where(
                PositionPayProfilePeriod.venue_id == int(venue_id),
                PositionPayProfilePeriod.is_active.is_(True),
            )
            .distinct()
        ).scalars()
    }
    period_rows = db.execute(
        select(PositionPayProfilePeriod, VenuePosition, User)
        .join(VenuePosition, VenuePosition.id == PositionPayProfilePeriod.venue_position_id)
        .join(User, User.id == PositionPayProfilePeriod.member_user_id)
        .where(
            PositionPayProfilePeriod.venue_id == int(venue_id),
            PositionPayProfilePeriod.is_active.is_(True),
            or_(
                PositionPayProfilePeriod.valid_from.is_(None),
                PositionPayProfilePeriod.valid_from < month_end_excl,
            ),
            or_(
                PositionPayProfilePeriod.valid_to.is_(None),
                PositionPayProfilePeriod.valid_to >= month_start,
            ),
        )
        .order_by(PositionPayProfilePeriod.venue_position_id.asc(), PositionPayProfilePeriod.id.asc())
    ).all()
    periods_by_position: dict[int, list[PositionPayProfilePeriod]] = {}
    period_member_ids: set[int] = set()
    for period, position, member in period_rows:
        periods_by_position.setdefault(int(period.venue_position_id), []).append(period)
        period_member_ids.add(int(member.id))
        member_by_id[int(member.id)] = member

    fallback_member_ids = {
        int(position.member_user_id)
        for position, _member in active_position_rows
        if int(position.id) not in position_ids_with_periods and position.pay_profile_id is None
    }

    missing_profile_ids = sorted(
        {
            int(position.pay_profile_id)
            for position, _member in active_position_rows
            if int(position.id) not in position_ids_with_periods
            and position.pay_profile_id is not None
            and int(position.pay_profile_id) not in profile_by_id
        }
        | {
            int(period.pay_profile_id)
            for period, _position, _member in period_rows
            if int(period.pay_profile_id) not in profile_by_id
        }
    )
    if missing_profile_ids:
        profiles = (
            db.execute(
                select(PayProfile).where(
                    PayProfile.venue_id == int(venue_id),
                    PayProfile.id.in_(missing_profile_ids),
                )
            )
            .scalars()
            .all()
        )
        profile_by_id.update({int(profile.id): profile for profile in profiles})

    contexts: dict[tuple[int, int], PayrollPositionContext] = {}

    def ensure_context(*, member_user_id: int, profile_id: int) -> PayrollPositionContext | None:
        profile = profile_by_id.get(int(profile_id))
        member = member_by_id.get(int(member_user_id))
        if profile is None or member is None:
            return None
        key = (int(member_user_id), int(profile_id))
        if key not in contexts:
            fallback = next(
                (
                    row
                    for row in fallback_by_member.get(int(member_user_id), [])
                    if int(row[1].id) == int(profile_id)
                ),
                None,
            )
            contexts[key] = PayrollPositionContext(
                assignment=fallback[0] if fallback is not None else None,
                profile=profile,
                member_user=member,
            )
        return contexts[key]

    month_dates = _dates_between(month_start, month_end_excl)

    for period, position, member in period_rows:
        active_dates = _period_dates(period, month_start=month_start, month_end_excl=month_end_excl)
        if not active_dates:
            continue
        context = ensure_context(member_user_id=int(member.id), profile_id=int(period.pay_profile_id))
        if context is None:
            continue
        context.position_ids.add(int(position.id))
        if position.title:
            context.position_titles.add(str(position.title).strip())
        context.profile_active_dates.update(active_dates)
        context.profile_period_ids.add(int(period.id))
        context.profile_sources.add("POSITION_PERIOD")
        context.uses_effective_periods = True

    for position, member in active_position_rows:
        if int(position.id) in position_ids_with_periods:
            continue
        if position.pay_profile_id is None:
            continue
        context = ensure_context(member_user_id=int(member.id), profile_id=int(position.pay_profile_id))
        if context is not None:
            context.position_ids.add(int(position.id))
            context.position_titles.add(str(position.title or "").strip())
            context.profile_active_dates.update(month_dates)
            context.profile_sources.add("POSITION_LEGACY")

    for assignment, profile, member in fallback_assignments:
        member_user_id = int(member.id)
        if (
            member_user_id not in active_position_member_ids and member_user_id not in period_member_ids
        ) or member_user_id in fallback_member_ids:
            context = ensure_context(member_user_id=member_user_id, profile_id=int(profile.id))
            if context is not None:
                start = max(month_start, assignment.start_date or month_start)
                end_excl = min(
                    month_end_excl,
                    (assignment.end_date + timedelta(days=1)) if assignment.end_date else month_end_excl,
                )
                if start < end_excl:
                    context.profile_active_dates.update(_dates_between(start, end_excl))
                    context.assignment_ids.add(int(assignment.id))
                    context.profile_sources.add("MEMBER_FALLBACK")

    shift_rows = db.execute(
        select(
            ShiftAssignment.member_user_id,
            ShiftAssignment.venue_position_id,
            VenuePosition.title.label("position_title"),
            VenuePosition.pay_profile_id.label("position_pay_profile_id"),
            Shift.id.label("shift_id"),
            Shift.date.label("shift_date"),
            Shift.shift_slot.label("shift_slot"),
            ShiftInterval.start_time,
            ShiftInterval.end_time,
        )
        .join(Shift, Shift.id == ShiftAssignment.shift_id)
        .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
        .join(VenuePosition, VenuePosition.id == ShiftAssignment.venue_position_id)
        .join(
            DailyReport,
            and_(
                DailyReport.venue_id == Shift.venue_id,
                DailyReport.date == Shift.date,
                DailyReport.shift_slot == Shift.shift_slot,
                DailyReport.status == "CLOSED",
            ),
        )
        .where(
            Shift.venue_id == int(venue_id),
            Shift.is_active.is_(True),
            Shift.date >= month_start,
            Shift.date < month_end_excl,
        )
        .order_by(Shift.id.asc())
    ).all()

    shift_profile_ids = {
        int(row.position_pay_profile_id) for row in shift_rows if row.position_pay_profile_id is not None
    }
    missing_shift_profile_ids = sorted(shift_profile_ids - set(profile_by_id))
    if missing_shift_profile_ids:
        profiles = (
            db.execute(
                select(PayProfile).where(
                    PayProfile.venue_id == int(venue_id),
                    PayProfile.id.in_(missing_shift_profile_ids),
                )
            )
            .scalars()
            .all()
        )
        profile_by_id.update({int(profile.id): profile for profile in profiles})

    shift_member_ids = {int(row.member_user_id) for row in shift_rows}
    missing_shift_member_ids = sorted(shift_member_ids - set(member_by_id))
    if missing_shift_member_ids:
        members = db.execute(select(User).where(User.id.in_(missing_shift_member_ids))).scalars().all()
        member_by_id.update({int(member.id): member for member in members})

    seen_shifts_by_context: dict[tuple[int, int], set[int]] = {}
    unresolved_seen: set[tuple[int, int, int]] = set()

    def add_unresolved_warning(row, *, attempted_profile_id: int | None = None) -> None:
        key = (int(row.member_user_id), int(row.shift_id), int(row.venue_position_id))
        if warnings is None or key in unresolved_seen:
            return
        unresolved_seen.add(key)
        warnings.append(
            {
                "code": "PAY_PROFILE_UNRESOLVED",
                "member_user_id": int(row.member_user_id),
                "shift_id": int(row.shift_id),
                "venue_position_id": int(row.venue_position_id),
                "shift_date": row.shift_date.isoformat(),
                "shift_slot": normalize_shift_slot(row.shift_slot),
                "attempted_pay_profile_id": attempted_profile_id,
            }
        )

    for row in shift_rows:
        member_user_id = int(row.member_user_id)
        position_id = int(row.venue_position_id)
        position_periods = periods_by_position.get(position_id, [])
        position_has_periods = position_id in position_ids_with_periods
        matching_period = next(
            (
                period
                for period in position_periods
                if int(period.member_user_id) == member_user_id and period_contains(row.shift_date, period)
            ),
            None,
        )
        profile_id = int(matching_period.pay_profile_id) if matching_period is not None else None
        if profile_id is None and not position_has_periods and row.position_pay_profile_id is not None:
            profile_id = int(row.position_pay_profile_id)
        matching_fallback = None
        if profile_id is None and not position_has_periods:
            matching_fallback = next(
                (
                    item
                    for item in reversed(fallback_by_member.get(member_user_id, []))
                    if (item[0].start_date is None or item[0].start_date <= row.shift_date)
                    and (item[0].end_date is None or item[0].end_date >= row.shift_date)
                ),
                None,
            )
            profile_id = int(matching_fallback[1].id) if matching_fallback is not None else None
        if profile_id is None:
            add_unresolved_warning(row)
            continue
        context = ensure_context(member_user_id=member_user_id, profile_id=profile_id)
        if context is None:
            add_unresolved_warning(row, attempted_profile_id=profile_id)
            continue
        context.position_ids.add(int(row.venue_position_id))
        if row.position_title:
            context.position_titles.add(str(row.position_title).strip())
        if matching_period is not None:
            context.profile_sources.add("POSITION_PERIOD")
            context.profile_period_ids.add(int(matching_period.id))
        elif row.position_pay_profile_id is not None and not position_has_periods:
            context.profile_sources.add("POSITION_LEGACY")
        elif matching_fallback is not None:
            context.profile_sources.add("MEMBER_FALLBACK")
            context.assignment_ids.add(int(matching_fallback[0].id))
        key = (member_user_id, profile_id)
        seen_shift_ids = seen_shifts_by_context.setdefault(key, set())
        shift_id = int(row.shift_id)
        if shift_id in seen_shift_ids:
            continue
        seen_shift_ids.add(shift_id)
        minutes = interval_duration_minutes(row.start_time, row.end_time)
        context.metrics.minutes_total += int(minutes)
        context.metrics.worked_dates.add(row.shift_date)
        context.metrics.worked_shifts.append(
            PayrollWorkedShift(
                shift_id=shift_id,
                shift_date=row.shift_date,
                shift_slot=normalize_shift_slot(row.shift_slot),
                minutes=int(minutes),
            )
        )
        context.metrics.shifts_count += 1

    return sorted(
        contexts.values(),
        key=lambda item: (int(item.member_user.id), int(item.profile.id)),
    )

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import DailyReport, PayProfile, Shift, ShiftAssignment, ShiftInterval, User, VenuePosition
from app.services.shifts import normalize_shift_slot

from .metric_loaders import interval_duration_minutes
from .payroll_types import PayrollMemberMetrics, PayrollWorkedShift


@dataclass
class PayrollPositionContext:
    assignment: object | None
    profile: PayProfile
    member_user: User
    metrics: PayrollMemberMetrics = field(default_factory=PayrollMemberMetrics)
    position_ids: set[int] = field(default_factory=set)
    position_titles: set[str] = field(default_factory=set)


def load_position_payroll_contexts(
    db: Session,
    *,
    venue_id: int,
    month_start: date,
    month_end_excl: date,
    fallback_assignments: list[tuple],
) -> list[PayrollPositionContext]:
    """Split one member's metrics by the position selected on each shift.

    ``VenuePosition.pay_profile_id`` is authoritative. A legacy/current member
    profile assignment is used only when the selected position has no profile.
    """

    fallback_by_member = {
        int(assignment.member_user_id): (assignment, profile, member_user)
        for assignment, profile, member_user in fallback_assignments
    }
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
    fallback_member_ids = {
        int(position.member_user_id) for position, _member in active_position_rows if position.pay_profile_id is None
    }

    missing_profile_ids = sorted(
        {
            int(position.pay_profile_id)
            for position, _member in active_position_rows
            if position.pay_profile_id is not None and int(position.pay_profile_id) not in profile_by_id
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
            fallback = fallback_by_member.get(int(member_user_id))
            contexts[key] = PayrollPositionContext(
                assignment=fallback[0] if fallback is not None else None,
                profile=profile,
                member_user=member,
            )
        return contexts[key]

    for position, member in active_position_rows:
        if position.pay_profile_id is None:
            continue
        context = ensure_context(member_user_id=int(member.id), profile_id=int(position.pay_profile_id))
        if context is not None:
            context.position_ids.add(int(position.id))
            context.position_titles.add(str(position.title or "").strip())

    for assignment, profile, member in fallback_assignments:
        member_user_id = int(member.id)
        if member_user_id not in active_position_member_ids or member_user_id in fallback_member_ids:
            ensure_context(member_user_id=member_user_id, profile_id=int(profile.id))

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
    for row in shift_rows:
        member_user_id = int(row.member_user_id)
        profile_id = int(row.position_pay_profile_id) if row.position_pay_profile_id is not None else None
        if profile_id is None:
            fallback = fallback_by_member.get(member_user_id)
            profile_id = int(fallback[1].id) if fallback is not None else None
        if profile_id is None:
            continue
        context = ensure_context(member_user_id=member_user_id, profile_id=profile_id)
        if context is None:
            continue
        context.position_ids.add(int(row.venue_position_id))
        if row.position_title:
            context.position_titles.add(str(row.position_title).strip())
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

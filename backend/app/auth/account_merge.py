from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permission_codes import parse_permission_codes, unique_permission_codes
from app.models import (
    Adjustment,
    AdjustmentDispute,
    AdjustmentDisputeComment,
    AuthIdentity,
    BalanceAdjustment,
    DailyReport,
    DailyReportAttachment,
    DailyReportAudit,
    DailyReportTipAllocation,
    Expense,
    NotificationDeliveryLog,
    PayProfileAssignment,
    PaymentMethodTransfer,
    PayrollLine,
    PayrollRecalculationLog,
    PayrollRun,
    RecurringExpenseRule,
    Shift,
    ShiftAssignment,
    ShiftAvailability,
    ShiftComment,
    ShiftSwapRequest,
    User,
    VenueInvite,
    VenueMember,
    VenuePosition,
)
from app.models.bonus import Bonus
from app.models.penalty import Penalty
from app.models.writeoff import Writeoff


_PHONE_PROVIDER = "PHONE"
_TELEGRAM_PROVIDER = "TELEGRAM"


def merge_user_accounts(
    db: Session,
    *,
    target_user: User,
    source_user: User,
) -> User:
    """Merge ``source_user`` into ``target_user``.

    The current authenticated user should normally be passed as ``target_user`` so
    the active session remains valid after the merge.
    """
    if target_user is None or source_user is None:
        raise ValueError("Both target_user and source_user are required")
    if int(target_user.id) == int(source_user.id):
        return target_user

    target_had_telegram = bool(getattr(target_user, "tg_user_id", None))
    source_had_telegram = bool(getattr(source_user, "tg_user_id", None))

    _merge_user_profile(target_user=target_user, source_user=source_user)
    if not target_had_telegram and source_had_telegram:
        _copy_notification_settings(target_user=target_user, source_user=source_user)

    _merge_auth_identities(db, target_user=target_user, source_user=source_user)
    _merge_venue_members(db, target_user=target_user, source_user=source_user)
    position_map = _merge_venue_positions(db, target_user=target_user, source_user=source_user)
    _merge_shift_assignments(db, target_user=target_user, source_user=source_user, position_map=position_map)
    _merge_shift_availabilities(db, target_user=target_user, source_user=source_user)
    _merge_shift_swap_refs(db, target_user=target_user, source_user=source_user)
    _merge_pay_profile_assignments(db, target_user=target_user, source_user=source_user)
    _merge_tip_allocations(db, target_user=target_user, source_user=source_user)
    _merge_payroll_lines(db, target_user=target_user, source_user=source_user)

    _bulk_reassign_user_ref(db, Adjustment, "member_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Adjustment, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Adjustment, "updated_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, AdjustmentDispute, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, AdjustmentDispute, "resolved_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, AdjustmentDisputeComment, "author_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, BalanceAdjustment, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Bonus, "member_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Bonus, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, DailyReport, "closed_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, DailyReport, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, DailyReport, "updated_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, DailyReportAttachment, "uploaded_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, DailyReportAudit, "user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Expense, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, NotificationDeliveryLog, "user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, PaymentMethodTransfer, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, PayrollRecalculationLog, "triggered_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, PayrollRun, "calculated_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Penalty, "member_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Penalty, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, RecurringExpenseRule, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Shift, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, ShiftComment, "author_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, ShiftSwapRequest, "decided_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, VenueInvite, "accepted_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, VenueInvite, "created_by_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Writeoff, "member_user_id", source_user.id, target_user.id)
    _bulk_reassign_user_ref(db, Writeoff, "created_by_user_id", source_user.id, target_user.id)

    db.flush()

    source_user.tg_user_id = None
    source_user.tg_username = None
    db.query(AuthIdentity).filter(AuthIdentity.user_id == int(source_user.id)).delete(synchronize_session=False)
    db.flush()
    db.delete(source_user)
    db.flush()
    db.refresh(target_user)
    return target_user


def _merge_user_profile(*, target_user: User, source_user: User) -> None:
    if not getattr(target_user, "full_name", None) and getattr(source_user, "full_name", None):
        target_user.full_name = source_user.full_name
    if not getattr(target_user, "short_name", None) and getattr(source_user, "short_name", None):
        target_user.short_name = source_user.short_name
    if not getattr(target_user, "tg_username", None) and getattr(source_user, "tg_username", None):
        target_user.tg_username = source_user.tg_username

    if not getattr(target_user, "password_hash", None) and getattr(source_user, "password_hash", None):
        target_user.password_hash = source_user.password_hash
        target_user.password_set_at = source_user.password_set_at
        target_user.password_changed_at = source_user.password_changed_at

    target_role = str(getattr(target_user, "system_role", "") or "NONE").upper()
    source_role = str(getattr(source_user, "system_role", "") or "NONE").upper()
    if "SUPER_ADMIN" in {target_role, source_role}:
        target_user.system_role = "SUPER_ADMIN"
    elif target_role in {"", "NONE"} and source_role not in {"", "NONE"}:
        target_user.system_role = source_role


def _copy_notification_settings(*, target_user: User, source_user: User) -> None:
    fields = [
        "notify_enabled",
        "notify_adjustments",
        "notify_shifts",
        "notify_shift_comments",
        "notify_day_economics",
        "notify_salary",
        "notify_soft_alerts",
        "shift_reminder_lead_time_hours",
        "notification_detail_level",
    ]
    for field in fields:
        setattr(target_user, field, getattr(source_user, field))


def _merge_auth_identities(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = db.execute(
        select(AuthIdentity).where(AuthIdentity.user_id == int(target_user.id)).order_by(AuthIdentity.id.asc())
    ).scalars().all()
    source_rows = db.execute(
        select(AuthIdentity).where(AuthIdentity.user_id == int(source_user.id)).order_by(AuthIdentity.id.asc())
    ).scalars().all()
    target_by_provider = {str(row.provider or "").upper(): row for row in target_rows}

    for row in source_rows:
        provider = str(row.provider or "").upper()
        existing = target_by_provider.get(provider)
        if existing is None:
            row.user_id = int(target_user.id)
            target_by_provider[provider] = row
        else:
            existing.is_verified = bool(existing.is_verified or row.is_verified)
            if provider == _PHONE_PROVIDER:
                if row.phone_e164 and (not existing.phone_e164 or existing.phone_e164 == row.phone_e164):
                    existing.phone_e164 = row.phone_e164
            if provider == _TELEGRAM_PROVIDER:
                if row.provider_user_id and not existing.provider_user_id:
                    existing.provider_user_id = row.provider_user_id
            db.delete(row)

    db.flush()


def _merge_venue_members(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = db.execute(
        select(VenueMember).where(VenueMember.user_id == int(target_user.id)).order_by(VenueMember.id.asc())
    ).scalars().all()
    source_rows = db.execute(
        select(VenueMember).where(VenueMember.user_id == int(source_user.id)).order_by(VenueMember.id.asc())
    ).scalars().all()
    by_venue = {int(row.venue_id): row for row in target_rows}

    for row in source_rows:
        existing = by_venue.get(int(row.venue_id))
        if existing is None:
            row.user_id = int(target_user.id)
            by_venue[int(row.venue_id)] = row
            continue
        existing.is_active = bool(existing.is_active or row.is_active)
        existing.venue_role = _prefer_venue_role(existing.venue_role, row.venue_role)
        db.delete(row)

    db.flush()


def _merge_venue_positions(db: Session, *, target_user: User, source_user: User) -> dict[int, int]:
    target_rows = db.execute(
        select(VenuePosition).where(VenuePosition.member_user_id == int(target_user.id)).order_by(VenuePosition.id.asc())
    ).scalars().all()
    source_rows = db.execute(
        select(VenuePosition).where(VenuePosition.member_user_id == int(source_user.id)).order_by(VenuePosition.id.asc())
    ).scalars().all()

    by_venue = {int(row.venue_id): row for row in target_rows}
    position_map: dict[int, int] = {int(row.id): int(row.id) for row in target_rows}

    for row in source_rows:
        existing = by_venue.get(int(row.venue_id))
        if existing is None:
            row.member_user_id = int(target_user.id)
            by_venue[int(row.venue_id)] = row
            position_map[int(row.id)] = int(row.id)
            continue

        if not existing.title and row.title:
            existing.title = row.title
        if int(getattr(existing, "rate", 0) or 0) == 0 and int(getattr(row, "rate", 0) or 0) > 0:
            existing.rate = row.rate
        if int(getattr(existing, "percent", 0) or 0) == 0 and int(getattr(row, "percent", 0) or 0) > 0:
            existing.percent = row.percent
        existing.is_active = bool(existing.is_active or row.is_active)

        merged_codes = unique_permission_codes(
            list(parse_permission_codes(getattr(existing, "permission_codes", None)))
            + list(parse_permission_codes(getattr(row, "permission_codes", None)))
        )
        existing.permission_codes = json.dumps(merged_codes, ensure_ascii=False) if merged_codes else None
        position_map[int(row.id)] = int(existing.id)
        assignment_rows = db.execute(
            select(ShiftAssignment).where(ShiftAssignment.venue_position_id == int(row.id))
        ).scalars().all()
        for assignment in assignment_rows:
            assignment.venue_position_id = int(existing.id)
        swap_rows = db.execute(
            select(ShiftSwapRequest).where(
                ShiftSwapRequest.replacement_position_id == int(row.id)
            )
        ).scalars().all()
        for swap_request in swap_rows:
            swap_request.replacement_position_id = int(existing.id)
        db.delete(row)

    db.flush()
    return position_map


def _merge_shift_assignments(
    db: Session,
    *,
    target_user: User,
    source_user: User,
    position_map: dict[int, int],
) -> None:
    target_rows = db.execute(
        select(ShiftAssignment).where(ShiftAssignment.member_user_id == int(target_user.id)).order_by(ShiftAssignment.id.asc())
    ).scalars().all()
    source_rows = db.execute(
        select(ShiftAssignment).where(ShiftAssignment.member_user_id == int(source_user.id)).order_by(ShiftAssignment.id.asc())
    ).scalars().all()
    by_shift = {int(row.shift_id): row for row in target_rows}

    for row in source_rows:
        desired_position_id = position_map.get(int(row.venue_position_id), int(row.venue_position_id))
        existing = by_shift.get(int(row.shift_id))
        if existing is None:
            row.member_user_id = int(target_user.id)
            row.venue_position_id = int(desired_position_id)
            by_shift[int(row.shift_id)] = row
            continue

        if desired_position_id and int(existing.venue_position_id) != int(desired_position_id):
            existing.venue_position_id = int(desired_position_id)
        if existing.reminder_sent_at is None and row.reminder_sent_at is not None:
            existing.reminder_sent_at = row.reminder_sent_at
        db.delete(row)

    db.flush()


def _merge_shift_availabilities(
    db: Session,
    *,
    target_user: User,
    source_user: User,
) -> None:
    target_rows = db.execute(
        select(ShiftAvailability)
        .where(ShiftAvailability.member_user_id == int(target_user.id))
        .order_by(ShiftAvailability.id.asc())
    ).scalars().all()
    source_rows = db.execute(
        select(ShiftAvailability)
        .where(ShiftAvailability.member_user_id == int(source_user.id))
        .order_by(ShiftAvailability.id.asc())
    ).scalars().all()
    target_keys = {
        (int(row.venue_id), row.date, str(row.shift_slot)): row
        for row in target_rows
    }
    for row in source_rows:
        key = (int(row.venue_id), row.date, str(row.shift_slot))
        existing = target_keys.get(key)
        if existing is None:
            row.member_user_id = int(target_user.id)
            target_keys[key] = row
            continue
        if not existing.comment and row.comment:
            existing.comment = row.comment
        db.delete(row)
    db.flush()


def _merge_shift_swap_refs(
    db: Session,
    *,
    target_user: User,
    source_user: User,
) -> None:
    rows = db.execute(
        select(ShiftSwapRequest).where(
            (ShiftSwapRequest.requester_user_id == int(source_user.id))
            | (ShiftSwapRequest.replacement_user_id == int(source_user.id))
        )
    ).scalars().all()
    for row in rows:
        requester_id = (
            int(target_user.id)
            if int(row.requester_user_id) == int(source_user.id)
            else int(row.requester_user_id)
        )
        replacement_id = (
            int(target_user.id)
            if row.replacement_user_id is not None
            and int(row.replacement_user_id) == int(source_user.id)
            else row.replacement_user_id
        )
        row.requester_user_id = requester_id
        if replacement_id is not None and int(replacement_id) == requester_id:
            row.replacement_user_id = None
            row.replacement_position_id = None
        else:
            row.replacement_user_id = replacement_id
    db.flush()


def _merge_pay_profile_assignments(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = db.execute(
        select(PayProfileAssignment).where(PayProfileAssignment.member_user_id == int(target_user.id)).order_by(PayProfileAssignment.id.asc())
    ).scalars().all()
    source_rows = db.execute(
        select(PayProfileAssignment).where(PayProfileAssignment.member_user_id == int(source_user.id)).order_by(PayProfileAssignment.id.asc())
    ).scalars().all()

    keys = {
        _pay_profile_assignment_key(row)
        for row in target_rows
    }
    for row in source_rows:
        key = _pay_profile_assignment_key(row)
        if key in keys:
            db.delete(row)
            continue
        row.member_user_id = int(target_user.id)
        keys.add(key)

    db.flush()


def _merge_tip_allocations(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = db.execute(
        select(DailyReportTipAllocation).where(DailyReportTipAllocation.user_id == int(target_user.id)).order_by(DailyReportTipAllocation.id.asc())
    ).scalars().all()
    source_rows = db.execute(
        select(DailyReportTipAllocation).where(DailyReportTipAllocation.user_id == int(source_user.id)).order_by(DailyReportTipAllocation.id.asc())
    ).scalars().all()
    by_report = {int(row.report_id): row for row in target_rows}

    for row in source_rows:
        existing = by_report.get(int(row.report_id))
        if existing is None:
            row.user_id = int(target_user.id)
            by_report[int(row.report_id)] = row
            continue
        existing.amount = int(existing.amount or 0) + int(row.amount or 0)
        if not existing.meta_json and row.meta_json:
            existing.meta_json = row.meta_json
        if (not existing.split_mode or existing.split_mode == "EQUAL") and row.split_mode:
            existing.split_mode = row.split_mode
        db.delete(row)

    db.flush()


def _merge_payroll_lines(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = db.execute(
        select(PayrollLine).where(PayrollLine.member_user_id == int(target_user.id)).order_by(PayrollLine.id.asc())
    ).scalars().all()
    source_rows = db.execute(
        select(PayrollLine).where(PayrollLine.member_user_id == int(source_user.id)).order_by(PayrollLine.id.asc())
    ).scalars().all()
    by_run = {int(row.payroll_run_id): row for row in target_rows}
    affected_runs: set[int] = set()

    for row in source_rows:
        run_id = int(row.payroll_run_id)
        existing = by_run.get(run_id)
        if existing is None:
            row.member_user_id = int(target_user.id)
            by_run[run_id] = row
            affected_runs.add(run_id)
            continue
        existing.amount_minor = int(existing.amount_minor or 0) + int(row.amount_minor or 0)
        if not existing.pay_profile_id and row.pay_profile_id:
            existing.pay_profile_id = row.pay_profile_id
        if not existing.breakdown_json and row.breakdown_json:
            existing.breakdown_json = row.breakdown_json
        db.delete(row)
        affected_runs.add(run_id)

    db.flush()

    for run_id in affected_runs:
        lines_count, total_amount_minor = db.execute(
            select(func.count(PayrollLine.id), func.coalesce(func.sum(PayrollLine.amount_minor), 0))
            .where(PayrollLine.payroll_run_id == int(run_id))
        ).one()
        run = db.execute(select(PayrollRun).where(PayrollRun.id == int(run_id))).scalar_one_or_none()
        if run is None:
            continue
        run.lines_count = int(lines_count or 0)
        run.total_amount_minor = int(total_amount_minor or 0)

    db.flush()


def _prefer_venue_role(first: str | None, second: str | None) -> str:
    a = str(first or "STAFF").upper()
    b = str(second or "STAFF").upper()
    order = {"OWNER": 2, "STAFF": 1}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def _pay_profile_assignment_key(row: PayProfileAssignment) -> tuple[int, int, object, object, bool]:
    return (
        int(row.venue_id),
        int(row.pay_profile_id),
        row.start_date,
        row.end_date,
        bool(row.is_active),
    )


def _bulk_reassign_user_ref(db: Session, model, column_name: str, source_user_id: int, target_user_id: int) -> None:
    column = getattr(model, column_name)
    db.query(model).filter(column == int(source_user_id)).update(
        {column: int(target_user_id)},
        synchronize_session=False,
    )

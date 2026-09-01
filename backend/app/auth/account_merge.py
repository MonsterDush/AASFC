from __future__ import annotations

import json
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.permission_codes import parse_permission_codes
from app.models import (
    Adjustment,
    AdjustmentDispute,
    AdjustmentDisputeComment,
    AuthIdentity,
    BalanceAdjustment,
    BillingPromoCode,
    BillingReconciliationIssue,
    DailyReport,
    DailyReportAttachment,
    DailyReportAudit,
    DailyReportTipAllocation,
    DemoEvent,
    Expense,
    ExpenseAttachment,
    NotificationDeliveryLog,
    PayProfileAssignment,
    PaymentMethodTransfer,
    PayrollLine,
    PayrollRecalculationLog,
    PayrollRun,
    PositionPermissionTemplate,
    QuickRestoConnection,
    QuickRestoImportIssue,
    QuickRestoImportIssueAudit,
    QuickRestoSalePlaceScope,
    QuickRestoScopeAudit,
    QuickRestoSyncRun,
    RecurringExpenseRule,
    Shift,
    ShiftAssignment,
    ShiftAvailability,
    ShiftComment,
    ShiftCommentMention,
    ShiftScheduleTemplate,
    ShiftSwapRequest,
    User,
    VenueInvite,
    VenueBillingEvent,
    VenueBillingTransaction,
    VenueMember,
    VenuePosition,
    VenueSetupState,
)
from app.models.bonus import Bonus
from app.models.penalty import Penalty
from app.models.writeoff import Writeoff
from app.services.venue_member_names import normalize_owner_note


_PHONE_PROVIDER = "PHONE"
_TELEGRAM_PROVIDER = "TELEGRAM"


_DIRECT_USER_REF_REASSIGNMENTS = (
    (Adjustment, "member_user_id"),
    (Adjustment, "created_by_user_id"),
    (Adjustment, "updated_by_user_id"),
    (AdjustmentDispute, "created_by_user_id"),
    (AdjustmentDispute, "resolved_by_user_id"),
    (AdjustmentDisputeComment, "author_user_id"),
    (BalanceAdjustment, "created_by_user_id"),
    (BillingPromoCode, "created_by_user_id"),
    (BillingReconciliationIssue, "resolved_by_user_id"),
    (Bonus, "member_user_id"),
    (Bonus, "created_by_user_id"),
    (DailyReport, "closed_by_user_id"),
    (DailyReport, "created_by_user_id"),
    (DailyReport, "updated_by_user_id"),
    (DailyReportAttachment, "uploaded_by_user_id"),
    (DailyReportAudit, "user_id"),
    (DemoEvent, "user_id"),
    (Expense, "created_by_user_id"),
    (ExpenseAttachment, "uploaded_by_user_id"),
    (NotificationDeliveryLog, "user_id"),
    (PaymentMethodTransfer, "created_by_user_id"),
    (PayrollRecalculationLog, "triggered_by_user_id"),
    (PayrollRun, "calculated_by_user_id"),
    (Penalty, "member_user_id"),
    (Penalty, "created_by_user_id"),
    (PositionPermissionTemplate, "created_by_user_id"),
    (PositionPermissionTemplate, "updated_by_user_id"),
    (QuickRestoConnection, "created_by_user_id"),
    (QuickRestoConnection, "scope_confirmed_by_user_id"),
    (QuickRestoConnection, "updated_by_user_id"),
    (QuickRestoImportIssue, "resolved_by_user_id"),
    (QuickRestoImportIssueAudit, "actor_user_id"),
    (QuickRestoSalePlaceScope, "confirmed_by_user_id"),
    (QuickRestoScopeAudit, "actor_user_id"),
    (QuickRestoSyncRun, "requested_by_user_id"),
    (RecurringExpenseRule, "created_by_user_id"),
    (Shift, "created_by_user_id"),
    (ShiftComment, "author_user_id"),
    (ShiftScheduleTemplate, "created_by_user_id"),
    (ShiftSwapRequest, "decided_by_user_id"),
    (VenueBillingEvent, "created_by_user_id"),
    (VenueBillingTransaction, "created_by_user_id"),
    (VenueInvite, "accepted_user_id"),
    (VenueInvite, "created_by_user_id"),
    (VenueSetupState, "last_seen_by_user_id"),
    (Writeoff, "member_user_id"),
    (Writeoff, "created_by_user_id"),
)

_SPECIALIZED_USER_REFS = frozenset(
    {
        ("auth_identities", "user_id"),
        ("daily_report_tip_allocations", "user_id"),
        ("pay_profile_assignments", "member_user_id"),
        ("payroll_lines", "member_user_id"),
        ("shift_assignments", "member_user_id"),
        ("shift_availabilities", "member_user_id"),
        ("shift_comment_mentions", "mentioned_user_id"),
        ("shift_swap_requests", "replacement_user_id"),
        ("shift_swap_requests", "requester_user_id"),
        ("venue_members", "user_id"),
        ("venue_positions", "member_user_id"),
    }
)

# Pending browser-link tokens from the absorbed account must not authorize the
# surviving account. PostgreSQL deliberately invalidates them via ON DELETE SET NULL.
_DELIBERATE_DB_USER_REF_POLICIES = {
    ("telegram_browser_auth_sessions", "user_id"): "SET NULL",
}


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
    source_telegram_user_id = int(source_user.tg_user_id) if source_had_telegram else None

    _merge_user_profile(target_user=target_user, source_user=source_user)
    if not target_had_telegram and source_had_telegram:
        if source_user.tg_username:
            target_user.tg_username = source_user.tg_username
        _copy_notification_settings(target_user=target_user, source_user=source_user)

    _merge_auth_identities(db, target_user=target_user, source_user=source_user)
    _merge_venue_members(db, target_user=target_user, source_user=source_user)
    position_map = _merge_venue_positions(db, target_user=target_user, source_user=source_user)
    _merge_shift_assignments(db, target_user=target_user, source_user=source_user, position_map=position_map)
    _merge_shift_availabilities(db, target_user=target_user, source_user=source_user)
    _merge_shift_swap_refs(db, target_user=target_user, source_user=source_user)
    _merge_shift_comment_mentions(db, target_user=target_user, source_user=source_user)
    _merge_pay_profile_assignments(db, target_user=target_user, source_user=source_user)
    _merge_tip_allocations(db, target_user=target_user, source_user=source_user)
    _merge_payroll_lines(db, target_user=target_user, source_user=source_user)

    for model, column_name in _DIRECT_USER_REF_REASSIGNMENTS:
        _bulk_reassign_user_ref(db, model, column_name, source_user.id, target_user.id)

    db.flush()

    source_user.tg_user_id = None
    source_user.tg_username = None
    db.flush()
    if not target_had_telegram and source_telegram_user_id is not None:
        target_user.tg_user_id = source_telegram_user_id
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
    if not getattr(target_user, "preferred_locale", None) and getattr(source_user, "preferred_locale", None):
        target_user.preferred_locale = source_user.preferred_locale
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
        "notify_integrations",
        "shift_reminder_lead_time_hours",
        "notification_detail_level",
    ]
    for field in fields:
        setattr(target_user, field, getattr(source_user, field))


def _merge_auth_identities(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = (
        db.execute(
            select(AuthIdentity).where(AuthIdentity.user_id == int(target_user.id)).order_by(AuthIdentity.id.asc())
        )
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(
            select(AuthIdentity).where(AuthIdentity.user_id == int(source_user.id)).order_by(AuthIdentity.id.asc())
        )
        .scalars()
        .all()
    )
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
    target_rows = (
        db.execute(select(VenueMember).where(VenueMember.user_id == int(target_user.id)).order_by(VenueMember.id.asc()))
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(select(VenueMember).where(VenueMember.user_id == int(source_user.id)).order_by(VenueMember.id.asc()))
        .scalars()
        .all()
    )
    by_venue = {int(row.venue_id): row for row in target_rows}

    for row in source_rows:
        existing = by_venue.get(int(row.venue_id))
        if existing is None:
            row.user_id = int(target_user.id)
            by_venue[int(row.venue_id)] = row
            continue
        existing.is_active = bool(existing.is_active or row.is_active)
        existing.venue_role = _prefer_venue_role(existing.venue_role, row.venue_role)
        existing.owner_note = _merge_owner_notes(existing.owner_note, row.owner_note)
        db.delete(row)

    db.flush()


def _merge_venue_positions(db: Session, *, target_user: User, source_user: User) -> dict[int, int]:
    target_rows = (
        db.execute(
            select(VenuePosition)
            .where(VenuePosition.member_user_id == int(target_user.id))
            .order_by(VenuePosition.id.asc())
        )
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(
            select(VenuePosition)
            .where(VenuePosition.member_user_id == int(source_user.id))
            .order_by(VenuePosition.id.asc())
        )
        .scalars()
        .all()
    )

    position_map: dict[int, int] = {int(row.id): int(row.id) for row in target_rows}
    target_by_key: dict[tuple, VenuePosition] = {_venue_position_merge_key(row): row for row in target_rows}

    for row in source_rows:
        key = _venue_position_merge_key(row)
        existing = target_by_key.get(key)
        if existing is None:
            row.member_user_id = int(target_user.id)
            target_by_key[key] = row
            position_map[int(row.id)] = int(row.id)
            continue
        existing.is_active = bool(existing.is_active or row.is_active)
        position_map[int(row.id)] = int(existing.id)
        assignment_rows = (
            db.execute(select(ShiftAssignment).where(ShiftAssignment.venue_position_id == int(row.id))).scalars().all()
        )
        for assignment in assignment_rows:
            assignment.venue_position_id = int(existing.id)
        swap_rows = (
            db.execute(select(ShiftSwapRequest).where(ShiftSwapRequest.replacement_position_id == int(row.id)))
            .scalars()
            .all()
        )
        for swap_request in swap_rows:
            swap_request.replacement_position_id = int(existing.id)
        db.delete(row)

    db.flush()
    return position_map


def _venue_position_merge_key(row: VenuePosition) -> tuple:
    return (
        int(row.venue_id),
        str(row.title or "").strip().casefold(),
        int(getattr(row, "rate", 0) or 0),
        int(getattr(row, "percent", 0) or 0),
        int(row.pay_profile_id) if getattr(row, "pay_profile_id", None) is not None else None,
        tuple(sorted(parse_permission_codes(getattr(row, "permission_codes", None)))),
    )


def _merge_shift_assignments(
    db: Session,
    *,
    target_user: User,
    source_user: User,
    position_map: dict[int, int],
) -> None:
    target_rows = (
        db.execute(
            select(ShiftAssignment)
            .where(ShiftAssignment.member_user_id == int(target_user.id))
            .order_by(ShiftAssignment.id.asc())
        )
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(
            select(ShiftAssignment)
            .where(ShiftAssignment.member_user_id == int(source_user.id))
            .order_by(ShiftAssignment.id.asc())
        )
        .scalars()
        .all()
    )
    by_shift = {int(row.shift_id): row for row in target_rows}

    for row in source_rows:
        desired_position_id = position_map.get(int(row.venue_position_id), int(row.venue_position_id))
        existing = by_shift.get(int(row.shift_id))
        if existing is None:
            row.member_user_id = int(target_user.id)
            row.venue_position_id = int(desired_position_id)
            by_shift[int(row.shift_id)] = row
            continue

        _repoint_shift_assignment_refs(db, source_assignment=row, target_assignment=existing)
        if row.reminder_sent_at is not None and (
            existing.reminder_sent_at is None
            or _datetime_timestamp(row.reminder_sent_at) > _datetime_timestamp(existing.reminder_sent_at)
        ):
            existing.reminder_sent_at = row.reminder_sent_at
        db.delete(row)

    db.flush()


def _repoint_shift_assignment_refs(
    db: Session,
    *,
    source_assignment: ShiftAssignment,
    target_assignment: ShiftAssignment,
) -> None:
    db.query(NotificationDeliveryLog).filter(
        NotificationDeliveryLog.shift_assignment_id == int(source_assignment.id)
    ).update(
        {NotificationDeliveryLog.shift_assignment_id: int(target_assignment.id)},
        synchronize_session=False,
    )

    target_open_request = db.execute(
        select(ShiftSwapRequest)
        .where(
            ShiftSwapRequest.assignment_id == int(target_assignment.id),
            ShiftSwapRequest.status == "OPEN",
        )
        .order_by(ShiftSwapRequest.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    source_requests = (
        db.execute(
            select(ShiftSwapRequest)
            .where(ShiftSwapRequest.assignment_id == int(source_assignment.id))
            .order_by(ShiftSwapRequest.id.asc())
        )
        .scalars()
        .all()
    )
    for request in source_requests:
        if str(request.status or "").upper() == "OPEN" and target_open_request is not None:
            request.status = "CANCELLED"
            request.manager_comment = _append_merge_note(
                request.manager_comment,
                f"Закрыт при объединении аккаунтов; сохранён запрос #{int(target_open_request.id)}.",
            )
            request.updated_at = datetime.utcnow()
        request.assignment_id = int(target_assignment.id)
        if str(request.status or "").upper() == "OPEN":
            target_open_request = request


def _append_merge_note(value: str | None, note: str) -> str:
    current = str(value or "").strip()
    if not current:
        return note
    if note in current:
        return current
    return f"{current}\n{note}"


def _merge_shift_availabilities(
    db: Session,
    *,
    target_user: User,
    source_user: User,
) -> None:
    target_rows = (
        db.execute(
            select(ShiftAvailability)
            .where(ShiftAvailability.member_user_id == int(target_user.id))
            .order_by(ShiftAvailability.id.asc())
        )
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(
            select(ShiftAvailability)
            .where(ShiftAvailability.member_user_id == int(source_user.id))
            .order_by(ShiftAvailability.id.asc())
        )
        .scalars()
        .all()
    )
    target_keys = {(int(row.venue_id), row.date, str(row.shift_slot)): row for row in target_rows}
    for row in source_rows:
        key = (int(row.venue_id), row.date, str(row.shift_slot))
        existing = target_keys.get(key)
        if existing is None:
            row.member_user_id = int(target_user.id)
            target_keys[key] = row
            continue
        if _row_change_timestamp(row) > _row_change_timestamp(existing):
            existing.status = row.status
            existing.comment = row.comment
            existing.updated_at = row.updated_at or row.created_at or existing.updated_at
        db.delete(row)
    db.flush()


def _merge_shift_swap_refs(
    db: Session,
    *,
    target_user: User,
    source_user: User,
) -> None:
    rows = (
        db.execute(
            select(ShiftSwapRequest).where(
                (ShiftSwapRequest.requester_user_id == int(source_user.id))
                | (ShiftSwapRequest.replacement_user_id == int(source_user.id))
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        requester_id = (
            int(target_user.id) if int(row.requester_user_id) == int(source_user.id) else int(row.requester_user_id)
        )
        replacement_id = (
            int(target_user.id)
            if row.replacement_user_id is not None and int(row.replacement_user_id) == int(source_user.id)
            else row.replacement_user_id
        )
        row.requester_user_id = requester_id
        if replacement_id is not None and int(replacement_id) == requester_id:
            row.replacement_user_id = None
            row.replacement_position_id = None
        else:
            row.replacement_user_id = replacement_id
    db.flush()


def _merge_shift_comment_mentions(
    db: Session,
    *,
    target_user: User,
    source_user: User,
) -> None:
    target_rows = (
        db.execute(
            select(ShiftCommentMention)
            .where(ShiftCommentMention.mentioned_user_id == int(target_user.id))
            .order_by(ShiftCommentMention.id.asc())
        )
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(
            select(ShiftCommentMention)
            .where(ShiftCommentMention.mentioned_user_id == int(source_user.id))
            .order_by(ShiftCommentMention.id.asc())
        )
        .scalars()
        .all()
    )
    target_comment_ids = {int(row.comment_id) for row in target_rows}

    for row in source_rows:
        comment_id = int(row.comment_id)
        if comment_id in target_comment_ids:
            db.delete(row)
            continue
        row.mentioned_user_id = int(target_user.id)
        target_comment_ids.add(comment_id)

    db.flush()


def _merge_pay_profile_assignments(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = (
        db.execute(
            select(PayProfileAssignment)
            .where(PayProfileAssignment.member_user_id == int(target_user.id))
            .order_by(PayProfileAssignment.id.asc())
        )
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(
            select(PayProfileAssignment)
            .where(PayProfileAssignment.member_user_id == int(source_user.id))
            .order_by(PayProfileAssignment.id.asc())
        )
        .scalars()
        .all()
    )

    keys = {_pay_profile_assignment_key(row) for row in target_rows}
    for row in source_rows:
        key = _pay_profile_assignment_key(row)
        if key in keys:
            db.delete(row)
            continue
        row.member_user_id = int(target_user.id)
        keys.add(key)

    db.flush()


def _merge_tip_allocations(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = (
        db.execute(
            select(DailyReportTipAllocation)
            .where(DailyReportTipAllocation.user_id == int(target_user.id))
            .order_by(DailyReportTipAllocation.id.asc())
        )
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(
            select(DailyReportTipAllocation)
            .where(DailyReportTipAllocation.user_id == int(source_user.id))
            .order_by(DailyReportTipAllocation.id.asc())
        )
        .scalars()
        .all()
    )
    by_report = {int(row.report_id): row for row in target_rows}

    for row in source_rows:
        existing = by_report.get(int(row.report_id))
        if existing is None:
            row.user_id = int(target_user.id)
            by_report[int(row.report_id)] = row
            continue
        target_amount = int(existing.amount or 0)
        source_amount = int(row.amount or 0)
        existing.meta_json = _merge_tip_allocation_meta(
            target_amount=target_amount,
            target_split_mode=existing.split_mode,
            target_meta=existing.meta_json,
            source_amount=source_amount,
            source_split_mode=row.split_mode,
            source_meta=row.meta_json,
        )
        existing.amount = target_amount + source_amount
        if (not existing.split_mode or existing.split_mode == "EQUAL") and row.split_mode:
            existing.split_mode = row.split_mode
        db.delete(row)

    db.flush()


def _merge_payroll_lines(db: Session, *, target_user: User, source_user: User) -> None:
    target_rows = (
        db.execute(
            select(PayrollLine).where(PayrollLine.member_user_id == int(target_user.id)).order_by(PayrollLine.id.asc())
        )
        .scalars()
        .all()
    )
    source_rows = (
        db.execute(
            select(PayrollLine).where(PayrollLine.member_user_id == int(source_user.id)).order_by(PayrollLine.id.asc())
        )
        .scalars()
        .all()
    )
    by_run = {int(row.payroll_run_id): row for row in target_rows}
    affected_runs: set[int] = set()

    for row in source_rows:
        run_id = int(row.payroll_run_id)
        existing = by_run.get(run_id)
        if existing is None:
            row.member_user_id = int(target_user.id)
            row.breakdown_json, row.pay_profile_id = _merge_payroll_breakdowns(
                target_breakdown_json=None,
                source_breakdown_json=row.breakdown_json,
                target_amount_minor=0,
                source_amount_minor=int(row.amount_minor or 0),
                target_pay_profile_id=None,
                source_pay_profile_id=row.pay_profile_id,
                target_user=target_user,
            )
            by_run[run_id] = row
            affected_runs.add(run_id)
            continue
        target_amount = int(existing.amount_minor or 0)
        source_amount = int(row.amount_minor or 0)
        existing.amount_minor = target_amount + source_amount
        existing.breakdown_json, existing.pay_profile_id = _merge_payroll_breakdowns(
            target_breakdown_json=existing.breakdown_json,
            source_breakdown_json=row.breakdown_json,
            target_amount_minor=target_amount,
            source_amount_minor=source_amount,
            target_pay_profile_id=existing.pay_profile_id,
            source_pay_profile_id=row.pay_profile_id,
            target_user=target_user,
        )
        db.delete(row)
        affected_runs.add(run_id)

    db.flush()

    for run_id in affected_runs:
        lines_count, total_amount_minor = db.execute(
            select(func.count(PayrollLine.id), func.coalesce(func.sum(PayrollLine.amount_minor), 0)).where(
                PayrollLine.payroll_run_id == int(run_id)
            )
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
    order = {"OWNER": 3, "MANAGER": 2, "STAFF": 1}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def _merge_owner_notes(target_note: str | None, source_note: str | None) -> str | None:
    target = normalize_owner_note(target_note)
    source = normalize_owner_note(source_note)
    if not target:
        return source
    if not source or source.casefold() == target.casefold():
        return target
    return normalize_owner_note(f"{target} · {source}")


def _row_change_timestamp(row) -> float:
    value = getattr(row, "updated_at", None) or getattr(row, "created_at", None)
    if not isinstance(value, datetime):
        return float("-inf")
    return _datetime_timestamp(value)


def _datetime_timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _merge_payroll_breakdowns(
    *,
    target_breakdown_json: str | None,
    source_breakdown_json: str | None,
    target_amount_minor: int,
    source_amount_minor: int,
    target_pay_profile_id: int | None,
    source_pay_profile_id: int | None,
    target_user: User,
) -> tuple[str, int | None]:
    target = _parse_payroll_breakdown(target_breakdown_json)
    source = _parse_payroll_breakdown(source_breakdown_json)

    profile_titles = _payroll_profile_titles(target, source)
    profile_ids = sorted(
        _payroll_profile_ids(
            target,
            source,
            explicit_ids=(target_pay_profile_id, source_pay_profile_id),
        )
    )
    breakdown_profile_id = profile_ids[0] if len(profile_ids) == 1 else None
    persisted_profile_ids = sorted(
        {int(value) for value in (target_pay_profile_id, source_pay_profile_id) if value is not None}
    )
    persisted_profile_id = persisted_profile_ids[0] if len(persisted_profile_ids) == 1 else None

    target_metrics = target.get("metrics") if isinstance(target.get("metrics"), dict) else {}
    source_metrics = source.get("metrics") if isinstance(source.get("metrics"), dict) else {}
    target_worked_dates = _payroll_breakdown_worked_dates(target, target_metrics)
    source_worked_dates = _payroll_breakdown_worked_dates(source, source_metrics)
    worked_dates = sorted(target_worked_dates | source_worked_dates)
    minutes_total = _safe_int(target_metrics.get("minutes_total")) + _safe_int(source_metrics.get("minutes_total"))
    shifts_count = _safe_int(target_metrics.get("shifts_count")) + _safe_int(source_metrics.get("shifts_count"))
    metrics = _target_first_mapping(target_metrics, source_metrics)
    metrics.update(
        {
            "minutes_total": minutes_total,
            "hours_total": round(minutes_total / 60.0, 2),
            "shifts_count": shifts_count,
            "worked_dates_count": len(worked_dates),
            "worked_dates": worked_dates,
        }
    )

    target_components, target_repair = _prepare_payroll_components(
        target.get("components"),
        amount_minor=int(target_amount_minor),
        worked_dates=target_worked_dates,
        side="target",
    )
    source_components, source_repair = _prepare_payroll_components(
        source.get("components"),
        amount_minor=int(source_amount_minor),
        worked_dates=source_worked_dates,
        side="source",
    )
    components = [*target_components, *source_components]
    component_repairs = [
        *_dict_items(target.get("account_merge_component_repairs")),
        *_dict_items(source.get("account_merge_component_repairs")),
        *([target_repair] if target_repair is not None else []),
        *([source_repair] if source_repair is not None else []),
    ]

    shift_allocations = _merge_payroll_shift_allocations(
        target,
        source,
        target_amount_minor=int(target_amount_minor),
        source_amount_minor=int(source_amount_minor),
    )
    member_name = (
        str(target.get("member_name") or "").strip()
        or str(source.get("member_name") or "").strip()
        or str(
            target_user.short_name or target_user.full_name or target_user.tg_username or f"user #{int(target_user.id)}"
        )
    )

    merged = _target_first_mapping(target, source)
    merged.update(
        {
            "member_user_id": int(target_user.id),
            "member_name": member_name,
            "pay_profile_id": breakdown_profile_id,
            "pay_profile_title": profile_titles.get(breakdown_profile_id) if breakdown_profile_id is not None else None,
            "pay_profile_ids": profile_ids,
            "pay_profile_titles": [profile_titles.get(profile_id) for profile_id in profile_ids],
            "position_profiles": [
                *_dict_items(target.get("position_profiles")),
                *_dict_items(source.get("position_profiles")),
            ],
            "metrics": metrics,
            "revenue_metrics": _target_first_mapping(
                target.get("revenue_metrics"),
                source.get("revenue_metrics"),
            ),
            "kpi_metrics": _target_first_mapping(target.get("kpi_metrics"), source.get("kpi_metrics")),
            "components": components,
            "shift_allocations": shift_allocations,
        }
    )
    if component_repairs:
        merged["account_merge_component_repairs"] = component_repairs
    else:
        merged.pop("account_merge_component_repairs", None)
    return json.dumps(merged, ensure_ascii=False), persisted_profile_id


def _merge_tip_allocation_meta(
    *,
    target_amount: int,
    target_split_mode: str | None,
    target_meta: dict | None,
    source_amount: int,
    source_split_mode: str | None,
    source_meta: dict | None,
) -> dict | None:
    if not target_meta and not source_meta:
        return None
    if target_meta == source_meta and target_split_mode == source_split_mode:
        return target_meta

    base_meta = target_meta if isinstance(target_meta, dict) else source_meta
    merged = dict(base_meta) if isinstance(base_meta, dict) else {}
    merged["account_merge_allocations"] = [
        {
            "amount": int(target_amount),
            "split_mode": str(target_split_mode or "EQUAL"),
            "meta": target_meta,
        },
        {
            "amount": int(source_amount),
            "split_mode": str(source_split_mode or "EQUAL"),
            "meta": source_meta,
        },
    ]
    return merged


def _parse_payroll_breakdown(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _target_first_mapping(target, source) -> dict:
    result = dict(target) if isinstance(target, dict) else {}
    if isinstance(source, dict):
        for key, value in source.items():
            if key not in result or result[key] is None:
                result[key] = value
    return result


def _dict_items(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _valid_worked_dates(metrics: dict) -> set[str]:
    values = metrics.get("worked_dates") if isinstance(metrics, dict) else None
    result: set[str] = set()
    for value in values if isinstance(values, list) else []:
        try:
            result.add(date.fromisoformat(str(value)).isoformat())
        except (TypeError, ValueError):
            continue
    return result


def _payroll_breakdown_worked_dates(breakdown: dict, metrics: dict) -> set[str]:
    result = _valid_worked_dates(metrics)
    allocations = _dict_items(breakdown.get("shift_allocations"))
    for allocation in allocations:
        _add_iso_date(result, allocation.get("date") or allocation.get("shift_date"))
    for component in _dict_items(breakdown.get("components")):
        component_dates = component.get("account_merge_worked_dates")
        for value in component_dates if isinstance(component_dates, list) else []:
            _add_iso_date(result, value)
        for row_key in ("shift_rows", "day_rows"):
            for row in _dict_items(component.get(row_key)):
                _add_iso_date(result, row.get("date"))
    return result


def _add_iso_date(result: set[str], value) -> None:
    if value in (None, ""):
        return
    try:
        result.add(date.fromisoformat(str(value)).isoformat())
    except (TypeError, ValueError):
        return


def _prepare_payroll_components(
    value,
    *,
    amount_minor: int,
    worked_dates: set[str],
    side: str,
) -> tuple[list[dict], dict | None]:
    components = _dict_items(value)
    ordered_dates = sorted(worked_dates)
    for component in components:
        if "account_merge_worked_dates" not in component:
            component["account_merge_worked_dates"] = ordered_dates

    component_total = sum(_safe_int(item.get("amount_minor")) for item in components)
    remainder = int(amount_minor) - component_total
    if remainder >= 0:
        if remainder:
            remainder_component = {
                "component_id": None,
                "component_type": "ACCOUNT_MERGE_REMAINDER",
                "title": "Начисление из объединённого аккаунта",
                "amount_minor": remainder,
                "source": "account_merge",
            }
            remainder_component["account_merge_worked_dates"] = ordered_dates
            components.append(remainder_component)
        return components, None

    repair_component = {
        "component_id": None,
        "component_type": "ACCOUNT_MERGE_REPAIR",
        "title": "Восстановленное начисление после объединения аккаунтов",
        "amount_minor": int(amount_minor),
        "source": "account_merge",
    }
    repair_component["account_merge_worked_dates"] = ordered_dates
    repair_record = {
        "side": side,
        "line_amount_minor": int(amount_minor),
        "components_amount_minor": component_total,
        "components": components,
    }
    return [repair_component], repair_record


def _payroll_profile_ids(target: dict, source: dict, *, explicit_ids: tuple[int | None, ...]) -> set[int]:
    result = {int(value) for value in explicit_ids if value is not None}
    for breakdown in (target, source):
        profile_id = breakdown.get("pay_profile_id")
        if profile_id is not None:
            try:
                result.add(int(profile_id))
            except (TypeError, ValueError):
                pass
        profile_ids = breakdown.get("pay_profile_ids")
        for value in profile_ids if isinstance(profile_ids, list) else []:
            try:
                result.add(int(value))
            except (TypeError, ValueError):
                continue
    return result


def _payroll_profile_titles(target: dict, source: dict) -> dict[int, str | None]:
    result: dict[int, str | None] = {}
    for breakdown in (target, source):
        profile_ids = breakdown.get("pay_profile_ids")
        profile_titles = breakdown.get("pay_profile_titles")
        if isinstance(profile_ids, list) and isinstance(profile_titles, list):
            for profile_id, title in zip(profile_ids, profile_titles):
                try:
                    normalized_id = int(profile_id)
                except (TypeError, ValueError):
                    continue
                if normalized_id not in result or result[normalized_id] is None:
                    result[normalized_id] = str(title) if title is not None else None
        profile_id = breakdown.get("pay_profile_id")
        if profile_id is not None:
            try:
                normalized_id = int(profile_id)
            except (TypeError, ValueError):
                continue
            if normalized_id not in result or result[normalized_id] is None:
                title = breakdown.get("pay_profile_title")
                result[normalized_id] = str(title) if title is not None else None
    return result


def _merge_payroll_shift_allocations(
    target: dict,
    source: dict,
    *,
    target_amount_minor: int,
    source_amount_minor: int,
) -> list[dict]:
    target_allocations = _complete_shift_allocations(target.get("shift_allocations"), target_amount_minor)
    source_allocations = _complete_shift_allocations(source.get("shift_allocations"), source_amount_minor)
    if target_allocations is None or source_allocations is None:
        return []

    by_shift: dict[int, dict] = {}
    for allocation in [*target_allocations, *source_allocations]:
        shift_id = int(allocation["shift_id"])
        normalized_allocation = dict(allocation)
        if not normalized_allocation.get("date") and normalized_allocation.get("shift_date"):
            normalized_allocation["date"] = str(normalized_allocation["shift_date"])
        existing = by_shift.get(shift_id)
        if existing is None:
            by_shift[shift_id] = normalized_allocation
            by_shift[shift_id]["shift_id"] = shift_id
            by_shift[shift_id]["amount_minor"] = _safe_int(normalized_allocation.get("amount_minor"))
            continue
        existing["amount_minor"] = _safe_int(existing.get("amount_minor")) + _safe_int(
            normalized_allocation.get("amount_minor")
        )
        for key, value in normalized_allocation.items():
            if key not in existing or existing[key] is None:
                existing[key] = value
        if "minutes" in existing or "minutes" in normalized_allocation:
            existing["minutes"] = max(
                _safe_int(existing.get("minutes")),
                _safe_int(normalized_allocation.get("minutes")),
            )
    return [by_shift[shift_id] for shift_id in sorted(by_shift)]


def _complete_shift_allocations(value, amount_minor: int) -> list[dict] | None:
    if not isinstance(value, list):
        return [] if int(amount_minor) == 0 else None
    result: list[dict] = []
    for item in value:
        if not isinstance(item, dict) or item.get("shift_id") is None:
            return None
        try:
            int(item["shift_id"])
            date.fromisoformat(str(item.get("date") or item.get("shift_date")))
        except (TypeError, ValueError):
            return None
        result.append(dict(item))
    if sum(_safe_int(item.get("amount_minor")) for item in result) != int(amount_minor):
        return None
    return result


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

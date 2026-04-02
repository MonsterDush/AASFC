"""Process billing state transitions and send owner reminders.

Run periodically (for example, every hour) from the backend environment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Venue, VenueBillingState, VenueBillingTransaction
from app.services.billing import get_billing_snapshot_for_state, get_robokassa_config, mark_checkout_transaction_failed, send_owner_billing_notification_once, sync_billing_state


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _fmt_date(dt) -> str:
    if not dt:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%d.%m.%Y")


def _days_until(target_dt, now: datetime) -> int | None:
    if target_dt is None:
        return None
    target = target_dt.astimezone(timezone.utc).date()
    return (target - now.date()).days


def main() -> int:
    now = _utc_now()
    changed_states = 0
    sent_notifications = 0
    expired_checkouts = 0
    robo_cfg = get_robokassa_config()

    with SessionLocal() as db:
        pending_before = now - timedelta(minutes=max(5, int(robo_cfg.pending_timeout_minutes or 180)))
        pending_rows = db.execute(
            select(VenueBillingTransaction)
            .where(
                VenueBillingTransaction.source == "ROBOKASSA",
                VenueBillingTransaction.status == "PENDING",
                VenueBillingTransaction.created_at < pending_before,
            )
            .order_by(VenueBillingTransaction.created_at.asc(), VenueBillingTransaction.id.asc())
        ).scalars().all()
        for tx in pending_rows:
            _, event = mark_checkout_transaction_failed(
                db,
                transaction=tx,
                status="EXPIRED",
                provider_payload_json={"expired_by_job_at": now.isoformat()},
                comment="Robokassa checkout expired before successful callback",
                event_type="ROBOKASSA_PAYMENT_TIMEOUT",
            )
            if event is not None:
                expired_checkouts += 1
        db.commit()

        rows = db.execute(
            select(VenueBillingState, Venue.name)
            .join(Venue, Venue.id == VenueBillingState.venue_id)
            .order_by(VenueBillingState.venue_id.asc())
        ).all()

        for state, venue_name in rows:
            state, snapshot_before, event = sync_billing_state(db, state=state, now=now)
            snapshot = get_billing_snapshot_for_state(state)
            if event is not None:
                changed_states += 1
                if snapshot.status == "GRACE":
                    sent_notifications += send_owner_billing_notification_once(
                        db,
                        venue_id=int(state.venue_id),
                        notification_type="grace_started",
                        event_key=str(event.id),
                        text=(
                            f"По заведению «{venue_name}» закончился оплаченный период. "
                            f"Льготный период действует до {_fmt_date(snapshot.grace_until)}."
                        ),
                        button_text="Продлить доступ",
                    )
                elif snapshot.status == "SUSPENDED":
                    sent_notifications += send_owner_billing_notification_once(
                        db,
                        venue_id=int(state.venue_id),
                        notification_type="suspended",
                        event_key=str(event.id),
                        text=(
                            f"По заведению «{venue_name}» закончился льготный период. "
                            f"Рабочий доступ ограничен до продления оплаты."
                        ),
                        button_text="Продлить доступ",
                    )

            days_to_paid_end = _days_until(snapshot.paid_until, now)
            reminder_codes = {7: "7d", 3: "3d", 1: "1d", 0: "due_today"}
            if snapshot.status == "ACTIVE" and days_to_paid_end in reminder_codes:
                label = {
                    7: "через 7 дней",
                    3: "через 3 дня",
                    1: "завтра",
                    0: "сегодня",
                }[int(days_to_paid_end)]
                sent_notifications += send_owner_billing_notification_once(
                    db,
                    venue_id=int(state.venue_id),
                    notification_type=f"reminder_{reminder_codes[int(days_to_paid_end)]}",
                    event_key=str(snapshot.paid_until.date().isoformat()),
                    text=(
                        f"Оплата по заведению «{venue_name}» заканчивается {label}. "
                        f"Текущий срок — до {_fmt_date(snapshot.paid_until)}."
                    ),
                    button_text="Продлить доступ",
                )

            days_to_grace_end = _days_until(snapshot.grace_until, now)
            if snapshot.status == "GRACE" and days_to_grace_end == 0:
                sent_notifications += send_owner_billing_notification_once(
                    db,
                    venue_id=int(state.venue_id),
                    notification_type="grace_ends_today",
                    event_key=str(snapshot.grace_until.date().isoformat()) if snapshot.grace_until else str(now.date().isoformat()),
                    text=(
                        f"Сегодня последний день льготного периода по заведению «{venue_name}». "
                        f"После {_fmt_date(snapshot.grace_until)} доступ будет ограничен."
                    ),
                    button_text="Продлить доступ",
                )

            db.commit()

    print(f"changed_states={changed_states} sent_notifications={sent_notifications} expired_checkouts={expired_checkouts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

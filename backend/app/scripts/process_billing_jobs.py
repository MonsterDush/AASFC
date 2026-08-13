"""Process billing state transitions and send owner reminders.

Run periodically (for example, every hour) from the backend environment.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import Venue, VenueBillingState
from app.models.venue_billing_transaction import VenueBillingTransaction
from app.services.billing import (
    expire_stale_pending_checkouts,
    get_billing_health_summary,
    get_billing_snapshot_for_state,
    get_refund_request_state,
    list_pending_external_refund_transactions,
    send_owner_billing_notification_once,
    send_super_admin_billing_alert_once,
    sync_billing_reconciliation_issues,
    sync_billing_state,
    sync_external_refund_transaction_state,
)


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
    sent_admin_alerts = 0

    with SessionLocal() as db:
        expired_checkouts, events = expire_stale_pending_checkouts(db, now=now)
        if expired_checkouts:
            db.commit()
            for event in events:
                sent_admin_alerts += send_super_admin_billing_alert_once(
                    db,
                    notification_type="stale_pending",
                    event_key=str(event.id),
                    venue_id=int(event.venue_id),
                    text=(
                        f"Проблема биллинга: checkout по заведению #{int(event.venue_id)} истёк без оплаты. "
                        f"Проверьте pending-платежи и историю операций."
                    ),
                    text_en=(
                        f"Billing issue: checkout for venue #{int(event.venue_id)} expired without payment. "
                        "Check pending payments and transaction history."
                    ),
                )
            if sent_admin_alerts:
                db.commit()

        pending_refunds = list_pending_external_refund_transactions(db, limit=100)
        for refund_tx in pending_refunds:
            request_id = str(refund_tx.provider_payment_id or "").strip()
            if not request_id:
                continue
            try:
                state_data = get_refund_request_state(request_id=request_id)
            except Exception as exc:
                sent_admin_alerts += send_super_admin_billing_alert_once(
                    db,
                    notification_type="refund_state_error",
                    event_key=f"refund-state:{int(refund_tx.id)}:{now.date().isoformat()}",
                    venue_id=int(refund_tx.venue_id),
                    text=(
                        f"Проблема биллинга: не удалось проверить статус возврата по заведению #{int(refund_tx.venue_id)} "
                        f"(refund tx #{int(refund_tx.id)}): {exc}"
                    ),
                    text_en=(
                        f"Billing issue: unable to check the refund status for venue #{int(refund_tx.venue_id)} "
                        f"(refund tx #{int(refund_tx.id)}): {exc}"
                    ),
                )
                db.commit()
                continue
            refund_tx, refund_event = sync_external_refund_transaction_state(
                db,
                transaction=refund_tx,
                refund_state_label=str(state_data.get("label") or "processing"),
                provider_payload_json={"refund_state_result": state_data},
            )
            db.commit()
            if refund_event is not None and str(refund_tx.status or "").upper() == "SUCCEEDED":
                venue_name = (
                    db.execute(select(Venue.name).where(Venue.id == int(refund_tx.venue_id))).scalar_one_or_none()
                    or f"Заведение #{int(refund_tx.venue_id)}"
                )
                sent_notifications += send_owner_billing_notification_once(
                    db,
                    venue_id=int(refund_tx.venue_id),
                    notification_type="refund_finished",
                    event_key=str(refund_event.id),
                    text=(
                        f"Возврат по заведению «{venue_name}» выполнен. Сумма: {int(refund_tx.amount_minor or 0) / 100:.2f} ₽."
                    ),
                    text_en=(
                        f"The refund for venue “{venue_name}” is complete. Amount: {int(refund_tx.amount_minor or 0) / 100:.2f} ₽."
                    ),
                    button_text="Открыть подписку",
                    button_text_en="Open subscription",
                )
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
                        text_en=(
                            f"The paid period for venue “{venue_name}” has ended. "
                            f"The grace period lasts until {_fmt_date(snapshot.grace_until)}."
                        ),
                        button_text="Продлить доступ",
                        button_text_en="Renew access",
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
                        text_en=(
                            f"The grace period for venue “{venue_name}” has ended. "
                            "Workspace access is restricted until payment is renewed."
                        ),
                        button_text="Продлить доступ",
                        button_text_en="Renew access",
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
                label_en = {
                    7: "in 7 days",
                    3: "in 3 days",
                    1: "tomorrow",
                    0: "today",
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
                    text_en=(
                        f"Payment for venue “{venue_name}” expires {label_en}. "
                        f"The current paid period ends on {_fmt_date(snapshot.paid_until)}."
                    ),
                    button_text="Продлить доступ",
                    button_text_en="Renew access",
                )

            days_to_grace_end = _days_until(snapshot.grace_until, now)
            if snapshot.status == "GRACE" and days_to_grace_end == 0:
                sent_notifications += send_owner_billing_notification_once(
                    db,
                    venue_id=int(state.venue_id),
                    notification_type="grace_ends_today",
                    event_key=str(snapshot.grace_until.date().isoformat())
                    if snapshot.grace_until
                    else str(now.date().isoformat()),
                    text=(
                        f"Сегодня последний день льготного периода по заведению «{venue_name}». "
                        f"После {_fmt_date(snapshot.grace_until)} доступ будет ограничен."
                    ),
                    text_en=(
                        f"Today is the last day of the grace period for venue “{venue_name}”. "
                        f"Access will be restricted after {_fmt_date(snapshot.grace_until)}."
                    ),
                    button_text="Продлить доступ",
                    button_text_en="Renew access",
                )

            db.commit()

        failed_threshold = max(1, int(getattr(settings, "BILLING_ALERT_FAILED_THRESHOLD_24H", 5) or 5))
        failed_24h = db.execute(
            select(VenueBillingTransaction.id).where(
                VenueBillingTransaction.type == "PAYMENT",
                VenueBillingTransaction.status == "FAILED",
                VenueBillingTransaction.created_at >= now - timedelta(hours=24),
            )
        ).all()
        if len(failed_24h) >= failed_threshold:
            sent_admin_alerts += send_super_admin_billing_alert_once(
                db,
                notification_type="failed_threshold_24h",
                event_key=now.date().isoformat(),
                text=(
                    f"Проблема биллинга: за последние 24 часа накопилось {len(failed_24h)} failed checkout. "
                    f"Проверьте раздел биллинга и сверку."
                ),
                text_en=(
                    f"Billing issue: {len(failed_24h)} failed checkouts were recorded in the last 24 hours. "
                    "Check billing and reconciliation."
                ),
            )
            if sent_admin_alerts:
                db.commit()

        sync_billing_reconciliation_issues(db)
        db.commit()
        get_billing_health_summary(db)

    print(
        f"changed_states={changed_states} sent_notifications={sent_notifications} expired_checkouts={expired_checkouts} sent_admin_alerts={sent_admin_alerts}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

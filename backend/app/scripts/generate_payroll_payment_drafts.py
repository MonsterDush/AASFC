"""Generate payroll payout drafts due on the next calendar day.

This command is idempotent and is executed from process_notification_jobs.
"""

from __future__ import annotations

from datetime import date, timedelta
import logging

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import PayrollPaymentSettings
from app.services.payroll.notifications import send_payroll_window_notifications
from app.services.payroll.payments import generate_payroll_draft_expenses, payment_windows_for_settings


log = logging.getLogger(__name__)


def main(today: date | None = None) -> int:
    target_payment_date = (today or date.today()) + timedelta(days=1)
    changed = 0
    notifications_sent = 0
    with SessionLocal() as db:
        settings_rows = (
            db.execute(
                select(PayrollPaymentSettings)
                .where(PayrollPaymentSettings.is_active.is_(True))
                .order_by(PayrollPaymentSettings.venue_id.asc())
            )
            .scalars()
            .all()
        )
        for settings in settings_rows:
            try:
                windows = payment_windows_for_settings(
                    settings,
                    schedule_month=target_payment_date.replace(day=1),
                )
                if not any(item.payment_date == target_payment_date for item in windows):
                    continue
                result = generate_payroll_draft_expenses(
                    db,
                    settings=settings,
                    schedule_month=target_payment_date.replace(day=1),
                    only_payment_date=target_payment_date,
                )
                changed += int(result.get("created") or 0) + int(result.get("updated") or 0)
                db.commit()
                items_by_payment_date = {
                    item.get("payment_date"): item
                    for item in result.get("items") or []
                    if item.get("expense_id") is not None and str(item.get("status") or "").upper() == "DRAFT"
                }
                for window in windows:
                    if window.payment_date != target_payment_date:
                        continue
                    item = items_by_payment_date.get(window.payment_date)
                    if item is None:
                        continue
                    notification_result = send_payroll_window_notifications(
                        db,
                        settings_row=settings,
                        window=window,
                        amount_minor=int(item.get("amount_minor") or 0),
                    )
                    notifications_sent += int(notification_result.get("managers_sent") or 0)
                    notifications_sent += int(notification_result.get("employees_sent") or 0)
            except Exception as exc:  # pragma: no cover - keep other venues processing
                db.rollback()
                log.exception(
                    "payroll payment draft generation failed venue_id=%s payment_date=%s: %s",
                    getattr(settings, "venue_id", None),
                    target_payment_date,
                    exc,
                )
    return changed + notifications_sent


if __name__ == "__main__":
    raise SystemExit(0 if main() >= 0 else 1)

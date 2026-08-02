"""Generate payroll payout drafts due on the next calendar day.

This command is idempotent and is executed from process_notification_jobs.
"""

from __future__ import annotations

from datetime import date, timedelta
import logging

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import PayrollPaymentSettings
from app.services.payroll.payments import generate_payroll_draft_expenses, payment_windows_for_settings


log = logging.getLogger(__name__)


def main(today: date | None = None) -> int:
    target_payment_date = (today or date.today()) + timedelta(days=1)
    changed = 0
    with SessionLocal() as db:
        settings_rows = db.execute(
            select(PayrollPaymentSettings)
            .where(PayrollPaymentSettings.is_active.is_(True))
            .order_by(PayrollPaymentSettings.venue_id.asc())
        ).scalars().all()
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
            except Exception as exc:  # pragma: no cover - keep other venues processing
                db.rollback()
                log.exception(
                    "payroll payment draft generation failed venue_id=%s payment_date=%s: %s",
                    getattr(settings, "venue_id", None),
                    target_payment_date,
                    exc,
                )
    return changed


if __name__ == "__main__":
    raise SystemExit(0 if main() >= 0 else 1)

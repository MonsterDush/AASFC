"""Process notification jobs and scheduled reminder checks.

Run periodically (e.g. every minute) from the backend environment.
This is safe to run alongside the in-request FastAPI BackgroundTasks trigger.

Important: shift reminders are time-based and are not stored in notification_jobs,
so this runner also executes app.scripts.send_shift_reminders.main().
"""

from __future__ import annotations

from datetime import date
import logging

from app.core.db import SessionLocal
from app.routers.venue_economics_notifications import process_pending_notification_jobs_once
from app.scripts.generate_payroll_payment_drafts import main as generate_payroll_payment_drafts_once
from app.scripts.send_shift_reminders import main as send_shift_reminders_once
from app.services.payroll.notifications import send_due_draft_expense_reminders_once

log = logging.getLogger(__name__)

# Deployment tooling uses this explicit contract to decide whether the legacy
# shift-reminder timer must be disabled for the checked-out release.
OWNS_SHIFT_REMINDERS = True


def main() -> int:
    payroll_payment_drafts = 0
    try:
        payroll_payment_drafts = generate_payroll_payment_drafts_once()
    except Exception as exc:  # pragma: no cover - keep notification runner alive
        log.exception("payroll payment draft generation failed: %s", exc)
    draft_expense_reminders = 0
    try:
        with SessionLocal() as db:
            draft_expense_reminders = send_due_draft_expense_reminders_once(db, today=date.today())
    except Exception as exc:  # pragma: no cover - keep notification runner alive
        log.exception("draft expense reminder processing failed: %s", exc)
    processed_jobs = process_pending_notification_jobs_once(50)
    shift_reminders = 0
    try:
        shift_reminders = send_shift_reminders_once()
    except Exception as exc:  # pragma: no cover - keep queued jobs runner alive
        log.exception("shift reminders processing failed: %s", exc)
        print(
            f"payroll_payment_drafts={payroll_payment_drafts} draft_expense_reminders={draft_expense_reminders} processed_jobs={processed_jobs} shift_reminders_error={exc}"
        )
        return int(payroll_payment_drafts or 0) + int(draft_expense_reminders or 0) + int(processed_jobs or 0)

    print(
        f"payroll_payment_drafts={payroll_payment_drafts} draft_expense_reminders={draft_expense_reminders} processed_jobs={processed_jobs} shift_reminders={shift_reminders}"
    )
    return (
        int(payroll_payment_drafts or 0)
        + int(draft_expense_reminders or 0)
        + int(processed_jobs or 0)
        + int(shift_reminders or 0)
    )


if __name__ == "__main__":
    raise SystemExit(0 if main() >= 0 else 1)

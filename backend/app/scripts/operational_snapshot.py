from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select

from app.core.db import SessionLocal
from app.models import BillingReconciliationIssue, NotificationJob, VenueBillingTransaction


def build_snapshot() -> dict[str, int]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        failed_payments = db.execute(
            select(func.count(VenueBillingTransaction.id)).where(
                VenueBillingTransaction.type == "PAYMENT",
                VenueBillingTransaction.status == "FAILED",
                VenueBillingTransaction.created_at >= now - timedelta(hours=24),
            )
        ).scalar_one()
        open_reconciliation = db.execute(
            select(func.count(BillingReconciliationIssue.id)).where(
                BillingReconciliationIssue.status == "OPEN",
                BillingReconciliationIssue.severity.in_(["HIGH", "CRITICAL"]),
            )
        ).scalar_one()
        failed_jobs = db.execute(
            select(func.count(NotificationJob.id)).where(NotificationJob.status == "failed")
        ).scalar_one()
        stale_jobs = db.execute(
            select(func.count(NotificationJob.id)).where(
                or_(
                    (NotificationJob.status == "pending") & (NotificationJob.run_after <= now - timedelta(minutes=15)),
                    (NotificationJob.status == "processing")
                    & or_(
                        NotificationJob.locked_at.is_(None),
                        NotificationJob.locked_at <= now - timedelta(minutes=15),
                    ),
                )
            )
        ).scalar_one()
    return {
        "failed_payments_24h": int(failed_payments or 0),
        "open_reconciliation_high": int(open_reconciliation or 0),
        "failed_notification_jobs": int(failed_jobs or 0),
        "stale_notification_jobs": int(stale_jobs or 0),
    }


def main() -> int:
    print(json.dumps(build_snapshot(), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Cleanup old notification delivery logs.

Keeps active idempotency records (pending/sent) by default so already delivered
notifications remain protected from duplicates. Failed/duplicate rows can be
trimmed safely after the configured retention period.

Env:
  NOTIFICATION_LOG_RETENTION_DAYS=90
  NOTIFICATION_LOG_CLEAN_SENT=0  # set to 1 only if you intentionally want to
                                 # remove old sent rows after retention.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.db import SessionLocal
from app.models import NotificationDeliveryLog


RETENTION_DAYS = max(1, int(os.getenv("NOTIFICATION_LOG_RETENTION_DAYS", "90")))
CLEAN_SENT = os.getenv("NOTIFICATION_LOG_CLEAN_SENT", "").strip().lower() in {"1", "true", "yes"}


def main() -> int:
    cutoff = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=RETENTION_DAYS)
    removable_statuses = ["failed", "duplicate"]
    if CLEAN_SENT:
        removable_statuses.append("sent")

    with SessionLocal() as db:
        result = db.execute(
            delete(NotificationDeliveryLog)
            .where(NotificationDeliveryLog.planned_at.is_not(None))
            .where(NotificationDeliveryLog.planned_at < cutoff)
            .where(NotificationDeliveryLog.status.in_(removable_statuses))
        )
        db.commit()
        return int(result.rowcount or 0)


if __name__ == "__main__":
    deleted = main()
    print(f"deleted={deleted}")

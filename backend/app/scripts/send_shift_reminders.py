"""Send 'upcoming shift' reminders via Telegram bot.

Run this script periodically (e.g. every 10 minutes) from the backend environment.
It will send a reminder ~18 hours before shift start (best-effort) and mark assignments to avoid duplicates.

Env:
  - DATABASE_URL (or whatever your app uses via app.core.db)
  - BOT_SERVICE_URL / BOT_SERVICE_SECRET (preferred) OR TG_BOT_TOKEN/TELEGRAM_BOT_TOKEN (fallback)
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import Shift, ShiftInterval, ShiftAssignment, User
from app.services import tg_notify


REMINDER_HOURS = 18
WINDOW_MINUTES = 15  # send once when we are within this window around the exact 18h mark


def _shift_start_naive(shift_date, start_time):
    # DB stores date + time separately; treat as local/server time.
    return datetime.combine(shift_date, start_time)


def main() -> int:
    now = datetime.now()
    target = now + timedelta(hours=REMINDER_HOURS)
    win_start = target - timedelta(minutes=WINDOW_MINUTES)
    win_end = target + timedelta(minutes=WINDOW_MINUTES)

    sent = 0
    with SessionLocal() as db: 
        # load candidate assignments by joining shifts + intervals
        q = (
            select(ShiftAssignment, Shift, ShiftInterval, User)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
            .join(User, User.id == ShiftAssignment.member_user_id)
            .where(Shift.is_active.is_(True))
        )
        rows = db.execute(q).all()
        for sa, sh, interval, user in rows:
            if not getattr(user, "notify_enabled", True):
                continue
            if not getattr(user, "notify_shifts", True):
                continue
            if sa.reminder_sent_at is not None:
                continue

            start_dt = _shift_start_naive(sh.date, interval.start_time)
            if not (win_start <= start_dt <= win_end):
                continue

            # best-effort send
            text = f"Напоминание: смена скоро начнётся ({sh.date.isoformat()} · {interval.title})."
            ok = tg_notify.notify(chat_id=int(user.tg_user_id), text=text)
            if ok:
                sa.reminder_sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
                db.add(sa)
                sent += 1

        if sent:
            db.commit()

    return sent


if __name__ == "__main__":
    n = main()
    print(f"sent={n}")

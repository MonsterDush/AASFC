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
from app.models import Shift, ShiftInterval, ShiftAssignment, User, Venue
from app.services import tg_notify


REMINDER_HOURS = int(os.getenv("REMINDER_HOURS", "18"))

RU_MONTHS_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

def format_date_ru(d) -> str:
    # d: date-like (expects .day and .month)
    return f"{d.day} {RU_MONTHS_GEN.get(d.month, str(d.month))}"

WINDOW_MINUTES = int(os.getenv("REMINDER_WINDOW_MINUTES", "15"))  # window around the exact mark

# For manual testing:
# - DRY_RUN=1 will not send, only print matches
# - FORCE_CHAT_ID=<tg_user_id> will send all matches to this chat_id instead of the assignee
DRY_RUN = os.getenv("DRY_RUN", "").strip() in ("1", "true", "yes")
FORCE_CHAT_ID = os.getenv("FORCE_CHAT_ID")

def _fmt_time(t) -> str:
    # t can be datetime.time or a string like "18:00:00"
    try:
        return t.strftime("%H:%M")
    except Exception:
        s = str(t)
        return s[:5] if len(s) >= 5 else s


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
            select(ShiftAssignment, Shift, ShiftInterval, User, Venue)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
            .join(User, User.id == ShiftAssignment.member_user_id)
            .join(Venue, Venue.id == Shift.venue_id)
            .where(Shift.is_active.is_(True))
        )
        rows = db.execute(q).all()
        for sa, sh, interval, user, venue in rows:
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
            text = (
                f"Напоминаем, что у Вас смена {format_date_ru(sh.date)} "
                f"в {_fmt_time(interval.start_time)} "
                f"в заведении \"{venue.name}\""
            )
            chat_id = int(FORCE_CHAT_ID) if FORCE_CHAT_ID else int(user.tg_user_id)

            if DRY_RUN:
                print(f"DRY_RUN match: chat_id={chat_id} user_id={user.id} shift_id={sh.id} start={start_dt} venue=\"{venue.name}\"")
                continue

            ok = tg_notify.notify(chat_id=chat_id, text=text)
            if ok and not FORCE_CHAT_ID:
                # Mark as sent only for real reminders to real assignee
                sa.reminder_sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
                db.add(sa)
                sent += 1

        if sent:
            db.commit()

    return sent


if __name__ == "__main__":
    n = main()
    print(f"sent={n}")

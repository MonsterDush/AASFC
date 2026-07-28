"""Send 'upcoming shift' reminders via Telegram bot.

This module is executed from app.scripts.process_notification_jobs only.
Do not run a separate systemd timer for this file, otherwise shift reminders will have
two schedulers competing for the same delivery window.

Env:
  - DATABASE_URL (or whatever your app uses via app.core.db)
  - BOT_SERVICE_URL / BOT_SERVICE_SECRET
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone, date

try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import Shift, ShiftInterval, ShiftAssignment, User, Venue
from app.services import tg_notify
from app.services.notification_logs import (
    lock_notification_idempotency_key,
    log_notification_attempt,
    notification_delivery_exists,
    notification_dedupe_scope,
)


DEFAULT_REMINDER_HOURS = int(os.getenv("REMINDER_HOURS", "18"))
ALLOWED_REMINDER_HOURS = {1, 2, 6, 12, 18, 24}
WINDOW_MINUTES = int(os.getenv("REMINDER_WINDOW_MINUTES", "15"))  # early window before the exact mark
# If the timer/job was down or missed the exact reminder moment, still send
# the reminder while the shift has not started yet. This prevents silent misses
# when systemd timers are delayed, the server was restarted, or a shift was
# assigned after the ideal reminder time.
LATE_GRACE_MINUTES = int(os.getenv("SHIFT_REMINDER_LATE_GRACE_MINUTES", "1440"))

RU_MONTHS_GEN = {
    1: "января", 2: "февраля", 3: "марта", 4: "апреля",
    5: "мая", 6: "июня", 7: "июля", 8: "августа",
    9: "сентября", 10: "октября", 11: "ноября", 12: "декабря",
}

# For manual testing:
# - DRY_RUN=1 will not send, only print matches
# - FORCE_CHAT_ID=<tg_user_id> will send all matches to this chat_id instead of the assignee
DRY_RUN = os.getenv("DRY_RUN", "").strip() in ("1", "true", "yes")
FORCE_CHAT_ID = os.getenv("FORCE_CHAT_ID")


def format_date_ru(d) -> str:
    return f"{d.day} {RU_MONTHS_GEN.get(d.month, str(d.month))}"


def _fmt_time(t) -> str:
    try:
        return t.strftime("%H:%M")
    except Exception:
        s = str(t)
        return s[:5] if len(s) >= 5 else s


def _shift_start_naive(shift_date, start_time):
    return datetime.combine(shift_date, start_time)


def _get_tzinfo():
    tz_name = (os.getenv("AXELIO_TZ") or os.getenv("TZ") or "").strip()
    if tz_name and ZoneInfo is not None:
        try:
            return ZoneInfo(tz_name)
        except Exception:
            return datetime.now().astimezone().tzinfo
    return datetime.now().astimezone().tzinfo


def _normalize_lead_hours(value: int | None) -> int:
    try:
        parsed = int(value or DEFAULT_REMINDER_HOURS)
    except Exception:
        parsed = DEFAULT_REMINDER_HOURS
    return parsed if parsed in ALLOWED_REMINDER_HOURS else DEFAULT_REMINDER_HOURS


def main() -> int:
    tz = _get_tzinfo()
    now = datetime.now(tz)
    max_lead_hours = max(ALLOWED_REMINDER_HOURS | {DEFAULT_REMINDER_HOURS})
    scan_until = now + timedelta(hours=max_lead_hours, minutes=WINDOW_MINUTES + 5)

    d_from: date = now.date()
    d_to: date = scan_until.date()

    sent = 0
    with SessionLocal() as db:
        q = (
            select(ShiftAssignment, Shift, ShiftInterval, User, Venue)
            .join(Shift, Shift.id == ShiftAssignment.shift_id)
            .join(ShiftInterval, ShiftInterval.id == Shift.interval_id)
            .join(User, User.id == ShiftAssignment.member_user_id)
            .join(Venue, Venue.id == Shift.venue_id)
            .where(Shift.is_active.is_(True))
            .where(Shift.date >= d_from)
            .where(Shift.date <= d_to)
        )
        rows = db.execute(q).all()
        for sa, sh, interval, user, venue in rows:
            if not getattr(user, "notify_enabled", True):
                continue
            if not getattr(user, "notify_shifts", True):
                continue
            if not getattr(user, "tg_user_id", None) and not FORCE_CHAT_ID:
                continue
            if sa.reminder_sent_at is not None:
                continue

            lead_hours = _normalize_lead_hours(getattr(user, "shift_reminder_lead_time_hours", DEFAULT_REMINDER_HOURS))
            start_dt = _shift_start_naive(sh.date, interval.start_time).replace(tzinfo=tz)
            planned_at = start_dt - timedelta(hours=lead_hours)

            # Previous logic required the script to run inside a narrow ±window
            # around planned_at. In production this is too fragile: any delayed
            # systemd timer/restart/late assignment skips the reminder forever.
            # New rule: send once when the reminder is due or slightly early,
            # and still allow late delivery until the shift starts.
            if now < planned_at - timedelta(minutes=WINDOW_MINUTES):
                continue
            if now >= start_dt:
                continue
            if now > planned_at + timedelta(minutes=max(LATE_GRACE_MINUTES, WINDOW_MINUTES)):
                continue

            text = (
                f"Напоминаем, что у Вас смена {format_date_ru(sh.date)} "
                f"в {_fmt_time(interval.start_time)} "
                f"в заведении \"{venue.name}\""
            )
            chat_id = int(FORCE_CHAT_ID) if FORCE_CHAT_ID else int(user.tg_user_id)
            dedupe_scope = f"force:{chat_id}" if FORCE_CHAT_ID else notification_dedupe_scope(user)
            shift_slot = str(getattr(sh, "shift_slot", None) or "DAY").upper()
            idempotency_key = (
                f"shift_reminder:{int(sh.id)}:{dedupe_scope}:{lead_hours}:"
                f"{sh.date.isoformat()}:{_fmt_time(interval.start_time)}:{shift_slot}"
            )
            lock_notification_idempotency_key(db, idempotency_key)
            if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
                if not FORCE_CHAT_ID and sa.reminder_sent_at is None:
                    sa.reminder_sent_at = datetime.utcnow().replace(tzinfo=timezone.utc)
                    db.add(sa)
                    db.commit()
                continue

            if DRY_RUN:
                print(
                    f"DRY_RUN match: chat_id={chat_id} user_id={user.id} shift_id={sh.id} "
                    f"start={start_dt} lead_hours={lead_hours} slot={shift_slot} venue=\"{venue.name}\""
                )
                continue

            pending_log = log_notification_attempt(
                db,
                notification_type="shift_reminder",
                status="pending",
                user_id=user.id,
                venue_id=venue.id,
                shift_id=sh.id,
                shift_assignment_id=sa.id,
                planned_at=planned_at,
                idempotency_key=idempotency_key,
                payload_preview=text,
            )
            db.flush()
            db.commit()

            result = tg_notify.notify_result(chat_id=chat_id, text=text)
            ok = bool(result.get("ok"))
            sent_at = datetime.utcnow().replace(tzinfo=timezone.utc) if ok else None
            pending_log.status = "sent" if ok else "failed"
            pending_log.sent_at = sent_at
            pending_log.error_text = None if ok else str(result.get("error") or "notify() returned False")[:2000]
            db.add(pending_log)
            if ok and not FORCE_CHAT_ID:
                sa.reminder_sent_at = sent_at
                db.add(sa)
                sent += 1
            db.commit()

    return sent


if __name__ == "__main__":
    n = main()
    print(f"sent={n}")

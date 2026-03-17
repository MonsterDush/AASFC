from __future__ import annotations

import hashlib
import random
import re
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuthIdentity, PhoneOtpChallenge, User
from app.settings import settings

PHONE_PROVIDER_TELEGRAM = "TELEGRAM"
PHONE_PROVIDER_PHONE = "PHONE"
OTP_STATUS_PENDING = "PENDING"
OTP_STATUS_VERIFIED = "VERIFIED"
OTP_STATUS_EXPIRED = "EXPIRED"
OTP_STATUS_FAILED = "FAILED"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_phone_e164(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Phone is required")

    has_plus = value.startswith("+")
    digits = re.sub(r"\D+", "", value)
    if not digits:
        raise HTTPException(status_code=400, detail="Bad phone format")

    if has_plus:
        e164_digits = digits
    else:
        default_cc = re.sub(r"\D+", "", settings.PHONE_AUTH_DEFAULT_COUNTRY_CODE or "7") or "7"
        if len(digits) == 10:
            e164_digits = default_cc + digits
        elif len(digits) == 11 and digits.startswith("8") and default_cc == "7":
            e164_digits = "7" + digits[1:]
        elif len(digits) == 11 and digits.startswith(default_cc):
            e164_digits = digits
        elif 11 <= len(digits) <= 15:
            e164_digits = digits
        else:
            raise HTTPException(status_code=400, detail="Bad phone format")

    if not (11 <= len(e164_digits) <= 15):
        raise HTTPException(status_code=400, detail="Bad phone length")
    if settings.PHONE_AUTH_REQUIRE_RU_NUMBERS and not e164_digits.startswith("7"):
        raise HTTPException(status_code=400, detail="Пока поддерживаются только российские номера")
    return f"+{e164_digits}"


def mask_phone(phone_e164: str) -> str:
    phone = str(phone_e164 or "")
    if len(phone) <= 5:
        return phone
    return f"{phone[:2]}***{phone[-2:]}"


def _hash_code(*, phone_e164: str, code: str) -> str:
    raw = f"{settings.JWT_SECRET}|{phone_e164}|{code}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def generate_code() -> str:
    length = max(4, min(int(settings.PHONE_AUTH_CODE_LENGTH or 6), 8))
    return ''.join(random.SystemRandom().choice('0123456789') for _ in range(length))


def expire_stale_challenges(db: Session, *, phone_e164: str) -> None:
    now = utcnow()
    rows = db.execute(
        select(PhoneOtpChallenge)
        .where(
            PhoneOtpChallenge.phone_e164 == phone_e164,
            PhoneOtpChallenge.status == OTP_STATUS_PENDING,
        )
        .order_by(PhoneOtpChallenge.id.desc())
    ).scalars().all()
    for row in rows:
        if row.expires_at <= now:
            row.status = OTP_STATUS_EXPIRED


def build_challenge(db: Session, *, phone_e164: str, request_ip: str | None, user_agent: str | None) -> tuple[PhoneOtpChallenge, str]:
    expire_stale_challenges(db, phone_e164=phone_e164)
    now = utcnow()
    cooldown_from = now - timedelta(seconds=int(settings.PHONE_AUTH_RESEND_COOLDOWN_SECONDS or 30))
    recent = db.execute(
        select(PhoneOtpChallenge)
        .where(
            PhoneOtpChallenge.phone_e164 == phone_e164,
            PhoneOtpChallenge.status == OTP_STATUS_PENDING,
            PhoneOtpChallenge.sent_at >= cooldown_from,
        )
        .order_by(PhoneOtpChallenge.id.desc())
    ).scalar_one_or_none()
    if recent is not None:
        raise HTTPException(status_code=429, detail="Код уже отправлен. Подождите немного и попробуйте снова.")

    max_sends_per_day = int(settings.PHONE_AUTH_MAX_SENDS_PER_DAY or 0)
    if max_sends_per_day > 0:
        since = now - timedelta(days=1)
        sent_today = db.execute(
            select(func.count(PhoneOtpChallenge.id)).where(
                PhoneOtpChallenge.phone_e164 == phone_e164,
                PhoneOtpChallenge.sent_at >= since,
            )
        ).scalar_one()
        if int(sent_today or 0) >= max_sends_per_day:
            raise HTTPException(status_code=429, detail="Превышен дневной лимит отправки кодов")

    code = generate_code()
    challenge = PhoneOtpChallenge(
        phone_e164=phone_e164,
        code_hash=_hash_code(phone_e164=phone_e164, code=code),
        status=OTP_STATUS_PENDING,
        provider=str(settings.PHONE_AUTH_PROVIDER or "debug"),
        attempts=0,
        max_attempts=int(settings.PHONE_AUTH_MAX_ATTEMPTS or 5),
        expires_at=now + timedelta(seconds=int(settings.PHONE_AUTH_CODE_TTL_SECONDS or 300)),
        request_ip=(request_ip or None),
        user_agent=(user_agent or None),
    )
    db.add(challenge)
    db.flush()
    return challenge, code


def verify_challenge(db: Session, *, phone_e164: str, code: str) -> PhoneOtpChallenge:
    expire_stale_challenges(db, phone_e164=phone_e164)
    challenge = db.execute(
        select(PhoneOtpChallenge)
        .where(
            PhoneOtpChallenge.phone_e164 == phone_e164,
            PhoneOtpChallenge.status == OTP_STATUS_PENDING,
        )
        .order_by(PhoneOtpChallenge.id.desc())
    ).scalar_one_or_none()
    if challenge is None:
        raise HTTPException(status_code=400, detail="Код не найден или уже истёк")

    if challenge.expires_at <= utcnow():
        challenge.status = OTP_STATUS_EXPIRED
        db.flush()
        raise HTTPException(status_code=400, detail="Код истёк")

    if challenge.attempts >= challenge.max_attempts:
        challenge.status = OTP_STATUS_FAILED
        db.flush()
        raise HTTPException(status_code=429, detail="Превышено число попыток. Запросите новый код")

    if challenge.code_hash != _hash_code(phone_e164=phone_e164, code=str(code or "").strip()):
        challenge.attempts += 1
        if challenge.attempts >= challenge.max_attempts:
            challenge.status = OTP_STATUS_FAILED
        db.flush()
        raise HTTPException(status_code=400, detail="Неверный код")

    challenge.status = OTP_STATUS_VERIFIED
    challenge.verified_at = utcnow()
    db.flush()
    return challenge


def upsert_telegram_identity(db: Session, *, user: User, tg_user_id: int) -> AuthIdentity:
    provider_user_id = str(int(tg_user_id))
    ident = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == PHONE_PROVIDER_TELEGRAM,
            AuthIdentity.provider_user_id == provider_user_id,
        )
    ).scalar_one_or_none()
    if ident is None:
        ident = AuthIdentity(
            user_id=user.id,
            provider=PHONE_PROVIDER_TELEGRAM,
            provider_user_id=provider_user_id,
            is_verified=True,
        )
        db.add(ident)
        db.flush()
        return ident

    if ident.user_id != user.id:
        raise HTTPException(status_code=409, detail="Telegram identity already linked to another user")
    ident.is_verified = True
    db.flush()
    return ident



def link_phone_identity_to_user(db: Session, *, user: User, phone_e164: str) -> AuthIdentity:
    existing = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == PHONE_PROVIDER_PHONE,
            AuthIdentity.phone_e164 == phone_e164,
        )
    ).scalar_one_or_none()

    if existing is not None and existing.user_id != user.id:
        raise HTTPException(status_code=409, detail="Этот номер уже привязан к другой учётной записи")

    # Keep history rows, but only one verified phone per user.
    user_phone_rows = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.user_id == user.id,
            AuthIdentity.provider == PHONE_PROVIDER_PHONE,
        )
    ).scalars().all()
    for row in user_phone_rows:
        row.is_verified = False

    if existing is None:
        existing = AuthIdentity(
            user_id=user.id,
            provider=PHONE_PROVIDER_PHONE,
            phone_e164=phone_e164,
            is_verified=True,
        )
        db.add(existing)
        db.flush()
        return existing

    existing.user_id = user.id
    existing.phone_e164 = phone_e164
    existing.is_verified = True
    db.flush()
    return existing


def link_telegram_identity_to_user(
    db: Session,
    *,
    user: User,
    tg_user_id: int,
    tg_username: str | None = None,
    default_full_name: str | None = None,
    default_short_name: str | None = None,
) -> AuthIdentity:
    provider_user_id = str(int(tg_user_id))
    ident = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == PHONE_PROVIDER_TELEGRAM,
            AuthIdentity.provider_user_id == provider_user_id,
        )
    ).scalar_one_or_none()
    if ident is not None and ident.user_id != user.id:
        raise HTTPException(status_code=409, detail="Этот Telegram-аккаунт уже привязан к другой учётной записи")

    # legacy user.tg_user_id also must stay unique and synced
    clash_user = db.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
    if clash_user is not None and clash_user.id != user.id:
        raise HTTPException(status_code=409, detail="Этот Telegram-аккаунт уже используется другой учётной записью")

    user.tg_user_id = tg_user_id
    if tg_username:
        user.tg_username = tg_username
    if not user.full_name and default_full_name:
        user.full_name = default_full_name
    if not user.short_name and default_short_name:
        user.short_name = default_short_name

    if ident is None:
        ident = AuthIdentity(
            user_id=user.id,
            provider=PHONE_PROVIDER_TELEGRAM,
            provider_user_id=provider_user_id,
            is_verified=True,
        )
        db.add(ident)
        db.flush()
        return ident

    ident.user_id = user.id
    ident.is_verified = True
    db.flush()
    return ident

def get_user_phone(db: Session, *, user_id: int) -> str | None:
    return db.execute(
        select(AuthIdentity.phone_e164)
        .where(
            AuthIdentity.user_id == user_id,
            AuthIdentity.provider == PHONE_PROVIDER_PHONE,
            AuthIdentity.is_verified.is_(True),
        )
        .order_by(AuthIdentity.id.desc())
    ).scalar_one_or_none()


def get_user_auth_methods(db: Session, *, user_id: int) -> list[str]:
    rows = db.execute(
        select(AuthIdentity.provider)
        .where(AuthIdentity.user_id == user_id, AuthIdentity.is_verified.is_(True))
        .order_by(AuthIdentity.id.asc())
    ).scalars().all()
    out: list[str] = []
    for row in rows:
        val = str(row or "").strip().lower()
        if val and val not in out:
            out.append(val)
    return out


def find_or_create_user_by_phone(db: Session, *, phone_e164: str) -> User:
    ident = db.execute(
        select(AuthIdentity).where(
            AuthIdentity.provider == PHONE_PROVIDER_PHONE,
            AuthIdentity.phone_e164 == phone_e164,
            AuthIdentity.is_verified.is_(True),
        )
    ).scalar_one_or_none()
    if ident is not None:
        user = db.execute(select(User).where(User.id == ident.user_id)).scalar_one()
        return user

    user = User(
        tg_user_id=None,
        tg_username=None,
        full_name=None,
        short_name=None,
        system_role="NONE",
    )
    db.add(user)
    db.flush()

    ident = AuthIdentity(
        user_id=user.id,
        provider=PHONE_PROVIDER_PHONE,
        phone_e164=phone_e164,
        is_verified=True,
    )
    db.add(ident)
    db.flush()
    return user

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.jwt_tokens import JwtConfig, create_access_token
from app.auth.passwords import has_password
from app.auth.phone_auth import (
    get_user_auth_methods,
    get_user_phone,
    upsert_telegram_identity,
)
from app.core.db import SessionLocal
from app.core.i18n import localized, user_locale
from app.core.request_ip import resolve_client_ip
from app.models import NotificationDeliveryLog, User
from app.services import tg_notify
from app.services.notification_logs import (
    lock_notification_idempotency_key,
    notification_delivery_exists,
    notification_dedupe_scope,
)
from app.settings import settings

from .auth_schemas import AuthStateOut


_LOG = logging.getLogger("axelio.auth.telegram_browser")


def _jwt_config() -> JwtConfig:
    return JwtConfig(
        secret=settings.JWT_SECRET,
        issuer=settings.JWT_ISS,
        audience=settings.JWT_AUD,
        ttl_seconds=settings.ACCESS_TOKEN_TTL_SECONDS,
    )


def _write_access_cookie(response: Response, *, user: User, extra_claims: dict | None = None) -> None:
    token = create_access_token(
        _jwt_config(),
        user.id,
        session_version=int(user.session_version or 0),
        extra_claims=extra_claims,
    )
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        domain=settings.COOKIE_DOMAIN,
        path="/",
        max_age=settings.ACCESS_TOKEN_TTL_SECONDS,
    )


def _clear_access_cookie(response: Response) -> None:
    response.delete_cookie(
        key="access_token",
        domain=settings.COOKIE_DOMAIN,
        path="/",
        secure=settings.COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def _client_ip(request: Request) -> str | None:
    return resolve_client_ip(request)


def _upsert_user_from_telegram_payload(
    db: Session,
    *,
    tg_user_id: int,
    tg_username: str | None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> User:
    first_name = (first_name or "").strip()
    last_name = (last_name or "").strip()
    default_full_name = " ".join([p for p in [last_name, first_name] if p]) or None
    default_short_name = first_name or (tg_username.lstrip("@") if tg_username else None)

    user = db.query(User).filter(User.tg_user_id == tg_user_id).one_or_none()
    if user is None:
        user = User(
            tg_user_id=tg_user_id,
            tg_username=tg_username,
            full_name=default_full_name,
            short_name=default_short_name,
            system_role="NONE",
        )
        db.add(user)
        db.flush()
    else:
        user.tg_user_id = tg_user_id
        if tg_username and user.tg_username != tg_username:
            user.tg_username = tg_username
        if user.full_name is None and default_full_name:
            user.full_name = default_full_name
        if user.short_name is None and default_short_name:
            user.short_name = default_short_name

    if tg_user_id in settings.super_admin_ids() and user.system_role != "SUPER_ADMIN":
        user.system_role = "SUPER_ADMIN"

    upsert_telegram_identity(db, user=user, tg_user_id=tg_user_id)
    return user


def _auth_state(db: Session, *, user: User) -> AuthStateOut:
    return AuthStateOut(
        user_id=user.id,
        auth_methods=get_user_auth_methods(db, user_id=user.id),
        phone=get_user_phone(db, user_id=user.id),
        has_password=has_password(user),
        password_set_at=(user.password_set_at.isoformat() if user.password_set_at else None),
    )


_PHONE_LINK_REMINDER_TYPE = "phone_link_reminder"
_PHONE_LINK_REMINDER_INTERVAL = timedelta(days=3)


def _phone_link_profile_url() -> str:
    return f"{settings.frontend_base_url()}/profile.html"


def _phone_link_reminder_text(locale: str = "ru") -> str:
    if locale == "en":
        return (
            "To avoid losing access to Axelio, link your phone number and set a password. "
            "You will then be able to sign in through a browser even if Telegram Mini App "
            "is temporarily unavailable.\n\n"
            "Open your profile and link a phone number under Sign-in methods."
        )
    return (
        "Чтобы не потерять доступ к Axelio, рекомендуем привязать номер телефона "
        "и задать пароль. Так вы сможете входить в аккаунт через браузер, даже если "
        "Telegram Mini App временно недоступен.\n\n"
        "Откройте профиль и привяжите телефон в блоке «Способы входа»."
    )


def _send_phone_link_reminder_if_due(user_id: int) -> None:
    """Send a no-phone reminder after Telegram Mini App login, max once per 3 days."""
    try:
        normalized_user_id = int(user_id)
    except Exception:
        return

    try:
        with SessionLocal() as db:
            user = db.get(User, normalized_user_id)
            if user is None:
                return
            if not getattr(user, "tg_user_id", None):
                return
            if getattr(user, "is_demo_user", False):
                return
            if getattr(user, "notify_enabled", True) is False:
                return
            if get_user_phone(db, user_id=int(user.id)):
                return

            now = _utcnow()
            cutoff = now - _PHONE_LINK_REMINDER_INTERVAL

            dedupe_scope = notification_dedupe_scope(user)
            key_prefix = f"phone_link_reminder:{dedupe_scope}:"

            recent_sent = db.execute(
                select(NotificationDeliveryLog.id)
                .where(
                    NotificationDeliveryLog.notification_type == _PHONE_LINK_REMINDER_TYPE,
                    NotificationDeliveryLog.idempotency_key.like(f"{key_prefix}%"),
                    NotificationDeliveryLog.status == "sent",
                    NotificationDeliveryLog.sent_at.is_not(None),
                    NotificationDeliveryLog.sent_at >= cutoff,
                )
                .order_by(NotificationDeliveryLog.sent_at.desc(), NotificationDeliveryLog.id.desc())
                .limit(1)
            ).first()
            if recent_sent is not None:
                return

            recent_pending = db.execute(
                select(NotificationDeliveryLog.id)
                .where(
                    NotificationDeliveryLog.notification_type == _PHONE_LINK_REMINDER_TYPE,
                    NotificationDeliveryLog.idempotency_key.like(f"{key_prefix}%"),
                    NotificationDeliveryLog.status == "pending",
                    NotificationDeliveryLog.planned_at.is_not(None),
                    NotificationDeliveryLog.planned_at >= cutoff,
                )
                .order_by(NotificationDeliveryLog.planned_at.desc(), NotificationDeliveryLog.id.desc())
                .limit(1)
            ).first()
            if recent_pending is not None:
                return

            idempotency_key = f"{key_prefix}{now.date().isoformat()}"
            lock_notification_idempotency_key(db, idempotency_key)
            if notification_delivery_exists(db, idempotency_key=idempotency_key, statuses=("pending", "sent")):
                return

            locale = user_locale(user)
            text = _phone_link_reminder_text(locale)
            delivery_log = NotificationDeliveryLog(
                notification_type=_PHONE_LINK_REMINDER_TYPE,
                status="pending",
                user_id=int(user.id),
                venue_id=None,
                planned_at=now,
                idempotency_key=idempotency_key,
                payload_preview=text[:2000],
            )
            db.add(delivery_log)
            db.commit()
            db.refresh(delivery_log)

            result = tg_notify.notify_result(
                chat_id=int(user.tg_user_id),
                text=text,
                url=_phone_link_profile_url(),
                button_text=localized(locale, ru="Открыть профиль", en="Open profile"),
            )
            ok = bool(result.get("ok"))
            delivery_log.status = "sent" if ok else "failed"
            delivery_log.sent_at = now if ok else None
            delivery_log.error_text = None if ok else str(result.get("error") or "notify() returned False")[:2000]
            db.add(delivery_log)
            db.commit()
    except Exception:
        _LOG.exception("phone link reminder failed user_id=%s", user_id)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_next_path(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return None
    if not raw.startswith("/"):
        raw = "/" + raw
    if raw.startswith("/auth.html"):
        return "/"
    if len(raw) > 1024:
        raw = raw[:1024]
    return raw

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.account_merge import merge_user_accounts
from app.auth.deps import get_current_user, get_current_user_optional
from app.auth.jwt_tokens import JwtConfig, create_access_token
from app.auth.passwords import has_password, set_password, validate_new_password, verify_password
from app.auth.phone_auth import (
    OTP_CHANNEL_CALL,
    OTP_CHANNEL_SMS,
    OTP_PURPOSE_LINK_PHONE,
    OTP_PURPOSE_PHONE_LOGIN,
    OTP_PURPOSE_RESET_PASSWORD,
    OTP_STATUS_EXPIRED,
    OTP_STATUS_PENDING,
    OTP_STATUS_VERIFIED,
    build_challenge,
    find_or_create_user_by_phone,
    find_user_by_phone,
    get_challenge_by_id,
    get_user_auth_methods,
    get_user_phone,
    link_phone_identity_to_user,
    link_telegram_identity_to_user,
    mark_challenge_verified,
    normalize_phone_e164,
    resolve_verified_challenge,
    upsert_telegram_identity,
)
from app.auth.telegram_webapp import TelegramInitDataError, verify_init_data
from app.auth.telegram_widget import TelegramLoginWidgetError, verify_login_widget_data
from app.core.db import get_db
from app.core.tg import normalize_tg_username
from app.models import TelegramBrowserAuthSession, User, Venue
from app.services.demo.analytics import record_demo_event
from app.services.demo.access import build_demo_banner_payload, get_demo_session_or_none
from app.services.demo.session import (
    DEMO_PERSONA_OWNER,
    build_demo_session_claims,
    build_demo_start_url,
    get_demo_user_for_venue,
    get_public_demo_venue,
    normalize_demo_persona,
)
from app.services.invites import accept_invites_for_user, accept_phone_invites_for_user
from app.services.sms_auth import get_sms_provider
from app.settings import settings

_LOG = logging.getLogger("axelio.auth.telegram_browser")

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramAuthIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    initData: str = Field(alias="init_data")


class TelegramWidgetAuthIn(BaseModel):
    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str


class PhoneCodeRequestIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)


class PhoneCodeVerifyIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    code: str | None = Field(default=None, min_length=4, max_length=8)
    challenge_id: int | None = None
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class PasswordLoginIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordResetConfirmIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    code: str | None = Field(default=None, min_length=4, max_length=8)
    challenge_id: int | None = None
    new_password: str = Field(..., min_length=8, max_length=128)


class AuthStateOut(BaseModel):
    ok: bool = True
    user_id: int
    auth_methods: list[str] = []
    phone: str | None = None
    has_password: bool = False
    password_set_at: str | None = None


class LinkTelegramIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    initData: str = Field(alias="init_data")


class TelegramBrowserAuthStartIn(BaseModel):
    next_path: str | None = Field(default=None, max_length=1024)


class TelegramBrowserAuthStartOut(BaseModel):
    ok: bool = True
    enabled: bool = True
    session_token: str
    bot_username: str
    deep_link_url: str
    expires_in_seconds: int
    poll_interval_ms: int = 2000
    status: str = "PENDING"


class TelegramBrowserAuthStatusOut(BaseModel):
    ok: bool = True
    status: str
    authorized: bool = False
    expires_in_seconds: int = 0
    finalized: bool = False
    telegram_username: str | None = None


class TelegramBrowserAuthFinalizeIn(BaseModel):
    session_token: str = Field(..., min_length=16, max_length=64)


class DemoSwitchPersonaIn(BaseModel):
    persona: str = Field(default=DEMO_PERSONA_OWNER, min_length=3, max_length=32)
    next_path: str | None = Field(default=None, max_length=1024)


class PasswordStateOut(BaseModel):
    ok: bool = True
    user_id: int
    has_password: bool
    password_set_at: str | None = None
    password_changed_at: str | None = None


class PhoneCallStatusOut(BaseModel):
    ok: bool = True
    challenge_id: int
    phone: str
    purpose: str
    verification_channel: str
    provider: str
    status: str
    verified: bool = False
    expired: bool = False
    pending: bool = False
    call_phone: str | None = None
    call_phone_pretty: str | None = None
    status_text: str | None = None
    fallback_after_seconds: int = 10


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
    return request.client.host if request.client else None


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


def _telegram_browser_bot_username() -> str:
    """Return bot username for browser auth without calling Telegram API.

    Browser Telegram auth must not depend on outbound api.telegram.org calls.
    Set TG_BROWSER_LOGIN_BOT_USERNAME (preferred) or TG_LOGIN_WIDGET_BOT_USERNAME
    in backend .env.
    """
    return str(
        settings.TG_BROWSER_LOGIN_BOT_USERNAME
        or settings.TG_LOGIN_WIDGET_BOT_USERNAME
        or ""
    ).strip().lstrip("@")


def _browser_login_ttl_seconds() -> int:
    return max(int(settings.TG_BROWSER_LOGIN_SESSION_TTL_SECONDS or 600), 60)


def _browser_login_prefix() -> str:
    return "browser_login_"


def _browser_link_prefix() -> str:
    return "browser_link_"


def _new_browser_login_token() -> str:
    return secrets.token_hex(16)


def _get_browser_login_session(db: Session, *, session_token: str) -> TelegramBrowserAuthSession:
    token = str(session_token or "").strip().lower()
    session = db.execute(
        select(TelegramBrowserAuthSession).where(TelegramBrowserAuthSession.public_token == token)
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=404, detail="Сессия входа через Telegram не найдена")
    return session


def _expire_browser_login_session(session: TelegramBrowserAuthSession) -> bool:
    if str(session.status or "").upper() == "EXPIRED":
        return True
    if session.expires_at <= _utcnow():
        session.status = "EXPIRED"
        return True
    return False


def _browser_login_status_payload(session: TelegramBrowserAuthSession) -> TelegramBrowserAuthStatusOut:
    expires_in_seconds = max(0, int((session.expires_at - _utcnow()).total_seconds()))
    status_value = str(session.status or "PENDING").upper()
    return TelegramBrowserAuthStatusOut(
        status=status_value,
        authorized=status_value in {"COMPLETED", "FINALIZED"} and bool(session.user_id),
        expires_in_seconds=expires_in_seconds,
        finalized=status_value == "FINALIZED",
        telegram_username=(normalize_tg_username(session.tg_username) if session.tg_username else None),
    )


# Browser Telegram auth is intentionally inbound-only.
#
# Previous versions tried to answer /start with sendMessage and then waited for an
# inline callback. On this VPS outgoing Telegram API calls are unstable, so the
# browser flow no longer calls api.telegram.org at all. Opening the deep-link is
# treated as confirmation: Telegram sends /start <token> to our webhook, backend
# marks the session COMPLETED, and the browser polling endpoint finalizes login.

def _telegram_user_from_update(value: dict | None) -> tuple[int, str | None, str, str]:
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="Telegram user payload is missing")
    try:
        tg_user_id = int(value.get("id"))
    except Exception:
        raise HTTPException(status_code=400, detail="Telegram user id is missing")
    return (
        tg_user_id,
        normalize_tg_username(value.get("username")),
        str(value.get("first_name") or "").strip(),
        str(value.get("last_name") or "").strip(),
    )


def _complete_browser_login_session(

    db: Session,
    *,
    session_token: str,
    tg_user_id: int,
    tg_username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> tuple[TelegramBrowserAuthSession, User]:
    session = _get_browser_login_session(db, session_token=session_token)
    if _expire_browser_login_session(session):
        db.commit()
        raise HTTPException(status_code=410, detail="Сессия входа через Telegram истекла")

    if str(session.status or "PENDING").upper() in {"COMPLETED", "FINALIZED"} and session.user_id:
        user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=404, detail="Пользователь для этой сессии не найден")
        return session, user

    user = _upsert_user_from_telegram_payload(
        db,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
    )
    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    session.user_id = user.id
    session.tg_user_id = tg_user_id
    session.tg_username = tg_username
    session.status = "COMPLETED"
    session.completed_at = _utcnow()
    db.flush()
    db.commit()
    db.refresh(user)
    return session, user


def _complete_browser_link_session(
    db: Session,
    *,
    session_token: str,
    tg_user_id: int,
    tg_username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> tuple[TelegramBrowserAuthSession, User]:
    session = _get_browser_login_session(db, session_token=session_token)
    if _expire_browser_login_session(session):
        db.commit()
        raise HTTPException(status_code=410, detail="Сессия привязки Telegram истекла")
    if not session.user_id:
        raise HTTPException(status_code=409, detail="Для этой сессии не найден пользователь")

    target_user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
    if target_user is None:
        raise HTTPException(status_code=404, detail="Пользователь для этой сессии не найден")

    if str(session.status or "PENDING").upper() in {"COMPLETED", "FINALIZED"} and session.tg_user_id == tg_user_id:
        return session, target_user

    default_full_name = " ".join([p for p in [(last_name or "").strip(), (first_name or "").strip()] if p]) or None
    default_short_name = (first_name or "").strip() or (tg_username.lstrip("@") if tg_username else None)

    existing_tg_user = db.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
    if existing_tg_user is not None and existing_tg_user.id != target_user.id:
        target_user = merge_user_accounts(db, target_user=target_user, source_user=existing_tg_user)

    link_telegram_identity_to_user(
        db,
        user=target_user,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        default_full_name=default_full_name,
        default_short_name=default_short_name,
    )
    if tg_user_id in settings.super_admin_ids() and target_user.system_role != "SUPER_ADMIN":
        target_user.system_role = "SUPER_ADMIN"

    accept_invites_for_user(db, user_id=target_user.id, tg_username=target_user.tg_username)
    session.user_id = target_user.id
    session.tg_user_id = tg_user_id
    session.tg_username = tg_username
    session.status = "COMPLETED"
    session.completed_at = _utcnow()
    db.flush()
    db.commit()
    db.refresh(target_user)
    return session, target_user


def _handle_browser_login_start_message(db: Session, *, text: str, from_user: dict | None = None) -> None:
    """Auto-confirm browser login/link from Telegram /start payload.

    No messages are sent back to Telegram. This makes the flow independent from
    outbound Telegram API availability.
    """
    raw = str(text or "").strip()
    if not raw.startswith("/start"):
        return

    parts = raw.split(maxsplit=1)
    command = str(parts[0] if parts else "").split("@", 1)[0].strip().lower()
    if command != "/start":
        return

    start_arg = parts[1].strip() if len(parts) > 1 else ""
    if not start_arg:
        return

    try:
        tg_user_id, tg_username, first_name, last_name = _telegram_user_from_update(from_user)

        if start_arg.startswith(_browser_login_prefix()):
            session_token = start_arg[len(_browser_login_prefix()):].strip().lower()
            _complete_browser_login_session(
                db,
                session_token=session_token,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
            )
            return

        if start_arg.startswith(_browser_link_prefix()):
            session_token = start_arg[len(_browser_link_prefix()):].strip().lower()
            _complete_browser_link_session(
                db,
                session_token=session_token,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
            )
            return

        # Unknown /start payload: do nothing. The browser flow is driven only by
        # Axelio-generated browser_login_/browser_link_ tokens.
        return
    except HTTPException:
        db.rollback()
        _LOG.exception("telegram browser auto-confirm rejected")
    except Exception:
        db.rollback()
        _LOG.exception("telegram browser auto-confirm failed")


def _handle_browser_login_callback(db: Session, *, callback_query: dict) -> None:
    """Backward-compatible no-outbound callback handler.

    Old messages with inline buttons may still exist in Telegram. If clicked, we
    complete the session but do not call answerCallbackQuery/editMessageText.
    """
    data = str(callback_query.get("data") or "")
    if data.startswith("browser_login:"):
        mode = "login"
    elif data.startswith("browser_link:"):
        mode = "link"
    else:
        return

    try:
        session_token = data.split(":", 1)[1].strip().lower()
        tg_user_id, tg_username, first_name, last_name = _telegram_user_from_update(callback_query.get("from") or {})
        if mode == "login":
            _complete_browser_login_session(
                db,
                session_token=session_token,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
            )
        else:
            _complete_browser_link_session(
                db,
                session_token=session_token,
                tg_user_id=tg_user_id,
                tg_username=tg_username,
                first_name=first_name,
                last_name=last_name,
            )
    except HTTPException:
        db.rollback()
        _LOG.exception("telegram browser callback auto-confirm rejected")
    except Exception:
        db.rollback()
        _LOG.exception("telegram browser callback auto-confirm failed")


def _phone_auth_config_payload() -> dict:
    return {
        "ok": True,
        "call_enabled": bool(settings.PHONE_AUTH_CALL_ENABLED),
        "sms_enabled": bool(settings.PHONE_AUTH_SMS_ENABLED),
        "fallback_after_seconds": int(settings.PHONE_AUTH_CALL_FALLBACK_AFTER_SECONDS or 10),
    }


def _ensure_phone_call_enabled() -> None:
    if not bool(settings.PHONE_AUTH_CALL_ENABLED):
        raise HTTPException(status_code=503, detail="Подтверждение звонком временно отключено")


def _ensure_phone_sms_enabled() -> None:
    if not bool(settings.PHONE_AUTH_SMS_ENABLED):
        raise HTTPException(status_code=503, detail="Подтверждение по SMS временно отключено")


def _challenge_to_status_out(challenge, *, status_text: str | None = None) -> PhoneCallStatusOut:
    verified = challenge.status == OTP_STATUS_VERIFIED
    expired = challenge.status == OTP_STATUS_EXPIRED
    pending = challenge.status == OTP_STATUS_PENDING
    return PhoneCallStatusOut(
        challenge_id=challenge.id,
        phone=challenge.phone_e164,
        purpose=str(challenge.purpose or ""),
        verification_channel=str(challenge.verification_channel or OTP_CHANNEL_SMS),
        provider=str(challenge.provider or ""),
        status=str(challenge.status or OTP_STATUS_PENDING),
        verified=verified,
        expired=expired,
        pending=pending,
        call_phone=str(challenge.external_target or "") or None,
        call_phone_pretty=str(challenge.external_target or "") or None,
        status_text=status_text,
        fallback_after_seconds=int(settings.PHONE_AUTH_CALL_FALLBACK_AFTER_SECONDS or 10),
    )


def _request_sms_challenge(db: Session, *, phone_e164: str, request: Request, purpose: str):
    challenge, code = build_challenge(
        db,
        phone_e164=phone_e164,
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        purpose=purpose,
        channel=OTP_CHANNEL_SMS,
    )
    provider = get_sms_provider()
    send_result = provider.send_code(
        phone_e164=phone_e164,
        code=code,
        request_ip=_client_ip(request),
    )
    db.commit()

    out = {
        "ok": True,
        "phone": phone_e164,
        "provider": send_result.provider,
        "verification_channel": OTP_CHANNEL_SMS,
        "expires_in_seconds": int(settings.PHONE_AUTH_CODE_TTL_SECONDS or 300),
        "cooldown_seconds": int(settings.PHONE_AUTH_RESEND_COOLDOWN_SECONDS or 60),
        "challenge_id": challenge.id,
        "purpose": purpose,
    }
    if send_result.get("sms_id"):
        out["sms_id"] = send_result.get("sms_id")
    if send_result.get("test"):
        out["test"] = True
    if "debug_code" in send_result:
        out["debug_code"] = send_result["debug_code"]
    return out


def _request_call_challenge(db: Session, *, phone_e164: str, request: Request, purpose: str):
    challenge, _ = build_challenge(
        db,
        phone_e164=phone_e164,
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        purpose=purpose,
        channel=OTP_CHANNEL_CALL,
    )
    provider = get_sms_provider()
    call_result = provider.start_call_verification(
        phone_e164=phone_e164,
        request_ip=_client_ip(request),
    )
    challenge.provider = call_result.provider
    challenge.external_check_id = str(call_result.get("check_id") or "").strip() or None
    challenge.external_target = str(call_result.get("call_phone_pretty") or call_result.get("call_phone") or "").strip() or None
    db.flush()
    db.commit()
    return {
        "ok": True,
        "phone": phone_e164,
        "provider": call_result.provider,
        "verification_channel": OTP_CHANNEL_CALL,
        "expires_in_seconds": int(settings.PHONE_AUTH_CODE_TTL_SECONDS or 300),
        "cooldown_seconds": int(settings.PHONE_AUTH_RESEND_COOLDOWN_SECONDS or 60),
        "fallback_after_seconds": int(settings.PHONE_AUTH_CALL_FALLBACK_AFTER_SECONDS or 10),
        "challenge_id": challenge.id,
        "purpose": purpose,
        "call_phone": call_result.get("call_phone"),
        "call_phone_pretty": call_result.get("call_phone_pretty"),
        "call_phone_html": call_result.get("call_phone_html"),
    }


def _resolve_verification(db: Session, *, phone_e164: str, purpose: str, code: str | None, challenge_id: int | None):
    return resolve_verified_challenge(
        db,
        phone_e164=phone_e164,
        purpose=purpose,
        code=code,
        challenge_id=challenge_id,
    )



@router.post("/telegram/browser/start", response_model=TelegramBrowserAuthStartOut)
def start_telegram_browser_auth(
    payload: TelegramBrowserAuthStartIn,
    request: Request,
    db: Session = Depends(get_db),
):
    bot_username = _telegram_browser_bot_username()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram browser login is not configured")

    session = TelegramBrowserAuthSession(
        public_token=_new_browser_login_token(),
        status="PENDING",
        next_path=_normalize_next_path(payload.next_path),
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        expires_at=_utcnow() + timedelta(seconds=_browser_login_ttl_seconds()),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return TelegramBrowserAuthStartOut(
        session_token=session.public_token,
        bot_username=bot_username,
        deep_link_url=f"https://t.me/{bot_username}?start={_browser_login_prefix()}{session.public_token}",
        expires_in_seconds=_browser_login_ttl_seconds(),
    )


@router.get("/telegram/browser/status/{session_token}", response_model=TelegramBrowserAuthStatusOut)
def telegram_browser_auth_status(session_token: str, db: Session = Depends(get_db)):
    session = _get_browser_login_session(db, session_token=session_token)
    if _expire_browser_login_session(session):
        db.commit()
    else:
        db.flush()
    return _browser_login_status_payload(session)


@router.post("/telegram/browser/finalize", response_model=AuthStateOut)
def finalize_telegram_browser_auth(
    payload: TelegramBrowserAuthFinalizeIn,
    response: Response,
    db: Session = Depends(get_db),
):
    session = _get_browser_login_session(db, session_token=payload.session_token)
    if _expire_browser_login_session(session):
        db.commit()
        raise HTTPException(status_code=410, detail="Сессия входа через Telegram истекла")

    if str(session.status or "PENDING").upper() not in {"COMPLETED", "FINALIZED"} or not session.user_id:
        raise HTTPException(status_code=409, detail="Подтверждение в Telegram ещё не завершено")

    user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь для этой сессии не найден")

    session.status = "FINALIZED"
    if session.finalized_at is None:
        session.finalized_at = _utcnow()
    db.commit()
    db.refresh(user)
    _write_access_cookie(response, user=user)
    return _auth_state(db, user=user)


def _process_telegram_browser_update(db: Session, *, update: dict) -> None:
    """Process Telegram webhook update for browser login/link flow.

    The same handler is reused by the canonical /auth/telegram/browser/webhook
    endpoint and by legacy webhook aliases declared in app/main.py.
    """
    if not isinstance(update, dict):
        return

    callback_query = update.get("callback_query")
    if isinstance(callback_query, dict):
        _handle_browser_login_callback(db, callback_query=callback_query)
        return

    message = update.get("message")
    if not isinstance(message, dict):
        message = update.get("edited_message") if isinstance(update.get("edited_message"), dict) else None

    if isinstance(message, dict):
        text = message.get("text")
        if text:
            _handle_browser_login_start_message(
                db,
                text=str(text),
                from_user=(message.get("from") or {}),
            )
        return


async def process_telegram_browser_webhook_request(
    request: Request,
    *,
    x_telegram_bot_api_secret_token: str | None,
    db: Session,
) -> None:
    secret = str(settings.TG_WEBHOOK_SECRET_TOKEN or "").strip()
    if secret and str(x_telegram_bot_api_secret_token or "").strip() != secret:
        raise HTTPException(status_code=401, detail="bad telegram secret")

    try:
        update = await request.json()
    except Exception:
        _LOG.warning("telegram browser webhook received invalid json")
        return

    _process_telegram_browser_update(db, update=update)


@router.post("/telegram/browser/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_browser_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    await process_telegram_browser_webhook_request(
        request,
        x_telegram_bot_api_secret_token=x_telegram_bot_api_secret_token,
        db=db,
    )
    return None


@router.post("/telegram", status_code=status.HTTP_204_NO_CONTENT)
def auth_telegram(payload: TelegramAuthIn, response: Response, db: Session = Depends(get_db)):
    try:
        data = verify_init_data(payload.initData, settings.TG_BOT_TOKEN)
    except TelegramInitDataError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status_code=400, detail="user is missing in initData")

    try:
        tg_user = json.loads(user_raw)
        tg_user_id = int(tg_user["id"])
        tg_username = normalize_tg_username(tg_user.get("username"))
        first_name = (tg_user.get("first_name") or "").strip()
        last_name = (tg_user.get("last_name") or "").strip()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user payload")

    user = _upsert_user_from_telegram_payload(
        db,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
    )
    db.commit()
    db.refresh(user)

    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    _write_access_cookie(response, user=user)
    return


@router.get("/telegram/widget/config")
def telegram_widget_config():
    bot_username = str(settings.TG_LOGIN_WIDGET_BOT_USERNAME or "").strip()
    return {
        "ok": True,
        "enabled": bool(bot_username),
        "bot_username": bot_username or None,
    }


@router.post("/telegram/widget", status_code=status.HTTP_204_NO_CONTENT)
def auth_telegram_widget(payload: TelegramWidgetAuthIn, response: Response, db: Session = Depends(get_db)):
    bot_username = str(settings.TG_LOGIN_WIDGET_BOT_USERNAME or "").strip()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram Login Widget is not configured")

    try:
        data = verify_login_widget_data(
            payload.model_dump(exclude_none=True),
            settings.TG_BOT_TOKEN,
            max_age_seconds=int(settings.TG_LOGIN_WIDGET_MAX_AGE_SECONDS or 3600),
        )
    except TelegramLoginWidgetError as e:
        raise HTTPException(status_code=401, detail=str(e))

    try:
        tg_user_id = int(data["id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Telegram widget payload")

    tg_username = normalize_tg_username(data.get("username"))
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()

    user = _upsert_user_from_telegram_payload(
        db,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        first_name=first_name,
        last_name=last_name,
    )
    db.commit()
    db.refresh(user)

    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    _write_access_cookie(response, user=user)
    return


@router.get("/phone/config")
def phone_auth_config():
    return _phone_auth_config_payload()


@router.post("/phone/request-call")
def request_phone_call(payload: PhoneCodeRequestIn, request: Request, db: Session = Depends(get_db)):
    _ensure_phone_call_enabled()
    phone_e164 = normalize_phone_e164(payload.phone)
    return _request_call_challenge(db, phone_e164=phone_e164, request=request, purpose=OTP_PURPOSE_PHONE_LOGIN)


@router.post("/phone/request-code")
def request_phone_code(payload: PhoneCodeRequestIn, request: Request, db: Session = Depends(get_db)):
    _ensure_phone_sms_enabled()
    phone_e164 = normalize_phone_e164(payload.phone)
    return _request_sms_challenge(db, phone_e164=phone_e164, request=request, purpose=OTP_PURPOSE_PHONE_LOGIN)


@router.get("/phone/call-status/{challenge_id}", response_model=PhoneCallStatusOut)
def phone_call_status(challenge_id: int, phone: str = Query(..., min_length=5, max_length=32), db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(phone)
    challenge = get_challenge_by_id(db, challenge_id=challenge_id, phone_e164=phone_e164)
    if str(challenge.verification_channel or OTP_CHANNEL_SMS) != OTP_CHANNEL_CALL:
        raise HTTPException(status_code=400, detail="Это подтверждение не использует звонок")

    if challenge.status == OTP_STATUS_VERIFIED:
        db.commit()
        return _challenge_to_status_out(challenge, status_text="Номер уже подтверждён")
    if challenge.status == OTP_STATUS_EXPIRED:
        db.commit()
        return _challenge_to_status_out(challenge, status_text="Время подтверждения истекло")

    provider = get_sms_provider()
    status_result = provider.get_call_verification_status(check_id=str(challenge.external_check_id or ""))
    if status_result.get("confirmed"):
        mark_challenge_verified(db, challenge=challenge)
    elif status_result.get("expired"):
        challenge.status = OTP_STATUS_EXPIRED
        db.flush()

    db.commit()
    challenge = get_challenge_by_id(db, challenge_id=challenge_id, phone_e164=phone_e164)
    out = _challenge_to_status_out(challenge, status_text=str(status_result.get("check_status_text") or "").strip() or None)
    if status_result.get("call_phone_pretty") and not out.call_phone_pretty:
        out.call_phone_pretty = str(status_result.get("call_phone_pretty") or "") or out.call_phone_pretty
    return out


@router.post("/phone/verify-code", response_model=AuthStateOut)
def verify_phone_code(payload: PhoneCodeVerifyIn, response: Response, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    _resolve_verification(
        db,
        phone_e164=phone_e164,
        purpose=OTP_PURPOSE_PHONE_LOGIN,
        code=payload.code,
        challenge_id=payload.challenge_id,
    )
    user = find_or_create_user_by_phone(db, phone_e164=phone_e164)
    if payload.new_password:
        set_password(user, payload.new_password)
    db.commit()
    db.refresh(user)

    accept_phone_invites_for_user(db, user_id=user.id, phone_e164=phone_e164)
    _write_access_cookie(response, user=user)
    return _auth_state(db, user=user)


@router.post("/password/login", response_model=AuthStateOut)
def password_login(payload: PasswordLoginIn, response: Response, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    user = find_user_by_phone(db, phone_e164=phone_e164)
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный номер или пароль")

    _write_access_cookie(response, user=user)
    return _auth_state(db, user=user)


@router.post("/password/set-after-phone-verify", response_model=AuthStateOut)
def set_password_after_phone_verify(payload: PasswordResetConfirmIn, response: Response, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    _resolve_verification(
        db,
        phone_e164=phone_e164,
        purpose=OTP_PURPOSE_PHONE_LOGIN,
        code=payload.code,
        challenge_id=payload.challenge_id,
    )
    user = find_or_create_user_by_phone(db, phone_e164=phone_e164)
    set_password(user, payload.new_password)
    db.commit()
    db.refresh(user)

    accept_phone_invites_for_user(db, user_id=user.id, phone_e164=phone_e164)
    _write_access_cookie(response, user=user)
    return _auth_state(db, user=user)


@router.post("/password/reset/request-call")
def request_password_reset_call(payload: PhoneCodeRequestIn, request: Request, db: Session = Depends(get_db)):
    _ensure_phone_call_enabled()
    phone_e164 = normalize_phone_e164(payload.phone)
    user = find_user_by_phone(db, phone_e164=phone_e164)
    if user is None or not has_password(user):
        raise HTTPException(status_code=404, detail="Для этого номера пароль ещё не настроен")
    return _request_call_challenge(db, phone_e164=phone_e164, request=request, purpose=OTP_PURPOSE_RESET_PASSWORD)


@router.post("/password/reset/request-code")
def request_password_reset_code(payload: PhoneCodeRequestIn, request: Request, db: Session = Depends(get_db)):
    _ensure_phone_sms_enabled()
    phone_e164 = normalize_phone_e164(payload.phone)
    user = find_user_by_phone(db, phone_e164=phone_e164)
    if user is None or not has_password(user):
        raise HTTPException(status_code=404, detail="Для этого номера пароль ещё не настроен")
    return _request_sms_challenge(db, phone_e164=phone_e164, request=request, purpose=OTP_PURPOSE_RESET_PASSWORD)


@router.post("/password/reset/confirm", response_model=AuthStateOut)
def confirm_password_reset(payload: PasswordResetConfirmIn, response: Response, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    _resolve_verification(
        db,
        phone_e164=phone_e164,
        purpose=OTP_PURPOSE_RESET_PASSWORD,
        code=payload.code,
        challenge_id=payload.challenge_id,
    )
    user = find_user_by_phone(db, phone_e164=phone_e164)
    if user is None:
        raise HTTPException(status_code=404, detail="Пользователь с таким номером не найден")

    set_password(user, payload.new_password)
    db.commit()
    db.refresh(user)

    _write_access_cookie(response, user=user)
    return _auth_state(db, user=user)


@router.get("/password/state", response_model=PasswordStateOut)
def password_state(user: User = Depends(get_current_user)):
    return PasswordStateOut(
        user_id=user.id,
        has_password=has_password(user),
        password_set_at=(user.password_set_at.isoformat() if user.password_set_at else None),
        password_changed_at=(user.password_changed_at.isoformat() if user.password_changed_at else None),
    )


@router.post("/password/change", response_model=PasswordStateOut)
def change_password(
    payload: PasswordChangeIn,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if not has_password(user):
        raise HTTPException(status_code=400, detail="У текущей учётной записи пароль ещё не установлен")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")

    validate_new_password(payload.new_password)
    set_password(user, payload.new_password)
    db.commit()
    db.refresh(user)
    _write_access_cookie(response, user=user)
    return PasswordStateOut(
        user_id=user.id,
        has_password=has_password(user),
        password_set_at=(user.password_set_at.isoformat() if user.password_set_at else None),
        password_changed_at=(user.password_changed_at.isoformat() if user.password_changed_at else None),
    )


def _build_demo_session_payload(*, venue: Venue, persona: str, session_id: str | None = None) -> dict:
    persona_upper = normalize_demo_persona(persona, default=DEMO_PERSONA_OWNER)
    claims = build_demo_session_claims(venue=venue, persona=persona_upper, session_id=session_id)
    return {
        "ok": True,
        "demo_mode": True,
        "demo_persona": persona_upper,
        "demo_venue_id": int(venue.id),
        "demo_reference_year": getattr(venue, "demo_reference_year", None),
        "demo_reference_month": getattr(venue, "demo_reference_month", None),
        "redirect_url": build_demo_start_url(
            venue_id=int(venue.id),
            persona=persona_upper,
        ),
        "banner": build_demo_banner_payload(),
        "claims": claims,
    }


def _resolve_demo_identity_or_404(db: Session, *, persona: str) -> tuple[Venue, User, str]:
    venue = get_public_demo_venue(db)
    if venue is None:
        raise HTTPException(status_code=404, detail="Публичное DEMO-заведение не настроено")

    persona_upper = normalize_demo_persona(persona, default=DEMO_PERSONA_OWNER)
    demo_user = get_demo_user_for_venue(db, venue_id=int(venue.id), persona=persona_upper)
    if demo_user is None:
        raise HTTPException(status_code=404, detail=f"DEMO-пользователь для роли {persona_upper} не настроен")

    return venue, demo_user, persona_upper


@router.get("/demo/start")
def start_demo_session(
    db: Session = Depends(get_db),
    persona: str = Query(default=DEMO_PERSONA_OWNER),
    next_path: str | None = Query(default=None),
):
    venue, demo_user, persona_upper = _resolve_demo_identity_or_404(db, persona=persona)
    claims = build_demo_session_claims(venue=venue, persona=persona_upper)
    redirect_url = build_demo_start_url(venue_id=int(venue.id), persona=persona_upper, next_path=next_path)
    redirect = RedirectResponse(url=redirect_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    _write_access_cookie(redirect, user=demo_user, extra_claims=claims)
    try:
        record_demo_event(db, event_name="demo_start", user=demo_user, venue_id=int(venue.id), persona=persona_upper, page_path=redirect_url, session_id=claims.get("demo_session_id"), meta={"source": "auth_start"})
        db.commit()
    except Exception:
        db.rollback()
    return redirect


@router.post("/demo/switch-persona")
def switch_demo_persona(
    payload: DemoSwitchPersonaIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demo_ctx = get_demo_session_or_none(user)
    if demo_ctx is None:
        raise HTTPException(status_code=403, detail="DEMO-сессия не активна")

    venue = db.execute(select(Venue).where(Venue.id == int(demo_ctx.venue_id))).scalar_one_or_none()
    if venue is None or not bool(getattr(venue, "is_demo", False)):
        raise HTTPException(status_code=404, detail="DEMO-заведение не найдено")

    persona_upper = normalize_demo_persona(payload.persona, default=DEMO_PERSONA_OWNER)
    demo_user = get_demo_user_for_venue(db, venue_id=int(venue.id), persona=persona_upper)
    if demo_user is None:
        raise HTTPException(status_code=404, detail=f"DEMO-пользователь для роли {persona_upper} не настроен")

    claims = build_demo_session_claims(venue=venue, persona=persona_upper)
    body = {
        "ok": True,
        "demo_mode": True,
        "demo_persona": persona_upper,
        "demo_venue_id": int(venue.id),
        "demo_reference_year": getattr(venue, "demo_reference_year", None),
        "demo_reference_month": getattr(venue, "demo_reference_month", None),
        "redirect_url": build_demo_start_url(venue_id=int(venue.id), persona=persona_upper, next_path=payload.next_path),
        "banner": build_demo_banner_payload(),
    }
    resp = JSONResponse(body)
    _write_access_cookie(resp, user=demo_user, extra_claims=claims)
    try:
        record_demo_event(db, event_name="switch_persona", user=demo_user, venue_id=int(venue.id), persona=persona_upper, page_path=body.get("redirect_url"), session_id=claims.get("demo_session_id"), meta={"source": "auth_switch"})
        db.commit()
    except Exception:
        db.rollback()
    return resp


@router.post("/demo/exit")
def exit_demo_session(response: Response, db: Session = Depends(get_db), user: User | None = Depends(get_current_user_optional)):
    demo_ctx = get_demo_session_or_none(user)
    if demo_ctx is None:
        return {"ok": True, "demo_mode": False, "redirect_url": build_demo_banner_payload().get("return_url")}
    try:
        record_demo_event(db, event_name="exit_demo", user=user, session_id=getattr(demo_ctx, "session_id", None), meta={"source": "auth_exit"})
        db.commit()
    except Exception:
        db.rollback()
    _clear_access_cookie(response)
    return {"ok": True, "demo_mode": False, "redirect_url": build_demo_banner_payload().get("return_url")}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response):
    _clear_access_cookie(response)
    return


@router.post("/link/phone/request-call")
def request_link_phone_call(
    payload: PhoneCodeRequestIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_phone_call_enabled()
    phone_e164 = normalize_phone_e164(payload.phone)
    out = _request_call_challenge(db, phone_e164=phone_e164, request=request, purpose=OTP_PURPOSE_LINK_PHONE)
    out["link_mode"] = True
    out["user_id"] = user.id
    return out


@router.post("/link/phone/request-code")
def request_link_phone_code(
    payload: PhoneCodeRequestIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _ensure_phone_sms_enabled()
    phone_e164 = normalize_phone_e164(payload.phone)
    out = _request_sms_challenge(db, phone_e164=phone_e164, request=request, purpose=OTP_PURPOSE_LINK_PHONE)
    out["link_mode"] = True
    out["user_id"] = user.id
    return out


@router.post("/link/phone/verify-code", response_model=AuthStateOut)
def verify_link_phone_code(
    payload: PhoneCodeVerifyIn,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    phone_e164 = normalize_phone_e164(payload.phone)
    _resolve_verification(
        db,
        phone_e164=phone_e164,
        purpose=OTP_PURPOSE_LINK_PHONE,
        code=payload.code,
        challenge_id=payload.challenge_id,
    )
    existing_phone_user = find_user_by_phone(db, phone_e164=phone_e164)
    if existing_phone_user is not None and existing_phone_user.id != user.id:
        user = merge_user_accounts(db, target_user=user, source_user=existing_phone_user)

    link_phone_identity_to_user(db, user=user, phone_e164=phone_e164)
    if payload.new_password:
        set_password(user, payload.new_password)
    db.commit()
    db.refresh(user)
    accept_phone_invites_for_user(db, user_id=user.id, phone_e164=phone_e164)
    if payload.new_password:
        _write_access_cookie(response, user=user)
    return _auth_state(db, user=user)


@router.post("/link/telegram/browser/start", response_model=TelegramBrowserAuthStartOut)
def start_telegram_browser_link(
    payload: TelegramBrowserAuthStartIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bot_username = _telegram_browser_bot_username()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram browser login is not configured")

    session = TelegramBrowserAuthSession(
        public_token=_new_browser_login_token(),
        status="PENDING",
        next_path=_normalize_next_path(payload.next_path),
        user_id=user.id,
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        expires_at=_utcnow() + timedelta(seconds=_browser_login_ttl_seconds()),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return TelegramBrowserAuthStartOut(
        session_token=session.public_token,
        bot_username=bot_username,
        deep_link_url=f"https://t.me/{bot_username}?start={_browser_link_prefix()}{session.public_token}",
        expires_in_seconds=_browser_login_ttl_seconds(),
    )


@router.get("/link/telegram/browser/status/{session_token}", response_model=TelegramBrowserAuthStatusOut)
def telegram_browser_link_status(
    session_token: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = _get_browser_login_session(db, session_token=session_token)
    if int(session.user_id or 0) != int(user.id):
        raise HTTPException(status_code=404, detail="Сессия привязки Telegram не найдена")
    if _expire_browser_login_session(session):
        db.commit()
    else:
        db.flush()
    return _browser_login_status_payload(session)


@router.post("/link/telegram/browser/finalize", response_model=AuthStateOut)
def finalize_telegram_browser_link(
    payload: TelegramBrowserAuthFinalizeIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    session = _get_browser_login_session(db, session_token=payload.session_token)
    if int(session.user_id or 0) != int(user.id):
        raise HTTPException(status_code=404, detail="Сессия привязки Telegram не найдена")
    if _expire_browser_login_session(session):
        db.commit()
        raise HTTPException(status_code=410, detail="Сессия привязки Telegram истекла")
    if str(session.status or "PENDING").upper() not in {"COMPLETED", "FINALIZED"} or not session.tg_user_id:
        raise HTTPException(status_code=409, detail="Подтверждение в Telegram ещё не завершено")

    linked_user = db.execute(select(User).where(User.id == session.user_id)).scalar_one_or_none()
    if linked_user is None:
        raise HTTPException(status_code=404, detail="Пользователь для этой сессии не найден")

    session.status = "FINALIZED"
    if session.finalized_at is None:
        session.finalized_at = _utcnow()
    db.commit()
    db.refresh(linked_user)
    return _auth_state(db, user=linked_user)


@router.post("/link/telegram", response_model=AuthStateOut)
def link_telegram_account(
    payload: LinkTelegramIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        data = verify_init_data(payload.initData, settings.TG_BOT_TOKEN)
    except TelegramInitDataError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status_code=400, detail="user is missing in initData")

    try:
        tg_user = json.loads(user_raw)
        tg_user_id = int(tg_user["id"])
        tg_username = normalize_tg_username(tg_user.get("username"))
        first_name = (tg_user.get("first_name") or "").strip()
        last_name = (tg_user.get("last_name") or "").strip()
        default_full_name = " ".join([p for p in [last_name, first_name] if p]) or None
        default_short_name = first_name or (tg_username.lstrip("@") if tg_username else None)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user payload")

    existing_tg_user = db.execute(select(User).where(User.tg_user_id == tg_user_id)).scalar_one_or_none()
    if existing_tg_user is not None and existing_tg_user.id != user.id:
        user = merge_user_accounts(db, target_user=user, source_user=existing_tg_user)

    link_telegram_identity_to_user(
        db,
        user=user,
        tg_user_id=tg_user_id,
        tg_username=tg_username,
        default_full_name=default_full_name,
        default_short_name=default_short_name,
    )

    if tg_user_id in settings.super_admin_ids() and user.system_role != "SUPER_ADMIN":
        user.system_role = "SUPER_ADMIN"

    db.commit()
    db.refresh(user)
    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    return _auth_state(db, user=user)

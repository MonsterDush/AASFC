from __future__ import annotations

import json
import os
import secrets
import threading
import time
from datetime import datetime, timezone
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.account_merge import merge_user_accounts
from app.auth.deps import get_current_user
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
from app.models import User
from app.services.invites import accept_invites_for_user, accept_phone_invites_for_user
from app.services.sms_auth import get_sms_provider
from app.settings import settings

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


class TelegramBrowserStartOut(BaseModel):
    ok: bool = True
    token: str
    status: str = "pending"
    bot_username: str
    deep_link: str
    expires_at: str
    poll_interval_ms: int = 2000


class TelegramBrowserStatusOut(BaseModel):
    ok: bool = True
    token: str
    status: str
    expires_at: str
    approved_at: str | None = None
    consumed_at: str | None = None
    telegram_username: str | None = None
    telegram_display_name: str | None = None


class TelegramBrowserCompleteIn(BaseModel):
    token: str = Field(..., min_length=8, max_length=128)


class TelegramBrowserInternalApproveIn(BaseModel):
    token: str = Field(..., min_length=8, max_length=128)
    tg_user_id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None


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


def _write_access_cookie(response: Response, *, user: User) -> None:
    token = create_access_token(_jwt_config(), user.id, session_version=int(user.session_version or 0))
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


_BROWSER_TG_LOGIN_TTL_SECONDS = 60 * 10
_BROWSER_TG_POLL_INTERVAL_MS = 2000
_BROWSER_TG_SESSION_PREFIX = "axelio_login_"
_BROWSER_TG_SESSION_LOCK = threading.Lock()
_BROWSER_TG_SESSIONS: dict[str, dict] = {}
_BROWSER_TG_BOT_USERNAME_CACHE: dict[str, object] = {"value": None, "checked_at": 0.0}


def _utc_iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()


def _cleanup_browser_tg_sessions(now_ts: float | None = None) -> None:
    now = float(now_ts or time.time())
    stale_before = now - (_BROWSER_TG_LOGIN_TTL_SECONDS * 2)
    with _BROWSER_TG_SESSION_LOCK:
        for token, row in list(_BROWSER_TG_SESSIONS.items()):
            expires_at = float(row.get("expires_at") or 0.0)
            consumed_at = row.get("consumed_at")
            created_at = float(row.get("created_at") or 0.0)
            if expires_at and now > expires_at:
                row["status"] = "expired"
            if consumed_at and float(consumed_at) < stale_before:
                _BROWSER_TG_SESSIONS.pop(token, None)
                continue
            if not consumed_at and created_at and created_at < stale_before:
                _BROWSER_TG_SESSIONS.pop(token, None)


def _get_browser_login_bot_username() -> str:
    cached_value = str(_BROWSER_TG_BOT_USERNAME_CACHE.get("value") or "").strip()
    checked_at = float(_BROWSER_TG_BOT_USERNAME_CACHE.get("checked_at") or 0.0)
    now = time.time()
    if cached_value and (now - checked_at) < 300:
        return cached_value

    if not settings.TG_BOT_TOKEN:
        return ""

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{settings.TG_BOT_TOKEN}/getMe",
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="ignore") or "{}")
        username = str(((payload.get("result") or {}).get("username")) or "").strip()
        _BROWSER_TG_BOT_USERNAME_CACHE["value"] = username
        _BROWSER_TG_BOT_USERNAME_CACHE["checked_at"] = now
        return username
    except Exception:
        fallback = str(settings.TG_LOGIN_WIDGET_BOT_USERNAME or "").strip()
        if fallback:
            _BROWSER_TG_BOT_USERNAME_CACHE["value"] = fallback
            _BROWSER_TG_BOT_USERNAME_CACHE["checked_at"] = now
            return fallback
        return ""


def _create_browser_tg_session() -> dict:
    _cleanup_browser_tg_sessions()
    token = secrets.token_urlsafe(24)
    now = time.time()
    row = {
        "token": token,
        "status": "pending",
        "created_at": now,
        "expires_at": now + _BROWSER_TG_LOGIN_TTL_SECONDS,
        "approved_at": None,
        "consumed_at": None,
        "tg_user_id": None,
        "tg_username": None,
        "first_name": None,
        "last_name": None,
    }
    with _BROWSER_TG_SESSION_LOCK:
        _BROWSER_TG_SESSIONS[token] = row
    return dict(row)


def _get_browser_tg_session(token: str) -> dict | None:
    normalized = str(token or "").strip()
    if not normalized:
        return None
    _cleanup_browser_tg_sessions()
    with _BROWSER_TG_SESSION_LOCK:
        row = _BROWSER_TG_SESSIONS.get(normalized)
        if not row:
            return None
        if float(row.get("expires_at") or 0.0) < time.time() and row.get("status") == "pending":
            row["status"] = "expired"
        return dict(row)


def _browser_tg_public_payload(row: dict) -> TelegramBrowserStatusOut:
    first_name = str(row.get("first_name") or "").strip()
    last_name = str(row.get("last_name") or "").strip()
    tg_username = normalize_tg_username(row.get("tg_username"))
    display_name = " ".join([part for part in [first_name, last_name] if part]).strip() or (tg_username.lstrip("@") if tg_username else None)
    return TelegramBrowserStatusOut(
        token=str(row.get("token") or ""),
        status=str(row.get("status") or "pending"),
        expires_at=str(_utc_iso(row.get("expires_at")) or ""),
        approved_at=_utc_iso(row.get("approved_at")),
        consumed_at=_utc_iso(row.get("consumed_at")),
        telegram_username=tg_username,
        telegram_display_name=display_name,
    )


def _bot_service_secret() -> str:
    return str(os.getenv("BOT_SERVICE_SECRET") or "").strip()


def _assert_internal_bot_secret(request: Request) -> None:
    expected = _bot_service_secret()
    if not expected:
        return
    got = request.headers.get("X-Bot-Secret", "")
    if got != expected:
        raise HTTPException(status_code=401, detail="bad secret")


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


@router.post("/telegram/browser/start", response_model=TelegramBrowserStartOut)
def start_telegram_browser_auth():
    bot_username = _get_browser_login_bot_username()
    if not bot_username:
        raise HTTPException(status_code=503, detail="Telegram browser login is not configured")

    session_row = _create_browser_tg_session()
    token = str(session_row["token"])
    return TelegramBrowserStartOut(
        token=token,
        bot_username=bot_username,
        deep_link=f"https://t.me/{bot_username}?start={_BROWSER_TG_SESSION_PREFIX}{token}",
        expires_at=str(_utc_iso(session_row.get("expires_at")) or ""),
        poll_interval_ms=_BROWSER_TG_POLL_INTERVAL_MS,
    )


@router.get("/telegram/browser/status/{token}", response_model=TelegramBrowserStatusOut)
def telegram_browser_auth_status(token: str):
    row = _get_browser_tg_session(token)
    if row is None:
        raise HTTPException(status_code=404, detail="Сессия входа не найдена")
    return _browser_tg_public_payload(row)


@router.post("/telegram/browser/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_telegram_browser_auth(payload: TelegramBrowserCompleteIn, response: Response, db: Session = Depends(get_db)):
    row = _get_browser_tg_session(payload.token)
    if row is None:
        raise HTTPException(status_code=404, detail="Сессия входа не найдена")
    if row.get("status") == "expired":
        raise HTTPException(status_code=410, detail="Сессия входа истекла")
    if row.get("status") not in {"approved", "consumed"}:
        raise HTTPException(status_code=409, detail="Вход через Telegram ещё не подтверждён")

    tg_user_id = row.get("tg_user_id")
    if not tg_user_id:
        raise HTTPException(status_code=409, detail="Не удалось получить данные Telegram-пользователя")

    user = _upsert_user_from_telegram_payload(
        db,
        tg_user_id=int(tg_user_id),
        tg_username=normalize_tg_username(row.get("tg_username")),
        first_name=str(row.get("first_name") or "").strip() or None,
        last_name=str(row.get("last_name") or "").strip() or None,
    )
    db.commit()
    db.refresh(user)

    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    _write_access_cookie(response, user=user)

    with _BROWSER_TG_SESSION_LOCK:
        session_ref = _BROWSER_TG_SESSIONS.get(payload.token)
        if session_ref is not None:
            session_ref["status"] = "consumed"
            session_ref["consumed_at"] = time.time()
    return


@router.get("/telegram/browser/internal/session/{token}")
def telegram_browser_internal_session(token: str, request: Request):
    _assert_internal_bot_secret(request)
    row = _get_browser_tg_session(token)
    if row is None:
        raise HTTPException(status_code=404, detail="browser auth session not found")
    payload = _browser_tg_public_payload(row).model_dump()
    payload["tg_user_id"] = row.get("tg_user_id")
    return payload


@router.post("/telegram/browser/internal/approve")
def telegram_browser_internal_approve(payload: TelegramBrowserInternalApproveIn, request: Request):
    _assert_internal_bot_secret(request)
    normalized_token = str(payload.token or "").strip()
    if not normalized_token:
        raise HTTPException(status_code=400, detail="token is required")

    now = time.time()
    with _BROWSER_TG_SESSION_LOCK:
        row = _BROWSER_TG_SESSIONS.get(normalized_token)
        if row is None:
            raise HTTPException(status_code=404, detail="browser auth session not found")
        if float(row.get("expires_at") or 0.0) < now:
            row["status"] = "expired"
            raise HTTPException(status_code=410, detail="browser auth session expired")
        if row.get("status") == "consumed":
            return {"ok": True, "status": "consumed"}
        row["status"] = "approved"
        row["approved_at"] = now
        row["tg_user_id"] = int(payload.tg_user_id)
        row["tg_username"] = normalize_tg_username(payload.username)
        row["first_name"] = str(payload.first_name or "").strip() or None
        row["last_name"] = str(payload.last_name or "").strip() or None
    return {"ok": True, "status": "approved"}


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

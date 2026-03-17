from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.jwt_tokens import JwtConfig, create_access_token
from app.auth.passwords import has_password, set_password, validate_new_password, verify_password
from app.auth.phone_auth import (
    OTP_PURPOSE_LINK_PHONE,
    OTP_PURPOSE_PHONE_LOGIN,
    OTP_PURPOSE_RESET_PASSWORD,
    build_challenge,
    find_or_create_user_by_phone,
    find_user_by_phone,
    get_user_auth_methods,
    get_user_phone,
    link_phone_identity_to_user,
    link_telegram_identity_to_user,
    normalize_phone_e164,
    upsert_telegram_identity,
    verify_challenge,
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
    code: str = Field(..., min_length=4, max_length=8)
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class PasswordLoginIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)


class PasswordResetConfirmIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    code: str = Field(..., min_length=4, max_length=8)
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


class PasswordStateOut(BaseModel):
    ok: bool = True
    user_id: int
    has_password: bool
    password_set_at: str | None = None
    password_changed_at: str | None = None



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


@router.post("/phone/request-code")
def request_phone_code(payload: PhoneCodeRequestIn, request: Request, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    challenge, code = build_challenge(
        db,
        phone_e164=phone_e164,
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        purpose=OTP_PURPOSE_PHONE_LOGIN,
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
        "expires_in_seconds": int(settings.PHONE_AUTH_CODE_TTL_SECONDS or 300),
        "cooldown_seconds": int(settings.PHONE_AUTH_RESEND_COOLDOWN_SECONDS or 60),
        "challenge_id": challenge.id,
        "purpose": OTP_PURPOSE_PHONE_LOGIN,
    }
    if send_result.get("sms_id"):
        out["sms_id"] = send_result.get("sms_id")
    if send_result.get("test"):
        out["test"] = True
    if "debug_code" in send_result:
        out["debug_code"] = send_result["debug_code"]
    return out


@router.post("/phone/verify-code", response_model=AuthStateOut)
def verify_phone_code(payload: PhoneCodeVerifyIn, response: Response, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    verify_challenge(db, phone_e164=phone_e164, code=payload.code, purpose=OTP_PURPOSE_PHONE_LOGIN)
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
    verify_challenge(db, phone_e164=phone_e164, code=payload.code, purpose=OTP_PURPOSE_PHONE_LOGIN)
    user = find_or_create_user_by_phone(db, phone_e164=phone_e164)
    set_password(user, payload.new_password)
    db.commit()
    db.refresh(user)

    accept_phone_invites_for_user(db, user_id=user.id, phone_e164=phone_e164)
    _write_access_cookie(response, user=user)
    return _auth_state(db, user=user)


@router.post("/password/reset/request-code")
def request_password_reset_code(payload: PhoneCodeRequestIn, request: Request, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    user = find_user_by_phone(db, phone_e164=phone_e164)
    if user is None or not has_password(user):
        raise HTTPException(status_code=404, detail="Для этого номера пароль ещё не настроен")

    challenge, code = build_challenge(
        db,
        phone_e164=phone_e164,
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        purpose=OTP_PURPOSE_RESET_PASSWORD,
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
        "expires_in_seconds": int(settings.PHONE_AUTH_CODE_TTL_SECONDS or 300),
        "cooldown_seconds": int(settings.PHONE_AUTH_RESEND_COOLDOWN_SECONDS or 60),
        "challenge_id": challenge.id,
        "purpose": OTP_PURPOSE_RESET_PASSWORD,
    }
    if send_result.get("sms_id"):
        out["sms_id"] = send_result.get("sms_id")
    if send_result.get("test"):
        out["test"] = True
    if "debug_code" in send_result:
        out["debug_code"] = send_result["debug_code"]
    return out


@router.post("/password/reset/confirm", response_model=AuthStateOut)
def confirm_password_reset(payload: PasswordResetConfirmIn, response: Response, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    verify_challenge(db, phone_e164=phone_e164, code=payload.code, purpose=OTP_PURPOSE_RESET_PASSWORD)
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


@router.post("/link/phone/request-code")
def request_link_phone_code(
    payload: PhoneCodeRequestIn,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    phone_e164 = normalize_phone_e164(payload.phone)
    challenge, code = build_challenge(
        db,
        phone_e164=phone_e164,
        request_ip=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        purpose=OTP_PURPOSE_LINK_PHONE,
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
        "link_mode": True,
        "user_id": user.id,
        "phone": phone_e164,
        "provider": send_result.provider,
        "expires_in_seconds": int(settings.PHONE_AUTH_CODE_TTL_SECONDS or 300),
        "cooldown_seconds": int(settings.PHONE_AUTH_RESEND_COOLDOWN_SECONDS or 60),
        "challenge_id": challenge.id,
        "purpose": OTP_PURPOSE_LINK_PHONE,
    }
    if send_result.get("sms_id"):
        out["sms_id"] = send_result.get("sms_id")
    if send_result.get("test"):
        out["test"] = True
    if "debug_code" in send_result:
        out["debug_code"] = send_result["debug_code"]
    return out


@router.post("/link/phone/verify-code", response_model=AuthStateOut)
def verify_link_phone_code(
    payload: PhoneCodeVerifyIn,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    phone_e164 = normalize_phone_e164(payload.phone)
    verify_challenge(db, phone_e164=phone_e164, code=payload.code, purpose=OTP_PURPOSE_LINK_PHONE)
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

from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.auth.jwt_tokens import JwtConfig, create_access_token
from app.auth.phone_auth import (
    find_or_create_user_by_phone,
    get_user_auth_methods,
    get_user_phone,
    normalize_phone_e164,
    build_challenge,
    upsert_telegram_identity,
    link_phone_identity_to_user,
    link_telegram_identity_to_user,
    verify_challenge,
)
from app.auth.telegram_webapp import TelegramInitDataError, verify_init_data
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


class PhoneCodeRequestIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)


class PhoneCodeVerifyIn(BaseModel):
    phone: str = Field(..., min_length=5, max_length=32)
    code: str = Field(..., min_length=4, max_length=8)


class AuthStateOut(BaseModel):
    ok: bool = True
    user_id: int
    auth_methods: list[str] = []
    phone: str | None = None


class LinkTelegramIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    initData: str = Field(alias="init_data")


def _jwt_config() -> JwtConfig:
    return JwtConfig(
        secret=settings.JWT_SECRET,
        issuer=settings.JWT_ISS,
        audience=settings.JWT_AUD,
        ttl_seconds=settings.ACCESS_TOKEN_TTL_SECONDS,
    )


def _write_access_cookie(response: Response, *, user_id: int) -> None:
    token = create_access_token(_jwt_config(), user_id)
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
        default_full_name = " ".join([p for p in [last_name, first_name] if p]) or None
        default_short_name = first_name or (tg_username.lstrip("@") if tg_username else None)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user payload")

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
    db.commit()
    db.refresh(user)

    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)
    _write_access_cookie(response, user_id=user.id)
    return


@router.post("/phone/request-code")
def request_phone_code(payload: PhoneCodeRequestIn, request: Request, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    challenge, code = build_challenge(
        db,
        phone_e164=phone_e164,
        request_ip=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    provider = get_sms_provider()
    send_result = provider.send_code(
        phone_e164=phone_e164,
        code=code,
        request_ip=(request.client.host if request.client else None),
    )
    db.commit()

    out = {
        "ok": True,
        "phone": phone_e164,
        "provider": send_result.provider,
        "expires_in_seconds": int(settings.PHONE_AUTH_CODE_TTL_SECONDS or 300),
        "cooldown_seconds": int(settings.PHONE_AUTH_RESEND_COOLDOWN_SECONDS or 30),
        "challenge_id": challenge.id,
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
    verify_challenge(db, phone_e164=phone_e164, code=payload.code)
    user = find_or_create_user_by_phone(db, phone_e164=phone_e164)
    db.commit()
    db.refresh(user)

    accept_phone_invites_for_user(db, user_id=user.id, phone_e164=phone_e164)
    _write_access_cookie(response, user_id=user.id)
    return AuthStateOut(
        user_id=user.id,
        auth_methods=get_user_auth_methods(db, user_id=user.id),
        phone=get_user_phone(db, user_id=user.id),
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
        request_ip=(request.client.host if request.client else None),
        user_agent=request.headers.get("user-agent"),
    )
    provider = get_sms_provider()
    send_result = provider.send_code(
        phone_e164=phone_e164,
        code=code,
        request_ip=(request.client.host if request.client else None),
    )
    db.commit()

    out = {
        "ok": True,
        "link_mode": True,
        "user_id": user.id,
        "phone": phone_e164,
        "provider": send_result.provider,
        "expires_in_seconds": int(settings.PHONE_AUTH_CODE_TTL_SECONDS or 300),
        "cooldown_seconds": int(settings.PHONE_AUTH_RESEND_COOLDOWN_SECONDS or 30),
        "challenge_id": challenge.id,
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    phone_e164 = normalize_phone_e164(payload.phone)
    verify_challenge(db, phone_e164=phone_e164, code=payload.code)
    link_phone_identity_to_user(db, user=user, phone_e164=phone_e164)
    db.commit()
    db.refresh(user)
    accept_phone_invites_for_user(db, user_id=user.id, phone_e164=phone_e164)
    return AuthStateOut(
        user_id=user.id,
        auth_methods=get_user_auth_methods(db, user_id=user.id),
        phone=get_user_phone(db, user_id=user.id),
    )


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
    return AuthStateOut(
        user_id=user.id,
        auth_methods=get_user_auth_methods(db, user_id=user.id),
        phone=get_user_phone(db, user_id=user.id),
    )

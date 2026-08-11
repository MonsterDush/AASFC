from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from app.auth.account_merge import merge_user_accounts
from app.auth.deps import get_current_user
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
    link_phone_identity_to_user,
    mark_challenge_verified,
    normalize_phone_e164,
    resolve_verified_challenge,
)
from app.core.db import get_db
from app.core.request_ip import resolve_client_ip
from app.models import User
from app.services.invites import accept_phone_invites_for_user
from app.services.security_rate_limits import (
    RateLimitDecision,
    RateLimitPolicy,
    check_rate_limit,
    register_rate_limit_failure,
    reset_rate_limit,
)
from app.services.sms_auth import get_sms_provider
from app.settings import settings

from .auth_common import _auth_state, _client_ip, _write_access_cookie
from .auth_schemas import (
    AuthStateOut,
    PasswordChangeIn,
    PasswordLoginIn,
    PasswordResetConfirmIn,
    PasswordStateOut,
    PhoneCallStatusOut,
    PhoneCodeRequestIn,
    PhoneCodeVerifyIn,
)


router = APIRouter()
link_router = APIRouter()

_PASSWORD_LOGIN_ACCOUNT_SCOPE = "password-login-account"
_PASSWORD_LOGIN_IP_SCOPE = "password-login-ip"


def _password_login_policies() -> tuple[RateLimitPolicy, RateLimitPolicy]:
    window_seconds = int(settings.PASSWORD_LOGIN_RATE_WINDOW_SECONDS or 900)
    block_seconds = int(settings.PASSWORD_LOGIN_BLOCK_SECONDS or 900)
    return (
        RateLimitPolicy(
            limit=int(settings.PASSWORD_LOGIN_ACCOUNT_LIMIT or 5),
            window_seconds=window_seconds,
            block_seconds=block_seconds,
        ),
        RateLimitPolicy(
            limit=int(settings.PASSWORD_LOGIN_IP_LIMIT or 20),
            window_seconds=window_seconds,
            block_seconds=block_seconds,
        ),
    )


def _raise_login_rate_limit(decisions: list[RateLimitDecision]) -> None:
    blocked = [decision for decision in decisions if not decision.allowed]
    if not blocked:
        return
    retry_after = max(decision.retry_after_seconds for decision in blocked)
    raise HTTPException(
        status_code=429,
        detail="Слишком много попыток входа. Попробуйте позже.",
        headers={"Retry-After": str(max(1, retry_after))},
    )


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
def password_login(payload: PasswordLoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    phone_e164 = normalize_phone_e164(payload.phone)
    client_ip = resolve_client_ip(request)
    account_policy, ip_policy = _password_login_policies()
    _raise_login_rate_limit(
        [
            check_rate_limit(
                db,
                scope=_PASSWORD_LOGIN_ACCOUNT_SCOPE,
                subject=phone_e164,
                policy=account_policy,
            ),
            check_rate_limit(
                db,
                scope=_PASSWORD_LOGIN_IP_SCOPE,
                subject=client_ip,
                policy=ip_policy,
            ),
        ]
    )

    user = find_user_by_phone(db, phone_e164=phone_e164)
    if user is None or not verify_password(payload.password, user.password_hash):
        decisions = [
            register_rate_limit_failure(
                db,
                scope=_PASSWORD_LOGIN_ACCOUNT_SCOPE,
                subject=phone_e164,
                policy=account_policy,
            ),
            register_rate_limit_failure(
                db,
                scope=_PASSWORD_LOGIN_IP_SCOPE,
                subject=client_ip,
                policy=ip_policy,
            ),
        ]
        db.commit()
        _raise_login_rate_limit(decisions)
        raise HTTPException(status_code=401, detail="Неверный номер или пароль")

    reset_rate_limit(db, scope=_PASSWORD_LOGIN_ACCOUNT_SCOPE, subject=phone_e164)
    db.commit()
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

@link_router.post("/link/phone/request-call")
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


@link_router.post("/link/phone/request-code")
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


@link_router.post("/link/phone/verify-code", response_model=AuthStateOut)
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

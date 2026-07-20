from __future__ import annotations

from fastapi import APIRouter

from .auth_common import (
    _auth_state,
    _clear_access_cookie,
    _client_ip,
    _jwt_config,
    _normalize_next_path,
    _phone_link_profile_url,
    _phone_link_reminder_text,
    _send_phone_link_reminder_if_due,
    _upsert_user_from_telegram_payload,
    _utcnow,
    _write_access_cookie,
)
from .auth_demo import (
    _build_demo_session_payload,
    _resolve_demo_identity_or_404,
    exit_demo_session,
    logout,
    router as demo_router,
    start_demo_session,
    switch_demo_persona,
)
from .auth_phone import (
    _challenge_to_status_out,
    _ensure_phone_call_enabled,
    _ensure_phone_sms_enabled,
    _phone_auth_config_payload,
    _request_call_challenge,
    _request_sms_challenge,
    _resolve_verification,
    change_password,
    confirm_password_reset,
    link_router as phone_link_router,
    password_login,
    password_state,
    phone_auth_config,
    phone_call_status,
    request_link_phone_call,
    request_link_phone_code,
    request_password_reset_call,
    request_password_reset_code,
    request_phone_call,
    request_phone_code,
    router as phone_router,
    set_password_after_phone_verify,
    verify_link_phone_code,
    verify_phone_code,
)
from .auth_schemas import (
    AuthStateOut,
    DemoSwitchPersonaIn,
    LinkTelegramIn,
    PasswordChangeIn,
    PasswordLoginIn,
    PasswordResetConfirmIn,
    PasswordStateOut,
    PhoneCallStatusOut,
    PhoneCodeRequestIn,
    PhoneCodeVerifyIn,
    TelegramAuthIn,
    TelegramBrowserAuthFinalizeIn,
    TelegramBrowserAuthStartIn,
    TelegramBrowserAuthStartOut,
    TelegramBrowserAuthStatusOut,
    TelegramMiniAppLinkOut,
    TelegramWidgetAuthIn,
)
from .auth_telegram import (
    _browser_link_prefix,
    _browser_login_prefix,
    _browser_login_status_payload,
    _browser_login_ttl_seconds,
    _complete_browser_link_session,
    _complete_browser_login_session,
    _expire_browser_login_session,
    _get_browser_login_session,
    _handle_browser_login_callback,
    _handle_browser_login_start_message,
    _new_browser_login_token,
    _telegram_browser_bot_username,
    _telegram_mini_app_url,
    _telegram_user_from_update,
    auth_telegram,
    auth_telegram_widget,
    finalize_telegram_browser_auth,
    finalize_telegram_browser_link,
    link_router as telegram_link_router,
    link_telegram_account,
    process_telegram_browser_webhook_request,
    router as telegram_router,
    start_telegram_browser_auth,
    start_telegram_browser_link,
    telegram_browser_auth_status,
    telegram_browser_link_status,
    telegram_browser_webhook,
    telegram_miniapp_link,
    telegram_widget_config,
)


router = APIRouter(prefix="/auth", tags=["auth"])
router.include_router(telegram_router)
router.include_router(phone_router)
router.include_router(demo_router)
router.include_router(phone_link_router)
router.include_router(telegram_link_router)

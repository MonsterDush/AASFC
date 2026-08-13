from __future__ import annotations

from fastapi import APIRouter

# Redundant aliases intentionally declare this compatibility facade's public
# re-exports while keeping Ruff F401 enabled repository-wide.
from .auth_common import (
    _auth_state as _auth_state,
    _clear_access_cookie as _clear_access_cookie,
    _client_ip as _client_ip,
    _jwt_config as _jwt_config,
    _normalize_next_path as _normalize_next_path,
    _phone_link_profile_url as _phone_link_profile_url,
    _phone_link_reminder_text as _phone_link_reminder_text,
    _send_phone_link_reminder_if_due as _send_phone_link_reminder_if_due,
    _upsert_user_from_telegram_payload as _upsert_user_from_telegram_payload,
    _utcnow as _utcnow,
    _write_access_cookie as _write_access_cookie,
)
from .auth_demo import (
    _build_demo_session_payload as _build_demo_session_payload,
    _resolve_demo_identity_or_404 as _resolve_demo_identity_or_404,
    exit_demo_session as exit_demo_session,
    logout as logout,
    router as demo_router,
    start_demo_session as start_demo_session,
    switch_demo_persona as switch_demo_persona,
)
from .auth_phone import (
    _challenge_to_status_out as _challenge_to_status_out,
    _ensure_phone_call_enabled as _ensure_phone_call_enabled,
    _ensure_phone_sms_enabled as _ensure_phone_sms_enabled,
    _phone_auth_config_payload as _phone_auth_config_payload,
    _request_call_challenge as _request_call_challenge,
    _request_sms_challenge as _request_sms_challenge,
    _resolve_verification as _resolve_verification,
    change_password as change_password,
    confirm_password_reset as confirm_password_reset,
    link_router as phone_link_router,
    password_login as password_login,
    password_state as password_state,
    phone_auth_config as phone_auth_config,
    phone_call_status as phone_call_status,
    request_link_phone_call as request_link_phone_call,
    request_link_phone_code as request_link_phone_code,
    request_password_reset_call as request_password_reset_call,
    request_password_reset_code as request_password_reset_code,
    request_phone_call as request_phone_call,
    request_phone_code as request_phone_code,
    router as phone_router,
    set_password_after_phone_verify as set_password_after_phone_verify,
    verify_link_phone_code as verify_link_phone_code,
    verify_phone_code as verify_phone_code,
)
from .auth_schemas import (
    AuthStateOut as AuthStateOut,
    DemoSwitchPersonaIn as DemoSwitchPersonaIn,
    LinkTelegramIn as LinkTelegramIn,
    PasswordChangeIn as PasswordChangeIn,
    PasswordLoginIn as PasswordLoginIn,
    PasswordResetConfirmIn as PasswordResetConfirmIn,
    PasswordStateOut as PasswordStateOut,
    PhoneCallStatusOut as PhoneCallStatusOut,
    PhoneCodeRequestIn as PhoneCodeRequestIn,
    PhoneCodeVerifyIn as PhoneCodeVerifyIn,
    TelegramAuthIn as TelegramAuthIn,
    TelegramBrowserAuthFinalizeIn as TelegramBrowserAuthFinalizeIn,
    TelegramBrowserAuthStartIn as TelegramBrowserAuthStartIn,
    TelegramBrowserAuthStartOut as TelegramBrowserAuthStartOut,
    TelegramBrowserAuthStatusOut as TelegramBrowserAuthStatusOut,
    TelegramMiniAppLinkOut as TelegramMiniAppLinkOut,
    TelegramWidgetAuthIn as TelegramWidgetAuthIn,
)
from .auth_telegram import (
    _browser_link_prefix as _browser_link_prefix,
    _browser_login_prefix as _browser_login_prefix,
    _browser_login_status_payload as _browser_login_status_payload,
    _browser_login_ttl_seconds as _browser_login_ttl_seconds,
    _complete_browser_link_session as _complete_browser_link_session,
    _complete_browser_login_session as _complete_browser_login_session,
    _expire_browser_login_session as _expire_browser_login_session,
    _get_browser_login_session as _get_browser_login_session,
    _handle_browser_login_callback as _handle_browser_login_callback,
    _handle_browser_login_start_message as _handle_browser_login_start_message,
    _new_browser_login_token as _new_browser_login_token,
    _telegram_browser_bot_username as _telegram_browser_bot_username,
    _telegram_mini_app_url as _telegram_mini_app_url,
    _telegram_user_from_update as _telegram_user_from_update,
    auth_telegram as auth_telegram,
    auth_telegram_widget as auth_telegram_widget,
    finalize_telegram_browser_auth as finalize_telegram_browser_auth,
    finalize_telegram_browser_link as finalize_telegram_browser_link,
    link_router as telegram_link_router,
    link_telegram_account as link_telegram_account,
    process_telegram_browser_webhook_request as process_telegram_browser_webhook_request,
    router as telegram_router,
    start_telegram_browser_auth as start_telegram_browser_auth,
    start_telegram_browser_link as start_telegram_browser_link,
    telegram_browser_auth_status as telegram_browser_auth_status,
    telegram_browser_link_status as telegram_browser_link_status,
    telegram_browser_webhook as telegram_browser_webhook,
    telegram_miniapp_link as telegram_miniapp_link,
    telegram_widget_config as telegram_widget_config,
)


router = APIRouter(prefix="/auth", tags=["auth"])
router.include_router(telegram_router)
router.include_router(phone_router)
router.include_router(demo_router)
router.include_router(phone_link_router)
router.include_router(telegram_link_router)

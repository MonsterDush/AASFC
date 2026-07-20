from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.services.demo.session import DEMO_PERSONA_OWNER


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


class TelegramMiniAppLinkOut(BaseModel):
    ok: bool = True
    enabled: bool = True
    bot_username: str
    mini_app_url: str


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

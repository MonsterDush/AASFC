from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Set

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str

    # Telegram WebApp auth
    TG_BOT_TOKEN: str

    # JWT (cookie-based auth)
    JWT_SECRET: str
    JWT_ISS: str = "axelio-api-dev"
    JWT_AUD: str = "axelio-miniapp"

    # Public export links (signed)
    EXPORT_LINK_SECRET: str = ""  # if empty, JWT_SECRET is used
    EXPORT_LINK_TTL_SECONDS: int = 60 * 10  # 10 minutes


    # Cookie
    COOKIE_DOMAIN: str = ".axelio.ru"
    COOKIE_SECURE: bool = True
    ACCESS_TOKEN_TTL_SECONDS: int = 60 * 60 * 24 * 7  # 7 days


SUPER_ADMIN_TG_USER_IDS: str = ""

# Phone auth / OTP
PHONE_AUTH_PROVIDER: str = "debug"
PHONE_AUTH_DEBUG_REVEAL_CODE: bool = True
PHONE_AUTH_DEFAULT_COUNTRY_CODE: str = "7"
PHONE_AUTH_CODE_LENGTH: int = 6
PHONE_AUTH_CODE_TTL_SECONDS: int = 60 * 5
PHONE_AUTH_RESEND_COOLDOWN_SECONDS: int = 30
PHONE_AUTH_MAX_ATTEMPTS: int = 5

    def super_admin_ids(self) -> set[int]:
        raw = (self.SUPER_ADMIN_TG_USER_IDS or "").strip()
        if not raw:
            return set()
        return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}

settings = Settings()

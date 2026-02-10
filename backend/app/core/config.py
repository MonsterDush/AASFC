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

    # Cookie
    COOKIE_DOMAIN: str = ".axelio.ru"
    COOKIE_SECURE: bool = True
    ACCESS_TOKEN_TTL_SECONDS: int = 60 * 60 * 24 * 7  # 7 days

    SUPER_ADMIN_TG_USER_IDS: str = ""

    def super_admin_ids(self) -> set[int]:
        raw = (self.SUPER_ADMIN_TG_USER_IDS or "").strip()
        if not raw:
            return set()
        return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}

settings = Settings()

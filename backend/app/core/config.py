from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Roles
    SUPER_ADMIN_TG_USER_IDS: str = ""

    # Phone auth / OTP
    PHONE_AUTH_PROVIDER: str = "debug"  # debug | console | sms_ru
    PHONE_AUTH_DEBUG_REVEAL_CODE: bool = True
    PHONE_AUTH_DEFAULT_COUNTRY_CODE: str = "7"
    PHONE_AUTH_REQUIRE_RU_NUMBERS: bool = False
    PHONE_AUTH_CODE_LENGTH: int = 6
    PHONE_AUTH_CODE_TTL_SECONDS: int = 60 * 5
    PHONE_AUTH_RESEND_COOLDOWN_SECONDS: int = 30
    PHONE_AUTH_MAX_ATTEMPTS: int = 5
    PHONE_AUTH_MAX_SENDS_PER_DAY: int = 10
    PHONE_AUTH_SMS_TEMPLATE: str = "Ваш код: {code}"

    # SMS.ru
    SMS_RU_API_ID: str = ""
    SMS_RU_API_URL: str = "https://sms.ru/sms/send"
    SMS_RU_TEST: bool = False
    SMS_RU_TIMEOUT_SECONDS: int = 10
    SMS_RU_FROM: str = ""

    def super_admin_ids(self) -> set[int]:
        raw = (self.SUPER_ADMIN_TG_USER_IDS or "").strip()
        if not raw:
            return set()
        return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}


settings = Settings()

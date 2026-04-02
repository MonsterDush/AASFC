from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str

    # Telegram WebApp auth
    TG_BOT_TOKEN: str

    TG_LOGIN_WIDGET_BOT_USERNAME: str = ""
    TG_LOGIN_WIDGET_MAX_AGE_SECONDS: int = 60 * 60
    TG_BROWSER_LOGIN_BOT_USERNAME: str = ""
    TG_BROWSER_LOGIN_SESSION_TTL_SECONDS: int = 60 * 10
    TG_WEBHOOK_SECRET_TOKEN: str = ""

    # Public landing leads
    PUBLIC_LEAD_SITE_KEY: str = ""

    # JWT (cookie-based auth)
    JWT_SECRET: str
    JWT_ISS: str = "axelio-api-dev"
    JWT_AUD: str = "axelio-miniapp"

    # Public export links (signed)
    EXPORT_LINK_SECRET: str = ""  # if empty, JWT_SECRET is used
    EXPORT_LINK_TTL_SECONDS: int = 60 * 10  # 10 minutes

    # Cookie
    COOKIE_DOMAIN: str = ".axelio.ru"

    # Public app/base URLs
    FRONTEND_BASE_URL: str = ""
    APP_BASE_URL: str = ""
    API_BASE_URL: str = ""
    CORS_ALLOW_ORIGINS: str = ""

    # Robokassa
    ROBOKASSA_MERCHANT_LOGIN: str = ""
    ROBOKASSA_PASSWORD1: str = ""
    ROBOKASSA_PASSWORD2: str = ""
    ROBOKASSA_TEST_PASSWORD1: str = ""
    ROBOKASSA_TEST_PASSWORD2: str = ""
    ROBOKASSA_TEST_MODE: bool = False
    ROBOKASSA_HASH_ALGORITHM: str = "MD5"
    ROBOKASSA_PAYMENT_URL: str = "https://auth.robokassa.ru/Merchant/Index.aspx"
    ROBOKASSA_CHECKOUT_TTL_MINUTES: int = 60
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
    PHONE_AUTH_RESEND_COOLDOWN_SECONDS: int = 60
    PHONE_AUTH_MAX_ATTEMPTS: int = 5
    PHONE_AUTH_MAX_SENDS_PER_DAY: int = 10
    PHONE_AUTH_BURST_WINDOW_SECONDS: int = 60 * 10
    PHONE_AUTH_MAX_SENDS_PER_WINDOW: int = 5
    PHONE_AUTH_BLOCK_SECONDS: int = 60 * 30
    PHONE_AUTH_CALL_FALLBACK_AFTER_SECONDS: int = 10
    PHONE_AUTH_CALL_ENABLED: bool = True
    PHONE_AUTH_SMS_ENABLED: bool = True
    PHONE_AUTH_SMS_TEMPLATE: str = "Ваш код: {code}"

    # Пароли
    PASSWORD_MIN_LENGTH: int = 8
    PASSWORD_PBKDF2_ITERATIONS: int = 260_000

    # SMS.ru
    SMS_RU_API_ID: str = ""
    SMS_RU_API_URL: str = "https://sms.ru/sms/send"
    SMS_RU_TEST: bool = False
    SMS_RU_TIMEOUT_SECONDS: int = 10
    SMS_RU_FROM: str = ""
    SMS_RU_CALL_ADD_URL: str = "https://sms.ru/callcheck/add"
    SMS_RU_CALL_STATUS_URL: str = "https://sms.ru/callcheck/status"

    def frontend_base_url(self) -> str:
        raw = (self.FRONTEND_BASE_URL or self.APP_BASE_URL or "").strip().rstrip("/")
        if raw:
            return raw
        iss = (self.JWT_ISS or "").strip().lower()
        if "dev" in iss:
            return "https://app-dev.axelio.ru"
        return "https://app.axelio.ru"

    def api_base_url(self) -> str:
        raw = (self.API_BASE_URL or "").strip().rstrip("/")
        if raw:
            return raw
        frontend = self.frontend_base_url()
        if frontend:
            try:
                from urllib.parse import urlparse
                parsed = urlparse(frontend)
                host = (parsed.hostname or "").strip().lower()
                if host:
                    parts = host.split(".")
                    if parts[0] == "app":
                        parts[0] = "api"
                    elif parts[0].startswith("app-"):
                        parts[0] = parts[0].replace("app-", "api-", 1)
                    scheme = parsed.scheme or "https"
                    port = f":{parsed.port}" if parsed.port else ""
                    host_out = ".".join(parts)
                    return f"{scheme}://{host_out}{port}"
            except Exception:
                pass
        iss = (self.JWT_ISS or "").strip().lower()
        if "dev" in iss:
            return "https://api-dev.axelio.ru"
        return "https://api.axelio.ru"

    def cors_allow_origins(self) -> list[str]:
        raw = (self.CORS_ALLOW_ORIGINS or "").strip()
        if raw:
            seen: set[str] = set()
            origins: list[str] = []
            for part in raw.replace("\n", ",").replace(";", ",").split(","):
                item = part.strip().rstrip("/")
                if not item or item in seen:
                    continue
                seen.add(item)
                origins.append(item)
            if origins:
                return origins
        defaults = [
            self.frontend_base_url(),
            "https://app-dev.axelio.ru",
            "https://app.axelio.ru",
            "https://axelio.ru",
            "https://www.axelio.ru",
            "https://web.telegram.org",
        ]
        seen: set[str] = set()
        result: list[str] = []
        for item in defaults:
            value = str(item or "").strip().rstrip("/")
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    def super_admin_ids(self) -> set[int]:
        raw = (self.SUPER_ADMIN_TG_USER_IDS or "").strip()
        if not raw:
            return set()
        return {int(x.strip()) for x in raw.split(",") if x.strip().isdigit()}


settings = Settings()

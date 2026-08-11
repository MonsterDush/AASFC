from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"

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
    PUBLIC_LEAD_IP_LIMIT: int = 5
    PUBLIC_LEAD_RATE_WINDOW_SECONDS: int = 60 * 60
    PUBLIC_LEAD_BLOCK_SECONDS: int = 60 * 60

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
    TRUSTED_PROXY_IPS: str = "127.0.0.1,::1"

    # Robokassa
    ROBOKASSA_MERCHANT_LOGIN: str = ""
    ROBOKASSA_PASSWORD1: str = ""
    ROBOKASSA_PASSWORD2: str = ""
    ROBOKASSA_PASSWORD3: str = ""
    ROBOKASSA_REFUND_API_URL: str = "https://services.robokassa.ru/RefundService/Refund/Create"
    ROBOKASSA_REFUND_STATE_URL: str = "https://services.robokassa.ru/RefundService/Refund/GetState"
    ROBOKASSA_OPSTATE_URL: str = "https://auth.robokassa.ru/Merchant/WebService/Service.asmx/OpStateExt"
    ROBOKASSA_REFUND_JWT_ALGORITHM: str = "HS256"
    ROBOKASSA_REFUND_TIMEOUT_SECONDS: int = 15
    ROBOKASSA_TEST_PASSWORD1: str = ""
    ROBOKASSA_TEST_PASSWORD2: str = ""
    ROBOKASSA_TEST_MODE: bool = False
    ROBOKASSA_HASH_ALGORITHM: str = "MD5"
    ROBOKASSA_PAYMENT_URL: str = "https://auth.robokassa.ru/Merchant/Index.aspx"
    ROBOKASSA_USE_RETURN_URL2: bool = False
    ROBOKASSA_SEND_EXPIRATION_DATE: bool = False
    ROBOKASSA_CHECKOUT_TTL_MINUTES: int = 60
    BILLING_ALERT_STALE_PENDING_MINUTES: int = 180
    BILLING_ALERT_FAILED_THRESHOLD_24H: int = 5
    COOKIE_SECURE: bool = True
    ACCESS_TOKEN_TTL_SECONDS: int = 60 * 60 * 24 * 7  # 7 days

    # Roles
    SUPER_ADMIN_TG_USER_IDS: str = ""
    # When false, SUPER_ADMIN keeps access to venue settings/rules, but report-derived financial values are masked.
    SUPER_ADMIN_CAN_VIEW_FINANCIAL_VALUES: bool = True

    # Phone auth / OTP
    DEMO_ENABLED: bool = False
    DEMO_RETURN_URL: str = "https://axelio.ru"
    DEMO_PRIMARY_CTA_URL: str = "https://axelio.ru/#contact"
    DEMO_PRIMARY_CTA_LABEL: str = "Оставить заявку"
    DEMO_SECONDARY_CTA_URL: str = ""
    DEMO_SECONDARY_CTA_LABEL: str = "Начать пользоваться"
    DEMO_FIXTURE_PATH: str = "app/demo/demo_fixture.json"

    PHONE_AUTH_PROVIDER: str = "console"  # debug | console | sms_ru
    PHONE_AUTH_DEBUG_REVEAL_CODE: bool = False
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
    PASSWORD_LOGIN_ACCOUNT_LIMIT: int = 5
    PASSWORD_LOGIN_IP_LIMIT: int = 20
    PASSWORD_LOGIN_RATE_WINDOW_SECONDS: int = 60 * 15
    PASSWORD_LOGIN_BLOCK_SECONDS: int = 60 * 15

    # SMS.ru
    SMS_RU_API_ID: str = ""
    SMS_RU_API_URL: str = "https://sms.ru/sms/send"
    SMS_RU_TEST: bool = False
    SMS_RU_TIMEOUT_SECONDS: int = 10
    SMS_RU_FROM: str = ""
    SMS_RU_CALL_ADD_URL: str = "https://sms.ru/callcheck/add"
    SMS_RU_CALL_STATUS_URL: str = "https://sms.ru/callcheck/status"

    @model_validator(mode="after")
    def validate_production_security(self):
        if self.is_production():
            provider = str(self.PHONE_AUTH_PROVIDER or "").strip().lower()
            if provider == "debug":
                raise ValueError("PHONE_AUTH_PROVIDER=debug is forbidden in production")
            if self.PHONE_AUTH_DEBUG_REVEAL_CODE:
                raise ValueError("PHONE_AUTH_DEBUG_REVEAL_CODE=true is forbidden in production")
            if not self.COOKIE_SECURE:
                raise ValueError("COOKIE_SECURE=false is forbidden in production")
        return self

    def is_production(self) -> bool:
        return str(self.APP_ENV or "").strip().lower() in {"prod", "production"}

    def trusted_proxy_ips(self) -> set[str]:
        raw = str(self.TRUSTED_PROXY_IPS or "")
        return {
            item.strip()
            for item in raw.replace(";", ",").replace("\n", ",").split(",")
            if item.strip()
        }

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
        normalized = raw.replace("\n", ",").replace(";", ",").replace(" ", ",")
        return {int(x.strip()) for x in normalized.split(",") if x.strip().isdigit()}


settings = Settings()

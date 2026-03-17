from __future__ import annotations

import logging

from app.settings import settings

log = logging.getLogger(__name__)


class SmsSendResult(dict):
    @property
    def provider(self) -> str:
        return str(self.get("provider") or "debug")


class SmsProvider:
    provider_name = "debug"

    def send_code(self, *, phone_e164: str, code: str) -> SmsSendResult:
        raise NotImplementedError


class DebugSmsProvider(SmsProvider):
    provider_name = "debug"

    def send_code(self, *, phone_e164: str, code: str) -> SmsSendResult:
        log.warning("PHONE AUTH DEBUG CODE phone=%s code=%s", phone_e164, code)
        payload = SmsSendResult(ok=True, provider=self.provider_name)
        if settings.PHONE_AUTH_DEBUG_REVEAL_CODE:
            payload["debug_code"] = code
        return payload


class ConsoleSmsProvider(SmsProvider):
    provider_name = "console"

    def send_code(self, *, phone_e164: str, code: str) -> SmsSendResult:
        log.info("PHONE AUTH CODE phone=%s code=%s", phone_e164, code)
        return SmsSendResult(ok=True, provider=self.provider_name)


PROVIDERS = {
    "debug": DebugSmsProvider,
    "console": ConsoleSmsProvider,
}


def get_sms_provider() -> SmsProvider:
    provider_name = str(settings.PHONE_AUTH_PROVIDER or "debug").strip().lower()
    provider_cls = PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise RuntimeError(f"Unsupported PHONE_AUTH_PROVIDER: {provider_name}")
    return provider_cls()

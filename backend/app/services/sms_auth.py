from __future__ import annotations

import json
import logging
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fastapi import HTTPException

from app.settings import settings

log = logging.getLogger(__name__)


class SmsSendResult(dict):
    @property
    def provider(self) -> str:
        return str(self.get("provider") or "debug")


class SmsProvider:
    provider_name = "debug"

    def send_code(self, *, phone_e164: str, code: str, request_ip: str | None = None) -> SmsSendResult:
        raise NotImplementedError


class DebugSmsProvider(SmsProvider):
    provider_name = "debug"

    def send_code(self, *, phone_e164: str, code: str, request_ip: str | None = None) -> SmsSendResult:
        log.warning("PHONE AUTH DEBUG CODE phone=%s code=%s", phone_e164, code)
        payload = SmsSendResult(ok=True, provider=self.provider_name)
        if settings.PHONE_AUTH_DEBUG_REVEAL_CODE:
            payload["debug_code"] = code
        return payload


class ConsoleSmsProvider(SmsProvider):
    provider_name = "console"

    def send_code(self, *, phone_e164: str, code: str, request_ip: str | None = None) -> SmsSendResult:
        log.info("PHONE AUTH CODE phone=%s code=%s", phone_e164, code)
        return SmsSendResult(ok=True, provider=self.provider_name)


class SmsRuProvider(SmsProvider):
    provider_name = "sms_ru"

    def _user_message(self, status_code: int, status_text: str | None = None) -> tuple[int, str]:
        if status_code == 100:
            return 200, "OK"
        if status_code in {201, 202}:
            return 400, "Не удалось отправить SMS на этот номер"
        if status_code in {230, 231, 232, 233}:
            return 429, "Слишком много попыток. Попробуйте позже"
        if status_code in {220}:
            return 503, "Сервис SMS временно недоступен"
        if status_text:
            return 502, f"SMS.ru error: {status_text}"
        return 502, "Не удалось отправить SMS"

    def send_code(self, *, phone_e164: str, code: str, request_ip: str | None = None) -> SmsSendResult:
        api_id = str(settings.SMS_RU_API_ID or "").strip()
        if not api_id:
            raise RuntimeError("SMS_RU_API_ID is not configured")

        phone_digits = re.sub(r"\D+", "", phone_e164)
        if not phone_digits:
            raise HTTPException(status_code=400, detail="Некорректный номер телефона")

        message = str(settings.PHONE_AUTH_SMS_TEMPLATE or "Ваш код: {code}")
        try:
            message = message.format(code=code)
        except Exception:
            message = f"Ваш код: {code}"

        payload = {
            "api_id": api_id,
            "to": phone_digits,
            "msg": message,
            "json": 1,
        }
        if request_ip:
            payload["ip"] = request_ip
        if settings.SMS_RU_TEST:
            payload["test"] = 1
        if str(settings.SMS_RU_FROM or "").strip():
            payload["from"] = str(settings.SMS_RU_FROM).strip()

        body = urlencode(payload).encode("utf-8")
        req = Request(
            str(settings.SMS_RU_API_URL or "https://sms.ru/sms/send"),
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )

        try:
            with urlopen(req, timeout=float(settings.SMS_RU_TIMEOUT_SECONDS or 10)) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            log.exception("SMS.ru HTTP error")
            raise HTTPException(status_code=502, detail="Ошибка SMS-провайдера") from exc
        except URLError as exc:
            log.exception("SMS.ru transport error")
            raise HTTPException(status_code=503, detail="Не удалось связаться с SMS-провайдером") from exc
        except Exception as exc:
            log.exception("SMS.ru unknown error")
            raise HTTPException(status_code=503, detail="Не удалось отправить SMS") from exc

        try:
            data = json.loads(raw)
        except Exception as exc:
            log.error("SMS.ru bad response: %s", raw)
            raise HTTPException(status_code=502, detail="Некорректный ответ SMS-провайдера") from exc

        overall_status_code = int(data.get("status_code") or 0)
        overall_status_text = str(data.get("status_text") or data.get("status") or "").strip()
        if overall_status_code and overall_status_code != 100:
            http_status, msg = self._user_message(overall_status_code, overall_status_text)
            raise HTTPException(status_code=http_status, detail=msg)

        sms_map = data.get("sms") or {}
        phone_info = None
        if isinstance(sms_map, dict):
            for _, val in sms_map.items():
                if isinstance(val, dict):
                    phone_info = val
                    break
        if not phone_info:
            raise HTTPException(status_code=502, detail="SMS-провайдер не вернул статус отправки")

        per_status_code = int(phone_info.get("status_code") or 0)
        per_status_text = str(phone_info.get("status_text") or phone_info.get("status") or "").strip()
        if per_status_code != 100:
            http_status, msg = self._user_message(per_status_code, per_status_text)
            raise HTTPException(status_code=http_status, detail=msg)

        return SmsSendResult(
            ok=True,
            provider=self.provider_name,
            sms_id=phone_info.get("sms_id"),
            status_code=per_status_code,
            status_text=per_status_text or "OK",
            balance=data.get("balance"),
            test=bool(settings.SMS_RU_TEST),
        )


PROVIDERS = {
    "debug": DebugSmsProvider,
    "console": ConsoleSmsProvider,
    "sms_ru": SmsRuProvider,
}


def get_sms_provider() -> SmsProvider:
    provider_name = str(settings.PHONE_AUTH_PROVIDER or "debug").strip().lower()
    provider_cls = PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise RuntimeError(f"Unsupported PHONE_AUTH_PROVIDER: {provider_name}")
    return provider_cls()

from __future__ import annotations

import json
import logging
import re
import time
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


class CallStartResult(dict):
    @property
    def provider(self) -> str:
        return str(self.get("provider") or "debug")


class CallStatusResult(dict):
    @property
    def provider(self) -> str:
        return str(self.get("provider") or "debug")


class SmsProvider:
    provider_name = "debug"

    def send_code(self, *, phone_e164: str, code: str, request_ip: str | None = None) -> SmsSendResult:
        raise NotImplementedError

    def start_call_verification(self, *, phone_e164: str, request_ip: str | None = None) -> CallStartResult:
        raise NotImplementedError

    def get_call_verification_status(self, *, check_id: str) -> CallStatusResult:
        raise NotImplementedError


class DebugSmsProvider(SmsProvider):
    provider_name = "debug"

    def send_code(self, *, phone_e164: str, code: str, request_ip: str | None = None) -> SmsSendResult:
        log.warning("PHONE AUTH DEBUG CODE phone=%s code=%s", phone_e164, code)
        payload = SmsSendResult(ok=True, provider=self.provider_name)
        if settings.PHONE_AUTH_DEBUG_REVEAL_CODE:
            payload["debug_code"] = code
        return payload

    def start_call_verification(self, *, phone_e164: str, request_ip: str | None = None) -> CallStartResult:
        check_id = f"debug-{int(time.time() * 1000)}"
        log.warning("PHONE AUTH DEBUG CALL phone=%s check_id=%s", phone_e164, check_id)
        return CallStartResult(
            ok=True,
            provider=self.provider_name,
            check_id=check_id,
            call_phone="78000000000",
            call_phone_pretty="+7 (800) 000-00-00",
            debug_auto_verified=True,
        )

    def get_call_verification_status(self, *, check_id: str) -> CallStatusResult:
        return CallStatusResult(
            ok=True,
            provider=self.provider_name,
            check_status=401,
            check_status_text="Авторизация по звонку: номер подтвержден",
            confirmed=True,
            expired=False,
        )


class ConsoleSmsProvider(DebugSmsProvider):
    provider_name = "console"

    def send_code(self, *, phone_e164: str, code: str, request_ip: str | None = None) -> SmsSendResult:
        log.info("PHONE AUTH CODE phone=%s code=%s", phone_e164, code)
        return super().send_code(phone_e164=phone_e164, code=code, request_ip=request_ip)

    def start_call_verification(self, *, phone_e164: str, request_ip: str | None = None) -> CallStartResult:
        result = super().start_call_verification(phone_e164=phone_e164, request_ip=request_ip)
        log.info("PHONE AUTH CALL phone=%s check_id=%s", phone_e164, result.get("check_id"))
        return result


class SmsRuProvider(SmsProvider):
    provider_name = "sms_ru"

    def _user_message(self, status_code: int, status_text: str | None = None) -> tuple[int, str]:
        if status_code == 100:
            return 200, "OK"
        if status_code in {201, 202}:
            return 400, "Не удалось отправить подтверждение на этот номер"
        if status_code in {230, 231, 232, 233}:
            return 429, "Слишком много попыток. Попробуйте позже"
        if status_code in {220}:
            return 503, "Сервис SMS временно недоступен"
        if status_text:
            return 502, f"SMS.ru error: {status_text}"
        return 502, "Не удалось отправить подтверждение"

    def _phone_digits(self, phone_e164: str) -> str:
        phone_digits = re.sub(r"\D+", "", phone_e164)
        if not phone_digits:
            raise HTTPException(status_code=400, detail="Некорректный номер телефона")
        return phone_digits

    def _api_id(self) -> str:
        api_id = str(settings.SMS_RU_API_ID or "").strip()
        if not api_id:
            raise RuntimeError("SMS_RU_API_ID is not configured")
        return api_id

    def _request_json(self, url: str, payload: dict[str, object], *, method: str = "POST") -> dict:
        body = urlencode(payload).encode("utf-8")
        req = Request(
            url,
            data=body if method.upper() == "POST" else None,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method=method.upper(),
        )
        if method.upper() == "GET":
            req = Request(
                f"{url}?{urlencode(payload)}",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="GET",
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
            raise HTTPException(status_code=503, detail="Не удалось отправить подтверждение") from exc

        try:
            data = json.loads(raw)
        except Exception as exc:
            log.error("SMS.ru bad response: %s", raw)
            raise HTTPException(status_code=502, detail="Некорректный ответ SMS-провайдера") from exc
        return data

    def send_code(self, *, phone_e164: str, code: str, request_ip: str | None = None) -> SmsSendResult:
        message = str(settings.PHONE_AUTH_SMS_TEMPLATE or "Ваш код: {code}")
        try:
            message = message.format(code=code)
        except Exception:
            message = f"Ваш код: {code}"

        payload = {
            "api_id": self._api_id(),
            "to": self._phone_digits(phone_e164),
            "msg": message,
            "json": 1,
        }
        if request_ip:
            payload["ip"] = request_ip
        if settings.SMS_RU_TEST:
            payload["test"] = 1

        data = self._request_json(str(settings.SMS_RU_API_URL or "https://sms.ru/sms/send"), payload, method="POST")

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

    def start_call_verification(self, *, phone_e164: str, request_ip: str | None = None) -> CallStartResult:
        payload = {
            "api_id": self._api_id(),
            "phone": self._phone_digits(phone_e164),
            "json": 1,
        }
        data = self._request_json(
            str(settings.SMS_RU_CALL_ADD_URL or "https://sms.ru/callcheck/add"), payload, method="POST"
        )

        status_code = int(data.get("status_code") or 0)
        status_text = str(data.get("status_text") or data.get("status") or "").strip()
        if status_code != 100:
            http_status, msg = self._user_message(status_code, status_text)
            raise HTTPException(status_code=http_status, detail=msg)

        check_id = str(data.get("check_id") or "").strip()
        if not check_id:
            raise HTTPException(status_code=502, detail="Провайдер звонков не вернул идентификатор проверки")

        call_phone = str(data.get("call_phone") or "").strip()
        call_phone_pretty = str(data.get("call_phone_pretty") or call_phone or "").strip()

        return CallStartResult(
            ok=True,
            provider=self.provider_name,
            check_id=check_id,
            call_phone=call_phone,
            call_phone_pretty=call_phone_pretty,
            call_phone_html=data.get("call_phone_html"),
        )

    def get_call_verification_status(self, *, check_id: str) -> CallStatusResult:
        payload = {
            "api_id": self._api_id(),
            "check_id": str(check_id or "").strip(),
            "json": 1,
        }
        data = self._request_json(
            str(settings.SMS_RU_CALL_STATUS_URL or "https://sms.ru/callcheck/status"), payload, method="GET"
        )

        status_code = int(data.get("status_code") or 0)
        status_text = str(data.get("status_text") or data.get("status") or "").strip()
        if status_code != 100:
            http_status, msg = self._user_message(status_code, status_text)
            raise HTTPException(status_code=http_status, detail=msg)

        check_status = int(data.get("check_status") or 0)
        check_status_text = str(data.get("check_status_text") or "").strip()
        return CallStatusResult(
            ok=True,
            provider=self.provider_name,
            check_status=check_status,
            check_status_text=check_status_text,
            confirmed=check_status == 401,
            expired=check_status == 402,
            pending=check_status == 400,
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

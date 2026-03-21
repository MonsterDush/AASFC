from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

log = logging.getLogger("axelio.tg_notify")


def _direct_bot_token() -> Optional[str]:
    # keep backward compatibility
    return os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN")


def _bot_service_url() -> Optional[str]:
    return os.getenv("BOT_SERVICE_URL")


def _bot_service_secret() -> Optional[str]:
    return os.getenv("BOT_SERVICE_SECRET")


def _normalize_error_message(body_text: str | None) -> str | None:
    if not body_text:
        return None
    try:
        payload = json.loads(body_text)
        description = str(payload.get("description") or payload.get("detail") or "").strip()
        if description:
            return description
    except Exception:
        pass
    body_text = str(body_text).strip()
    return body_text[:300] if body_text else None


def notify_result(
    chat_id: int,
    text: str,
    *,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> dict:
    """Best-effort notification with normalized result. Never raises."""
    svc_url = _bot_service_url()
    secret = _bot_service_secret()
    timeout_seconds = max(float(os.getenv("BOT_SERVICE_TIMEOUT_SECONDS", "5") or 5), 1.0)

    if svc_url:
        try:
            data_obj = {"chat_id": int(chat_id), "text": text}
            if url:
                data_obj["url"] = url
            if button_text:
                data_obj["button_text"] = button_text
            if parse_mode:
                data_obj["parse_mode"] = parse_mode

            payload = json.dumps(data_obj, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                svc_url.rstrip("/") + "/notify",
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    **({"X-Bot-Secret": secret} if secret else {}),
                },
            )
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                        body = resp.read().decode("utf-8", errors="ignore")
                        js = json.loads(body) if body else {}
                        result = {
                            "ok": bool(js.get("ok", False)),
                            "retryable": bool(js.get("retryable", False)),
                            "status_code": int(js.get("status_code") or resp.status),
                            "error": js.get("error"),
                        }
                        if result["ok"]:
                            return result
                        if attempt == 2 or not result["retryable"]:
                            return result
                except urllib.error.HTTPError as e:
                    body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
                    error_message = _normalize_error_message(body) or str(e)
                    retryable = e.code in {408, 409, 425, 429, 500, 502, 503, 504}
                    if attempt == 2 or not retryable:
                        return {"ok": False, "retryable": retryable, "status_code": int(e.code), "error": error_message}
                except Exception as e:
                    retryable = True
                    if attempt == 2:
                        log.exception("bot-service notify exception: %s", e)
                        return {"ok": False, "retryable": retryable, "status_code": None, "error": str(e)}
                time.sleep(min(0.35 * (attempt + 1), 1.0))
        except Exception as e:
            log.exception("bot-service notify exception: %s", e)
            return {"ok": False, "retryable": True, "status_code": None, "error": str(e)}

    token = _direct_bot_token()
    if not token:
        log.warning("notify skipped: no BOT_SERVICE_URL and no telegram token (chat_id=%s)", chat_id)
        return {"ok": False, "retryable": False, "status_code": None, "error": "Telegram bot is not configured"}

    try:
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        data_dict = {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": "true",
        }
        if parse_mode:
            data_dict["parse_mode"] = parse_mode
        if url:
            bt = button_text or "Открыть в Axelio"
            reply_markup = {"inline_keyboard": [[{"text": bt, "web_app": {"url": url}}]]}
            data_dict["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

        data = urllib.parse.urlencode(data_dict).encode("utf-8")
        req = urllib.request.Request(api_url, data=data, method="POST")
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                    js = json.loads(body) if body else {}
                    ok = bool(js.get("ok"))
                    if ok:
                        return {"ok": True, "retryable": False, "status_code": int(resp.status), "error": None}
                    description = _normalize_error_message(body) or "telegram sendMessage failed"
                    params = js.get("parameters") or {}
                    retry_after = params.get("retry_after")
                    retryable = bool(retry_after) or int(resp.status) in {408, 409, 425, 429, 500, 502, 503, 504}
                    if attempt == 2 or not retryable:
                        return {"ok": False, "retryable": retryable, "status_code": int(resp.status), "error": description}
                    if retry_after:
                        time.sleep(min(max(float(retry_after), 0.35), 2.0))
                        continue
                time.sleep(min(0.35 * (attempt + 1), 1.0))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
                description = _normalize_error_message(body) or str(e)
                retryable = e.code in {408, 409, 425, 429, 500, 502, 503, 504}
                if attempt == 2 or not retryable:
                    return {"ok": False, "retryable": retryable, "status_code": int(e.code), "error": description}
                time.sleep(min(0.35 * (attempt + 1), 1.0))
            except Exception as e:
                if attempt == 2:
                    log.exception("telegram notify exception: %s", e)
                    return {"ok": False, "retryable": True, "status_code": None, "error": str(e)}
                time.sleep(min(0.35 * (attempt + 1), 1.0))
    except Exception as e:
        log.exception("telegram notify exception: %s", e)
        return {"ok": False, "retryable": True, "status_code": None, "error": str(e)}


def notify(
    chat_id: int,
    text: str,
    *,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> bool:
    return bool(notify_result(
        chat_id=chat_id,
        text=text,
        url=url,
        button_text=button_text,
        parse_mode=parse_mode,
    ).get("ok"))


def send_telegram_message(chat_id: int, text: str) -> bool:
    return notify(chat_id=chat_id, text=text)

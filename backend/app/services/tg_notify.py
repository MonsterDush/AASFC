from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from typing import Any

log = logging.getLogger("axelio.tg_notify")


def _bot_service_url() -> str | None:
    return os.getenv("BOT_SERVICE_URL")


def _bot_service_secret() -> str | None:
    return os.getenv("BOT_SERVICE_SECRET")


def _validated_bot_service_url(value: str) -> str:
    candidate = str(value or "").strip().rstrip("/")
    parsed = urlparse(candidate)
    is_loopback_http = parsed.scheme.lower() == "http" and parsed.hostname in {"127.0.0.1", "::1", "localhost"}
    if not parsed.hostname or parsed.username or (parsed.scheme.lower() != "https" and not is_loopback_http):
        raise ValueError("BOT_SERVICE_URL must use HTTPS, except for a loopback HTTP address")
    return candidate


def _normalize_error_message(body_text: str | None) -> str | None:
    if not body_text:
        return None
    try:
        payload = json.loads(body_text)
        description = str(payload.get("description") or payload.get("detail") or payload.get("error") or "").strip()
        if description:
            return description
    except Exception:
        pass
    body_text = str(body_text).strip()
    return body_text[:300] if body_text else None


def _reply_markup(*, url: str | None, button_text: str | None) -> dict[str, Any] | None:
    if not url:
        return None
    parsed = urlparse(str(url).strip())
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        log.warning("telegram web_app button skipped for non-HTTPS URL")
        return None
    return {
        "inline_keyboard": [
            [
                {
                    "text": button_text or "Открыть в Axelio",
                    "web_app": {"url": url},
                }
            ]
        ]
    }


def _send_via_bot_service(
    *,
    chat_id: int,
    text: str,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> dict:
    svc_url = _bot_service_url()
    if not svc_url:
        return {
            "ok": False,
            "retryable": False,
            "status_code": None,
            "error": "BOT_SERVICE_URL is not configured",
        }

    try:
        service_url = _validated_bot_service_url(svc_url)
    except ValueError as exc:
        return {"ok": False, "retryable": False, "status_code": None, "error": str(exc)}

    timeout_seconds = max(float(os.getenv("BOT_SERVICE_TIMEOUT_SECONDS", "5") or 5), 1.0)
    payload: dict[str, Any] = {
        "chat_id": int(chat_id),
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    markup = _reply_markup(url=url, button_text=button_text)
    if markup is not None:
        payload["reply_markup"] = markup

    request_body = json.dumps(
        {
            "method": "sendMessage",
            "payload": payload,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        service_url + "/internal/telegram/api",
        data=request_body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            **({"X-Bot-Secret": _bot_service_secret()} if _bot_service_secret() else {}),
        },
    )

    for attempt in range(3):
        try:
            # The target was restricted above to HTTPS or a loopback-only HTTP address.
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # nosec B310
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
            if attempt == 2:
                log.exception("bot-service telegram api exception: %s", e)
                return {"ok": False, "retryable": True, "status_code": None, "error": str(e)}
        time.sleep(min(0.35 * (attempt + 1), 1.0))

    return {"ok": False, "retryable": True, "status_code": None, "error": "bot-service telegram api failed"}


def notify_result(
    chat_id: int,
    text: str,
    *,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> dict:
    """Send Telegram notification through the single bot_service transport. Never raises."""
    if not chat_id or not str(text or "").strip():
        return {"ok": False, "retryable": False, "status_code": None, "error": "empty chat_id or text"}
    return _send_via_bot_service(
        chat_id=int(chat_id),
        text=text,
        url=url,
        button_text=button_text,
        parse_mode=parse_mode,
    )


def notify(
    chat_id: int,
    text: str,
    *,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> bool:
    return bool(
        notify_result(
            chat_id=chat_id,
            text=text,
            url=url,
            button_text=button_text,
            parse_mode=parse_mode,
        ).get("ok")
    )

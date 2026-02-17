from __future__ import annotations

import json
import logging
import os
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


def notify(
    chat_id: int,
    text: str,
    *,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> bool:
    """Best-effort notification.

    Preferred route (variant B): send to internal bot-service if BOT_SERVICE_URL is set.
    Fallback route: send directly via Telegram Bot API if TELEGRAM_BOT_TOKEN/TG_BOT_TOKEN is set.

    Returns True if request succeeded, else False. Never raises.
    """
    svc_url = _bot_service_url()
    secret = _bot_service_secret()

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
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                if 200 <= resp.status < 300:
                    if not body:
                        return True
                    try:
                        js = json.loads(body)
                        return bool(js.get("ok", True))
                    except Exception:
                        return True
                log.warning("bot-service notify failed status=%s body=%s", resp.status, body[:300])
                return False
        except Exception as e:
            log.exception("bot-service notify exception: %s", e)
            return False

    # Fallback: direct Telegram API
    token = _direct_bot_token()
    if not token:
        log.warning("notify skipped: no BOT_SERVICE_URL and no telegram token (chat_id=%s)", chat_id)
        return False

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
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            js = json.loads(body) if body else {}
            ok = bool(js.get("ok"))
            if not ok:
                log.warning("telegram notify failed status=%s body=%s", resp.status, body[:300])
            return ok
    except Exception as e:
        log.exception("telegram notify exception: %s", e)
        return False


# Backward compatible name used in older code
def send_telegram_message(chat_id: int, text: str) -> bool:
    return notify(chat_id=chat_id, text=text)

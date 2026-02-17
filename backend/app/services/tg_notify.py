from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Optional


def _direct_bot_token() -> Optional[str]:
    # keep backward compatibility
    return os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN")


def _bot_service_url() -> Optional[str]:
    return os.getenv("BOT_SERVICE_URL")


def _bot_service_secret() -> Optional[str]:
    return os.getenv("BOT_SERVICE_SECRET")


def notify(chat_id: int, text: str) -> bool:
    """Best-effort notification.

    Preferred route (variant B): send to internal bot-service if BOT_SERVICE_URL is set.
    Fallback route: send directly via Telegram Bot API if TELEGRAM_BOT_TOKEN/TG_BOT_TOKEN is set.

    Returns True if request succeeded, else False. Never raises.
    """
    url = _bot_service_url()
    import logging
    log = logging.getLogger("axelio.tg_notify")
    secret = _bot_service_secret()
    if url:
        try:
            payload = json.dumps({"chat_id": int(chat_id), "text": text}).encode("utf-8")
            req = urllib.request.Request(
                url.rstrip("/") + "/notify",
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    **({"X-Bot-Secret": secret} if secret else {}),
                },
            )
            log.debug(f"Sending notification to bot-service for chat_id={chat_id} and req = {req}") 
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                # bot-service returns {ok:true} (we don't strictly require it, 200 is enough)
                if 200 <= resp.status < 300:
                    if not body:
                        return True
                    try:
                        js = json.loads(body)
                        return bool(js.get("ok", True))
                    except Exception:
                        return True
                return False
        except Exception as e:
            log.exception(f"bot-service notify failed: {e}")
            return False

    # Fallback: direct Telegram API
    token = _direct_bot_token()
    if not token:
        return False
    try:
        api_url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode(
            {
                "chat_id": str(chat_id),
                "text": text,
                "disable_web_page_preview": "true",
            }
        ).encode("utf-8")
        req = urllib.request.Request(api_url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            js = json.loads(body) if body else {}
            return bool(js.get("ok"))
    except Exception:
        return False


# Backward compatible name used in older code
def send_telegram_message(chat_id: int, text: str) -> bool:
    return notify(chat_id=chat_id, text=text)

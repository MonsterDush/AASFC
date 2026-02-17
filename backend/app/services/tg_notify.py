from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def _bot_token() -> str | None:
    # Support both names (we standardize on TG_BOT_TOKEN for bot-service)
    return os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN")


def _bot_service_url() -> str | None:
    return os.getenv("BOT_SERVICE_URL")


def _bot_service_secret() -> str | None:
    return os.getenv("BOT_SERVICE_SECRET")


def send_telegram_message(chat_id: int, text: str) -> bool:
    """Best-effort Telegram notification.

    Preferred mode (Variant B):
      - if BOT_SERVICE_URL is set, call bot-service: POST {BOT_SERVICE_URL}/notify

    Fallback mode (Variant A):
      - call Telegram Bot API directly using TG_BOT_TOKEN / TELEGRAM_BOT_TOKEN

    Returns True if request was sent successfully (HTTP 200 + ok=true), else False.
    """
    # --- Variant B: bot-service ---
    bs_url = _bot_service_url()
    if bs_url:
        secret = _bot_service_secret() or ""
        try:
            url = bs_url.rstrip("/") + "/notify"
            payload = json.dumps({"chat_id": int(chat_id), "text": text}).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "X-Bot-Secret": secret,
                },
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                js = json.loads(body) if body else {}
                return bool(js.get("ok") is True)
        except Exception:
            return False

    # --- Variant A: direct Telegram API ---
    token = _bot_token()
    if not token:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode(
        {
            "chat_id": str(chat_id),
            "text": text,
            "disable_web_page_preview": "true",
        }
    ).encode("utf-8")

    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            js = json.loads(body) if body else {}
            return bool(js.get("ok"))
    except Exception:
        return False

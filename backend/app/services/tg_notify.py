from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def _bot_token() -> str | None:
    return os.getenv("TELEGRAM_BOT_TOKEN")


def send_telegram_message(chat_id: int, text: str) -> bool:
    """Best-effort Telegram notification.

    Returns True if request was sent successfully (HTTP 200 + ok=true), else False.
    If TELEGRAM_BOT_TOKEN is not set, returns False.
    """
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

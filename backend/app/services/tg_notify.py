from __future__ import annotations

import json
import os
import urllib.request


def _bot_service_url() -> str | None:
    return (os.getenv("BOT_SERVICE_URL") or "").strip() or None


def _bot_service_secret() -> str | None:
    return (os.getenv("BOT_SERVICE_SECRET") or "").strip() or None


def _direct_bot_token() -> str | None:
    # support both names
    return (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("TG_BOT_TOKEN") or "").strip() or None


def notify(chat_id: int, text: str) -> bool:
    """Best-effort notification.

    Priority:
      1) BOT_SERVICE_URL (HTTP POST /notify with X-Bot-Secret)
      2) direct Telegram Bot API using TELEGRAM_BOT_TOKEN / TG_BOT_TOKEN
    Returns True if request succeeded, else False.
    """
    if not chat_id or not text:
        return False

    url = _bot_service_url()
    secret = _bot_service_secret()
    if url:
        try:
            payload = {"chat_id": int(chat_id), "text": text}
            req = urllib.request.Request(
                url.rstrip("/") + "/notify",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    **({"X-Bot-Secret": secret} if secret else {}),
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = resp.read().decode("utf-8", "ignore")
            # bot-service returns {"ok": true} on success
            return '"ok"' in body or resp.status == 200
        except Exception:
            return False

    token = _direct_bot_token()
    if not token:
        return False

    try:
        import urllib.parse

        payload = {"chat_id": int(chat_id), "text": text, "disable_web_page_preview": True}
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=7) as resp:
            body = resp.read().decode("utf-8", "ignore")
        return '"ok":true' in body or resp.status == 200
    except Exception:
        return False


# Backward-compatible name used in some parts of the codebase
def send_telegram_message(chat_id: int, text: str) -> bool:
    return notify(chat_id=chat_id, text=text)

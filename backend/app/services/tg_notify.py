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


def _trim(s: str, n: int = 500) -> str:
    s = s or ""
    if len(s) <= n:
        return s
    return s[:n] + "…"


def notify(chat_id: int, text: str) -> bool:
    """Best-effort notification.

    Preferred route (variant B): send to internal bot-service if BOT_SERVICE_URL is set.
    Fallback route: send directly via Telegram Bot API if TELEGRAM_BOT_TOKEN/TG_BOT_TOKEN is set.

    Returns True if request succeeded, else False. Never raises.
    """
    url = _bot_service_url()
    secret = _bot_service_secret()

    # Route B: bot-service
    if url:
        try:
            endpoint = url.rstrip("/") + "/notify"
            payload = json.dumps({"chat_id": int(chat_id), "text": text}).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
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
                        log.info(
                            "notify via bot-service ok (chat_id=%s url=%s secret=%s)",
                            chat_id,
                            url,
                            "set" if secret else "missing",
                        )
                        return True
                    try:
                        js = json.loads(body)
                        ok = bool(js.get("ok", True))
                        log.info(
                            "notify via bot-service ok=%s (chat_id=%s url=%s secret=%s)",
                            ok,
                            chat_id,
                            url,
                            "set" if secret else "missing",
                        )
                        return ok
                    except Exception:
                        log.info(
                            "notify via bot-service ok (non-json) (chat_id=%s url=%s secret=%s body=%s)",
                            chat_id,
                            url,
                            "set" if secret else "missing",
                            _trim(body),
                        )
                        return True

                log.warning(
                    "notify via bot-service failed status=%s (chat_id=%s url=%s secret=%s body=%s)",
                    getattr(resp, "status", None),
                    chat_id,
                    url,
                    "set" if secret else "missing",
                    _trim(body),
                )
                return False
        except Exception as e:
            log.exception(
                "notify via bot-service exception (chat_id=%s url=%s secret=%s): %s",
                chat_id,
                url,
                "set" if secret else "missing",
                e,
            )
            return False

    # Route A fallback: direct Telegram API
    token = _direct_bot_token()
    if not token:
        log.warning(
            "notify skipped: no BOT_SERVICE_URL and no telegram token (chat_id=%s)", chat_id
        )
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
            try:
                js = json.loads(body) if body else {}
            except Exception:
                js = {}
            ok = bool(js.get("ok"))
            if ok:
                log.info("notify via telegram ok (chat_id=%s)", chat_id)
            else:
                log.warning(
                    "notify via telegram failed status=%s (chat_id=%s body=%s)",
                    getattr(resp, "status", None),
                    chat_id,
                    _trim(body),
                )
            return ok
    except Exception as e:
        log.exception("notify via telegram exception (chat_id=%s): %s", chat_id, e)
        return False


# Backward compatible name used in older code
def send_telegram_message(chat_id: int, text: str) -> bool:
    return notify(chat_id=chat_id, text=text)

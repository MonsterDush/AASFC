from __future__ import annotations

import os
import json
import asyncio
import logging
import time
import urllib.request
import urllib.parse
import urllib.error
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# Outbound-only bot service (Variant B).
# It exposes HTTP API for backend notifications and can later run scheduled reminders.

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
BOT_SERVICE_SECRET = os.getenv("BOT_SERVICE_SECRET", "")
TG_WEBHOOK_SECRET_TOKEN = os.getenv("TG_WEBHOOK_SECRET_TOKEN", "")
BACKEND_INTERNAL_BASE_URL = (os.getenv("BACKEND_INTERNAL_BASE_URL") or os.getenv("BACKEND_API_URL") or "http://127.0.0.1:9001").rstrip("/")
BROWSER_AUTH_WEBHOOK_PATH = os.getenv("BROWSER_AUTH_WEBHOOK_PATH", "/auth/telegram/browser/webhook")

app = FastAPI(title="Axelio Bot Service")

log = logging.getLogger("axelio-bot")

# ---- Scheduled shift reminders (optional) ----
#
# If you want the bot service to run reminders itself (instead of cron/systemd),
# set:
#   REMINDER_SCHEDULER_ENABLED=1
# and make sure send_shift_reminders.py is deployed рядом с этим файлом.
REMINDER_SCHEDULER_ENABLED = os.getenv("REMINDER_SCHEDULER_ENABLED", "").strip() in ("1", "true", "yes")
REMINDER_INTERVAL_SECONDS = int(os.getenv("REMINDER_INTERVAL_SECONDS", "900"))  # 15 minutes

_reminder_lock = asyncio.Lock()

try:
    from . import send_shift_reminders as _ssr  # noqa: WPS433
except Exception:  # pragma: no cover
    _ssr = None


class NotifyIn(BaseModel):
    chat_id: int = Field(..., description="Telegram chat id (for private chats equals tg_user_id)")
    text: str = Field(..., min_length=1, max_length=4000)
    url: str | None = Field(None, description="Optional URL to open in WebApp button")
    button_text: str | None = Field(None, description="Button text (default: Открыть в Axelio)")
    parse_mode: str | None = Field(None, description="Optional parse_mode: HTML or MarkdownV2")


def _normalize_telegram_error(status_code: int | None, body_text: str | None) -> tuple[bool, str | None]:
    retryable = int(status_code or 0) in {408, 409, 425, 429, 500, 502, 503, 504}
    if not body_text:
        return retryable, None
    try:
        payload = json.loads(body_text)
        description = str(payload.get("description") or "").strip() or None
        params = payload.get("parameters") or {}
        retry_after = params.get("retry_after")
        if retry_after:
            retryable = True
        return retryable, description
    except Exception:
        return retryable, str(body_text).strip()[:300] or None


def _telegram_browser_webhook_url() -> str:
    path = BROWSER_AUTH_WEBHOOK_PATH or "/auth/telegram/browser/webhook"
    if not path.startswith("/"):
        path = "/" + path
    return f"{BACKEND_INTERNAL_BASE_URL}{path}"


def _post_json(url: str, payload: dict, *, headers: dict[str, str] | None = None, timeout: int = 7) -> tuple[int | None, str | None]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        return int(getattr(resp, "status", 200) or 200), body


def _send_message(
    token: str,
    chat_id: int,
    text: str,
    *,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> dict:
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

    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=7) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                js = json.loads(body) if body else {}
                ok = bool(js.get("ok"))
                if ok:
                    return {"ok": True, "retryable": False, "status_code": int(resp.status), "error": None}
                retryable, description = _normalize_telegram_error(resp.status, body)
                last_error = description or "telegram sendMessage failed"
                if attempt == 2 or not retryable:
                    return {"ok": False, "retryable": retryable, "status_code": int(resp.status), "error": last_error}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
            retryable, description = _normalize_telegram_error(e.code, body)
            last_error = description or str(e)
            if attempt == 2 or not retryable:
                return {"ok": False, "retryable": retryable, "status_code": int(e.code), "error": last_error}
        except Exception as e:
            last_error = str(e)
            if attempt == 2:
                return {"ok": False, "retryable": True, "status_code": None, "error": last_error}
        time.sleep(min(0.35 * (attempt + 1), 1.0))
    return {"ok": False, "retryable": True, "status_code": None, "error": last_error or "telegram sendMessage failed"}


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/notify")
def notify(payload: NotifyIn, request: Request):
    got = request.headers.get("X-Bot-Secret", "")
    if BOT_SERVICE_SECRET and got != BOT_SERVICE_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    if not TG_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TG_BOT_TOKEN is not configured")

    result = _send_message(
        TG_BOT_TOKEN,
        payload.chat_id,
        payload.text,
        url=payload.url,
        button_text=payload.button_text,
        parse_mode=payload.parse_mode,
    )
    return result


@app.post("/telegram/webhook", status_code=204)
async def telegram_webhook_proxy(request: Request):
    """Proxy Telegram updates to backend browser-auth webhook.

    This keeps existing bot webhook installations working even when
    browser Telegram login is handled by the backend app.
    """

    expected_secret = (TG_WEBHOOK_SECRET_TOKEN or "").strip()
    got_secret = (request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") or "").strip()
    if expected_secret and got_secret != expected_secret:
        raise HTTPException(status_code=401, detail="bad telegram secret")

    payload = await request.json()
    forward_headers: dict[str, str] = {}
    if got_secret:
        forward_headers["X-Telegram-Bot-Api-Secret-Token"] = got_secret

    try:
        status_code, body = await asyncio.to_thread(
            _post_json,
            _telegram_browser_webhook_url(),
            payload,
            headers=forward_headers,
            timeout=7,
        )
        if status_code and status_code >= 400:
            log.warning("browser auth webhook proxy failed: status=%s body=%s", status_code, (body or "")[:300])
            raise HTTPException(status_code=502, detail="backend browser auth webhook failed")
    except HTTPException:
        raise
    except Exception as exc:
        log.exception("telegram webhook proxy failed")
        raise HTTPException(status_code=502, detail=f"telegram webhook proxy error: {exc}")


@app.post("/internal/run-shift-reminders")
async def run_shift_reminders(request: Request):
    """Manual trigger for shift reminders.

    Protected by BOT_SERVICE_SECRET via X-Bot-Secret header.
    """

    got = request.headers.get("X-Bot-Secret", "")
    if BOT_SERVICE_SECRET and got != BOT_SERVICE_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    if _ssr is None:
        raise HTTPException(status_code=500, detail="send_shift_reminders.py is not available in bot service")

    async with _reminder_lock:
        try:
            sent = await asyncio.to_thread(_ssr.main)
            return {"ok": True, "sent": int(sent or 0)}
        except Exception as e:
            log.exception("shift reminders failed")
            raise HTTPException(status_code=500, detail=f"reminder error: {e}")


@app.on_event("startup")
async def _start_scheduler():
    if not REMINDER_SCHEDULER_ENABLED:
        return
    if _ssr is None:
        log.warning("REMINDER_SCHEDULER_ENABLED=1 but send_shift_reminders.py is missing")
        return

    async def _loop():
        while True:
            try:
                async with _reminder_lock:
                    await asyncio.to_thread(_ssr.main)
            except Exception:
                log.exception("scheduled shift reminders failed")
            await asyncio.sleep(REMINDER_INTERVAL_SECONDS)

    asyncio.create_task(_loop())

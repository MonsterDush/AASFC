from __future__ import annotations

import os
import json
import asyncio
import logging
import time
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import socket
from typing import Any
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# Outbound-only bot service (Variant B).
# It exposes HTTP API for backend notifications and can later run scheduled reminders.

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
BOT_SERVICE_SECRET = os.getenv("BOT_SERVICE_SECRET", "")
BACKEND_INTERNAL_URL = (
    os.getenv("BACKEND_INTERNAL_URL")
    or os.getenv("BACKEND_BASE_URL")
    or os.getenv("API_BASE")
    or "http://127.0.0.1:9001"
).rstrip("/")
TG_WEBHOOK_SECRET_TOKEN = os.getenv("TG_WEBHOOK_SECRET_TOKEN", "")


_ORIGINAL_GETADDRINFO = socket.getaddrinfo

def _telegram_ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if str(host or "").lower() == "api.telegram.org" and str(os.getenv("TELEGRAM_FORCE_IPV4", "1")).lower() not in {"0", "false", "no"}:
        return _ORIGINAL_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)
    return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

if getattr(socket.getaddrinfo, "__name__", "") != "_telegram_ipv4_getaddrinfo":
    socket.getaddrinfo = _telegram_ipv4_getaddrinfo

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




class TelegramApiIn(BaseModel):
    method: str = Field(..., min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


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




def _telegram_form_payload(payload: dict[str, Any]) -> dict[str, str]:
    data_dict: dict[str, str] = {}
    for key, value in (payload or {}).items():
        if value is None:
            continue
        if isinstance(value, bool):
            data_dict[key] = "true" if value else "false"
        elif isinstance(value, (dict, list)):
            data_dict[key] = json.dumps(value, ensure_ascii=False)
        else:
            data_dict[key] = str(value)
    return data_dict


def _telegram_api_post_curl(token: str, method: str, payload: dict[str, Any], *, timeout_seconds: int = 12) -> dict:
    """Fallback sender for VPS cases where Python urllib hangs but curl -4 works."""
    api_url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(_telegram_form_payload(payload)).encode("utf-8")
    try:
        proc = subprocess.run(
            [
                "curl",
                "-4",
                "--http1.1",
                "--silent",
                "--show-error",
                "--fail-with-body",
                "--connect-timeout",
                "5",
                "--max-time",
                str(max(int(timeout_seconds), 3)),
                "-X",
                "POST",
                api_url,
                "-H",
                "Content-Type: application/x-www-form-urlencoded",
                "--data-binary",
                data.decode("utf-8"),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=max(int(timeout_seconds) + 3, 6),
        )
    except Exception as e:
        return {"ok": False, "retryable": True, "status_code": None, "error": f"curl exception: {e}", "result": None}

    raw = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        retryable = proc.returncode in {7, 28, 35, 52, 56}
        return {
            "ok": False,
            "retryable": retryable,
            "status_code": None,
            "error": (err or raw or f"curl exit {proc.returncode}")[:500],
            "result": None,
        }

    try:
        js = json.loads(raw or "{}")
    except Exception:
        return {"ok": False, "retryable": True, "status_code": None, "error": f"invalid telegram json: {raw[:300]}", "result": None}

    if bool(js.get("ok")):
        return {"ok": True, "retryable": False, "status_code": 200, "error": None, "result": js}

    description = str(js.get("description") or f"telegram {method} failed")
    return {"ok": False, "retryable": False, "status_code": None, "error": description, "result": js}


def _telegram_api_post(token: str, method: str, payload: dict[str, Any]) -> dict:
    api_url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(_telegram_form_payload(payload)).encode("utf-8")
    req = urllib.request.Request(api_url, data=data, method="POST")

    last_error = None
    urllib_attempts = int(os.getenv("TELEGRAM_URLLIB_ATTEMPTS", "1") or "1")
    urllib_attempts = max(0, min(urllib_attempts, 3))
    timeout_seconds = float(os.getenv("TELEGRAM_API_TIMEOUT_SECONDS", "6") or "6")

    for attempt in range(urllib_attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                js = json.loads(body) if body else {}
                ok = bool(js.get("ok"))
                if ok:
                    return {"ok": True, "retryable": False, "status_code": int(resp.status), "error": None, "result": js}
                retryable, description = _normalize_telegram_error(resp.status, body)
                last_error = description or f"telegram {method} failed"
                if attempt == urllib_attempts - 1 or not retryable:
                    break
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
            retryable, description = _normalize_telegram_error(e.code, body)
            last_error = description or str(e)
            if attempt == urllib_attempts - 1 or not retryable:
                return {"ok": False, "retryable": retryable, "status_code": int(e.code), "error": last_error, "result": None}
        except Exception as e:
            last_error = str(e)
            log.warning("telegram urllib %s failed on attempt %s/%s: %s", method, attempt + 1, urllib_attempts, e)
        time.sleep(min(0.35 * (attempt + 1), 1.0))

    if str(os.getenv("TELEGRAM_CURL_FALLBACK", "1")).lower() not in {"0", "false", "no"}:
        curl_result = _telegram_api_post_curl(token, method, payload, timeout_seconds=int(os.getenv("TELEGRAM_CURL_TIMEOUT_SECONDS", "12") or 12))
        if curl_result.get("ok"):
            return curl_result
        if last_error:
            curl_result["error"] = f"{curl_result.get('error')}; urllib_last_error={last_error}"
        return curl_result

    return {"ok": False, "retryable": True, "status_code": None, "error": last_error or f"telegram {method} failed", "result": None}

def _forward_telegram_update_to_backend(raw_body: bytes, *, secret_token: str | None = None) -> tuple[int, str]:
    target_url = f"{BACKEND_INTERNAL_URL}/auth/telegram/browser/webhook"
    headers = {"Content-Type": "application/json"}
    if secret_token:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret_token
    req = urllib.request.Request(target_url, data=raw_body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return int(resp.status), body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        return int(e.code), body


def _send_message(
    token: str,
    chat_id: int,
    text: str,
    *,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> dict:
    payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    if url:
        bt = button_text or "Открыть в Axelio"
        payload["reply_markup"] = {"inline_keyboard": [[{"text": bt, "web_app": {"url": url}}]]}

    return _telegram_api_post(token, "sendMessage", payload)


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




@app.post("/internal/telegram/api")
def telegram_api_proxy(payload: TelegramApiIn, request: Request):
    got = request.headers.get("X-Bot-Secret", "")
    if BOT_SERVICE_SECRET and got != BOT_SERVICE_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    if not TG_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TG_BOT_TOKEN is not configured")

    result = _telegram_api_post(TG_BOT_TOKEN, payload.method, payload.payload or {})
    if not result.get("ok") and not result.get("retryable"):
        # Preserve a 200 response for normalized caller handling, same style as /notify.
        return result
    return result


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



async def _forward_telegram_update_to_backend_background(raw_body: bytes, *, secret_token: str | None = None) -> None:
    try:
        status_code, body = await asyncio.to_thread(
            _forward_telegram_update_to_backend,
            raw_body,
            secret_token=secret_token,
        )
        if not (200 <= int(status_code or 0) < 300):
            log.error("telegram webhook proxy failed in background: status=%s body=%s", status_code, str(body or "")[:500])
    except Exception:
        log.exception("telegram webhook proxy background task failed")


@app.post("/telegram/webhook", status_code=204)
@app.post("/webhook", status_code=204)
async def telegram_webhook(request: Request):
    if TG_WEBHOOK_SECRET_TOKEN:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != TG_WEBHOOK_SECRET_TOKEN:
            raise HTTPException(status_code=401, detail="bad telegram secret")

    raw_body = await request.body()
    secret_token = TG_WEBHOOK_SECRET_TOKEN or request.headers.get("X-Telegram-Bot-Api-Secret-Token") or None

    # Telegram must receive 204 quickly. Forwarding to backend is intentionally
    # asynchronous, because backend may call this bot_service back to send/edit
    # Telegram messages. Waiting here creates a circular timeout.
    asyncio.create_task(_forward_telegram_update_to_backend_background(raw_body, secret_token=secret_token))
    return

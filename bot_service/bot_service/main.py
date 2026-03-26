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
BACKEND_INTERNAL_URL = (os.getenv("BACKEND_INTERNAL_URL") or os.getenv("API_BASE") or "http://127.0.0.1:9001").rstrip("/")
TG_WEBHOOK_SECRET_TOKEN = os.getenv("TG_WEBHOOK_SECRET_TOKEN", "")
BROWSER_LOGIN_START_PREFIX = "axelio_login_"
LAST_PUBLIC_API_BASE = ""

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


def _json_request(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None, timeout: float = 7.0) -> tuple[int | None, dict | None, str | None]:
    req_headers = dict(headers or {})
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            return int(resp.status), (json.loads(body) if body else {}), None
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
        try:
            data_obj = json.loads(body) if body else None
        except Exception:
            data_obj = None
        return int(e.code), data_obj, body or str(e)
    except Exception as e:
        return None, None, str(e)


def _backend_base_url() -> str:
    return (BACKEND_INTERNAL_URL or LAST_PUBLIC_API_BASE or "http://127.0.0.1:9001").rstrip("/")


def _backend_request(path: str, *, method: str = "GET", payload: dict | None = None) -> tuple[int | None, dict | None, str | None]:
    headers = {"Accept": "application/json"}
    if BOT_SERVICE_SECRET:
        headers["X-Bot-Secret"] = BOT_SERVICE_SECRET
    return _json_request(f"{_backend_base_url()}{path}", method=method, payload=payload, headers=headers, timeout=7.0)


def _telegram_api_post(method_name: str, payload: dict) -> tuple[int | None, dict | None, str | None]:
    if not TG_BOT_TOKEN:
        return None, None, "TG_BOT_TOKEN is not configured"
    return _json_request(
        f"https://api.telegram.org/bot{TG_BOT_TOKEN}/{method_name}",
        method="POST",
        payload=payload,
        headers={"Accept": "application/json"},
        timeout=7.0,
    )


def _send_text_message(chat_id: int, text: str, *, reply_markup: dict | None = None) -> None:
    payload = {
        "chat_id": int(chat_id),
        "text": text,
        "disable_web_page_preview": True,
    }
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    _telegram_api_post("sendMessage", payload)


def _answer_callback(callback_query_id: str, text: str, *, show_alert: bool = False) -> None:
    _telegram_api_post("answerCallbackQuery", {
        "callback_query_id": callback_query_id,
        "text": text[:180],
        "show_alert": bool(show_alert),
    })


def _edit_message(chat_id: int, message_id: int, text: str) -> None:
    _telegram_api_post("editMessageText", {
        "chat_id": int(chat_id),
        "message_id": int(message_id),
        "text": text,
        "disable_web_page_preview": True,
    })


def _extract_start_payload(text: str | None) -> str:
    raw = str(text or "").strip()
    if not raw.startswith("/start"):
        return ""
    parts = raw.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _handle_browser_login_start(message: dict) -> None:
    chat = message.get("chat") or {}
    chat_id = int(chat.get("id") or 0)
    if not chat_id:
        return
    payload = _extract_start_payload(message.get("text"))
    if not payload.startswith(BROWSER_LOGIN_START_PREFIX):
        return
    token = payload[len(BROWSER_LOGIN_START_PREFIX):].strip()
    status_code, session_data, error_text = _backend_request(f"/auth/telegram/browser/internal/session/{urllib.parse.quote(token)}")
    if status_code == 404:
        _send_text_message(chat_id, "Эта ссылка для входа уже недействительна. Вернитесь в браузер и начните вход заново.")
        return
    if status_code == 410 or (session_data and session_data.get("status") == "expired"):
        _send_text_message(chat_id, "Сессия входа истекла. Вернитесь в браузер и создайте новую ссылку.")
        return
    if status_code and status_code >= 400:
        _send_text_message(chat_id, "Не удалось подготовить подтверждение входа. Попробуйте ещё раз чуть позже.")
        return

    reply_markup = {
        "inline_keyboard": [[{
            "text": "Подтвердить вход",
            "callback_data": f"browser_login_confirm:{token}",
        }]]
    }
    _send_text_message(
        chat_id,
        "Нажмите кнопку ниже, чтобы подтвердить вход в Axelio в браузере. После подтверждения вернитесь в браузер — страница завершит вход автоматически.",
        reply_markup=reply_markup,
    )


def _handle_browser_login_callback(callback_query: dict) -> None:
    callback_id = str(callback_query.get("id") or "")
    data = str(callback_query.get("data") or "")
    if not data.startswith("browser_login_confirm:"):
        if callback_id:
            _answer_callback(callback_id, "Неизвестное действие", show_alert=False)
        return

    token = data.split(":", 1)[1].strip()
    from_user = callback_query.get("from") or {}
    payload = {
        "token": token,
        "tg_user_id": int(from_user.get("id") or 0),
        "username": from_user.get("username"),
        "first_name": from_user.get("first_name"),
        "last_name": from_user.get("last_name"),
    }
    status_code, body, error_text = _backend_request("/auth/telegram/browser/internal/approve", method="POST", payload=payload)
    if status_code and status_code < 300:
        if callback_id:
            _answer_callback(callback_id, "Вход подтверждён")
        msg = callback_query.get("message") or {}
        chat = msg.get("chat") or {}
        message_id = msg.get("message_id")
        chat_id = chat.get("id")
        if chat_id and message_id:
            _edit_message(int(chat_id), int(message_id), "Вход подтверждён. Вернитесь в браузер — Axelio завершит авторизацию автоматически.")
        else:
            _send_text_message(int((callback_query.get("from") or {}).get("id") or 0), "Вход подтверждён. Вернитесь в браузер.")
        return

    detail = None
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("error")
    detail = detail or error_text or "Не удалось подтвердить вход"
    if callback_id:
        _answer_callback(callback_id, str(detail), show_alert=True)


def _process_telegram_update(update: dict) -> None:
    message = update.get("message") or {}
    callback_query = update.get("callback_query") or {}
    if message:
        _handle_browser_login_start(message)
        return
    if callback_query:
        _handle_browser_login_callback(callback_query)
        return


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


@app.post("/telegram/webhook")
@app.post("/webhook")
async def telegram_webhook(request: Request):
    global LAST_PUBLIC_API_BASE
    got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if TG_WEBHOOK_SECRET_TOKEN and got != TG_WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=401, detail="bad telegram webhook secret")
    if not BACKEND_INTERNAL_URL:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "https"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
        if host:
            LAST_PUBLIC_API_BASE = f"{proto}://{host}".rstrip("/")
    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid telegram update")
    try:
        _process_telegram_update(update or {})
    except Exception:
        log.exception("telegram webhook processing failed")
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

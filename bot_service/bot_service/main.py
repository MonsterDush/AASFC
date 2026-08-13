from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# Single outbound Telegram transport for Axelio notifications.
# Backend sends all push messages to /internal/telegram/api, and this service
# is the only place that calls https://api.telegram.org/bot... directly.

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
    if str(host or "").lower() == "api.telegram.org" and str(os.getenv("TELEGRAM_FORCE_IPV4", "1")).lower() not in {
        "0",
        "false",
        "no",
    }:
        return _ORIGINAL_GETADDRINFO(host, port, socket.AF_INET, type, proto, flags)
    return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)


if getattr(socket.getaddrinfo, "__name__", "") != "_telegram_ipv4_getaddrinfo":
    socket.getaddrinfo = _telegram_ipv4_getaddrinfo

app = FastAPI(title="Axelio Bot Service")
log = logging.getLogger("axelio-bot")


class TelegramApiIn(BaseModel):
    method: str = Field(..., min_length=1, max_length=80)
    payload: dict[str, Any] = Field(default_factory=dict)


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


def _telegram_payload_to_form_bytes(payload: dict[str, Any]) -> bytes:
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
    return urllib.parse.urlencode(data_dict).encode("utf-8")


def _parse_telegram_api_response(method: str, status_code: int | None, body: str, *, curl_returncode: int = 0) -> dict:
    try:
        js = json.loads(body) if body else {}
    except Exception:
        js = {}

    ok = bool(js.get("ok"))
    if ok:
        return {"ok": True, "retryable": False, "status_code": int(status_code or 200), "error": None, "result": js}

    retryable, description = _normalize_telegram_error(status_code, body)
    if curl_returncode:
        retryable = True
    error = description or js.get("description") or body[:300] or f"telegram {method} failed"
    return {
        "ok": False,
        "retryable": bool(retryable),
        "status_code": int(status_code or 0) if status_code else None,
        "error": str(error),
        "result": js or None,
    }


def _telegram_api_post_curl(token: str, method: str, payload: dict[str, Any]) -> dict:
    """Telegram API transport through system curl.

    On the current VPS curl -4 reaches api.telegram.org reliably while Python urllib
    may hang on the same endpoint. This transport is the default production path.
    """
    api_url = f"https://api.telegram.org/bot{token}/{method}"
    data = _telegram_payload_to_form_bytes(payload)
    timeout_seconds = max(int(float(os.getenv("TELEGRAM_API_TIMEOUT_SECONDS", "10") or 10)), 3)
    connect_timeout = max(int(float(os.getenv("TELEGRAM_API_CONNECT_TIMEOUT_SECONDS", "5") or 5)), 2)
    force_ipv4 = str(os.getenv("TELEGRAM_FORCE_IPV4", "1")).lower() not in {"0", "false", "no"}

    cmd = [
        "curl",
        "-sS",
        "--show-error",
        "--max-time",
        str(timeout_seconds),
        "--connect-timeout",
        str(connect_timeout),
        "-H",
        "Content-Type: application/x-www-form-urlencoded",
        "--data-binary",
        "@-",
        api_url,
    ]
    if force_ipv4:
        cmd.insert(1, "-4")

    last_error = None
    for attempt in range(3):
        try:
            proc = subprocess.run(
                cmd,
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout_seconds + connect_timeout + 2,
                check=False,
            )
            body = proc.stdout.decode("utf-8", errors="ignore")
            stderr = proc.stderr.decode("utf-8", errors="ignore").strip()
            result = _parse_telegram_api_response(
                method, 200 if proc.returncode == 0 else None, body, curl_returncode=proc.returncode
            )
            if result.get("ok"):
                return result
            last_error = result.get("error") or stderr or f"curl exit {proc.returncode}"
            if attempt == 2 or not result.get("retryable"):
                if stderr and not result.get("error"):
                    result["error"] = stderr[:300]
                return result
        except Exception as e:
            last_error = str(e)
            if attempt == 2:
                return {"ok": False, "retryable": True, "status_code": None, "error": last_error, "result": None}
        time.sleep(min(0.5 * (attempt + 1), 1.5))

    return {
        "ok": False,
        "retryable": True,
        "status_code": None,
        "error": last_error or f"telegram {method} failed",
        "result": None,
    }


def _telegram_api_post_urllib(token: str, method: str, payload: dict[str, Any]) -> dict:
    api_url = f"https://api.telegram.org/bot{token}/{method}"
    data = _telegram_payload_to_form_bytes(payload)
    req = urllib.request.Request(api_url, data=data, method="POST")

    last_error = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=7) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                result = _parse_telegram_api_response(method, int(resp.status), body)
                if result.get("ok"):
                    return result
                last_error = result.get("error") or f"telegram {method} failed"
                if attempt == 2 or not result.get("retryable"):
                    return result
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else ""
            result = _parse_telegram_api_response(method, int(e.code), body)
            last_error = result.get("error") or str(e)
            if attempt == 2 or not result.get("retryable"):
                return result
        except Exception as e:
            last_error = str(e)
            if attempt == 2:
                return {"ok": False, "retryable": True, "status_code": None, "error": last_error, "result": None}
        time.sleep(min(0.35 * (attempt + 1), 1.0))
    return {
        "ok": False,
        "retryable": True,
        "status_code": None,
        "error": last_error or f"telegram {method} failed",
        "result": None,
    }


def _telegram_api_post(token: str, method: str, payload: dict[str, Any]) -> dict:
    transport = str(os.getenv("TELEGRAM_API_TRANSPORT", "curl") or "curl").strip().lower()
    if transport == "urllib":
        result = _telegram_api_post_urllib(token, method, payload)
        if result.get("ok") or str(os.getenv("TELEGRAM_API_CURL_FALLBACK", "1")).lower() in {"0", "false", "no"}:
            return result
        log.warning("telegram urllib failed, trying curl fallback: method=%s error=%s", method, result.get("error"))
        return _telegram_api_post_curl(token, method, payload)
    return _telegram_api_post_curl(token, method, payload)


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


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/internal/telegram/api")
def telegram_api_proxy(payload: TelegramApiIn, request: Request):
    got = request.headers.get("X-Bot-Secret", "")
    if BOT_SERVICE_SECRET and got != BOT_SERVICE_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    if not TG_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TG_BOT_TOKEN is not configured")

    return _telegram_api_post(TG_BOT_TOKEN, payload.method, payload.payload or {})


def _forward_telegram_update_to_backend_background(raw_body: bytes, *, secret_token: str | None = None) -> None:
    try:
        status_code, body = _forward_telegram_update_to_backend(raw_body, secret_token=secret_token)
        if not (200 <= int(status_code or 0) < 300):
            log.error("telegram webhook proxy background failed: status=%s body=%s", status_code, str(body or "")[:500])
    except Exception:
        log.exception("telegram webhook proxy background task failed")


@app.post("/telegram/webhook", status_code=204)
@app.post("/webhook", status_code=204)
async def telegram_webhook(request: Request, background_tasks: BackgroundTasks):
    if TG_WEBHOOK_SECRET_TOKEN:
        got = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if got != TG_WEBHOOK_SECRET_TOKEN:
            raise HTTPException(status_code=401, detail="bad telegram secret")

    raw_body = await request.body()
    secret_token = TG_WEBHOOK_SECRET_TOKEN or request.headers.get("X-Telegram-Bot-Api-Secret-Token") or None

    # Critical: answer Telegram immediately. Backend processing may call this bot
    # service back for Telegram API methods; waiting here causes a circular timeout.
    background_tasks.add_task(
        _forward_telegram_update_to_backend_background,
        raw_body,
        secret_token=secret_token,
    )
    return None

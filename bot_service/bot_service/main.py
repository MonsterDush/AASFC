from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# Outbound-only bot service (Variant B).
# It exposes HTTP API for backend notifications and can later run scheduled reminders.

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
BOT_SERVICE_SECRET = os.getenv("BOT_SERVICE_SECRET", "")

app = FastAPI(title="Axelio Bot Service")


class NotifyIn(BaseModel):
    chat_id: int = Field(..., description="Telegram chat id (for private chats equals tg_user_id)")
    text: str = Field(..., min_length=1, max_length=4000)
    url: str | None = Field(None, description="Optional URL to open in WebApp button")
    button_text: str | None = Field(None, description="Button text (default: Открыть в Axelio)")
    parse_mode: str | None = Field(None, description="Optional parse_mode: HTML or MarkdownV2")


def _send_message(
    token: str,
    chat_id: int,
    text: str,
    *,
    url: str | None = None,
    button_text: str | None = None,
    parse_mode: str | None = None,
) -> bool:
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    data_dict = {
        "chat_id": str(chat_id),
        "text": text,
        "disable_web_page_preview": "true",
    }
    if parse_mode:
        data_dict["parse_mode"] = parse_mode

    # If url is provided, attach an inline keyboard with a WebApp button.
    # Telegram will open WebApp inside the client instead of external browser.
    if url:
        bt = button_text or "Открыть в Axelio"
        reply_markup = {"inline_keyboard": [[{"text": bt, "web_app": {"url": url}}]]}
        data_dict["reply_markup"] = json.dumps(reply_markup, ensure_ascii=False)

    data = urllib.parse.urlencode(data_dict).encode("utf-8")
    req = urllib.request.Request(api_url, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=7) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        js = json.loads(body) if body else {}
        return bool(js.get("ok"))


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

    try:
        ok = _send_message(
            TG_BOT_TOKEN,
            payload.chat_id,
            payload.text,
            url=payload.url,
            button_text=payload.button_text,
            parse_mode=payload.parse_mode,
        )
        return {"ok": ok}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"telegram error: {e}")

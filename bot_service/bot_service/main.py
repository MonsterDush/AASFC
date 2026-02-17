from __future__ import annotations

import os
import json
import urllib.request
import urllib.parse
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# Outbound-only bot service (Variant B).
# It exposes HTTP API for backend notifications and (later) can run scheduled reminders.

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
BOT_SERVICE_SECRET = os.getenv("BOT_SERVICE_SECRET", "")

app = FastAPI(title="Axelio Bot Service")


class NotifyIn(BaseModel):
    chat_id: int = Field(..., description="Telegram chat id (for private chats equals tg_user_id)")
    text: str = Field(..., min_length=1, max_length=4000)
    url: str | None = Field(None, description="Optional URL to open in WebApp")
    button_text: str | None = Field(None, max_length=64, description="Button caption")


def _send_message(token: str, chat_id: int, text: str, url: str | None = None, button_text: str | None = None) -> bool:
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload: dict = {
        "chat_id": int(chat_id),
        "text": text,
        "disable_web_page_preview": True,
    }
    if url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{
                "text": button_text or "Открыть в Axelio",
                "web_app": {"url": url},
            }]]
        }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(api_url, data=data, method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=7) as resp:
        body = resp.read().decode("utf-8", errors="ignore")
        js = json.loads(body) if body else {}
        return bool(js.get("ok"))


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/notify")
def notify(payload: NotifyIn, request: Request):
    # Simple shared-secret auth
    got = request.headers.get("X-Bot-Secret", "")
    if BOT_SERVICE_SECRET and got != BOT_SERVICE_SECRET:
        raise HTTPException(status_code=401, detail="bad secret")

    if not TG_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TG_BOT_TOKEN is not configured")

    try:
        ok = _send_message(TG_BOT_TOKEN, payload.chat_id, payload.text, url=payload.url, button_text=payload.button_text)
        return {"ok": ok}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"telegram error: {e}")

def normalize_tg_username(value: str) -> str:
    v = (value or "").strip()
    if v.startswith("@"):
        v = v[1:]
    return v.lower()


def send_telegram_message(*, bot_token: str, chat_id: int, text: str) -> None:
    """Best-effort Telegram notification via HTTP API. No-op on errors."""
    if not bot_token or not chat_id or not text:
        return
    try:
        import json
        import urllib.request
        import urllib.parse

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        return

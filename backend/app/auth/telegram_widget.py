from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any


class TelegramLoginWidgetError(ValueError):
    pass


_ALLOWED_FIELDS = {
    "id",
    "first_name",
    "last_name",
    "username",
    "photo_url",
    "auth_date",
    "hash",
}


def _to_string_map(payload: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (payload or {}).items():
        if key not in _ALLOWED_FIELDS:
            continue
        if value is None:
            continue
        out[str(key)] = str(value)
    return out


def verify_login_widget_data(payload: dict[str, Any], bot_token: str, max_age_seconds: int = 3600) -> dict[str, str]:
    data = _to_string_map(payload)
    received_hash = (data.get("hash") or "").strip()
    if not received_hash:
        raise TelegramLoginWidgetError("hash is missing")

    auth_date_raw = (data.get("auth_date") or "").strip()
    if not auth_date_raw.isdigit():
        raise TelegramLoginWidgetError("auth_date is missing/invalid")
    auth_date = int(auth_date_raw)
    now = int(time.time())
    if max_age_seconds > 0 and now - auth_date > int(max_age_seconds):
        raise TelegramLoginWidgetError("telegram login data expired")

    check_items = [f"{k}={v}" for k, v in sorted(data.items()) if k != "hash"]
    if not check_items:
        raise TelegramLoginWidgetError("telegram login payload is empty")
    data_check_string = "\n".join(check_items)
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise TelegramLoginWidgetError("invalid telegram login signature")
    return data

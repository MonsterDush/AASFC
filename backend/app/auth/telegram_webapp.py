from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any
from urllib.parse import parse_qsl


class TelegramInitDataError(Exception):
    pass


def _hmac_sha256(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def verify_init_data(init_data: str, bot_token: str, max_age_seconds: int = 24 * 3600) -> dict[str, Any]:
    """
    Validates Telegram WebApp initData.
    Returns parsed data dict (strings), including "user" JSON string if present.
    """
    if not init_data:
        raise TelegramInitDataError("initData is empty")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise TelegramInitDataError("hash is missing")

    auth_date_str = pairs.get("auth_date")
    if not auth_date_str or not auth_date_str.isdigit():
        raise TelegramInitDataError("auth_date is missing/invalid")

    auth_date = int(auth_date_str)
    now = int(time.time())
    if now - auth_date > max_age_seconds:
        raise TelegramInitDataError("initData expired")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))

    secret_key = _hmac_sha256(b"WebAppData", bot_token.encode("utf-8"))
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise TelegramInitDataError("hash mismatch")

    return pairs

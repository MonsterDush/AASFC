from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from app.settings import settings


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode((s + pad).encode("ascii"))


def _secret_bytes() -> bytes:
    secret = (settings.EXPORT_LINK_SECRET or "").strip()
    if not secret:
        secret = settings.JWT_SECRET
    return secret.encode("utf-8")


def make_signed_token(payload: dict[str, Any], ttl_seconds: int | None = None) -> str:
    """Create a signed token with exp (unix seconds)."""
    ttl = int(ttl_seconds or settings.EXPORT_LINK_TTL_SECONDS)
    exp = int(time.time()) + max(1, ttl)

    body_obj = dict(payload)
    body_obj["exp"] = exp

    body = json.dumps(body_obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(_secret_bytes(), body, hashlib.sha256).digest()
    return f"{_b64url_encode(body)}.{_b64url_encode(sig)}"


def verify_signed_token(token: str) -> dict[str, Any]:
    """Verify signature and exp; returns payload dict."""
    if not token or "." not in token:
        raise ValueError("bad token")
    body_b64, sig_b64 = token.split(".", 1)
    body = _b64url_decode(body_b64)
    sig = _b64url_decode(sig_b64)

    expected = hmac.new(_secret_bytes(), body, hashlib.sha256).digest()
    if not hmac.compare_digest(expected, sig):
        raise ValueError("bad signature")

    payload = json.loads(body.decode("utf-8"))
    exp = int(payload.get("exp") or 0)
    if exp < int(time.time()):
        raise ValueError("expired")
    return payload

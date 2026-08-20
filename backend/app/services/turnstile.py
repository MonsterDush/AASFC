from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

import requests

from app.core.config import settings


SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
MAX_TOKEN_LENGTH = 2048


@dataclass(frozen=True)
class TurnstileResult:
    success: bool
    reason: str
    error_codes: tuple[str, ...] = ()
    hostname: str = ""
    action: str = ""


def verify_turnstile_token(*, token: str | None, remote_ip: str | None) -> TurnstileResult:
    if not settings.PUBLIC_LEAD_CAPTCHA_REQUIRED:
        return TurnstileResult(success=True, reason="disabled")

    secret = str(settings.TURNSTILE_SECRET_KEY or "").strip()
    normalized_token = str(token or "").strip()
    if not secret:
        return TurnstileResult(success=False, reason="not_configured")
    if not normalized_token:
        return TurnstileResult(success=False, reason="missing_token")
    if len(normalized_token) > MAX_TOKEN_LENGTH:
        return TurnstileResult(success=False, reason="token_too_long")

    try:
        # The request timeout is configured explicitly below.
        response = requests.post(  # nosec B113
            SITEVERIFY_URL,
            data={
                "secret": secret,
                "response": normalized_token,
                "remoteip": str(remote_ip or "").strip(),
                "idempotency_key": str(uuid4()),
            },
            timeout=max(1.0, float(settings.TURNSTILE_TIMEOUT_SECONDS or 5.0)),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError, TypeError):
        return TurnstileResult(success=False, reason="verification_unavailable")

    error_codes = tuple(str(code) for code in (payload.get("error-codes") or []) if code)
    hostname = str(payload.get("hostname") or "").strip().lower().rstrip(".")
    action = str(payload.get("action") or "").strip()
    if payload.get("success") is not True:
        return TurnstileResult(
            success=False,
            reason="challenge_failed",
            error_codes=error_codes,
            hostname=hostname,
            action=action,
        )

    expected_action = str(settings.TURNSTILE_EXPECTED_ACTION or "").strip()
    if expected_action and action != expected_action:
        return TurnstileResult(success=False, reason="action_mismatch", hostname=hostname, action=action)

    allowed_hostnames = settings.turnstile_allowed_hostnames()
    if allowed_hostnames and hostname not in allowed_hostnames:
        return TurnstileResult(success=False, reason="hostname_mismatch", hostname=hostname, action=action)

    return TurnstileResult(success=True, reason="verified", hostname=hostname, action=action)

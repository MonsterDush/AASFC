from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timezone

from fastapi import HTTPException

from app.models import User
from app.settings import settings

PBKDF2_ALGORITHM = "pbkdf2_sha256"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_new_password(password: str) -> str:
    value = str(password or "")
    min_length = max(8, int(settings.PASSWORD_MIN_LENGTH or 8))
    if len(value) < min_length:
        raise HTTPException(status_code=400, detail=f"Пароль должен быть не короче {min_length} символов")
    if not any(ch.isalpha() for ch in value):
        raise HTTPException(status_code=400, detail="Пароль должен содержать хотя бы одну букву")
    if not any(ch.isdigit() for ch in value):
        raise HTTPException(status_code=400, detail="Пароль должен содержать хотя бы одну цифру")
    return value


def _iterations() -> int:
    return max(120_000, int(settings.PASSWORD_PBKDF2_ITERATIONS or 260_000))


def hash_password(password: str) -> str:
    raw = validate_new_password(password).encode("utf-8")
    iterations = _iterations()
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", raw, salt, iterations)
    return "$".join(
        [
            PBKDF2_ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, encoded_hash: str | None) -> bool:
    if not encoded_hash:
        return False
    try:
        algorithm, iterations_raw, salt_b64, digest_b64 = encoded_hash.split("$", 3)
        if algorithm != PBKDF2_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected = base64.b64decode(digest_b64.encode("ascii"))
    except Exception:
        return False

    actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def has_password(user: User) -> bool:
    return bool((user.password_hash or "").strip())


def set_password(user: User, new_password: str, *, is_reset: bool = False) -> None:
    now = utcnow()
    user.password_hash = hash_password(new_password)
    if user.password_set_at is None:
        user.password_set_at = now
    user.password_changed_at = now
    # invalidate all older cookies / sessions; current session must receive a fresh JWT
    user.session_version = int(user.session_version or 0) + 1

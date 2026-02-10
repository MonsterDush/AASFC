from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt  # PyJWT


@dataclass(frozen=True)
class JwtConfig:
    secret: str
    issuer: str
    audience: str
    ttl_seconds: int


def create_access_token(cfg: JwtConfig, user_id: int) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + cfg.ttl_seconds,
        "iss": cfg.issuer,
        "aud": cfg.audience,
        "typ": "access",
    }
    return jwt.encode(payload, cfg.secret, algorithm="HS256")


def decode_access_token(cfg: JwtConfig, token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        cfg.secret,
        algorithms=["HS256"],
        issuer=cfg.issuer,
        audience=cfg.audience,
        options={"require": ["exp", "iat", "iss", "aud", "sub"]},
    )

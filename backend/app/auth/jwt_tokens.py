from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import jwt  # PyJWT


RESERVED_ACCESS_CLAIMS = {"sub", "sv", "iat", "exp", "iss", "aud", "typ"}


@dataclass(frozen=True)
class JwtConfig:
    secret: str
    issuer: str
    audience: str
    ttl_seconds: int


def create_access_token(
    cfg: JwtConfig,
    user_id: int,
    *,
    session_version: int = 0,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "sv": int(session_version or 0),
        "iat": now,
        "exp": now + cfg.ttl_seconds,
        "iss": cfg.issuer,
        "aud": cfg.audience,
        "typ": "access",
    }
    if extra_claims:
        conflicts = RESERVED_ACCESS_CLAIMS.intersection(extra_claims)
        if conflicts:
            names = ", ".join(sorted(conflicts))
            raise ValueError(f"extra_claims cannot override reserved access claims: {names}")
        payload.update(extra_claims)
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

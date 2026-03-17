from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.jwt_tokens import JwtConfig, decode_access_token
from app.core.db import get_db
from app.models import User
from app.settings import settings


def get_jwt_config() -> JwtConfig:
    return JwtConfig(
        secret=settings.JWT_SECRET,
        issuer=settings.JWT_ISS,
        audience=settings.JWT_AUD,
        ttl_seconds=settings.ACCESS_TOKEN_TTL_SECONDS,
    )


def _decode_user_from_cookie(db: Session, access_token: str | None) -> User | None:
    if not access_token:
        return None
    try:
        payload = decode_access_token(get_jwt_config(), access_token)
        user_id = int(payload["sub"])
        token_session_version = int(payload.get("sv", 0) or 0)
    except Exception:
        return None

    user = db.query(User).filter(User.id == user_id).one_or_none()
    if not user:
        return None
    if token_session_version != int(user.session_version or 0):
        return None
    return user


def get_current_user(
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(default=None, alias="access_token"),
) -> User:
    user = _decode_user_from_cookie(db, access_token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user


def get_current_user_optional(
    db: Session = Depends(get_db),
    access_token: str | None = Cookie(default=None, alias="access_token"),
) -> User | None:
    """Same as get_current_user, but returns None instead of raising."""
    return _decode_user_from_cookie(db, access_token)

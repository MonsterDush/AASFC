from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy.orm import Session

from app.auth.jwt_tokens import JwtConfig, create_access_token
from app.auth.telegram_webapp import TelegramInitDataError, verify_init_data
from app.core.db import get_db
from app.models import User
from app.settings import settings
from app.core.tg import normalize_tg_username
from app.services.invites import accept_invites_for_user



router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramAuthIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    initData: str = Field(alias="init_data")


@router.post("/telegram", status_code=status.HTTP_204_NO_CONTENT)
def auth_telegram(payload: TelegramAuthIn, response: Response, db: Session = Depends(get_db)):
    try:
        data = verify_init_data(payload.initData, settings.TG_BOT_TOKEN)
    except TelegramInitDataError as e:
        raise HTTPException(status_code=401, detail=str(e))

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status_code=400, detail="user is missing in initData")

    try:
        tg_user = json.loads(user_raw)
        tg_user_id = int(tg_user["id"])
        tg_username = tg_user.get("username")
        tg_username = normalize_tg_username(tg_username)
        first_name = (tg_user.get("first_name") or "").strip()
        last_name = (tg_user.get("last_name") or "").strip()
        # дефолты профиля (пользователь потом сможет отредактировать в Настройках)
        default_full_name = " ".join([p for p in [last_name, first_name] if p]) or None
        default_short_name = first_name or (tg_username.lstrip("@") if tg_username else None)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid user payload")

    # upsert user
# 1) ищем пользователя
    user = db.query(User).filter(User.tg_user_id == tg_user_id).one_or_none()

    # 2) если нет — создаём
    if user is None:
        user = User(
            tg_user_id=tg_user_id,
            tg_username=tg_username,
            full_name=default_full_name,
            short_name=default_short_name,
            system_role="NONE",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # если есть — обновим username (не обязательно, но полезно)
        if tg_username and user.tg_username != tg_username:
            user.tg_username = tg_username
            db.commit()
        # заполним профиль дефолтами, если ещё не заполнен
        changed = False
        if user.full_name is None and default_full_name:
            user.full_name = default_full_name
            changed = True
        if user.short_name is None and default_short_name:
            user.short_name = default_short_name
            changed = True
        if changed:
            db.commit()

    # 3) DEV: авто-SUPER_ADMIN по whitelist (если ты это добавлял)
    if tg_user_id in settings.super_admin_ids():
        if user.system_role != "SUPER_ADMIN":
            user.system_role = "SUPER_ADMIN"
            db.commit()

    if user is None:
        user = User(tg_user_id=tg_user_id, tg_username=tg_username, full_name=default_full_name, short_name=default_short_name, system_role="NONE")
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if tg_username and user.tg_username != tg_username:
            user.tg_username = tg_username
            db.commit()
        # заполним профиль дефолтами, если ещё не заполнен
        changed = False
        if user.full_name is None and default_full_name:
            user.full_name = default_full_name
            changed = True
        if user.short_name is None and default_short_name:
            user.short_name = default_short_name
            changed = True
        if changed:
            db.commit()

    accept_invites_for_user(db, user_id=user.id, tg_username=user.tg_username)

    jwt_cfg = JwtConfig(
        secret=settings.JWT_SECRET,
        issuer=settings.JWT_ISS,
        audience=settings.JWT_AUD,
        ttl_seconds=settings.ACCESS_TOKEN_TTL_SECONDS,
    )
    token = create_access_token(jwt_cfg, user.id)

    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        domain=settings.COOKIE_DOMAIN,
        path="/",
        max_age=settings.ACCESS_TOKEN_TTL_SECONDS,
    )
    return

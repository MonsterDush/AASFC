from __future__ import annotations

import json
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.jwt_tokens import JwtConfig, create_access_token
from app.auth.telegram_webapp import TelegramInitDataError, verify_init_data
from app.core.db import get_db
from app.models import User
from app.settings import settings

router = APIRouter(prefix="/auth", tags=["auth"])


class TelegramAuthIn(BaseModel):
    initData: str


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

    # 3) DEV: авто-SUPER_ADMIN по whitelist (если ты это добавлял)
    if tg_user_id in settings.super_admin_ids():
        if user.system_role != "SUPER_ADMIN":
            user.system_role = "SUPER_ADMIN"
            db.commit()

    if user is None:
        user = User(tg_user_id=tg_user_id, tg_username=tg_username, system_role="NONE")
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if tg_username and user.tg_username != tg_username:
            user.tg_username = tg_username
            db.commit()

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

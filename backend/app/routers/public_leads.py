from __future__ import annotations

import html
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.request_ip import resolve_client_ip
from app.models.user import User
from app.services import tg_notify
from app.services.security_rate_limits import RateLimitPolicy, consume_rate_limit

router = APIRouter(prefix="/public/leads", tags=["public-leads"])


class PublicLeadIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    phone: str = Field(..., min_length=5, max_length=64)
    venue: str | None = Field(default=None, max_length=160)
    message: str | None = Field(default=None, max_length=2000)
    source: str | None = Field(default=None, max_length=120)
    page: str | None = Field(default=None, max_length=500)
    userAgent: str | None = Field(default=None, max_length=500)
    submittedAt: str | None = Field(default=None, max_length=64)
    publicSiteKey: str | None = Field(default=None, max_length=120)

    @field_validator("name", "phone", "venue", "message", "source", "page", "userAgent", "submittedAt", "publicSiteKey", mode="before")
    @classmethod
    def _strip_values(cls, value):
        if value is None:
            return None
        return str(value).strip()



def _mask_key(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if len(raw) <= 6:
        return "*" * len(raw)
    return raw[:3] + "***" + raw[-2:]



def _collect_super_admin_chat_ids(db: Session) -> list[int]:
    ids = set(int(x) for x in settings.super_admin_ids())
    rows = (
        db.query(User.tg_user_id)
        .filter(User.system_role == "SUPER_ADMIN")
        .filter(User.tg_user_id.is_not(None))
        .all()
    )
    for (tg_user_id,) in rows:
        if tg_user_id:
            ids.add(int(tg_user_id))
    return sorted(ids)



def _format_lead_message(payload: PublicLeadIn, request: Request) -> str:
    submitted = payload.submittedAt or datetime.now(timezone.utc).isoformat()
    host = request.headers.get("host") or request.url.hostname or "axelio.ru"
    parts = [
        "<b>Новая заявка с сайта Axelio</b>",
        "",
        f"<b>Имя:</b> {html.escape(payload.name)}",
        f"<b>Телефон:</b> {html.escape(payload.phone)}",
    ]
    if payload.venue:
        parts.append(f"<b>Заведение:</b> {html.escape(payload.venue)}")
    if payload.message:
        parts.append(f"<b>Комментарий:</b> {html.escape(payload.message)}")
    parts.extend(
        [
            "",
            f"<b>Источник:</b> {html.escape(payload.source or host)}",
            f"<b>Страница:</b> {html.escape(payload.page or str(request.url))}",
            f"<b>Время:</b> {html.escape(submitted)}",
        ]
    )
    return "\n".join(parts)


@router.post("")
def create_public_lead(payload: PublicLeadIn, request: Request, db: Session = Depends(get_db)):
    decision = consume_rate_limit(
        db,
        scope="public-lead-ip",
        subject=resolve_client_ip(request),
        policy=RateLimitPolicy(
            limit=int(settings.PUBLIC_LEAD_IP_LIMIT or 5),
            window_seconds=int(settings.PUBLIC_LEAD_RATE_WINDOW_SECONDS or 3600),
            block_seconds=int(settings.PUBLIC_LEAD_BLOCK_SECONDS or 3600),
        ),
    )
    if not decision.allowed:
        db.commit()
        raise HTTPException(
            status_code=429,
            detail="Слишком много заявок. Попробуйте позже.",
            headers={"Retry-After": str(max(1, decision.retry_after_seconds))},
        )

    expected_key = str(settings.PUBLIC_LEAD_SITE_KEY or "").strip()
    if expected_key and payload.publicSiteKey != expected_key:
        db.commit()
        raise HTTPException(status_code=401, detail="bad public site key")

    chat_ids = _collect_super_admin_chat_ids(db)
    db.commit()

    if not chat_ids:
        raise HTTPException(status_code=503, detail="No super admin Telegram recipients configured")

    text = _format_lead_message(payload, request)
    open_url = settings.frontend_base_url() or "https://app.axelio.ru"

    sent = 0
    last_error = None
    for chat_id in chat_ids:
        result = tg_notify.notify_result(
            chat_id=chat_id,
            text=text,
            url=open_url,
            button_text="Открыть Axelio",
            parse_mode="HTML",
        )
        if result.get("ok"):
            sent += 1
        else:
            last_error = result.get("error") or last_error

    if sent <= 0:
        raise HTTPException(status_code=502, detail=last_error or "Failed to deliver lead notification")

    return {
        "ok": True,
        "sent": sent,
        "recipients": len(chat_ids),
        "siteKey": _mask_key(payload.publicSiteKey),
    }

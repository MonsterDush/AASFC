from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user
from app.core.db import get_db
from app.models import User
from app.services.demo.access import get_demo_session_or_none
from app.services.demo.analytics import record_demo_event

router = APIRouter(prefix="/demo", tags=["demo-telemetry"])


class DemoEventIn(BaseModel):
    event_name: str = Field(..., min_length=1, max_length=64)
    page_path: str | None = Field(default=None, max_length=255)
    cta_code: str | None = Field(default=None, max_length=64)
    meta: dict | None = None


@router.post("/event")
def create_demo_event(
    payload: DemoEventIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    demo_ctx = get_demo_session_or_none(user)
    if demo_ctx is None:
        raise HTTPException(status_code=403, detail="DEMO-сессия не активна")
    event = record_demo_event(
        db,
        event_name=payload.event_name,
        user=user,
        page_path=payload.page_path,
        cta_code=payload.cta_code,
        meta=payload.meta,
    )
    db.commit()
    return {
        "ok": True,
        "event_id": int(event.id) if event is not None else None,
    }

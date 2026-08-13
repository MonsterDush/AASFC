from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models.shift_interval import ShiftInterval
from app.models.shift import Shift
from app.models.shift_schedule_template import ShiftScheduleTemplate, ShiftScheduleTemplateItem


def _normalize_shift_interval_title(title: str) -> str:
    value = str(title or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="Interval title is required")
    return value


def _ensure_shift_interval_title_unique(
    db: Session,
    *,
    venue_id: int,
    title: str,
    exclude_interval_id: int | None = None,
) -> None:
    stmt = select(ShiftInterval.id).where(
        ShiftInterval.venue_id == venue_id,
        func.lower(ShiftInterval.title) == title.lower(),
    )
    if exclude_interval_id is not None:
        stmt = stmt.where(ShiftInterval.id != exclude_interval_id)
    exists_id = db.execute(stmt.limit(1)).scalar_one_or_none()
    if exists_id is not None:
        raise HTTPException(status_code=409, detail="Shift interval with this title already exists")


def _count_interval_shift_usage(db: Session, *, venue_id: int, interval_id: int) -> int:
    return int(
        db.execute(
            select(func.count(Shift.id)).where(
                Shift.venue_id == venue_id,
                Shift.interval_id == interval_id,
            )
        ).scalar_one()
        or 0
    )


def _count_interval_template_usage(db: Session, *, venue_id: int, interval_id: int) -> int:
    return int(
        db.execute(
            select(func.count(ShiftScheduleTemplateItem.id))
            .join(ShiftScheduleTemplate, ShiftScheduleTemplate.id == ShiftScheduleTemplateItem.template_id)
            .where(
                ShiftScheduleTemplate.venue_id == venue_id,
                ShiftScheduleTemplateItem.interval_id == interval_id,
            )
        ).scalar_one()
        or 0
    )


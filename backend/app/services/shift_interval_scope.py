"""Position restrictions for new assignments; existing assignments are never mutated here."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.shift_interval import ShiftInterval, ShiftIntervalPosition
from app.models.venue_position import VenuePosition


def interval_scope_payloads(db: Session, *, venue_id: int, intervals: list[ShiftInterval]) -> dict[int, dict]:
    if not intervals:
        return {}
    ids_by_interval = {int(row.id): set() for row in intervals}
    for row in intervals:
        if row.position_id is not None:
            ids_by_interval[int(row.id)].add(int(row.position_id))
    for interval_id, position_id in db.execute(
        select(ShiftIntervalPosition.interval_id, ShiftIntervalPosition.position_id).where(
            ShiftIntervalPosition.interval_id.in_(ids_by_interval)
        )
    ).all():
        ids_by_interval[int(interval_id)].add(int(position_id))
    position_ids = {position_id for ids in ids_by_interval.values() for position_id in ids}
    titles = (
        dict(
            db.execute(
                select(VenuePosition.id, VenuePosition.title).where(
                    VenuePosition.venue_id == venue_id, VenuePosition.id.in_(position_ids)
                )
            ).all()
        )
        if position_ids
        else {}
    )
    return {
        interval_id: {
            "position_ids": sorted(ids),
            "position_titles": [titles.get(position_id, "Должность") for position_id in sorted(ids)],
        }
        for interval_id, ids in ids_by_interval.items()
    }


def set_interval_positions(db: Session, *, interval: ShiftInterval, position_ids: list[int]) -> None:
    ids = sorted(set(position_ids))
    # Keep the first allowed role readable by older clients while retaining all roles in the association.
    interval.position_id = ids[0] if ids else None
    db.flush()
    db.execute(delete(ShiftIntervalPosition).where(ShiftIntervalPosition.interval_id == interval.id))
    db.add_all([ShiftIntervalPosition(interval_id=interval.id, position_id=position_id) for position_id in ids])


def require_interval_position_match(
    db: Session, *, venue_id: int, interval: ShiftInterval, position: VenuePosition
) -> None:
    scope = interval_scope_payloads(db, venue_id=venue_id, intervals=[interval])[int(interval.id)]
    if not scope["position_ids"]:
        return
    if position.catalog_position_id not in scope["position_ids"]:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SHIFT_INTERVAL_POSITION_MISMATCH",
                "message": "Должность не подходит для интервала этой смены",
            },
        )

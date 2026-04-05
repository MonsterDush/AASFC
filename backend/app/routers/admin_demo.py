from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.models import User, Venue, VenueMember
from app.services.demo.fixture import export_demo_fixture, get_demo_fixture_status, reset_demo_fixture

router = APIRouter(prefix='/admin/demo', tags=['admin-demo'])


class DemoExportIn(BaseModel):
    venue_id: int | None = Field(default=None, ge=1)
    fixture_path: str | None = Field(default=None, max_length=500)


class DemoResetIn(BaseModel):
    venue_id: int | None = Field(default=None, ge=1)
    fixture_path: str | None = Field(default=None, max_length=500)


class DemoEnableIn(BaseModel):
    venue_id: int = Field(..., ge=1)
    reference_year: int | None = Field(default=None, ge=2020, le=2100)
    reference_month: int | None = Field(default=None, ge=1, le=12)


class DemoDisableIn(BaseModel):
    venue_id: int | None = Field(default=None, ge=1)


@router.get('/status')
def admin_demo_status(
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    return get_demo_fixture_status(db)


@router.post('/export-fixture')
def admin_demo_export_fixture(
    payload: DemoExportIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    status = get_demo_fixture_status(db)
    target_venue_id = int(payload.venue_id or ((status.get('venue') or {}).get('id') or 0))
    if not target_venue_id:
        raise HTTPException(status_code=400, detail='Сначала укажи venue_id или активируй публичное DEMO-заведение')
    result = export_demo_fixture(db, venue_id=target_venue_id, fixture_path=payload.fixture_path)
    db.commit()
    return {
        'ok': True,
        'fixture_path': result.fixture_path,
        'venue_id': result.venue_id,
        'venue_name': result.venue_name,
        'counts': result.counts,
        'warnings': result.warnings,
    }


@router.post('/reset')
def admin_demo_reset_fixture(
    payload: DemoResetIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    try:
        result = reset_demo_fixture(db, fixture_path=payload.fixture_path, venue_id=payload.venue_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {
        'ok': True,
        'fixture_path': result.fixture_path,
        'venue_id': result.venue_id,
        'venue_name': result.venue_name,
        'counts': result.counts,
        'warnings': result.warnings,
    }


@router.post('/enable')
def admin_demo_enable(
    payload: DemoEnableIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    venue = db.execute(select(Venue).where(Venue.id == int(payload.venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail='Venue not found')

    db.execute(update(Venue).values(is_demo=False))
    venue.is_demo = True
    if payload.reference_year is not None:
        venue.demo_reference_year = int(payload.reference_year)
    if payload.reference_month is not None:
        venue.demo_reference_month = int(payload.reference_month)

    member_rows = db.execute(
        select(VenueMember.user_id, User.demo_persona)
        .join(User, User.id == VenueMember.user_id)
        .where(VenueMember.venue_id == int(venue.id), User.is_demo_user.is_(True), VenueMember.is_active.is_(True))
    ).all()
    personas = {str(row.demo_persona or '').upper() for row in member_rows}
    db.commit()
    return {
        'ok': True,
        'venue_id': int(venue.id),
        'venue_name': venue.name,
        'is_demo': bool(venue.is_demo),
        'demo_reference_year': venue.demo_reference_year,
        'demo_reference_month': venue.demo_reference_month,
        'personas': {
            'OWNER': 'OWNER' in personas,
            'STAFF': 'STAFF' in personas,
        },
    }


@router.post('/disable')
def admin_demo_disable(
    payload: DemoDisableIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    stmt = update(Venue).values(is_demo=False)
    if payload.venue_id is not None:
        stmt = stmt.where(Venue.id == int(payload.venue_id))
    else:
        stmt = stmt.where(Venue.is_demo.is_(True))
    result = db.execute(stmt)
    db.commit()
    return {
        'ok': True,
        'disabled_count': int(result.rowcount or 0),
    }

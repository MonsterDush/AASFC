from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.models import User, Venue, VenueMember
from app.services.demo.analytics import get_demo_analytics_summary
from app.services.demo.bootstrap import bootstrap_demo_venue
from app.services.demo.fixture import export_demo_fixture, get_demo_fixture_status, reset_demo_fixture
from app.services.demo.session import (
    DEMO_KIND_PUBLIC,
    DEMO_KIND_TEMPLATE,
    build_demo_auth_start_url,
    build_demo_start_url,
    get_demo_template_venue,
)

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


class DemoBootstrapIn(BaseModel):
    venue_id: int | None = Field(default=None, ge=1)
    venue_name: str | None = Field(default=None, max_length=200)
    reference_year: int | None = Field(default=None, ge=2020, le=2100)
    reference_month: int | None = Field(default=None, ge=1, le=12)
    make_public: bool = True
    export_fixture_after: bool = True
    fixture_path: str | None = Field(default=None, max_length=500)


class DemoPublishTemplateIn(BaseModel):
    venue_id: int | None = Field(default=None, ge=1)


def _demo_personas_for_venue(db: Session, venue_id: int) -> dict[str, bool]:
    member_rows = db.execute(
        select(VenueMember.user_id, User.demo_persona)
        .join(User, User.id == VenueMember.user_id)
        .where(VenueMember.venue_id == int(venue_id), User.is_demo_user.is_(True), VenueMember.is_active.is_(True))
    ).all()
    personas = {str(row.demo_persona or '').upper() for row in member_rows}
    return {'OWNER': 'OWNER' in personas, 'STAFF': 'STAFF' in personas}


@router.get('/status')
def admin_demo_status(db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    status = get_demo_fixture_status(db)
    venue = status.get('venue') or {}
    venue_id = int(venue.get('id') or 0) if venue else 0
    template_venue = get_demo_template_venue(db)
    analytics = get_demo_analytics_summary(db)
    if venue_id:
        status['preview_urls'] = {
            'owner': build_demo_auth_start_url(persona='OWNER'),
            'staff': build_demo_auth_start_url(persona='STAFF'),
            'owner_summary': build_demo_auth_start_url(persona='OWNER', next_path='/owner-summary.html'),
            'owner_expenses': build_demo_auth_start_url(persona='OWNER', next_path='/owner-expenses.html'),
            'owner_payroll': build_demo_auth_start_url(persona='OWNER', next_path='/owner-payroll.html'),
            'owner_revenue': build_demo_auth_start_url(persona='OWNER', next_path='/owner-turnover.html'),
            'owner_ledger': build_demo_auth_start_url(persona='OWNER', next_path='/owner-finance-ledger.html'),
            'owner_day_economics': build_demo_auth_start_url(persona='OWNER', next_path='/owner-day-economics.html'),
            'staff_shifts': build_demo_auth_start_url(persona='STAFF', next_path='/staff-shifts.html'),
            'staff_salary': build_demo_auth_start_url(persona='STAFF', next_path='/staff-salary.html'),
        }
        status['open_urls'] = {
            'owner_summary': build_demo_start_url(venue_id=venue_id, persona='OWNER', next_path='/owner-summary.html'),
            'staff_shifts': build_demo_start_url(venue_id=venue_id, persona='STAFF', next_path='/staff-shifts.html'),
        }
    status['template_venue'] = {
        'id': int(template_venue.id),
        'name': template_venue.name,
        'demo_kind': getattr(template_venue, 'demo_kind', None),
        'demo_reference_year': getattr(template_venue, 'demo_reference_year', None),
        'demo_reference_month': getattr(template_venue, 'demo_reference_month', None),
        'personas': _demo_personas_for_venue(db, int(template_venue.id)),
    } if template_venue else None
    status['analytics'] = analytics
    return status


@router.post('/export-fixture')
def admin_demo_export_fixture(payload: DemoExportIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    status = get_demo_fixture_status(db)
    target_venue_id = int(payload.venue_id or ((status.get('venue') or {}).get('id') or 0))
    if not target_venue_id:
        template_venue = get_demo_template_venue(db)
        target_venue_id = int(template_venue.id) if template_venue else 0
    if not target_venue_id:
        raise HTTPException(status_code=400, detail='Сначала укажи venue_id или настрой DEMO venue')
    result = export_demo_fixture(db, venue_id=target_venue_id, fixture_path=payload.fixture_path)
    db.commit()
    return {'ok': True, 'fixture_path': result.fixture_path, 'venue_id': result.venue_id, 'venue_name': result.venue_name, 'counts': result.counts, 'warnings': result.warnings}


@router.post('/reset')
def admin_demo_reset_fixture(payload: DemoResetIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    try:
        result = reset_demo_fixture(db, fixture_path=payload.fixture_path, venue_id=payload.venue_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {'ok': True, 'fixture_path': result.fixture_path, 'venue_id': result.venue_id, 'venue_name': result.venue_name, 'counts': result.counts, 'warnings': result.warnings}


@router.post('/enable')
def admin_demo_enable(payload: DemoEnableIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    venue = db.execute(select(Venue).where(Venue.id == int(payload.venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail='Venue not found')
    db.execute(update(Venue).values(is_demo=False))
    db.execute(update(Venue).where(Venue.id != int(venue.id)).values(demo_kind=None))
    venue.is_demo = True
    venue.demo_kind = DEMO_KIND_PUBLIC
    if payload.reference_year is not None:
        venue.demo_reference_year = int(payload.reference_year)
    if payload.reference_month is not None:
        venue.demo_reference_month = int(payload.reference_month)
    db.commit()
    return {'ok': True, 'venue_id': int(venue.id), 'venue_name': venue.name, 'is_demo': bool(venue.is_demo), 'demo_kind': venue.demo_kind, 'demo_reference_year': venue.demo_reference_year, 'demo_reference_month': venue.demo_reference_month, 'personas': _demo_personas_for_venue(db, int(venue.id))}


@router.post('/publish-template')
def admin_demo_publish_template(payload: DemoPublishTemplateIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    venue = db.execute(select(Venue).where(Venue.id == int(payload.venue_id))).scalar_one_or_none() if payload.venue_id else get_demo_template_venue(db)
    if venue is None:
        raise HTTPException(status_code=404, detail='DEMO template venue not found')
    db.execute(update(Venue).where(Venue.is_demo.is_(True), Venue.id != int(venue.id)).values(is_demo=False, demo_kind=DEMO_KIND_TEMPLATE))
    venue.is_demo = True
    venue.demo_kind = DEMO_KIND_PUBLIC
    db.commit()
    return {'ok': True, 'venue_id': int(venue.id), 'venue_name': venue.name, 'demo_kind': venue.demo_kind, 'personas': _demo_personas_for_venue(db, int(venue.id))}


@router.post('/disable')
def admin_demo_disable(payload: DemoDisableIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    stmt = update(Venue).values(is_demo=False, demo_kind=None)
    if payload.venue_id is not None:
        stmt = stmt.where(Venue.id == int(payload.venue_id))
    else:
        stmt = stmt.where(Venue.is_demo.is_(True))
    result = db.execute(stmt)
    db.commit()
    return {'ok': True, 'disabled_count': int(result.rowcount or 0)}


@router.post('/bootstrap')
def admin_demo_bootstrap(payload: DemoBootstrapIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    try:
        result = bootstrap_demo_venue(
            db,
            venue_id=payload.venue_id,
            venue_name=str(payload.venue_name or '').strip() or 'Axelio DEMO · Hookah Lounge',
            reference_year=int(payload.reference_year or 2026),
            reference_month=int(payload.reference_month or 3),
            make_public=bool(payload.make_public),
            export_fixture_after=bool(payload.export_fixture_after),
            export_fixture_path=payload.fixture_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {'ok': True, 'venue_id': result.venue_id, 'venue_name': result.venue_name, 'reference_year': result.reference_year, 'reference_month': result.reference_month, 'fixture_path': result.fixture_path, 'counts': result.counts, 'warnings': result.warnings}

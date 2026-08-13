from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.guards import require_super_admin
from app.core.db import get_db
from app.models import User, Venue, VenueMember
from app.services.demo.analytics import get_demo_analytics_dashboard, get_demo_analytics_summary
from app.services.demo.bootstrap import bootstrap_demo_venue
from app.services.demo.fixture import export_demo_fixture, get_demo_fixture_status, reset_demo_fixture
from app.services.demo.session import (
    DEMO_KIND_PUBLIC,
    DEMO_KIND_TEMPLATE,
    build_demo_auth_start_url,
    build_frontend_route_url,
    get_demo_template_venue,
    get_public_demo_venue,
)

router = APIRouter(prefix="/admin/demo", tags=["admin-demo"])


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
    history_months: int = Field(default=1, ge=1, le=24)
    make_public: bool = True
    export_fixture_after: bool = True
    fixture_path: str | None = Field(default=None, max_length=500)


class DemoPublishTemplateIn(BaseModel):
    venue_id: int | None = Field(default=None, ge=1)


class DemoEnsureTemplateIn(BaseModel):
    venue_name: str | None = Field(default=None, max_length=200)
    reference_year: int | None = Field(default=None, ge=2020, le=2100)
    reference_month: int | None = Field(default=None, ge=1, le=12)


def _demo_personas_for_venue(db: Session, venue_id: int) -> dict[str, bool]:
    member_rows = db.execute(
        select(VenueMember.user_id, User.demo_persona)
        .join(User, User.id == VenueMember.user_id)
        .where(VenueMember.venue_id == int(venue_id), User.is_demo_user.is_(True), VenueMember.is_active.is_(True))
    ).all()
    personas = {str(row.demo_persona or "").upper() for row in member_rows}
    return {"OWNER": "OWNER" in personas, "STAFF": "STAFF" in personas}


def _venue_status_payload(db: Session, venue: Venue | None) -> dict | None:
    if venue is None:
        return None
    return {
        "id": int(venue.id),
        "name": venue.name,
        "demo_kind": getattr(venue, "demo_kind", None),
        "is_demo": bool(getattr(venue, "is_demo", False)),
        "demo_reference_year": getattr(venue, "demo_reference_year", None),
        "demo_reference_month": getattr(venue, "demo_reference_month", None),
        "personas": _demo_personas_for_venue(db, int(venue.id)),
        "open_urls": {
            "venue": build_frontend_route_url(venue_id=int(venue.id), path="/app-venue.html"),
            "summary": build_frontend_route_url(venue_id=int(venue.id), path="/owner-summary.html"),
            "expenses": build_frontend_route_url(venue_id=int(venue.id), path="/owner-expenses.html"),
            "payroll": build_frontend_route_url(venue_id=int(venue.id), path="/owner-payroll.html"),
            "staff_shifts": build_frontend_route_url(venue_id=int(venue.id), path="/staff-shifts.html"),
        },
    }


@router.get("/status")
def admin_demo_status(db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    status = get_demo_fixture_status(db)
    public_venue = get_public_demo_venue(db)
    template_venue = get_demo_template_venue(db)
    public_venue_id = int(public_venue.id) if public_venue is not None else 0
    analytics = get_demo_analytics_summary(db)
    if public_venue_id:
        status["preview_urls"] = {
            "owner": build_demo_auth_start_url(persona="OWNER"),
            "staff": build_demo_auth_start_url(persona="STAFF"),
            "owner_summary": build_demo_auth_start_url(persona="OWNER", next_path="/owner-summary.html"),
            "owner_expenses": build_demo_auth_start_url(persona="OWNER", next_path="/owner-expenses.html"),
            "owner_payroll": build_demo_auth_start_url(persona="OWNER", next_path="/owner-payroll.html"),
            "owner_revenue": build_demo_auth_start_url(persona="OWNER", next_path="/owner-turnover.html"),
            "owner_ledger": build_demo_auth_start_url(persona="OWNER", next_path="/owner-finance-ledger.html"),
            "owner_day_economics": build_demo_auth_start_url(persona="OWNER", next_path="/owner-day-economics.html"),
            "staff_shifts": build_demo_auth_start_url(persona="STAFF", next_path="/staff-shifts.html"),
            "staff_salary": build_demo_auth_start_url(persona="STAFF", next_path="/staff-salary.html"),
        }
    status["public_venue"] = _venue_status_payload(db, public_venue)
    status["template_venue"] = _venue_status_payload(db, template_venue)
    status["analytics"] = analytics
    return status


@router.get("/analytics")
def admin_demo_analytics(
    range_type: str = Query(default="month", alias="range"),
    year: int | None = Query(default=None, ge=2020, le=2100),
    month: int | None = Query(default=None, ge=1, le=12),
    quarter: int | None = Query(default=None, ge=1, le=4),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(require_super_admin),
):
    return get_demo_analytics_dashboard(
        db,
        range_type=range_type,
        year=year,
        month=month,
        quarter=quarter,
        date_from=date_from,
        date_to=date_to,
    )


@router.post("/export-fixture")
def admin_demo_export_fixture(
    payload: DemoExportIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    status = get_demo_fixture_status(db)
    target_venue_id = int(payload.venue_id or ((status.get("venue") or {}).get("id") or 0))
    if not target_venue_id:
        template_venue = get_demo_template_venue(db)
        target_venue_id = int(template_venue.id) if template_venue else 0
    if not target_venue_id:
        raise HTTPException(status_code=400, detail="Сначала укажи venue_id или настрой DEMO venue")
    result = export_demo_fixture(db, venue_id=target_venue_id, fixture_path=payload.fixture_path)
    db.commit()
    return {
        "ok": True,
        "fixture_path": result.fixture_path,
        "venue_id": result.venue_id,
        "venue_name": result.venue_name,
        "counts": result.counts,
        "warnings": result.warnings,
    }


@router.post("/reset")
def admin_demo_reset_fixture(
    payload: DemoResetIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    try:
        result = reset_demo_fixture(db, fixture_path=payload.fixture_path, venue_id=payload.venue_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {
        "ok": True,
        "fixture_path": result.fixture_path,
        "venue_id": result.venue_id,
        "venue_name": result.venue_name,
        "counts": result.counts,
        "warnings": result.warnings,
    }


@router.post("/enable")
def admin_demo_enable(payload: DemoEnableIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)):
    venue = db.execute(select(Venue).where(Venue.id == int(payload.venue_id))).scalar_one_or_none()
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    db.execute(update(Venue).values(is_demo=False))
    db.execute(update(Venue).where(Venue.id != int(venue.id)).values(demo_kind=None))
    venue.is_demo = True
    venue.demo_kind = DEMO_KIND_PUBLIC
    if payload.reference_year is not None:
        venue.demo_reference_year = int(payload.reference_year)
    if payload.reference_month is not None:
        venue.demo_reference_month = int(payload.reference_month)
    db.commit()
    return {
        "ok": True,
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "is_demo": bool(venue.is_demo),
        "demo_kind": venue.demo_kind,
        "demo_reference_year": venue.demo_reference_year,
        "demo_reference_month": venue.demo_reference_month,
        "personas": _demo_personas_for_venue(db, int(venue.id)),
    }


@router.post("/publish-template")
def admin_demo_publish_template(
    payload: DemoPublishTemplateIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    venue = (
        db.execute(select(Venue).where(Venue.id == int(payload.venue_id))).scalar_one_or_none()
        if payload.venue_id
        else get_demo_template_venue(db)
    )
    if venue is None:
        raise HTTPException(status_code=404, detail="DEMO template venue not found")
    db.execute(
        update(Venue)
        .where(Venue.is_demo.is_(True), Venue.id != int(venue.id))
        .values(is_demo=False, demo_kind=DEMO_KIND_TEMPLATE)
    )
    venue.is_demo = True
    venue.demo_kind = DEMO_KIND_PUBLIC
    db.commit()
    return {
        "ok": True,
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "demo_kind": venue.demo_kind,
        "personas": _demo_personas_for_venue(db, int(venue.id)),
    }


@router.post("/ensure-template")
def admin_demo_ensure_template(
    payload: DemoEnsureTemplateIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    existing = get_demo_template_venue(db)
    if existing is not None:
        return {
            "ok": True,
            "created": False,
            "venue_id": int(existing.id),
            "venue_name": existing.name,
            "demo_kind": existing.demo_kind,
            "personas": _demo_personas_for_venue(db, int(existing.id)),
        }
    public = get_public_demo_venue(db)
    reference_year = int(payload.reference_year or getattr(public, "demo_reference_year", None) or 2026)
    reference_month = int(payload.reference_month or getattr(public, "demo_reference_month", None) or 3)
    venue_name = str(
        payload.venue_name
        or (f"{getattr(public, 'name', 'Axelio DEMO')} · TEMPLATE" if public is not None else "Axelio DEMO · TEMPLATE")
    ).strip()
    result = bootstrap_demo_venue(
        db,
        venue_name=venue_name,
        reference_year=reference_year,
        reference_month=reference_month,
        make_public=False,
        export_fixture_after=False,
    )
    db.commit()
    return {
        "ok": True,
        "created": True,
        "venue_id": result.venue_id,
        "venue_name": result.venue_name,
        "demo_kind": DEMO_KIND_TEMPLATE,
        "personas": _demo_personas_for_venue(db, int(result.venue_id)),
        "counts": result.counts,
    }


@router.post("/disable")
def admin_demo_disable(
    payload: DemoDisableIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    stmt = update(Venue).values(is_demo=False, demo_kind=None)
    if payload.venue_id is not None:
        stmt = stmt.where(Venue.id == int(payload.venue_id))
    else:
        stmt = stmt.where(Venue.is_demo.is_(True))
    result = db.execute(stmt)
    db.commit()
    return {"ok": True, "disabled_count": int(result.rowcount or 0)}


@router.post("/bootstrap")
def admin_demo_bootstrap(
    payload: DemoBootstrapIn, db: Session = Depends(get_db), user: User = Depends(require_super_admin)
):
    try:
        result = bootstrap_demo_venue(
            db,
            venue_id=payload.venue_id,
            venue_name=str(payload.venue_name or "").strip() or "Axelio DEMO · Hookah Lounge",
            reference_year=int(payload.reference_year or 2026),
            reference_month=int(payload.reference_month or 3),
            history_months=int(payload.history_months),
            make_public=bool(payload.make_public),
            export_fixture_after=bool(payload.export_fixture_after),
            export_fixture_path=payload.fixture_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    db.commit()
    return {
        "ok": True,
        "venue_id": result.venue_id,
        "venue_name": result.venue_name,
        "reference_year": result.reference_year,
        "reference_month": result.reference_month,
        "history_months": result.history_months,
        "period_start_year": result.period_start_year,
        "period_start_month": result.period_start_month,
        "fixture_path": result.fixture_path,
        "counts": result.counts,
        "warnings": result.warnings,
    }

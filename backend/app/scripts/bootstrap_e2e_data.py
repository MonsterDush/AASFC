from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.passwords import set_password
from app.auth.phone_auth import PHONE_PROVIDER_PHONE, normalize_phone_e164
from app.core.db import SessionLocal
from app.models import AuthIdentity, User, Venue, VenueBillingState, VenueMember
from app.services.demo.bootstrap import bootstrap_demo_venue
from app.settings import settings


DEFAULT_OWNER_PHONE = "+79990000001"
DEFAULT_STAFF_PHONE = "+79990000002"
DEFAULT_ADMIN_PHONE = "+79990000003"
DEFAULT_VENUE_NAME = "Axelio E2E Lounge"
LOCAL_DATABASE_HOSTS = {"127.0.0.1", "localhost", "::1", "db"}


def require_safe_e2e_database(database_url: str, *, confirmation: str | None) -> None:
    if str(confirmation or "").strip() != "1":
        raise RuntimeError("AXELIO_E2E_ALLOW_SEED=1 is required")

    parsed = urlparse(str(database_url or ""))
    host = str(parsed.hostname or "").strip().lower()
    database_name = str(parsed.path or "").strip("/").lower()
    if host not in LOCAL_DATABASE_HOSTS:
        raise RuntimeError(f"E2E seed only supports a local database host, got: {host or 'empty'}")
    if not any(marker in database_name for marker in ("e2e", "test")):
        raise RuntimeError(
            f"E2E database name must contain 'e2e' or 'test', got: {database_name or 'empty'}"
        )


def _required_password() -> str:
    password = str(os.getenv("E2E_PASSWORD") or "")
    if not password:
        raise RuntimeError("E2E_PASSWORD is required")
    return password


def _find_persona_user(db: Session, *, venue_id: int, persona: str) -> User:
    user = db.execute(
        select(User)
        .join(VenueMember, VenueMember.user_id == User.id)
        .where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.is_active.is_(True),
            User.is_demo_user.is_(True),
            User.demo_persona == str(persona).upper(),
        )
        .order_by(User.id.asc())
    ).scalar_one_or_none()
    if user is None:
        raise RuntimeError(f"Bootstrap did not create the {persona} user")
    return user


def _attach_phone_login(db: Session, *, user: User, phone: str, password: str) -> None:
    normalized_phone = normalize_phone_e164(phone)
    existing = db.execute(
        select(AuthIdentity).where(AuthIdentity.phone_e164 == normalized_phone)
    ).scalar_one_or_none()
    if existing is not None and int(existing.user_id) != int(user.id):
        raise RuntimeError(f"Phone {normalized_phone} is already assigned to another E2E user")
    if existing is None:
        db.add(
            AuthIdentity(
                user_id=int(user.id),
                provider=PHONE_PROVIDER_PHONE,
                provider_user_id=normalized_phone,
                phone_e164=normalized_phone,
                is_verified=True,
            )
        )
    else:
        existing.provider = PHONE_PROVIDER_PHONE
        existing.provider_user_id = normalized_phone
        existing.is_verified = True
    set_password(user, password)


def _find_or_create_admin_user(db: Session, *, phone: str) -> User:
    identity = db.execute(
        select(AuthIdentity).where(AuthIdentity.phone_e164 == normalize_phone_e164(phone))
    ).scalar_one_or_none()
    if identity is not None:
        user = db.get(User, int(identity.user_id))
        if user is None:
            raise RuntimeError("E2E admin identity points to a missing user")
    else:
        user = User(
            full_name="Axelio E2E Admin",
            short_name="E2E Admin",
            system_role="SUPER_ADMIN",
            is_demo_user=False,
            demo_persona=None,
        )
        db.add(user)
        db.flush()
    user.system_role = "SUPER_ADMIN"
    return user


def bootstrap_e2e_data(db: Session) -> dict[str, object]:
    require_safe_e2e_database(
        settings.database_url,
        confirmation=os.getenv("AXELIO_E2E_ALLOW_SEED"),
    )
    password = _required_password()
    venue_name = str(os.getenv("E2E_VENUE_NAME") or DEFAULT_VENUE_NAME).strip() or DEFAULT_VENUE_NAME
    owner_phone = normalize_phone_e164(os.getenv("E2E_OWNER_PHONE") or DEFAULT_OWNER_PHONE)
    staff_phone = normalize_phone_e164(os.getenv("E2E_STAFF_PHONE") or DEFAULT_STAFF_PHONE)
    admin_phone = normalize_phone_e164(os.getenv("E2E_ADMIN_PHONE") or DEFAULT_ADMIN_PHONE)
    if len({owner_phone, staff_phone, admin_phone}) != 3:
        raise RuntimeError("E2E owner, staff and admin phones must differ")

    existing_venues = db.execute(
        select(Venue).where(Venue.name == venue_name).order_by(Venue.id.asc())
    ).scalars().all()
    if len(existing_venues) > 1:
        raise RuntimeError(f"Multiple E2E venues named {venue_name!r} found")

    existing_venue = existing_venues[0] if existing_venues else None
    if existing_venue is not None:
        # The demo bootstrap owns this isolated venue and can safely reset its fixture data.
        existing_venue.is_demo = True
        db.flush()

    now = datetime.now(timezone.utc)
    result = bootstrap_demo_venue(
        db,
        venue_id=(int(existing_venue.id) if existing_venue is not None else None),
        venue_name=venue_name,
        reference_year=now.year,
        reference_month=now.month,
        make_public=False,
        export_fixture_after=False,
    )

    venue = db.get(Venue, int(result.venue_id))
    if venue is None:
        raise RuntimeError("E2E venue disappeared after bootstrap")
    venue.is_demo = False
    venue.demo_kind = None
    venue.demo_reference_year = None
    venue.demo_reference_month = None

    owner = _find_persona_user(db, venue_id=int(venue.id), persona="OWNER")
    staff = _find_persona_user(db, venue_id=int(venue.id), persona="STAFF")
    admin = _find_or_create_admin_user(db, phone=admin_phone)
    _attach_phone_login(db, user=owner, phone=owner_phone, password=password)
    _attach_phone_login(db, user=staff, phone=staff_phone, password=password)
    _attach_phone_login(db, user=admin, phone=admin_phone, password=password)

    billing = db.execute(
        select(VenueBillingState).where(VenueBillingState.venue_id == int(venue.id))
    ).scalar_one_or_none()
    if billing is None:
        raise RuntimeError("E2E bootstrap did not create billing state")
    billing.status = "ACTIVE"
    billing.paid_until = now + timedelta(days=365)
    billing.grace_until = now + timedelta(days=372)
    billing.next_payment_due_at = billing.paid_until
    billing.updated_at = now

    db.commit()
    return {
        "venue_id": int(venue.id),
        "venue_name": venue.name,
        "reference_month": f"{now.year:04d}-{now.month:02d}",
        "owner": {"user_id": int(owner.id), "phone": owner_phone, "role": "OWNER"},
        "staff": {"user_id": int(staff.id), "phone": staff_phone, "role": "STAFF"},
        "admin": {"user_id": int(admin.id), "phone": admin_phone, "role": "SUPER_ADMIN"},
        "counts": result.counts,
    }


def main() -> int:
    with SessionLocal() as db:
        payload = bootstrap_e2e_data(db)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

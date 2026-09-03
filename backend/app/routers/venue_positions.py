from fastapi import APIRouter

from app.routers.venue_core import (
    Depends,
    HTTPException,
    PayProfile,
    Query,
    Session,
    User,
    VenueMember,
    VenuePosition,
    _is_owner_or_super_admin,
    _require_active_member_or_admin,
    get_current_user,
    get_db,
    json,
    require_venue_permission,
    select,
)
from app.schemas.venue_payroll import (
    PositionCreateIn,
    PositionPresetsOut,
    PositionUpdateIn,
)
from app.routers.venue_permissions import (
    _is_schedule_editor,
)
from app.routers.venue_pay_profile_support import (
    _normalize_permission_codes,
    _parse_position_permission_codes,
)
from app.routers.venue_position_support import (
    _load_position_presets_from_setup,
)
from app.services.venue_member_names import load_member_display_names, load_owner_notes, owner_display_name


router = APIRouter()


def _ensure_catalog_position(
    db: Session,
    *,
    venue_id: int,
    title: str,
    rate: int,
    percent: int,
    pay_profile_id: int | None,
    permission_codes: str | None,
) -> VenuePosition:
    catalog = (
        db.execute(
            select(VenuePosition)
            .where(
                VenuePosition.venue_id == int(venue_id),
                VenuePosition.member_user_id.is_(None),
                VenuePosition.title == str(title or "").strip(),
            )
            .order_by(VenuePosition.is_active.desc(), VenuePosition.id.asc())
        )
        .scalars()
        .first()
    )
    if catalog is None:
        catalog = VenuePosition(
            venue_id=int(venue_id),
            member_user_id=None,
            title=str(title or "").strip(),
            rate=int(rate or 0),
            percent=int(percent or 0),
            pay_profile_id=pay_profile_id,
            permission_codes=permission_codes,
            is_active=True,
        )
        db.add(catalog)
    elif not catalog.is_active:
        catalog.is_active = True
    return catalog


@router.get("/{venue_id}/position-presets", response_model=PositionPresetsOut)
def list_position_presets(
    venue_id: int,
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)
    if not allowed:
        for code in ("POSITIONS_VIEW", "POSITIONS_ASSIGN", "POSITIONS_MANAGE", "POSITION_PERMISSIONS_MANAGE"):
            try:
                require_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
                allowed = True
                break
            except HTTPException:
                pass
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

    return {"items": _load_position_presets_from_setup(db, venue_id=venue_id, include_inactive=include_inactive)}


@router.get("/{venue_id}/positions")
def list_positions(
    venue_id: int,
    include_inactive: bool = Query(
        False, description="If true, return inactive members/positions too (requires manage)."
    ),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _is_schedule_editor(
        db, venue_id=venue_id, user=user
    )
    if not allowed:
        for code in ("POSITIONS_VIEW", "POSITIONS_MANAGE", "SHIFTS_VIEW", "SHIFTS_MANAGE"):
            try:
                require_venue_permission(db, venue_id=venue_id, user=user, permission_code=code)
                allowed = True
                break
            except HTTPException:
                pass
    if not allowed:
        raise HTTPException(status_code=403, detail="Forbidden")

    if include_inactive:
        manage_ok = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)
        if not manage_ok:
            try:
                require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_MANAGE")
                manage_ok = True
            except HTTPException:
                manage_ok = False
        if not manage_ok:
            raise HTTPException(status_code=403, detail="Forbidden")

    stmt = (
        select(
            VenuePosition.id,
            VenuePosition.title,
            VenuePosition.member_user_id,
            VenuePosition.pay_profile_id,
            VenuePosition.rate,
            VenuePosition.percent,
            VenuePosition.permission_codes,
            VenuePosition.is_active,
            User.tg_user_id,
            User.tg_username,
            User.full_name,
            User.short_name,
            VenueMember.venue_role,
            VenueMember.is_active.label("member_is_active"),
            PayProfile.title.label("pay_profile_title"),
        )
        .outerjoin(User, User.id == VenuePosition.member_user_id)
        .outerjoin(
            VenueMember,
            (VenueMember.venue_id == VenuePosition.venue_id) & (VenueMember.user_id == VenuePosition.member_user_id),
        )
        .outerjoin(PayProfile, PayProfile.id == VenuePosition.pay_profile_id)
        .where(VenuePosition.venue_id == venue_id)
        .order_by(VenuePosition.id.desc())
    )

    if not include_inactive:
        stmt = stmt.where(
            VenuePosition.is_active.is_(True),
            (VenuePosition.member_user_id.is_(None)) | VenueMember.is_active.is_(True),
        )

    rows = db.execute(stmt).all()

    owner_notes = load_owner_notes(
        db,
        venue_id=venue_id,
        viewer=user,
        member_user_ids=[int(r.member_user_id) for r in rows if r.member_user_id is not None],
    )
    member_display_names = load_member_display_names(
        db,
        venue_id=venue_id,
        member_user_ids=[int(r.member_user_id) for r in rows if r.member_user_id is not None],
    )
    items = []
    for r in rows:
        member_user_id = int(r.member_user_id) if r.member_user_id is not None else None
        owner_note = owner_notes.get(member_user_id) if member_user_id is not None else None
        display_name_override = member_display_names.get(member_user_id) if member_user_id is not None else None
        items.append(
            {
                "id": r.id,
                "title": r.title,
                "member_user_id": r.member_user_id,
                "rate": r.rate,
                "percent": r.percent,
                "pay_profile_id": int(r.pay_profile_id) if r.pay_profile_id is not None else None,
                "pay_profile_title": r.pay_profile_title,
                "pay_profile_assignment_id": None,
                "permission_codes": _parse_position_permission_codes(getattr(r, "permission_codes", None)),
                "is_active": bool(r.is_active),
                "member": {
                    "user_id": member_user_id,
                    "tg_user_id": r.tg_user_id,
                    "tg_username": r.tg_username,
                    "full_name": r.full_name,
                    "short_name": r.short_name,
                    "venue_role": r.venue_role,
                    "display_name": owner_display_name(
                        owner_note=display_name_override,
                        short_name=r.short_name,
                        full_name=r.full_name,
                        tg_username=r.tg_username,
                        user_id=member_user_id,
                    )
                    if member_user_id is not None
                    else None,
                    "owner_note": owner_note,
                    "is_active": bool(r.member_is_active) if member_user_id is not None else False,
                },
            }
        )
    return items


@router.post("/{venue_id}/positions")
def create_position(
    venue_id: int,
    payload: PositionCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_MANAGE")

    # Setting permission codes requires POSITION_PERMISSIONS_MANAGE
    if payload.permission_codes is not None and not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITION_PERMISSIONS_MANAGE")

    codes_provided = payload.permission_codes is not None
    norm_codes = _normalize_permission_codes(db, payload.permission_codes or []) if codes_provided else []

    if payload.member_user_id is not None:
        if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_ASSIGN")
        vm = db.execute(
            select(VenueMember).where(
                VenueMember.venue_id == venue_id,
                VenueMember.user_id == payload.member_user_id,
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if vm is None:
            raise HTTPException(status_code=400, detail="Member not found in venue")

    if payload.pay_profile_id is not None and not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")
    profile = None
    if payload.pay_profile_id is not None:
        profile = db.execute(
            select(PayProfile).where(PayProfile.id == payload.pay_profile_id, PayProfile.venue_id == venue_id)
        ).scalar_one_or_none()
        if profile is None:
            raise HTTPException(status_code=400, detail="Pay profile not found in venue")

    title = payload.title.strip()
    member_filter = (
        VenuePosition.member_user_id.is_(None)
        if payload.member_user_id is None
        else VenuePosition.member_user_id == payload.member_user_id
    )
    pos = (
        db.execute(
            select(VenuePosition)
            .where(
                VenuePosition.venue_id == venue_id,
                member_filter,
                VenuePosition.title == title,
            )
            .order_by(VenuePosition.is_active.desc(), VenuePosition.id.asc())
        )
        .scalars()
        .first()
    )
    created = pos is None
    if pos is None:
        pos = VenuePosition(venue_id=venue_id, member_user_id=payload.member_user_id)
        db.add(pos)

    # A catalog row (member_user_id=NULL) is stable and is never "claimed"
    # by an employee. Employee assignments are separate VenuePosition rows.
    pos.member_user_id = payload.member_user_id
    pos.title = title
    pos.rate = payload.rate
    pos.percent = payload.percent
    pos.pay_profile_id = payload.pay_profile_id
    pos.permission_codes = json.dumps(norm_codes) if codes_provided else json.dumps([])
    pos.is_active = payload.is_active
    if pos.member_user_id is not None and pos.is_active:
        _ensure_catalog_position(
            db,
            venue_id=venue_id,
            title=pos.title,
            rate=pos.rate,
            percent=pos.percent,
            pay_profile_id=pos.pay_profile_id,
            permission_codes=pos.permission_codes,
        )
    db.commit()
    db.refresh(pos)
    return {
        "id": pos.id,
        "mode": (
            "created_catalog"
            if payload.member_user_id is None and created
            else "updated_catalog"
            if payload.member_user_id is None
            else "created_assignment"
            if created
            else "updated_assignment"
        ),
        "pay_profile_id": int(profile.id) if profile is not None else None,
        "pay_profile_title": profile.title if profile is not None else None,
        "pay_profile_assignment_id": None,
    }


@router.patch("/{venue_id}/positions/{position_id}")
def update_position(
    venue_id: int,
    position_id: int,
    payload: PositionUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    is_owner = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)
    if not is_owner:
        # General editing of position requires POSITIONS_MANAGE
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_MANAGE")

    pos = db.execute(
        select(VenuePosition).where(VenuePosition.id == position_id, VenuePosition.venue_id == venue_id)
    ).scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")

    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))

    # Changing or clearing member assignment is a separate permission.
    if "member_user_id" in fields_set and payload.member_user_id != pos.member_user_id:
        if not is_owner:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_ASSIGN")

        if payload.member_user_id is not None:
            vm = db.execute(
                select(VenueMember).where(
                    VenueMember.venue_id == venue_id,
                    VenueMember.user_id == payload.member_user_id,
                    VenueMember.is_active.is_(True),
                )
            ).scalar_one_or_none()
            if vm is None:
                raise HTTPException(status_code=400, detail="Member not found in venue")

        pos.member_user_id = payload.member_user_id

    # Editing permission codes is a separate permission (matrix)
    codes_provided = payload.permission_codes is not None
    norm_codes: list[str] | None = None
    perms_changed = False
    if codes_provided:
        norm_codes = _normalize_permission_codes(db, payload.permission_codes or [])
        current = set(_parse_position_permission_codes(getattr(pos, "permission_codes", None)))
        incoming = set(norm_codes)
        perms_changed = current != incoming

    if perms_changed and not is_owner:
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITION_PERMISSIONS_MANAGE")

    if payload.title is not None:
        next_title = payload.title.strip()
        if pos.member_user_id is None and next_title != pos.title:
            assigned_rows = (
                db.execute(
                    select(VenuePosition).where(
                        VenuePosition.venue_id == venue_id,
                        VenuePosition.member_user_id.is_not(None),
                        VenuePosition.is_active.is_(True),
                        VenuePosition.title == pos.title,
                    )
                )
                .scalars()
                .all()
            )
            for assigned in assigned_rows:
                assigned.title = next_title
        pos.title = next_title
    if payload.rate is not None:
        pos.rate = payload.rate
    if payload.percent is not None:
        pos.percent = payload.percent
    if payload.is_active is not None:
        pos.is_active = payload.is_active

    if perms_changed:
        pos.permission_codes = json.dumps(norm_codes or [])

    profile = None
    if "pay_profile_id" in fields_set:
        if not is_owner:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")
        if payload.pay_profile_id is not None:
            profile = db.execute(
                select(PayProfile).where(PayProfile.id == payload.pay_profile_id, PayProfile.venue_id == venue_id)
            ).scalar_one_or_none()
            if profile is None:
                raise HTTPException(status_code=400, detail="Pay profile not found in venue")
        pos.pay_profile_id = payload.pay_profile_id
    elif pos.pay_profile_id is not None:
        profile = db.execute(select(PayProfile).where(PayProfile.id == pos.pay_profile_id)).scalar_one_or_none()

    if pos.member_user_id is not None and pos.is_active:
        _ensure_catalog_position(
            db,
            venue_id=venue_id,
            title=pos.title,
            rate=pos.rate,
            percent=pos.percent,
            pay_profile_id=pos.pay_profile_id,
            permission_codes=pos.permission_codes,
        )

    db.commit()
    db.refresh(pos)

    return {
        "ok": True,
        "id": pos.id,
        "title": pos.title,
        "member_user_id": pos.member_user_id,
        "rate": pos.rate,
        "percent": pos.percent,
        "pay_profile_id": int(pos.pay_profile_id) if pos.pay_profile_id is not None else None,
        "pay_profile_title": profile.title if profile is not None else None,
        "pay_profile_assignment_id": None,
        "permission_codes": _parse_position_permission_codes(getattr(pos, "permission_codes", None)),
        "is_active": bool(pos.is_active),
    }


@router.delete("/{venue_id}/positions/{position_id}")
def delete_position(
    venue_id: int,
    position_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_MANAGE")

    pos = db.execute(
        select(VenuePosition).where(VenuePosition.id == position_id, VenuePosition.venue_id == venue_id)
    ).scalar_one_or_none()
    if pos is None:
        raise HTTPException(status_code=404, detail="Position not found")

    mode = "archived"
    if pos.member_user_id is not None:
        sibling = (
            db.execute(
                select(VenuePosition.id).where(
                    VenuePosition.venue_id == venue_id,
                    VenuePosition.id != pos.id,
                    VenuePosition.title == pos.title,
                    VenuePosition.is_active.is_(True),
                )
            )
            .scalars()
            .first()
        )
        if sibling is None:
            db.add(
                VenuePosition(
                    venue_id=pos.venue_id,
                    member_user_id=None,
                    pay_profile_id=pos.pay_profile_id,
                    title=pos.title,
                    rate=pos.rate,
                    percent=pos.percent,
                    permission_codes=pos.permission_codes,
                    is_active=True,
                )
            )
            pos.is_active = False
            mode = "member_detached_position_kept"
        else:
            pos.is_active = False
            mode = "member_detached"
    else:
        pos.is_active = False
    db.commit()
    return {"ok": True, "mode": mode}

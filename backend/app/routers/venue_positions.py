from fastapi import APIRouter

from app.routers.venue_core import (
    Depends,
    HTTPException,
    PositionCreateIn,
    PositionPresetsOut,
    PositionUpdateIn,
    Query,
    Session,
    User,
    VenueMember,
    VenuePosition,
    _get_member_active_pay_profile_assignment,
    _is_owner_or_super_admin,
    _is_schedule_editor,
    _load_position_presets_from_setup,
    _normalize_permission_codes,
    _parse_position_permission_codes,
    _require_active_member_or_admin,
    _sync_member_pay_profile_assignment,
    date,
    get_current_user,
    get_db,
    json,
    require_venue_permission,
    select,
)


router = APIRouter()


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
    include_inactive: bool = Query(False, description="If true, return inactive members/positions too (requires manage)."),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    allowed = _is_owner_or_super_admin(db, venue_id=venue_id, user=user) or _is_schedule_editor(db, venue_id=venue_id, user=user)
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
        )
        .join(User, User.id == VenuePosition.member_user_id)
        .join(
            VenueMember,
            (VenueMember.venue_id == VenuePosition.venue_id)
            & (VenueMember.user_id == VenuePosition.member_user_id),
        )
        .where(VenuePosition.venue_id == venue_id)
        .order_by(VenuePosition.id.desc())
    )

    if not include_inactive:
        stmt = stmt.where(VenuePosition.is_active.is_(True), VenueMember.is_active.is_(True))

    rows = db.execute(stmt).all()

    items = []
    for r in rows:
        assignment, profile = _get_member_active_pay_profile_assignment(db, venue_id=venue_id, member_user_id=int(r.member_user_id), on_date=date.today())
        items.append({
            "id": r.id,
            "title": r.title,
            "member_user_id": r.member_user_id,
            "rate": r.rate,
            "percent": r.percent,
            "pay_profile_id": int(profile.id) if profile is not None else None,
            "pay_profile_title": profile.title if profile is not None else None,
            "pay_profile_assignment_id": int(assignment.id) if assignment is not None else None,
            "permission_codes": _parse_position_permission_codes(getattr(r, "permission_codes", None)),
            "is_active": bool(r.is_active),
            "member": {
                "user_id": r.member_user_id,
                "tg_user_id": r.tg_user_id,
                "tg_username": r.tg_username,
                "full_name": r.full_name,
                "short_name": r.short_name,
                "venue_role": r.venue_role,
                "is_active": bool(r.member_is_active),
            },
        })
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

    # validate member exists in this venue (active)
    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == payload.member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if vm is None:
        raise HTTPException(status_code=400, detail="Member not found in venue")

    existing = db.execute(
        select(VenuePosition).where(
            VenuePosition.venue_id == venue_id,
            VenuePosition.member_user_id == payload.member_user_id,
        )
    ).scalar_one_or_none()

    if payload.pay_profile_id is not None and not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")

    if existing is None:
        pos = VenuePosition(
            venue_id=venue_id,
            member_user_id=payload.member_user_id,
            title=payload.title.strip(),
            rate=payload.rate,
            percent=payload.percent,
            permission_codes=json.dumps(norm_codes),
            is_active=payload.is_active,
        )
        db.add(pos)
        db.flush()
        assignment, profile = _sync_member_pay_profile_assignment(
            db,
            venue_id=venue_id,
            member_user_id=payload.member_user_id,
            pay_profile_id=payload.pay_profile_id,
        )
        db.commit()
        db.refresh(pos)
        return {"id": pos.id, "pay_profile_id": int(profile.id) if profile is not None else None, "pay_profile_title": profile.title if profile is not None else None, "pay_profile_assignment_id": int(assignment.id) if assignment is not None else None}

    # update-in-place
    existing.title = payload.title.strip()
    existing.rate = payload.rate
    existing.percent = payload.percent
    if codes_provided:
        existing.permission_codes = json.dumps(norm_codes)
    existing.is_active = payload.is_active
    assignment, profile = _sync_member_pay_profile_assignment(
        db,
        venue_id=venue_id,
        member_user_id=payload.member_user_id,
        pay_profile_id=payload.pay_profile_id,
    )

    db.commit()
    return {"id": existing.id, "mode": "updated", "pay_profile_id": int(profile.id) if profile is not None else None, "pay_profile_title": profile.title if profile is not None else None, "pay_profile_assignment_id": int(assignment.id) if assignment is not None else None}


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

    # Changing member assignment is a separate permission
    if payload.member_user_id is not None and payload.member_user_id != pos.member_user_id:
        if not is_owner:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_ASSIGN")

        # validate member exists
        vm = db.execute(
            select(VenueMember).where(
                VenueMember.venue_id == venue_id,
                VenueMember.user_id == payload.member_user_id,
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if vm is None:
            raise HTTPException(status_code=400, detail="Member not found in venue")

        clash = db.execute(
            select(VenuePosition).where(
                VenuePosition.venue_id == venue_id,
                VenuePosition.member_user_id == payload.member_user_id,
            )
        ).scalar_one_or_none()
        if clash is not None and clash.id != pos.id:
            raise HTTPException(status_code=409, detail="Position for this member already exists")

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
        pos.title = payload.title.strip()
    if payload.rate is not None:
        pos.rate = payload.rate
    if payload.percent is not None:
        pos.percent = payload.percent
    if payload.is_active is not None:
        pos.is_active = payload.is_active

    if perms_changed:
        pos.permission_codes = json.dumps(norm_codes or [])

    assignment = None
    profile = None
    fields_set = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    if "pay_profile_id" in fields_set:
        if not is_owner:
            require_venue_permission(db, venue_id=venue_id, user=user, permission_code="PAY_PROFILES_MANAGE")
        assignment, profile = _sync_member_pay_profile_assignment(
            db,
            venue_id=venue_id,
            member_user_id=pos.member_user_id,
            pay_profile_id=payload.pay_profile_id,
        )
    else:
        assignment, profile = _get_member_active_pay_profile_assignment(db, venue_id=venue_id, member_user_id=pos.member_user_id, on_date=date.today())

    db.commit()
    db.refresh(pos)

    return {
        "ok": True,
        "id": pos.id,
        "title": pos.title,
        "member_user_id": pos.member_user_id,
        "rate": pos.rate,
        "percent": pos.percent,
        "pay_profile_id": int(profile.id) if profile is not None else None,
        "pay_profile_title": profile.title if profile is not None else None,
        "pay_profile_assignment_id": int(assignment.id) if assignment is not None else None,
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

    pos.is_active = False
    db.commit()
    return {"ok": True}


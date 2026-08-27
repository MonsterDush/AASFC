from fastapi import APIRouter

from app.routers.venue_core import (
    AuthIdentity,
    Depends,
    HTTPException,
    PayProfile,
    Session,
    Shift,
    ShiftAssignment,
    User,
    VenueInvite,
    VenueMember,
    VenuePosition,
    _is_owner_or_super_admin,
    _require_active_member_or_admin,
    build_invite_link,
    create_venue_invite,
    datetime,
    delete,
    get_current_user,
    get_db,
    normalize_phone_e164,
    normalize_tg_username,
    require_venue_permission,
    select,
    status,
    timezone,
)
from app.schemas.venue_core import (
    InviteCreateIn,
    InviteDefaultPositionPatchIn,
    MemberOwnerNotePatchIn,
)
from app.routers.venue_permissions import (
    _require_staff_manage_or_owner_or_super_admin,
)
from app.routers.venue_membership_support import (
    _build_pending_invite_target_map,
    _build_user_auth_snapshot_map,
    _serialize_user_brief,
)
from app.routers.venue_payroll_support import (
    _recalculate_payroll_for_dates,
)
from app.services.venue_member_names import normalize_owner_note, owner_display_name


router = APIRouter()


def _detach_member_positions(db: Session, *, venue_id: int, member_user_id: int) -> None:
    positions = (
        db.execute(
            select(VenuePosition)
            .where(
                VenuePosition.venue_id == int(venue_id),
                VenuePosition.member_user_id == int(member_user_id),
                VenuePosition.is_active.is_(True),
            )
            .order_by(VenuePosition.id.asc())
        )
        .scalars()
        .all()
    )
    by_title: dict[str, list[VenuePosition]] = {}
    for position in positions:
        by_title.setdefault(str(position.title or "").strip(), []).append(position)

    for title, member_positions in by_title.items():
        member_position_ids = [int(position.id) for position in member_positions]
        sibling_id = (
            db.execute(
                select(VenuePosition.id)
                .where(
                    VenuePosition.venue_id == int(venue_id),
                    VenuePosition.title == title,
                    VenuePosition.is_active.is_(True),
                    VenuePosition.id.not_in(member_position_ids),
                )
                .order_by(VenuePosition.id.asc())
            )
            .scalars()
            .first()
        )
        if sibling_id is None and member_positions:
            keeper, *duplicates = member_positions
            keeper.member_user_id = None
            for duplicate in duplicates:
                duplicate.is_active = False
        else:
            for position in member_positions:
                position.is_active = False


@router.post("/{venue_id}/invites")
def create_invite(
    venue_id: int,
    payload: InviteCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_staff_manage_or_owner_or_super_admin(db, venue_id=venue_id, user=user)

    can_manage_owner_members = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)

    role = str(payload.venue_role or "").strip().upper()
    if role not in ("OWNER", "STAFF"):
        raise HTTPException(status_code=400, detail="Bad venue_role")
    if role == "OWNER" and not can_manage_owner_members:
        raise HTTPException(status_code=403, detail="Недостаточно прав для приглашения владельца")

    channel = str(payload.invite_channel or "TELEGRAM").strip().upper()
    if channel not in ("TELEGRAM", "PHONE"):
        raise HTTPException(status_code=400, detail="Bad invite_channel")

    existing_user = None

    if channel == "TELEGRAM":
        username = normalize_tg_username(payload.tg_username)
        if not username:
            raise HTTPException(status_code=400, detail="Bad tg_username")

        existing_user = db.query(User).filter(User.tg_username == username).one_or_none()
        if existing_user:
            mem = (
                db.query(VenueMember)
                .filter(
                    VenueMember.venue_id == venue_id,
                    VenueMember.user_id == existing_user.id,
                )
                .one_or_none()
            )

            if mem:
                if str(mem.venue_role or "").upper() == "OWNER" and not can_manage_owner_members:
                    raise HTTPException(status_code=403, detail="Недостаточно прав для изменения владельца")
                mem.venue_role = role
                mem.is_active = True
                mem.owner_note = normalize_owner_note(payload.contact_label)
            else:
                db.add(
                    VenueMember(
                        venue_id=venue_id,
                        user_id=existing_user.id,
                        venue_role=role,
                        is_active=True,
                        owner_note=normalize_owner_note(payload.contact_label),
                    )
                )

            db.commit()
            auth_map = _build_user_auth_snapshot_map(db, [existing_user.id])
            member_row = type(
                "MemberRow",
                (),
                {
                    "id": existing_user.id,
                    "tg_user_id": existing_user.tg_user_id,
                    "tg_username": existing_user.tg_username,
                    "full_name": existing_user.full_name,
                    "short_name": existing_user.short_name,
                },
            )()
            return {
                "ok": True,
                "mode": "member_added",
                "channel": channel,
                "member": {
                    **_serialize_user_brief(
                        member_row, auth_map, owner_note=normalize_owner_note(payload.contact_label)
                    ),
                    "venue_role": role,
                },
            }

        try:
            inv = create_venue_invite(
                db,
                venue_id=venue_id,
                venue_role=role,
                invite_channel="TELEGRAM",
                tg_username=username,
                contact_label=payload.contact_label,
                created_by_user_id=user.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    else:
        phone = normalize_phone_e164(payload.phone)
        if not phone:
            raise HTTPException(status_code=400, detail="Bad phone")

        phone_ident = db.execute(
            select(AuthIdentity).where(
                AuthIdentity.provider == "PHONE",
                AuthIdentity.phone_e164 == phone,
                AuthIdentity.is_verified.is_(True),
            )
        ).scalar_one_or_none()
        if phone_ident is not None:
            existing_user = db.execute(select(User).where(User.id == phone_ident.user_id)).scalar_one_or_none()

        if existing_user:
            mem = (
                db.query(VenueMember)
                .filter(
                    VenueMember.venue_id == venue_id,
                    VenueMember.user_id == existing_user.id,
                )
                .one_or_none()
            )
            if mem:
                if str(mem.venue_role or "").upper() == "OWNER" and not can_manage_owner_members:
                    raise HTTPException(status_code=403, detail="Недостаточно прав для изменения владельца")
                mem.venue_role = role
                mem.is_active = True
                mem.owner_note = normalize_owner_note(payload.contact_label)
            else:
                db.add(
                    VenueMember(
                        venue_id=venue_id,
                        user_id=existing_user.id,
                        venue_role=role,
                        is_active=True,
                        owner_note=normalize_owner_note(payload.contact_label),
                    )
                )

            db.commit()
            auth_map = _build_user_auth_snapshot_map(db, [existing_user.id])
            member_row = type(
                "MemberRow",
                (),
                {
                    "id": existing_user.id,
                    "tg_user_id": existing_user.tg_user_id,
                    "tg_username": existing_user.tg_username,
                    "full_name": existing_user.full_name,
                    "short_name": existing_user.short_name,
                },
            )()
            return {
                "ok": True,
                "mode": "member_added",
                "channel": channel,
                "member": {
                    **_serialize_user_brief(
                        member_row, auth_map, owner_note=normalize_owner_note(payload.contact_label)
                    ),
                    "venue_role": role,
                },
            }

        try:
            inv = create_venue_invite(
                db,
                venue_id=venue_id,
                venue_role=role,
                invite_channel="PHONE",
                phone_e164=phone,
                contact_label=payload.contact_label,
                created_by_user_id=user.id,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    db.refresh(inv)
    invite_meta = _build_pending_invite_target_map(db, [inv]).get(
        int(inv.id), {"target_status": "WAITING_SIGNUP", "target_user": None}
    )
    return {
        "ok": True,
        "mode": "invited",
        "channel": inv.invite_channel,
        "invite_id": inv.id,
        "invite_link": build_invite_link(inv.invite_token),
        "token": inv.invite_token,
        "target_status": invite_meta.get("target_status", "WAITING_SIGNUP"),
        "target_user": invite_meta.get("target_user"),
    }


@router.patch("/{venue_id}/members/{member_user_id}/owner-note")
def update_member_owner_note(
    venue_id: int,
    member_user_id: int,
    payload: MemberOwnerNotePatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        raise HTTPException(status_code=403, detail="Only the venue owner can edit this note")

    membership = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if membership is None:
        raise HTTPException(status_code=404, detail="Member not found")

    membership.owner_note = normalize_owner_note(payload.owner_note)
    member = db.execute(select(User).where(User.id == member_user_id)).scalar_one()
    db.commit()
    return {
        "ok": True,
        "member_user_id": int(member_user_id),
        "owner_note": membership.owner_note,
        "display_name": owner_display_name(
            owner_note=membership.owner_note,
            short_name=member.short_name,
            full_name=member.full_name,
            tg_username=member.tg_username,
            user_id=member.id,
        ),
    }


@router.patch("/{venue_id}/invites/{invite_id}/default_position")
def set_invite_default_position(
    venue_id: int,
    invite_id: int,
    payload: InviteDefaultPositionPatchIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    # Changing preset position for an invite requires POSITIONS_ASSIGN (or owner/admin).
    if not _is_owner_or_super_admin(db, venue_id=venue_id, user=user):
        require_venue_permission(db, venue_id=venue_id, user=user, permission_code="POSITIONS_ASSIGN")

    inv = (
        db.query(VenueInvite)
        .filter(
            VenueInvite.id == invite_id,
            VenueInvite.venue_id == venue_id,
        )
        .one_or_none()
    )
    if not inv or not inv.is_active or inv.accepted_user_id is not None:
        raise HTTPException(status_code=404, detail="Invite not found")

    if payload.default_position is None:
        inv.default_position_json = None
    else:
        if payload.default_position.pay_profile_id is not None:
            profile_ok = db.execute(
                select(PayProfile.id).where(
                    PayProfile.id == int(payload.default_position.pay_profile_id),
                    PayProfile.venue_id == venue_id,
                )
            ).scalar_one_or_none()
            if profile_ok is None:
                raise HTTPException(status_code=400, detail="Pay profile not found in venue")
        inv.default_position_json = payload.default_position.dict()

    db.commit()
    return {"ok": True, "default_position": inv.default_position_json}


@router.delete("/{venue_id}/invites/{invite_id}")
def cancel_invite(
    venue_id: int,
    invite_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_staff_manage_or_owner_or_super_admin(db, venue_id=venue_id, user=user)

    can_manage_owner_members = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)

    inv = db.query(VenueInvite).filter(VenueInvite.id == invite_id, VenueInvite.venue_id == venue_id).one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Invite not found")
    if str(inv.venue_role or "").upper() == "OWNER" and not can_manage_owner_members:
        raise HTTPException(status_code=403, detail="Недостаточно прав для отмены приглашения владельца")

    inv.is_active = False
    inv.revoked_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.delete("/{venue_id}/members/{member_user_id}")
def remove_member(
    venue_id: int,
    member_user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_staff_manage_or_owner_or_super_admin(db, venue_id=venue_id, user=user)

    can_manage_owner_members = _is_owner_or_super_admin(db, venue_id=venue_id, user=user)

    vm = db.execute(
        select(VenueMember).where(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == member_user_id,
            VenueMember.is_active.is_(True),
        )
    ).scalar_one_or_none()

    if vm is None:
        raise HTTPException(status_code=404, detail="Member not found")

    if str(vm.venue_role or "").upper() == "OWNER" and not can_manage_owner_members:
        raise HTTPException(status_code=403, detail="Недостаточно прав для удаления владельца")

    if vm.venue_role == "OWNER":
        owners = db.execute(
            select(VenueMember.id).where(
                VenueMember.venue_id == venue_id,
                VenueMember.venue_role == "OWNER",
                VenueMember.is_active.is_(True),
            )
        ).all()
        if len(owners) <= 1:
            raise HTTPException(status_code=400, detail="Cannot remove last OWNER")

    vm.is_active = False

    affected_shift_dates = (
        db.execute(
            select(Shift.date)
            .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
            .where(
                Shift.venue_id == venue_id,
                ShiftAssignment.member_user_id == member_user_id,
            )
            .distinct()
        )
        .scalars()
        .all()
    )

    # Deactivate member's position (if exists) and remove their assignments in this venue
    venue_shift_ids = select(Shift.id).where(Shift.venue_id == venue_id)

    # Remove their assignments first (FK depends on venue_positions)
    db.execute(
        delete(ShiftAssignment).where(
            ShiftAssignment.member_user_id == member_user_id,
            ShiftAssignment.shift_id.in_(venue_shift_ids),
        )
    )

    _detach_member_positions(db, venue_id=venue_id, member_user_id=member_user_id)

    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=list(affected_shift_dates),
        calculated_by_user_id=user.id,
        trigger_reason="member_removed_from_venue",
    )

    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/leave", status_code=204)
def leave_venue(
    venue_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Находим активное членство пользователя в заведении
    membership = (
        db.query(VenueMember)
        .filter(
            VenueMember.venue_id == venue_id,
            VenueMember.user_id == current_user.id,
            VenueMember.is_active.is_(True),
        )
        .one_or_none()
    )

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вы не являетесь участником этого заведения",
        )

    # Если это OWNER — проверяем, что он не последний владелец
    if membership.venue_role == "OWNER":
        owners_count = (
            db.query(VenueMember)
            .filter(
                VenueMember.venue_id == venue_id,
                VenueMember.venue_role == "OWNER",
                VenueMember.is_active.is_(True),
            )
            .count()
        )

        if owners_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Нельзя выйти из заведения: вы последний владелец",
            )

    # Деактивируем membership
    membership.is_active = False
    db.add(membership)

    affected_shift_dates = (
        db.execute(
            select(Shift.date)
            .join(ShiftAssignment, ShiftAssignment.shift_id == Shift.id)
            .where(
                Shift.venue_id == venue_id,
                ShiftAssignment.member_user_id == current_user.id,
            )
            .distinct()
        )
        .scalars()
        .all()
    )

    # Deactivate user's position (if exists) and remove their assignments in this venue
    venue_shift_ids = select(Shift.id).where(Shift.venue_id == venue_id)

    # Remove assignments first
    db.execute(
        delete(ShiftAssignment).where(
            ShiftAssignment.member_user_id == current_user.id,
            ShiftAssignment.shift_id.in_(venue_shift_ids),
        )
    )

    _detach_member_positions(db, venue_id=venue_id, member_user_id=current_user.id)

    _recalculate_payroll_for_dates(
        db,
        venue_id=venue_id,
        target_dates=list(affected_shift_dates),
        calculated_by_user_id=current_user.id,
        trigger_reason="member_left_venue",
    )

    db.commit()

    return None


# ---------- Schedule templates: weekly patterns for month generation ----------

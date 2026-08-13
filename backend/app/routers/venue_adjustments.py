import datetime as dt

from fastapi import APIRouter

from app.routers.venue_core import (
    Adjustment,
    AdjustmentDispute,
    AdjustmentDisputeComment,
    BaseModel,
    Depends,
    HTTPException,
    Optional,
    Query,
    Session,
    User,
    VenueMember,
    _require_active_member_or_admin,
    date,
    datetime,
    get_current_user,
    get_db,
    select,
    timedelta,
    timezone,
)
from app.schemas.venue_reports import (
    AdjustmentCreateIn,
    DisputeCommentIn,
    DisputeCreateIn,
    DisputeStatusIn,
)
from app.routers.venue_permissions import (
    _has_adjustments_manage_access,
    _require_adjustments_manager,
    _require_adjustments_viewer,
    _require_dispute_resolver,
)
from app.routers.venue_adjustment_notifications import (
    _enqueue_adjustment_assigned_job,
    _enqueue_adjustment_dispute_event_job,
)


router = APIRouter()


@router.get("/{venue_id}/adjustments")
def list_adjustments(
    venue_id: int,
    month: str | None = Query(default=None, description="YYYY-MM"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    mine: int = Query(0, description="1 => only my items"),
    type: str | None = Query(default=None, description="penalty|writeoff|bonus|tip"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    if not mine:
        _require_adjustments_viewer(db, venue_id=venue_id, user=user)

    if month and (date_from is not None or date_to is not None):
        raise HTTPException(status_code=400, detail="Use either month or date_from/date_to")

    if month:
        try:
            y_s, m_s = month.split("-")
            y = int(y_s)
            m = int(m_s)
            start = date(y, m, 1)
            end = date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1)
        except Exception:
            raise HTTPException(status_code=400, detail="Bad month format, expected YYYY-MM")
    else:
        if date_from is None or date_to is None:
            raise HTTPException(status_code=400, detail="Provide month or both date_from/date_to")
        if date_from > date_to:
            raise HTTPException(status_code=400, detail="date_from must be <= date_to")
        start = date_from
        end = date_to + timedelta(days=1)

    stmt = select(Adjustment).where(
        Adjustment.venue_id == venue_id,
        Adjustment.is_active.is_(True),
        Adjustment.date >= start,
        Adjustment.date < end,
    )

    if type:
        stmt = stmt.where(Adjustment.type == type)
    else:
        stmt = stmt.where(Adjustment.type != "tip")
    if mine:
        stmt = stmt.where(Adjustment.member_user_id == user.id)

    rows = db.execute(stmt.order_by(Adjustment.date.asc(), Adjustment.id.asc())).scalars().all()

    # preload member users
    member_ids = {r.member_user_id for r in rows if r.member_user_id}
    users_by_id = {}
    if member_ids:
        urows = db.execute(select(User).where(User.id.in_(member_ids))).scalars().all()
        users_by_id = {u.id: u for u in urows}

    return {
        "items": [
            {
                "id": r.id,
                "type": r.type,
                "date": r.date.isoformat(),
            "status": getattr(r, "status", "DRAFT"),
            "closed_at": r.closed_at.isoformat() if getattr(r, "closed_at", None) else None,
                "amount": r.amount,
                "reason": r.reason,
                "member_user_id": r.member_user_id,
                "member": (
                    {
                        "user_id": u.id,
                        "tg_user_id": u.tg_user_id,
                        "tg_username": u.tg_username,
                        "full_name": u.full_name,
                        "short_name": u.short_name,
                    }
                    if (r.member_user_id and (u := users_by_id.get(r.member_user_id)))
                    else None
                ),
            }
            for r in rows
        ]
    }



# ---------- Adjustments helpers ----------


@router.post("/{venue_id}/adjustments")
def create_adjustment(
    venue_id: int,
    payload: AdjustmentCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    if payload.type not in ("penalty", "writeoff", "bonus"):
        raise HTTPException(status_code=400, detail="Bad type")

    if payload.type in ("penalty", "bonus") and not payload.member_user_id:
        raise HTTPException(status_code=400, detail="member_user_id is required")

    if payload.member_user_id:
        vm = db.execute(
            select(VenueMember).where(
                VenueMember.venue_id == venue_id,
                VenueMember.user_id == payload.member_user_id,
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
        if vm is None:
            raise HTTPException(status_code=400, detail="Member not found in venue")

    obj = Adjustment(
        venue_id=venue_id,
        type=payload.type,
        member_user_id=payload.member_user_id,
        date=payload.date,
        amount=payload.amount,
        reason=(payload.reason or "").strip() or None,
        created_by_user_id=user.id,
        is_active=True,
    )
    db.add(obj)
    db.flush()

    if payload.member_user_id:
        _enqueue_adjustment_assigned_job(db, venue_id=venue_id, adjustment_id=int(obj.id))

    db.commit()
    db.refresh(obj)
    return {"id": obj.id}

class AdjustmentUpdateIn(BaseModel):
    type: Optional[str] = None          # "penalty" | "writeoff" | "bonus"
    member_user_id: Optional[int] = None
    date: Optional[dt.date] = None
    amount: Optional[int] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None



@router.patch("/{venue_id}/adjustments/{adjustment_id}")
def update_adjustment(
    venue_id: int,
    adjustment_id: int,
    payload: AdjustmentUpdateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == adjustment_id,
            Adjustment.venue_id == venue_id,
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    if payload.type is not None:
        t = payload.type.strip()
        if t not in ("penalty", "writeoff", "bonus"):
            raise HTTPException(status_code=400, detail="Bad type")
        adj.type = t

    if payload.date is not None:
        adj.date = payload.date

    if payload.amount is not None:
        adj.amount = int(payload.amount)

    if payload.reason is not None:
        adj.reason = payload.reason.strip() or None

    if payload.member_user_id is not None:
        # allow null only for writeoff
        if payload.member_user_id == 0:
            adj.member_user_id = None
        else:
            adj.member_user_id = int(payload.member_user_id)

    adj.updated_by_user_id = user.id
    adj.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.delete("/{venue_id}/adjustments/{adjustment_id}")
def delete_adjustment(
    venue_id: int,
    adjustment_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == adjustment_id,
            Adjustment.venue_id == venue_id,
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    adj.is_active = False
    adj.updated_by_user_id = user.id
    adj.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/{venue_id}/adjustments/{adj_type}/{adj_id}/dispute")
def create_dispute(
    venue_id: int,
    adj_type: str,
    adj_id: int,
    payload: DisputeCreateIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Employee disputes a specific adjustment.

    If there is an OPEN dispute thread for this adjustment, we append a comment.
    Otherwise we create a new dispute + first comment.
    """
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == adj_id,
            Adjustment.venue_id == venue_id,
            Adjustment.type == adj_type,
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    if adj.member_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    message = (payload.message or "").strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message is required")

    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.adjustment_id == adj.id,
            AdjustmentDispute.is_active.is_(True),
            AdjustmentDispute.status == "OPEN",
        )
        .order_by(AdjustmentDispute.id.desc())
    ).scalar_one_or_none()

    created_new = False
    if dis is None:
        created_new = True
        dis = AdjustmentDispute(
            venue_id=venue_id,
            adjustment_id=adj.id,
            message=message,
            created_by_user_id=user.id,
            is_active=True,
            status="OPEN",
        )
        db.add(dis)
        db.flush()

    com = AdjustmentDisputeComment(
        dispute_id=dis.id,
        author_user_id=user.id,
        message=message,
        is_active=True,
    )
    db.add(com)
    db.flush()

    _enqueue_adjustment_dispute_event_job(
        db,
        venue_id=venue_id,
        dispute_id=int(dis.id),
        comment_id=int(com.id),
        event_kind="opened" if created_new else "comment",
    )

    db.commit()
    return {"ok": True, "dispute_id": dis.id}

@router.get("/{venue_id}/adjustments/{adj_type}/{adj_id}/dispute")
def get_dispute_thread(
    venue_id: int,
    adj_type: str,
    adj_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    adj = db.execute(
        select(Adjustment).where(
            Adjustment.id == adj_id,
            Adjustment.venue_id == venue_id,
            Adjustment.type == adj_type,
            Adjustment.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    # Access: owner/managers OR employee owning the adjustment
    if not _has_adjustments_manage_access(db, venue_id=venue_id, user=user) and adj.member_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.adjustment_id == adj.id,
            AdjustmentDispute.is_active.is_(True),
        ).order_by(AdjustmentDispute.id.desc())
    ).scalar_one_or_none()

    if dis is None:
        return {"dispute": None, "comments": []}

    comments = db.execute(
        select(AdjustmentDisputeComment)
        .where(
            AdjustmentDisputeComment.dispute_id == dis.id,
            AdjustmentDisputeComment.is_active.is_(True),
        )
        .order_by(AdjustmentDisputeComment.created_at.asc(), AdjustmentDisputeComment.id.asc())
    ).scalars().all()

    return {
        "dispute": {
            "id": dis.id,
            "status": dis.status,
            "created_by_user_id": dis.created_by_user_id,
            "created_at": dis.created_at.isoformat(),
            "resolved_by_user_id": dis.resolved_by_user_id,
            "resolved_at": dis.resolved_at.isoformat() if dis.resolved_at else None,
        },
        "comments": [
            {
                "id": c.id,
                "author_user_id": c.author_user_id,
                "message": c.message,
                "created_at": c.created_at.isoformat(),
            }
            for c in comments
        ],
    }


@router.post("/{venue_id}/disputes/{dispute_id}/comments")
def add_dispute_comment(
    venue_id: int,
    dispute_id: int,
    payload: DisputeCommentIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)

    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.id == dispute_id,
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if dis is None:
        raise HTTPException(status_code=404, detail="Not found")

    adj = db.execute(select(Adjustment).where(Adjustment.id == dis.adjustment_id)).scalar_one_or_none()
    if adj is None:
        raise HTTPException(status_code=404, detail="Not found")

    is_manager = _has_adjustments_manage_access(db, venue_id=venue_id, user=user)
    if not is_manager and adj.member_user_id != user.id and dis.created_by_user_id != user.id:
        raise HTTPException(status_code=403, detail="Forbidden")

    msg = (payload.message or "").strip()
    if not msg:
        raise HTTPException(status_code=422, detail="Message is required")

    com = AdjustmentDisputeComment(
        dispute_id=dis.id,
        author_user_id=user.id,
        message=msg,
        is_active=True,
    )
    db.add(com)
    db.flush()

    _enqueue_adjustment_dispute_event_job(
        db,
        venue_id=venue_id,
        dispute_id=int(dis.id),
        comment_id=int(com.id),
        event_kind="comment",
    )

    db.commit()
    return {"ok": True}


@router.patch("/{venue_id}/disputes/{dispute_id}")
def set_dispute_status(
    venue_id: int,
    dispute_id: int,
    payload: DisputeStatusIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_dispute_resolver(db, venue_id=venue_id, user=user)

    dis = db.execute(
        select(AdjustmentDispute).where(
            AdjustmentDispute.id == dispute_id,
            AdjustmentDispute.venue_id == venue_id,
            AdjustmentDispute.is_active.is_(True),
        )
    ).scalar_one_or_none()
    if dis is None:
        raise HTTPException(status_code=404, detail="Not found")

    st = (payload.status or "").upper()
    if st not in ("OPEN", "CLOSED"):
        raise HTTPException(status_code=422, detail="Invalid status")

    dis.status = st
    if st == "CLOSED":
        dis.resolved_by_user_id = user.id
        dis.resolved_at = datetime.utcnow()
    else:
        dis.resolved_by_user_id = None
        dis.resolved_at = None

    db.add(dis)
    db.commit()
    return {"ok": True}


@router.get("/{venue_id}/disputes")
def list_disputes(
    venue_id: int,
    status: str | None = Query(None),
    month: str | None = Query(None, description="YYYY-MM"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _require_active_member_or_admin(db, venue_id=venue_id, user=user)
    _require_adjustments_manager(db, venue_id=venue_id, user=user)

    stmt = select(AdjustmentDispute, Adjustment).join(Adjustment, Adjustment.id == AdjustmentDispute.adjustment_id).where(
        AdjustmentDispute.venue_id == venue_id,
        AdjustmentDispute.is_active.is_(True),
        Adjustment.is_active.is_(True),
    )

    if status:
        st = status.upper()
        if st in ("OPEN", "CLOSED"):
            stmt = stmt.where(AdjustmentDispute.status == st)

    if month:
        try:
            y, m = month.split("-")
            y = int(y)
            m = int(m)
            start = date(y, m, 1)
            end = date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
            stmt = stmt.where(Adjustment.date >= start, Adjustment.date < end)
        except Exception:
            raise HTTPException(status_code=422, detail="Invalid month")

    rows = db.execute(stmt.order_by(AdjustmentDispute.id.desc())).all()
    return {
        "items": [
            {
                "dispute_id": d.id,
                "status": d.status,
                "adjustment": {
                    "id": a.id,
                    "type": a.type,
                    "date": a.date.isoformat(),
                    "amount": a.amount,
                    "member_user_id": a.member_user_id,
                    "reason": a.reason,
                },
            }
            for d, a in rows
        ]
    }

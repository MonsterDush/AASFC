from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.venue_member import VenueMember


def normalize_owner_note(value: str | None) -> str | None:
    normalized = " ".join(str(value or "").strip().split())
    return normalized[:500] or None


def base_member_display_name(
    *,
    short_name: str | None = None,
    full_name: str | None = None,
    tg_username: str | None = None,
    phone: str | None = None,
    user_id: int | None = None,
) -> str:
    return str(
        short_name
        or full_name
        or (f"@{str(tg_username).lstrip('@')}" if tg_username else None)
        or phone
        or (f"user #{int(user_id)}" if user_id else None)
        or "—"
    ).strip()


def is_owner_note_viewer(db: Session, *, venue_id: int, viewer: User) -> bool:
    if str(getattr(viewer, "system_role", "") or "").upper() == "SUPER_ADMIN":
        return True
    return bool(
        db.execute(
            select(VenueMember.id).where(
                VenueMember.venue_id == int(venue_id),
                VenueMember.user_id == int(viewer.id),
                VenueMember.venue_role == "OWNER",
                VenueMember.is_active.is_(True),
            )
        ).scalar_one_or_none()
    )


def load_owner_notes(
    db: Session,
    *,
    venue_id: int,
    viewer: User,
    member_user_ids: Iterable[int],
) -> dict[int, str]:
    if not is_owner_note_viewer(db, venue_id=venue_id, viewer=viewer):
        return {}
    user_ids = sorted({int(value) for value in member_user_ids if value})
    if not user_ids:
        return {}
    rows = db.execute(
        select(VenueMember.user_id, VenueMember.owner_note).where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.user_id.in_(user_ids),
            VenueMember.is_active.is_(True),
        )
    ).all()
    return {int(row.user_id): note for row in rows if (note := normalize_owner_note(getattr(row, "owner_note", None)))}


def load_member_display_names(
    db: Session,
    *,
    venue_id: int,
    member_user_ids: Iterable[int],
) -> dict[int, str]:
    """Load venue-local labels used as member display names.

    The label may be used in ``display_name`` for authorized venue viewers.
    Raw ``owner_note`` visibility remains protected by ``load_owner_notes``.
    """
    user_ids = sorted({int(value) for value in member_user_ids if value})
    if not user_ids:
        return {}

    rows = db.execute(
        select(VenueMember.user_id, VenueMember.owner_note).where(
            VenueMember.venue_id == int(venue_id),
            VenueMember.user_id.in_(user_ids),
            VenueMember.is_active.is_(True),
        )
    ).all()

    return {
        int(row.user_id): note
        for row in rows
        if (note := normalize_owner_note(getattr(row, "owner_note", None)))
    }


def owner_display_name(
    *,
    owner_note: str | None = None,
    short_name: str | None = None,
    full_name: str | None = None,
    tg_username: str | None = None,
    phone: str | None = None,
    user_id: int | None = None,
) -> str:
    return normalize_owner_note(owner_note) or base_member_display_name(
        short_name=short_name,
        full_name=full_name,
        tg_username=tg_username,
        phone=phone,
        user_id=user_id,
    )


def apply_payroll_owner_display_names(
    db: Session,
    *,
    venue_id: int,
    viewer: User,
    payload: dict,
) -> dict:
    lines = list((payload or {}).get("lines") or [])
    notes = load_owner_notes(
        db,
        venue_id=venue_id,
        viewer=viewer,
        member_user_ids=[int(line.get("member_user_id") or 0) for line in lines],
    )
    for line in lines:
        member = line.get("member") or {}
        member_user_id = int(line.get("member_user_id") or member.get("user_id") or 0)
        owner_note = notes.get(member_user_id)
        member["owner_note"] = owner_note
        member["display_name"] = owner_display_name(
            owner_note=owner_note,
            short_name=member.get("short_name"),
            full_name=member.get("full_name"),
            tg_username=member.get("tg_username"),
            user_id=member_user_id,
        )
        line["member"] = member
    payload["lines"] = lines
    return payload

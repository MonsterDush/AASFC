from __future__ import annotations

from difflib import SequenceMatcher
import re
from unicodedata import normalize

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.pos_canonical import POSEmployee, POSEmployeeMapping
from app.models.venue_member import VenueMember


_NON_WORD = re.compile(r"[^a-zа-яё0-9]+", re.IGNORECASE)


def suggest_employee_mappings(
    db: Session,
    *,
    connection_id: int,
    venue_id: int,
    minimum_confidence: float = 0.88,
) -> int:
    if not 0 < float(minimum_confidence) <= 1:
        raise ValueError("minimum_confidence must be in the interval (0, 1]")
    employees = list(
        db.execute(
            select(POSEmployee).where(POSEmployee.connection_id == int(connection_id), POSEmployee.active.is_(True))
        ).scalars()
    )
    members = list(
        db.execute(
            select(VenueMember)
            .options(joinedload(VenueMember.user))
            .where(VenueMember.venue_id == int(venue_id), VenueMember.is_active.is_(True))
        ).scalars()
    )
    created_or_updated = 0
    for employee in employees:
        current = db.execute(
            select(POSEmployeeMapping).where(POSEmployeeMapping.pos_employee_id == int(employee.id))
        ).scalar_one_or_none()
        if current is not None and current.confirmed:
            continue
        candidates = []
        source_name = _normalized_name(employee.name)
        for member in members:
            names = (
                member.owner_note,
                getattr(member.user, "full_name", None),
                getattr(member.user, "short_name", None),
            )
            confidence = max(
                (SequenceMatcher(None, source_name, normalized).ratio() for value in names if (normalized := _normalized_name(value))),
                default=0.0,
            )
            if confidence >= float(minimum_confidence):
                candidates.append((confidence, int(member.id)))
        candidates.sort(reverse=True)
        if not candidates:
            continue
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            continue
        confidence, member_id = candidates[0]
        if current is None:
            current = POSEmployeeMapping(pos_employee_id=int(employee.id))
            db.add(current)
        current.venue_member_id = member_id
        current.match_type = "EXACT_NAME" if confidence == 1 else "FUZZY_NAME"
        current.confidence = confidence
        current.confirmed = False
        current.confirmed_at = None
        current.confirmed_by_user_id = None
        created_or_updated += 1
    db.flush()
    return created_or_updated


def _normalized_name(value: str | None) -> str:
    text = normalize("NFKC", str(value or "")).casefold().replace("ё", "е")
    return " ".join(_NON_WORD.sub(" ", text).split())

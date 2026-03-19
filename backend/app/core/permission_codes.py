from __future__ import annotations

import json
import re
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions_registry import PERMISSIONS
from app.models import Permission


def parse_permission_codes(raw: object) -> list[str]:
    """Parse permission codes from JSON list or tolerant legacy text formats.

    Canonical storage format is a JSON list in ``VenuePosition.permission_codes``.
    We still tolerate older serialized strings here so the parser stays in one place.
    """
    if raw is None:
        return []

    if isinstance(raw, (list, tuple, set)):
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            code = str(item or "").strip().upper()
            if code and code not in seen:
                seen.add(code)
                out.append(code)
        return out

    s = str(raw).strip()
    if not s:
        return []

    try:
        data = json.loads(s)
        if isinstance(data, list):
            return parse_permission_codes(data)
    except Exception:
        pass

    cleaned = s.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
    out: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[\s,;]+", cleaned):
        code = str(part or "").strip().upper()
        if code and code not in seen:
            seen.add(code)
            out.append(code)
    return out


def registry_permission_codes() -> set[str]:
    return {p.code.strip().upper() for p in PERMISSIONS}


def unique_permission_codes(codes: Iterable[object] | None) -> list[str]:
    if not codes:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for code in codes:
        s = str(code or "").strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def normalize_known_permission_codes(db: Session, codes: Iterable[object] | None) -> list[str]:
    cleaned = unique_permission_codes(codes)
    if not cleaned:
        return []

    active = set(
        db.execute(
            select(Permission.code).where(Permission.code.in_(cleaned), Permission.is_active.is_(True))
        )
        .scalars()
        .all()
    )
    registry = registry_permission_codes()
    return [code for code in cleaned if code in active or code in registry]

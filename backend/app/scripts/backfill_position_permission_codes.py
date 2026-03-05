"""Normalize VenuePosition.permission_codes.

Purpose
-------
The project moved to a single source of truth for per-venue permissions:

  VenuePosition.permission_codes  (TEXT, JSON list of permission codes)

This script normalizes existing rows to a canonical JSON list:
- uppercase
- de-duplicate
- keeps only active permissions (DB) or codes present in code registry
- writes an explicit "[]" for NULL/empty values (optional but convenient)

It can also normalize invite presets (venue_invites.default_position_json) to keep
only `permission_codes` and remove legacy keys.

Usage
-----
  python -m app.scripts.backfill_position_permission_codes

Optional env vars:
  DRY_RUN=1            # do not commit changes
  VENUE_ID=123         # process only one venue
  LIMIT=5000           # limit rows (useful for testing)
"""

from __future__ import annotations

import json
import os
import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.permissions_registry import PERMISSIONS
from app.models import Permission, VenuePosition, VenueInvite


def _parse_codes(raw: str | None) -> list[str]:
    """Tolerant parser for VenuePosition.permission_codes stored as TEXT."""
    if raw is None:
        return []
    s = str(raw).strip()
    if not s:
        return []

    # 1) JSON list (preferred)
    try:
        data = json.loads(s)
        if isinstance(data, list):
            out: list[str] = []
            for x in data:
                v = str(x or "").strip().upper()
                if v and v not in out:
                    out.append(v)
            return out
    except Exception:
        pass

    # 2) fallback: comma/space separated list or python-like list string
    cleaned = s.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
    out: list[str] = []
    for part in re.split(r"[\s,;]+", cleaned):
        v = str(part or "").strip().upper()
        if v and v not in out:
            out.append(v)
    return out


def _normalize_permission_codes(db: Session, codes: Iterable[str] | None) -> list[str]:
    if not codes:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for c in codes:
        s = str(c or "").strip().upper()
        if not s or s in seen:
            continue
        seen.add(s)
        cleaned.append(s)

    if not cleaned:
        return []

    active = set(
        db.execute(
            select(Permission.code).where(Permission.code.in_(cleaned), Permission.is_active.is_(True))
        )
        .scalars()
        .all()
    )
    registry = {p.code.strip().upper() for p in PERMISSIONS}
    # Keep codes that exist in DB as active OR are defined in code registry (even if sync wasn't run yet).
    return [c for c in cleaned if c in active or c in registry]


def _normalize_invite_preset(inv: VenueInvite) -> bool:
    preset = getattr(inv, "default_position_json", None)
    if not isinstance(preset, dict):
        return False

    # accept both keys, but always store as permission_codes
    raw = preset.get("permission_codes")
    if raw is None:
        raw = preset.get("permissions")

    if isinstance(raw, str):
        raw_list = [x.strip() for x in raw.split(",") if x.strip()]
    elif isinstance(raw, list):
        raw_list = raw
    else:
        raw_list = []

    cleaned: list[str] = []
    seen: set[str] = set()
    for x in raw_list:
        v = str(x or "").strip().upper()
        if v and v not in seen:
            seen.add(v)
            cleaned.append(v)

    # Remove legacy keys completely (we no longer use them)
    for k in list(preset.keys()):
        if str(k).startswith("can_"):
            preset.pop(k, None)
    preset.pop("permissions", None)

    preset["permission_codes"] = cleaned
    inv.default_position_json = preset
    return True


def main() -> int:
    dry_run = os.getenv("DRY_RUN", "").strip() in ("1", "true", "yes")
    venue_id = os.getenv("VENUE_ID", "").strip()
    limit = int(os.getenv("LIMIT", "0") or "0")

    normalized_positions = 0
    normalized_invites = 0
    scanned = 0

    with SessionLocal() as db:
        q = select(VenuePosition)
        if venue_id:
            try:
                vid = int(venue_id)
                q = q.where(VenuePosition.venue_id == vid)
            except Exception:
                raise SystemExit("VENUE_ID must be int")

        if limit > 0:
            q = q.limit(limit)

        rows = db.execute(q).scalars().all()
        for pos in rows:
            scanned += 1
            raw = getattr(pos, "permission_codes", None)
            existing_codes = _parse_codes(raw)
            norm = _normalize_permission_codes(db, existing_codes)
            canon = json.dumps(norm or [])

            # always write canonical JSON string (also converts NULL/empty to "[]")
            if (raw is None) or (str(raw).strip() != canon):
                pos.permission_codes = canon
                normalized_positions += 1
                if not dry_run:
                    db.add(pos)

        inv_q = select(VenueInvite)
        if venue_id:
            inv_q = inv_q.where(VenueInvite.venue_id == int(venue_id))
        if limit > 0:
            inv_q = inv_q.limit(limit)

        inv_rows = db.execute(inv_q).scalars().all()
        for inv in inv_rows:
            if _normalize_invite_preset(inv):
                normalized_invites += 1
                if not dry_run:
                    db.add(inv)

        if not dry_run:
            db.commit()

    print(f"Scanned positions: {scanned}")
    print(f"Normalized positions: {normalized_positions}")
    print(f"Normalized invite presets: {normalized_invites}")
    print("DRY_RUN=1 (no commit)" if dry_run else "Committed changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

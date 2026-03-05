"""Backfill VenuePosition.permission_codes from legacy boolean flags and normalize formats.

Purpose
-------
We are migrating the app from coarse legacy boolean flags (can_make_reports, can_edit_schedule, ...)
to fine-grained permission codes stored in VenuePosition.permission_codes (JSON list of codes).

This script:
- normalizes existing permission_codes into canonical JSON list (dedup + uppercase)
- for rows where permission_codes is NULL/empty, derives codes from legacy flags
- keeps legacy flags in sync with derived codes (so old UI/logic won't "stick")

Usage
-----
Run inside backend virtualenv / docker container with access to DATABASE_URL:

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


def _derive_codes_from_legacy_flags(pos: VenuePosition) -> list[str]:
    codes: list[str] = []

    # Reports / revenue
    if bool(getattr(pos, "can_make_reports", False)):
        codes += ["SHIFT_REPORT_VIEW", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_CLOSE"]
    elif bool(getattr(pos, "can_view_reports", False)) or bool(getattr(pos, "can_view_revenue", False)):
        # revenue-only legacy flag still implies view-level access in new model
        codes += ["SHIFT_REPORT_VIEW"]

    # Schedule
    if bool(getattr(pos, "can_edit_schedule", False)):
        codes += ["SHIFTS_VIEW", "SHIFTS_MANAGE"]

    # Adjustments & disputes
    if bool(getattr(pos, "can_manage_adjustments", False)):
        codes += ["ADJUSTMENTS_VIEW", "ADJUSTMENTS_MANAGE"]
    elif bool(getattr(pos, "can_view_adjustments", False)):
        codes += ["ADJUSTMENTS_VIEW"]

    if bool(getattr(pos, "can_resolve_disputes", False)):
        codes += ["DISPUTES_RESOLVE"]

    # dedup/uppercase here (final normalization happens later too)
    out: list[str] = []
    seen: set[str] = set()
    for c in codes:
        s = str(c or "").strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _derive_legacy_flags_from_codes(codes: list[str]) -> dict[str, bool]:
    s = {str(c or "").strip().upper() for c in (codes or [])}
    s.discard("")
    return {
        "can_make_reports": bool(s.intersection({"SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT"})),
        "can_view_reports": bool(s.intersection({"SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_REOPEN"})),
        "can_view_revenue": bool(s.intersection({"SHIFT_REPORT_VIEW", "SHIFT_REPORT_CLOSE", "SHIFT_REPORT_EDIT"})),
        "can_edit_schedule": bool(s.intersection({"SHIFTS_MANAGE"})),
        "can_view_adjustments": bool(s.intersection({"ADJUSTMENTS_VIEW", "ADJUSTMENTS_MANAGE"})),
        "can_manage_adjustments": bool(s.intersection({"ADJUSTMENTS_MANAGE"})),
        "can_resolve_disputes": bool(s.intersection({"DISPUTES_RESOLVE"})),
    }


def _update_invite_preset(db: Session, inv: VenueInvite) -> bool:
    """Optional: normalize invite default_position_json to include permission_codes when missing."""
    preset = getattr(inv, "default_position_json", None)
    if not isinstance(preset, dict):
        return False

    if preset.get("permission_codes") or preset.get("permissions"):
        # ensure list is clean and stored under permission_codes
        raw = preset.get("permission_codes") or preset.get("permissions")
        if isinstance(raw, str):
            raw_list = [x.strip() for x in raw.split(",") if x.strip()]
        elif isinstance(raw, list):
            raw_list = raw
        else:
            raw_list = []
        cleaned = [str(x or "").strip().upper() for x in raw_list if str(x or "").strip()]
        dedup = []
        seen = set()
        for c in cleaned:
            if c not in seen:
                seen.add(c)
                dedup.append(c)
        preset["permission_codes"] = dedup
        preset.pop("permissions", None)
        inv.default_position_json = preset
        return True

    # derive from legacy flags inside preset
    dummy = type("Dummy", (), preset)  # minimal attribute access
    codes = []
    if bool(getattr(dummy, "can_make_reports", False)):
        codes += ["SHIFT_REPORT_VIEW", "SHIFT_REPORT_EDIT", "SHIFT_REPORT_CLOSE"]
    elif bool(getattr(dummy, "can_view_reports", False)) or bool(getattr(dummy, "can_view_revenue", False)):
        codes += ["SHIFT_REPORT_VIEW"]
    if bool(getattr(dummy, "can_edit_schedule", False)):
        codes += ["SHIFTS_VIEW", "SHIFTS_MANAGE"]
    if bool(getattr(dummy, "can_manage_adjustments", False)):
        codes += ["ADJUSTMENTS_VIEW", "ADJUSTMENTS_MANAGE"]
    elif bool(getattr(dummy, "can_view_adjustments", False)):
        codes += ["ADJUSTMENTS_VIEW"]
    if bool(getattr(dummy, "can_resolve_disputes", False)):
        codes += ["DISPUTES_RESOLVE"]

    cleaned = []
    seen = set()
    for c in codes:
        s = str(c or "").strip().upper()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)

    if not cleaned:
        return False

    preset["permission_codes"] = cleaned
    inv.default_position_json = preset
    return True


def main() -> int:
    dry_run = os.getenv("DRY_RUN", "").strip() in ("1", "true", "yes")
    venue_id = os.getenv("VENUE_ID", "").strip()
    limit = int(os.getenv("LIMIT", "0") or "0")

    updated_positions = 0
    normalized_positions = 0
    updated_invites = 0
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
            raw_present = raw is not None and str(raw).strip() != ""

            existing_codes = _parse_codes(raw) if raw_present else []
            changed = False

            if raw_present:
                # normalize and canonicalize to JSON list
                norm = _normalize_permission_codes(db, existing_codes)
                canon = json.dumps(norm or [])
                if str(raw).strip() != canon:
                    pos.permission_codes = canon
                    changed = True
                    normalized_positions += 1

                # keep legacy flags in sync with codes
                derived = _derive_legacy_flags_from_codes(norm)
                for k, v in derived.items():
                    if bool(getattr(pos, k)) != bool(v):
                        setattr(pos, k, bool(v))
                        changed = True
            else:
                # backfill from legacy flags
                derived_codes = _derive_codes_from_legacy_flags(pos)
                norm = _normalize_permission_codes(db, derived_codes)
                if norm:
                    pos.permission_codes = json.dumps(norm)
                    derived_flags = _derive_legacy_flags_from_codes(norm)
                    for k, v in derived_flags.items():
                        setattr(pos, k, bool(v))
                    changed = True
                    updated_positions += 1

            if changed and not dry_run:
                db.add(pos)

        # Optional: normalize invites presets
        inv_q = select(VenueInvite)
        if venue_id:
            inv_q = inv_q.where(VenueInvite.venue_id == int(venue_id))
        if limit > 0:
            inv_q = inv_q.limit(limit)

        inv_rows = db.execute(inv_q).scalars().all()
        for inv in inv_rows:
            if _update_invite_preset(db, inv):
                updated_invites += 1
                if not dry_run:
                    db.add(inv)

        if not dry_run:
            db.commit()

    print(f"Scanned positions: {scanned}")
    print(f"Backfilled positions (from legacy flags): {updated_positions}")
    print(f"Normalized positions (canonical JSON / synced flags): {normalized_positions}")
    print(f"Updated invites (added/normalized permission_codes in preset): {updated_invites}")
    print("DRY_RUN=1 (no commit)" if dry_run else "Committed changes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

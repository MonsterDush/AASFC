from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models.venue_setup_state import VenueSetupState
from app.models.pay_profile import PayProfile


from app.routers.venue_pay_profile_support import _parse_position_permission_codes


def _normalize_position_preset_item(raw: object, *, idx: int = 0) -> dict | None:
    if not isinstance(raw, dict):
        return None
    title = str(raw.get("title") or "").strip()
    if not title:
        return None
    raw_id = str(raw.get("id") or "").strip() or f"preset-{idx + 1}"
    try:
        rate = max(0, int(raw.get("rate") or 0))
    except Exception:
        rate = 0
    try:
        percent = max(0, min(100, int(raw.get("percent") or 0)))
    except Exception:
        percent = 0
    pay_profile_id = raw.get("pay_profile_id")
    try:
        pay_profile_id = int(pay_profile_id) if pay_profile_id not in (None, "", 0, "0") else None
    except Exception:
        pay_profile_id = None
    venue_position_id = raw.get("venue_position_id")
    try:
        venue_position_id = (
            int(venue_position_id)
            if venue_position_id not in (None, "", 0, "0")
            else None
        )
    except Exception:
        venue_position_id = None
    return {
        "id": raw_id,
        "title": title[:100],
        "venue_position_id": venue_position_id,
        "rate": rate,
        "percent": percent,
        "pay_profile_id": pay_profile_id,
        "pay_profile_title": str(raw.get("pay_profile_title") or "").strip() or None,
        "template_id": str(raw.get("template_id") or "").strip() or None,
        "template_title": str(raw.get("template_title") or "").strip() or None,
        "permission_codes": _parse_position_permission_codes(raw.get("permission_codes")),
        "is_active": raw.get("is_active") is not False,
    }


def _load_position_presets_from_setup(db: Session, *, venue_id: int, include_inactive: bool = False) -> list[dict]:
    state = db.execute(select(VenueSetupState).where(VenueSetupState.venue_id == int(venue_id))).scalar_one_or_none()
    meta = getattr(state, "step_meta_json", None) or {}
    if not isinstance(meta, dict):
        return []
    raw_positions = meta.get("positions") or {}
    if not isinstance(raw_positions, dict):
        return []
    raw_presets = raw_positions.get("presets") or []
    if not isinstance(raw_presets, list):
        return []

    items: list[dict] = []
    for idx, raw in enumerate(raw_presets):
        item = _normalize_position_preset_item(raw, idx=idx)
        if not item:
            continue
        if not include_inactive and not item.get("is_active", True):
            continue
        items.append(item)

    profile_ids = sorted({int(x["pay_profile_id"]) for x in items if x.get("pay_profile_id")})
    if profile_ids:
        rows = db.execute(
            select(PayProfile.id, PayProfile.title).where(
                PayProfile.venue_id == int(venue_id),
                PayProfile.id.in_(profile_ids),
            )
        ).all()
        titles = {int(r.id): str(r.title or "") for r in rows}
        for item in items:
            pid = item.get("pay_profile_id")
            if pid and titles.get(int(pid)):
                item["pay_profile_title"] = titles[int(pid)]
    return items

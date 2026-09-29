from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.models import PayComponent, PayProfile, PositionPayProfilePeriod, VenuePosition


def audit_position_pay_profiles(db: Session, *, venue_id: int | None = None) -> dict:
    """Inspect effective-dated position payroll data without changing it."""

    position_query = select(VenuePosition)
    period_query = select(PositionPayProfilePeriod)
    profile_query = select(PayProfile)
    component_query = select(PayComponent).where(PayComponent.is_active.is_(True))
    if venue_id is not None:
        position_query = position_query.where(VenuePosition.venue_id == int(venue_id))
        period_query = period_query.where(PositionPayProfilePeriod.venue_id == int(venue_id))
        profile_query = profile_query.where(PayProfile.venue_id == int(venue_id))
        component_query = component_query.where(PayComponent.venue_id == int(venue_id))

    positions = list(db.execute(position_query).scalars())
    periods = list(db.execute(period_query).scalars())
    profiles = {int(row.id): row for row in db.execute(profile_query).scalars()}
    component_profile_ids = {
        int(profile_id)
        for profile_id in db.execute(component_query.with_only_columns(PayComponent.pay_profile_id)).scalars()
    }
    positions_by_id = {int(row.id): row for row in positions}
    periods_by_position: dict[int, list[PositionPayProfilePeriod]] = defaultdict(list)
    for period in periods:
        periods_by_position[int(period.venue_position_id)].append(period)

    issues: list[dict] = []
    warnings: list[dict] = []
    for position in positions:
        if not position.is_active or position.member_user_id is None or position.pay_profile_id is None:
            continue
        active_periods = [row for row in periods_by_position.get(int(position.id), []) if row.is_active]
        if not active_periods:
            issues.append(
                {
                    "code": "ACTIVE_POSITION_WITHOUT_PROFILE_PERIOD",
                    "venue_id": int(position.venue_id),
                    "venue_position_id": int(position.id),
                    "member_user_id": int(position.member_user_id),
                    "pay_profile_id": int(position.pay_profile_id),
                }
            )

    for position_id, rows in periods_by_position.items():
        position = positions_by_id.get(position_id)
        ordered = sorted(
            (row for row in rows if row.is_active),
            key=lambda row: (row.valid_from or date.min, row.valid_to or date.max, int(row.id)),
        )
        for period in ordered:
            profile = profiles.get(int(period.pay_profile_id))
            if position is None or int(position.venue_id) != int(period.venue_id):
                issues.append(
                    {
                        "code": "PROFILE_PERIOD_POSITION_SCOPE_MISMATCH",
                        "period_id": int(period.id),
                        "venue_position_id": position_id,
                    }
                )
            if profile is None or int(profile.venue_id) != int(period.venue_id):
                issues.append(
                    {
                        "code": "PROFILE_PERIOD_PROFILE_SCOPE_MISMATCH",
                        "period_id": int(period.id),
                        "pay_profile_id": int(period.pay_profile_id),
                    }
                )
            elif int(profile.id) not in component_profile_ids:
                warnings.append(
                    {
                        "code": "PROFILE_WITHOUT_ACTIVE_COMPONENTS",
                        "period_id": int(period.id),
                        "pay_profile_id": int(profile.id),
                    }
                )

        for previous, current in zip(ordered, ordered[1:]):
            previous_end = previous.valid_to or date.max
            current_start = current.valid_from or date.min
            if current_start <= previous_end:
                issues.append(
                    {
                        "code": "OVERLAPPING_PROFILE_PERIODS",
                        "venue_position_id": position_id,
                        "period_ids": [int(previous.id), int(current.id)],
                    }
                )

        open_periods = [row for row in ordered if row.valid_to is None]
        if position is not None and open_periods:
            current = open_periods[-1]
            if (
                position.member_user_id is None
                or int(current.member_user_id) != int(position.member_user_id)
                or position.pay_profile_id is None
                or int(current.pay_profile_id) != int(position.pay_profile_id)
            ):
                issues.append(
                    {
                        "code": "OPEN_PROFILE_PERIOD_DIFFERS_FROM_POSITION",
                        "venue_position_id": position_id,
                        "period_id": int(current.id),
                    }
                )

    return {
        "ok": not issues,
        "venue_id": int(venue_id) if venue_id is not None else None,
        "positions_checked": len(positions),
        "periods_checked": len(periods),
        "issues": issues,
        "warnings": warnings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only audit of effective-dated position payroll profiles")
    parser.add_argument("--venue-id", type=int, default=None)
    args = parser.parse_args()
    with SessionLocal() as db:
        result = audit_position_pay_profiles(db, venue_id=args.venue_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

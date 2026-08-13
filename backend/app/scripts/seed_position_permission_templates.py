"""Seed or refresh global position permission templates.

Usage:
  python -m app.scripts.seed_position_permission_templates
  python -m app.scripts.seed_position_permission_templates --reactivate
"""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.position_permission_template import PositionPermissionTemplate
from app.services.position_permission_templates import ensure_default_templates


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed default position permission templates")
    parser.add_argument("--reactivate", action="store_true", help="reactivate inactive system templates while seeding")
    args = parser.parse_args()

    with SessionLocal() as db:
        result = ensure_default_templates(db, reactivate=bool(args.reactivate))
        db.commit()
        rows = (
            db.execute(
                select(PositionPermissionTemplate)
                .where(PositionPermissionTemplate.scope == "GLOBAL")
                .order_by(PositionPermissionTemplate.sort_order.asc(), PositionPermissionTemplate.id.asc())
            )
            .scalars()
            .all()
        )
        print(
            f"Position permission templates seed done. created={int(result.get('created', 0))}, updated={int(result.get('updated', 0))}, total={len(rows)}"
        )
        for row in rows:
            status = "active" if bool(getattr(row, "is_active", True)) else "inactive"
            system = "system" if bool(getattr(row, "is_system", False)) else "custom"
            print(f" - #{int(row.id)} {row.code} :: {row.title} [{status}, {system}]")


if __name__ == "__main__":
    main()

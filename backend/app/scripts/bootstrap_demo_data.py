from __future__ import annotations

import argparse

from app.core.db import SessionLocal
from app.services.demo.bootstrap import bootstrap_demo_venue
from app.services.demo.session import get_public_demo_venue


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap demo venue with sample Axelio data")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--venue-id", type=int, default=None)
    target.add_argument(
        "--current-public-demo",
        action="store_true",
        default=False,
        help="Пересобрать текущее публичное DEMO venue вместо создания нового",
    )
    parser.add_argument("--venue-name", type=str, default=None)
    parser.add_argument("--reference-year", type=int, default=2026)
    parser.add_argument("--reference-month", type=int, default=3)
    parser.add_argument(
        "--history-months",
        type=int,
        default=1,
        help="Количество месяцев истории до reference month включительно (1-24)",
    )
    parser.add_argument("--make-public", action="store_true", default=False)
    parser.add_argument("--export-fixture-after", action="store_true", default=False)
    parser.add_argument("--fixture-path", type=str, default=None)
    args = parser.parse_args()

    with SessionLocal() as db:
        venue_id = args.venue_id
        venue_name = args.venue_name
        if args.current_public_demo:
            public_demo = get_public_demo_venue(db)
            if public_demo is None:
                parser.error("Текущее публичное DEMO venue не найдено")
            venue_id = int(public_demo.id)
            venue_name = venue_name or str(public_demo.name or "")
        result = bootstrap_demo_venue(
            db,
            venue_id=venue_id,
            venue_name=venue_name or "Axelio DEMO · Hookah Lounge",
            reference_year=args.reference_year,
            reference_month=args.reference_month,
            history_months=args.history_months,
            make_public=bool(args.make_public),
            export_fixture_after=bool(args.export_fixture_after),
            export_fixture_path=args.fixture_path,
        )
        db.commit()

    print(f"venue_id={result.venue_id}")
    print(f"venue_name={result.venue_name}")
    print(f"reference={result.reference_year}-{result.reference_month:02d}")
    print(
        f"period={result.period_start_year}-{result.period_start_month:02d}..{result.reference_year}-{result.reference_month:02d}"
    )
    print(f"history_months={result.history_months}")
    print(f"fixture_path={result.fixture_path}")
    print(f"counts={result.counts}")
    if result.warnings:
        print(f"warnings={result.warnings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

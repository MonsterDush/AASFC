from __future__ import annotations

import argparse

from app.core.db import SessionLocal
from app.services.demo.bootstrap import bootstrap_demo_venue


def main() -> int:
    parser = argparse.ArgumentParser(description='Bootstrap demo venue with sample Axelio data')
    parser.add_argument('--venue-id', type=int, default=None)
    parser.add_argument('--venue-name', type=str, default='Axelio DEMO · Hookah Lounge')
    parser.add_argument('--reference-year', type=int, default=2026)
    parser.add_argument('--reference-month', type=int, default=3)
    parser.add_argument('--make-public', action='store_true', default=False)
    parser.add_argument('--export-fixture-after', action='store_true', default=False)
    parser.add_argument('--fixture-path', type=str, default=None)
    args = parser.parse_args()

    with SessionLocal() as db:
        result = bootstrap_demo_venue(
            db,
            venue_id=args.venue_id,
            venue_name=args.venue_name,
            reference_year=args.reference_year,
            reference_month=args.reference_month,
            make_public=bool(args.make_public),
            export_fixture_after=bool(args.export_fixture_after),
            export_fixture_path=args.fixture_path,
        )
        db.commit()

    print(f'venue_id={result.venue_id}')
    print(f'venue_name={result.venue_name}')
    print(f'reference={result.reference_year}-{result.reference_month:02d}')
    print(f'fixture_path={result.fixture_path}')
    print(f'counts={result.counts}')
    if result.warnings:
        print(f'warnings={result.warnings}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

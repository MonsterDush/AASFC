from __future__ import annotations

import argparse

from app.core.db import SessionLocal
from app.services.demo.fixture import export_demo_fixture, get_demo_fixture_status


def main() -> int:
    parser = argparse.ArgumentParser(description='Export current DEMO venue fixture to JSON')
    parser.add_argument('--venue-id', type=int, default=None)
    parser.add_argument('--fixture-path', type=str, default=None)
    args = parser.parse_args()

    with SessionLocal() as db:
        status = get_demo_fixture_status(db, fixture_path=args.fixture_path)
        venue_id = int(args.venue_id or ((status.get('venue') or {}).get('id') or 0))
        if not venue_id:
            raise SystemExit('No DEMO venue configured. Pass --venue-id or enable a DEMO venue first.')
        result = export_demo_fixture(db, venue_id=venue_id, fixture_path=args.fixture_path)
        db.commit()

    print(f'fixture_path={result.fixture_path}')
    print(f'venue_id={result.venue_id}')
    print(f'venue_name={result.venue_name}')
    print(f'counts={result.counts}')
    if result.warnings:
        print(f'warnings={result.warnings}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

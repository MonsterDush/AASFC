from __future__ import annotations

import argparse

from app.core.db import SessionLocal
from app.services.demo.fixture import reset_demo_fixture


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset DEMO venue from JSON fixture")
    parser.add_argument("--venue-id", type=int, default=None)
    parser.add_argument("--fixture-path", type=str, default=None)
    args = parser.parse_args()

    with SessionLocal() as db:
        result = reset_demo_fixture(db, fixture_path=args.fixture_path, venue_id=args.venue_id)
        db.commit()

    print(f"fixture_path={result.fixture_path}")
    print(f"venue_id={result.venue_id}")
    print(f"venue_name={result.venue_name}")
    print(f"counts={result.counts}")
    if result.warnings:
        print(f"warnings={result.warnings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
from datetime import date
import json

from app.core.db import SessionLocal
from app.integrations.providers.quickresto.expanded_sync import sync_quickresto_expanded_connection
from app.models.quickresto_connection import QuickRestoConnection


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected an ISO date (YYYY-MM-DD)") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run isolated Quick Resto v0.4 Stage 3 canonical sync")
    parser.add_argument("--connection-id", type=int, required=True)
    parser.add_argument("--period-start", type=_date, required=True)
    parser.add_argument("--period-end-exclusive", type=_date, required=True)
    args = parser.parse_args(argv)
    if args.period_end_exclusive <= args.period_start:
        parser.error("--period-end-exclusive must be later than --period-start")

    with SessionLocal() as db:
        connection = db.get(QuickRestoConnection, int(args.connection_id))
        if connection is None:
            parser.error("QuickResto connection was not found")
        result = sync_quickresto_expanded_connection(
            db,
            connection=connection,
            period_start=args.period_start,
            period_end_exclusive=args.period_end_exclusive,
        )
        print(
            json.dumps(
                {
                    "connection_id": int(connection.id),
                    "venue_id": int(connection.venue_id),
                    "counts": result.counts,
                    "raw_objects": len(result.raw_object_ids),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

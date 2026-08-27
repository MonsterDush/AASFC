from __future__ import annotations

import json

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.quickresto_connection import QuickRestoConnection
from app.services.integrations.quickresto_sync import QuickRestoSyncError, sync_quickresto_connection


def main() -> int:
    with SessionLocal() as db:
        connection_ids = list(
            db.execute(
                select(QuickRestoConnection.id).where(
                    QuickRestoConnection.is_active.is_(True),
                    QuickRestoConnection.auto_sync_enabled.is_(True),
                )
            ).scalars()
        )

    results: list[dict] = []
    failed = False
    for connection_id in connection_ids:
        with SessionLocal() as db:
            connection = db.get(QuickRestoConnection, int(connection_id))
            if connection is None:
                continue
            try:
                run = sync_quickresto_connection(
                    db,
                    connection=connection,
                    requested_by_user_id=None,
                    trigger="SCHEDULED",
                )
                results.append(
                    {
                        "connection_id": int(connection.id),
                        "venue_id": int(connection.venue_id),
                        "run_id": int(run.id),
                        "status": run.status,
                    }
                )
                failed = failed or run.status not in {"SUCCEEDED", "PARTIAL"}
            except QuickRestoSyncError as exc:
                failed = True
                results.append(
                    {
                        "connection_id": int(connection.id),
                        "venue_id": int(connection.venue_id),
                        "status": "FAILED",
                        "error": str(exc),
                    }
                )
    print(json.dumps({"connections": len(connection_ids), "results": results}, ensure_ascii=False))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

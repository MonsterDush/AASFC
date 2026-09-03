from __future__ import annotations

import json

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.quickresto_connection import QuickRestoConnection
from app.services.integrations.quickresto_issues import purge_expired_source_snapshots
from app.services.integrations.quickresto_sync import QuickRestoSyncError, sync_quickresto_connection


def main() -> int:
    with SessionLocal() as db:
        expired_snapshots_purged = purge_expired_source_snapshots(db)
        db.commit()
        candidate_rows = list(
            db.execute(
                select(
                    QuickRestoConnection.id,
                    QuickRestoConnection.venue_id,
                    QuickRestoConnection.scope_status,
                ).where(
                    QuickRestoConnection.is_active.is_(True),
                    QuickRestoConnection.auto_sync_enabled.is_(True),
                )
            )
        )
        connection_ids = [
            int(connection_id)
            for connection_id, _venue_id, scope_status in candidate_rows
            if str(scope_status or "").upper() == "READY"
        ]
        scope_blocked = [
            {
                "connection_id": int(connection_id),
                "venue_id": int(venue_id),
                "scope_status": str(scope_status or "NEEDS_SELECTION"),
            }
            for connection_id, venue_id, scope_status in candidate_rows
            if str(scope_status or "").upper() != "READY"
        ]

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
    print(
        json.dumps(
            {
                "connections": len(connection_ids),
                "scope_blocked": scope_blocked,
                "expired_snapshots_purged": expired_snapshots_purged,
                "results": results,
            },
            ensure_ascii=False,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

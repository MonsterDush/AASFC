from __future__ import annotations

import json

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_import_batch import QuickRestoImportBatch
from app.services.integrations.quickresto_import_batches import (
    process_quickresto_import_batch,
    reclaim_stale_quickresto_import_batches,
)
from app.services.integrations.quickresto_issues import purge_expired_source_snapshots
from app.services.integrations.quickresto_sync import QuickRestoSyncError, sync_quickresto_connection


def main() -> int:
    with SessionLocal() as db:
        expired_snapshots_purged = purge_expired_source_snapshots(db)
        recovered_batches = reclaim_stale_quickresto_import_batches(db)
        db.commit()
        queued_batch_ids = [
            int(value)
            for value in db.execute(
                select(QuickRestoImportBatch.id)
                .where(QuickRestoImportBatch.status == "PENDING")
                .order_by(QuickRestoImportBatch.created_at.asc(), QuickRestoImportBatch.id.asc())
            ).scalars()
        ]

    batch_results: list[dict] = []
    processed_batch_connection_ids: set[int] = set()
    failed = False
    for batch_id in queued_batch_ids:
        with SessionLocal() as db:
            batch = db.get(QuickRestoImportBatch, int(batch_id))
            if batch is None:
                continue
            processed_batch_connection_ids.add(int(batch.connection_id))
            try:
                batch = process_quickresto_import_batch(db, batch_id=int(batch.id))
                batch_results.append(
                    {
                        "batch_id": int(batch.id),
                        "connection_id": int(batch.connection_id),
                        "status": str(batch.status),
                        "completed_periods": int(batch.completed_periods),
                        "total_periods": int(batch.total_periods),
                    }
                )
                failed = failed or str(batch.status).upper() == "FAILED"
            except QuickRestoSyncError as exc:
                failed = True
                batch_results.append(
                    {
                        "batch_id": int(batch_id),
                        "connection_id": int(batch.connection_id),
                        "status": "FAILED",
                        "error": str(exc),
                    }
                )

    with SessionLocal() as db:
        blocked_connection_ids = {
            int(value)
            for value in db.execute(
                select(QuickRestoImportBatch.connection_id).where(
                    QuickRestoImportBatch.status.in_(("PENDING", "RUNNING", "FAILED")),
                    QuickRestoImportBatch.next_period_start < QuickRestoImportBatch.period_end_exclusive,
                )
            ).scalars()
        }
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
            and int(connection_id) not in blocked_connection_ids
            and int(connection_id) not in processed_batch_connection_ids
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
                "monthly_batches": batch_results,
                "monthly_batches_recovered": recovered_batches,
                "expired_snapshots_purged": expired_snapshots_purged,
                "results": results,
            },
            ensure_ascii=False,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

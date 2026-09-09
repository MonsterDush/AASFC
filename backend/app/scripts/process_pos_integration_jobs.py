"""Enqueue due POS integration work and process one bounded batch.

Run every minute. CRITICAL sales/health work is claimed before NORMAL catalog
and inventory work, while historical and nightly reconciliation use BULK.
"""

from __future__ import annotations

import json

from app.core.db import SessionLocal
from app.integrations.sync.jobs import enqueue_due_jobs, process_next_job


def main(limit: int = 100) -> int:
    with SessionLocal() as db:
        queued = enqueue_due_jobs(db)
    results = []
    for _ in range(max(1, min(int(limit), 1000))):
        with SessionLocal() as db:
            job = process_next_job(db)
            if job is None:
                break
            results.append(
                {
                    "id": int(job.id),
                    "connection_id": int(job.integration_connection_id),
                    "job_type": job.job_type,
                    "capability": job.capability,
                    "queue": job.queue,
                    "status": job.status,
                }
            )
    print(json.dumps({"queued": queued, "processed": len(results), "results": results}, ensure_ascii=False))
    return 1 if any(item["status"] == "FAILED" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())

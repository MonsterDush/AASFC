from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IntegrationSyncJob


class SyncStrategy(str, Enum):
    FULL_REFRESH = "FULL_REFRESH"
    DATE_RANGE = "DATE_RANGE"
    UPDATED_SINCE = "UPDATED_SINCE"
    REVISION = "REVISION"
    WEBHOOK_FIRST = "WEBHOOK_FIRST"
    REALTIME_POLL = "REALTIME_POLL"


class SyncQueue(str, Enum):
    REALTIME = "realtime"
    NORMAL = "normal"
    BULK = "bulk"


QUEUE_PRIORITIES = {SyncQueue.REALTIME: 10, SyncQueue.NORMAL: 100, SyncQueue.BULK: 200}

CAPABILITY_DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "TERMINALS": ("EXTERNAL_VENUES",),
    "TABLES": ("TERMINALS",),
    "PRODUCT_VARIANTS": ("PRODUCTS",),
    "MODIFIERS": ("PRODUCTS", "PRODUCT_VARIANTS"),
    "PAYMENTS": ("ORDERS",),
    "RECONCILIATION": ("ORDERS", "PAYMENTS"),
}


@dataclass(frozen=True, slots=True)
class SyncRequest:
    connection_id: int
    capability: str
    strategy: SyncStrategy
    queue: SyncQueue = SyncQueue.NORMAL
    period_start: date | None = None
    period_end_exclusive: date | None = None
    updated_since: datetime | None = None
    revision: str | None = None
    scope: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if (self.period_start is None) != (self.period_end_exclusive is None):
            raise ValueError("Both date range boundaries are required")
        if self.period_start and self.period_end_exclusive and self.period_end_exclusive <= self.period_start:
            raise ValueError("Sync date range must be positive")
        if self.strategy is SyncStrategy.DATE_RANGE and self.period_start is None:
            raise ValueError("DATE_RANGE strategy requires a date range")
        if self.strategy is SyncStrategy.UPDATED_SINCE and self.updated_since is None:
            raise ValueError("UPDATED_SINCE strategy requires a timestamp")
        if self.updated_since is not None and self.updated_since.tzinfo is None:
            raise ValueError("Sync timestamp must be timezone-aware")
        if self.strategy is SyncStrategy.REVISION and not self.revision:
            raise ValueError("REVISION strategy requires a revision")
        if self.strategy is SyncStrategy.REALTIME_POLL and self.queue is not SyncQueue.REALTIME:
            raise ValueError("REALTIME_POLL strategy requires the realtime queue")

    def payload(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "period_start": self.period_start.isoformat() if self.period_start else None,
            "period_end_exclusive": self.period_end_exclusive.isoformat() if self.period_end_exclusive else None,
            "updated_since": self.updated_since.isoformat() if self.updated_since else None,
            "revision": self.revision,
            "scope": self.scope,
        }


def ordered_capabilities(capabilities: list[str]) -> tuple[str, ...]:
    """Topologically order requested capabilities and their known prerequisites."""

    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(capability: str) -> None:
        normalized = capability.strip().upper()
        if normalized in visited:
            return
        if normalized in visiting:
            raise ValueError(f"Cyclic sync capability dependency: {normalized}")
        visiting.add(normalized)
        for dependency in CAPABILITY_DEPENDENCIES.get(normalized, ()):
            visit(dependency)
        visiting.remove(normalized)
        visited.add(normalized)
        ordered.append(normalized)

    for capability in capabilities:
        visit(capability)
    return tuple(ordered)


def schedule_sync(db: Session, request: SyncRequest) -> tuple[IntegrationSyncJob, bool]:
    canonical = json.dumps(request.payload(), sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(
        f"{request.connection_id}:{request.capability}:{canonical}".encode("utf-8")
    ).hexdigest()
    idempotency_key = f"sync:v1:{fingerprint}"
    existing = db.scalar(select(IntegrationSyncJob).where(IntegrationSyncJob.idempotency_key == idempotency_key))
    if existing is not None:
        return existing, False

    job = IntegrationSyncJob(
        connection_id=request.connection_id,
        job_type="CAPABILITY_SYNC",
        capability=request.capability,
        queue=request.queue.value,
        priority=QUEUE_PRIORITIES[request.queue],
        idempotency_key=idempotency_key,
        job_payload_json=request.payload(),
    )
    db.add(job)
    db.flush()
    return job, True


class IntegrationSyncCoordinator:
    """Provider-neutral scheduling facade for historical and realtime sync."""

    def __init__(self, db: Session):
        self._db = db

    def plan(self, capabilities: list[str]) -> tuple[str, ...]:
        return ordered_capabilities(capabilities)

    def schedule(self, request: SyncRequest) -> tuple[IntegrationSyncJob, bool]:
        return schedule_sync(self._db, request)

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from typing import Any, Mapping

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.pos_report_projection import POSReportProjection
from app.models.report_value_contribution import ReportValueContribution


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ShadowProjectionCandidate:
    daily_report_id: int
    connection_id: int
    business_date: date
    shift_slot: str
    sync_run_id: int
    status: str
    aggregate_hash: str
    canonical_coverage_hash: str
    shift_count: int
    mapping_version: int
    policy_version: int
    summary_json: Mapping[str, Any]
    facts: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ShadowProjectionResult:
    projection: POSReportProjection
    updated: bool


class ReportProjector:
    """Persist provider-neutral report facts without touching another source's contributions."""

    def persist_shadow(self, db: Session, *, candidate: ShadowProjectionCandidate) -> ShadowProjectionResult:
        projection = db.execute(
            select(POSReportProjection).where(
                POSReportProjection.connection_id == int(candidate.connection_id),
                POSReportProjection.business_date == candidate.business_date,
                POSReportProjection.shift_slot == str(candidate.shift_slot),
            )
        ).scalar_one_or_none()
        preserve_confirmed_projection = (
            projection is not None
            and str(projection.status) == "MATCHED"
            and str(candidate.status) == "FAILED"
        )
        updated = projection is None or not preserve_confirmed_projection
        if projection is None:
            projection = POSReportProjection(
                daily_report_id=int(candidate.daily_report_id),
                connection_id=int(candidate.connection_id),
                business_date=candidate.business_date,
                shift_slot=str(candidate.shift_slot),
                aggregate_hash=str(candidate.aggregate_hash),
                mapping_version=int(candidate.mapping_version),
                policy_version=int(candidate.policy_version),
                shift_count=int(candidate.shift_count),
                canonical_coverage_hash=str(candidate.canonical_coverage_hash),
                last_sync_run_id=int(candidate.sync_run_id),
                status=str(candidate.status),
                summary_json=dict(candidate.summary_json),
            )
            db.add(projection)
        elif updated:
            projection.daily_report_id = int(candidate.daily_report_id)
            projection.aggregate_hash = str(candidate.aggregate_hash)
            projection.mapping_version = int(candidate.mapping_version)
            projection.policy_version = int(candidate.policy_version)
            projection.shift_count = int(candidate.shift_count)
            projection.canonical_coverage_hash = str(candidate.canonical_coverage_hash)
            projection.last_sync_run_id = int(candidate.sync_run_id)
            projection.status = str(candidate.status)
            projection.summary_json = dict(candidate.summary_json)
            projection.updated_at = _utcnow()
        db.flush()
        if candidate.status == "MATCHED":
            self._replace_pos_contributions(
                db,
                report_id=int(candidate.daily_report_id),
                projection_id=int(projection.id),
                aggregate_hash=str(candidate.aggregate_hash),
                canonical_coverage_hash=str(candidate.canonical_coverage_hash),
                facts=candidate.facts,
            )
        return ShadowProjectionResult(projection=projection, updated=updated)

    @staticmethod
    def _replace_pos_contributions(
        db: Session,
        *,
        report_id: int,
        projection_id: int,
        aggregate_hash: str,
        canonical_coverage_hash: str,
        facts: Mapping[str, Any],
    ) -> None:
        db.execute(
            delete(ReportValueContribution).where(
                ReportValueContribution.report_id == int(report_id),
                ReportValueContribution.source_type == "POS",
            )
        )
        contributions: list[tuple[str, int, int]] = [
            ("REVENUE", 0, int(facts.get("revenue_total") or 0)),
            ("UNALLOCATED_REVENUE", 0, int(facts.get("unallocated_revenue_total") or 0)),
            ("WRITEOFF", 0, int(facts.get("writeoff_total") or 0)),
            ("RETURN", 0, int(facts.get("refund_total") or 0)),
            ("DISCOUNT", 0, int(facts.get("discount_total") or 0)),
        ]
        for kind, aggregate_key in (
            ("PAYMENT", "payments_internal"),
            ("DEPT", "departments_internal"),
            ("KPI", "kpis_internal"),
        ):
            contributions.extend(
                (kind, int(ref_id), int(value))
                for ref_id, value in (facts.get(aggregate_key) or {}).items()
                if int(value)
            )
        for kind, ref_id, value in contributions:
            source_id = f"POSReportProjection:{int(projection_id)}:{kind}:{int(ref_id)}"
            db.add(
                ReportValueContribution(
                    report_id=int(report_id),
                    kind=kind,
                    ref_id=int(ref_id),
                    source_type="POS",
                    source_id=source_id,
                    value_numeric=Decimal(value),
                    source_hash=_stable_hash(
                        {
                            "aggregate_hash": aggregate_hash,
                            "canonical_coverage_hash": canonical_coverage_hash,
                            "kind": kind,
                            "ref_id": int(ref_id),
                            "value": int(value),
                        }
                    ),
                )
            )

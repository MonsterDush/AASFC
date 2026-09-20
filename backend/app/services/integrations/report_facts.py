from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
import hashlib
import json
from typing import Iterable

from sqlalchemy import delete, inspect, select
from sqlalchemy.orm import Session

from app.integrations.feature_flags import feature_flags_for
from app.models import (
    DailyReport,
    DailyReportValue,
    IntegrationConnection,
    POSReportProjection,
    ReportValueContribution,
)


MANUAL = "MANUAL"
POS_CANONICAL = "POS_CANONICAL"


@dataclass(frozen=True, slots=True)
class ReportFactValue:
    kind: str
    ref_id: int
    value_numeric: int


@dataclass(frozen=True, slots=True)
class ReportFacts:
    report_id: int
    venue_id: int
    report_date: date
    shift_slot: str
    status: str
    source_mode: str
    revenue_total: int
    unallocated_revenue_total: int
    values: tuple[ReportFactValue, ...] = field(default_factory=tuple)

    def values_for(self, kind: str) -> tuple[ReportFactValue, ...]:
        normalized = str(kind or "").upper()
        return tuple(value for value in self.values if value.kind == normalized)


def _numeric_int(value: object) -> int:
    if isinstance(value, Decimal):
        return int(value)
    return int(value or 0)


def _stable_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _table_exists(db: Session, table_name: str) -> bool:
    cache = db.info.setdefault("report_facts_table_presence", {})
    if table_name in cache:
        return bool(cache[table_name])
    try:
        exists = inspect(db.connection()).has_table(table_name)
    except Exception:
        exists = False
    cache[table_name] = bool(exists)
    return bool(exists)


def sync_manual_report_contributions(
    db: Session,
    *,
    report: DailyReport,
    values: Iterable[DailyReportValue] | None = None,
) -> None:
    """Mirror an editable report into provider-neutral MANUAL contributions.

    MANUAL and POS contributions deliberately coexist. Updating a report only
    replaces its MANUAL rows and can never erase the canonical POS projection.
    """

    if not _table_exists(db, ReportValueContribution.__tablename__):
        # During a rolling deploy an older database can briefly serve a newer
        # worker. The legacy write remains authoritative until the migration
        # creates and backfills the canonical table.
        return
    if report.id is None:
        db.flush()
    value_rows = list(values) if values is not None else list(
        db.execute(
            select(DailyReportValue).where(DailyReportValue.report_id == int(report.id))
        ).scalars()
    )
    aggregated: dict[tuple[str, int], int] = defaultdict(int)
    aggregated[("REVENUE", 0)] = int(report.revenue_total or 0)
    aggregated[("UNALLOCATED_REVENUE", 0)] = int(report.unallocated_revenue_total or 0)
    for row in value_rows:
        aggregated[(str(row.kind).upper(), int(row.ref_id))] += int(row.value_numeric or 0)

    db.execute(
        delete(ReportValueContribution).where(
            ReportValueContribution.report_id == int(report.id),
            ReportValueContribution.source_type == "MANUAL",
        )
    )
    for (kind, ref_id), value in sorted(aggregated.items()):
        source_id = f"DailyReport:{int(report.id)}:{kind}:{int(ref_id)}"
        db.add(
            ReportValueContribution(
                report_id=int(report.id),
                kind=kind,
                ref_id=int(ref_id),
                source_type="MANUAL",
                source_id=source_id,
                value_numeric=Decimal(value),
                source_hash=_stable_hash(
                    {
                        "report_id": int(report.id),
                        "kind": kind,
                        "ref_id": int(ref_id),
                        "value": int(value),
                    }
                ),
            )
        )
    db.flush()


def _contribution_facts(
    db: Session,
    *,
    report: DailyReport,
    source_type: str,
    source_mode: str,
) -> ReportFacts | None:
    rows = list(
        db.execute(
            select(ReportValueContribution)
            .where(
                ReportValueContribution.report_id == int(report.id),
                ReportValueContribution.source_type == str(source_type),
            )
            .order_by(ReportValueContribution.kind.asc(), ReportValueContribution.ref_id.asc())
        ).scalars()
    )
    if not rows:
        return None
    scalar_values = {(str(row.kind), int(row.ref_id)): _numeric_int(row.value_numeric) for row in rows}
    values = tuple(
        ReportFactValue(
            kind=str(row.kind),
            ref_id=int(row.ref_id),
            value_numeric=_numeric_int(row.value_numeric),
        )
        for row in rows
        if str(row.kind) in {"PAYMENT", "DEPT", "KPI"}
    )
    return ReportFacts(
        report_id=int(report.id),
        venue_id=int(report.venue_id),
        report_date=report.date,
        shift_slot=str(report.shift_slot or "DAY"),
        status=str(report.status or "DRAFT"),
        source_mode=source_mode,
        revenue_total=scalar_values.get(("REVENUE", 0), 0),
        unallocated_revenue_total=scalar_values.get(("UNALLOCATED_REVENUE", 0), 0),
        values=values,
    )


def _manual_facts(db: Session, report: DailyReport) -> ReportFacts:
    if not _table_exists(db, ReportValueContribution.__tablename__):
        values = tuple(
            ReportFactValue(kind=str(row.kind), ref_id=int(row.ref_id), value_numeric=int(row.value_numeric or 0))
            for row in db.execute(
                select(DailyReportValue)
                .where(DailyReportValue.report_id == int(report.id))
                .order_by(DailyReportValue.kind.asc(), DailyReportValue.ref_id.asc())
            ).scalars()
        )
        return ReportFacts(
            report_id=int(report.id),
            venue_id=int(report.venue_id),
            report_date=report.date,
            shift_slot=str(report.shift_slot or "DAY"),
            status=str(report.status or "DRAFT"),
            source_mode=MANUAL,
            revenue_total=int(report.revenue_total or 0),
            unallocated_revenue_total=int(report.unallocated_revenue_total or 0),
            values=values,
        )
    facts = _contribution_facts(db, report=report, source_type="MANUAL", source_mode=MANUAL)
    if facts is not None:
        return facts

    # The migration backfills existing reports and every supported write path
    # mirrors new edits. This final compatibility guard canonicalizes reports
    # created by maintenance scripts or older workers during a rolling deploy.
    sync_manual_report_contributions(db, report=report)
    facts = _contribution_facts(db, report=report, source_type="MANUAL", source_mode=MANUAL)
    if facts is None:  # pragma: no cover - scalar rows make this unreachable
        raise RuntimeError(f"Unable to canonicalize report {report.id}")
    return facts


def _matched_projection(db: Session, report: DailyReport) -> POSReportProjection | None:
    if not _table_exists(db, POSReportProjection.__tablename__):
        return None
    return db.execute(
        select(POSReportProjection).where(
            POSReportProjection.daily_report_id == int(report.id),
            POSReportProjection.status == "MATCHED",
        )
    ).scalar_one_or_none()


def _canonical_facts(db: Session, report: DailyReport) -> ReportFacts | None:
    if _matched_projection(db, report) is None:
        return None
    return _contribution_facts(db, report=report, source_type="POS", source_mode=POS_CANONICAL)


def effective_source_mode(db: Session, *, report: DailyReport) -> str:
    """Resolve the source automatically; users never choose a report backend."""

    projection = _matched_projection(db, report)
    if projection is None:
        return MANUAL
    connection = db.get(IntegrationConnection, int(projection.connection_id))
    if connection is None or int(connection.venue_id) != int(report.venue_id):
        return MANUAL
    flags = feature_flags_for(connection.provider)
    if not flags.canonical_read_enabled or not flags.provider_rollout_enabled:
        return MANUAL
    if str(connection.status) != "ACTIVE" or str(connection.read_mode) != POS_CANONICAL:
        return MANUAL
    return POS_CANONICAL


def load_report_facts(db: Session, *, report: DailyReport, force_mode: str | None = None) -> ReportFacts:
    mode = str(force_mode or effective_source_mode(db, report=report)).upper()
    if mode == POS_CANONICAL:
        canonical = _canonical_facts(db, report)
        if canonical is not None:
            return canonical
    return _manual_facts(db, report)


def load_period_report_facts(
    db: Session,
    *,
    venue_id: int,
    period_start: date,
    period_end_exclusive: date,
    closed_only: bool = True,
    force_mode: str | None = None,
) -> list[ReportFacts]:
    statement = select(DailyReport).where(
        DailyReport.venue_id == int(venue_id),
        DailyReport.date >= period_start,
        DailyReport.date < period_end_exclusive,
    )
    if closed_only:
        statement = statement.where(DailyReport.status == "CLOSED")
    reports = list(db.execute(statement.order_by(DailyReport.date.asc(), DailyReport.shift_slot.asc())).scalars())
    return [load_report_facts(db, report=report, force_mode=force_mode) for report in reports]

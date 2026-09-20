from __future__ import annotations

from datetime import date
from decimal import Decimal
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- register complete metadata
from app.core.config import settings
from app.core.db import Base
from app.integrations.canonical.order_items import attribution_minor_for_item
from app.models import (
    DailyReport,
    DailyReportValue,
    IntegrationConnection,
    POSReportProjection,
    ReportValueContribution,
    User,
    Venue,
)
from app.services.integrations.report_facts import (
    MANUAL,
    POS_CANONICAL,
    load_report_facts,
    sync_manual_report_contributions,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class POSIntegrationStageThreeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        self.db.add_all(
            [
                User(id=1, system_role="NONE"),
                Venue(id=1, name="Stage three", timezone="Europe/Moscow"),
            ]
        )
        self.db.flush()
        self.report = DailyReport(
            id=1,
            venue_id=1,
            date=date(2031, 3, 10),
            shift_slot="DAY",
            revenue_total=1_000,
            unallocated_revenue_total=100,
            status="CLOSED",
            created_by_user_id=1,
        )
        self.connection = IntegrationConnection(
            id=1,
            venue_id=1,
            provider="QUICKRESTO",
            status="ACTIVE",
            read_mode="LEGACY",
            shadow_sync_enabled=True,
            coverage_start=date(2031, 3, 1),
            coverage_end_exclusive=date(2031, 4, 1),
        )
        self.db.add_all([self.report, self.connection])
        self.db.flush()
        self.db.add(DailyReportValue(report_id=1, kind="DEPT", ref_id=10, value_numeric=900))
        self.db.flush()
        sync_manual_report_contributions(self.db, report=self.report)
        self.projection = POSReportProjection(
            daily_report_id=1,
            connection_id=1,
            business_date=self.report.date,
            shift_slot="DAY",
            aggregate_hash="a" * 64,
            mapping_version=1,
            policy_version=1,
            shift_count=1,
            canonical_coverage_hash="b" * 64,
            status="MATCHED",
            summary_json={},
        )
        self.db.add(self.projection)
        self.db.flush()
        self.db.add_all(
            [
                ReportValueContribution(
                    report_id=1,
                    kind="REVENUE",
                    ref_id=0,
                    source_type="POS",
                    source_id="projection:1:revenue",
                    value_numeric=Decimal("1200"),
                    source_hash="c" * 64,
                ),
                ReportValueContribution(
                    report_id=1,
                    kind="UNALLOCATED_REVENUE",
                    ref_id=0,
                    source_type="POS",
                    source_id="projection:1:unallocated",
                    value_numeric=Decimal("50"),
                    source_hash="d" * 64,
                ),
                ReportValueContribution(
                    report_id=1,
                    kind="DEPT",
                    ref_id=10,
                    source_type="POS",
                    source_id="projection:1:dept:10",
                    value_numeric=Decimal("1150"),
                    source_hash="e" * 64,
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _enabled_flags(self):
        return (
            patch.object(settings, "POS_INTEGRATION_PROVIDER_ROLLOUT", "QUICKRESTO"),
            patch.object(settings, "POS_INTEGRATION_CANONICAL_READ_ENABLED", True),
        )

    def test_source_is_resolved_automatically_without_user_policy(self):
        manual = load_report_facts(self.db, report=self.report)
        self.assertEqual(manual.source_mode, MANUAL)
        self.assertEqual(manual.revenue_total, 1_000)

        rollout, reads = self._enabled_flags()
        with rollout, reads:
            self.assertEqual(load_report_facts(self.db, report=self.report).source_mode, MANUAL)
            self.connection.read_mode = POS_CANONICAL
            self.db.flush()
            canonical = load_report_facts(self.db, report=self.report)
            self.assertEqual(canonical.source_mode, POS_CANONICAL)
            self.assertEqual(canonical.revenue_total, 1_200)
            self.assertEqual(canonical.values_for("DEPT")[0].value_numeric, 1_150)

        # The global flag is the instant rollback gate; MANUAL contributions
        # remained intact while canonical reads were enabled.
        fallback = load_report_facts(self.db, report=self.report)
        self.assertEqual(fallback.source_mode, MANUAL)
        self.assertEqual(fallback.revenue_total, 1_000)

    def test_unmatched_or_incomplete_projection_falls_back_to_manual(self):
        self.connection.read_mode = POS_CANONICAL
        self.projection.status = "MISMATCH"
        self.db.flush()
        rollout, reads = self._enabled_flags()
        with rollout, reads:
            self.assertEqual(load_report_facts(self.db, report=self.report).source_mode, MANUAL)

        self.projection.status = "MATCHED"
        self.db.execute(
            ReportValueContribution.__table__.delete().where(
                ReportValueContribution.report_id == 1,
                ReportValueContribution.source_type == "POS",
            )
        )
        self.db.flush()
        rollout, reads = self._enabled_flags()
        with rollout, reads:
            self.assertEqual(load_report_facts(self.db, report=self.report).source_mode, MANUAL)

    def test_manual_edit_replaces_only_manual_contributions(self):
        self.report.revenue_total = 1_050
        sync_manual_report_contributions(self.db, report=self.report)
        rows = list(
            self.db.execute(select(ReportValueContribution).where(ReportValueContribution.report_id == 1)).scalars()
        )
        self.assertTrue(any(row.source_type == "POS" for row in rows))
        manual_revenue = next(row for row in rows if row.source_type == "MANUAL" and row.kind == "REVENUE")
        self.assertEqual(int(manual_revenue.value_numeric), 1_050)

    def test_composite_item_attribution_never_double_counts_parent_charge(self):
        parent = SimpleNamespace(
            parent_item_id=None,
            included_in_parent=False,
            net_amount=Decimal("1000"),
            attributed_net_amount=Decimal("0"),
        )
        primary = SimpleNamespace(
            parent_item_id=1,
            included_in_parent=True,
            net_amount=Decimal("1000"),
            attributed_net_amount=Decimal("700"),
        )
        secondary = SimpleNamespace(
            parent_item_id=1,
            included_in_parent=True,
            net_amount=Decimal("1000"),
            attributed_net_amount=Decimal("300"),
        )
        self.assertEqual(
            sum(attribution_minor_for_item(item) for item in (parent, primary, secondary)),
            100_000,
        )
        unresolved_component = SimpleNamespace(
            parent_item_id=1,
            included_in_parent=True,
            net_amount=Decimal("1000"),
            attributed_net_amount=None,
        )
        fallback_parent = SimpleNamespace(
            parent_item_id=None,
            included_in_parent=False,
            net_amount=Decimal("1000"),
            attributed_net_amount=None,
        )
        self.assertEqual(attribution_minor_for_item(unresolved_component), 0)
        self.assertEqual(attribution_minor_for_item(fallback_parent), 100_000)


class StageThreeNotificationRegressionTests(unittest.TestCase):
    def test_successful_auto_import_does_not_enqueue_user_notification(self):
        from app.services.integrations.quickresto_sync import _enqueue_sync_notification_safely

        db = Mock()
        _enqueue_sync_notification_safely(
            db,
            connection=SimpleNamespace(venue_id=1, id=1),
            run=SimpleNamespace(
                id=2,
                status="SUCCEEDED",
                trigger="SCHEDULED",
                shifts_seen=1,
                shifts_imported=1,
                reports_created=0,
                reports_updated=1,
                reports_unchanged=0,
            ),
            issue_count=0,
            force=True,
        )
        db.commit.assert_not_called()
        db.add.assert_not_called()

    def test_shift_backed_salary_component_is_available_for_slot_notification(self):
        from app.services.payroll.day_breakdown import DayAllocationContext, _component_allocation_for_day

        target = date(2031, 3, 10)
        context = DayAllocationContext(
            shift_slot="DAY",
            month_dates=[target],
            worked_dates=[target],
            minutes_by_date={target: 480},
            shifts_by_date={target: 1},
            revenue_by_date_minor={target: 0},
            department_revenue_by_date_minor={},
            kpi_by_date={},
        )
        item = _component_allocation_for_day(
            component={
                "component_type": "SALARY_PER_SHIFT",
                "amount_minor": 300_000,
                "shift_rows": [
                    {
                        "date": target.isoformat(),
                        "shift_slot": "DAY",
                        "amount_minor": 300_000,
                        "applied_rate_minor": 300_000,
                    },
                    {
                        "date": target.isoformat(),
                        "shift_slot": "NIGHT",
                        "amount_minor": 400_000,
                        "applied_rate_minor": 400_000,
                    },
                ],
            },
            target_date=target,
            context=context,
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["amount_minor"], 300_000)

from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.daily_report import DailyReport
from app.models.daily_report_value import DailyReportValue
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.user import User
from app.models.venue import Venue
from app.services.integrations.quickresto_sync import sync_quickresto_connection


TARGET_DATE = date(2030, 1, 15)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class FixtureQuickRestoClient:
    def __init__(self, *, shifts, orders, payment_types, departments):
        self.shifts = shifts
        self.orders = orders
        self.payment_types = payment_types
        self.departments = departments
        self.orders_by_id = {int(item["id"]): item for item in orders}

    def list_all_objects(self, *, module_name, class_name):
        del module_name
        if class_name.endswith("PaymentType"):
            return deepcopy(self.payment_types)
        if class_name.endswith("DishCategory"):
            return deepcopy(self.departments)
        if class_name.endswith("Shift"):
            return deepcopy(self.shifts)
        if class_name.endswith("OrderInfo"):
            return deepcopy(self.orders)
        raise AssertionError(f"Unexpected QuickResto class: {class_name}")

    def read_object(self, *, module_name, class_name, object_id):
        del module_name, class_name
        return deepcopy(self.orders_by_id[int(object_id)])


class QuickRestoSyncIntegrationTests(unittest.TestCase):
    def test_closed_shifts_auto_close_legacy_draft_and_remain_idempotent(self):
        fixture_path = Path(__file__).parent / "fixtures" / "quickresto" / "complex_same_day_shifts.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        shifts = deepcopy(fixture["shifts"])
        for shift in shifts:
            shift["localClosedTime"] = shift["localClosedTime"].replace(fixture["report_date"], TARGET_DATE.isoformat())

        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Venue.__table__,
                PaymentMethod.__table__,
                Department.__table__,
                DailyReport.__table__,
                DailyReportValue.__table__,
                QuickRestoConnection.__table__,
                QuickRestoPaymentMapping.__table__,
                QuickRestoDepartmentMapping.__table__,
                QuickRestoSyncRun.__table__,
                QuickRestoShiftImport.__table__,
                QuickRestoReportImport.__table__,
            ],
        )
        with Session(engine) as db:
            venue_id = 1
            user_id = 1
            db.add(User(id=user_id, system_role="NONE"))
            db.add(Venue(id=venue_id, name="QuickResto integration test"))
            payment_methods = {
                code: PaymentMethod(
                    venue_id=venue_id,
                    code=code,
                    title=title,
                    is_active=True,
                    sort_order=sort_order,
                )
                for sort_order, (code, title) in enumerate(
                    (("cash", "Наличные"), ("cashless", "Эквайринг"), ("bonus", "Бонусы")),
                    start=1,
                )
            }
            departments = [
                Department(
                    venue_id=venue_id,
                    code=code,
                    title=title,
                    is_active=True,
                    sort_order=sort_order,
                )
                for sort_order, (code, title) in enumerate(
                    (("hookah", "Кальянный зал"), ("bar", "Бар")),
                    start=1,
                )
            ]
            db.add_all([*payment_methods.values(), *departments])
            db.flush()

            empty_report = DailyReport(
                venue_id=venue_id,
                date=TARGET_DATE,
                shift_slot="DAY",
                cash=0,
                cashless=0,
                revenue_total=0,
                tips_total=0,
                status="DRAFT",
                created_by_user_id=user_id,
            )
            db.add(empty_report)
            db.flush()

            connection = QuickRestoConnection(
                venue_id=venue_id,
                cloud="fixture",
                api_login_encrypted="v1:unused",
                api_password_encrypted="v1:unused",
                is_active=True,
                auto_sync_enabled=False,
                business_day_cutoff_hour=0,
                sync_from_date=TARGET_DATE,
                created_by_user_id=user_id,
            )
            db.add(connection)
            db.commit()
            db.refresh(connection)

            client = FixtureQuickRestoClient(
                shifts=shifts,
                orders=fixture["orders"],
                payment_types=[
                    {"id": 1, "name": payment_methods["cash"].title, "operationType": "payment"},
                    {
                        "id": 2,
                        "name": payment_methods["cashless"].title,
                        "operationType": "payment",
                    },
                    {"id": 3, "name": payment_methods["bonus"].title, "operationType": "payment"},
                    {"id": 7, "name": "Все бесплатно!!!", "operationType": "writeoff"},
                ],
                departments=[
                    {"id": 6, "name": departments[0].title},
                    {"id": 7, "name": departments[1].title},
                ],
            )

            close_side_effects = (
                "_rebuild_report_tip_allocations",
                "rebuild_revenue_entries_for_report",
                "sync_daily_recurring_accruals_for_date",
                "_recalculate_payroll_for_dates",
                "_enqueue_day_economics_summary_job",
                "_enqueue_salary_day_breakdown_job",
                "_enqueue_soft_alerts_job",
            )
            patchers = [patch(f"app.routers.venue_reports.{name}") for name in close_side_effects]
            mocked_side_effects = [patcher.start() for patcher in patchers]
            self.addCleanup(lambda: [patcher.stop() for patcher in reversed(patchers)])

            first = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=user_id,
                trigger="E2E",
                client=client,
            )
            self.assertEqual(first.status, "SUCCEEDED")
            self.assertEqual(first.shifts_imported, 3)
            self.assertEqual(first.reports_created, 0)
            self.assertEqual(first.reports_updated, 1)
            self.assertEqual(first.summary_json["conflicts"], [])

            report = db.execute(
                select(DailyReport).where(
                    DailyReport.venue_id == venue_id,
                    DailyReport.date == TARGET_DATE,
                    DailyReport.shift_slot == "DAY",
                )
            ).scalar_one()
            self.assertEqual(report.id, empty_report.id)
            self.assertEqual(report.status, "CLOSED")
            self.assertEqual(report.closed_by_user_id, user_id)
            self.assertIsNotNone(report.closed_at)
            self.assertEqual(report.revenue_total, 23_900)
            self.assertEqual(report.cash, 6_600)
            self.assertEqual(report.cashless, 16_300)
            self.assertEqual(
                len(
                    db.execute(
                        select(QuickRestoShiftImport).where(QuickRestoShiftImport.connection_id == connection.id)
                    )
                    .scalars()
                    .all()
                ),
                3,
            )
            source = db.execute(
                select(QuickRestoReportImport).where(QuickRestoReportImport.connection_id == connection.id)
            ).scalar_one()
            self.assertEqual(source.writeoff_total, 4_600)
            self.assertEqual(source.discount_total, 600)
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 1)

            # Simulate a report imported by the previous integration version,
            # which stored a matching source but left the report as a draft.
            report.status = "DRAFT"
            report.closed_by_user_id = None
            report.closed_at = None
            db.commit()

            second = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=user_id,
                trigger="E2E",
                client=client,
            )
            self.assertEqual(second.status, "SUCCEEDED")
            self.assertEqual(second.shifts_imported, 0)
            self.assertEqual(second.reports_created, 0)
            self.assertEqual(second.reports_updated, 1)
            self.assertEqual(second.reports_unchanged, 0)
            db.refresh(report)
            self.assertEqual(report.status, "CLOSED")
            self.assertEqual(report.closed_by_user_id, user_id)
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 2)

            third = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=user_id,
                trigger="E2E",
                client=client,
            )
            self.assertEqual(third.status, "SUCCEEDED")
            self.assertEqual(third.shifts_imported, 0)
            self.assertEqual(third.reports_created, 0)
            self.assertEqual(third.reports_updated, 0)
            self.assertEqual(third.reports_unchanged, 1)
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 2)

            report.status = "DRAFT"
            report.closed_by_user_id = None
            report.closed_at = None
            report.revenue_total += 1
            db.commit()
            modified = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=user_id,
                trigger="E2E",
                client=client,
            )
            self.assertEqual(modified.status, "PARTIAL")
            self.assertEqual(modified.reports_updated, 0)
            self.assertEqual(len(modified.summary_json["conflicts"]), 1)
            db.refresh(report)
            self.assertEqual(report.status, "DRAFT")
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 2)
            self.assertEqual(
                len(
                    db.execute(
                        select(DailyReport).where(
                            DailyReport.venue_id == venue_id,
                            DailyReport.date == TARGET_DATE,
                            DailyReport.shift_slot == "DAY",
                        )
                    )
                    .scalars()
                    .all()
                ),
                1,
            )

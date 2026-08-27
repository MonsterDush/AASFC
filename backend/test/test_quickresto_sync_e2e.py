from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import unittest

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.daily_report import DailyReport
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.services.integrations.quickresto_sync import sync_quickresto_connection


TARGET_DATE = date(2030, 1, 15)


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


@unittest.skipUnless(
    os.environ.get("AXELIO_QUICKRESTO_E2E") == "1",
    "set AXELIO_QUICKRESTO_E2E=1 against the isolated local E2E database",
)
class QuickRestoSyncE2ETests(unittest.TestCase):
    def test_closed_shifts_create_one_report_and_second_sync_is_idempotent(self):
        url = make_url(settings.database_url)
        self.assertIn(url.host, {"127.0.0.1", "localhost"})
        self.assertTrue(str(url.database or "").endswith("_e2e"))

        fixture_path = Path(__file__).parent / "fixtures" / "quickresto" / "complex_same_day_shifts.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        shifts = deepcopy(fixture["shifts"])
        for shift in shifts:
            shift["localClosedTime"] = shift["localClosedTime"].replace(fixture["report_date"], TARGET_DATE.isoformat())

        with SessionLocal() as db:
            venue_id = 1
            user_id = 1
            existing_connection = db.execute(
                select(QuickRestoConnection).where(QuickRestoConnection.venue_id == venue_id)
            ).scalar_one_or_none()
            if existing_connection is not None:
                db.delete(existing_connection)
                db.commit()
            existing_report = db.execute(
                select(DailyReport).where(
                    DailyReport.venue_id == venue_id,
                    DailyReport.date == TARGET_DATE,
                    DailyReport.shift_slot == "DAY",
                )
            ).scalar_one_or_none()
            if existing_report is not None:
                db.delete(existing_report)
                db.commit()

            payment_methods = {
                item.code: item
                for item in db.execute(select(PaymentMethod).where(PaymentMethod.venue_id == venue_id)).scalars()
            }
            bonus = payment_methods.get("bonus")
            if bonus is None:
                bonus = PaymentMethod(
                    venue_id=venue_id,
                    code="bonus",
                    title="Бонусы",
                    is_active=True,
                    sort_order=50,
                )
                db.add(bonus)
                db.flush()
                payment_methods["bonus"] = bonus
            departments = list(
                db.execute(
                    select(Department).where(Department.venue_id == venue_id).order_by(Department.id).limit(2)
                ).scalars()
            )
            self.assertEqual(len(departments), 2)

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
                    {"id": 3, "name": bonus.title, "operationType": "payment"},
                    {"id": 7, "name": "Все бесплатно!!!", "operationType": "writeoff"},
                ],
                departments=[
                    {"id": 6, "name": departments[0].title},
                    {"id": 7, "name": departments[1].title},
                ],
            )

            first = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=user_id,
                trigger="E2E",
                client=client,
            )
            self.assertEqual(first.status, "SUCCEEDED")
            self.assertEqual(first.shifts_imported, 3)
            self.assertEqual(first.reports_created, 1)
            self.assertEqual(first.summary_json["conflicts"], [])

            report = db.execute(
                select(DailyReport).where(
                    DailyReport.venue_id == venue_id,
                    DailyReport.date == TARGET_DATE,
                    DailyReport.shift_slot == "DAY",
                )
            ).scalar_one()
            self.assertEqual(report.status, "DRAFT")
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
            self.assertEqual(second.reports_updated, 0)
            self.assertEqual(second.reports_unchanged, 1)
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

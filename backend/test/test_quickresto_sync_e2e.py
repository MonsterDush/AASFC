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
from app.models.daily_report_attachment import DailyReportAttachment
from app.models.daily_report_audit import DailyReportAudit
from app.models.daily_report_tip_allocation import DailyReportTipAllocation
from app.models.daily_report_value import DailyReportValue
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.notification_job import NotificationJob
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_import_issue_audit import QuickRestoImportIssueAudit
from app.models.quickresto_import_issue_shift import QuickRestoImportIssueShift
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.quickresto_source_snapshot import QuickRestoSourceSnapshot
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
    def test_closed_shifts_follow_import_mode_auto_create_catalogs_and_remain_idempotent(self):
        fixture_path = Path(__file__).parent / "fixtures" / "quickresto" / "complex_same_day_shifts.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        shifts = deepcopy(fixture["shifts"])
        orders = deepcopy(fixture["orders"])
        for shift in shifts:
            for field in ("localOpenedTime", "localClosedTime"):
                shift[field] = shift[field].replace(fixture["report_date"], TARGET_DATE.isoformat())
        returned_order = deepcopy(orders[0])
        returned_order["id"] = max(int(item["id"]) for item in orders) + 1
        returned_order["returned"] = True
        orders.append(returned_order)
        returned_shift = next(item for item in shifts if item["frontId"] == returned_order["shiftId"])
        returned_amount = float(returned_order["frontTotalPrice"])
        returned_shift["totalCash"] = float(returned_shift.get("totalCash") or 0) + returned_amount
        returned_shift["totalReturnCash"] = float(returned_shift.get("totalReturnCash") or 0) + returned_amount
        returned_shift["ordersCount"] = int(returned_shift.get("ordersCount") or 0) + 1
        returned_shift["returnOrdersCount"] = int(returned_shift.get("returnOrdersCount") or 0) + 1

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
                QuickRestoSourceSnapshot.__table__,
                QuickRestoImportIssue.__table__,
                QuickRestoImportIssueShift.__table__,
                QuickRestoImportIssueAudit.__table__,
                NotificationJob.__table__,
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
            catalog_edge_payments = [
                PaymentMethod(
                    venue_id=venue_id,
                    code="quickresto-payment-9",
                    title="Резерв кода",
                    is_active=True,
                    sort_order=4,
                ),
                PaymentMethod(
                    venue_id=venue_id,
                    code="archived-qr",
                    title="Архивный QR",
                    is_active=False,
                    sort_order=5,
                ),
                PaymentMethod(
                    venue_id=venue_id,
                    code="duplicate-qr-1",
                    title="Дубль QR",
                    is_active=True,
                    sort_order=6,
                ),
                PaymentMethod(
                    venue_id=venue_id,
                    code="duplicate-qr-2",
                    title="Дубль QR",
                    is_active=True,
                    sort_order=7,
                ),
            ]
            db.add_all([*payment_methods.values(), *catalog_edge_payments, *departments])
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
                report_import_mode="DRAFT",
                business_day_cutoff_hour=0,
                sync_from_date=TARGET_DATE,
                created_by_user_id=user_id,
            )
            db.add(connection)
            db.commit()
            db.refresh(connection)
            manual_mapping = QuickRestoPaymentMapping(
                connection_id=connection.id,
                external_id=8,
                external_name="СБП QR",
                operation_type="payment",
                payment_mechanism=None,
                payment_method_id=payment_methods["bonus"].id,
                excluded_from_revenue=False,
            )
            db.add(manual_mapping)
            db.commit()

            client = FixtureQuickRestoClient(
                shifts=shifts,
                orders=orders,
                payment_types=[
                    {"id": 1, "name": payment_methods["cash"].title, "operationType": "payment"},
                    {
                        "id": 2,
                        "name": payment_methods["cashless"].title,
                        "operationType": "payment",
                    },
                    {"id": 3, "name": payment_methods["bonus"].title, "operationType": "payment"},
                    {"id": 7, "name": "Все бесплатно!!!", "operationType": "writeoff"},
                    {"id": 8, "name": "СБП QR", "operationType": "payment"},
                    {"id": 9, "name": "Новая оплата QR", "operationType": "payment"},
                    {"id": 10, "name": "Архивный QR", "operationType": "payment"},
                    {"id": 11, "name": "Дубль QR", "operationType": "payment"},
                ],
                departments=[
                    {"id": 6, "name": departments[0].title},
                    {"id": 7, "name": departments[1].title},
                    {"id": 8, "name": "Кухня QR"},
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
            self.assertEqual(first.summary_json["payment_methods_created"], 2)
            self.assertEqual(first.summary_json["departments_created"], 1)
            self.assertEqual(first.summary_json["unmapped_payment_type_ids"], [11])

            report = db.execute(
                select(DailyReport).where(
                    DailyReport.venue_id == venue_id,
                    DailyReport.date == TARGET_DATE,
                    DailyReport.shift_slot == "DAY",
                )
            ).scalar_one()
            self.assertEqual(report.id, empty_report.id)
            self.assertEqual(report.status, "DRAFT")
            self.assertIsNone(report.closed_by_user_id)
            self.assertIsNone(report.closed_at)
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
            self.assertEqual(source.summary_json["returned_orders_count"], 1)
            created_payment = db.execute(
                select(PaymentMethod).where(
                    PaymentMethod.venue_id == venue_id,
                    PaymentMethod.title == "Новая оплата QR",
                )
            ).scalar_one()
            created_department = db.execute(
                select(Department).where(
                    Department.venue_id == venue_id,
                    Department.title == "Кухня QR",
                )
            ).scalar_one()
            self.assertEqual(created_payment.code, "quickresto-payment-9-2")
            self.assertEqual(created_department.code, "quickresto-department-8")
            self.assertEqual(manual_mapping.payment_method_id, payment_methods["bonus"].id)
            self.assertFalse(
                db.execute(
                    select(PaymentMethod).where(
                        PaymentMethod.venue_id == venue_id,
                        PaymentMethod.title == "СБП QR",
                    )
                )
                .scalars()
                .all()
            )
            active_archived_title = db.execute(
                select(PaymentMethod).where(
                    PaymentMethod.venue_id == venue_id,
                    PaymentMethod.title == "Архивный QR",
                    PaymentMethod.is_active.is_(True),
                )
            ).scalar_one()
            self.assertEqual(active_archived_title.code, "quickresto-payment-10")
            self.assertFalse(
                db.execute(
                    select(PaymentMethod).where(
                        PaymentMethod.venue_id == venue_id,
                        PaymentMethod.title == "Все бесплатно!!!",
                    )
                )
                .scalars()
                .all()
            )
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 0)

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
            self.assertEqual(second.summary_json["payment_methods_created"], 0)
            self.assertEqual(second.summary_json["departments_created"], 0)
            db.refresh(report)
            self.assertEqual(report.status, "DRAFT")
            self.assertEqual(
                len(db.execute(select(PaymentMethod).where(PaymentMethod.venue_id == venue_id)).scalars().all()),
                9,
            )
            self.assertEqual(
                len(db.execute(select(Department).where(Department.venue_id == venue_id)).scalars().all()),
                3,
            )
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 0)

            connection.report_import_mode = "CLOSED"
            db.commit()

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
            self.assertEqual(third.reports_updated, 1)
            self.assertEqual(third.reports_unchanged, 0)
            db.refresh(report)
            self.assertEqual(report.status, "CLOSED")
            self.assertEqual(report.closed_by_user_id, user_id)
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 1)

            unchanged_closed = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=user_id,
                trigger="E2E",
                client=client,
            )
            self.assertEqual(unchanged_closed.status, "SUCCEEDED")
            self.assertEqual(unchanged_closed.reports_unchanged, 1)
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 1)

            incremental_shift_id = "fixture-closed-shift-4"
            incremental_shift = {
                "id": 4,
                "frontId": incremental_shift_id,
                "status": "CLOSED",
                "shiftNumber": 4,
                "localOpenedTime": f"{TARGET_DATE.isoformat()}T23:00:00.000Z",
                "localClosedTime": f"{TARGET_DATE.isoformat()}T23:10:00.000Z",
                "ordersCount": 1,
                "totalCash": 1_000.0,
                "totalCard": 0.0,
                "totalBonuses": 0.0,
                "nonFiscalTotalCash": 0.0,
                "nonFiscalTotalCard": 0.0,
                "nonFiscalTotalBonuses": 0.0,
                "totalReturnCash": 0.0,
                "totalReturnCard": 0.0,
                "totalReturnBonuses": 0.0,
                "nonFiscalTotalReturnCash": 0.0,
                "nonFiscalTotalReturnCard": 0.0,
                "nonFiscalTotalReturnBonuses": 0.0,
                "writeOffTotalCash": 0.0,
                "writeOffTotalCard": 0.0,
                "writeOffTotalBonuses": 0.0,
            }
            incremental_order = {
                "id": max(client.orders_by_id) + 1,
                "shiftId": incremental_shift_id,
                "returned": False,
                "frontTotalPrice": 1_000.0,
                "frontTotalAbsoluteDiscount": 0.0,
                "payments": [
                    {
                        "amount": 1_000.0,
                        "paymentType": {
                            "id": 1,
                            "operationType": "fiscal",
                            "paymentMechanismWeb": "cash",
                        },
                    }
                ],
                "orderItemList": [
                    {
                        "amount": 1.0,
                        "totalPrice": 1_000.0,
                        "totalAbsoluteDiscount": 0.0,
                        "totalAbsoluteCharge": 0.0,
                        "product": {"id": 9, "name": "Новая позиция", "parentId": 6},
                    }
                ],
            }
            client.shifts.append(incremental_shift)
            client.orders.append(incremental_order)
            client.orders_by_id[int(incremental_order["id"])] = incremental_order

            incrementally_closed = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=user_id,
                trigger="E2E",
                client=client,
            )
            self.assertEqual(incrementally_closed.status, "SUCCEEDED")
            self.assertEqual(incrementally_closed.shifts_imported, 1)
            self.assertEqual(incrementally_closed.reports_updated, 1)
            self.assertEqual(incrementally_closed.summary_json["conflicts"], [])
            db.refresh(report)
            self.assertEqual(report.status, "CLOSED")
            self.assertEqual(report.revenue_total, 24_900)
            self.assertEqual(report.cash, 7_600)
            source = db.execute(
                select(QuickRestoReportImport).where(QuickRestoReportImport.connection_id == connection.id)
            ).scalar_one()
            self.assertEqual(source.shift_count, 4)
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 2)

            report.status = "DRAFT"
            report.closed_by_user_id = None
            report.closed_at = None
            report.revenue_total += 1
            connection.report_import_mode = "DRAFT"
            changed_order = next(
                item
                for item in client.orders_by_id.values()
                if item.get("payments")
                and item["payments"][0].get("paymentType", {}).get("id") == 1
                and item["payments"][0].get("paymentType", {}).get("operationType") != "writeoff"
            )
            changed_order["payments"][0]["paymentType"]["id"] = 2
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

            report.revenue_total -= 1
            db.commit()
            safely_updated = sync_quickresto_connection(
                db,
                connection=connection,
                requested_by_user_id=user_id,
                trigger="E2E",
                client=client,
            )
            self.assertEqual(safely_updated.status, "SUCCEEDED")
            self.assertEqual(safely_updated.reports_updated, 1)
            db.refresh(report)
            self.assertEqual(report.status, "DRAFT")
            self.assertEqual(report.revenue_total, 24_900)
            for mocked_side_effect in mocked_side_effects:
                self.assertEqual(mocked_side_effect.call_count, 2)

    def test_enabling_night_split_regroups_owned_report_without_duplicate(self):
        shift_id = "fixture-night-shift"
        shift = {
            "id": 91,
            "version": 1,
            "frontId": shift_id,
            "status": "CLOSED",
            "localOpenedTime": f"{TARGET_DATE.isoformat()}T23:00:00.000Z",
            "localClosedTime": f"{TARGET_DATE.isoformat()}T23:45:00.000Z",
            "ordersCount": 1,
            "totalCash": 1_000.0,
            "totalCard": 0.0,
            "totalBonuses": 0.0,
            "nonFiscalTotalCash": 0.0,
            "nonFiscalTotalCard": 0.0,
            "nonFiscalTotalBonuses": 0.0,
            "totalReturnCash": 0.0,
            "totalReturnCard": 0.0,
            "totalReturnBonuses": 0.0,
            "nonFiscalTotalReturnCash": 0.0,
            "nonFiscalTotalReturnCard": 0.0,
            "nonFiscalTotalReturnBonuses": 0.0,
            "writeOffTotalCash": 0.0,
            "writeOffTotalCard": 0.0,
            "writeOffTotalBonuses": 0.0,
            "writeOffTotalReturnCash": 0.0,
            "writeOffTotalReturnCard": 0.0,
            "writeOffTotalReturnBonuses": 0.0,
        }
        order = {
            "id": 92,
            "shiftId": shift_id,
            "returned": False,
            "frontTotalPrice": 1_000.0,
            "frontTotalAbsoluteDiscount": 0.0,
            "payments": [
                {
                    "amount": 1_000.0,
                    "paymentType": {"id": 1, "operationType": "fiscal", "paymentMechanismWeb": "cash"},
                }
            ],
            "orderItemList": [
                {
                    "totalPrice": 1_000.0,
                    "totalAbsoluteDiscount": 0.0,
                    "totalAbsoluteCharge": 0.0,
                    "product": {"id": 3, "name": "Позиция", "parentId": 6},
                }
            ],
        }
        client = FixtureQuickRestoClient(
            shifts=[shift],
            orders=[order],
            payment_types=[{"id": 1, "name": "Наличные", "operationType": "payment"}],
            departments=[{"id": 6, "name": "Бар"}],
        )
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
                DailyReportAudit.__table__,
                DailyReportTipAllocation.__table__,
                DailyReportAttachment.__table__,
                QuickRestoConnection.__table__,
                QuickRestoPaymentMapping.__table__,
                QuickRestoDepartmentMapping.__table__,
                QuickRestoSyncRun.__table__,
                QuickRestoShiftImport.__table__,
                QuickRestoReportImport.__table__,
                QuickRestoSourceSnapshot.__table__,
                QuickRestoImportIssue.__table__,
                QuickRestoImportIssueShift.__table__,
                QuickRestoImportIssueAudit.__table__,
                NotificationJob.__table__,
            ],
        )

        with Session(engine) as db:
            db.add(User(id=1, system_role="NONE"))
            venue = Venue(id=1, name="QuickResto split test", night_shifts_enabled=True)
            db.add(venue)
            connection = QuickRestoConnection(
                venue_id=1,
                cloud="fixture",
                api_login_encrypted="v1:unused",
                api_password_encrypted="v1:unused",
                is_active=True,
                report_import_mode="CLOSED",
                business_day_cutoff_hour=6,
                night_shift_split_enabled=False,
                night_shift_start_hour=22,
                sync_from_date=TARGET_DATE,
                created_by_user_id=1,
            )
            db.add(connection)
            db.commit()
            db.refresh(connection)

            with (
                patch("app.routers.venue_reports._rebuild_report_tip_allocations"),
                patch("app.routers.venue_reports.rebuild_revenue_entries_for_report"),
                patch("app.routers.venue_reports.sync_daily_recurring_accruals_for_date"),
                patch("app.routers.venue_reports._recalculate_payroll_for_dates"),
                patch("app.routers.venue_payroll_support._recalculate_payroll_for_dates"),
                patch("app.routers.venue_reports._enqueue_day_economics_summary_job"),
                patch("app.routers.venue_reports._enqueue_salary_day_breakdown_job"),
                patch("app.routers.venue_reports._enqueue_soft_alerts_job"),
                patch("app.routers.venue_reports._sync_recurring_accruals_after_report_reopen") as reopen_sync,
                patch("app.services.finance.revenue.delete_revenue_entries_for_report") as delete_revenue,
            ):
                first = sync_quickresto_connection(
                    db,
                    connection=connection,
                    requested_by_user_id=1,
                    trigger="E2E",
                    client=client,
                )
                self.assertEqual(first.status, "SUCCEEDED")
                self.assertEqual(first.reports_created, 1)

                day_report = db.execute(
                    select(DailyReport).where(
                        DailyReport.venue_id == 1,
                        DailyReport.date == TARGET_DATE,
                        DailyReport.shift_slot == "DAY",
                    )
                ).scalar_one()
                integration_comment = day_report.comment
                day_report.comment = "Проверено и изменено вручную"
                connection.night_shift_split_enabled = True
                db.commit()
                conflicted = sync_quickresto_connection(
                    db,
                    connection=connection,
                    requested_by_user_id=1,
                    trigger="E2E",
                    client=client,
                )
                self.assertEqual(conflicted.status, "PARTIAL")
                self.assertEqual(len(conflicted.summary_json["conflicts"]), 1)
                issue = db.execute(select(QuickRestoImportIssue)).scalar_one()
                self.assertEqual(issue.status, "OPEN")
                self.assertEqual(issue.error_code, "REPORT_CONFLICT")
                db.expire_all()
                day_report = db.execute(
                    select(DailyReport).where(
                        DailyReport.venue_id == 1,
                        DailyReport.date == TARGET_DATE,
                        DailyReport.shift_slot == "DAY",
                    )
                ).scalar_one()
                imported_before_retry = db.execute(select(QuickRestoShiftImport)).scalar_one()
                self.assertEqual(imported_before_retry.shift_slot, "DAY")
                self.assertEqual(imported_before_retry.daily_report_id, day_report.id)

                day_report.comment = integration_comment
                db.commit()
                connection = db.get(QuickRestoConnection, connection.id)
                second = sync_quickresto_connection(
                    db,
                    connection=connection,
                    requested_by_user_id=1,
                    trigger="E2E",
                    client=client,
                )

            self.assertEqual(second.status, "SUCCEEDED")
            self.assertEqual(second.reports_created, 1)
            self.assertEqual(second.summary_json["reports_removed"], 1)
            reports = db.execute(select(DailyReport).where(DailyReport.venue_id == 1)).scalars().all()
            self.assertEqual(len(reports), 1)
            self.assertEqual(reports[0].shift_slot, "NIGHT")
            self.assertEqual(reports[0].status, "CLOSED")
            sources = db.execute(select(QuickRestoReportImport)).scalars().all()
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0].shift_slot, "NIGHT")
            imported_shift = db.execute(select(QuickRestoShiftImport)).scalar_one()
            self.assertEqual(imported_shift.shift_slot, "NIGHT")
            self.assertEqual(imported_shift.daily_report_id, reports[0].id)
            issue = db.execute(select(QuickRestoImportIssue)).scalar_one()
            self.assertEqual(issue.status, "RESOLVED")
            delete_revenue.assert_called_once()
            reopen_sync.assert_called_once()

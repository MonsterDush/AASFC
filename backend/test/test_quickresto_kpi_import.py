from __future__ import annotations

from datetime import date
import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.models.daily_report import DailyReport
from app.models.daily_report_value import DailyReportValue
from app.models.department import Department
from app.models.kpi_metric import KpiMetric
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import (
    QuickRestoDepartmentAllocation,
    QuickRestoDepartmentMapping,
)
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_kpi_product_mapping import QuickRestoKpiProductMapping
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_report_import import QuickRestoReportImport
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.user import User
from app.models.venue import Venue
from app.routers.venue_quickresto import put_quickresto_kpi_mappings
from app.schemas.quickresto import QuickRestoKpiMappingsUpdateIn
from app.services.integrations.quickresto_kpi import product_catalog_from_sources
from app.services.integrations.quickresto_normalize import (
    QuickRestoDataError,
    aggregate_normalized_shifts,
    normalize_closed_shift,
)
from app.services.integrations.quickresto_sync import (
    _mapped_aggregate,
    _replace_report_values,
    _report_values,
    _report_values_match,
)
from app.services.payroll.metric_loaders import _load_revenue_metrics


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


def _closed_shift() -> dict:
    return {
        "id": 71,
        "frontId": "SHIFT-71",
        "status": "CLOSED",
        "version": 1,
        "localOpenedTime": "2026-09-09T12:00:00",
        "localClosedTime": "2026-09-09T23:00:00",
        "totalCash": 0,
        "totalCard": 150,
        "totalBonuses": 0,
        "nonFiscalTotalCash": 0,
        "nonFiscalTotalCard": 0,
        "nonFiscalTotalBonuses": 0,
        "totalReturnCash": 0,
        "totalReturnCard": 0,
        "totalReturnBonuses": 0,
        "nonFiscalTotalReturnCash": 0,
        "nonFiscalTotalReturnCard": 0,
        "nonFiscalTotalReturnBonuses": 0,
        "writeOffTotalCash": 0,
        "writeOffTotalCard": 20,
        "writeOffTotalBonuses": 0,
        "writeOffTotalReturnCash": 0,
        "writeOffTotalReturnCard": 0,
        "writeOffTotalReturnBonuses": 0,
    }


def _orders() -> list[dict]:
    payment_type = {"id": 901, "operationType": "payment"}
    zeroes = {"totalAbsoluteDiscount": 0, "totalAbsoluteCharge": 0}
    return [
        {
            "id": 81,
            "shiftId": "SHIFT-71",
            "frontTotalPrice": 150,
            "frontTotalAbsoluteDiscount": 0,
            "returned": False,
            "payments": [{"amount": 150, "paymentType": payment_type}],
            "orderItemList": [
                {
                    **zeroes,
                    "amount": 2,
                    "totalPrice": 100,
                    "product": {
                        "id": 501,
                        "name": "Бизнес-ланч KPI",
                        "parentId": 1106,
                        "parentName": "Бизнес-ланчи",
                    },
                },
                {
                    **zeroes,
                    "amount": 1,
                    "totalPrice": 50,
                    "product": {"id": 502, "name": "Лимонад", "parentId": 1101},
                },
            ],
        },
        {
            "id": 82,
            "shiftId": "SHIFT-71",
            "frontTotalPrice": 20,
            "frontTotalAbsoluteDiscount": 0,
            "returned": False,
            "payments": [
                {
                    "amount": 20,
                    "paymentType": {"id": 902, "operationType": "writeoff"},
                }
            ],
            "orderItemList": [
                {
                    **zeroes,
                    "amount": 1,
                    "totalPrice": 20,
                    "product": {"id": 503, "name": "Списание", "parentId": 1106},
                }
            ],
        },
        {
            "id": 83,
            "shiftId": "SHIFT-71",
            "frontTotalPrice": 15,
            "frontTotalAbsoluteDiscount": 0,
            "returned": True,
            "payments": [{"amount": 15, "paymentType": payment_type}],
            "orderItemList": [
                {
                    **zeroes,
                    "amount": 1,
                    "totalPrice": 15,
                    "product": {"id": 504, "name": "Возврат", "parentId": 1106},
                }
            ],
        },
    ]


class QuickRestoKpiImportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        BaseTables = [
            User.__table__,
            Venue.__table__,
            PaymentMethod.__table__,
            Department.__table__,
            KpiMetric.__table__,
            QuickRestoConnection.__table__,
            QuickRestoPaymentMapping.__table__,
            QuickRestoDepartmentMapping.__table__,
            QuickRestoDepartmentAllocation.__table__,
            QuickRestoKpiProductMapping.__table__,
            QuickRestoSyncRun.__table__,
            QuickRestoImportIssue.__table__,
            DailyReport.__table__,
            DailyReportValue.__table__,
            QuickRestoReportImport.__table__,
        ]
        from app.core.db import Base

        Base.metadata.create_all(self.engine, tables=BaseTables)

    def tearDown(self):
        self.engine.dispose()

    def _seed(self, db: Session):
        user = User(id=1, system_role="SUPER_ADMIN")
        venue = Venue(id=21, name="KPI QuickResto")
        bar = Department(id=21, venue_id=21, code="bar", title="Бар", sort_order=1)
        hookah = Department(id=22, venue_id=21, code="hookah", title="Кальян", sort_order=2)
        card = PaymentMethod(id=31, venue_id=21, code="card", title="Карта", sort_order=1)
        kpi = KpiMetric(id=41, venue_id=21, code="qr_kpi", title="KPI-позиции", unit="QTY")
        other_kpi = KpiMetric(id=42, venue_id=21, code="manual", title="Ручной KPI", unit="QTY")
        rub_kpi = KpiMetric(id=43, venue_id=21, code="rub", title="KPI в рублях", unit="RUB")
        db.add_all([user, venue, bar, hookah, card, kpi, other_kpi, rub_kpi])
        connection = QuickRestoConnection(
            venue_id=21,
            cloud="fixture",
            api_login_encrypted="v1:test",
            api_password_encrypted="v1:test",
            external_venue_id=3,
            scope_status="READY",
            is_active=True,
            report_import_mode="CLOSED",
            business_day_cutoff_hour=6,
            created_by_user_id=1,
        )
        db.add(connection)
        db.flush()
        db.add_all(
            [
                QuickRestoPaymentMapping(
                    connection_id=connection.id,
                    external_id=901,
                    external_name="Карта",
                    operation_type="payment",
                    payment_method_id=31,
                    excluded_from_revenue=False,
                    is_applicable=True,
                    is_available=True,
                    allowed_sale_place_ids_json=[],
                ),
                QuickRestoDepartmentMapping(
                    connection_id=connection.id,
                    external_id=1101,
                    external_name="Бар",
                    department_id=21,
                ),
                QuickRestoDepartmentMapping(
                    connection_id=connection.id,
                    external_id=1106,
                    external_name="Бизнес-ланчи",
                    department_id=None,
                ),
                QuickRestoKpiProductMapping(
                    connection_id=connection.id,
                    external_product_id=501,
                    external_name="Бизнес-ланч KPI",
                    external_group_id=1106,
                    external_group_name="Бизнес-ланчи",
                    kpi_metric_id=41,
                    exclude_from_percentage_base=True,
                ),
            ]
        )
        db.flush()
        composite = db.execute(
            select(QuickRestoDepartmentMapping).where(
                QuickRestoDepartmentMapping.connection_id == connection.id,
                QuickRestoDepartmentMapping.external_id == 1106,
            )
        ).scalar_one()
        db.add_all(
            [
                QuickRestoDepartmentAllocation(mapping_id=composite.id, department_id=21, share_percent=60),
                QuickRestoDepartmentAllocation(mapping_id=composite.id, department_id=22, share_percent=40),
            ]
        )
        db.commit()
        return user, venue, connection

    def test_catalog_and_normalization_keep_only_sold_products(self):
        sources = [{"orders": _orders()}]
        catalog = product_catalog_from_sources(sources)
        self.assertEqual(set(catalog), {501, 502})
        self.assertEqual(catalog[501]["external_name"], "Бизнес-ланч KPI")
        self.assertEqual(catalog[501]["external_group_name"], "Бизнес-ланчи")

        normalized = normalize_closed_shift(_closed_shift(), _orders(), cutoff_hour=6)
        self.assertEqual(normalized["product_sales_external"]["501:1106"]["quantity"], "2")
        self.assertEqual(normalized["product_sales_external"]["501:1106"]["revenue_minor"], 10_000)
        self.assertNotIn("503:1106", normalized["product_sales_external"])
        self.assertNotIn("504:1106", normalized["product_sales_external"])

    def test_mapped_product_increments_kpi_and_routes_revenue_outside_departments(self):
        normalized = normalize_closed_shift(_closed_shift(), _orders(), cutoff_hour=6)
        aggregate = aggregate_normalized_shifts([normalized])
        with Session(self.engine) as db:
            _user, _venue, connection = self._seed(db)
            mapped = _mapped_aggregate(db, connection=connection, aggregate=aggregate)

        self.assertEqual(mapped["revenue_total"], 150)
        self.assertEqual(mapped["departments_internal"], {21: 50})
        self.assertEqual(mapped["kpis_internal"], {41: 2})
        self.assertEqual(mapped["department_unallocated_total"], 100)
        self.assertEqual(mapped["percentage_excluded_total"], 100)
        self.assertEqual(mapped["percentage_excluded_departments_internal"], {})

    def test_fractional_quantity_is_rejected_only_for_a_mapped_kpi_product(self):
        normalized = normalize_closed_shift(_closed_shift(), _orders(), cutoff_hour=6)
        aggregate = aggregate_normalized_shifts([normalized])
        aggregate["product_sales_external"]["501:1106"]["quantity"] = "1.5"
        with Session(self.engine) as db:
            _user, _venue, connection = self._seed(db)
            with self.assertRaisesRegex(QuickRestoDataError, "fractional quantity"):
                _mapped_aggregate(db, connection=connection, aggregate=aggregate)
            row = db.execute(select(QuickRestoKpiProductMapping)).scalar_one()
            row.kpi_metric_id = None
            db.flush()
            mapped = _mapped_aggregate(db, connection=connection, aggregate=aggregate)
            self.assertEqual(mapped["kpis_internal"], {})

    def test_report_value_replacement_preserves_manual_kpi_delta_across_retries(self):
        with Session(self.engine) as db:
            user, _venue, _connection = self._seed(db)
            report = DailyReport(
                venue_id=21,
                date=date(2026, 9, 9),
                shift_slot="DAY",
                status="DRAFT",
                created_by_user_id=user.id,
            )
            db.add(report)
            db.flush()
            db.add_all(
                [
                    DailyReportValue(report_id=report.id, kind="KPI", ref_id=41, value_numeric=3),
                    DailyReportValue(report_id=report.id, kind="KPI", ref_id=42, value_numeric=7),
                ]
            )
            db.flush()

            base = {
                "revenue_total": 0,
                "department_unallocated_total": 0,
                "payments_internal": {},
                "departments_internal": {},
            }
            first = {**base, "kpis_internal": {41: 2}}
            _replace_report_values(db, report, first)
            db.flush()
            self.assertEqual(_report_values(db, report.id, "KPI"), {41: 5, 42: 7})
            self.assertTrue(_report_values_match(db, report, first))

            second = {**base, "kpis_internal": {41: 4}}
            _replace_report_values(db, report, second, previous_aggregate=first)
            db.flush()
            self.assertEqual(_report_values(db, report.id, "KPI"), {41: 7, 42: 7})

            removed = {**base, "kpis_internal": {}}
            _replace_report_values(db, report, removed, previous_aggregate=second)
            db.flush()
            self.assertEqual(_report_values(db, report.id, "KPI"), {41: 3, 42: 7})

    def test_mapping_api_accepts_only_quantity_kpi_of_current_venue(self):
        with Session(self.engine) as db:
            user, _venue, _connection = self._seed(db)
            response = put_quickresto_kpi_mappings(
                21,
                QuickRestoKpiMappingsUpdateIn.model_validate(
                    {
                        "products": [
                            {
                                "external_product_id": 501,
                                "kpi_metric_id": 41,
                                "exclude_from_percentage_base": True,
                            }
                        ]
                    }
                ),
                db,
                user,
            )
            self.assertEqual(response["mapped_products"], 1)

            with self.assertRaises(HTTPException) as context:
                put_quickresto_kpi_mappings(
                    21,
                    QuickRestoKpiMappingsUpdateIn.model_validate(
                        {"products": [{"external_product_id": 501, "kpi_metric_id": 43}]}
                    ),
                    db,
                    user,
                )
            self.assertEqual(context.exception.status_code, 400)

    def test_payroll_percentage_revenue_excludes_kpi_product_but_report_total_stays_intact(self):
        with Session(self.engine) as db:
            user, _venue, connection = self._seed(db)
            report = DailyReport(
                venue_id=21,
                date=date(2026, 9, 9),
                shift_slot="DAY",
                status="CLOSED",
                revenue_total=150,
                unallocated_revenue_total=100,
                created_by_user_id=user.id,
                closed_by_user_id=user.id,
            )
            db.add(report)
            db.flush()
            db.add_all(
                [
                    DailyReportValue(report_id=report.id, kind="DEPT", ref_id=21, value_numeric=50),
                    DailyReportValue(report_id=report.id, kind="KPI", ref_id=41, value_numeric=2),
                    QuickRestoReportImport(
                        connection_id=connection.id,
                        daily_report_id=report.id,
                        business_date=report.date,
                        shift_slot="DAY",
                        aggregate_hash="a" * 64,
                        shift_count=1,
                        writeoff_total=0,
                        discount_total=0,
                        summary_json={
                            "percentage_excluded_total": 100,
                            "percentage_excluded_departments_internal": {},
                        },
                    ),
                ]
            )
            db.commit()

            metrics = _load_revenue_metrics(
                db,
                venue_id=21,
                month_start=date(2026, 9, 1),
                month_end_excl=date(2026, 10, 1),
            )

            self.assertEqual(report.revenue_total, 150)
            self.assertEqual(report.unallocated_revenue_total, 100)
            self.assertEqual(metrics.total_revenue_minor, 5_000)
            self.assertEqual(metrics.department_revenue_minor, {21: 5_000})


if __name__ == "__main__":
    unittest.main()

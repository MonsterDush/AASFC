from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth.deps import get_current_user
from app.core.db import Base, get_db
from app.main import app
from app.routers import venue_economics_notifications
from app.services.billing import manager as billing_manager
from app.models import (
    Department,
    ExpenseCategory,
    KpiMetric,
    PaymentMethod,
    NotificationJob,
    Supplier,
    User,
    VenueBillingState,
    VenueMember,
)
from app.services.demo.bootstrap import bootstrap_demo_venue


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class MoneyWorkflowApiTests(unittest.TestCase):
    """Full-stack money regressions over the real FastAPI routes and ORM schema."""

    month = "2026-09"
    venue_id = 1

    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)

        with Session(self.engine) as db:
            result = bootstrap_demo_venue(
                db,
                reference_year=2026,
                reference_month=9,
                history_months=1,
                make_public=False,
            )
            self.assertEqual(result.venue_id, self.venue_id)
            self.assertEqual(result.warnings, [])

            now = datetime.now(timezone.utc)
            billing = db.execute(
                select(VenueBillingState).where(VenueBillingState.venue_id == self.venue_id)
            ).scalar_one()
            billing.status = "ACTIVE"
            billing.provider = "ROBOKASSA"
            billing.paid_until = now + timedelta(days=365)
            billing.grace_until = now + timedelta(days=372)
            billing.next_payment_due_at = billing.paid_until

            owner_row = db.execute(
                select(User)
                .join(VenueMember, VenueMember.user_id == User.id)
                .where(
                    VenueMember.venue_id == self.venue_id,
                    VenueMember.venue_role == "OWNER",
                )
            ).scalar_one()
            self.owner = SimpleNamespace(
                id=int(owner_row.id),
                system_role=str(owner_row.system_role or "NONE"),
                tg_user_id=owner_row.tg_user_id,
                tg_username=owner_row.tg_username,
                full_name=owner_row.full_name,
                short_name=owner_row.short_name,
                preferred_locale=owner_row.preferred_locale,
                is_demo_user=False,
                demo_persona=None,
            )
            self.staff_id = (
                db.execute(
                    select(VenueMember.user_id)
                    .where(
                        VenueMember.venue_id == self.venue_id,
                        VenueMember.venue_role == "STAFF",
                    )
                    .order_by(VenueMember.user_id)
                )
                .scalars()
                .first()
            )
            staff_row = db.get(User, int(self.staff_id))
            self.staff = SimpleNamespace(
                id=int(staff_row.id),
                system_role=str(staff_row.system_role or "NONE"),
                tg_user_id=staff_row.tg_user_id,
                tg_username=staff_row.tg_username,
                full_name=staff_row.full_name,
                short_name=staff_row.short_name,
                preferred_locale=staff_row.preferred_locale,
                is_demo_user=False,
                demo_persona=None,
            )
            self.payment_method_ids = list(
                db.execute(
                    select(PaymentMethod.id)
                    .where(PaymentMethod.venue_id == self.venue_id, PaymentMethod.is_active.is_(True))
                    .order_by(PaymentMethod.id)
                ).scalars()
            )
            self.category_id = (
                db.execute(
                    select(ExpenseCategory.id)
                    .where(ExpenseCategory.venue_id == self.venue_id, ExpenseCategory.is_active.is_(True))
                    .order_by(ExpenseCategory.id)
                )
                .scalars()
                .first()
            )
            self.supplier_id = (
                db.execute(
                    select(Supplier.id)
                    .where(Supplier.venue_id == self.venue_id, Supplier.is_active.is_(True))
                    .order_by(Supplier.id)
                )
                .scalars()
                .first()
            )
            self.department_ids = list(
                db.execute(
                    select(Department.id)
                    .where(Department.venue_id == self.venue_id, Department.is_active.is_(True))
                    .order_by(Department.id)
                ).scalars()
            )
            self.kpi_ids = list(
                db.execute(
                    select(KpiMetric.id)
                    .where(KpiMetric.venue_id == self.venue_id, KpiMetric.is_active.is_(True))
                    .order_by(KpiMetric.id)
                ).scalars()
            )
            db.commit()

        def override_db():
            with Session(self.engine) as db:
                yield db

        app.dependency_overrides[get_db] = override_db
        self.current_user = self.owner
        app.dependency_overrides[get_current_user] = lambda: self.current_user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def request(self, method: str, path: str, *, expected: int = 200, **kwargs):
        response = self.client.request(method, path, **kwargs)
        self.assertEqual(response.status_code, expected, response.text)
        return response

    def json(self, method: str, path: str, *, expected: int = 200, **kwargs):
        return self.request(method, path, expected=expected, **kwargs).json()

    def test_payroll_month_range_profiles_and_payment_drafts_reconcile(self):
        profiles = self.json("GET", f"/venues/{self.venue_id}/pay-profiles")
        self.assertEqual(len(profiles), 3)
        profile_details = [
            self.json("GET", f"/venues/{self.venue_id}/pay-profiles/{profile['id']}") for profile in profiles
        ]
        seeded_types = {component["component_type"] for detail in profile_details for component in detail["components"]}
        self.assertEqual(
            seeded_types,
            {
                "SALARY_FIXED_MONTH",
                "SALARY_HOURLY",
                "SALARY_PER_SHIFT",
                "PERCENT_DEPARTMENT_REVENUE",
                "KPI_BONUS",
            },
        )

        monthly = self.json("GET", f"/venues/{self.venue_id}/payroll", params={"month": self.month})
        self.assertEqual(monthly["run"]["base_total_amount_minor"], 100_752_832)
        self.assertEqual(monthly["total_amount_minor"], 126_752_832)
        self.assertEqual(monthly["run"]["total_amount_minor"], monthly["total_amount_minor"])
        self.assertEqual(monthly["lines_count"], len(monthly["lines"]))
        self.assertEqual(monthly["total_amount_minor"], sum(row["amount_minor"] for row in monthly["lines"]))
        for line in monthly["lines"]:
            component_total = sum(item["amount_minor"] for item in line["breakdown"]["components"])
            self.assertEqual(component_total, line["amount_minor"])

        ranged = self.json(
            "GET",
            f"/venues/{self.venue_id}/payroll",
            params={"date_from": "2026-09-01", "date_to": "2026-09-30"},
        )
        self.assertEqual(ranged["mode"], "range")
        self.assertEqual(ranged["total_amount_minor"], monthly["total_amount_minor"])
        self.assertEqual(
            {row["member_user_id"]: row["amount_minor"] for row in ranged["lines"]},
            {row["member_user_id"]: row["amount_minor"] for row in monthly["lines"]},
        )
        for line in ranged["lines"]:
            breakdown = line["breakdown"]
            self.assertEqual(breakdown["summary"]["total_minor"], line["amount_minor"])
            payable_components = [item for item in breakdown["components"] if str(item.get("category") or "") != "tip"]
            self.assertEqual(sum(item["amount_minor"] for item in payable_components), line["amount_minor"])

        partial = self.json(
            "GET",
            f"/venues/{self.venue_id}/payroll",
            params={"date_from": "2026-09-10", "date_to": "2026-09-19"},
        )
        self.assertEqual(partial["date_from"], "2026-09-10")
        self.assertEqual(partial["date_to"], "2026-09-19")
        self.assertEqual(partial["total_amount_minor"], sum(row["amount_minor"] for row in partial["lines"]))

        recalculated = self.json(
            "POST",
            f"/venues/{self.venue_id}/payroll/calculate",
            json={"month": self.month},
        )
        self.assertEqual(recalculated["total_amount_minor"], monthly["total_amount_minor"])
        log = self.json(
            "GET",
            f"/venues/{self.venue_id}/payroll/recalculation-log",
            params={"month": self.month},
        )
        self.assertEqual(log["items"][0]["trigger_reason"], "manual_calculation")

        defaults = self.json(
            "GET",
            f"/venues/{self.venue_id}/payroll/payment-settings",
            params={"month": self.month},
        )
        self.assertTrue(defaults["preview"])
        settings = self.json(
            "PUT",
            f"/venues/{self.venue_id}/payroll/payment-settings",
            json={
                "payment_method_id": self.payment_method_ids[0],
                "cadence": "MONTHLY",
                "monthly_rules": [
                    {
                        "payment_day": 15,
                        "period_start_day": 1,
                        "period_end_day": 15,
                        "period_month_offset": 0,
                    },
                    {
                        "payment_day": 30,
                        "period_start_day": 16,
                        "period_end_day": 31,
                        "period_month_offset": 0,
                    },
                ],
                "is_active": True,
            },
        )
        self.assertEqual(settings["cadence"], "MONTHLY")
        drafts = self.json(
            "POST",
            f"/venues/{self.venue_id}/payroll/payment-drafts/generate",
            json={"month": self.month},
        )
        self.assertEqual(drafts["created"], 2)
        self.assertEqual(sum(item["amount_minor"] for item in drafts["items"]), monthly["total_amount_minor"])
        repeated = self.json(
            "POST",
            f"/venues/{self.venue_id}/payroll/payment-drafts/generate",
            json={"month": self.month},
        )
        self.assertEqual(repeated["created"], 0)
        self.assertEqual(repeated["updated"], 0)
        self.assertEqual({item["action"] for item in repeated["items"]}, {"unchanged"})

    def test_every_pay_component_profile_shape_can_be_saved_and_validated(self):
        profile = self.json(
            "POST",
            f"/venues/{self.venue_id}/pay-profiles",
            json={"title": "All money formulas", "description": "API regression profile"},
        )
        profile_id = profile["id"]
        components = [
            {"component_type": "SALARY_FIXED_MONTH", "title": "Fixed", "amount_minor": 3_100_000},
            {
                "component_type": "SALARY_HOURLY",
                "title": "Hourly",
                "rate_minor": 25_000,
                "weekday_rates": [{"weekday": 5, "rate_minor": 35_000}],
            },
            {"component_type": "SALARY_PER_SHIFT", "title": "Shift", "amount_minor": 150_000},
            {
                "component_type": "PERCENT_TOTAL_REVENUE",
                "title": "Total percent",
                "percent_bps": 500,
                "base_scope": "FULL_PERIOD",
                "boost_source_type": "VENUE_MONTH_PLAN",
                "boost_recalc_mode": "REPLACE_ALL",
                "minimum_guarantee_minor": 100_000,
                "maximum_cap_minor": 5_000_000,
                "percent_tiers": [
                    {"threshold_value": 0, "percent_bps": 500},
                    {"threshold_value": 1_000_000, "percent_bps": 700},
                ],
            },
            {
                "component_type": "PERCENT_DEPARTMENT_REVENUE",
                "title": "Department percent",
                "percent_bps": 300,
                "department_ids": self.department_ids[:2],
                "base_scope": "WORKED_DATES",
            },
            {
                "component_type": "KPI_BONUS",
                "title": "KPI fixed",
                "amount_minor": 50_000,
                "kpi_metric_id": self.kpi_ids[0],
                "threshold_value": 1,
            },
            {
                "component_type": "MINIMUM_PAYOUT",
                "title": "Shift minimum",
                "amount_minor": 200_000,
                "minimum_guarantee_scope": "SHIFT",
            },
        ]
        created = []
        for payload in components:
            created.append(
                self.json(
                    "POST",
                    f"/venues/{self.venue_id}/pay-profiles/{profile_id}/components",
                    json=payload,
                )
            )
        self.assertEqual({row["component_type"] for row in created}, {row["component_type"] for row in components})
        percent = next(row for row in created if row["component_type"] == "PERCENT_TOTAL_REVENUE")
        self.assertEqual([tier["percent_bps"] for tier in percent["percent_tiers"]], [500, 700])
        patched = self.json(
            "PATCH",
            f"/venues/{self.venue_id}/pay-components/{percent['id']}",
            json={
                "boost_enabled": True,
                "boost_percent_bps": 900,
                "boost_source_type": "VENUE_MONTH_PLAN",
                "boost_recalc_mode": "EXCESS_ONLY",
                "percent_tiers": [
                    {"threshold_value": 0, "percent_bps": 500},
                    {"threshold_value": 1_000_000, "percent_bps": 900},
                ],
            },
        )
        self.assertTrue(patched["boost_enabled"])
        self.assertEqual(patched["effective_boost_recalc_mode"], "EXCESS_ONLY")

        assignment = self.json(
            "POST",
            f"/venues/{self.venue_id}/pay-profiles/{profile_id}/assignments",
            json={
                "member_user_id": self.staff_id,
                "start_date": "2035-01-01",
                "end_date": "2035-12-31",
            },
        )
        assignment = self.json(
            "PATCH",
            f"/venues/{self.venue_id}/pay-profile-assignments/{assignment['id']}",
            json={"is_active": False},
        )
        self.assertFalse(assignment["is_active"])
        detail = self.json("GET", f"/venues/{self.venue_id}/pay-profiles/{profile_id}")
        self.assertEqual(len(detail["components"]), 7)

        invalid = self.json(
            "POST",
            f"/venues/{self.venue_id}/pay-profiles/{profile_id}/components",
            expected=400,
            json={"component_type": "SALARY_HOURLY", "title": "No rate"},
        )
        self.assertIn("rate_minor", invalid["detail"])
        invalid = self.json(
            "POST",
            f"/venues/{self.venue_id}/pay-profiles/{profile_id}/components",
            expected=400,
            json={
                "component_type": "PERCENT_TOTAL_REVENUE",
                "title": "Bad limits",
                "percent_bps": 100,
                "minimum_guarantee_minor": 200,
                "maximum_cap_minor": 100,
            },
        )
        self.assertIn("minimum_guarantee_minor", invalid["detail"])

    def test_expenses_recurring_rules_and_ledger_entries_reconcile(self):
        baseline_reconciliation = self.json(
            "GET",
            f"/venues/{self.venue_id}/finance/reconciliation",
            params={"month": self.month},
        )
        before = self.json(
            "GET",
            f"/venues/{self.venue_id}/expenses/period-summary",
            params={"month": self.month},
        )
        expense = self.json(
            "POST",
            f"/venues/{self.venue_id}/expenses",
            json={
                "category_id": self.category_id,
                "supplier_id": self.supplier_id,
                "payment_method_id": self.payment_method_ids[0],
                "amount_minor": 120_000,
                "expense_date": "2026-09-10",
                "spread_months": 3,
                "status": "CONFIRMED",
                "comment": "three-month recognition",
            },
        )
        self.assertEqual([row["amount_minor"] for row in expense["allocations"]], [40_000, 40_000, 40_000])
        after = self.json(
            "GET",
            f"/venues/{self.venue_id}/expenses/period-summary",
            params={"month": self.month},
        )
        self.assertEqual(after["total_minor"] - before["total_minor"], 40_000)

        expense = self.json(
            "PATCH",
            f"/venues/{self.venue_id}/expenses/{expense['id']}",
            json={"amount_minor": 150_000, "clear_supplier": True},
        )
        self.assertEqual([row["amount_minor"] for row in expense["allocations"]], [50_000, 50_000, 50_000])
        after_update = self.json(
            "GET",
            f"/venues/{self.venue_id}/expenses/period-summary",
            params={"month": self.month},
        )
        self.assertEqual(after_update["total_minor"] - before["total_minor"], 50_000)

        adjustment = self.json(
            "POST",
            f"/venues/{self.venue_id}/balance-adjustments",
            json={
                "payment_method_id": self.payment_method_ids[0],
                "adjustment_date": "2026-09-20",
                "delta_minor": 1_111,
                "status": "CONFIRMED",
                "reason": "cash count",
            },
        )
        transfer = self.json(
            "POST",
            f"/venues/{self.venue_id}/payment-method-transfers",
            json={
                "from_payment_method_id": self.payment_method_ids[0],
                "to_payment_method_id": self.payment_method_ids[1],
                "transfer_date": "2026-09-20",
                "amount_minor": 3_333,
                "status": "CONFIRMED",
            },
        )
        entries = self.json(
            "GET",
            f"/venues/{self.venue_id}/finance/entries",
            params={"month": self.month},
        )
        adjustment_entries = [row for row in entries if row["source_type"] == "balance_adjustment"]
        transfer_entries = [row for row in entries if row["source_type"] == "payment_method_transfer"]
        self.assertEqual([(row["direction"], row["amount_minor"]) for row in adjustment_entries], [("INCOME", 1_111)])
        self.assertEqual(
            sorted((row["direction"], row["amount_minor"]) for row in transfer_entries),
            [("EXPENSE", 3_333), ("INCOME", 3_333)],
        )
        analytics = self.json(
            "GET",
            f"/venues/{self.venue_id}/finance/entries/analytics",
            params={"month": self.month},
        )
        self.assertEqual(
            analytics["metrics"]["net_minor"],
            analytics["metrics"]["income_minor"] - analytics["metrics"]["expense_minor"],
        )
        reconciliation = self.json(
            "GET",
            f"/venues/{self.venue_id}/finance/reconciliation",
            params={"month": self.month},
        )
        self.assertEqual(reconciliation["issue_count"], baseline_reconciliation["issue_count"])
        self.assertEqual(
            {(item["check_key"], item["source_type"], item["source_id"]) for item in reconciliation["issues"]},
            {(item["check_key"], item["source_type"], item["source_id"]) for item in baseline_reconciliation["issues"]},
        )

        rule = self.json(
            "POST",
            f"/venues/{self.venue_id}/recurring-expense-rules",
            json={
                "title": "Monthly fixed regression",
                "category_id": self.category_id,
                "supplier_id": self.supplier_id,
                "payment_method_id": self.payment_method_ids[0],
                "payment_method_ids": [self.payment_method_ids[0]],
                "start_date": "2026-09-01",
                "frequency": "MONTHLY",
                "day_of_month": 12,
                "generation_mode": "FIXED",
                "amount_minor": 34_567,
                "spread_months": 1,
            },
        )
        generated = self.json(
            "POST",
            f"/venues/{self.venue_id}/recurring-expense-rules/generate",
            params={"month": self.month, "rule_id": rule["id"]},
        )
        self.assertEqual(generated["created_count"], 1)
        self.assertEqual(generated["created"][0]["amount_minor"], 34_567)
        repeated = self.json(
            "POST",
            f"/venues/{self.venue_id}/recurring-expense-rules/generate",
            params={"month": self.month, "rule_id": rule["id"]},
        )
        self.assertEqual(repeated["created_count"], 0)
        self.assertEqual(repeated["updated_count"], 1)
        self.assertEqual(repeated["updated"][0]["id"], generated["created"][0]["id"])

        self.json("DELETE", f"/venues/{self.venue_id}/balance-adjustments/{adjustment['id']}")
        self.json("DELETE", f"/venues/{self.venue_id}/payment-method-transfers/{transfer['id']}")
        self.json("DELETE", f"/venues/{self.venue_id}/expenses/{expense['id']}")
        self.json("DELETE", f"/venues/{self.venue_id}/recurring-expense-rules/{rule['id']}")

    def test_reports_summaries_revenue_and_exports_use_the_same_money(self):
        monthly = self.json(
            "GET",
            f"/venues/{self.venue_id}/summary/monthly",
            params={"month": self.month, "income_mode": "PAYMENTS"},
        )
        finance = self.json(
            "GET",
            f"/venues/{self.venue_id}/finance/summary",
            params={"month": self.month, "include_series": True},
        )
        revenue = self.json(
            "GET",
            f"/venues/{self.venue_id}/revenue",
            params={"month": self.month, "mode": "PAYMENTS"},
        )
        self.assertEqual(monthly["revenue_minor"], finance["revenue_minor"])
        self.assertEqual(monthly["revenue_breakdown_total_minor"], revenue["total"] * 100)
        self.assertEqual(
            monthly["revenue_breakdown_total_minor"] - monthly["revenue_minor"],
            monthly["revenue_discrepancy_minor"],
        )
        self.assertEqual(monthly["profit_minor"], monthly["revenue_minor"] - monthly["total_cost_minor"])
        self.assertEqual(finance["profit_minor"], finance["revenue_minor"] - finance["total_cost_minor"])
        self.assertEqual(
            sum(row["amount_minor"] for row in monthly["revenue_breakdown"]),
            monthly["revenue_breakdown_total_minor"],
        )

        day = self.json(
            "GET",
            f"/venues/{self.venue_id}/summary/day",
            params={"date": "2026-09-10", "income_mode": "PAYMENTS"},
        )
        self.assertEqual(day["profit_minor"], day["revenue_minor"] - day["total_cost_minor"])

        report = self.json(
            "POST",
            f"/venues/{self.venue_id}/reports",
            params={"shift_slot": "DAY"},
            json={
                "date": "2035-01-10",
                "cash": 10_000,
                "cashless": 20_000,
                "revenue_total": 30_000,
                "payments": [
                    {"ref_id": self.payment_method_ids[0], "value": 10_000},
                    {"ref_id": self.payment_method_ids[1], "value": 20_000},
                ],
                "departments": [
                    {"ref_id": self.department_ids[0], "value": 12_000},
                    {"ref_id": self.department_ids[1], "value": 18_000},
                ],
                "kpis": [{"ref_id": self.kpi_ids[0], "value": 3}],
                "comment": "money workflow regression",
            },
        )
        self.assertEqual(report["mode"], "created")
        loaded = self.json(
            "GET",
            f"/venues/{self.venue_id}/reports/2035-01-10",
            params={"shift_slot": "DAY"},
        )
        self.assertEqual(loaded["payments_total"], 30_000)
        self.assertEqual(loaded["departments_total"], 30_000)
        self.assertEqual(loaded["discrepancy"], 0)
        with patch("app.routers.venue_reports.process_pending_notification_jobs_once", return_value=None):
            closed = self.json(
                "POST",
                f"/venues/{self.venue_id}/reports/2035-01-10/close",
                params={"shift_slot": "DAY"},
                json={"comment": "close balanced report"},
            )
        self.assertEqual(closed["discrepancy"], 0)
        reopened = self.json(
            "POST",
            f"/venues/{self.venue_id}/reports/2035-01-10/reopen",
            params={"shift_slot": "DAY"},
        )
        self.assertEqual(reopened["status"], "DRAFT")

        export_links = [
            (f"/venues/{self.venue_id}/revenue/export-link", {"month": self.month, "mode": "PAYMENTS", "fmt": "csv"}),
            (f"/venues/{self.venue_id}/expenses/export-link", {"month": self.month}),
            (f"/venues/{self.venue_id}/summary/monthly/export-link", {"month": self.month}),
            (f"/venues/{self.venue_id}/payroll/export-link", {"month": self.month}),
            (f"/venues/{self.venue_id}/finance/entries/export-link", {"month": self.month}),
        ]
        for path, params in export_links:
            link = self.json("GET", path, params=params)
            exported = self.request("GET", link["export_path"])
            self.assertGreater(len(exported.content), 100)

    def test_day_economics_plans_rules_and_department_targets(self):
        day = self.json(
            "GET",
            f"/venues/{self.venue_id}/economics/day",
            params={"date": "2026-09-10", "shift_slot": "TOTAL"},
        )
        self.assertEqual(day["date"], "2026-09-10")
        self.assertEqual(
            day["summary"]["profit_minor"], day["summary"]["revenue_minor"] - day["summary"]["total_cost_minor"]
        )
        self.assertEqual(
            day["summary"]["revenue_breakdown_total_minor"] - day["summary"]["revenue_minor"],
            day["summary"]["revenue_discrepancy_minor"],
        )
        for slot in ("DAY", "NIGHT"):
            slot_day = self.json(
                "GET",
                f"/venues/{self.venue_id}/economics/day",
                params={"date": "2026-09-10", "shift_slot": slot},
            )
            self.assertEqual(slot_day["shift_slot"], slot)

        self.json("GET", f"/venues/{self.venue_id}/economics/plan", params={"date": "2026-09-10"})
        self.json("GET", f"/venues/{self.venue_id}/economics/plan/override", params={"date": "2026-09-10"})
        self.json("GET", f"/venues/{self.venue_id}/economics/plan-month", params={"month": self.month})
        self.json("GET", f"/venues/{self.venue_id}/economics/plan-templates")
        self.json("GET", f"/venues/{self.venue_id}/economics/department-plan-month", params={"month": self.month})
        self.json(
            "GET",
            f"/venues/{self.venue_id}/economics/department-plan-day",
            params={"date": "2026-09-10"},
        )

        previous_month = self.json(
            "PUT",
            f"/venues/{self.venue_id}/economics/plan-month",
            params={"month": "2034-12"},
            json={
                "revenue_plan_minor": 90_000_000,
                "profit_plan_minor": 20_000_000,
                "revenue_per_assigned_plan_minor": 2_000_000,
                "assigned_user_target": 8,
                "notes": "previous month target",
            },
        )
        self.assertEqual(previous_month["revenue_plan_minor"], 90_000_000)
        copied_month = self.json(
            "POST",
            f"/venues/{self.venue_id}/economics/plan-month/copy-previous",
            params={"month": "2035-01", "overwrite": True},
        )
        self.assertTrue(copied_month["copied"])
        self.assertEqual(copied_month["plan"]["revenue_plan_minor"], 90_000_000)

        override = self.json(
            "PUT",
            f"/venues/{self.venue_id}/economics/plan",
            params={"date": "2035-01-10"},
            json={
                "revenue_plan_minor": 4_000_000,
                "profit_plan_minor": 1_000_000,
                "revenue_per_assigned_plan_minor": 500_000,
                "assigned_user_target": 8,
                "day_kind": "SPECIAL",
                "title": "Test event",
            },
        )
        self.assertEqual(override["source"], "DATE_OVERRIDE")

        template = self.json(
            "PUT",
            f"/venues/{self.venue_id}/economics/plan-templates/0",
            json={
                "revenue_plan_minor": 3_000_000,
                "profit_plan_minor": 700_000,
                "assigned_user_target": 6,
            },
        )
        self.assertEqual(template["weekday"], 0)
        copied_templates = self.json(
            "POST",
            f"/venues/{self.venue_id}/economics/plan-templates/copy",
            json={"source_weekday": 0, "target_weekdays": [1, 2], "overwrite": True},
        )
        self.assertEqual(copied_templates["copied_count"], 2)

        month_items = [
            {"department_id": department_id, "revenue_plan_minor": 10_000_000 + index * 1_000_000}
            for index, department_id in enumerate(self.department_ids)
        ]
        month_plan = self.json(
            "PUT",
            f"/venues/{self.venue_id}/economics/department-plan-month",
            params={"month": "2034-12"},
            json={"items": month_items},
        )
        self.assertEqual(month_plan["saved_count"], len(self.department_ids))
        autofilled = self.json(
            "POST",
            f"/venues/{self.venue_id}/economics/department-plan-month/autofill-from-last-month",
            params={"month": "2035-01", "overwrite": True},
        )
        self.assertEqual(autofilled["copied"], len(self.department_ids))
        distributed = self.json(
            "POST",
            f"/venues/{self.venue_id}/economics/department-plan-month/distribute-from-venue-plan",
            params={"month": "2035-01", "overwrite": True},
        )
        self.assertEqual(distributed["distributed_total_minor"], 90_000_000)

        day_items = [
            {"department_id": department_id, "revenue_plan_minor": 1_000_000 + index * 100_000}
            for index, department_id in enumerate(self.department_ids)
        ]
        department_day = self.json(
            "PUT",
            f"/venues/{self.venue_id}/economics/department-plan-day",
            params={"date": "2035-01-10"},
            json={"items": day_items},
        )
        self.assertEqual(department_day["saved_count"], len(self.department_ids))
        copied_day = self.json(
            "POST",
            f"/venues/{self.venue_id}/economics/department-plan-day/copy-from-date",
            params={"source_date": "2035-01-10", "target_date": "2035-01-11", "overwrite": True},
        )
        self.assertEqual(copied_day["copied"], len(self.department_ids))
        history_day = self.json(
            "POST",
            f"/venues/{self.venue_id}/economics/department-plan-day/autofill-from-history",
            params={
                "target_date": "2026-09-17",
                "mode": "SAME_WEEKDAY_AVG",
                "overwrite": True,
                "lookback_weeks": 2,
            },
        )
        self.assertEqual(history_day["mode"], "SAME_WEEKDAY_AVG")

        rules = self.json(
            "PUT",
            f"/venues/{self.venue_id}/economics/rules",
            json={
                "max_expense_ratio_bps": 3500,
                "max_payroll_ratio_bps": 4000,
                "min_revenue_per_assigned_minor": 500_000,
                "min_assigned_shift_coverage_bps": 8000,
                "min_profit_minor": 100_000,
                "warn_on_draft_expenses": False,
            },
        )
        self.assertEqual(rules["max_expense_ratio_bps"], 3500)
        self.assertFalse(rules["warn_on_draft_expenses"])
        self.assertEqual(
            self.json("GET", f"/venues/{self.venue_id}/economics/rules"),
            rules,
        )

    def test_money_configuration_catalogs_positions_and_setup(self):
        """Exercise every editable input that can change a money calculation."""
        base = f"/venues/{self.venue_id}"
        catalog_cases = [
            ("departments", {"code": "test_food", "title": "Test food", "sort_order": 71}),
            ("payment-methods", {"code": "test_card", "title": "Test card", "sort_order": 72}),
            ("expense-categories", {"code": "test_rent", "title": "Test rent", "sort_order": 73}),
        ]
        for route, payload in catalog_cases:
            created = self.json("POST", f"{base}/{route}", json=payload)
            item_id = created["id"]
            self.json(
                "PATCH",
                f"{base}/{route}/{item_id}",
                json={"title": f"{payload['title']} updated", "sort_order": 91, "is_active": False},
            )
            archived = self.json("GET", f"{base}/{route}", params={"include_archived": True})
            saved = next(item for item in archived if item["id"] == item_id)
            self.assertFalse(saved["is_active"])
            self.assertEqual(saved["sort_order"], 91)

        kpi = self.json(
            "POST",
            f"{base}/kpi-metrics",
            json={"code": "test_check", "title": "Average check", "unit": "RUB", "sort_order": 74},
        )
        self.json(
            "PATCH",
            f"{base}/kpi-metrics/{kpi['id']}",
            json={"title": "Average check updated", "unit": "QTY", "is_active": False},
        )
        kpi_rows = self.json("GET", f"{base}/kpi-metrics", params={"include_archived": True})
        saved_kpi = next(item for item in kpi_rows if item["id"] == kpi["id"])
        self.assertEqual(saved_kpi["unit"], "QTY")
        self.assertFalse(saved_kpi["is_active"])

        supplier = self.json(
            "POST",
            f"{base}/suppliers",
            json={"title": "Test supplier", "contact": "+79990000000", "sort_order": 75},
        )
        self.json(
            "PATCH",
            f"{base}/suppliers/{supplier['id']}",
            json={"title": "Test supplier updated", "contact": "mail@example.test", "is_active": False},
        )
        supplier_rows = self.json("GET", f"{base}/suppliers", params={"include_archived": True})
        saved_supplier = next(item for item in supplier_rows if item["id"] == supplier["id"])
        self.assertEqual(saved_supplier["contact"], "mail@example.test")
        self.assertFalse(saved_supplier["is_active"])

        self.request(
            "POST",
            f"{base}/departments",
            expected=400,
            json={"code": "bad code!", "title": "Invalid"},
        )
        self.request("PATCH", f"{base}/expense-categories/999999", expected=404, json={"title": "Missing"})
        self.request("PATCH", f"{base}/suppliers/999999", expected=404, json={"title": "Missing"})

        profiles = self.json("GET", f"{base}/pay-profiles")
        profile_id = profiles[0]["id"]
        catalog_position = self.json(
            "POST",
            f"{base}/positions",
            json={
                "title": "Money tester",
                "rate": 125_000,
                "percent": 7,
                "pay_profile_id": profile_id,
                "permission_codes": ["PAYROLL_VIEW", "SHIFT_REPORT_VIEW"],
            },
        )
        self.assertEqual(catalog_position["mode"], "created_catalog")
        assigned = self.json(
            "PATCH",
            f"{base}/positions/{catalog_position['id']}",
            json={"member_user_id": self.staff_id, "pay_profile_effective_from": "2026-09-01"},
        )
        self.assertEqual(assigned["member_user_id"], self.staff_id)
        self.assertEqual(assigned["rate"], 125_000)
        positions = self.json("GET", f"{base}/positions", params={"include_inactive": True})
        saved_position = next(item for item in positions if item["id"] == assigned["id"])
        self.assertEqual(saved_position["pay_profile_id"], profile_id)
        self.assertEqual(set(saved_position["permission_codes"]), {"PAYROLL_VIEW", "SHIFT_REPORT_VIEW"})
        archived = self.json("DELETE", f"{base}/positions/{assigned['id']}")
        self.assertTrue(archived["ok"])

        initial_settings = self.json("GET", f"{base}/settings")
        changed_settings = self.json(
            "PATCH",
            f"{base}/settings",
            json={
                "tips_enabled": not initial_settings["tips_enabled"],
                "tips_split_mode": "WEIGHTED_BY_POSITION",
                "tips_weights": {"Money tester": 3},
            },
        )
        self.assertEqual(changed_settings["tips_split_mode"], "WEIGHTED_BY_POSITION")
        self.assertEqual(changed_settings["tips_weights"], {"Money tester": 3})
        self.request(
            "PATCH",
            f"{base}/settings",
            expected=400,
            json={"tips_split_mode": "NOT_A_MODE"},
        )

        started = self.json("POST", f"{base}/setup/start")
        self.assertIn(started["status"], {"IN_PROGRESS", "PREPARE_DONE", "EXTRA_IN_PROGRESS", "DONE"})
        patched = self.json(
            "PATCH",
            f"{base}/setup",
            json={
                "current_step_key": "payment_methods",
                "phase": "PREPARE",
                "step_meta": {"positions": {"presets": [{"title": "Cashier", "is_active": True}]}},
            },
        )
        self.assertEqual(patched["current_step_key"], "payment_methods")
        for step_key in ("payment_methods", "departments", "pay_profiles", "positions", "shift_intervals"):
            completed = self.json("POST", f"{base}/setup/complete-step", json={"step_key": step_key})
            self.assertIn(step_key, completed["completed_steps"])
        skipped = self.json("POST", f"{base}/setup/skip-step", json={"step_key": "kpi"})
        self.assertIn("kpi", skipped["skipped_steps"])
        reset = self.json("POST", f"{base}/setup/reset-step", json={"step_key": "kpi"})
        self.assertNotIn("kpi", reset["skipped_steps"])
        self.json("POST", f"{base}/setup/skip-step", json={"step_key": "kpi"})
        self.json("POST", f"{base}/setup/skip-step", json={"step_key": "invites"})
        prepared = self.json("POST", f"{base}/setup/finish-prepare")
        self.assertTrue(prepared["prepare_done"])
        for step_key in ("expense_categories", "suppliers", "recurring_expenses"):
            self.json("POST", f"{base}/setup/skip-step", json={"step_key": step_key})
        finished = self.json("POST", f"{base}/setup/finish-extra")
        self.assertEqual(finished["status"], "DONE")
        renamed = self.json("PATCH", f"{base}/setup/venue", json={"name": "Axelio money QA"})
        self.assertEqual(renamed["name"], "Axelio money QA")
        self.assertEqual(self.json("GET", f"{base}/setup")["status"], "DONE")

    def test_money_notification_payloads_and_worker_dispatch(self):
        notifications = venue_economics_notifications
        alerts = [
            {"code": "LOSS_DAY", "severity": "CRITICAL", "title": "Loss", "detail": "Negative result"},
            {
                "code": "EXPENSE_RATIO_HIGH",
                "severity": "WARN",
                "title": "Expenses",
                "detail": "Above limit",
            },
            {"code": "REPORT_NOT_CLOSED", "severity": "WARN", "title": "Draft", "detail": "Not closed"},
            {"code": "LOSS_DAY", "severity": "WARN", "title": "Duplicate", "detail": "Ignored"},
            {"code": "INFO_ONLY", "severity": "INFO", "title": "Info", "detail": "Ignored"},
        ]
        economics = {
            "summary": {
                "revenue_minor": 1_000_050,
                "expense_minor": 400_000,
                "payroll_minor": 350_000,
                "profit_minor": 250_050,
                "payroll_ratio_bps": 3500,
                "point_expense_minor": 250_000,
                "recurring_expense_minor": 150_000,
                "draft_expense_total_minor": 12_300,
                "draft_expense_count": 2,
                "slot_profit_available": True,
                "point_expenses": [{"title": "Products", "amount_minor": 250_000}],
                "recurring_expenses": [{"title": "Rent", "amount_minor": 150_000}],
            },
            "metrics": {
                "expense_ratio_bps": 4000,
                "payroll_ratio_bps": 3500,
                "assigned_shift_coverage_bps": 7800,
            },
            "rules": {
                "max_expense_ratio_bps": 3000,
                "max_payroll_ratio_bps": 3000,
                "min_assigned_shift_coverage_bps": 8000,
                "warn_on_draft_expenses": True,
            },
            "alerts": alerts,
            "payment_revenue_breakdown": [
                {"title": f"Payment {index}", "amount_minor": 100_000 + index} for index in range(9)
            ],
            "department_revenue_breakdown": [
                {"title": f"Department {index}", "amount_minor": 200_000 + index} for index in range(9)
            ],
        }
        selected = notifications._select_soft_alerts_for_notification(economics)
        self.assertEqual([item["code"] for item in selected], ["LOSS_DAY", "EXPENSE_RATIO_HIGH", "REPORT_NOT_CLOSED"])
        self.assertEqual(notifications._notification_detail_level("wrong"), "standard")
        self.assertEqual(notifications._normalize_notification_shift_slot("wrong"), "TOTAL")
        self.assertEqual(notifications._fmt_money_minor(-12_345), "-123.45 ₽")
        self.assertEqual(notifications._fmt_percent_bps(None), "—")
        self.assertEqual(notifications._fmt_percent_bps(1250), "12.5%")
        self.assertEqual(notifications._soft_alert_signature([]), "none")
        self.assertEqual(notifications._render_breakdown("Empty", [], limit=4), ["Empty: —"])

        for locale in ("ru", "en"):
            for level in ("short", "standard", "detailed"):
                soft_text = notifications._build_soft_alerts_notification_text(
                    venue_name="Axelio QA",
                    target_date=date(2026, 9, 10),
                    economics=economics,
                    alerts=selected,
                    detail_level=level,
                    shift_slot="NIGHT",
                    locale=locale,
                )
                self.assertIn("Axelio QA", soft_text)
                day_text = notifications._build_day_economics_notification_text(
                    venue_name="Axelio QA",
                    target_date=date(2026, 9, 10),
                    economics=economics,
                    detail_level=level,
                    shift_slot="DAY",
                    locale=locale,
                )
                self.assertIn("Axelio QA", day_text)

        slot_economics = {**economics, "summary": {**economics["summary"], "slot_profit_available": False}}
        self.assertIn(
            "Full day",
            notifications._build_day_economics_notification_text(
                venue_name="Axelio QA",
                target_date=date(2026, 9, 10),
                economics=slot_economics,
                detail_level="standard",
                shift_slot="NIGHT",
                locale="en",
            ),
        )

        salary = {
            "state": "partial",
            "summary": {
                "total_minor": 185_000,
                "earnings_minor": 150_000,
                "tips_minor": 20_000,
                "bonuses_minor": 25_000,
                "penalties_minor": 10_000,
            },
            "context": {"hours_total": "8.5", "shifts_count": 1},
            "items": [
                {
                    "title": f"Component {index}",
                    "amount_minor": 10_000 + index,
                    "base_text": "8.5 hours",
                    "formula_text": "rate × hours",
                }
                for index in range(9)
            ],
        }
        for state in ("partial", "no_payroll", "empty", "ready"):
            rendered = notifications._build_salary_day_breakdown_text(
                venue_name="Axelio QA",
                target_date=date(2026, 9, 10),
                breakdown={**salary, "state": state},
                detail_level="detailed",
                shift_slot="TOTAL",
                locale="en",
            )
            self.assertIn("Axelio QA", rendered)

        factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        target_date = date(2026, 9, 10)
        success_result = {"ok": True, "retryable": False}
        with factory() as db:
            owner = db.get(User, int(self.owner.id))
            staff = db.get(User, int(self.staff_id))
            owner.tg_user_id = 9_001
            staff.tg_user_id = 9_002
            owner.notify_day_economics = True
            owner.notify_soft_alerts = True
            staff.notify_salary = True
            db.commit()

        with (
            factory() as db,
            patch.object(
                notifications,
                "_can_receive_day_economics_summary",
                side_effect=lambda _db, *, venue_id, user: bool(getattr(user, "tg_user_id", None)),
            ),
            patch.object(
                notifications,
                "_can_receive_soft_alerts",
                side_effect=lambda _db, *, venue_id, user: bool(getattr(user, "tg_user_id", None)),
            ),
            patch.object(notifications, "_should_notify_user", return_value=True),
            patch.object(notifications, "get_day_economics", return_value=economics),
            patch.object(notifications, "build_member_day_breakdown", return_value=salary),
            patch.object(notifications, "notification_delivery_exists", return_value=False),
            patch.object(notifications, "lock_notification_idempotency_key", return_value=None),
            patch.object(notifications, "disable_unreachable_telegram_recipient", return_value=False),
            patch.object(notifications.tg_notify, "notify_result", return_value=success_result) as notify,
        ):
            notifications._send_day_economics_summary_notifications(
                db,
                venue_id=self.venue_id,
                target_date=target_date,
                shift_slot="DAY",
                event_key="money-day",
            )
            notifications._send_soft_alert_notifications(
                db,
                venue_id=self.venue_id,
                target_date=target_date,
                shift_slot="NIGHT",
                event_key="money-alerts",
            )
            notifications._send_salary_day_breakdown_notifications(
                db,
                venue_id=self.venue_id,
                target_date=target_date,
                shift_slot="TOTAL",
                event_key="money-salary",
            )
            self.assertGreater(notify.call_count, 3)

        failed_result = {"ok": False, "retryable": False, "error": "delivery failed"}
        with (
            factory() as db,
            patch.object(
                notifications,
                "_can_receive_soft_alerts",
                side_effect=lambda _db, *, venue_id, user: bool(getattr(user, "tg_user_id", None)),
            ),
            patch.object(notifications, "get_day_economics", return_value=economics),
            patch.object(notifications, "notification_delivery_exists", return_value=False),
            patch.object(notifications, "lock_notification_idempotency_key", return_value=None),
            patch.object(notifications, "disable_unreachable_telegram_recipient", return_value=False),
            patch.object(notifications.tg_notify, "notify_result", return_value=failed_result),
        ):
            with self.assertRaises(notifications.NotificationDeliveryError) as raised:
                notifications._send_soft_alert_notifications(
                    db,
                    venue_id=self.venue_id,
                    target_date=target_date,
                    shift_slot="TOTAL",
                    event_key="money-alerts-failed",
                )
            self.assertFalse(raised.exception.retryable)

        with factory() as db:
            salary_job = notifications._enqueue_salary_day_breakdown_job(
                db, venue_id=self.venue_id, target_date=target_date, shift_slot="DAY", event_key="money-test"
            )
            self.assertEqual(
                notifications._enqueue_salary_day_breakdown_job(
                    db, venue_id=self.venue_id, target_date=target_date, shift_slot="DAY", event_key="money-test"
                ).id,
                salary_job.id,
            )
            notifications._enqueue_soft_alerts_job(
                db, venue_id=self.venue_id, target_date=target_date, shift_slot="NIGHT", event_key="money-test"
            )
            notifications._enqueue_day_economics_summary_job(
                db, venue_id=self.venue_id, target_date=target_date, shift_slot="TOTAL", event_key="money-test"
            )
            db.commit()

        with (
            patch.object(notifications, "SessionLocal", factory),
            patch.object(notifications, "_send_salary_day_breakdown_notifications") as salary_sender,
            patch.object(notifications, "_send_soft_alert_notifications") as alerts_sender,
            patch.object(notifications, "_send_day_economics_summary_notifications") as economics_sender,
        ):
            self.assertEqual(notifications.process_pending_notification_jobs_once(limit=3), 3)
        salary_sender.assert_called_once()
        alerts_sender.assert_called_once()
        economics_sender.assert_called_once()

        with factory() as db:
            statuses = list(db.execute(select(NotificationJob.status)).scalars())
            self.assertEqual(statuses.count(notifications._NOTIFICATION_JOB_STATUS_SENT), 3)
            db.add(
                NotificationJob(
                    job_type="UNSUPPORTED_MONEY_JOB",
                    status=notifications._NOTIFICATION_JOB_STATUS_PENDING,
                    payload_json="{}",
                    attempts=0,
                    max_attempts=1,
                    run_after=datetime.utcnow(),
                    idempotency_key="unsupported-money-job",
                )
            )
            db.commit()
        with patch.object(notifications, "SessionLocal", factory), patch.object(notifications.log, "exception"):
            self.assertEqual(notifications.process_pending_notification_jobs_once(limit=1), 1)
        with factory() as db:
            failed = db.execute(
                select(NotificationJob).where(NotificationJob.idempotency_key == "unsupported-money-job")
            ).scalar_one()
            self.assertEqual(failed.status, notifications._NOTIFICATION_JOB_STATUS_FAILED)

    def test_adjustment_money_lifecycle_and_dispute_permissions(self):
        before = self.json("GET", f"/venues/{self.venue_id}/adjustments", params={"month": self.month})
        created = self.json(
            "POST",
            f"/venues/{self.venue_id}/adjustments",
            json={
                "type": "bonus",
                "date": "2026-09-20",
                "amount": 12_345,
                "reason": "money lifecycle",
                "member_user_id": self.staff_id,
            },
        )
        adjustment_id = created["id"]
        self.json(
            "PATCH",
            f"/venues/{self.venue_id}/adjustments/{adjustment_id}",
            json={"amount": 23_456, "reason": "updated money lifecycle"},
        )
        listed = self.json(
            "GET",
            f"/venues/{self.venue_id}/adjustments",
            params={"date_from": "2026-09-01", "date_to": "2026-09-30", "type": "bonus"},
        )
        row = next(item for item in listed["items"] if item["id"] == adjustment_id)
        self.assertEqual(row["amount"], 23_456)

        self.current_user = self.staff
        mine = self.json("GET", f"/venues/{self.venue_id}/adjustments", params={"month": self.month, "mine": 1})
        self.assertIn(adjustment_id, {item["id"] for item in mine["items"]})
        dispute = self.json(
            "POST",
            f"/venues/{self.venue_id}/adjustments/bonus/{adjustment_id}/dispute",
            json={"message": "Please verify the amount"},
        )
        dispute_id = dispute["dispute_id"]
        self.json(
            "POST",
            f"/venues/{self.venue_id}/disputes/{dispute_id}/comments",
            json={"message": "Additional calculation context"},
        )
        thread = self.json(
            "GET",
            f"/venues/{self.venue_id}/adjustments/bonus/{adjustment_id}/dispute",
        )
        self.assertEqual(len(thread["comments"]), 2)

        self.current_user = self.owner
        disputes = self.json(
            "GET",
            f"/venues/{self.venue_id}/disputes",
            params={"status": "OPEN", "month": self.month},
        )
        self.assertIn(dispute_id, {item["dispute_id"] for item in disputes["items"]})
        self.json(
            "PATCH",
            f"/venues/{self.venue_id}/disputes/{dispute_id}",
            json={"status": "CLOSED"},
        )
        closed = self.json(
            "GET",
            f"/venues/{self.venue_id}/adjustments/bonus/{adjustment_id}/dispute",
        )
        self.assertEqual(closed["dispute"]["status"], "CLOSED")
        self.json("DELETE", f"/venues/{self.venue_id}/adjustments/{adjustment_id}")
        after = self.json("GET", f"/venues/{self.venue_id}/adjustments", params={"month": self.month})
        self.assertEqual(len(after["items"]), len(before["items"]))

    def test_billing_money_admin_and_owner_views_reconcile(self):
        owner_billing = self.json("GET", f"/venues/{self.venue_id}/billing")
        self.assertEqual(owner_billing["billing_access_mode"], "FULL")
        self.assertEqual(owner_billing["plan"]["price_minor"], 299_000)

        self.owner.system_role = "SUPER_ADMIN"
        promo = self.json(
            "POST",
            "/admin/billing/promocodes",
            json={
                "code": "MONEY10",
                "title": "Money regression",
                "kind": "PERCENT",
                "percent_value": 10,
            },
        )["item"]
        self.assertEqual(promo["code"], "MONEY10")
        promo = self.json(
            "PATCH",
            f"/admin/billing/promocodes/{promo['id']}",
            json={"percent_value": 15},
        )["item"]
        self.assertEqual(promo["percent_value"], 15)

        self.owner.system_role = "NONE"
        preview = self.json(
            "GET",
            f"/venues/{self.venue_id}/billing/promocode/preview",
            params={"code": "MONEY10"},
        )["preview"]
        self.assertEqual(preview["price_before_minor"], 299_000)
        self.assertEqual(preview["discount_minor"], 44_850)
        self.assertEqual(preview["amount_after_minor"], 254_150)

        self.owner.system_role = "SUPER_ADMIN"
        with patch("app.routers.admin_billing.send_owner_billing_notification_once", return_value=None):
            extended = self.json(
                "POST",
                f"/admin/venues/{self.venue_id}/billing/extend",
                json={"days": 10, "amount_minor": 1_000, "comment": "test extension"},
            )
            fixed = self.json(
                "POST",
                f"/admin/venues/{self.venue_id}/billing/set-paid-until",
                json={"paid_until": "2028-01-01T00:00:00Z", "amount_minor": 2_000},
            )
        self.assertEqual(extended["transaction"]["amount_minor"], 1_000)
        self.assertTrue(fixed["billing"]["paid_until"].startswith("2028-01-01"))

        summary = self.json("GET", "/admin/billing/summary")
        self.assertEqual(summary["totals"]["venues_total"], 1)
        self.assertEqual(summary["totals"]["mrr_minor"], 299_000)
        venues = self.json("GET", "/admin/billing/venues", params={"sort_by": "name_asc"})
        self.assertEqual(venues["total"], 1)
        transactions = self.json(
            "GET",
            "/admin/billing/transactions",
            params={"venue_id": self.venue_id},
        )
        self.assertGreaterEqual(transactions["total"], 3)
        self.json("GET", "/admin/billing/reconciliation", params={"venue_id": self.venue_id})
        health = self.json("GET", "/admin/billing/health")
        self.assertIn("totals", health)
        for path in (
            "/admin/billing/transactions/export?fmt=csv",
            "/admin/billing/reconciliation/export?fmt=csv",
            f"/venues/{self.venue_id}/billing/transactions/export?fmt=csv",
        ):
            exported = self.request("GET", path)
            self.assertGreater(len(exported.content), 50)

        archived = self.json("POST", f"/admin/billing/promocodes/{promo['id']}/archive")["item"]
        self.assertFalse(archived["is_active"])

    def test_billing_promotions_checkout_failures_and_free_extension(self):
        base = f"/venues/{self.venue_id}/billing"
        self.owner.system_role = "SUPER_ADMIN"
        free = self.json(
            "POST",
            "/admin/billing/promocodes",
            json={
                "code": "FREE45",
                "title": "Free 45 days",
                "kind": "FREE_DAYS",
                "free_days": 45,
                "comment": "money regression",
            },
        )["item"]
        preview = self.json("GET", f"{base}/promocode/preview", params={"code": " free45 "})["preview"]
        self.assertEqual(preview["amount_after_minor"], 0)
        self.assertEqual(preview["days_added"], 45)
        self.assertFalse(preview["payment_required"])

        checkout = self.json("POST", f"{base}/checkout", json={"promo_code": "FREE45"})
        self.assertTrue(checkout["payment_skipped"])
        self.assertEqual(checkout["amount_minor"], 0)
        self.assertEqual(checkout["promo_applied"]["days_added"], 45)
        billing = self.json("GET", base)
        self.assertFalse(billing["can_use_promo_code"])
        self.assertEqual(billing["promo_redemption"]["promo_code_value"], "FREE45")
        self.request("POST", f"{base}/checkout", expected=400, json={"promo_code": "FREE45"})

        fixed = self.json(
            "POST",
            "/admin/billing/promocodes",
            json={"code": "FIXED500", "kind": "FIXED_MINOR", "amount_minor": 50_000},
        )["item"]
        percent = self.json(
            "POST",
            "/admin/billing/promocodes",
            json={"code": "PERCENT20", "kind": "PERCENT", "percent_value": 20},
        )["item"]
        self.assertEqual({fixed["kind"], percent["kind"]}, {"FIXED_MINOR", "PERCENT"})

        self.request("GET", f"{base}/promocode/preview", expected=400, params={"code": "NO-SUCH-PROMO"})
        self.request("POST", f"{base}/checkout", expected=503, json={})
        self.request(
            "POST",
            "/admin/billing/promocodes",
            expected=400,
            json={"code": "BROKEN", "kind": "PERCENT"},
        )
        self.request(
            "POST",
            "/admin/billing/promocodes",
            expected=400,
            json={"code": "PERCENT20", "kind": "PERCENT", "percent_value": 10},
        )
        self.request("PATCH", "/admin/billing/promocodes/999999", expected=404, json={"title": "Missing"})
        self.request("POST", "/admin/billing/promocodes/999999/archive", expected=404)
        self.request(
            "POST",
            f"/admin/venues/{self.venue_id}/billing/refund",
            expected=503,
            json={"amount_minor": 10_000, "comment": "provider disabled"},
        )
        self.request("POST", "/admin/venues/999999/billing/extend", expected=404, json={"days": 1})
        self.request(
            "POST",
            "/admin/venues/999999/billing/set-paid-until",
            expected=404,
            json={"paid_until": "2035-01-01T00:00:00Z"},
        )
        self.request("POST", "/admin/venues/999999/billing/refund", expected=404, json={"amount_minor": 10_000})

        promo_rows = self.json("GET", "/admin/billing/promocodes")["items"]
        self.assertGreaterEqual(len(promo_rows), 3)
        for params in (
            {"status": "SUCCEEDED"},
            {"tx_type": "PAYMENT"},
            {"source": "PROMOCODE"},
            {"q": "FREE45"},
            {"date_from": "2026-01-01", "date_to": "2036-01-01"},
        ):
            self.json("GET", "/admin/billing/transactions", params=params)
        for sort_by in ("status", "paid_until_asc", "paid_until_desc", "name_desc"):
            self.json("GET", "/admin/billing/venues", params={"sort_by": sort_by, "q": "Axelio"})

        self.json("POST", f"/admin/billing/promocodes/{fixed['id']}/archive")
        self.json("POST", f"/admin/billing/promocodes/{percent['id']}/archive")
        self.json("POST", f"/admin/billing/promocodes/{free['id']}/archive")

    def test_billing_manager_money_state_machine_and_refunds(self):
        self.assertEqual(billing_manager.parse_amount_minor("2990.005"), 299_001)
        self.assertEqual(billing_manager.parse_amount_minor(None), 0)
        self.assertIsNone(billing_manager.get_checkout_expires_at(None))

        now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        with (
            Session(self.engine, expire_on_commit=False) as db,
            patch.object(billing_manager, "utcnow", return_value=now),
        ):
            state = billing_manager.get_or_create_billing_state(db, venue_id=self.venue_id)
            state.status = "ACTIVE"
            state.paid_until = now - timedelta(days=1)
            state.grace_until = now + timedelta(days=2)
            db.flush()

            synced, snapshot, event = billing_manager.sync_billing_state(
                db, state=state, now=now, created_by_user_id=self.owner.id
            )
            self.assertEqual(synced.status, snapshot.status)
            self.assertIsNotNone(event)
            _, _, no_event = billing_manager.sync_billing_state(db, state=state, now=now)
            self.assertIsNone(no_event)

            first = billing_manager.create_checkout_transaction(
                db,
                venue_id=self.venue_id,
                created_by_user_id=self.owner.id,
                amount_minor=299_000,
                days_added=30,
                provider_payload_json={"promo": {"code": "STATE"}},
            )
            self.assertEqual(first.provider_invoice_id, str(first.id))
            self.assertIs(billing_manager.get_latest_pending_checkout(db, venue_id=self.venue_id), first)
            reused = billing_manager.create_checkout_transaction(
                db, venue_id=self.venue_id, created_by_user_id=self.owner.id, amount_minor=299_000
            )
            self.assertEqual(reused.id, first.id)
            replacement = billing_manager.create_checkout_transaction(
                db,
                venue_id=self.venue_id,
                created_by_user_id=self.owner.id,
                amount_minor=249_000,
                days_added=45,
                replace_existing=True,
            )
            self.assertEqual(first.status, "CANCELED")
            self.assertNotEqual(replacement.id, first.id)
            self.assertEqual(
                billing_manager.get_billing_transaction_by_invoice_id(db, invoice_id=replacement.id).id,
                replacement.id,
            )
            with self.assertRaisesRegex(ValueError, "amount mismatch"):
                billing_manager.apply_checkout_payment_success(
                    db, transaction=replacement, amount_minor=1, provider_payment_id="bad"
                )
            state, paid, paid_event, applied = billing_manager.apply_checkout_payment_success(
                db,
                transaction=replacement,
                amount_minor=249_000,
                provider_payment_id="op-payment",
                provider_payload_json=["provider", "payload"],
            )
            self.assertTrue(applied)
            self.assertEqual(paid.status, "SUCCEEDED")
            self.assertEqual(paid_event.event_type, "ROBOKASSA_PAYMENT_SUCCEEDED")
            _, _, second_event, applied_again = billing_manager.apply_checkout_payment_success(
                db, transaction=paid, amount_minor=249_000
            )
            self.assertFalse(applied_again)
            self.assertIsNone(second_event)
            unchanged, ignored_event = billing_manager.mark_checkout_transaction_failed(db, transaction=paid)
            self.assertIs(unchanged, paid)
            self.assertIsNone(ignored_event)

            manual_refund, manual_refund_event = billing_manager.create_refund_transaction(
                db,
                venue_id=self.venue_id,
                amount_minor=-50,
                created_by_user_id=self.owner.id,
                comment="manual refund",
                revoke_access_hint=True,
            )
            self.assertEqual(manual_refund.amount_minor, 0)
            self.assertTrue(manual_refund.provider_payload_json["revoke_access_hint"])
            self.assertEqual(manual_refund_event.event_type, "BILLING_REFUND_CREATED")

            external, request_event = billing_manager.create_external_refund_transaction(
                db,
                venue_id=self.venue_id,
                target_payment_transaction=paid,
                amount_minor=50_000,
                request_id="refund-request",
                op_key="op-payment",
                created_by_user_id=self.owner.id,
            )
            self.assertEqual(request_event.event_type, "ROBOKASSA_REFUND_REQUESTED")
            self.assertEqual(
                billing_manager.get_reserved_refund_amount_for_payment(db, payment_transaction_id=paid.id),
                50_000,
            )
            self.assertEqual(
                billing_manager.get_refundable_payment_transaction(
                    db, venue_id=self.venue_id, requested_amount_minor=199_000
                ).id,
                paid.id,
            )
            self.assertIsNone(
                billing_manager.get_refundable_payment_transaction(
                    db, venue_id=self.venue_id, requested_amount_minor=250_000
                )
            )
            self.assertIn(
                external.id,
                {item.id for item in billing_manager.list_pending_external_refund_transactions(db, limit=10)},
            )
            processing, processing_event = billing_manager.sync_external_refund_transaction_state(
                db, transaction=external, refund_state_label="processing"
            )
            self.assertEqual(processing.status, "PENDING")
            self.assertIsNone(processing_event)
            finished, finished_event = billing_manager.sync_external_refund_transaction_state(
                db, transaction=external, refund_state_label="finished", provider_payload_json={"ok": True}
            )
            self.assertEqual(finished.status, "SUCCEEDED")
            self.assertEqual(finished_event.event_type, "ROBOKASSA_REFUND_FINISHED")
            _, repeated_event = billing_manager.sync_external_refund_transaction_state(
                db, transaction=external, refund_state_label="finished"
            )
            self.assertIsNone(repeated_event)

            canceled, canceled_event = billing_manager.create_external_refund_transaction(
                db,
                venue_id=self.venue_id,
                target_payment_transaction=paid,
                amount_minor=10_000,
                request_id="refund-canceled",
                op_key="op-payment",
                created_by_user_id=self.owner.id,
            )
            canceled, canceled_state_event = billing_manager.sync_external_refund_transaction_state(
                db, transaction=canceled, refund_state_label="canceled"
            )
            self.assertEqual(canceled.status, "CANCELED")
            self.assertEqual(canceled_state_event.event_type, "ROBOKASSA_REFUND_CANCELED")
            self.assertEqual(canceled_event.event_type, "ROBOKASSA_REFUND_REQUESTED")

            failed, _ = billing_manager.create_external_refund_transaction(
                db,
                venue_id=self.venue_id,
                target_payment_transaction=paid,
                amount_minor=10_000,
                request_id="refund-failed",
                op_key="op-payment",
                created_by_user_id=self.owner.id,
            )
            failed, failed_event = billing_manager.sync_external_refund_transaction_state(
                db, transaction=failed, refund_state_label="provider_error"
            )
            self.assertEqual(failed.status, "FAILED")
            self.assertEqual(failed_event.event_type, "ROBOKASSA_REFUND_FAILED")

            old_pending = billing_manager.create_checkout_transaction(
                db,
                venue_id=self.venue_id,
                created_by_user_id=self.owner.id,
                amount_minor=299_000,
                replace_existing=True,
            )
            old_pending.provider_payload_json = {"checkout_expires_at": (now - timedelta(minutes=1)).isoformat()}
            expired_count, expired_events = billing_manager.expire_stale_pending_checkouts(db, now=now)
            self.assertGreaterEqual(expired_count, 1)
            self.assertTrue(expired_events)
            db.commit()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import (
    venue_adjustments,
    venue_catalogs,
    venue_finance_summary,
    venue_ledger,
    venue_membership,
    venue_pay_profiles,
    venue_payroll,
    venue_positions,
    venue_recurring_expenses,
    venue_reports,
    venue_schedule_templates,
    venue_shifts,
)
from app.schemas.venue_core import InviteCreateIn
from app.schemas.venue_payroll import PayrollCalculateIn


class VenueCatalogRouterTests(TestCase):
    def test_catalog_code_normalization_keeps_validation_contract(self):
        self.assertEqual(venue_catalogs._normalize_code(" Cash Less "), "cash_less")
        with self.assertRaises(HTTPException) as raised:
            venue_catalogs._normalize_code("касса")
        self.assertEqual(raised.exception.status_code, 400)


class VenueFinanceSummaryRouterTests(TestCase):
    def test_all_summary_routes_keep_guards_delegation_and_sanitizing(self):
        db = SimpleNamespace()
        user = SimpleNamespace(id=17)
        target_date = date(2026, 7, 18)

        with patch.object(venue_finance_summary, "_require_active_member_or_admin") as active, \
             patch.object(venue_finance_summary, "_require_revenue_viewer") as revenue, \
             patch.object(venue_finance_summary, "_require_report_viewer") as reports, \
             patch.object(venue_finance_summary, "get_monthly_finance_summary", return_value={"kind": "monthly"}), \
             patch.object(venue_finance_summary, "get_day_finance_summary", return_value={"kind": "daily"}), \
             patch.object(venue_finance_summary, "get_finance_summary", return_value={"kind": "finance"}), \
             patch.object(venue_finance_summary, "sanitize_financial_payload_for_user", side_effect=lambda current_user, payload: payload):
            monthly = venue_finance_summary.get_venue_monthly_finance_summary(
                5, "2026-07", None, None, "PAYMENTS", db, user
            )
            daily = venue_finance_summary.get_venue_day_finance_summary(
                5, target_date, "DEPARTMENTS", db, user
            )
            finance = venue_finance_summary.get_venue_finance_summary(
                5, "2026-07", None, None, db, user
            )

        self.assertEqual(monthly, {"kind": "monthly"})
        self.assertEqual(daily, {"kind": "daily"})
        self.assertEqual(finance, {"kind": "finance"})
        self.assertEqual(active.call_count, 3)
        self.assertEqual(revenue.call_count, 3)
        self.assertEqual(reports.call_count, 3)


class VenueLedgerRouterTests(TestCase):
    def test_ledger_serializers_preserve_minor_units_and_nested_catalogs(self):
        payment_method = SimpleNamespace(id=2, code="cash", title="Наличные")
        department = SimpleNamespace(id=3, code="bar", title="Бар")
        entry = SimpleNamespace(
            id=1,
            venue_id=5,
            entry_date=date(2026, 7, 18),
            amount_minor=12_345,
            direction="IN",
            kind="REVENUE",
            source_type="report",
            source_id=7,
            meta_json=None,
            created_at=None,
        )

        payload = venue_ledger._serialize_finance_entry(entry, payment_method, department)

        self.assertEqual(payload["amount_minor"], 12_345)
        self.assertEqual(payload["payment_method"]["code"], "cash")
        self.assertEqual(payload["department"]["title"], "Бар")


class VenueRecurringExpenseRouterTests(TestCase):
    def test_recurring_rule_serializer_preserves_payment_method_basis(self):
        category = SimpleNamespace(id=1, code="rent", title="Аренда")
        payment_method = SimpleNamespace(id=2, code="cash", title="Наличные")
        rule = SimpleNamespace(
            id=7,
            venue_id=5,
            title="Аренда",
            category_id=1,
            supplier_id=None,
            payment_method_id=2,
            is_active=True,
            start_date=date(2026, 1, 1),
            end_date=None,
            frequency="MONTHLY",
            day_of_month=1,
            generation_mode="FIXED",
            amount_minor=100_000,
            percent_bps=None,
            spread_months=1,
            description=None,
            created_by_user_id=17,
            created_at=None,
            updated_at=None,
        )

        payload = venue_recurring_expenses._serialize_recurring_expense_rule(
            rule,
            category,
            None,
            payment_method,
            [payment_method],
        )

        self.assertEqual(payload["amount_minor"], 100_000)
        self.assertEqual(payload["payment_method_ids"], [2])
        self.assertEqual(payload["category"]["code"], "rent")


class VenuePayrollRouterTests(TestCase):
    def test_calculate_route_keeps_guards_log_commit_and_sanitizing(self):
        class Db:
            commits = 0
            rollbacks = 0

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        db = Db()
        user = SimpleNamespace(id=17)
        payload = PayrollCalculateIn(month="2026-07")

        with patch.object(venue_payroll, "_require_active_member_or_admin"), \
             patch.object(venue_payroll, "_require_payroll_calculate"), \
             patch.object(venue_payroll, "calculate_payroll_for_month") as calculate, \
             patch.object(venue_payroll, "_create_payroll_recalculation_log") as create_log, \
             patch.object(venue_payroll, "_load_payroll_payload", return_value={"month": "2026-07"}), \
             patch.object(venue_payroll, "sanitize_financial_payload_for_user", side_effect=lambda current_user, result: result):
            result = venue_payroll.calculate_payroll(5, payload, db, user)

        self.assertEqual(result, {"month": "2026-07"})
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        calculate.assert_called_once_with(db=db, venue_id=5, month="2026-07", calculated_by_user_id=17)
        create_log.assert_called_once()


class VenueReportRouterTests(TestCase):
    def test_report_totals_keep_department_and_legacy_revenue_modes(self):
        values = [
            SimpleNamespace(kind="PAYMENT", value_numeric=800),
            SimpleNamespace(kind="DEPT", value_numeric=650),
        ]
        report = SimpleNamespace(revenue_total=700)

        department_totals = venue_reports._compute_report_totals(
            report=report,
            values=values,
            has_departments=True,
        )
        legacy_totals = venue_reports._compute_report_totals(
            report=report,
            values=values,
            has_departments=False,
        )

        self.assertEqual(department_totals["discrepancy"], 150)
        self.assertEqual(legacy_totals["discrepancy"], 100)


class VenuePeopleRouterTests(TestCase):
    def test_position_presets_and_pay_profile_detail_keep_delegation(self):
        db = SimpleNamespace()
        user = SimpleNamespace(id=17)

        with patch.object(venue_positions, "_require_active_member_or_admin"), \
             patch.object(venue_positions, "_is_owner_or_super_admin", return_value=True), \
             patch.object(venue_positions, "_load_position_presets_from_setup", return_value=[{"code": "bar"}]) as load_presets:
            presets = venue_positions.list_position_presets(5, False, db, user)

        with patch.object(venue_pay_profiles, "_require_active_member_or_admin"), \
             patch.object(venue_pay_profiles, "_require_pay_profiles_view"), \
             patch.object(venue_pay_profiles, "_load_pay_profile_detail", return_value={"id": 3}) as load_profile:
            profile = venue_pay_profiles.get_pay_profile(5, 3, db, user)

        self.assertEqual(presets, {"items": [{"code": "bar"}]})
        self.assertEqual(profile, {"id": 3})
        load_presets.assert_called_once_with(db, venue_id=5, include_inactive=False)
        load_profile.assert_called_once_with(db, venue_id=5, profile_id=3)

    def test_invite_route_rejects_unknown_role_before_database_work(self):
        payload = InviteCreateIn(tg_username="staff", venue_role="UNKNOWN")
        with patch.object(venue_membership, "_require_staff_manage_or_owner_or_super_admin"), \
             patch.object(venue_membership, "_is_owner_or_super_admin", return_value=True):
            with self.assertRaises(HTTPException) as raised:
                venue_membership.create_invite(5, payload, SimpleNamespace(), SimpleNamespace(id=17))
        self.assertEqual(raised.exception.status_code, 400)


class VenueAdjustmentAndScheduleRouterTests(TestCase):
    def test_adjustments_reject_mixed_period_filters(self):
        with patch.object(venue_adjustments, "_require_active_member_or_admin"), \
             patch.object(venue_adjustments, "_require_adjustments_viewer"):
            with self.assertRaises(HTTPException) as raised:
                venue_adjustments.list_adjustments(
                    5,
                    "2026-07",
                    date(2026, 7, 1),
                    date(2026, 7, 31),
                    0,
                    None,
                    SimpleNamespace(),
                    SimpleNamespace(id=17),
                )
        self.assertEqual(raised.exception.status_code, 400)

    def test_schedule_helpers_keep_month_bounds_slots_and_deep_link(self):
        start, end_exclusive, end = venue_schedule_templates._parse_shift_schedule_template_month("2026-07")
        path = venue_shifts._build_staff_shifts_deep_link_path(
            venue_id=5,
            view="month",
            period_start=start,
            interval_ids=[3, 4],
            staffing_state="unstaffed",
            shift_slot="NIGHT",
        )

        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 31))
        self.assertEqual(end_exclusive, date(2026, 8, 1))
        self.assertEqual(venue_schedule_templates._shift_slot_label("NIGHT"), "Ночь")
        self.assertIn("month=2026-07", path)
        self.assertIn("intervals=3%2C4", path)
        self.assertIn("unstaffed=1", path)

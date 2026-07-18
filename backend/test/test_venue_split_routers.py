from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import (
    venue_catalogs,
    venue_finance_summary,
    venue_ledger,
    venue_recurring_expenses,
)


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

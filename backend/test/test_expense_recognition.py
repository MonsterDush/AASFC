from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase

from app.services.finance.recognition import build_daily_spread_plan, build_expense_recognition_plan
from app.services.finance.recurring_expenses import _fixed_rule_daily_minor


class ExpenseRecognitionTests(TestCase):
    def test_build_daily_spread_plan_splits_with_remainder(self):
        plan = build_daily_spread_plan(
            amount_minor=100,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 3),
        )
        self.assertEqual(plan, [
            (date(2026, 3, 1), 34),
            (date(2026, 3, 2), 33),
            (date(2026, 3, 3), 33),
        ])

    def test_build_expense_recognition_plan_spreads_single_slot_month_by_days(self):
        expense = SimpleNamespace(
            expense_date=date(2026, 3, 15),
            shift_slot="TOTAL",
            spread_months=1,
            category_id=7,
            supplier_id=None,
            payment_method_id=2,
            recurring_rule_id=None,
        )
        allocation = SimpleNamespace(month=date(2026, 3, 1), amount_minor=3100, id=1)
        plan = build_expense_recognition_plan(expense=expense, allocations=[allocation])
        self.assertEqual(len(plan), 31)
        self.assertEqual(plan[0][0], date(2026, 3, 1))
        self.assertEqual(plan[-1][0], date(2026, 3, 31))
        self.assertEqual(sum(amount for _, amount, _ in plan), 3100)

    def test_common_expense_is_spread_across_all_62_month_slots(self):
        expense = SimpleNamespace(
            expense_date=date(2026, 7, 15),
            shift_slot="TOTAL",
            spread_months=1,
            category_id=7,
            supplier_id=None,
            payment_method_id=2,
            recurring_rule_id=None,
        )
        allocation = SimpleNamespace(month=date(2026, 7, 1), amount_minor=6201, id=1)

        plan = build_expense_recognition_plan(
            expense=expense,
            allocations=[allocation],
            available_shift_slots=["DAY", "NIGHT"],
        )

        self.assertEqual(len(plan), 62)
        self.assertEqual({meta["shift_slot"] for _, _, meta in plan}, {"DAY", "NIGHT"})
        self.assertEqual(sum(amount for _, amount, _ in plan), 6201)
        self.assertEqual(plan[0][2]["recognitions_in_period"], 62)

    def test_slot_specific_expense_is_not_split_into_other_slot(self):
        expense = SimpleNamespace(
            expense_date=date(2026, 7, 15),
            shift_slot="NIGHT",
            spread_months=1,
            category_id=7,
            supplier_id=None,
            payment_method_id=2,
            recurring_rule_id=None,
        )
        allocation = SimpleNamespace(month=date(2026, 7, 1), amount_minor=3100, id=1)

        plan = build_expense_recognition_plan(
            expense=expense,
            allocations=[allocation],
            available_shift_slots=["DAY", "NIGHT"],
        )

        self.assertEqual(len(plan), 31)
        self.assertEqual({meta["shift_slot"] for _, _, meta in plan}, {"NIGHT"})
        self.assertEqual(sum(amount for _, amount, _ in plan), 3100)

    def test_fixed_rule_daily_minor_spreads_across_active_days_only(self):
        rule = SimpleNamespace(
            amount_minor=3000,
            start_date=date(2026, 3, 11),
            end_date=date(2026, 3, 20),
        )
        self.assertEqual(_fixed_rule_daily_minor(rule=rule, target_date=date(2026, 3, 10)), 0)
        self.assertEqual(_fixed_rule_daily_minor(rule=rule, target_date=date(2026, 3, 11)), 300)
        self.assertEqual(_fixed_rule_daily_minor(rule=rule, target_date=date(2026, 3, 20)), 300)

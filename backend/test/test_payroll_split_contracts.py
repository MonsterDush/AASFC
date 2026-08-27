from __future__ import annotations

import ast
from datetime import date
import hashlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.models import PayrollLine, PayrollRun
from app.services.payroll import calculator
from app.services.payroll import component_calculations, metric_loaders, payroll_types, percent_calculations


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAYROLL_DIR = PROJECT_ROOT / "backend" / "app" / "services" / "payroll"


class PayrollCalculatorSplitContractTests(TestCase):
    classes = (
        "PayrollCalculationResult",
        "PayrollKpiBonusDecision",
        "PayrollKpiMetrics",
        "PayrollMemberMetrics",
        "PayrollPercentDecision",
        "PayrollRevenueMetrics",
        "PayrollVenuePlanMetrics",
        "PayrollWorkedShift",
    )
    constants = (
        "BASE_SCOPE_FULL_PERIOD",
        "BASE_SCOPE_TITLES",
        "BASE_SCOPE_WORKED_DATES",
        "BOOST_RECALC_EXCESS_ONLY",
        "BOOST_RECALC_REPLACE_ALL",
        "BOOST_RECALC_TITLES",
        "BOOST_SOURCE_DEPARTMENT_DAY_PLAN",
        "BOOST_SOURCE_DEPARTMENT_MONTH_PLAN",
        "BOOST_SOURCE_KPI_METRIC",
        "BOOST_SOURCE_NONE",
        "BOOST_SOURCE_TITLES",
        "BOOST_SOURCE_VENUE_DAY_PLAN",
        "BOOST_SOURCE_VENUE_MONTH_PLAN",
        "MINIMUM_GUARANTEE_DAY",
        "MINIMUM_GUARANTEE_MONTH",
        "MINIMUM_GUARANTEE_SHIFT",
        "PAY_COMPONENT_TYPES",
    )
    functions = (
        "_allocate_minor_by_keys",
        "_apply_daily_minimum_to_rows",
        "_assignment_overlaps_month",
        "_build_percent_component_decision",
        "_build_percent_component_snapshot",
        "_component_base_scope",
        "_component_boost_department_ids",
        "_component_boost_recalc_mode",
        "_component_boost_source_type",
        "_component_department_ids",
        "_component_shift_allocations",
        "_department_title_for",
        "_department_titles_for_ids",
        "_load_closed_report_dates",
        "_load_closed_report_slots_by_date",
        "_load_kpi_metrics",
        "_load_member_metrics",
        "_load_profile_components",
        "_load_revenue_metrics",
        "_load_venue_plan_metrics",
        "_minimum_guarantee_scope",
        "_minimum_payout_scope",
        "_minimum_payout_scope_title",
        "_minimum_payout_shift_top_up",
        "_minimum_payout_target_minor",
        "_month_dates",
        "_normalize_int_ids",
        "_ordered_worked_shifts",
        "_parse_steps_json",
        "_percent_decision_amounts_by_date",
        "_pick_latest_assignments",
        "_round_percent_amount",
        "_rub_to_minor",
        "_shift_ids",
        "_split_date_amounts_to_shifts",
        "_sum_department_day_target_minor",
        "_sum_department_month_target_minor",
        "_sum_department_revenue_by_date_minor",
        "_sum_department_revenue_for_worked_dates",
        "_sum_department_revenue_minor",
        "_sum_optional_targets",
        "calculate_component_amount_minor",
        "calculate_kpi_bonus",
        "calculate_payroll_for_month",
        "interval_duration_minutes",
        "next_month_start",
        "parse_month_start",
    )

    def test_facade_preserves_all_original_symbols_and_signatures(self):
        manifest = []
        for name in self.classes:
            value = getattr(calculator, name)
            manifest.append(("class", name, str(inspect.signature(value))))
        for name in self.constants:
            value = getattr(calculator, name)
            manifest.append(("constant", name, type(value).__name__))
        for name in self.functions:
            value = getattr(calculator, name)
            manifest.append(("function", name, str(inspect.signature(value))))

        manifest.sort()
        digest = hashlib.sha256(json.dumps(manifest, ensure_ascii=False).encode()).hexdigest()
        self.assertEqual(len(manifest), 72)
        self.assertEqual(digest, "cbacce87274d96fe2b55926983194eea035152d54bd57c89b470e6f8edd32583")

    def test_modules_remain_bounded_and_facade_reexports_their_contracts(self):
        modules = {
            "calculator.py": (220, "calculate_payroll_for_month"),
            "payroll_types.py": (100, "class PayrollPercentDecision"),
            "component_calculations.py": (375, "def calculate_component_amount_minor"),
            "percent_calculations.py": (175, "def _build_percent_component_decision"),
            "metric_loaders.py": (155, "def _load_member_metrics"),
        }
        for filename, (statement_limit, marker) in modules.items():
            source = (PAYROLL_DIR / filename).read_text(encoding="utf-8")
            statement_count = sum(isinstance(node, ast.stmt) for node in ast.walk(ast.parse(source)))
            self.assertLess(statement_count, statement_limit)
            self.assertIn(marker, source)

        self.assertIs(calculator.PayrollPercentDecision, payroll_types.PayrollPercentDecision)
        self.assertIs(
            calculator.calculate_component_amount_minor, component_calculations.calculate_component_amount_minor
        )
        self.assertIs(
            calculator._build_percent_component_decision, percent_calculations._build_percent_component_decision
        )
        self.assertIs(calculator._load_member_metrics, metric_loaders._load_member_metrics)


class PayrollExtractedHelperBehaviorTests(TestCase):
    def test_steps_json_normalizes_rubles_filters_invalid_rows_and_sorts(self):
        steps = calculator._parse_steps_json(
            '{"steps": ['
            '{"threshold_value": 20, "amount_rub": "250,50", "title": "silver"},'
            '{"threshold_value": -1, "amount_minor": 100},'
            '{"threshold_value": 10, "amount_minor": 10000}'
            "]}"
        )
        self.assertEqual(
            steps,
            [
                {"threshold_value": 10, "amount_minor": 10000},
                {"threshold_value": 20, "amount_minor": 25050, "title": "silver"},
            ],
        )

    def test_allocation_and_per_shift_minimum_keep_exact_minor_totals(self):
        allocation = calculator._allocate_minor_by_keys(101, [1, 2, 3], {1: 1, 2: 1, 3: 1})
        self.assertEqual(allocation, {1: 34, 2: 34, 3: 33})

        metrics = calculator.PayrollMemberMetrics(
            shifts_count=2,
            worked_shifts=[
                calculator.PayrollWorkedShift(shift_id=1, shift_date=date(2026, 3, 1), shift_slot="DAY", minutes=480),
                calculator.PayrollWorkedShift(shift_id=2, shift_date=date(2026, 3, 2), shift_slot="NIGHT", minutes=480),
            ],
        )
        total, rows = calculator._minimum_payout_shift_top_up(
            component=SimpleNamespace(amount_minor=50000),
            metrics=metrics,
            earnings_by_shift_minor={1: 30000, 2: 70000},
        )
        self.assertEqual(total, 20000)
        self.assertEqual([row["amount_minor"] for row in rows], [20000, 0])
        self.assertEqual([row["minimum_applied"] for row in rows], [True, False])

    def test_latest_overlapping_assignment_is_selected_per_member(self):
        user = SimpleNamespace(id=17)
        profile = SimpleNamespace(id=3, is_active=True)
        older = SimpleNamespace(
            id=1,
            member_user_id=17,
            is_active=True,
            start_date=date(2026, 2, 1),
            end_date=None,
        )
        newer = SimpleNamespace(
            id=2,
            member_user_id=17,
            is_active=True,
            start_date=date(2026, 3, 10),
            end_date=None,
        )

        selected = calculator._pick_latest_assignments(
            [(older, profile, user), (newer, profile, user)],
            month_start=date(2026, 3, 1),
            month_end_excl=date(2026, 4, 1),
        )
        self.assertEqual(len(selected), 1)
        self.assertIs(selected[0][0], newer)


class PayrollMonthOrchestratorTests(TestCase):
    class _Result:
        def __init__(self, *, scalar_one_or_none=None, rows=None):
            self._scalar_one_or_none = scalar_one_or_none
            self._rows = list(rows or [])

        def scalar_one_or_none(self):
            return self._scalar_one_or_none

        def all(self):
            return list(self._rows)

    class _Session:
        def __init__(self):
            self.results = [
                PayrollMonthOrchestratorTests._Result(scalar_one_or_none=None),
                PayrollMonthOrchestratorTests._Result(rows=[]),
                PayrollMonthOrchestratorTests._Result(scalar_one_or_none=None),
            ]
            self.added = []
            self.flush_count = 0

        def execute(self, _statement):
            return self.results.pop(0)

        def add(self, value):
            self.added.append(value)

        def flush(self):
            self.flush_count += 1
            for value in self.added:
                if isinstance(value, PayrollRun) and value.id is None:
                    value.id = 101
                if isinstance(value, PayrollLine) and value.id is None:
                    value.id = 202

    def test_month_calculation_keeps_run_line_and_finance_entry_flow(self):
        db = self._Session()
        assignment = SimpleNamespace(member_user_id=17)
        profile = SimpleNamespace(id=3, title="Основной")
        member = SimpleNamespace(id=17, short_name="Иван", full_name=None, tg_username=None)
        component = SimpleNamespace(
            id=5,
            component_type="SALARY_FIXED_MONTH",
            title="Оклад",
            amount_minor=150000,
            rate_minor=None,
            percent_bps=None,
            kpi_metric_id=None,
        )
        finance_entries = []
        context = SimpleNamespace(
            assignment=assignment,
            profile=profile,
            member_user=member,
            metrics=calculator.PayrollMemberMetrics(),
            position_ids=set(),
            position_titles=set(),
        )

        with (
            patch.object(calculator, "_pick_latest_assignments", return_value=[(assignment, profile, member)]),
            patch.object(calculator, "load_position_payroll_contexts", return_value=[context]),
            patch.object(calculator, "_load_profile_components", return_value={3: [component]}),
            patch.object(calculator, "_load_member_metrics", return_value={17: calculator.PayrollMemberMetrics()}),
            patch.object(calculator, "_load_revenue_metrics", return_value=calculator.PayrollRevenueMetrics()),
            patch.object(calculator, "_load_kpi_metrics", return_value=calculator.PayrollKpiMetrics()),
            patch.object(calculator, "_load_venue_plan_metrics", return_value=calculator.PayrollVenuePlanMetrics()),
            patch.object(
                calculator, "create_finance_entry", side_effect=lambda **kwargs: finance_entries.append(kwargs)
            ),
        ):
            result = calculator.calculate_payroll_for_month(
                db=db,
                venue_id=7,
                month="2026-03",
                calculated_by_user_id=99,
            )

        self.assertEqual(result.run.id, 101)
        self.assertEqual(result.run.total_amount_minor, 150000)
        self.assertEqual(result.run.lines_count, 1)
        self.assertEqual(len(result.lines), 1)
        self.assertEqual(result.lines[0].id, 202)
        self.assertEqual(result.lines[0].amount_minor, 150000)
        breakdown = json.loads(result.lines[0].breakdown_json)
        self.assertEqual(breakdown["components"][0]["component_type"], "SALARY_FIXED_MONTH")
        self.assertEqual(breakdown["components"][0]["amount_minor"], 150000)
        self.assertEqual(len(finance_entries), 1)
        self.assertEqual(finance_entries[0]["amount_minor"], 150000)
        self.assertEqual(finance_entries[0]["source_type"], "payroll_run")
        self.assertEqual(finance_entries[0]["source_id"], 101)
        self.assertGreaterEqual(db.flush_count, 3)

    def test_month_recalculation_records_percent_decision_and_minimum_top_up(self):
        db = self._Session()
        existing_run = PayrollRun(
            id=101,
            venue_id=7,
            period_month=date(2026, 3, 1),
            calculated_by_user_id=1,
            total_amount_minor=0,
            lines_count=0,
        )
        assignment = SimpleNamespace(member_user_id=17)
        profile = SimpleNamespace(id=3, title="Revenue profile")
        member = SimpleNamespace(id=17, short_name="Alex", full_name=None, tg_username=None)
        percent_component = SimpleNamespace(
            id=5,
            component_type="PERCENT_TOTAL_REVENUE",
            title="Revenue share",
            amount_minor=None,
            rate_minor=None,
            percent_bps=1_000,
            kpi_metric_id=None,
            department_id=None,
            department_ids_json=None,
            boost_department_id=None,
            boost_department=None,
            boost_kpi_metric=None,
        )
        minimum_component = SimpleNamespace(
            id=6,
            component_type="MINIMUM_PAYOUT",
            title="Monthly minimum",
            amount_minor=200_000,
        )
        worked_shift = calculator.PayrollWorkedShift(
            shift_id=11,
            shift_date=date(2026, 3, 2),
            shift_slot="DAY",
            minutes=480,
        )
        metrics = calculator.PayrollMemberMetrics(
            minutes_total=480,
            shifts_count=1,
            worked_dates={date(2026, 3, 2)},
            worked_shifts=[worked_shift],
        )
        decision = calculator.PayrollPercentDecision(
            amount_minor=100_000,
            base_amount_minor=1_000_000,
            base_scope=calculator.BASE_SCOPE_FULL_PERIOD,
            regular_percent_bps=1_000,
            applied_percent_bps=1_000,
            regular_amount_minor=100_000,
            boost_enabled=False,
            boost_applied=False,
            boost_source_type="NONE",
            boost_source_title="No boost",
            boost_recalc_mode="REPLACE_ALL",
            boost_recalc_mode_effective="REPLACE_ALL",
            boost_recalc_mode_title="Replace all",
            minimum_guarantee_minor=80_000,
            minimum_guarantee_scope=calculator.MINIMUM_GUARANTEE_MONTH,
            day_rows=[{"date": "2026-03-02", "amount_minor": 100_000}],
        )
        db.results = [
            self._Result(scalar_one_or_none=existing_run),
            self._Result(),
            self._Result(rows=[(assignment, profile, member)]),
            self._Result(scalar_one_or_none=1),
        ]
        context = SimpleNamespace(
            assignment=assignment,
            profile=profile,
            member_user=member,
            metrics=metrics,
            position_ids={9},
            position_titles={"Administrator"},
        )

        with (
            patch.object(calculator, "delete_finance_entries_for_source"),
            patch.object(calculator, "_pick_latest_assignments", return_value=[(assignment, profile, member)]),
            patch.object(calculator, "load_position_payroll_contexts", return_value=[context]),
            patch.object(
                calculator,
                "_load_profile_components",
                return_value={3: [percent_component, minimum_component]},
            ),
            patch.object(calculator, "_load_member_metrics", return_value={17: metrics}),
            patch.object(
                calculator,
                "_load_revenue_metrics",
                return_value=calculator.PayrollRevenueMetrics(total_revenue_minor=1_000_000),
            ),
            patch.object(calculator, "_load_kpi_metrics", return_value=calculator.PayrollKpiMetrics()),
            patch.object(calculator, "_load_venue_plan_metrics", return_value=calculator.PayrollVenuePlanMetrics()),
            patch.object(calculator, "_build_percent_component_decision", return_value=decision),
            patch.object(calculator, "_build_percent_component_snapshot", return_value={"auditable": True}),
            patch.object(calculator, "_component_shift_allocations", return_value={11: 50_000}),
            patch.object(calculator, "_minimum_payout_scope", return_value=calculator.MINIMUM_GUARANTEE_MONTH),
            patch.object(calculator, "_minimum_payout_target_minor", return_value=200_000),
        ):
            result = calculator.calculate_payroll_for_month(
                db=db,
                venue_id=7,
                month="2026-03",
                calculated_by_user_id=99,
            )

        self.assertEqual(result.run.total_amount_minor, 200_000)
        self.assertEqual(result.run.calculated_by_user_id, 99)
        breakdown = json.loads(result.lines[0].breakdown_json)
        percent_row, minimum_row = breakdown["components"]
        self.assertEqual(percent_row["base_amount_minor"], 1_000_000)
        self.assertEqual(percent_row["calculation_snapshot"], {"auditable": True})
        self.assertEqual(minimum_row["amount_minor"], 100_000)
        self.assertTrue(minimum_row["minimum_applied"])
        self.assertEqual(breakdown["shift_allocations"][0]["amount_minor"], 200_000)

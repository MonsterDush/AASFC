from __future__ import annotations

import inspect
from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi import HTTPException
from sqlalchemy import CheckConstraint

from app.models.daily_report import DailyReport
from app.models.daily_report_attachment import DailyReportAttachment
from app.models.shift import Shift
from app.models.shift_schedule_template import ShiftScheduleTemplateItem
from app.routers import (
    venue_core,
    venue_payroll_support,
    venue_reports,
    venue_schedule_templates,
    venue_shifts,
)
from app.schemas.finance import DailyFinanceSummaryOut
from app.schemas.venue_core import VenueSettingsPatchIn
from app.schemas.venue_economics import DayEconomicsOut, DayEconomicsReportOut
from app.schemas.venue_shifts import ShiftUpdateIn
from app.schemas.venue_shifts import ShiftScheduleTemplateUpdateIn
from app.services.finance import day_economics
from app.services.payroll import period_summary


class NightShiftPayrollRegressionTests(TestCase):
    def test_closed_report_probe_is_limited_to_one_row(self):
        db = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = 42

        result = venue_payroll_support._has_closed_report_for_date(
            db,
            venue_id=5,
            target_date=date(2026, 7, 29),
        )

        statement = db.execute.call_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertTrue(result)
        self.assertIn("LIMIT 1", compiled)

    def test_member_period_candidates_match_closed_report_slot(self):
        db = Mock()
        db.execute.return_value.all.return_value = []

        period_summary._collect_member_candidate_dates(
            db,
            member_user_id=17,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            venue_id=5,
        )

        shift_statement = db.execute.call_args_list[0].args[0]
        compiled = str(shift_statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("daily_reports.shift_slot = shifts.shift_slot", compiled)

    def test_owner_period_candidates_match_closed_report_slot(self):
        db = Mock()
        db.execute.return_value.all.return_value = []

        venue_payroll_support._collect_venue_payroll_candidate_dates(
            db,
            venue_id=5,
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
        )

        shift_statement = db.execute.call_args_list[0].args[0]
        compiled = str(shift_statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("daily_reports.shift_slot = shifts.shift_slot", compiled)


class NightShiftRecurringExpenseRegressionTests(TestCase):
    def test_reopen_resyncs_accruals_when_other_slot_is_still_closed(self):
        db = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = 99
        report = SimpleNamespace(
            id=12,
            venue_id=5,
            date=date(2026, 7, 29),
        )

        with (
            patch.object(venue_reports, "sync_daily_recurring_accruals_for_date") as sync,
            patch.object(venue_reports, "delete_daily_recurring_accruals_for_date") as delete,
        ):
            result = venue_reports._sync_recurring_accruals_after_report_reopen(
                db,
                report=report,
            )

        self.assertEqual(result, "synced")
        sync.assert_called_once_with(
            db=db,
            venue_id=5,
            target_date=date(2026, 7, 29),
        )
        delete.assert_not_called()

    def test_reopen_deletes_accruals_when_no_closed_slot_remains(self):
        db = Mock()
        db.execute.return_value.scalar_one_or_none.return_value = None
        report = SimpleNamespace(
            id=12,
            venue_id=5,
            date=date(2026, 7, 29),
        )

        with (
            patch.object(venue_reports, "sync_daily_recurring_accruals_for_date") as sync,
            patch.object(venue_reports, "delete_daily_recurring_accruals_for_date") as delete,
        ):
            result = venue_reports._sync_recurring_accruals_after_report_reopen(
                db,
                report=report,
            )

        self.assertEqual(result, "deleted")
        sync.assert_not_called()
        delete.assert_called_once_with(
            db=db,
            venue_id=5,
            target_date=date(2026, 7, 29),
        )


class NightShiftEconomicsRegressionTests(TestCase):
    def test_response_models_preserve_slot_metadata(self):
        self.assertIn("shift_slot", DayEconomicsOut.model_fields)
        self.assertIn("shift_slot", DayEconomicsReportOut.model_fields)
        self.assertIn("shift_slot", DailyFinanceSummaryOut.model_fields)
        self.assertIn("slot_costs_available", DailyFinanceSummaryOut.model_fields)
        self.assertIn("slot_profit_available", DailyFinanceSummaryOut.model_fields)

    def test_slot_metrics_and_plan_comparison_do_not_publish_fake_profit(self):
        summary = {
            "revenue_minor": 100000,
            "profit_minor": 0,
            "expense_minor": 0,
            "point_expense_minor": 0,
            "recurring_expense_minor": 0,
            "payroll_minor": 0,
            "slot_profit_available": False,
        }
        report = {"tips_total_minor": 0}
        team = {
            "assigned_user_count": 2,
            "total_shift_count": 1,
            "assigned_shift_count": 1,
            "assignment_count": 2,
        }

        metrics = day_economics._build_metrics(
            summary=summary,
            report=report,
            team=team,
            department_share_breakdown=[],
            kpi_breakdown=[],
        )
        plan_fact = day_economics._build_plan_fact(
            summary=summary,
            metrics=metrics,
            team=team,
            plan={
                "revenue_plan_minor": 200000,
                "profit_plan_minor": 50000,
                "revenue_per_assigned_plan_minor": 100000,
                "assigned_user_target": 3,
            },
            comparison_available=False,
        )

        self.assertEqual(metrics["result_status"], "UNAVAILABLE")
        self.assertIsNone(metrics["profit_per_assigned_minor"])
        self.assertIsNone(metrics["expense_ratio_bps"])
        self.assertFalse(plan_fact["comparison_available"])
        self.assertIsNone(plan_fact["revenue_delta_minor"])
        self.assertIsNone(plan_fact["profit_delta_minor"])

    def test_slot_alerts_apply_financial_rules_after_cost_allocation(self):
        alerts = day_economics._build_alerts(
            report={"status": "CLOSED"},
            summary={
                "slot_costs_available": True,
                "slot_profit_available": True,
                "profit_minor": -100000,
                "draft_expense_count": 0,
            },
            metrics={
                "expense_ratio_bps": 9000,
                "payroll_ratio_bps": 9000,
                "revenue_per_assigned_minor": 1,
                "assigned_shift_coverage_bps": 10000,
            },
            plan_fact={
                "revenue_delta_minor": -100000,
                "profit_delta_minor": -100000,
            },
            rules={
                "max_expense_ratio_bps": 100,
                "max_payroll_ratio_bps": 100,
                "min_revenue_per_assigned_minor": 100000,
                "min_assigned_shift_coverage_bps": 9000,
                "min_profit_minor": 100000,
            },
            shift_slot="NIGHT",
        )

        self.assertEqual(
            [item["code"] for item in alerts],
            [
                "LOSS_DAY",
                "EXPENSE_RATIO_HIGH",
                "PAYROLL_RATIO_HIGH",
                "REVENUE_PER_ASSIGNED_LOW",
                "PROFIT_BELOW_TARGET",
                "REVENUE_PLAN_MISSED",
                "PROFIT_PLAN_MISSED",
            ],
        )


class NightShiftTipAllocationRegressionTests(TestCase):
    def test_rebuild_helper_targets_only_requested_report_slot(self):
        venue = SimpleNamespace(id=5)
        report_date = date(2026, 7, 29)
        day_report = SimpleNamespace(id=10, date=report_date, shift_slot="DAY")
        night_report = SimpleNamespace(id=11, date=report_date, shift_slot="NIGHT")

        venue_result = Mock()
        venue_result.scalar_one_or_none.return_value = venue
        report_result = Mock()
        report_result.scalars.return_value.all.return_value = [day_report, night_report]
        db = Mock()
        db.execute.side_effect = [venue_result, report_result]

        with patch.object(venue_reports, "_rebuild_report_tip_allocations") as rebuild:
            rebuilt_count = venue_reports._rebuild_closed_report_tip_allocations_for_keys(
                db,
                venue_id=5,
                report_keys={(report_date, "NIGHT")},
            )

        self.assertEqual(rebuilt_count, 1)
        rebuild.assert_called_once_with(db, report=night_report, venue=venue)

    def test_shift_slot_change_rebuilds_old_and_new_report_allocations(self):
        shift = SimpleNamespace(
            id=10,
            venue_id=5,
            date=date(2026, 7, 29),
            interval_id=3,
            shift_slot="DAY",
            is_active=True,
        )
        shift_result = Mock()
        shift_result.scalar_one_or_none.return_value = shift
        db = Mock()
        db.execute.side_effect = [shift_result, Mock()]
        user = SimpleNamespace(id=17)

        with (
            patch.object(venue_shifts, "_require_schedule_editor"),
            patch.object(venue_shifts, "_normalize_shift_slot_for_venue", return_value="NIGHT"),
            patch.object(venue_shifts, "_rebuild_closed_report_tip_allocations_for_keys") as rebuild,
            patch.object(venue_shifts, "_recalculate_payroll_for_dates"),
        ):
            result = venue_shifts.update_shift(
                venue_id=5,
                shift_id=10,
                payload=ShiftUpdateIn(shift_slot="NIGHT"),
                db=db,
                user=user,
            )

        self.assertTrue(result["ok"])
        rebuild.assert_called_once_with(
            db,
            venue_id=5,
            report_keys={
                (date(2026, 7, 29), "DAY"),
                (date(2026, 7, 29), "NIGHT"),
            },
        )
        db.commit.assert_called_once()

    def test_template_apply_rebuilds_tips_before_payroll(self):
        source = inspect.getsource(venue_schedule_templates.apply_shift_schedule_template)
        self.assertLess(
            source.index("_rebuild_closed_report_tip_allocations_for_keys"),
            source.index("_recalculate_payroll_for_dates"),
        )


class NightShiftDisableRegressionTests(TestCase):
    def test_disabling_is_blocked_while_night_data_exists(self):
        venue = SimpleNamespace(
            id=5,
            tips_enabled=True,
            night_shifts_enabled=True,
            tips_split_mode="EQUAL",
            tips_weights=None,
        )
        venue_result = Mock()
        venue_result.scalar_one_or_none.return_value = venue
        db = Mock()
        db.execute.return_value = venue_result
        user = SimpleNamespace(id=17)

        with (
            patch.object(venue_core, "_require_active_member_or_admin"),
            patch.object(venue_core, "_is_owner_or_super_admin", return_value=True),
            patch.object(
                venue_core,
                "_night_shift_disable_blockers",
                return_value={
                    "active_shifts": 2,
                    "reports": 1,
                    "template_items": 3,
                },
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                venue_core.patch_venue_settings(
                    venue_id=5,
                    payload=VenueSettingsPatchIn(night_shifts_enabled=False),
                    db=db,
                    user=user,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("активных ночных смен", str(raised.exception.detail))
        self.assertTrue(venue.night_shifts_enabled)
        db.commit.assert_not_called()

    def test_disabling_succeeds_when_no_night_data_remains(self):
        venue = SimpleNamespace(
            id=5,
            tips_enabled=True,
            night_shifts_enabled=True,
            tips_split_mode="EQUAL",
            tips_weights=None,
        )
        venue_result = Mock()
        venue_result.scalar_one_or_none.return_value = venue
        db = Mock()
        db.execute.return_value = venue_result
        user = SimpleNamespace(id=17)

        with (
            patch.object(venue_core, "_require_active_member_or_admin"),
            patch.object(venue_core, "_is_owner_or_super_admin", return_value=True),
            patch.object(
                venue_core,
                "_night_shift_disable_blockers",
                return_value={
                    "active_shifts": 0,
                    "reports": 0,
                    "template_items": 0,
                },
            ),
        ):
            result = venue_core.patch_venue_settings(
                venue_id=5,
                payload=VenueSettingsPatchIn(night_shifts_enabled=False),
                db=db,
                user=user,
            )

        self.assertFalse(result.night_shifts_enabled)
        self.assertFalse(venue.night_shifts_enabled)
        db.commit.assert_called_once()

    def test_legacy_night_template_cannot_be_silently_overwritten(self):
        template = SimpleNamespace(
            id=10,
            title="Смешанный шаблон",
            description=None,
            is_active=True,
        )
        night_item_result = Mock()
        night_item_result.scalar_one_or_none.return_value = 55
        db = Mock()
        db.execute.return_value = night_item_result
        user = SimpleNamespace(id=17)

        with (
            patch.object(venue_schedule_templates, "_require_schedule_editor"),
            patch.object(
                venue_schedule_templates,
                "_get_shift_schedule_template_or_404",
                return_value=template,
            ),
            patch.object(
                venue_schedule_templates,
                "_venue_night_shifts_enabled",
                return_value=False,
            ),
        ):
            with self.assertRaises(HTTPException) as raised:
                venue_schedule_templates.update_shift_schedule_template(
                    venue_id=5,
                    template_id=10,
                    payload=ShiftScheduleTemplateUpdateIn(items=[]),
                    db=db,
                    user=user,
                )

        self.assertEqual(raised.exception.status_code, 409)
        self.assertIn("ночные интервалы", str(raised.exception.detail))
        db.commit.assert_not_called()

    def test_inactive_night_shift_cannot_be_reactivated_while_mode_is_disabled(self):
        shift = SimpleNamespace(
            id=10,
            venue_id=5,
            date=date(2026, 7, 29),
            interval_id=3,
            shift_slot="NIGHT",
            is_active=False,
        )
        shift_result = Mock()
        shift_result.scalar_one_or_none.return_value = shift
        db = Mock()
        db.execute.return_value = shift_result
        user = SimpleNamespace(id=17)

        with (
            patch.object(venue_shifts, "_require_schedule_editor"),
            patch.object(
                venue_shifts,
                "_normalize_shift_slot_for_venue",
                side_effect=HTTPException(
                    status_code=400,
                    detail="Night shifts are disabled for this venue",
                ),
            ) as normalize_for_venue,
        ):
            with self.assertRaises(HTTPException) as raised:
                venue_shifts.update_shift(
                    venue_id=5,
                    shift_id=10,
                    payload=ShiftUpdateIn(is_active=True),
                    db=db,
                    user=user,
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertFalse(shift.is_active)
        normalize_for_venue.assert_called_once_with(
            db,
            venue_id=5,
            shift_slot="NIGHT",
        )
        db.commit.assert_not_called()


class NightShiftDatabaseConstraintTests(TestCase):
    def test_all_persisted_shift_slots_have_check_constraints(self):
        expected = {
            Shift: "ck_shifts_shift_slot_valid",
            DailyReport: "ck_daily_reports_shift_slot_valid",
            DailyReportAttachment: "ck_daily_report_attachments_shift_slot_valid",
            ShiftScheduleTemplateItem: "ck_shift_schedule_template_items_shift_slot_valid",
        }

        for model, constraint_name in expected.items():
            with self.subTest(model=model.__name__):
                check_names = {
                    constraint.name
                    for constraint in model.__table__.constraints
                    if isinstance(constraint, CheckConstraint)
                }
                self.assertIn(constraint_name, check_names)

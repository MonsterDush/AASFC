from __future__ import annotations

from unittest import TestCase

from app.services import setup


class SetupSummaryTests(TestCase):
    def test_prepare_progress_uses_explicit_completion_and_skips(self):
        state = {
            "wizard_version": 1,
            "completed_steps_json": [
                setup.STEP_PAYMENT_METHODS,
                setup.STEP_DEPARTMENTS,
                setup.STEP_PAY_PROFILES,
                setup.STEP_POSITIONS,
                setup.STEP_SHIFT_INTERVALS,
            ],
            "skipped_steps_json": [setup.STEP_KPI, setup.STEP_INVITES],
            "phase": setup.SETUP_PHASE_PREPARE,
            "current_step_key": setup.STEP_SHIFT_INTERVALS,
        }
        counts = {
            "payment_methods_count": 3,
            "departments_count": 2,
            "kpi_count": 0,
            "pay_profiles_count": 1,
            "positions_count": 2,
            "team_targets_count": 0,
            "shift_intervals_count": 1,
            "expense_categories_count": 0,
            "suppliers_count": 0,
            "recurring_expenses_count": 0,
        }

        summary = setup.build_setup_summary_from_data(state=state, counts=counts)

        self.assertTrue(summary["prepare_done"])
        self.assertEqual(summary["status"], setup.SETUP_STATUS_PREPARE_DONE)
        self.assertEqual(summary["phase"], setup.SETUP_PHASE_EXTRA)
        self.assertEqual(summary["resume_step"], setup.STEP_EXPENSE_CATEGORIES)
        self.assertEqual(summary["progress_done"], 5)
        self.assertEqual(summary["progress_resolved"], 7)

    def test_completed_step_without_required_data_needs_attention(self):
        state = {
            "completed_steps_json": [setup.STEP_PAYMENT_METHODS],
            "skipped_steps_json": [],
            "phase": setup.SETUP_PHASE_PREPARE,
        }
        counts = {
            "payment_methods_count": 0,
        }

        summary = setup.build_setup_summary_from_data(state=state, counts=counts)
        step = next(item for item in summary["steps"] if item["key"] == setup.STEP_PAYMENT_METHODS)

        self.assertEqual(step["status"], setup.STEP_STATUS_REQUIRES_ATTENTION)
        self.assertEqual(summary["status"], setup.SETUP_STATUS_IN_PROGRESS)

    def test_done_status_requires_resolved_extra_steps(self):
        state = {
            "completed_steps_json": [
                setup.STEP_PAYMENT_METHODS,
                setup.STEP_DEPARTMENTS,
                setup.STEP_PAY_PROFILES,
                setup.STEP_POSITIONS,
                setup.STEP_SHIFT_INTERVALS,
                setup.STEP_EXPENSE_CATEGORIES,
            ],
            "skipped_steps_json": [
                setup.STEP_KPI,
                setup.STEP_INVITES,
                setup.STEP_SUPPLIERS,
                setup.STEP_RECURRING_EXPENSES,
            ],
            "phase": setup.SETUP_PHASE_EXTRA,
        }
        counts = {
            "payment_methods_count": 1,
            "departments_count": 1,
            "pay_profiles_count": 1,
            "positions_count": 1,
            "shift_intervals_count": 1,
            "expense_categories_count": 1,
        }

        summary = setup.build_setup_summary_from_data(state=state, counts=counts)

        self.assertEqual(summary["status"], setup.SETUP_STATUS_DONE)
        self.assertTrue(summary["prepare_done"])
        self.assertTrue(summary["extra_done"])
        self.assertIsNone(summary["resume_step"])

    def test_legacy_welcome_state_resumes_at_payment_methods(self):
        state = {
            "completed_steps_json": ["welcome"],
            "skipped_steps_json": [],
            "phase": setup.SETUP_PHASE_PREPARE,
            "current_step_key": "welcome",
        }

        summary = setup.build_setup_summary_from_data(state=state, counts={})

        self.assertNotIn("welcome", [item["key"] for item in summary["steps"]])
        self.assertEqual(summary["resume_step"], setup.STEP_PAYMENT_METHODS)
        self.assertEqual(summary["prepare_total"], 7)

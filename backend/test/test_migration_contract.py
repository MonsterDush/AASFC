from __future__ import annotations

import unittest
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_DIR = Path(__file__).resolve().parents[1]


class MigrationContractTests(unittest.TestCase):
    def test_user_locale_is_the_single_current_head(self):
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        scripts = ScriptDirectory.from_config(config)

        heads = scripts.get_heads()
        revision = scripts.get_revision("b7d9e1f3a5c8")

        self.assertEqual(heads, ["b7d9e1f3a5c8"])
        self.assertIsNotNone(revision)
        self.assertEqual(revision.down_revision, "a4d8e2f6c1b3")

    def test_daily_reports_waits_for_venue_positions_table(self):
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        scripts = ScriptDirectory.from_config(config)

        revision = scripts.get_revision("1b2c3d4e5f6a")

        self.assertIsNotNone(revision)
        dependencies = revision.dependencies
        if isinstance(dependencies, str):
            dependencies = (dependencies,)
        self.assertIn("2b7d9c1a8c61", tuple(dependencies or ()))

    def test_shift_comment_mentions_and_replies_extend_current_head(self):
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        scripts = ScriptDirectory.from_config(config)

        revision = scripts.get_revision("4a7c9e2b6d10")

        self.assertIsNotNone(revision)
        self.assertEqual(revision.down_revision, "f1a2b3c4d5e7")
        source = (
            BACKEND_DIR / "alembic" / "versions" / "4a7c9e2b6d10_add_shift_comment_mentions_and_replies.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"parent_comment_id"', source)
        self.assertIn('"shift_comment_mentions"', source)
        self.assertIn('"uq_shift_comment_mention_user"', source)

    def test_shift_availability_and_swaps_extend_current_head(self):
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        scripts = ScriptDirectory.from_config(config)

        revision = scripts.get_revision("7d0f2b6c8e33")

        self.assertIsNotNone(revision)
        self.assertEqual(revision.down_revision, "6c9e1a4b7d22")
        source = (BACKEND_DIR / "alembic" / "versions" / "7d0f2b6c8e33_add_shift_availability_and_swaps.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"shift_availabilities"', source)
        self.assertIn('"shift_swap_requests"', source)
        self.assertIn('"uq_shift_availability_member_date_slot"', source)
        self.assertIn('"uq_shift_swap_requests_open_assignment"', source)
        self.assertIn('ondelete="SET NULL"', source)

    def test_kpi_percentage_and_salary_accrual_extend_current_head(self):
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        scripts = ScriptDirectory.from_config(config)

        revision = scripts.get_revision("8b4d1e7a9c20")

        self.assertIsNotNone(revision)
        self.assertEqual(revision.down_revision, "7d0f2b6c8e33")
        source = (
            BACKEND_DIR / "alembic" / "versions" / "8b4d1e7a9c20_extend_kpi_bonus_and_salary_accrual.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"kpi_calculation_mode"', source)
        self.assertIn('"salary_accrual_day"', source)

    def test_payroll_payment_schedule_extends_current_head(self):
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        scripts = ScriptDirectory.from_config(config)

        revision = scripts.get_revision("9c2e4f6a8b10")

        self.assertIsNotNone(revision)
        self.assertEqual(revision.down_revision, "8b4d1e7a9c20")
        source = (BACKEND_DIR / "alembic" / "versions" / "9c2e4f6a8b10_payroll_payment_schedule.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"payroll_payment_settings"', source)
        self.assertIn('"expense_kind"', source)
        self.assertIn('"payroll_payout_key"', source)


if __name__ == "__main__":
    unittest.main()

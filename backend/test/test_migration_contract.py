from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app.core.config import settings


BACKEND_DIR = Path(__file__).resolve().parents[1]


class MigrationContractTests(unittest.TestCase):
    def _config(self) -> Config:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        return config

    def test_multi_positions_owner_notes_is_the_single_current_head(self):
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        scripts = ScriptDirectory.from_config(config)

        heads = scripts.get_heads()
        revision = scripts.get_revision("d4a9f6c2b8e1")

        self.assertEqual(heads, ["d4a9f6c2b8e1"])
        self.assertIsNotNone(revision)
        self.assertEqual(revision.down_revision, "c8e1f4a7b2d9")

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

    def test_multi_positions_migration_round_trips_on_sqlite_fixture(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)
            with engine.begin() as connection:
                for statement in (
                    "CREATE TABLE users (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE venues (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE pay_profiles (id INTEGER PRIMARY KEY, venue_id INTEGER NOT NULL)",
                    "CREATE TABLE venue_members (id INTEGER PRIMARY KEY, venue_id INTEGER NOT NULL, user_id INTEGER NOT NULL, venue_role VARCHAR(16) NOT NULL, is_active BOOLEAN NOT NULL)",
                    "CREATE TABLE venue_invites (id INTEGER PRIMARY KEY, venue_id INTEGER NOT NULL, accepted_user_id INTEGER, invited_contact_label VARCHAR(500), accepted_at DATETIME)",
                    "CREATE TABLE pay_profile_assignments (id INTEGER PRIMARY KEY, venue_id INTEGER NOT NULL, member_user_id INTEGER NOT NULL, pay_profile_id INTEGER NOT NULL, is_active BOOLEAN NOT NULL, created_at DATETIME, updated_at DATETIME)",
                    "CREATE TABLE venue_positions (id INTEGER PRIMARY KEY, venue_id INTEGER NOT NULL, member_user_id INTEGER NOT NULL, title VARCHAR(100) NOT NULL, rate INTEGER NOT NULL, percent INTEGER NOT NULL, permission_codes TEXT, is_active BOOLEAN NOT NULL, CONSTRAINT uq_venue_position_member UNIQUE (venue_id, member_user_id), FOREIGN KEY(venue_id) REFERENCES venues(id), FOREIGN KEY(member_user_id) REFERENCES users(id))",
                    "CREATE INDEX ix_venue_positions_venue_id ON venue_positions (venue_id)",
                    "CREATE INDEX ix_venue_positions_member_user_id ON venue_positions (member_user_id)",
                    "CREATE TABLE shift_assignments (id INTEGER PRIMARY KEY, venue_position_id INTEGER NOT NULL)",
                    "CREATE TABLE shift_swap_requests (id INTEGER PRIMARY KEY, replacement_position_id INTEGER)",
                    "INSERT INTO users (id) VALUES (2)",
                    "INSERT INTO venues (id) VALUES (5)",
                    "INSERT INTO pay_profiles (id, venue_id) VALUES (21, 5)",
                    "INSERT INTO venue_members (id, venue_id, user_id, venue_role, is_active) VALUES (1, 5, 2, 'STAFF', 1)",
                    "INSERT INTO venue_invites (id, venue_id, accepted_user_id, invited_contact_label, accepted_at) VALUES (1, 5, 2, 'Бармен из филиала', '2026-08-01')",
                    "INSERT INTO pay_profile_assignments (id, venue_id, member_user_id, pay_profile_id, is_active, created_at, updated_at) VALUES (1, 5, 2, 21, 1, '2026-08-01', '2026-08-01')",
                    "INSERT INTO venue_positions (id, venue_id, member_user_id, title, rate, percent, permission_codes, is_active) VALUES (11, 5, 2, 'Бармен', 0, 0, '[]', 1)",
                ):
                    connection.exec_driver_sql(statement)

            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "c8e1f4a7b2d9")
                command.upgrade(config, "d4a9f6c2b8e1")

                inspector = sa.inspect(engine)
                self.assertIn("owner_note", {column["name"] for column in inspector.get_columns("venue_members")})
                position_columns = {column["name"]: column for column in inspector.get_columns("venue_positions")}
                self.assertIn("pay_profile_id", position_columns)
                self.assertTrue(position_columns["member_user_id"]["nullable"])

                with engine.begin() as connection:
                    owner_note = connection.execute(
                        sa.text("SELECT owner_note FROM venue_members WHERE venue_id = 5 AND user_id = 2")
                    ).scalar_one()
                    pay_profile_id = connection.execute(
                        sa.text("SELECT pay_profile_id FROM venue_positions WHERE id = 11")
                    ).scalar_one()
                    self.assertEqual(owner_note, "Бармен из филиала")
                    self.assertEqual(pay_profile_id, 21)
                    connection.execute(
                        sa.text(
                            "INSERT INTO venue_positions (id, venue_id, member_user_id, pay_profile_id, title, rate, percent, permission_codes, is_active) VALUES (12, 5, 2, 21, 'Официант', 0, 0, '[]', 1), (13, 5, NULL, NULL, 'Хостес', 0, 0, '[]', 1)"
                        )
                    )

                command.downgrade(config, "c8e1f4a7b2d9")

            inspector = sa.inspect(engine)
            self.assertNotIn("owner_note", {column["name"] for column in inspector.get_columns("venue_members")})
            position_columns = {column["name"]: column for column in inspector.get_columns("venue_positions")}
            self.assertNotIn("pay_profile_id", position_columns)
            self.assertFalse(position_columns["member_user_id"]["nullable"])
            self.assertIn(
                {"venue_id", "member_user_id"},
                [{*constraint["column_names"]} for constraint in inspector.get_unique_constraints("venue_positions")],
            )


if __name__ == "__main__":
    unittest.main()

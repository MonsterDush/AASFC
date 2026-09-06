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

    def test_quickresto_multi_venue_scope_extends_the_single_current_head(self):
        config = self._config()
        scripts = ScriptDirectory.from_config(config)

        heads = scripts.get_heads()
        revision = scripts.get_revision("c9e7a5b3d1f0")
        hardening = scripts.get_revision("d0f8b6c4e2a1")
        reconciliation = scripts.get_revision("e2b4d6f8a1c3")
        pending_scope = scripts.get_revision("f4c6e8a0b2d5")
        preview_move = scripts.get_revision("a7d3e5f1c9b2")
        interval_positions = scripts.get_revision("f6b4d2a8c1e0")
        catalog_backfill = scripts.get_revision("b9d2e4f6a8c1")

        self.assertEqual(heads, ["c2f4a6b8d0e1"])
        self.assertEqual(scripts.get_revision("c2f4a6b8d0e1").down_revision, "b9d2e4f6a8c1")

        self.assertIsNotNone(revision)
        self.assertEqual(revision.down_revision, "b8d4f6a2c1e9")

        self.assertIsNotNone(hardening)
        self.assertEqual(hardening.down_revision, "c9e7a5b3d1f0")

        self.assertIsNotNone(reconciliation)
        self.assertEqual(reconciliation.down_revision, "d0f8b6c4e2a1")

        self.assertIsNotNone(pending_scope)
        self.assertEqual(pending_scope.down_revision, "e2b4d6f8a1c3")

        self.assertIsNotNone(preview_move)
        self.assertEqual(preview_move.down_revision, "f4c6e8a0b2d5")

        self.assertIsNotNone(interval_positions)
        self.assertEqual(interval_positions.down_revision, "a7d3e5f1c9b2")

        self.assertIsNotNone(catalog_backfill)
        self.assertEqual(catalog_backfill.down_revision, "f6b4d2a8c1e0")

    def test_quickresto_pending_scope_migration_round_trips_on_sqlite_fixture(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("CREATE TABLE quickresto_connections (id INTEGER PRIMARY KEY)")

            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "e2b4d6f8a1c3")
                command.upgrade(config, "f4c6e8a0b2d5")

                inspector = sa.inspect(engine)
                columns = {column["name"] for column in inspector.get_columns("quickresto_connections")}
                self.assertTrue(
                    {
                        "pending_external_venue_id",
                        "pending_sale_place_ids_json",
                        "pending_store_ids_json",
                        "pending_scope_generation",
                        "pending_scope_requested_at",
                        "pending_scope_requested_by_user_id",
                    }.issubset(columns)
                )
                indexes = {index["name"] for index in inspector.get_indexes("quickresto_connections")}
                self.assertIn("ix_quickresto_connections_pending_external_venue_id", indexes)
                self.assertIn("ix_quickresto_connections_pending_scope_requested_by_user_id", indexes)

                command.downgrade(config, "e2b4d6f8a1c3")

            columns = {column["name"] for column in sa.inspect(engine).get_columns("quickresto_connections")}
            self.assertNotIn("pending_external_venue_id", columns)
            self.assertNotIn("pending_scope_generation", columns)

    def test_quickresto_scope_move_constraint_round_trips_on_sqlite_fixture(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE quickresto_shift_imports ("
                    "id INTEGER PRIMARY KEY, scope_resolution_action VARCHAR(24), "
                    "CONSTRAINT ck_quickresto_shift_imports_scope_resolution_action "
                    "CHECK (scope_resolution_action IS NULL OR "
                    "scope_resolution_action IN ('KEEP_CURRENT', 'EXCLUDE_CURRENT')))"
                )

            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "f4c6e8a0b2d5")
                command.upgrade(config, "a7d3e5f1c9b2")
                constraints = {
                    item["name"]: item["sqltext"]
                    for item in sa.inspect(engine).get_check_constraints("quickresto_shift_imports")
                }
                self.assertIn(
                    "MOVE_TO_CONNECTED",
                    constraints["ck_quickresto_shift_imports_scope_resolution_action"],
                )
                command.downgrade(config, "f4c6e8a0b2d5")

            constraints = {
                item["name"]: item["sqltext"]
                for item in sa.inspect(engine).get_check_constraints("quickresto_shift_imports")
            }
            self.assertNotIn(
                "MOVE_TO_CONNECTED",
                constraints["ck_quickresto_shift_imports_scope_resolution_action"],
            )

    def test_quickresto_historical_scope_resolution_migration_round_trips_on_sqlite_fixture(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)
            with engine.begin() as connection:
                connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
                connection.exec_driver_sql("CREATE TABLE quickresto_shift_imports (id INTEGER PRIMARY KEY)")

            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "d0f8b6c4e2a1")
                command.upgrade(config, "e2b4d6f8a1c3")

                inspector = sa.inspect(engine)
                columns = {column["name"] for column in inspector.get_columns("quickresto_shift_imports")}
                self.assertTrue(
                    {
                        "scope_resolution_action",
                        "scope_resolution_generation",
                        "scope_resolved_by_user_id",
                        "scope_resolved_at",
                        "scope_resolution_note",
                    }.issubset(columns)
                )
                indexes = {index["name"] for index in inspector.get_indexes("quickresto_shift_imports")}
                self.assertIn("ix_quickresto_shift_imports_scope_resolution_action", indexes)
                self.assertIn("ix_quickresto_shift_imports_scope_resolved_by_user_id", indexes)

                command.downgrade(config, "d0f8b6c4e2a1")

            columns = {column["name"] for column in sa.inspect(engine).get_columns("quickresto_shift_imports")}
            self.assertNotIn("scope_resolution_action", columns)
            self.assertNotIn("scope_resolved_by_user_id", columns)

    def test_quickresto_scope_hardening_migration_round_trips_on_sqlite_fixture(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)
            with engine.begin() as connection:
                for statement in (
                    "CREATE TABLE users (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE quickresto_connections (id INTEGER PRIMARY KEY, external_venue_id INTEGER, scope_confirmed_at DATETIME)",
                    "CREATE TABLE quickresto_external_venues (id INTEGER PRIMARY KEY, connection_id INTEGER NOT NULL, external_id INTEGER NOT NULL, external_version INTEGER)",
                    "CREATE TABLE quickresto_sale_place_scopes (id INTEGER PRIMARY KEY, connection_id INTEGER NOT NULL, is_confirmed BOOLEAN NOT NULL DEFAULT 0)",
                ):
                    connection.exec_driver_sql(statement)
                connection.exec_driver_sql("INSERT INTO users (id) VALUES (1)")
                connection.exec_driver_sql(
                    "INSERT INTO quickresto_connections (id, external_venue_id, scope_confirmed_at) VALUES (1, 101, '2026-09-01')"
                )
                connection.exec_driver_sql(
                    "INSERT INTO quickresto_external_venues (id, connection_id, external_id, external_version) VALUES (1, 1, 101, 7)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO quickresto_sale_place_scopes (id, connection_id, is_confirmed) VALUES (1, 1, 1)"
                )

            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "c9e7a5b3d1f0")
                command.upgrade(config, "d0f8b6c4e2a1")
                inspector = sa.inspect(engine)
                connection_columns = {column["name"] for column in inspector.get_columns("quickresto_connections")}
                sale_columns = {column["name"] for column in inspector.get_columns("quickresto_sale_place_scopes")}
                self.assertIn("external_venue_version", connection_columns)
                self.assertIn("scope_confirmed_by_user_id", connection_columns)
                self.assertIn("confirmed_by_user_id", sale_columns)
                self.assertIn("confirmed_at", sale_columns)
                self.assertIn("quickresto_scope_audits", inspector.get_table_names())
                with engine.connect() as connection:
                    version = connection.exec_driver_sql(
                        "SELECT external_venue_version FROM quickresto_connections WHERE id = 1"
                    ).scalar_one()
                    self.assertEqual(version, 7)
                command.downgrade(config, "c9e7a5b3d1f0")

            inspector = sa.inspect(engine)
            self.assertNotIn("quickresto_scope_audits", inspector.get_table_names())
            self.assertNotIn(
                "external_venue_version",
                {column["name"] for column in inspector.get_columns("quickresto_connections")},
            )

    def test_quickresto_multi_venue_scope_migration_round_trips_on_sqlite_fixture(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)
            with engine.begin() as connection:
                for statement in (
                    "CREATE TABLE venues (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE quickresto_connections (id INTEGER PRIMARY KEY, venue_id INTEGER NOT NULL, cloud VARCHAR(255) NOT NULL, is_active BOOLEAN NOT NULL DEFAULT 1, auto_sync_enabled BOOLEAN NOT NULL DEFAULT 0, last_sync_error TEXT)",
                    "CREATE TABLE quickresto_payment_mappings (id INTEGER PRIMARY KEY)",
                ):
                    connection.exec_driver_sql(statement)
                connection.exec_driver_sql("INSERT INTO venues (id) VALUES (1)")
                connection.exec_driver_sql(
                    "INSERT INTO quickresto_connections "
                    "(id, venue_id, cloud, is_active, auto_sync_enabled, last_sync_error) "
                    "VALUES (1, 1, 'legacy', 1, 1, NULL)"
                )

            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "b8d4f6a2c1e9")
                command.upgrade(config, "c9e7a5b3d1f0")

                inspector = sa.inspect(engine)
                connection_columns = {column["name"] for column in inspector.get_columns("quickresto_connections")}
                self.assertIn("external_venue_id", connection_columns)
                self.assertIn("scope_status", connection_columns)
                with engine.connect() as connection:
                    migration_warning = connection.exec_driver_sql(
                        "SELECT last_sync_error FROM quickresto_connections WHERE id = 1"
                    ).scalar_one()
                self.assertIn("Автосинхронизация приостановлена", migration_warning)
                payment_columns = {column["name"] for column in inspector.get_columns("quickresto_payment_mappings")}
                self.assertIn("is_applicable", payment_columns)
                self.assertIn("allowed_sale_place_ids_json", payment_columns)
                for table_name in (
                    "quickresto_external_venues",
                    "quickresto_sale_place_scopes",
                    "quickresto_store_scopes",
                    "venue_pos_integration_selections",
                ):
                    self.assertIn(table_name, inspector.get_table_names())

                command.downgrade(config, "b8d4f6a2c1e9")

            inspector = sa.inspect(engine)
            with engine.connect() as connection:
                migration_warning = connection.exec_driver_sql(
                    "SELECT last_sync_error FROM quickresto_connections WHERE id = 1"
                ).scalar_one()
            self.assertIsNone(migration_warning)
            self.assertNotIn("quickresto_external_venues", inspector.get_table_names())
            self.assertNotIn(
                "external_venue_id",
                {column["name"] for column in inspector.get_columns("quickresto_connections")},
            )

    def test_quickresto_import_issues_migration_round_trips_on_sqlite_fixture(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)
            with engine.begin() as connection:
                for statement in (
                    "CREATE TABLE users (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE quickresto_connections (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE quickresto_sync_runs (id INTEGER PRIMARY KEY)",
                    "CREATE TABLE quickresto_shift_imports (id INTEGER PRIMARY KEY)",
                ):
                    connection.exec_driver_sql(statement)

            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "a7c9e1f3b5d7")
                command.upgrade(config, "b8d4f6a2c1e9")

                inspector = sa.inspect(engine)
                self.assertIn(
                    "notify_integrations",
                    {column["name"] for column in inspector.get_columns("users")},
                )
                connection_columns = {column["name"] for column in inspector.get_columns("quickresto_connections")}
                self.assertIn("incremental_cursor_closed_at", connection_columns)
                self.assertIn("last_full_reconciliation_at", connection_columns)
                for table_name in (
                    "quickresto_source_snapshots",
                    "quickresto_import_issues",
                    "quickresto_import_issue_shifts",
                    "quickresto_import_issue_audits",
                ):
                    self.assertIn(table_name, inspector.get_table_names())

                command.downgrade(config, "a7c9e1f3b5d7")

            inspector = sa.inspect(engine)
            self.assertNotIn("quickresto_import_issues", inspector.get_table_names())
            self.assertNotIn(
                "notify_integrations",
                {column["name"] for column in inspector.get_columns("users")},
            )

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

    def test_interval_scopes_backfill_and_rollback_preserve_assigned_shifts(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)
            self.addCleanup(engine.dispose)
            with engine.begin() as connection:
                for statement in (
                    "CREATE TABLE venue_positions (id INTEGER PRIMARY KEY, venue_id INTEGER NOT NULL, member_user_id INTEGER, title TEXT NOT NULL, is_active BOOLEAN NOT NULL)",
                    "CREATE TABLE shift_intervals (id INTEGER PRIMARY KEY, venue_id INTEGER NOT NULL, position_id INTEGER REFERENCES venue_positions(id))",
                    "CREATE TABLE shifts (id INTEGER PRIMARY KEY, interval_id INTEGER NOT NULL)",
                    "CREATE TABLE shift_assignments (id INTEGER PRIMARY KEY, shift_id INTEGER NOT NULL, venue_position_id INTEGER NOT NULL)",
                    "INSERT INTO venue_positions VALUES (10,5,NULL,'Бармен',1), (11,5,NULL,'Менеджер',1), (12,5,NULL,' бармен ',0), (20,5,2,'Бармен',1), (21,5,2,'Менеджер',1), (22,6,3,'Бармен',1)",
                    "INSERT INTO shift_intervals VALUES (1,5,NULL), (2,5,12), (3,5,11)",
                    "INSERT INTO shifts VALUES (1,2)",
                    "INSERT INTO shift_assignments VALUES (1,1,21)",
                ):
                    connection.exec_driver_sql(statement)
            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "b9d2e4f6a8c1")
                command.upgrade(config, "c2f4a6b8d0e1")
                with engine.connect() as connection:
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "SELECT id, catalog_position_id FROM venue_positions WHERE member_user_id IS NOT NULL ORDER BY id"
                        ).all(),
                        [(20, 10), (21, 11), (22, None)],
                    )
                    self.assertEqual(
                        connection.exec_driver_sql(
                            "SELECT * FROM shift_interval_positions ORDER BY interval_id, position_id"
                        ).all(),
                        [(2, 10), (2, 12), (3, 11)],
                    )
                    self.assertEqual(connection.exec_driver_sql("SELECT * FROM shifts").all(), [(1, 2)])
                    self.assertEqual(connection.exec_driver_sql("SELECT * FROM shift_assignments").all(), [(1, 1, 21)])
                with self.assertRaisesRegex(RuntimeError, "at most one allowed position"):
                    command.downgrade(config, "b9d2e4f6a8c1")
                self.assertIn("shift_interval_positions", sa.inspect(engine).get_table_names())
                with engine.begin() as connection:
                    connection.exec_driver_sql(
                        "DELETE FROM shift_interval_positions WHERE interval_id=2 AND position_id=10"
                    )
                command.downgrade(config, "b9d2e4f6a8c1")
                with engine.connect() as connection:
                    self.assertEqual(connection.exec_driver_sql("SELECT * FROM shift_assignments").all(), [(1, 1, 21)])
                    self.assertEqual(
                        connection.exec_driver_sql("SELECT position_id FROM shift_intervals ORDER BY id").all(),
                        [(None,), (12,), (11,)],
                    )
                self.assertNotIn(
                    "catalog_position_id",
                    {column["name"] for column in sa.inspect(engine).get_columns("venue_positions")},
                )

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

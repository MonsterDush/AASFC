from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import patch

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app.core.config import settings


BACKEND_DIR = Path(__file__).resolve().parents[1]


class CatalogPositionBackfillMigrationTests(unittest.TestCase):
    def _config(self) -> Config:
        config = Config(str(BACKEND_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
        return config

    def test_backfill_creates_catalog_roles_without_touching_legacy_intervals(self):
        with NamedTemporaryFile(suffix=".sqlite") as handle:
            database_url = f"sqlite:///{handle.name}"
            engine = sa.create_engine(database_url)

            with engine.begin() as connection:
                connection.exec_driver_sql(
                    """
                    CREATE TABLE venue_positions (
                        id INTEGER PRIMARY KEY,
                        venue_id INTEGER NOT NULL,
                        member_user_id INTEGER,
                        title VARCHAR(100) NOT NULL,
                        rate INTEGER NOT NULL DEFAULT 0,
                        percent INTEGER NOT NULL DEFAULT 0,
                        pay_profile_id INTEGER,
                        permission_codes TEXT,
                        is_active BOOLEAN NOT NULL DEFAULT 1
                    )
                    """
                )

                connection.exec_driver_sql(
                    """
                    CREATE TABLE venue_setup_state (
                        id INTEGER PRIMARY KEY,
                        venue_id INTEGER NOT NULL,
                        step_meta_json TEXT
                    )
                    """
                )

                connection.exec_driver_sql(
                    """
                    CREATE TABLE shift_intervals (
                        id INTEGER PRIMARY KEY,
                        venue_id INTEGER NOT NULL,
                        title VARCHAR(100) NOT NULL,
                        position_id INTEGER
                    )
                    """
                )

                connection.exec_driver_sql(
                    """
                    INSERT INTO venue_positions (
                        id,
                        venue_id,
                        member_user_id,
                        title,
                        rate,
                        percent,
                        pay_profile_id,
                        permission_codes,
                        is_active
                    )
                    VALUES
                        (1, 10, 101, 'Бармен', 1500, 10, NULL, NULL, 1),
                        (2, 10, 102, 'Бармен', 1800, 12, NULL, NULL, 1),
                        (3, 10, 103, 'Кальянщик', 2000, 10, NULL, NULL, 1),
                        (4, 10, NULL, 'Кальянщик', 0, 0, NULL, NULL, 0)
                    """
                )

                connection.execute(
                    sa.text(
                        """
                        INSERT INTO venue_setup_state (
                            id,
                            venue_id,
                            step_meta_json
                        )
                        VALUES (
                            1,
                            10,
                            :meta
                        )
                        """
                    ),
                    {
                        "meta": (
                            '{"positions":{"presets":['
                            '{"title":"Администратор","rate":2500,'
                            '"percent":5,"is_active":true}'
                            "]}}"
                        )
                    },
                )

                connection.exec_driver_sql(
                    """
                    INSERT INTO shift_intervals (
                        id,
                        venue_id,
                        title,
                        position_id
                    )
                    VALUES (
                        1,
                        10,
                        'Старый интервал',
                        NULL
                    )
                    """
                )

            with patch.object(settings, "database_url", database_url):
                config = self._config()
                command.stamp(config, "f6b4d2a8c1e0")
                command.upgrade(config, "b9d2e4f6a8c1")

            with engine.connect() as connection:
                catalogs = connection.exec_driver_sql(
                    """
                    SELECT title, is_active
                    FROM venue_positions
                    WHERE member_user_id IS NULL
                    ORDER BY title
                    """
                ).fetchall()

                legacy_position_id = connection.exec_driver_sql(
                    """
                    SELECT position_id
                    FROM shift_intervals
                    WHERE id = 1
                    """
                ).scalar_one()

            self.assertEqual(
                catalogs,
                [
                    ("Администратор", 1),
                    ("Бармен", 1),
                    ("Кальянщик", 1),
                ],
            )

            self.assertIsNone(legacy_position_id)


if __name__ == "__main__":
    unittest.main()

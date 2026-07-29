from __future__ import annotations

import unittest
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND_DIR = Path(__file__).resolve().parents[1]


class MigrationContractTests(unittest.TestCase):
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
        source = (BACKEND_DIR / "alembic" / "versions" / "4a7c9e2b6d10_add_shift_comment_mentions_and_replies.py").read_text(encoding="utf-8")
        self.assertIn('"parent_comment_id"', source)
        self.assertIn('"shift_comment_mentions"', source)
        self.assertIn('"uq_shift_comment_mention_user"', source)


if __name__ == "__main__":
    unittest.main()

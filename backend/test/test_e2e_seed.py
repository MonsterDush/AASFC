from __future__ import annotations

import unittest

from app.scripts.bootstrap_e2e_data import require_safe_e2e_database


class E2ESeedSafetyTests(unittest.TestCase):
    def test_accepts_confirmed_loopback_e2e_database(self):
        require_safe_e2e_database(
            "postgresql+psycopg://user:pass@127.0.0.1:55433/axelio_e2e",
            confirmation="1",
        )

    def test_rejects_missing_confirmation(self):
        with self.assertRaisesRegex(RuntimeError, "AXELIO_E2E_ALLOW_SEED"):
            require_safe_e2e_database(
                "postgresql+psycopg://user:pass@127.0.0.1:55433/axelio_e2e",
                confirmation=None,
            )

    def test_rejects_non_local_database(self):
        with self.assertRaisesRegex(RuntimeError, "local database host"):
            require_safe_e2e_database(
                "postgresql+psycopg://user:pass@db.example.com/axelio_e2e",
                confirmation="1",
            )

    def test_rejects_database_without_test_marker(self):
        with self.assertRaisesRegex(RuntimeError, "must contain"):
            require_safe_e2e_database(
                "postgresql+psycopg://user:pass@localhost/axelio_prod",
                confirmation="1",
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from datetime import date
from unittest import TestCase

from app.services.finance.ledger import create_finance_entry


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


class FinanceLedgerTests(TestCase):
    def test_create_finance_entry_uses_kopecks_and_absolute_amount(self):
        db = _FakeSession()

        entry = create_finance_entry(
            db=db,
            venue_id=12,
            entry_date=date(2026, 3, 10),
            amount_minor=12345,
            direction="income",
            kind="revenue",
            source_type="daily_report",
            source_id=77,
            meta_json={"report_date": "2026-03-10"},
        )

        self.assertEqual(entry.amount_minor, 12345)
        self.assertEqual(entry.direction, "INCOME")
        self.assertEqual(entry.kind, "REVENUE")
        self.assertEqual(entry.source_type, "daily_report")
        self.assertEqual(entry.source_id, 77)
        self.assertEqual(entry.meta_json, {"report_date": "2026-03-10"})
        self.assertEqual(len(db.added), 1)

    def test_create_finance_entry_rejects_non_int_amount(self):
        db = _FakeSession()

        with self.assertRaisesRegex(ValueError, "amount_minor must be int"):
            create_finance_entry(
                db=db,
                venue_id=12,
                entry_date=date(2026, 3, 10),
                amount_minor=12.34,
                direction="income",
                kind="revenue",
                source_type="daily_report",
            )

    def test_create_finance_entry_rejects_negative_amount(self):
        db = _FakeSession()

        with self.assertRaisesRegex(ValueError, "amount_minor must be non-negative"):
            create_finance_entry(
                db=db,
                venue_id=12,
                entry_date=date(2026, 3, 10),
                amount_minor=-100,
                direction="expense",
                kind="expense",
                source_type="expense",
            )

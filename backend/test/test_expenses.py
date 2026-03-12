from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.routers import venues


class _AllResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        if not self._responses:
            raise AssertionError("Unexpected execute() call without a prepared response")
        return self._responses.pop(0)


class ExpensesTests(TestCase):
    def test_list_expenses_filters_confirmed_by_recognition_month(self):
        expense = SimpleNamespace(
            id=15,
            venue_id=3,
            category_id=7,
            supplier_id=None,
            amount_minor=12345,
            expense_date=date(2026, 2, 10),
            spread_months=2,
            status="CONFIRMED",
            comment="Тест",
            created_by_user_id=44,
            created_at=None,
            updated_at=None,
        )
        category = SimpleNamespace(id=7, code="rent", title="Аренда")
        db = _FakeSession(responses=[_AllResult([(expense, category, None)])])
        user = SimpleNamespace(id=101, system_role="NONE")
        allocations = [
            SimpleNamespace(id=1, expense_id=15, venue_id=3, month=date(2026, 2, 1), amount_minor=6000, created_at=datetime.utcnow()),
            SimpleNamespace(id=2, expense_id=15, venue_id=3, month=date(2026, 3, 1), amount_minor=6345, created_at=datetime.utcnow()),
        ]

        with patch.object(venues, "require_venue_permission", return_value=None), patch.object(venues, "list_expense_allocations", return_value=allocations):
            result = venues.list_expenses(
                venue_id=1,
                month="2026-03",
                category_id=None,
                supplier_id=None,
                db=db,
                user=user,
            )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["recognized_amount_minor_for_month"], 6345)
        self.assertEqual(result[0]["recognized_month"], "2026-03-01")
        self.assertEqual(result[0]["status"], "CONFIRMED")

    def test_serialize_expense_returns_minor_units_and_nested_refs(self):
        category = SimpleNamespace(id=7, code="rent", title="Аренда")
        supplier = SimpleNamespace(id=9, title="ООО Поставщик", contact="+79990000000")
        expense = SimpleNamespace(
            id=15,
            venue_id=3,
            category_id=7,
            supplier_id=9,
            amount_minor=12345,
            expense_date=date(2026, 3, 10),
            spread_months=2,
            status="DRAFT",
            comment="Тест",
            created_by_user_id=44,
            created_at=None,
            updated_at=None,
        )
        allocations = [SimpleNamespace(id=1, expense_id=15, venue_id=3, month=date(2026, 3, 1), amount_minor=6172, created_at=None)]

        payload = venues._serialize_expense(expense, category, supplier, allocations, recognized_month=date(2026, 3, 1))

        self.assertEqual(payload["amount_minor"], 12345)
        self.assertEqual(payload["spread_months"], 2)
        self.assertEqual(payload["status"], "DRAFT")
        self.assertEqual(payload["recognized_amount_minor_for_month"], 6172)
        self.assertEqual(payload["category"]["code"], "rent")
        self.assertEqual(payload["supplier"]["title"], "ООО Поставщик")

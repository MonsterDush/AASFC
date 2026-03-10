from __future__ import annotations

from datetime import date
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
    def test_list_expenses_filters_by_month_range(self):
        db = _FakeSession(
            responses=[
                _AllResult([]),
            ]
        )
        user = SimpleNamespace(id=101, system_role="NONE")

        with patch.object(venues, "require_venue_permission", return_value=None):
            result = venues.list_expenses(
                venue_id=1,
                month="2026-03",
                category_id=None,
                supplier_id=None,
                db=db,
                user=user,
            )

        self.assertEqual(result, [])
        compiled_params = [stmt.compile().params for stmt in db.statements]
        params = compiled_params[0]
        self.assertIn(date(2026, 3, 1), params.values())
        self.assertIn(date(2026, 3, 31), params.values())

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
            comment="Тест",
            created_by_user_id=44,
            created_at=None,
            updated_at=None,
        )

        payload = venues._serialize_expense(expense, category, supplier)

        self.assertEqual(payload["amount_minor"], 12345)
        self.assertEqual(payload["spread_months"], 2)
        self.assertEqual(payload["category"]["code"], "rent")
        self.assertEqual(payload["supplier"]["title"], "ООО Поставщик")

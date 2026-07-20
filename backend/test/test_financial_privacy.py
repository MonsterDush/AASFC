from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.services import financial_privacy


class FinancialPrivacyTests(TestCase):
    def test_only_super_admin_is_hidden_when_setting_is_disabled(self):
        with patch.object(financial_privacy.settings, "SUPER_ADMIN_CAN_VIEW_FINANCIAL_VALUES", False):
            self.assertTrue(financial_privacy.should_hide_financial_values_for_user(SimpleNamespace(system_role=" super_admin ")))
            self.assertFalse(financial_privacy.should_hide_financial_values_for_user(SimpleNamespace(system_role="VENUE_OWNER")))
            self.assertFalse(financial_privacy.should_hide_financial_values_for_user(None))

        with patch.object(financial_privacy.settings, "SUPER_ADMIN_CAN_VIEW_FINANCIAL_VALUES", True):
            self.assertFalse(financial_privacy.should_hide_financial_values_for_user(SimpleNamespace(system_role="SUPER_ADMIN")))

    def test_visibility_payload_explains_hidden_state(self):
        user = SimpleNamespace(system_role="SUPER_ADMIN")
        with patch.object(financial_privacy.settings, "SUPER_ADMIN_CAN_VIEW_FINANCIAL_VALUES", False):
            payload = financial_privacy.financial_visibility_payload(user)

        self.assertFalse(payload["can_view_financial_values"])
        self.assertTrue(payload["financial_values_hidden"])
        self.assertEqual(payload["financial_values_hidden_reason"], financial_privacy.FINANCIAL_VALUES_HIDDEN_MESSAGE)

    def test_sanitize_masks_nested_financial_numbers_and_keeps_metadata(self):
        payload = {
            "venue_id": 12,
            "report_date": date(2026, 7, 18),
            "revenue_minor": 123_456,
            "margin_bps": 2_500,
            "is_active": True,
            "department_count": 3,
            "unclassified_number": 17,
            "rows": [
                {
                    "expense_total": Decimal("42.50"),
                    "supplier_name": "Склад",
                    "amount": None,
                }
            ],
            "totals": (123, {"payroll_minor": -500}),
        }

        result = financial_privacy.sanitize_financial_payload(payload)

        self.assertEqual(result["venue_id"], 12)
        self.assertEqual(result["report_date"], date(2026, 7, 18))
        self.assertEqual(result["revenue_minor"], 0)
        self.assertEqual(result["margin_bps"], 0)
        self.assertTrue(result["is_active"])
        self.assertEqual(result["department_count"], 3)
        self.assertEqual(result["unclassified_number"], 17)
        self.assertEqual(result["rows"][0]["expense_total"], 0)
        self.assertEqual(result["rows"][0]["supplier_name"], "Склад")
        self.assertIsNone(result["rows"][0]["amount"])
        self.assertEqual(result["totals"], (123, {"payroll_minor": 0}))
        self.assertTrue(result["financial_values_hidden"])
        self.assertFalse(result["can_view_financial_values"])

    def test_model_payload_is_dumped_before_sanitizing(self):
        class PayloadModel:
            def model_dump(self, *, mode):
                self.mode = mode
                return {"income_minor": 99, "status": "READY"}

        model = PayloadModel()
        result = financial_privacy.sanitize_financial_payload(model)

        self.assertEqual(model.mode, "json")
        self.assertEqual(result["income_minor"], 0)
        self.assertEqual(result["status"], "READY")

    def test_unmaskable_values_and_failed_model_dump_are_preserved(self):
        payload = {"": 17, "amount": True, "cash": "unknown"}

        result = financial_privacy.sanitize_financial_payload(payload)

        self.assertEqual(result[""], 17)
        self.assertTrue(result["amount"])
        self.assertEqual(result["cash"], "unknown")

        class BrokenPayloadModel:
            def model_dump(self, *, mode):
                raise RuntimeError("serialization failed")

        model = BrokenPayloadModel()
        self.assertIs(financial_privacy.sanitize_financial_payload(model), model)

    def test_visible_payload_is_returned_unchanged(self):
        payload = {"revenue_minor": 99}
        self.assertIs(financial_privacy.sanitize_financial_payload(payload, hidden=False), payload)

    def test_sanitize_for_user_uses_visibility_setting(self):
        hidden_user = SimpleNamespace(system_role="SUPER_ADMIN")
        visible_user = SimpleNamespace(system_role="STAFF")
        payload = {"profit_minor": 700}

        with patch.object(financial_privacy.settings, "SUPER_ADMIN_CAN_VIEW_FINANCIAL_VALUES", False):
            self.assertEqual(financial_privacy.sanitize_financial_payload_for_user(hidden_user, payload)["profit_minor"], 0)
            self.assertIs(financial_privacy.sanitize_financial_payload_for_user(visible_user, payload), payload)

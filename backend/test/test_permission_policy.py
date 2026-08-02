from __future__ import annotations

from unittest import TestCase

from app.core import permission_policy


class PermissionPolicyTests(TestCase):
    def test_normalize_permission_code(self):
        self.assertEqual(permission_policy.normalize_permission_code(" shifts_view "), "SHIFTS_VIEW")
        self.assertEqual(permission_policy.normalize_permission_code(None), "")

    def test_expand_permission_codes_adds_transitive_dependencies(self):
        expanded = permission_policy.expand_permission_codes([" shift_report_close "])

        self.assertEqual(
            expanded,
            {
                "SHIFT_REPORT_CLOSE",
                "SHIFT_REPORT_VIEW",
                "DEPARTMENTS_VIEW",
                "PAYMENT_METHODS_VIEW",
                "KPI_METRICS_VIEW",
            },
        )

    def test_expand_permission_codes_deduplicates_and_ignores_empty_values(self):
        self.assertEqual(
            permission_policy.expand_permission_codes(["shifts_manage", "SHIFTS_VIEW", "", None]),
            {"SHIFTS_MANAGE", "SHIFTS_VIEW"},
        )
        self.assertEqual(permission_policy.expand_permission_codes(None), set())

    def test_payroll_calculate_implies_payroll_view(self):
        self.assertEqual(
            permission_policy.expand_permission_codes(["PAYROLL_CALCULATE"]),
            {"PAYROLL_CALCULATE", "PAYROLL_VIEW"},
        )

    def test_manager_defaults_include_report_dependencies(self):
        codes = permission_policy.get_default_permission_codes_for_role("venue_manager")

        self.assertIn("VENUE_VIEW", codes)
        self.assertIn("SHIFT_REPORT_CLOSE", codes)
        self.assertIn("SHIFT_REPORT_VIEW", codes)
        self.assertIn("DEPARTMENTS_VIEW", codes)
        self.assertIn("PAYMENT_METHODS_VIEW", codes)
        self.assertIn("KPI_METRICS_VIEW", codes)

    def test_owner_and_moderator_receive_all_registered_permissions(self):
        self.assertEqual(
            permission_policy.get_default_permission_codes_for_role("VENUE_OWNER"),
            permission_policy.ALL_PERMISSION_CODES,
        )
        self.assertEqual(
            permission_policy.get_default_permission_codes_for_role("moderator"),
            permission_policy.ALL_PERMISSION_CODES,
        )

    def test_unknown_role_has_no_defaults(self):
        self.assertEqual(permission_policy.get_default_permission_codes_for_role("UNKNOWN"), set())

    def test_role_default_lookup_handles_empty_and_normalized_values(self):
        self.assertTrue(permission_policy.role_has_built_in_default("staff", " shifts_view "))
        self.assertFalse(permission_policy.role_has_built_in_default("staff", "SHIFT_REPORT_VIEW"))
        self.assertFalse(permission_policy.role_has_built_in_default("staff", None))

    def test_shift_report_permission_recognizes_only_report_codes(self):
        self.assertTrue(permission_policy.is_shift_report_permission(" shift_report_reopen "))
        self.assertFalse(permission_policy.is_shift_report_permission("SHIFTS_VIEW"))

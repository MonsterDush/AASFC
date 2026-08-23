from __future__ import annotations

import tempfile
from pathlib import Path
from unittest import TestCase

from pydantic import ValidationError

from app.core.upload_storage import confined_upload_storage_path, new_upload_storage_path
from app.routers.admin_demo import DemoBootstrapIn, DemoExportIn, DemoResetIn
from app.services.demo.fixture import BACKEND_ROOT, _resolve_fixture_path


REPO_ROOT = Path(__file__).resolve().parents[2]


class UploadStorageSecurityTests(TestCase):
    def test_generated_storage_name_contains_no_client_filename(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = new_upload_storage_path(tmp_dir)

        self.assertEqual(path.parent, Path(tmp_dir).resolve())
        self.assertRegex(path.name, r"^[0-9a-f]{32}$")

    def test_stored_path_must_remain_inside_upload_root(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            allowed = root / "fixture"
            outside = root.parent / "outside"
            self.assertEqual(confined_upload_storage_path(root, allowed), allowed.resolve())
            with self.assertRaises(ValueError):
                confined_upload_storage_path(root, outside)


class DemoFixturePathSecurityTests(TestCase):
    def test_custom_fixture_path_is_json_inside_backend(self):
        allowed = _resolve_fixture_path("tmp/security-fixture.json")
        self.assertEqual(allowed, (BACKEND_ROOT / "tmp/security-fixture.json").resolve())

        with self.assertRaises(ValueError):
            _resolve_fixture_path("../outside.json")
        with self.assertRaises(ValueError):
            _resolve_fixture_path("tmp/security-fixture.txt")

    def test_admin_payloads_forbid_custom_fixture_paths(self):
        for schema in (DemoExportIn, DemoResetIn, DemoBootstrapIn):
            with self.subTest(schema=schema.__name__), self.assertRaises(ValidationError):
                schema.model_validate({"fixture_path": "../../etc/passwd"})


class FrontendSecurityContractTests(TestCase):
    def _read(self, relative_path: str) -> str:
        return (REPO_ROOT / relative_path).read_text(encoding="utf-8")

    def test_auth_next_navigation_is_same_origin_only(self):
        source = self._read("frontend/auth.html")
        self.assertIn("target.origin !== location.origin", source)
        self.assertNotIn("return next;", source)

    def test_demo_navigation_and_markup_are_sanitized(self):
        source = self._read("frontend/app.js")
        self.assertIn("function safeDemoNavigationUrl", source)
        self.assertIn("escapeDemoHtml(banner.primary_cta_label", source)
        self.assertNotIn("location.href = out?.redirect_url", source)

    def test_billing_invoice_is_not_persisted_in_browser_storage(self):
        source = self._read("frontend/app-venue.html")
        self.assertNotIn("billingPaymentPendingStorageKey", source)
        self.assertNotIn("rememberPendingBillingPayment", source)

    def test_selector_values_are_compared_without_string_interpolation(self):
        calendar = self._read("frontend/staff-shifts/calendar-controller.js")
        comments = self._read("frontend/staff-shifts/comment-controller.js")
        self.assertIn("candidate.getAttribute('data-date') === normalizedDate", calendar)
        self.assertIn('candidate.getAttribute("data-comment-id") === normalizedCommentId', comments)

    def test_offline_catalog_uses_html_parser_for_script_content(self):
        source = self._read("tools/build_en_catalog_offline.py")
        self.assertIn("class ScriptContentParser(HTMLParser):", source)
        self.assertNotIn("SCRIPT_RE", source)

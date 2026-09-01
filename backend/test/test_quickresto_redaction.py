from __future__ import annotations

from unittest import TestCase

from app.services.integrations.quickresto_issues import classify_quickresto_failure
from app.services.integrations.quickresto_normalize import QuickRestoDataError
from app.services.integrations.quickresto_redaction import (
    STRUCTURED_DETAIL_REDACTED,
    redact_quickresto_technical_summary,
)


class QuickRestoRedactionTests(TestCase):
    def test_redacts_credentials_query_values_and_plain_pii(self):
        source = (
            "Bearer bearer-secret authorization=Basic auth-secret token=token-secret "
            "https://api-user:api-pass@cloud.example/api?api_password=query-secret "
            "guest=Guest-Secret email=guest@example.test phone=+79990000000"
        )

        redacted = redact_quickresto_technical_summary(source)

        self.assertIsNotNone(redacted)
        for marker in (
            "bearer-secret",
            "auth-secret",
            "token-secret",
            "api-user",
            "api-pass",
            "query-secret",
            "Guest-Secret",
            "guest@example.test",
            "+79990000000",
        ):
            self.assertNotIn(marker, redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_json_like_source_or_pii_detail_is_rejected_as_a_whole(self):
        redacted = redact_quickresto_technical_summary(
            '{"guest": {"phone": "+79990000000"}, "orders": [{"comment": "secret"}]}'
        )

        self.assertEqual(redacted, STRUCTURED_DETAIL_REDACTED)

    def test_unexpected_failure_fingerprint_does_not_depend_on_secret_message(self):
        first = classify_quickresto_failure(
            RuntimeError("token=first-secret guest=Alice phone=+79990000001"),
            correlation_id="correlation token=first-secret",
        )
        second = classify_quickresto_failure(
            RuntimeError("token=second-secret guest=Bob phone=+79990000002"),
            correlation_id="correlation token=second-secret",
        )

        self.assertEqual(first.technical_summary, "RuntimeError: unexpected QuickResto import failure")
        self.assertEqual(first.technical_summary, second.technical_summary)
        self.assertEqual(first.fingerprint, second.fingerprint)
        self.assertNotIn("first-secret", first.correlation_id)
        self.assertRegex(first.correlation_id, r"^redacted-[0-9a-f]{16}$")

    def test_known_mapping_failure_keeps_only_actionable_ids(self):
        failure = classify_quickresto_failure(
            QuickRestoDataError("QuickResto mappings are incomplete: payments=[7], departments=[9]")
        )

        self.assertEqual(failure.error_code, "MAPPING_INCOMPLETE")
        self.assertEqual(failure.details["missing_payment_type_ids"], [7])
        self.assertEqual(failure.details["missing_department_ids"], [9])

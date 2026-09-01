from __future__ import annotations

from datetime import date
import unittest
from unittest.mock import patch

from app.services.integrations import credentials
from app.services.integrations.quickresto_snapshot import (
    QuickRestoSnapshotError,
    open_quickresto_source_snapshot,
    seal_quickresto_source_snapshot,
)


class QuickRestoSourceSnapshotTests(unittest.TestCase):
    def _shift(self, **overrides):
        values = {
            "id": 42,
            "frontId": "shift-safe-42",
            "version": 3,
            "status": "CLOSED",
            "localOpenedTime": "2030-01-15T10:00:00.000Z",
            "localClosedTime": "2030-01-15T18:00:00.000Z",
            "totalCash": 1000.25,
            "guestName": "must not be retained",
        }
        values.update(overrides)
        return values

    def _orders(self, *, amount=1000.25):
        return [
            {
                "id": 99,
                "shiftId": "shift-safe-42",
                "returned": False,
                "frontTotalPrice": amount,
                "guest": {"phone": "+79990000000"},
                "comment": "secret free-form value",
                "payments": [
                    {
                        "amount": amount,
                        "paymentType": {"id": 7, "operationType": "payment", "name": "Guest card"},
                    }
                ],
                "orderItemList": [
                    {
                        "totalPrice": amount,
                        "totalAbsoluteDiscount": 0,
                        "totalAbsoluteCharge": 0,
                        "product": {"id": 11, "parentId": 5, "name": "Private product label"},
                    }
                ],
            }
        ]

    def test_snapshot_is_allowlisted_encrypted_and_integrity_checked(self):
        with patch.object(credentials.settings, "INTEGRATION_ENCRYPTION_KEY", "s" * 48):
            sealed = seal_quickresto_source_snapshot(
                shift=self._shift(),
                orders=self._orders(),
                business_date=date(2030, 1, 15),
                shift_slot="DAY",
                scope_store_ids=[402, 401, 402],
            )

            self.assertEqual(sealed.encryption_key_version, "v1")
            self.assertEqual(len(sealed.source_fingerprint), 64)
            self.assertEqual(len(sealed.payload_hash), 64)
            self.assertNotIn("must not be retained", sealed.encrypted_payload)
            self.assertNotIn("+79990000000", sealed.encrypted_payload)
            self.assertNotIn("secret free-form value", sealed.encrypted_payload)
            self.assertEqual(sealed.external_shift_id, "shift-safe-42")
            self.assertEqual(sealed.external_shift_pk, 42)
            self.assertEqual(sealed.source_version, 3)
            self.assertEqual(sealed.business_date, date(2030, 1, 15))
            self.assertEqual(sealed.shift_slot, "DAY")

            opened = open_quickresto_source_snapshot(
                encrypted_payload=sealed.encrypted_payload,
                expected_payload_hash=sealed.payload_hash,
                expected_key_version=sealed.encryption_key_version,
            )
            self.assertNotIn("guestName", opened["shift"])
            self.assertNotIn("guest", opened["orders"][0])
            self.assertNotIn("comment", opened["orders"][0])
            self.assertNotIn("name", opened["orders"][0]["payments"][0]["paymentType"])
            self.assertNotIn("name", opened["orders"][0]["orderItemList"][0]["product"])
            self.assertEqual(opened["scope"]["storeIds"], [401, 402])

            with self.assertRaisesRegex(QuickRestoSnapshotError, "integrity"):
                open_quickresto_source_snapshot(
                    encrypted_payload=sealed.encrypted_payload,
                    expected_payload_hash="0" * 64,
                    expected_key_version="v1",
                )

    def test_identity_is_stable_while_payload_hash_tracks_source_changes(self):
        with patch.object(credentials.settings, "INTEGRATION_ENCRYPTION_KEY", "s" * 48):
            first = seal_quickresto_source_snapshot(shift=self._shift(version=3), orders=self._orders())
            changed = seal_quickresto_source_snapshot(
                shift=self._shift(version=4, totalCash=1200.25),
                orders=self._orders(amount=1200.25),
            )

        self.assertEqual(first.source_fingerprint, changed.source_fingerprint)
        self.assertNotEqual(first.payload_hash, changed.payload_hash)

    def test_snapshot_requires_a_stable_source_identity(self):
        with (
            patch.object(credentials.settings, "INTEGRATION_ENCRYPTION_KEY", "s" * 48),
            self.assertRaisesRegex(QuickRestoSnapshotError, "stable shift identity"),
        ):
            seal_quickresto_source_snapshot(shift={"status": "CLOSED"}, orders=[])


if __name__ == "__main__":
    unittest.main()

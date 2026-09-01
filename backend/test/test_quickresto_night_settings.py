from __future__ import annotations

from types import SimpleNamespace
import unittest

from fastapi import HTTPException

from app.routers.venue_quickresto import _serialize_connection, _validate_night_shift_split
from app.schemas.quickresto import QuickRestoConnectionUpsertIn


class QuickRestoNightSettingsTests(unittest.TestCase):
    def _payload(self, **overrides) -> QuickRestoConnectionUpsertIn:
        values = {
            "cloud": "fixture",
            "night_shift_split_enabled": True,
            "business_day_cutoff_hour": 6,
            "night_shift_start_hour": 22,
        }
        values.update(overrides)
        return QuickRestoConnectionUpsertIn(**values)

    def test_split_requires_venue_night_shift_mode(self):
        with self.assertRaisesRegex(HTTPException, "Night shift split requires"):
            _validate_night_shift_split(
                self._payload(),
                venue=SimpleNamespace(night_shifts_enabled=False),
            )

    def test_split_requires_non_overlapping_opening_windows(self):
        with self.assertRaisesRegex(HTTPException, "Night shift start hour"):
            _validate_night_shift_split(
                self._payload(business_day_cutoff_hour=22, night_shift_start_hour=22),
                venue=SimpleNamespace(night_shifts_enabled=True),
            )

    def test_disabled_split_keeps_settings_without_requiring_night_mode(self):
        _validate_night_shift_split(
            self._payload(
                night_shift_split_enabled=False,
                business_day_cutoff_hour=23,
                night_shift_start_hour=1,
            ),
            venue=SimpleNamespace(night_shifts_enabled=False),
        )

    def test_serialized_connection_exposes_effective_ui_context(self):
        connection = SimpleNamespace(
            id=7,
            venue_id=3,
            cloud="fixture",
            external_venue_id=501,
            external_venue_name="Тестовое заведение",
            external_venue_version=17,
            scope_status="READY",
            scope_generation=1,
            scope_confirmed_at=None,
            scope_confirmed_by_user_id=9,
            api_login_encrypted="encrypted",
            api_password_encrypted="encrypted",
            is_active=True,
            auto_sync_enabled=False,
            report_import_mode="CLOSED",
            business_day_cutoff_hour=6,
            night_shift_split_enabled=True,
            night_shift_start_hour=22,
            sync_from_date=None,
            last_sync_started_at=None,
            last_sync_completed_at=None,
            last_sync_status="NEVER",
            last_sync_error=None,
        )

        result = _serialize_connection(connection, venue_night_shifts_enabled=True)

        self.assertTrue(result["venue_night_shifts_enabled"])
        self.assertTrue(result["night_shift_split_enabled"])
        self.assertEqual(result["night_shift_start_hour"], 22)
        self.assertEqual(result["external_venue_version"], 17)
        self.assertEqual(result["scope_confirmed_by_user_id"], 9)


if __name__ == "__main__":
    unittest.main()

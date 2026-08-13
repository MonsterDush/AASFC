from __future__ import annotations

from datetime import date
from io import BytesIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from openpyxl import load_workbook

from app.routers import venue_revenue_exports
from app.services.xlsx_export import build_revenue_xlsx


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _AllResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ScalarsResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        if not self._responses:
            raise AssertionError("Unexpected execute() call without a prepared response")
        return self._responses.pop(0)


class RevenueTests(TestCase):
    def test_revenue_summary_queries_closed_reports_only(self):
        db = _FakeSession(
            responses=[
                _ScalarResult(1),
                _AllResult([SimpleNamespace(ref_id=10, amount=700)]),
                _ScalarsResult([SimpleNamespace(id=10, code="HOOKAH", title="Кальяны", venue_id=1)]),
            ]
        )
        user = SimpleNamespace(id=101, system_role="NONE")

        with (
            patch.object(venue_revenue_exports, "_require_active_member_or_admin", return_value=None),
            patch.object(venue_revenue_exports, "_require_report_viewer", return_value=None),
            patch.object(venue_revenue_exports, "_require_revenue_viewer", return_value=None),
        ):
            result = venue_revenue_exports.get_revenue_summary(
                venue_id=1,
                month="2026-03",
                date_from=None,
                date_to=None,
                mode="DEPARTMENTS",
                db=db,
                user=user,
            )

        self.assertEqual(result["closed_reports"], 1)
        self.assertEqual(result["total"], 700)
        self.assertEqual(result["rows"][0]["title"], "Кальяны")

        compiled_params = [stmt.compile().params for stmt in db.statements]
        params_with_closed = [params for params in compiled_params if "CLOSED" in params.values()]
        self.assertGreaterEqual(
            len(params_with_closed),
            2,
            "Revenue queries must explicitly filter DailyReport.status == CLOSED",
        )

    def test_revenue_daily_series_uses_selected_mode_and_fills_missing_dates(self):
        db = _FakeSession(
            responses=[
                _ScalarResult(2),
                _AllResult([SimpleNamespace(ref_id=10, amount=700)]),
                _AllResult([SimpleNamespace(id=10, code="HOOKAH", title="Кальяны", venue_id=1)]),
                _AllResult(
                    [
                        SimpleNamespace(date=date(2026, 3, 1), amount=400),
                        SimpleNamespace(date=date(2026, 3, 3), amount=300),
                    ]
                ),
            ]
        )
        user = SimpleNamespace(id=101, system_role="NONE")

        with (
            patch.object(venue_revenue_exports, "_require_active_member_or_admin", return_value=None),
            patch.object(venue_revenue_exports, "_require_report_viewer", return_value=None),
            patch.object(venue_revenue_exports, "_require_revenue_viewer", return_value=None),
        ):
            result = venue_revenue_exports.get_revenue_summary(
                venue_id=1,
                month="2026-03",
                date_from=None,
                date_to=None,
                mode="DEPARTMENTS",
                include_series=True,
                db=db,
                user=user,
            )

        self.assertEqual(len(result["daily_series"]), 31)
        self.assertEqual(result["daily_series"][0], {"date": date(2026, 3, 1), "amount": 400})
        self.assertEqual(result["daily_series"][1], {"date": date(2026, 3, 2), "amount": 0})
        self.assertEqual(result["daily_series"][2], {"date": date(2026, 3, 3), "amount": 300})
        self.assertEqual(sum(point["amount"] for point in result["daily_series"]), result["total"])

        daily_params = db.statements[-1].compile().params
        self.assertIn("DEPT", daily_params.values())
        self.assertIn("CLOSED", daily_params.values())

    def test_export_revenue_returns_attachment_headers(self):
        db = _FakeSession(
            responses=[
                _ScalarsResult([SimpleNamespace(id=1, name="Test Venue")]),
            ]
        )
        user = SimpleNamespace(id=101, system_role="NONE")
        summary = {
            "mode": "DEPARTMENTS",
            "month": "2026-03",
            "period_start": date(2026, 3, 1),
            "period_end": date(2026, 3, 31),
            "rows": [{"ref_id": 10, "code": "HOOKAH", "title": "Кальяны", "amount": 700}],
            "total": 700,
            "closed_reports": 1,
        }

        with (
            patch.object(venue_revenue_exports, "_compute_revenue_summary", return_value=summary),
            patch.object(venue_revenue_exports, "build_revenue_xlsx", return_value=b"xlsx-bytes"),
            patch.object(venue_revenue_exports, "_build_revenue_export_details", return_value=([], [])),
            patch.object(venue_revenue_exports, "_require_active_member_or_admin", return_value=None),
            patch.object(venue_revenue_exports, "_require_report_viewer", return_value=None),
            patch.object(venue_revenue_exports, "_require_revenue_exporter", return_value=None),
        ):
            response = venue_revenue_exports.export_revenue(
                venue_id=1,
                request=SimpleNamespace(base_url="https://example.test/"),
                month="2026-03",
                date_from=None,
                date_to=None,
                mode="DEPARTMENTS",
                fmt="xlsx",
                token=None,
                db=db,
                user=user,
            )

        self.assertEqual(
            response.media_type,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        content_disposition = response.headers.get("Content-Disposition", "")
        self.assertIn("attachment;", content_disposition)
        self.assertIn('filename="revenue_Test_Venue_2026-03_departments.xlsx"', content_disposition)
        self.assertIn("filename*=UTF-8''revenue_Test_Venue_2026-03_departments.xlsx", content_disposition)

    def test_revenue_xlsx_distinguishes_day_and_night_reports(self):
        report = SimpleNamespace(
            id=7,
            date=date(2026, 3, 12),
            shift_slot="NIGHT",
            status="CLOSED",
            revenue_total=1000,
            tips_total=100,
            comment=None,
            closed_at=None,
        )
        value = SimpleNamespace(
            report_id=7,
            kind="PAYMENT",
            ref_id=3,
            value_numeric=1000,
        )
        db = _FakeSession(
            responses=[
                _AllResult([(report, None)]),
                _ScalarsResult([value]),
                _AllResult([]),
                _AllResult([]),
                _AllResult([]),
            ]
        )

        report_rows, value_rows = venue_revenue_exports._build_revenue_export_details(
            db=db,
            venue_id=1,
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
        )
        workbook_bytes = build_revenue_xlsx(
            month="2026-03",
            mode="PAYMENTS",
            venue_name="Test Venue",
            rows=[],
            total=1000,
            closed_reports=1,
            report_rows=report_rows,
            value_rows=value_rows,
        )
        workbook = load_workbook(BytesIO(workbook_bytes), read_only=True)

        self.assertEqual(report_rows[0]["shift_slot"], "NIGHT")
        self.assertEqual(value_rows[0]["shift_slot"], "NIGHT")
        self.assertEqual(workbook["Отчёты"]["B3"].value, "Слот")
        self.assertEqual(workbook["Отчёты"]["B4"].value, "NIGHT")
        self.assertEqual(workbook["Значения"]["B3"].value, "Слот")
        self.assertEqual(workbook["Значения"]["B4"].value, "NIGHT")

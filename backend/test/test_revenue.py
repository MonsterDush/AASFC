from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from app.routers import venues


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
            raise AssertionError('Unexpected execute() call without a prepared response')
        return self._responses.pop(0)


class RevenueTests(TestCase):
    def test_revenue_summary_queries_closed_reports_only(self):
        db = _FakeSession(
            responses=[
                _ScalarResult(1),
                _AllResult([SimpleNamespace(ref_id=10, amount=700)]),
                _ScalarsResult([SimpleNamespace(id=10, code='HOOKAH', title='Кальяны', venue_id=1)]),
            ]
        )
        user = SimpleNamespace(id=101, system_role='NONE')

        with patch.object(venues, '_require_active_member_or_admin', return_value=None),              patch.object(venues, '_require_report_viewer', return_value=None),              patch.object(venues, '_can_view_revenue', return_value=True):
            result = venues.get_revenue_summary(
                venue_id=1,
                month='2026-03',
                date_from=None,
                date_to=None,
                mode='DEPARTMENTS',
                db=db,
                user=user,
            )

        self.assertEqual(result['closed_reports'], 1)
        self.assertEqual(result['total'], 700)
        self.assertEqual(result['rows'][0]['title'], 'Кальяны')

        compiled_params = [stmt.compile().params for stmt in db.statements]
        params_with_closed = [params for params in compiled_params if 'CLOSED' in params.values()]
        self.assertGreaterEqual(
            len(params_with_closed),
            2,
            'Revenue queries must explicitly filter DailyReport.status == CLOSED',
        )

    def test_export_revenue_returns_attachment_headers(self):
        db = _FakeSession(
            responses=[
                _ScalarsResult([SimpleNamespace(id=1, name='Test Venue')]),
            ]
        )
        user = SimpleNamespace(id=101, system_role='NONE')
        summary = {
            'mode': 'DEPARTMENTS',
            'month': '2026-03',
            'period_start': date(2026, 3, 1),
            'period_end': date(2026, 3, 31),
            'rows': [{'ref_id': 10, 'code': 'HOOKAH', 'title': 'Кальяны', 'amount': 700}],
            'total': 700,
            'closed_reports': 1,
        }

        with patch.object(venues, 'get_revenue_summary', return_value=summary),              patch.object(venues, 'build_revenue_xlsx', return_value=b'xlsx-bytes'):
            response = venues.export_revenue(
                venue_id=1,
                month='2026-03',
                date_from=None,
                date_to=None,
                mode='DEPARTMENTS',
                fmt='xlsx',
                db=db,
                user=user,
            )

        self.assertEqual(
            response.media_type,
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        content_disposition = response.headers.get('Content-Disposition', '')
        self.assertIn('attachment;', content_disposition)
        self.assertIn('filename="revenue_Test_Venue_2026-03_departments.xlsx"', content_disposition)
        self.assertIn("filename*=UTF-8''revenue_Test_Venue_2026-03_departments.xlsx", content_disposition)

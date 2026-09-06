from datetime import date, time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from app.routers import me, venue_reports, venue_shifts
from app.services.tips import (
    build_equal_tip_allocations,
    build_weighted_by_position_tip_allocations,
    parse_position_percent_map,
)


class TipCalculationTests(TestCase):
    def test_parse_position_percent_map_normalizes_and_clamps_values(self):
        result = parse_position_percent_map(
            {
                "rows": [
                    {"title": "  Старший   Бармен ", "percent": 25},
                    {"title": "Официант", "percent": 140},
                    {"title": "Хостес", "percent": -15},
                    {"title": "", "percent": 50},
                ]
            }
        )

        self.assertEqual(
            result,
            {
                "старший бармен": {
                    "title": "Старший Бармен",
                    "percent": 25,
                },
                "официант": {"title": "Официант", "percent": 100},
                "хостес": {"title": "Хостес", "percent": 0},
            },
        )

    def test_equal_split_distributes_rounding_remainder_deterministically(self):
        allocations = build_equal_tip_allocations(
            report_id=7,
            tips_total=100,
            assigned_user_ids=[3, 1, 2],
        )

        self.assertEqual(
            [(item.user_id, item.amount) for item in allocations],
            [(1, 34), (2, 33), (3, 33)],
        )
        self.assertEqual(sum(item.amount for item in allocations), 100)

    def test_weighted_split_uses_position_share_and_fallback_pool(self):
        allocations = build_weighted_by_position_tip_allocations(
            report_id=7,
            tips_total=1001,
            assigned_members=[
                (1, "Бармен"),
                (2, "Официант"),
            ],
            tips_weights={"rows": [{"title": "Бармен", "percent": 30}]},
        )

        self.assertEqual(
            [(item.user_id, item.amount) for item in allocations],
            [(1, 300), (2, 701)],
        )
        self.assertEqual(sum(item.amount for item in allocations), 1001)

    def test_weighted_split_distributes_unallocated_part_between_all_members(self):
        allocations = build_weighted_by_position_tip_allocations(
            report_id=7,
            tips_total=1000,
            assigned_members=[
                (1, "Бармен"),
                (2, "Официант"),
            ],
            tips_weights={
                "rows": [
                    {"title": "Бармен", "percent": 30},
                    {"title": "Официант", "percent": 20},
                ]
            },
        )

        self.assertEqual(
            [(item.user_id, item.amount) for item in allocations],
            [(1, 550), (2, 450)],
        )

    def test_weighted_split_deduplicates_user_assignments(self):
        allocations = build_weighted_by_position_tip_allocations(
            report_id=7,
            tips_total=1000,
            assigned_members=[
                (1, "Бармен"),
                (1, "Официант"),
                (2, "Официант"),
            ],
            tips_weights={"rows": [{"title": "Бармен", "percent": 30}]},
        )

        self.assertEqual(
            [(item.user_id, item.amount) for item in allocations],
            [(1, 300), (2, 700)],
        )

    def test_weighted_split_rejects_actual_assigned_sum_over_100_percent(self):
        with self.assertRaisesRegex(
            ValueError,
            "Сумма долей чаевых для назначенных сотрудников превышает 100%",
        ):
            build_weighted_by_position_tip_allocations(
                report_id=7,
                tips_total=1000,
                assigned_members=[
                    (1, "Бармен"),
                    (2, "Бармен"),
                ],
                tips_weights={"rows": [{"title": "Бармен", "percent": 60}]},
            )


class TipAllocationIntegrationTests(TestCase):
    def test_rebuild_uses_only_members_from_report_shift_slot(self):
        db = Mock()
        report = SimpleNamespace(
            id=7,
            venue_id=5,
            date=date(2026, 7, 29),
            shift_slot="NIGHT",
            tips_total=1000,
        )
        venue = SimpleNamespace(
            tips_enabled=True,
            tips_split_mode="WEIGHTED_BY_POSITION",
            tips_weights={"rows": [{"title": "Бармен", "percent": 30}]},
        )

        with patch.object(
            venue_reports,
            "_load_assigned_members_for_report_date",
            return_value=[(1, "Бармен"), (2, "Официант")],
        ) as load_members:
            allocations = venue_reports._rebuild_report_tip_allocations(
                db,
                venue=venue,
                report=report,
            )

        load_members.assert_called_once_with(
            db,
            venue_id=5,
            report_date=date(2026, 7, 29),
            shift_slot="NIGHT",
        )
        self.assertEqual(
            [(item.user_id, item.amount) for item in allocations],
            [(1, 300), (2, 700)],
        )

    def test_assignment_loader_filters_by_shift_slot(self):
        db = SimpleNamespace(
            execute=Mock(
                return_value=SimpleNamespace(
                    all=lambda: [(1, "Бармен")],
                )
            )
        )

        result = venue_reports._load_assigned_members_for_report_date(
            db,
            venue_id=5,
            report_date=date(2026, 7, 29),
            shift_slot="NIGHT",
        )

        statement = db.execute.call_args.args[0]
        compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("shifts.shift_slot", compiled)
        self.assertIn("'NIGHT'", compiled)
        self.assertEqual(result, [(1, "Бармен")])

    def test_shift_list_uses_slot_report_and_stored_tip_allocation(self):
        report_date = date(2026, 7, 29)
        shifts = [
            SimpleNamespace(
                id=10,
                date=report_date,
                interval_id=1,
                shift_slot="DAY",
                is_active=True,
            ),
            SimpleNamespace(
                id=11,
                date=report_date,
                interval_id=1,
                shift_slot="NIGHT",
                is_active=True,
            ),
        ]
        reports = [
            SimpleNamespace(
                id=20,
                date=report_date,
                shift_slot="DAY",
                status="CLOSED",
                revenue_total=10000,
                tips_total=1000,
            ),
            SimpleNamespace(
                id=21,
                date=report_date,
                shift_slot="NIGHT",
                status="CLOSED",
                revenue_total=20000,
                tips_total=2000,
            ),
        ]
        intervals = [
            SimpleNamespace(
                id=1,
                title="Полная смена",
                start_time=time(10, 0),
                end_time=time(22, 0),
                position_id=None,
            )
        ]
        assignments = [
            SimpleNamespace(
                shift_id=10,
                member_user_id=9,
                venue_position_id=1,
                title="Бармен",
                tg_username="staff",
                full_name="Сотрудник",
                short_name="Сотр.",
            ),
            SimpleNamespace(
                shift_id=11,
                member_user_id=9,
                venue_position_id=1,
                title="Бармен",
                tg_username="staff",
                full_name="Сотрудник",
                short_name="Сотр.",
            ),
        ]
        my_assignments = [
            SimpleNamespace(shift_id=10, rate=3000, percent=5),
            SimpleNamespace(shift_id=11, rate=4000, percent=10),
        ]

        def scalar_result(items):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: items))

        db = SimpleNamespace(
            execute=Mock(
                side_effect=[
                    scalar_result(shifts),
                    scalar_result(reports),
                    scalar_result(intervals),
                    SimpleNamespace(all=lambda: assignments),
                    SimpleNamespace(all=lambda: my_assignments),
                    SimpleNamespace(
                        all=lambda: [
                            SimpleNamespace(report_id=20, amount=350),
                            SimpleNamespace(report_id=21, amount=1250),
                        ]
                    ),
                ]
            )
        )
        user = SimpleNamespace(id=9)

        with (
            patch.object(
                venue_shifts,
                "_require_active_member_or_admin",
                return_value=SimpleNamespace(),
            ),
            patch.object(
                venue_shifts,
                "_has_revenue_view_access",
                return_value=False,
            ),
            patch.object(venue_shifts, "load_owner_notes", return_value={}),
            patch.object(venue_shifts, "load_member_display_names", return_value={}),
            patch.object(
                venue_shifts,
                "interval_scope_payloads",
                return_value={interval.id: {"position_ids": [], "position_titles": []} for interval in intervals},
            ),
        ):
            result = venue_shifts.list_shifts(
                5,
                None,
                None,
                None,
                None,
                "all",
                None,
                db,
                user,
            )

        by_slot = {item["shift_slot"]: item for item in result}
        self.assertEqual(by_slot["DAY"]["my_tips_share"], 350)
        self.assertEqual(by_slot["NIGHT"]["my_tips_share"], 1250)
        self.assertEqual(by_slot["DAY"]["my_salary"], 3500)
        self.assertEqual(by_slot["NIGHT"]["my_salary"], 6000)
        self.assertTrue(by_slot["DAY"]["report_closed"])
        self.assertTrue(by_slot["NIGHT"]["report_closed"])

    def test_my_shifts_exposes_stored_weighted_tip_share(self):
        report_date = date(2026, 7, 29)
        shift_rows = [
            SimpleNamespace(
                shift_id=10,
                shift_date=report_date,
                shift_slot="DAY",
                venue_id=5,
                venue_name="Тест",
                interval_id=1,
                interval_title="День",
                start_time=time(10, 0),
                end_time=time(22, 0),
                rate=3000,
                percent=5,
            ),
            SimpleNamespace(
                shift_id=11,
                shift_date=report_date,
                shift_slot="NIGHT",
                venue_id=5,
                venue_name="Тест",
                interval_id=1,
                interval_title="Ночь",
                start_time=time(22, 0),
                end_time=time(6, 0),
                rate=4000,
                percent=10,
            ),
        ]
        reports = [
            SimpleNamespace(
                id=20,
                venue_id=5,
                date=report_date,
                shift_slot="DAY",
                status="CLOSED",
                revenue_total=10000,
            ),
            SimpleNamespace(
                id=21,
                venue_id=5,
                date=report_date,
                shift_slot="NIGHT",
                status="CLOSED",
                revenue_total=20000,
            ),
        ]

        def scalar_result(items):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: items))

        db = SimpleNamespace(
            execute=Mock(
                side_effect=[
                    SimpleNamespace(all=lambda: shift_rows),
                    scalar_result(reports),
                    SimpleNamespace(
                        all=lambda: [
                            SimpleNamespace(report_id=20, amount=350),
                            SimpleNamespace(report_id=21, amount=1250),
                        ]
                    ),
                ]
            )
        )
        user = SimpleNamespace(id=9)

        with patch.object(
            me,
            "sanitize_financial_payload_for_user",
            side_effect=lambda _user, payload: payload,
        ):
            result = me.my_shifts_across_venues(
                "2026-07",
                None,
                None,
                5,
                db,
                user,
            )

        by_slot = {item["shift_slot"]: item for item in result}
        self.assertEqual(by_slot["DAY"]["my_tips_share"], 350)
        self.assertEqual(by_slot["NIGHT"]["my_tips_share"], 1250)

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, time

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.account_merge import merge_user_accounts
from app.core.db import Base
from app.models import (
    AuthIdentity,
    DailyReport,
    DailyReportTipAllocation,
    NotificationDeliveryLog,
    PayProfile,
    PayProfileAssignment,
    PayrollLine,
    PayrollRun,
    Shift,
    ShiftAssignment,
    ShiftAvailability,
    ShiftInterval,
    ShiftSwapRequest,
    User,
    Venue,
    VenueMember,
    VenuePosition,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class AccountMergeConflictTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_profile_and_venue_member_conflicts_keep_strongest_information(self):
        with Session(self.engine) as db:
            target = User(id=1, short_name="Target", preferred_locale=None)
            source = User(
                id=2,
                tg_user_id=2002,
                tg_username="source_tg",
                short_name="Source",
                preferred_locale="ru",
                notify_shifts=False,
                notify_salary=False,
                shift_reminder_lead_time_hours=7,
                notification_detail_level="compact",
            )
            venue = Venue(id=5, name="Merge test")
            target_member = VenueMember(
                id=11,
                venue_id=venue.id,
                user_id=target.id,
                venue_role="STAFF",
                is_active=True,
                owner_note="  Основная заметка  ",
            )
            source_member = VenueMember(
                id=12,
                venue_id=venue.id,
                user_id=source.id,
                venue_role="MANAGER",
                is_active=True,
                owner_note="  Дополнение  ",
            )
            telegram_identity = AuthIdentity(
                id=13,
                user_id=source.id,
                provider="TELEGRAM",
                provider_user_id=str(source.tg_user_id),
                is_verified=True,
            )
            db.add_all([target, source, venue, target_member, source_member, telegram_identity])
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            surviving_user = db.get(User, target.id)
            surviving_member = db.execute(select(VenueMember)).scalar_one()

            self.assertEqual(surviving_user.preferred_locale, "ru")
            self.assertEqual(surviving_user.tg_user_id, 2002)
            self.assertEqual(surviving_user.tg_username, "source_tg")
            self.assertFalse(surviving_user.notify_shifts)
            self.assertFalse(surviving_user.notify_salary)
            self.assertEqual(surviving_user.shift_reminder_lead_time_hours, 7)
            self.assertEqual(surviving_user.notification_detail_level, "compact")
            surviving_identity = db.execute(select(AuthIdentity)).scalar_one()
            self.assertEqual(surviving_identity.user_id, target.id)
            self.assertEqual(surviving_identity.provider_user_id, "2002")
            self.assertEqual(surviving_member.id, target_member.id)
            self.assertEqual(surviving_member.user_id, target.id)
            self.assertEqual(surviving_member.venue_role, "MANAGER")
            self.assertEqual(surviving_member.owner_note, "Основная заметка · Дополнение")

    def test_duplicate_shift_assignment_preserves_graph_and_latest_reminder(self):
        older_reminder = datetime(2026, 8, 10, 8, 0)
        newer_reminder = datetime(2026, 8, 10, 9, 0)

        with Session(self.engine) as db:
            target = User(id=1, short_name="Target")
            source = User(id=2, short_name="Source")
            venue = Venue(id=5, name="Merge test")
            target_position = VenuePosition(
                id=101,
                venue_id=venue.id,
                member_user_id=target.id,
                title="Официант",
                rate=100,
                percent=0,
                is_active=True,
            )
            source_position = VenuePosition(
                id=102,
                venue_id=venue.id,
                member_user_id=source.id,
                title="Бармен",
                rate=200,
                percent=0,
                is_active=True,
            )
            interval = ShiftInterval(
                id=201,
                venue_id=venue.id,
                title="День",
                start_time=time(10, 0),
                end_time=time(18, 0),
                is_active=True,
            )
            shift = Shift(
                id=202,
                venue_id=venue.id,
                date=date(2026, 8, 11),
                interval_id=interval.id,
                shift_slot="DAY",
                is_active=True,
            )
            target_assignment = ShiftAssignment(
                id=301,
                shift_id=shift.id,
                member_user_id=target.id,
                venue_position_id=target_position.id,
                reminder_sent_at=older_reminder,
            )
            source_assignment = ShiftAssignment(
                id=302,
                shift_id=shift.id,
                member_user_id=source.id,
                venue_position_id=source_position.id,
                reminder_sent_at=newer_reminder,
            )
            delivery_log = NotificationDeliveryLog(
                id=401,
                notification_type="SHIFT_REMINDER",
                status="SENT",
                user_id=source.id,
                venue_id=venue.id,
                shift_id=shift.id,
                shift_assignment_id=source_assignment.id,
            )
            target_request = ShiftSwapRequest(
                id=501,
                venue_id=venue.id,
                shift_id=shift.id,
                assignment_id=target_assignment.id,
                requester_user_id=target.id,
                status="OPEN",
                comment="Target request",
            )
            source_request = ShiftSwapRequest(
                id=502,
                venue_id=venue.id,
                shift_id=shift.id,
                assignment_id=source_assignment.id,
                requester_user_id=source.id,
                status="OPEN",
                comment="Source request",
            )
            historical_request = ShiftSwapRequest(
                id=503,
                venue_id=venue.id,
                shift_id=shift.id,
                assignment_id=source_assignment.id,
                requester_user_id=target.id,
                replacement_user_id=source.id,
                replacement_position_id=source_position.id,
                status="APPROVED",
                comment="Historical request",
            )
            db.add_all(
                [
                    target,
                    source,
                    venue,
                    target_position,
                    source_position,
                    interval,
                    shift,
                    target_assignment,
                    source_assignment,
                ]
            )
            db.flush()
            db.add_all([delivery_log, target_request, source_request, historical_request])
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            assignment = db.execute(select(ShiftAssignment)).scalar_one()
            delivery = db.execute(select(NotificationDeliveryLog)).scalar_one()
            requests = {
                row.id: row for row in db.execute(select(ShiftSwapRequest).order_by(ShiftSwapRequest.id)).scalars()
            }

            self.assertEqual(assignment.id, target_assignment.id)
            self.assertEqual(assignment.member_user_id, target.id)
            self.assertEqual(assignment.venue_position_id, target_position.id)
            self.assertEqual(assignment.reminder_sent_at, newer_reminder)
            self.assertEqual(delivery.user_id, target.id)
            self.assertEqual(delivery.shift_assignment_id, target_assignment.id)
            self.assertEqual(requests[target_request.id].assignment_id, target_assignment.id)
            self.assertEqual(requests[target_request.id].status, "OPEN")
            self.assertEqual(requests[source_request.id].assignment_id, target_assignment.id)
            self.assertEqual(requests[source_request.id].requester_user_id, target.id)
            self.assertEqual(requests[source_request.id].status, "CANCELLED")
            self.assertIn("объединении аккаунтов", requests[source_request.id].manager_comment)
            self.assertEqual(requests[historical_request.id].assignment_id, target_assignment.id)
            self.assertEqual(requests[historical_request.id].requester_user_id, target.id)
            self.assertIsNone(requests[historical_request.id].replacement_user_id)
            self.assertIsNone(requests[historical_request.id].replacement_position_id)
            self.assertEqual(requests[historical_request.id].status, "APPROVED")

    def test_availability_conflicts_use_newest_complete_value_and_target_on_tie(self):
        older = datetime(2026, 8, 1, 10, 0)
        newer = datetime(2026, 8, 1, 11, 0)
        tied = datetime(2026, 8, 2, 10, 0)

        with Session(self.engine) as db:
            target = User(id=1, short_name="Target")
            source = User(id=2, short_name="Source")
            venue = Venue(id=5, name="Merge test")
            rows = [
                ShiftAvailability(
                    id=101,
                    venue_id=venue.id,
                    member_user_id=target.id,
                    date=date(2026, 8, 10),
                    shift_slot="DAY",
                    status="AVAILABLE",
                    comment="target older",
                    created_at=older,
                    updated_at=older,
                ),
                ShiftAvailability(
                    id=102,
                    venue_id=venue.id,
                    member_user_id=source.id,
                    date=date(2026, 8, 10),
                    shift_slot="DAY",
                    status="UNAVAILABLE",
                    comment="source newer",
                    created_at=older,
                    updated_at=newer,
                ),
                ShiftAvailability(
                    id=103,
                    venue_id=venue.id,
                    member_user_id=target.id,
                    date=date(2026, 8, 11),
                    shift_slot="NIGHT",
                    status="AVAILABLE",
                    comment="target tie",
                    created_at=tied,
                    updated_at=tied,
                ),
                ShiftAvailability(
                    id=104,
                    venue_id=venue.id,
                    member_user_id=source.id,
                    date=date(2026, 8, 11),
                    shift_slot="NIGHT",
                    status="UNAVAILABLE",
                    comment="source tie",
                    created_at=tied,
                    updated_at=tied,
                ),
            ]
            db.add_all([target, source, venue, *rows])
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            availabilities = {
                (row.date, row.shift_slot): row
                for row in db.execute(select(ShiftAvailability).order_by(ShiftAvailability.id)).scalars()
            }
            newer_result = availabilities[(date(2026, 8, 10), "DAY")]
            tie_result = availabilities[(date(2026, 8, 11), "NIGHT")]

            self.assertEqual(len(availabilities), 2)
            self.assertEqual(newer_result.status, "UNAVAILABLE")
            self.assertEqual(newer_result.comment, "source newer")
            self.assertEqual(newer_result.updated_at, newer)
            self.assertEqual(tie_result.status, "AVAILABLE")
            self.assertEqual(tie_result.comment, "target tie")
            self.assertEqual(tie_result.updated_at, tied)

    def test_pay_profile_and_tip_conflicts_preserve_history_and_totals(self):
        with Session(self.engine) as db:
            target = User(id=1, short_name="Target")
            source = User(id=2, short_name="Source")
            venue = Venue(id=5, name="Merge test")
            profile = PayProfile(id=11, venue_id=venue.id, title="Основной", is_active=True)
            target_assignment = PayProfileAssignment(
                id=21,
                venue_id=venue.id,
                pay_profile_id=profile.id,
                member_user_id=target.id,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                is_active=True,
            )
            exact_source_assignment = PayProfileAssignment(
                id=22,
                venue_id=venue.id,
                pay_profile_id=profile.id,
                member_user_id=source.id,
                start_date=date(2026, 1, 1),
                end_date=date(2026, 1, 31),
                is_active=True,
            )
            overlapping_source_assignment = PayProfileAssignment(
                id=23,
                venue_id=venue.id,
                pay_profile_id=profile.id,
                member_user_id=source.id,
                start_date=date(2026, 1, 15),
                end_date=date(2026, 2, 15),
                is_active=True,
            )
            report = DailyReport(
                id=31,
                venue_id=venue.id,
                date=date(2026, 1, 20),
                shift_slot="DAY",
                tips_total=350,
                status="CLOSED",
                created_by_user_id=target.id,
            )
            target_tip = DailyReportTipAllocation(
                id=41,
                report_id=report.id,
                user_id=target.id,
                amount=100,
                split_mode="EQUAL",
                meta_json={"source": "target"},
            )
            source_tip = DailyReportTipAllocation(
                id=42,
                report_id=report.id,
                user_id=source.id,
                amount=250,
                split_mode="WEIGHTED_BY_POSITION",
                meta_json={"source": "absorbed"},
            )
            db.add_all(
                [
                    target,
                    source,
                    venue,
                    profile,
                    target_assignment,
                    exact_source_assignment,
                    overlapping_source_assignment,
                    report,
                    target_tip,
                    source_tip,
                ]
            )
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            assignments = (
                db.execute(
                    select(PayProfileAssignment).order_by(PayProfileAssignment.start_date, PayProfileAssignment.id)
                )
                .scalars()
                .all()
            )
            allocation = db.execute(select(DailyReportTipAllocation)).scalar_one()

            self.assertEqual([row.id for row in assignments], [target_assignment.id, overlapping_source_assignment.id])
            self.assertTrue(all(row.member_user_id == target.id for row in assignments))
            self.assertEqual(
                [(row.start_date, row.end_date) for row in assignments],
                [
                    (date(2026, 1, 1), date(2026, 1, 31)),
                    (date(2026, 1, 15), date(2026, 2, 15)),
                ],
            )
            self.assertEqual(allocation.id, target_tip.id)
            self.assertEqual(allocation.user_id, target.id)
            self.assertEqual(allocation.amount, 350)
            self.assertEqual(allocation.split_mode, "WEIGHTED_BY_POSITION")
            merge_allocations = allocation.meta_json["account_merge_allocations"]
            self.assertEqual([item["amount"] for item in merge_allocations], [100, 250])
            self.assertEqual(
                [item["meta"] for item in merge_allocations],
                [{"source": "target"}, {"source": "absorbed"}],
            )

    def test_duplicate_payroll_lines_merge_structured_breakdown_and_run_totals(self):
        target_breakdown = {
            "member_user_id": 1,
            "member_name": "Target",
            "pay_profile_id": 11,
            "pay_profile_title": "Дневной",
            "pay_profile_ids": [11],
            "pay_profile_titles": ["Дневной"],
            "position_profiles": [
                {
                    "pay_profile_id": 11,
                    "pay_profile_title": "Дневной",
                    "position_ids": [201],
                    "amount_minor": 100,
                }
            ],
            "metrics": {
                "minutes_total": 60,
                "hours_total": 1.0,
                "shifts_count": 1,
                "worked_dates_count": 1,
                "worked_dates": ["2026-08-01"],
            },
            "revenue_metrics": {"total_revenue_minor": 50_000, "target_snapshot": 1},
            "kpi_metrics": {"1": 10, "target_snapshot": 5},
            "components": [{"component_id": 101, "amount_minor": 100}],
            "shift_allocations": [{"shift_id": 1001, "shift_date": "2026-08-01", "minutes": 480, "amount_minor": 100}],
        }
        source_breakdown = {
            "member_user_id": 2,
            "member_name": "Source",
            "pay_profile_id": 12,
            "pay_profile_title": "Ночной",
            "pay_profile_ids": [12],
            "pay_profile_titles": ["Ночной"],
            "position_profiles": [
                {
                    "pay_profile_id": 12,
                    "pay_profile_title": "Ночной",
                    "position_ids": [202],
                    "amount_minor": 250,
                }
            ],
            "metrics": {
                "minutes_total": 120,
                "hours_total": 2.0,
                "shifts_count": 2,
                "worked_dates_count": 2,
                "worked_dates": ["2026-08-01", "2026-08-02"],
            },
            "revenue_metrics": {"total_revenue_minor": 75_000, "source_snapshot": 2},
            "kpi_metrics": {"1": 99, "2": 20},
            "components": [{"component_id": 102, "amount_minor": 250}],
            "shift_allocations": [
                {"shift_id": 1001, "shift_date": "2026-08-01", "minutes": 600, "amount_minor": 50},
                {"shift_id": 1002, "shift_date": "2026-08-02", "minutes": 360, "amount_minor": 200},
            ],
        }

        with Session(self.engine) as db:
            target = User(id=1, short_name="Target")
            source = User(id=2, short_name="Source")
            other = User(id=3, short_name="Other")
            venue = Venue(id=5, name="Merge test")
            target_profile = PayProfile(id=11, venue_id=venue.id, title="Дневной", is_active=True)
            source_profile = PayProfile(id=12, venue_id=venue.id, title="Ночной", is_active=True)
            payroll_run = PayrollRun(
                id=21,
                venue_id=venue.id,
                period_month=date(2026, 8, 1),
                calculated_by_user_id=source.id,
                total_amount_minor=999,
                lines_count=99,
            )
            target_line = PayrollLine(
                id=31,
                payroll_run_id=payroll_run.id,
                venue_id=venue.id,
                member_user_id=target.id,
                pay_profile_id=target_profile.id,
                amount_minor=100,
                breakdown_json=json.dumps(target_breakdown, ensure_ascii=False),
            )
            source_line = PayrollLine(
                id=32,
                payroll_run_id=payroll_run.id,
                venue_id=venue.id,
                member_user_id=source.id,
                pay_profile_id=source_profile.id,
                amount_minor=250,
                breakdown_json=json.dumps(source_breakdown, ensure_ascii=False),
            )
            other_line = PayrollLine(
                id=33,
                payroll_run_id=payroll_run.id,
                venue_id=venue.id,
                member_user_id=other.id,
                pay_profile_id=target_profile.id,
                amount_minor=50,
                breakdown_json=json.dumps({"member_user_id": other.id, "components": []}),
            )
            db.add_all(
                [
                    target,
                    source,
                    other,
                    venue,
                    target_profile,
                    source_profile,
                    payroll_run,
                    target_line,
                    source_line,
                    other_line,
                ]
            )
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            surviving_line = db.get(PayrollLine, target_line.id)
            surviving_run = db.get(PayrollRun, payroll_run.id)
            breakdown = json.loads(surviving_line.breakdown_json)
            allocations = {int(row["shift_id"]): row for row in breakdown["shift_allocations"]}

            self.assertIsNone(db.get(PayrollLine, source_line.id))
            self.assertEqual(surviving_line.member_user_id, target.id)
            self.assertEqual(surviving_line.amount_minor, 350)
            self.assertIsNone(surviving_line.pay_profile_id)
            self.assertEqual(breakdown["member_user_id"], target.id)
            self.assertIsNone(breakdown["pay_profile_id"])
            self.assertEqual(breakdown["pay_profile_ids"], [target_profile.id, source_profile.id])
            self.assertEqual(breakdown["pay_profile_titles"], [target_profile.title, source_profile.title])
            self.assertEqual(
                [row["pay_profile_id"] for row in breakdown["position_profiles"]],
                [target_profile.id, source_profile.id],
            )
            self.assertEqual(breakdown["metrics"]["minutes_total"], 180)
            self.assertEqual(breakdown["metrics"]["hours_total"], 3.0)
            self.assertEqual(breakdown["metrics"]["shifts_count"], 3)
            self.assertEqual(breakdown["metrics"]["worked_dates_count"], 2)
            self.assertEqual(breakdown["metrics"]["worked_dates"], ["2026-08-01", "2026-08-02"])
            self.assertEqual([row["component_id"] for row in breakdown["components"]], [101, 102])
            components = {int(row["component_id"]): row for row in breakdown["components"]}
            self.assertEqual(components[101]["account_merge_worked_dates"], ["2026-08-01"])
            self.assertEqual(
                components[102]["account_merge_worked_dates"],
                ["2026-08-01", "2026-08-02"],
            )
            self.assertEqual(
                sum(int(row["amount_minor"]) for row in breakdown["components"]),
                surviving_line.amount_minor,
            )
            self.assertEqual(
                breakdown["revenue_metrics"],
                {"total_revenue_minor": 50_000, "target_snapshot": 1, "source_snapshot": 2},
            )
            self.assertEqual(
                breakdown["kpi_metrics"],
                {"1": 10, "target_snapshot": 5, "2": 20},
            )
            self.assertEqual(set(allocations), {1001, 1002})
            self.assertEqual(allocations[1001]["amount_minor"], 150)
            self.assertEqual(allocations[1001]["minutes"], 600)
            self.assertEqual(allocations[1001]["date"], "2026-08-01")
            self.assertEqual(allocations[1002]["amount_minor"], 200)
            self.assertEqual(allocations[1002]["date"], "2026-08-02")
            self.assertEqual(
                sum(int(row["amount_minor"]) for row in breakdown["shift_allocations"]),
                surviving_line.amount_minor,
            )
            self.assertEqual(surviving_run.calculated_by_user_id, target.id)
            self.assertEqual(surviving_run.lines_count, 2)
            self.assertEqual(surviving_run.total_amount_minor, 400)

    def test_source_only_payroll_line_repairs_invalid_breakdown(self):
        with Session(self.engine) as db:
            target = User(id=1, short_name="Target")
            source = User(id=2, short_name="Source")
            venue = Venue(id=5, name="Merge test")
            profile = PayProfile(id=11, venue_id=venue.id, title="Основной", is_active=True)
            payroll_run = PayrollRun(
                id=21,
                venue_id=venue.id,
                period_month=date(2026, 9, 1),
                calculated_by_user_id=source.id,
                total_amount_minor=1,
                lines_count=99,
            )
            source_line = PayrollLine(
                id=31,
                payroll_run_id=payroll_run.id,
                venue_id=venue.id,
                member_user_id=source.id,
                pay_profile_id=profile.id,
                amount_minor=777,
                breakdown_json="{damaged payroll json",
            )
            db.add_all([target, source, venue, profile, payroll_run, source_line])
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            surviving_line = db.get(PayrollLine, source_line.id)
            surviving_run = db.get(PayrollRun, payroll_run.id)
            breakdown = json.loads(surviving_line.breakdown_json)
            remainder = [
                component
                for component in breakdown["components"]
                if component.get("component_type") == "ACCOUNT_MERGE_REMAINDER"
            ]

            self.assertEqual(surviving_line.member_user_id, target.id)
            self.assertEqual(surviving_line.amount_minor, 777)
            self.assertEqual(surviving_line.pay_profile_id, profile.id)
            self.assertEqual(breakdown["member_user_id"], target.id)
            self.assertEqual(len(remainder), 1)
            self.assertEqual(remainder[0]["amount_minor"], surviving_line.amount_minor)
            self.assertEqual(breakdown["shift_allocations"], [])
            self.assertEqual(surviving_run.calculated_by_user_id, target.id)
            self.assertEqual(surviving_run.lines_count, 1)
            self.assertEqual(surviving_run.total_amount_minor, surviving_line.amount_minor)

    def test_payroll_merge_repairs_component_overage_without_trusting_stale_profile_fk(self):
        stale_profile_id = 999
        with Session(self.engine) as db:
            target = User(id=1, short_name="Target")
            source = User(id=2, short_name="Source")
            venue = Venue(id=5, name="Merge test")
            profile = PayProfile(id=11, venue_id=venue.id, title="Основной", is_active=True)
            payroll_run = PayrollRun(
                id=21,
                venue_id=venue.id,
                period_month=date(2026, 10, 1),
                calculated_by_user_id=source.id,
                total_amount_minor=700,
                lines_count=1,
            )
            source_line = PayrollLine(
                id=31,
                payroll_run_id=payroll_run.id,
                venue_id=venue.id,
                member_user_id=source.id,
                pay_profile_id=profile.id,
                amount_minor=700,
                breakdown_json=json.dumps(
                    {
                        "member_user_id": source.id,
                        "pay_profile_id": stale_profile_id,
                        "pay_profile_ids": [stale_profile_id],
                        "pay_profile_title": "Удалённый профиль",
                        "pay_profile_titles": ["Удалённый профиль"],
                        "metrics": {
                            "worked_dates": ["2026-10-03"],
                            "minutes_total": 60,
                            "shifts_count": 1,
                        },
                        "components": [
                            {
                                "component_id": 501,
                                "component_type": "SALARY_PER_SHIFT",
                                "amount_minor": 900,
                            }
                        ],
                        "shift_allocations": [],
                    },
                    ensure_ascii=False,
                ),
            )
            db.add_all([target, source, venue, profile, payroll_run, source_line])
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            surviving_line = db.get(PayrollLine, source_line.id)
            breakdown = json.loads(surviving_line.breakdown_json)

            self.assertEqual(surviving_line.pay_profile_id, profile.id)
            self.assertEqual(breakdown["pay_profile_ids"], [profile.id, stale_profile_id])
            self.assertIsNone(breakdown["pay_profile_id"])
            self.assertEqual(len(breakdown["components"]), 1)
            repair_component = breakdown["components"][0]
            self.assertEqual(repair_component["component_type"], "ACCOUNT_MERGE_REPAIR")
            self.assertEqual(repair_component["amount_minor"], surviving_line.amount_minor)
            self.assertEqual(repair_component["account_merge_worked_dates"], ["2026-10-03"])
            repairs = breakdown["account_merge_component_repairs"]
            self.assertEqual(len(repairs), 1)
            self.assertEqual(repairs[0]["components_amount_minor"], 900)
            self.assertEqual(repairs[0]["components"][0]["component_id"], 501)


if __name__ == "__main__":
    unittest.main()

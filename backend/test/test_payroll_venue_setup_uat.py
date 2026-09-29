from __future__ import annotations

import json
from datetime import date, time
from unittest import TestCase

from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models import (
    DailyReport,
    DailyReportValue,
    Department,
    KpiMetric,
    PayComponent,
    PayProfile,
    PayProfileAssignment,
    PayrollRecalculationLog,
    PayrollRun,
    PositionPayProfilePeriod,
    Shift,
    ShiftAssignment,
    ShiftInterval,
    User,
    Venue,
    VenueMember,
    VenuePosition,
)
from app.services.payroll import calculate_payroll_for_month
from app.scripts.audit_position_pay_profiles import audit_position_pay_profiles
from app.routers.venue_payroll_support import (
    _payroll_preview_payload,
    _recalculate_affected_payroll_runs,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class VenueSetupPayrollUatTests(TestCase):
    """Regression for the seven-profile August setup exercised in the Mini App."""

    def setUp(self):
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_effective_dated_profile_audit_is_read_only_and_reports_legacy_gap(self):
        with Session(self.engine) as db:
            venue_id, _owner_id, _staff_id = self._seed_uat(db)
            db.commit()
            before_periods = db.query(PositionPayProfilePeriod).count()
            clean = audit_position_pay_profiles(db, venue_id=venue_id)
            self.assertTrue(clean["ok"])
            self.assertEqual(clean["issues"], [])
            self.assertEqual(db.query(PositionPayProfilePeriod).count(), before_periods)

            legacy = VenuePosition(
                venue_id=venue_id,
                member_user_id=102,
                pay_profile_id=401,
                title="Legacy without period",
                permission_codes="[]",
                is_active=True,
            )
            db.add(legacy)
            db.flush()
            audit = audit_position_pay_profiles(db, venue_id=venue_id)
            self.assertFalse(audit["ok"])
            self.assertIn("ACTIVE_POSITION_WITHOUT_PROFILE_PERIOD", {item["code"] for item in audit["issues"]})
            self.assertEqual(db.query(PositionPayProfilePeriod).count(), before_periods)

    def _seed_uat(self, db: Session) -> tuple[int, int, int]:
        venue = Venue(id=25, name="codex_test")
        owner = User(id=101, short_name="Axelio Admin")
        staff = User(id=102, short_name="monsterdush", tg_username="monsterdush")
        kitchen = Department(id=201, venue_id=25, code="KITCHEN", title="Кухня", is_active=True)
        kpi = KpiMetric(id=301, venue_id=25, code="UPSELL", title="Доппродажи", unit="QTY", is_active=True)
        db.add_all(
            [
                venue,
                owner,
                staff,
                VenueMember(venue_id=25, user_id=101, venue_role="OWNER", is_active=True),
                VenueMember(venue_id=25, user_id=102, venue_role="STAFF", is_active=True),
                kitchen,
                kpi,
            ]
        )

        component_specs = [
            (401, "Оклад UAT", "SALARY_FIXED_MONTH", {"amount_minor": 3_100_000}),
            (402, "Почасовая UAT", "SALARY_HOURLY", {"rate_minor": 30_000}),
            (403, "За смену UAT", "SALARY_PER_SHIFT", {"amount_minor": 120_000}),
            (
                404,
                "Процент выручки UAT",
                "PERCENT_TOTAL_REVENUE",
                {"percent_bps": 500, "base_scope": "FULL_PERIOD"},
            ),
            (
                405,
                "Процент кухни UAT",
                "PERCENT_DEPARTMENT_REVENUE",
                {
                    "percent_bps": 1_000,
                    "department_id": kitchen.id,
                    "department_ids_json": json.dumps([kitchen.id]),
                    "base_scope": "WORKED_DATES",
                },
            ),
            (
                406,
                "KPI UAT",
                "KPI_BONUS",
                {"rate_minor": 50_000, "kpi_metric_id": kpi.id, "kpi_calculation_mode": "PER_UNIT"},
            ),
            (
                407,
                "Минимум UAT",
                "MINIMUM_PAYOUT",
                {"amount_minor": 500_000, "minimum_guarantee_scope": "MONTH"},
            ),
        ]
        profiles: dict[int, PayProfile] = {}
        for sort_order, (profile_id, title, component_type, values) in enumerate(component_specs):
            profile = PayProfile(id=profile_id, venue_id=25, title=title, is_active=True)
            profiles[profile_id] = profile
            db.add(profile)
            db.add(
                PayComponent(
                    id=profile_id + 100,
                    venue_id=25,
                    pay_profile_id=profile_id,
                    component_type=component_type,
                    title=title,
                    is_active=True,
                    sort_order=sort_order,
                    **values,
                )
            )

        assignments = [
            (date(2026, 8, 1), owner.id, 401, "Оклад"),
            (date(2026, 8, 2), owner.id, 402, "Почасовая"),
            (date(2026, 8, 3), staff.id, 406, "KPI"),
            (date(2026, 8, 4), staff.id, 404, "Процент выручки"),
            (date(2026, 8, 5), staff.id, 407, "Минимум"),
            (date(2026, 8, 6), owner.id, 405, "Процент кухни"),
            (date(2026, 8, 7), owner.id, 403, "За смену"),
        ]
        interval = ShiftInterval(
            id=601,
            venue_id=25,
            title="День UAT",
            start_time=time(10, 0),
            end_time=time(18, 0),
            is_active=True,
        )
        db.add(interval)
        revenue = [10_000, 0, 10_000, 20_000, 0, 15_000, 0]
        kitchen_revenue = [7_000, 0, 7_000, 14_000, 0, 10_000, 0]
        for index, (shift_date, member_id, profile_id, title) in enumerate(assignments, start=1):
            position = VenuePosition(
                id=700 + index,
                venue_id=25,
                member_user_id=member_id,
                pay_profile_id=profile_id,
                title=title,
                permission_codes="[]",
                is_active=True,
            )
            shift = Shift(
                id=800 + index,
                venue_id=25,
                date=shift_date,
                interval_id=interval.id,
                shift_slot="DAY",
                is_active=True,
            )
            report = DailyReport(
                id=900 + index,
                venue_id=25,
                date=shift_date,
                shift_slot="DAY",
                revenue_total=revenue[index - 1],
                status="CLOSED",
                created_by_user_id=owner.id,
                closed_by_user_id=owner.id,
            )
            db.add_all(
                [
                    position,
                    PositionPayProfilePeriod(
                        venue_id=25,
                        venue_position_id=position.id,
                        member_user_id=member_id,
                        pay_profile_id=profile_id,
                        valid_from=date(2026, 8, 1),
                        valid_to=None,
                        is_active=True,
                    ),
                    shift,
                    ShiftAssignment(
                        shift_id=shift.id,
                        member_user_id=member_id,
                        venue_position_id=position.id,
                    ),
                    report,
                    DailyReportValue(
                        report_id=report.id,
                        kind="DEPT",
                        ref_id=kitchen.id,
                        value_numeric=kitchen_revenue[index - 1],
                    ),
                ]
            )
            if shift_date in {date(2026, 8, 1), date(2026, 8, 3)}:
                db.add(
                    DailyReportValue(
                        report_id=report.id,
                        kind="KPI",
                        ref_id=kpi.id,
                        value_numeric=4,
                    )
                )
        db.commit()
        return int(venue.id), int(owner.id), int(staff.id)

    def test_all_seven_profiles_are_paid_and_recalculation_is_idempotent(self):
        with Session(self.engine) as db:
            venue_id, owner_id, staff_id = self._seed_uat(db)

            first = calculate_payroll_for_month(
                db=db,
                venue_id=venue_id,
                month="2026-08",
                calculated_by_user_id=owner_id,
            )
            db.commit()
            first_by_member = {int(line.member_user_id): line for line in first.lines}

            self.assertEqual(first.run.total_amount_minor, 4_535_000)
            self.assertEqual(first_by_member[owner_id].amount_minor, 3_560_000)
            self.assertEqual(first_by_member[staff_id].amount_minor, 975_000)
            self.assertEqual(
                sorted(
                    item["amount_minor"]
                    for line in first.lines
                    for item in json.loads(line.breakdown_json)["components"]
                ),
                [100_000, 120_000, 200_000, 240_000, 275_000, 500_000, 3_100_000],
            )
            snapshots = [json.loads(line.breakdown_json) for line in first.lines]
            component_rows = [item for snapshot in snapshots for item in snapshot["components"]]
            self.assertEqual({item["profile_source"] for item in component_rows}, {"POSITION_PERIOD"})
            self.assertTrue(all(item["position_ids"] for item in component_rows))
            self.assertTrue(all(item["profile_period_ids"] for item in component_rows))

            second = calculate_payroll_for_month(
                db=db,
                venue_id=venue_id,
                month="2026-08",
                calculated_by_user_id=owner_id,
            )
            db.commit()
            self.assertEqual(second.run.total_amount_minor, 4_535_000)
            self.assertEqual(len(second.lines), 2)

    def test_non_overlapping_direct_assignments_are_resolved_by_date(self):
        with Session(self.engine) as db:
            db.add_all(
                [
                    Venue(id=25, name="codex_test"),
                    User(id=101, short_name="Axelio Admin"),
                    VenueMember(venue_id=25, user_id=101, venue_role="OWNER", is_active=True),
                    PayProfile(id=401, venue_id=25, title="Первая половина", is_active=True),
                    PayProfile(id=402, venue_id=25, title="Вторая половина", is_active=True),
                    PayComponent(
                        id=501,
                        venue_id=25,
                        pay_profile_id=401,
                        component_type="SALARY_FIXED_MONTH",
                        title="Оклад 1",
                        amount_minor=310_000,
                        is_active=True,
                    ),
                    PayComponent(
                        id=502,
                        venue_id=25,
                        pay_profile_id=402,
                        component_type="SALARY_FIXED_MONTH",
                        title="Оклад 2",
                        amount_minor=620_000,
                        is_active=True,
                    ),
                    PayProfileAssignment(
                        id=601,
                        venue_id=25,
                        pay_profile_id=401,
                        member_user_id=101,
                        start_date=date(2026, 8, 1),
                        end_date=date(2026, 8, 15),
                        is_active=True,
                    ),
                    PayProfileAssignment(
                        id=602,
                        venue_id=25,
                        pay_profile_id=402,
                        member_user_id=101,
                        start_date=date(2026, 8, 16),
                        end_date=date(2026, 8, 31),
                        is_active=True,
                    ),
                ]
            )
            db.commit()

            result = calculate_payroll_for_month(
                db=db,
                venue_id=25,
                month="2026-08",
                calculated_by_user_id=101,
            )
            db.commit()
            self.assertEqual(result.run.total_amount_minor, 470_000)
            self.assertEqual(len(result.lines), 1)
            snapshot = json.loads(result.lines[0].breakdown_json)
            self.assertEqual([item["amount_minor"] for item in snapshot["components"]], [150_000, 320_000])
            self.assertEqual({item["profile_source"] for item in snapshot["components"]}, {"MEMBER_FALLBACK"})

    def test_mid_month_promotion_keeps_both_position_profiles_in_one_payroll_line(self):
        with Session(self.engine) as db:
            db.add_all(
                [
                    Venue(id=25, name="codex_test"),
                    User(id=101, short_name="Сотрудник с повышением"),
                    VenueMember(venue_id=25, user_id=101, venue_role="STAFF", is_active=True),
                    PayProfile(id=401, venue_id=25, title="Бариста", is_active=True),
                    PayProfile(id=402, venue_id=25, title="Старший бариста", is_active=True),
                    PayComponent(
                        id=501,
                        venue_id=25,
                        pay_profile_id=401,
                        component_type="SALARY_PER_SHIFT",
                        title="Смена бариста",
                        amount_minor=100_000,
                        is_active=True,
                    ),
                    PayComponent(
                        id=502,
                        venue_id=25,
                        pay_profile_id=402,
                        component_type="SALARY_PER_SHIFT",
                        title="Смена старшего бариста",
                        amount_minor=250_000,
                        is_active=True,
                    ),
                    VenuePosition(
                        id=601,
                        venue_id=25,
                        member_user_id=101,
                        pay_profile_id=401,
                        title="Бариста",
                        permission_codes="[]",
                        is_active=True,
                    ),
                    VenuePosition(
                        id=602,
                        venue_id=25,
                        member_user_id=101,
                        pay_profile_id=402,
                        title="Старший бариста",
                        permission_codes="[]",
                        is_active=True,
                    ),
                    PositionPayProfilePeriod(
                        id=701,
                        venue_id=25,
                        venue_position_id=601,
                        member_user_id=101,
                        pay_profile_id=401,
                        valid_from=date(2026, 8, 1),
                        valid_to=date(2026, 8, 15),
                        is_active=True,
                    ),
                    PositionPayProfilePeriod(
                        id=702,
                        venue_id=25,
                        venue_position_id=602,
                        member_user_id=101,
                        pay_profile_id=402,
                        valid_from=date(2026, 8, 16),
                        valid_to=None,
                        is_active=True,
                    ),
                    PayProfileAssignment(
                        id=703,
                        venue_id=25,
                        pay_profile_id=401,
                        member_user_id=101,
                        start_date=date(2026, 8, 1),
                        end_date=date(2026, 8, 31),
                        is_active=True,
                    ),
                    ShiftInterval(
                        id=801,
                        venue_id=25,
                        title="День",
                        start_time=time(10, 0),
                        end_time=time(18, 0),
                        is_active=True,
                    ),
                ]
            )
            for index, (shift_date, position_id) in enumerate(
                [
                    (date(2026, 8, 5), 601),
                    (date(2026, 8, 12), 601),
                    (date(2026, 8, 20), 602),
                    (date(2026, 8, 27), 602),
                ],
                start=1,
            ):
                shift_id = 900 + index
                db.add_all(
                    [
                        Shift(
                            id=shift_id,
                            venue_id=25,
                            date=shift_date,
                            interval_id=801,
                            shift_slot="DAY",
                            is_active=True,
                        ),
                        ShiftAssignment(
                            shift_id=shift_id,
                            member_user_id=101,
                            venue_position_id=position_id,
                        ),
                        DailyReport(
                            id=1000 + index,
                            venue_id=25,
                            date=shift_date,
                            shift_slot="DAY",
                            revenue_total=0,
                            status="CLOSED",
                            created_by_user_id=101,
                            closed_by_user_id=101,
                        ),
                    ]
                )
            db.commit()

            result = calculate_payroll_for_month(
                db=db,
                venue_id=25,
                month="2026-08",
                calculated_by_user_id=101,
            )
            db.commit()

            self.assertEqual(result.run.total_amount_minor, 700_000)
            self.assertEqual(len(result.lines), 1)
            self.assertIsNone(result.lines[0].pay_profile_id)
            snapshot = json.loads(result.lines[0].breakdown_json)
            self.assertEqual(snapshot["pay_profile_ids"], [401, 402])
            self.assertEqual(
                [item["amount_minor"] for item in snapshot["components"]],
                [200_000, 500_000],
            )
            self.assertEqual(
                [item["position_ids"] for item in snapshot["components"]],
                [[601], [602]],
            )
            self.assertEqual(
                {item["profile_source"] for item in snapshot["components"]},
                {"POSITION_PERIOD"},
            )
            self.assertEqual(snapshot["metrics"]["shifts_count"], 4)
            self.assertEqual(len(snapshot["position_profiles"]), 2)
            self.assertEqual(
                {item["rounding_rule"] for item in snapshot["components"]},
                {"EXACT_MINOR_UNITS"},
            )
            self.assertEqual(
                [item["profile_active_from"] for item in snapshot["components"]],
                ["2026-08-01", "2026-08-16"],
            )
            self.assertEqual(
                [item["used_shift_ids"] for item in snapshot["components"]],
                [[901, 902], [903, 904]],
            )
            self.assertTrue(
                all(
                    {candidate["profile_source"] for candidate in item["discarded_profile_candidates"]}
                    == {"MEMBER_FALLBACK", "POSITION_LEGACY"}
                    for item in snapshot["components"]
                )
            )

    def test_closed_assigned_shift_without_profile_returns_warning(self):
        with Session(self.engine) as db:
            db.add_all(
                [
                    Venue(id=25, name="codex_test"),
                    User(id=101, short_name="Сотрудник без профиля"),
                    VenueMember(venue_id=25, user_id=101, venue_role="STAFF", is_active=True),
                    VenuePosition(
                        id=601,
                        venue_id=25,
                        member_user_id=101,
                        pay_profile_id=None,
                        title="Стажёр",
                        permission_codes="[]",
                        is_active=True,
                    ),
                    ShiftInterval(
                        id=701,
                        venue_id=25,
                        title="День",
                        start_time=time(10, 0),
                        end_time=time(18, 0),
                        is_active=True,
                    ),
                    Shift(
                        id=801,
                        venue_id=25,
                        date=date(2026, 8, 10),
                        interval_id=701,
                        shift_slot="DAY",
                        is_active=True,
                    ),
                    ShiftAssignment(
                        shift_id=801,
                        member_user_id=101,
                        venue_position_id=601,
                    ),
                    DailyReport(
                        id=901,
                        venue_id=25,
                        date=date(2026, 8, 10),
                        shift_slot="DAY",
                        revenue_total=0,
                        status="CLOSED",
                        created_by_user_id=101,
                        closed_by_user_id=101,
                    ),
                ]
            )
            db.commit()

            result = calculate_payroll_for_month(
                db=db,
                venue_id=25,
                month="2026-08",
                calculated_by_user_id=101,
            )

            self.assertEqual(result.lines, [])
            self.assertEqual(result.run.total_amount_minor, 0)
            self.assertEqual(
                result.warnings,
                [
                    {
                        "code": "PAY_PROFILE_UNRESOLVED",
                        "member_user_id": 101,
                        "shift_id": 801,
                        "venue_position_id": 601,
                        "shift_date": "2026-08-10",
                        "shift_slot": "DAY",
                        "attempted_pay_profile_id": None,
                    }
                ],
            )

    def test_preview_blocks_profile_without_components_and_rolls_back_every_write(self):
        with Session(self.engine) as db:
            db.add_all(
                [
                    Venue(id=25, name="codex_test"),
                    User(id=101, short_name="Сотрудник"),
                    VenueMember(venue_id=25, user_id=101, venue_role="OWNER", is_active=True),
                    PayProfile(id=401, venue_id=25, title="Пустой профиль", is_active=True),
                    PayProfileAssignment(
                        id=501,
                        venue_id=25,
                        pay_profile_id=401,
                        member_user_id=101,
                        start_date=date(2026, 8, 1),
                        end_date=date(2026, 8, 31),
                        is_active=True,
                    ),
                ]
            )
            db.commit()

            preview = _payroll_preview_payload(
                db,
                venue_id=25,
                month="2026-08",
                calculated_by_user_id=101,
            )

            self.assertTrue(preview["is_blocked"])
            self.assertEqual(
                [warning["code"] for warning in preview["blocking_warnings"]],
                ["PAY_PROFILE_WITHOUT_COMPONENTS"],
            )
            self.assertEqual(db.execute(select(PayrollRun)).scalars().all(), [])

    def test_profile_rule_change_recalculates_persisted_month_and_records_diagnostics(self):
        with Session(self.engine) as db:
            venue_id, owner_id, _staff_id = self._seed_uat(db)
            first = calculate_payroll_for_month(
                db=db,
                venue_id=venue_id,
                month="2026-08",
                calculated_by_user_id=owner_id,
            )
            db.commit()
            self.assertEqual(first.run.total_amount_minor, 4_535_000)

            component = db.execute(select(PayComponent).where(PayComponent.id == 501)).scalar_one()
            component.amount_minor = 6_200_000
            months = _recalculate_affected_payroll_runs(
                db,
                venue_id=venue_id,
                calculated_by_user_id=owner_id,
                trigger_reason="pay_component_updated",
                details={"pay_component_id": int(component.id)},
            )
            db.commit()

            run = db.execute(
                select(PayrollRun).where(
                    PayrollRun.venue_id == venue_id,
                    PayrollRun.period_month == date(2026, 8, 1),
                )
            ).scalar_one()
            log = db.execute(
                select(PayrollRecalculationLog).where(
                    PayrollRecalculationLog.venue_id == venue_id,
                    PayrollRecalculationLog.period_month == date(2026, 8, 1),
                )
            ).scalar_one()
            details = json.loads(log.details_json)
            self.assertEqual(months, ["2026-08"])
            self.assertEqual(run.total_amount_minor, 7_635_000)
            self.assertEqual(log.trigger_reason, "pay_component_updated")
            self.assertEqual(details["previous_total_amount_minor"], 4_535_000)
            self.assertEqual(details["total_amount_minor"], 7_635_000)
            self.assertEqual(details["total_delta_minor"], 3_100_000)
            self.assertEqual(details["release"], "local")
            self.assertEqual(details["transaction_result"], "committed")
            self.assertGreaterEqual(details["contexts_count"], 7)

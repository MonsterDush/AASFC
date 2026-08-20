from __future__ import annotations

import unittest
from datetime import date, time

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models import (
    ShiftInterval,
    Shift,
    ShiftAssignment,
    ShiftScheduleTemplate,
    ShiftScheduleTemplateItem,
    ShiftSwapRequest,
    User,
    Venue,
    VenueMember,
)
from app.services.demo.bootstrap import (
    _daily_base_minor,
    _history_periods,
    _seasonal_factor,
    bootstrap_demo_venue,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class DemoBootstrapPeriodTests(unittest.TestCase):
    def test_builds_rolling_year_ending_at_reference_month(self):
        periods = _history_periods(2026, 3, 12)

        self.assertEqual(periods[0], (2025, 4))
        self.assertEqual(periods[-1], (2026, 3))
        self.assertEqual(len(periods), 12)

    def test_rejects_history_longer_than_supported_window(self):
        with self.assertRaisesRegex(ValueError, "history_months"):
            _history_periods(2026, 3, 25)


class DemoBootstrapSeasonalityTests(unittest.TestCase):
    def test_winter_is_stronger_than_summer(self):
        winter = [_seasonal_factor(month) for month in (12, 1, 2)]
        summer = [_seasonal_factor(month) for month in (6, 7, 8)]

        self.assertGreater(min(winter), max(summer))

    def test_decline_becomes_pronounced_in_may(self):
        self.assertGreater(_seasonal_factor(4), _seasonal_factor(5))
        self.assertGreater(_seasonal_factor(5), _seasonal_factor(6))
        self.assertGreater(_seasonal_factor(6), _seasonal_factor(7))

    def test_existing_march_peak_value_remains_the_anchor(self):
        self.assertEqual(_daily_base_minor(date(2026, 3, 8)), 11_800_000)


class DemoBootstrapForeignKeyTests(unittest.TestCase):
    def test_rebuild_deletes_schedule_template_items_before_intervals(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        with Session(engine) as db:
            first = bootstrap_demo_venue(
                db,
                reference_year=2026,
                reference_month=3,
                history_months=1,
                make_public=True,
            )
            interval = ShiftInterval(
                venue_id=int(first.venue_id),
                title="E2E reset interval",
                start_time=time(10, 0),
                end_time=time(18, 0),
                is_active=True,
            )
            template = ShiftScheduleTemplate(
                venue_id=int(first.venue_id),
                title="E2E reset template",
                is_active=True,
            )
            db.add_all([interval, template])
            db.flush()
            db.add(
                ShiftScheduleTemplateItem(
                    template_id=int(template.id),
                    weekday=0,
                    interval_id=int(interval.id),
                    shift_slot="DAY",
                    sort_order=0,
                )
            )
            assignment = db.execute(
                select(ShiftAssignment)
                .join(Shift, Shift.id == ShiftAssignment.shift_id)
                .where(Shift.venue_id == int(first.venue_id))
                .limit(1)
            ).scalar_one()
            db.add(
                ShiftSwapRequest(
                    venue_id=int(first.venue_id),
                    shift_id=int(assignment.shift_id),
                    assignment_id=int(assignment.id),
                    requester_user_id=int(assignment.member_user_id),
                    status="CANCELLED",
                    comment="fixture reset regression",
                )
            )
            db.commit()
            db.expunge_all()

            bootstrap_demo_venue(
                db,
                venue_id=int(first.venue_id),
                reference_year=2026,
                reference_month=3,
                history_months=1,
                make_public=True,
            )
            db.commit()

            self.assertIsNone(
                db.execute(
                    select(ShiftScheduleTemplate).where(ShiftScheduleTemplate.title == "E2E reset template")
                ).scalar_one_or_none()
            )
            self.assertEqual(
                db.execute(
                    select(func.count(ShiftSwapRequest.id)).where(ShiftSwapRequest.venue_id == int(first.venue_id))
                ).scalar_one(),
                0,
            )

    def test_rebuild_reuses_users_that_are_linked_to_another_venue(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")

        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        with Session(engine) as db:
            first = bootstrap_demo_venue(
                db,
                reference_year=2026,
                reference_month=3,
                history_months=1,
                make_public=True,
            )
            db.commit()

            shared_user = db.execute(
                select(User)
                .join(VenueMember, VenueMember.user_id == User.id)
                .where(
                    VenueMember.venue_id == int(first.venue_id),
                    User.tg_username == "axelio_demo_staff",
                )
            ).scalar_one()
            shared_user_id = int(shared_user.id)
            template = Venue(name="DEMO template")
            db.add(template)
            db.flush()
            db.add(
                VenueMember(
                    venue_id=int(template.id),
                    user_id=shared_user_id,
                    venue_role="STAFF",
                    is_active=True,
                )
            )
            db.commit()

            bootstrap_demo_venue(
                db,
                venue_id=int(first.venue_id),
                reference_year=2026,
                reference_month=3,
                history_months=1,
                make_public=True,
            )
            db.commit()

            self.assertEqual(
                db.execute(select(func.count(User.id)).where(User.is_demo_user.is_(True))).scalar(),
                10,
            )
            self.assertEqual(
                db.execute(select(func.count(VenueMember.id)).where(VenueMember.user_id == shared_user_id)).scalar(),
                2,
            )


if __name__ == "__main__":
    unittest.main()

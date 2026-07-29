from __future__ import annotations

from datetime import date, time, timedelta
from unittest import TestCase
from unittest.mock import patch

from fastapi import BackgroundTasks
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    DailyReport,
    Shift,
    ShiftAssignment,
    ShiftAvailability,
    ShiftInterval,
    ShiftSwapRequest,
    User,
    VenueMember,
    VenuePosition,
)
from app.auth import account_merge
from app.routers import venue_shift_swaps
from app.schemas.venue_shifts import (
    ShiftAvailabilityUpsertIn,
    ShiftSwapCreateIn,
    ShiftSwapDecisionIn,
)


class ShiftSwapWorkflowTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        for table in (
            User.__table__,
            VenueMember.__table__,
            VenuePosition.__table__,
            ShiftInterval.__table__,
            Shift.__table__,
            ShiftAssignment.__table__,
            ShiftAvailability.__table__,
            ShiftSwapRequest.__table__,
            DailyReport.__table__,
        ):
            table.create(self.engine)

    def _seed(self, db: Session):
        requester = User(id=1, short_name="Анна")
        replacement = User(id=2, short_name="Олег")
        manager = User(id=3, short_name="Мария")
        db.add_all([requester, replacement, manager])
        db.add_all(
            [
                VenueMember(venue_id=5, user_id=1, venue_role="STAFF", is_active=True),
                VenueMember(venue_id=5, user_id=2, venue_role="STAFF", is_active=True),
                VenueMember(venue_id=5, user_id=3, venue_role="OWNER", is_active=True),
            ]
        )
        requester_position = VenuePosition(
            id=11,
            venue_id=5,
            member_user_id=1,
            title="Бармен",
            rate=0,
            percent=0,
            is_active=True,
        )
        replacement_position = VenuePosition(
            id=12,
            venue_id=5,
            member_user_id=2,
            title="Бармен",
            rate=0,
            percent=0,
            is_active=True,
        )
        interval = ShiftInterval(
            id=21,
            venue_id=5,
            title="Ночь",
            start_time=time(22, 0),
            end_time=time(4, 0),
            is_active=True,
        )
        shift = Shift(
            id=31,
            venue_id=5,
            date=date.today() + timedelta(days=7),
            interval_id=21,
            shift_slot="NIGHT",
            is_active=True,
        )
        assignment = ShiftAssignment(
            id=41,
            shift_id=31,
            member_user_id=1,
            venue_position_id=11,
        )
        db.add_all([requester_position, replacement_position, interval, shift, assignment])
        db.commit()
        return requester, replacement, manager, shift, assignment

    def test_availability_upsert_updates_the_same_member_date_slot(self):
        with Session(self.engine) as db:
            requester, _, _, shift, _ = self._seed(db)
            with patch.object(venue_shift_swaps, "_require_active_member_or_admin"), patch.object(
                venue_shift_swaps,
                "_normalize_shift_slot_for_venue",
                return_value="NIGHT",
            ):
                first = venue_shift_swaps.upsert_shift_availability(
                    5,
                    shift.date,
                    "NIGHT",
                    ShiftAvailabilityUpsertIn(status="AVAILABLE", comment="После 21:00"),
                    db,
                    requester,
                )
                second = venue_shift_swaps.upsert_shift_availability(
                    5,
                    shift.date,
                    "NIGHT",
                    ShiftAvailabilityUpsertIn(status="UNAVAILABLE"),
                    db,
                    requester,
                )

            rows = db.execute(select(ShiftAvailability)).scalars().all()
            self.assertEqual(first["id"], second["id"])
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "UNAVAILABLE")
            self.assertIsNone(rows[0].comment)

    def test_manager_approval_atomically_moves_the_assignment(self):
        with Session(self.engine) as db:
            requester, replacement, manager, shift, assignment = self._seed(db)
            background_tasks = BackgroundTasks()
            with patch.object(venue_shift_swaps, "_require_active_member_or_admin"), patch.object(
                venue_shift_swaps,
                "_enqueue_shift_swap_job",
            ), patch.object(
                venue_shift_swaps,
                "_require_schedule_editor",
            ), patch.object(
                venue_shift_swaps,
                "_recalculate_payroll_for_dates",
            ) as recalculate:
                created = venue_shift_swaps.create_shift_swap_request(
                    5,
                    int(shift.id),
                    ShiftSwapCreateIn(replacement_user_id=int(replacement.id), comment="Учёба"),
                    background_tasks,
                    db,
                    requester,
                )
                approved = venue_shift_swaps.approve_shift_swap_request(
                    5,
                    int(created["id"]),
                    ShiftSwapDecisionIn(comment="Подтверждаю"),
                    background_tasks,
                    db,
                    manager,
                )

            db.refresh(assignment)
            request = db.get(ShiftSwapRequest, int(created["id"]))
            self.assertEqual(approved["status"], "APPROVED")
            self.assertEqual(assignment.member_user_id, replacement.id)
            self.assertEqual(assignment.venue_position_id, 12)
            self.assertEqual(request.status, "APPROVED")
            self.assertEqual(request.decided_by_user_id, manager.id)
            recalculate.assert_called_once()

    def test_overnight_candidate_conflict_checks_real_time_overlap(self):
        with Session(self.engine) as db:
            requester, replacement, _, shift, _ = self._seed(db)
            overlapping_interval = ShiftInterval(
                id=22,
                venue_id=7,
                title="Раннее утро",
                start_time=time(3, 0),
                end_time=time(7, 0),
                is_active=True,
            )
            overlapping_shift = Shift(
                id=32,
                venue_id=7,
                date=shift.date + timedelta(days=1),
                interval_id=22,
                shift_slot="DAY",
                is_active=True,
            )
            overlapping_assignment = ShiftAssignment(
                id=42,
                shift_id=32,
                member_user_id=int(replacement.id),
                venue_position_id=12,
            )
            db.add_all([overlapping_interval, overlapping_shift, overlapping_assignment])
            db.commit()
            interval = db.get(ShiftInterval, int(shift.interval_id))

            self.assertTrue(
                venue_shift_swaps._replacement_conflict(
                    db,
                    replacement_user_id=int(replacement.id),
                    shift=shift,
                    interval=interval,
                )
            )

    def test_only_one_open_request_is_allowed_per_assignment(self):
        with Session(self.engine) as db:
            requester, replacement, _, shift, assignment = self._seed(db)
            first = ShiftSwapRequest(
                venue_id=5,
                shift_id=int(shift.id),
                assignment_id=int(assignment.id),
                requester_user_id=int(requester.id),
                replacement_user_id=int(replacement.id),
                replacement_position_id=12,
                status="OPEN",
            )
            db.add(first)
            db.commit()
            second = ShiftSwapRequest(
                venue_id=5,
                shift_id=int(shift.id),
                assignment_id=int(assignment.id),
                requester_user_id=int(requester.id),
                status="OPEN",
            )
            db.add(second)
            with self.assertRaises(IntegrityError):
                db.commit()

    def test_account_merge_repoints_assignment_and_swap_position_before_delete(self):
        with Session(self.engine) as db:
            target, source, _, shift, assignment = self._seed(db)
            assignment.venue_position_id = 12
            request = ShiftSwapRequest(
                venue_id=5,
                shift_id=int(shift.id),
                assignment_id=int(assignment.id),
                requester_user_id=int(target.id),
                replacement_user_id=int(source.id),
                replacement_position_id=12,
                status="OPEN",
            )
            db.add(request)
            db.commit()

            position_map = account_merge._merge_venue_positions(
                db,
                target_user=target,
                source_user=source,
            )
            db.commit()
            db.refresh(assignment)
            db.refresh(request)

            self.assertEqual(position_map[12], 11)
            self.assertEqual(assignment.venue_position_id, 11)
            self.assertEqual(request.replacement_position_id, 11)

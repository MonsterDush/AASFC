from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import User, VenueMember, VenuePosition, ShiftInterval, Shift, ShiftAssignment, PayProfile
from app.models.shift_interval import ShiftIntervalPosition
from app.routers import venue_shifts, venue_shift_intervals, venue_positions
from app.schemas.venue_shifts import ShiftCreateIn, ShiftUpdateIn, ShiftIntervalCreateIn, ShiftIntervalUpdateIn
from app.schemas.venue_payroll import PositionUpdateIn
from app.services import invites
from app.services.shift_interval_scope import (
    interval_scope_payloads,
    require_interval_position_match,
    set_interval_positions,
)
from app.services.venue_member_names import apply_payroll_owner_display_names


class NamesAndIntervalScopesTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE venues (id INTEGER PRIMARY KEY, name TEXT, is_archived BOOLEAN)")
            connection.exec_driver_sql("INSERT INTO venues VALUES (5, 'Test', 0), (6, 'Other', 0)")
        for model in (
            User,
            VenueMember,
            PayProfile,
            VenuePosition,
            ShiftInterval,
            ShiftIntervalPosition,
            Shift,
            ShiftAssignment,
        ):
            model.__table__.create(self.engine)
        self.db = Session(self.engine)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.db.close)
        self.owner = User(id=1, short_name="Owner")
        self.employee = User(id=2, short_name="Михаил Иванов")
        self.manager = User(id=3, short_name="Manager")
        self.bar = VenuePosition(id=10, venue_id=5, title="Бармен")
        self.manager_role = VenuePosition(id=11, venue_id=5, title="Менеджер")
        self.bar_assignment = VenuePosition(id=20, venue_id=5, title="Бармен", member_user_id=2, catalog_position_id=10)
        self.manager_assignment = VenuePosition(
            id=21, venue_id=5, title="Менеджер", member_user_id=2, catalog_position_id=11
        )
        self.db.add_all(
            [
                self.owner,
                self.employee,
                self.manager,
                self.bar,
                self.manager_role,
                self.bar_assignment,
                self.manager_assignment,
            ]
        )
        self.db.add_all(
            [
                VenueMember(venue_id=5, user_id=1, venue_role="OWNER", is_active=True),
                VenueMember(venue_id=5, user_id=2, venue_role="STAFF", owner_note="Миша старший", is_active=True),
                VenueMember(venue_id=5, user_id=3, venue_role="STAFF", is_active=True),
                ShiftInterval(id=1, venue_id=5, title="Общий", start_time=time(10), end_time=time(22)),
                ShiftInterval(
                    id=2, venue_id=5, title="Менеджер", start_time=time(10), end_time=time(22), position_id=11
                ),
                Shift(id=1, venue_id=5, date=date(2026, 9, 4), interval_id=1),
                ShiftAssignment(id=1, shift_id=1, member_user_id=2, venue_position_id=20),
            ]
        )
        self.db.commit()

    def test_manager_detail_and_payroll_use_local_name_without_exposing_raw_note(self):
        self.employee.short_name = "Новое глобальное имя"
        self.db.commit()
        with patch.object(venue_shifts, "_require_active_member_or_admin"):
            payload = venue_shifts.get_shift(5, 1, self.db, self.manager)
        member = payload["assignments"][0]["member"]
        self.assertEqual(member["display_name"], "Миша старший")
        self.assertIsNone(member["owner_note"])
        result = apply_payroll_owner_display_names(
            self.db,
            venue_id=5,
            viewer=self.manager,
            payload={"lines": [{"member_user_id": 2, "member": {"short_name": self.employee.short_name}}]},
        )
        self.assertEqual(result["lines"][0]["member"]["display_name"], "Миша старший")
        self.assertIsNone(result["lines"][0]["member"]["owner_note"])

    def test_accepting_invite_preserves_global_name_and_fallback_remains_central(self):
        membership = self.db.scalar(select(VenueMember).where(VenueMember.user_id == 2))
        membership.owner_note = None
        with patch.object(venue_shifts, "_require_active_member_or_admin"):
            self.assertEqual(
                venue_shifts.get_shift(5, 1, self.db, self.manager)["assignments"][0]["member"]["display_name"],
                "Михаил Иванов",
            )
        invite = SimpleNamespace(venue_id=5, venue_role="STAFF", invited_contact_label="  Миша   старший  ")
        with patch.object(invites, "_apply_default_position"):
            invites._accept_invite_record(self.db, inv=invite, user_id=2)
        self.assertEqual(membership.owner_note, "Миша старший")
        self.assertEqual(self.employee.short_name, "Михаил Иванов")

    def test_local_mention_token_is_valid_without_changing_global_user(self):
        self.assertTrue(
            venue_shifts._shift_comment_has_mention_token(
                "@Миша старший привет", self.employee, display_name="Миша старший"
            )
        )
        self.assertFalse(
            venue_shifts._shift_comment_has_mention_token(
                "Миша старший привет", self.employee, display_name="Миша старший"
            )
        )

    def test_invite_assignment_links_current_catalog_after_rename(self):
        self.manager_role.title = "Управляющий"
        invite = SimpleNamespace(venue_id=5, default_position_json={"title": "Менеджер", "venue_position_id": 11})
        with patch.object(invites, "_sync_default_pay_profile_assignment"):
            invites._apply_default_position(self.db, inv=invite, user_id=3)
        assigned = self.db.scalar(select(VenuePosition).where(VenuePosition.member_user_id == 3))
        self.assertEqual(assigned.title, "Управляющий")
        self.assertEqual(assigned.catalog_position_id, 11)
        require_interval_position_match(self.db, venue_id=5, interval=self.db.get(ShiftInterval, 2), position=assigned)

    def test_interval_accepts_multiple_roles_and_matches_ids_after_rename(self):
        interval = self.db.get(ShiftInterval, 1)
        set_interval_positions(self.db, interval=interval, position_ids=[11, 10, 11])
        self.db.commit()
        self.bar.title = "Переименованная должность"
        self.bar_assignment.title = "Другая подпись назначения"
        require_interval_position_match(self.db, venue_id=5, interval=interval, position=self.bar_assignment)
        require_interval_position_match(self.db, venue_id=5, interval=interval, position=self.manager_assignment)
        self.assertEqual(
            interval_scope_payloads(self.db, venue_id=5, intervals=[interval])[1]["position_ids"], [10, 11]
        )

    def test_unrestricted_interval_accepts_unlinked_role_and_restricted_rejects_with_code(self):
        require_interval_position_match(
            self.db, venue_id=5, interval=self.db.get(ShiftInterval, 1), position=self.bar_assignment
        )
        with self.assertRaises(HTTPException) as caught:
            require_interval_position_match(
                self.db, venue_id=5, interval=self.db.get(ShiftInterval, 2), position=self.bar_assignment
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "SHIFT_INTERVAL_POSITION_MISMATCH")

    def test_scope_update_leaves_all_existing_assignments_untouched(self):
        with patch.object(venue_shift_intervals, "_require_schedule_editor"):
            venue_shift_intervals.update_shift_interval(
                5, 1, ShiftIntervalUpdateIn(position_ids=[11]), self.db, self.owner
            )
        self.assertEqual(self.db.get(ShiftAssignment, 1).venue_position_id, 20)
        with (
            patch.object(venue_shifts, "_require_schedule_editor"),
            patch.object(venue_shifts, "_recalculate_payroll_for_dates"),
        ):
            venue_shifts.update_shift(5, 1, ShiftUpdateIn(interval_id=2), self.db, self.owner)
        self.assertEqual(self.db.get(Shift, 1).interval_id, 2)
        self.assertEqual(self.db.get(ShiftAssignment, 1).venue_position_id, 20)

    def test_new_shift_and_assignment_are_validated_and_saved_together(self):
        with (
            patch.object(venue_shifts, "_require_schedule_editor"),
            patch.object(venue_shifts, "_normalize_shift_slot_for_venue", return_value="DAY"),
            patch.object(venue_shifts, "_recalculate_payroll_for_dates"),
            patch.object(venue_shifts, "_rebuild_closed_report_tip_allocations_for_keys"),
        ):
            with self.assertRaises(HTTPException):
                venue_shifts.create_shift(
                    5, ShiftCreateIn(date=date(2026, 9, 5), interval_id=2, venue_position_id=20), self.db, self.owner
                )
            self.assertEqual(len(self.db.scalars(select(Shift)).all()), 1)
            result = venue_shifts.create_shift(
                5, ShiftCreateIn(date=date(2026, 9, 5), interval_id=2, venue_position_id=21), self.db, self.owner
            )
        assignment = self.db.scalar(select(ShiftAssignment).where(ShiftAssignment.shift_id == result["id"]))
        self.assertEqual(assignment.venue_position_id, 21)

    def test_scope_payload_rejects_foreign_role_and_conflicting_legacy_input(self):
        self.db.add(VenuePosition(id=30, venue_id=6, title="Чужая"))
        self.db.commit()
        for payload in (
            ShiftIntervalCreateIn(title="Test", start_time=time(1), end_time=time(2), position_ids=[30]),
            ShiftIntervalCreateIn(
                title="Test", start_time=time(1), end_time=time(2), position_id=10, position_ids=[11]
            ),
        ):
            with patch.object(venue_shift_intervals, "_require_schedule_editor"), self.assertRaises(HTTPException):
                venue_shift_intervals.create_shift_interval(5, payload, self.db, self.owner)
        with self.assertRaises(ValidationError):
            ShiftIntervalUpdateIn(position_ids=[0])

    def test_partial_interval_edit_retains_scope_and_explicit_empty_list_clears_it(self):
        with patch.object(venue_shift_intervals, "_require_schedule_editor"):
            venue_shift_intervals.update_shift_interval(
                5, 1, ShiftIntervalUpdateIn(position_ids=[10, 11]), self.db, self.owner
            )
            venue_shift_intervals.update_shift_interval(
                5, 1, ShiftIntervalUpdateIn(title="Renamed"), self.db, self.owner
            )
            self.assertEqual(
                interval_scope_payloads(self.db, venue_id=5, intervals=[self.db.get(ShiftInterval, 1)])[1][
                    "position_ids"
                ],
                [10, 11],
            )
            venue_shift_intervals.update_shift_interval(
                5, 1, ShiftIntervalUpdateIn(position_ids=[]), self.db, self.owner
            )
        self.assertIsNone(self.db.get(ShiftInterval, 1).position_id)
        self.assertEqual(self.db.scalars(select(ShiftIntervalPosition)).all(), [])

    def test_catalog_rename_keeps_assignment_identity_and_scope(self):
        with (
            patch.object(venue_positions, "_require_active_member_or_admin"),
            patch.object(venue_positions, "_is_owner_or_super_admin", return_value=True),
        ):
            venue_positions.update_position(5, 10, PositionUpdateIn(title="Старший бармен"), self.db, self.owner)
        self.assertEqual(self.bar_assignment.catalog_position_id, 10)
        self.assertEqual(self.bar_assignment.title, "Старший бармен")
        self.assertEqual(self.db.get(ShiftAssignment, 1).venue_position_id, 20)

    def test_assigning_catalog_role_keeps_the_catalog_and_interval_reference(self):
        with (
            patch.object(venue_positions, "_require_active_member_or_admin"),
            patch.object(venue_positions, "_is_owner_or_super_admin", return_value=True),
        ):
            result = venue_positions.update_position(5, 11, PositionUpdateIn(member_user_id=3), self.db, self.owner)
        self.assertNotEqual(result["id"], 11)
        self.assertIsNone(self.manager_role.member_user_id)
        self.assertEqual(result["catalog_position_id"], 11)
        self.assertEqual(self.db.get(ShiftInterval, 2).position_id, 11)
        require_interval_position_match(
            self.db,
            venue_id=5,
            interval=self.db.get(ShiftInterval, 2),
            position=self.db.get(VenuePosition, result["id"]),
        )

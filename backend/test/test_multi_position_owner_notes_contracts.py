from __future__ import annotations

from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth import venue_permissions
from app.models.shift_interval import ShiftIntervalPosition
from app.models import (
    DailyReport,
    PayProfile,
    Shift,
    ShiftAssignment,
    ShiftInterval,
    User,
    VenueMember,
    VenuePosition,
)
from app.routers import venue_positions, venue_shifts
from app.schemas.venue_shifts import ShiftAssignmentAddIn
from app.services.payroll.position_contexts import load_position_payroll_contexts
from app.services.venue_member_names import load_owner_notes, owner_display_name


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FourFixesModelAndSourceContracts(TestCase):
    def test_position_model_supports_empty_and_multiple_assignments(self):
        member_column = VenuePosition.__table__.c.member_user_id
        self.assertTrue(member_column.nullable)
        self.assertIn("pay_profile_id", VenuePosition.__table__.c)
        unique_columns = {
            tuple(column.name for column in constraint.columns)
            for constraint in VenuePosition.__table__.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        self.assertNotIn(("venue_id", "member_user_id"), unique_columns)

    def test_auth_link_handlers_merge_and_reissue_cookie_in_both_directions(self):
        phone_source = (PROJECT_ROOT / "backend/app/routers/auth_phone.py").read_text(encoding="utf-8")
        telegram_source = (PROJECT_ROOT / "backend/app/routers/auth_telegram.py").read_text(encoding="utf-8")

        phone_handler = phone_source[phone_source.index("def verify_link_phone_code(") :]
        self.assertIn("merge_user_accounts", phone_handler)
        self.assertIn("_write_access_cookie(response, user=user)", phone_handler)

        telegram_handler = telegram_source[telegram_source.index("def link_telegram_account(") :]
        self.assertIn("merge_user_accounts", telegram_handler)
        self.assertIn("_write_access_cookie(response, user=user)", telegram_handler)

    def test_frontend_exposes_empty_roles_private_notes_and_shift_role_switching(self):
        editor = (PROJECT_ROOT / "frontend/positions/position-editor.js").read_text(encoding="utf-8")
        invites = (PROJECT_ROOT / "frontend/invites.html").read_text(encoding="utf-8")
        shifts = (PROJECT_ROOT / "frontend/staff-shifts.js").read_text(encoding="utf-8")

        self.assertIn("— без сотрудника —", editor)
        self.assertIn("/owner-note", invites)
        self.assertIn("Изменить заметку", invites)
        self.assertIn("Назначить / сменить должность", shifts)
        self.assertIn("assignedPositions", shifts)


class FourFixesDatabaseBehaviorTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE venues (id INTEGER PRIMARY KEY, name VARCHAR(200), is_archived BOOLEAN NOT NULL DEFAULT 0)"
            )
            connection.exec_driver_sql("INSERT INTO venues (id, name, is_archived) VALUES (5, 'Test', 0)")
        for table in (
            User.__table__,
            VenueMember.__table__,
            PayProfile.__table__,
            VenuePosition.__table__,
            ShiftInterval.__table__,
            ShiftIntervalPosition.__table__,
            Shift.__table__,
            ShiftAssignment.__table__,
            DailyReport.__table__,
        ):
            table.create(self.engine)

    def _seed_people_and_positions(self, db: Session):
        owner = User(id=1, short_name="Владелец")
        employee = User(id=2, short_name="Настоящее имя")
        db.add_all([owner, employee])
        db.add_all(
            [
                VenueMember(venue_id=5, user_id=1, venue_role="OWNER", is_active=True),
                VenueMember(
                    venue_id=5,
                    user_id=2,
                    venue_role="STAFF",
                    owner_note="Бармен из филиала",
                    is_active=True,
                ),
            ]
        )
        first_profile = PayProfile(id=21, venue_id=5, title="Бар", is_active=True)
        second_profile = PayProfile(id=22, venue_id=5, title="Зал", is_active=True)
        db.add_all([first_profile, second_profile])
        first_position = VenuePosition(
            id=11,
            venue_id=5,
            member_user_id=2,
            pay_profile_id=21,
            title="Бармен",
            rate=0,
            percent=0,
            permission_codes='["SHIFTS_VIEW"]',
            is_active=True,
        )
        second_position = VenuePosition(
            id=12,
            venue_id=5,
            member_user_id=2,
            pay_profile_id=22,
            title="Официант",
            rate=0,
            percent=0,
            permission_codes='["PAYROLL_VIEW"]',
            is_active=True,
        )
        db.add_all([first_position, second_position])
        db.commit()
        return owner, employee, first_position, second_position

    def test_owner_note_is_visible_only_to_owner_and_replaces_display_name(self):
        with Session(self.engine) as db:
            owner, employee, _first, _second = self._seed_people_and_positions(db)

            owner_notes = load_owner_notes(db, venue_id=5, viewer=owner, member_user_ids=[employee.id])
            employee_notes = load_owner_notes(db, venue_id=5, viewer=employee, member_user_ids=[employee.id])

            self.assertEqual(owner_notes, {2: "Бармен из филиала"})
            self.assertEqual(employee_notes, {})
            self.assertEqual(
                owner_display_name(owner_note=owner_notes[2], short_name=employee.short_name, user_id=employee.id),
                "Бармен из филиала",
            )

    def test_permissions_are_unioned_across_positions(self):
        with Session(self.engine) as db:
            _owner, employee, _first, _second = self._seed_people_and_positions(db)
            with patch.object(
                venue_permissions,
                "get_user_billing_access",
                return_value={"billing_access_mode": venue_permissions.BILLING_ACCESS_FULL},
            ):
                venue_permissions.require_venue_permission(
                    db,
                    venue_id=5,
                    user=employee,
                    permission_code="SHIFTS_VIEW",
                )
                venue_permissions.require_venue_permission(
                    db,
                    venue_id=5,
                    user=employee,
                    permission_code="PAYROLL_VIEW",
                )

    def test_selected_shift_position_can_be_changed_for_same_employee(self):
        with Session(self.engine) as db:
            owner, _employee, first_position, second_position = self._seed_people_and_positions(db)
            interval = ShiftInterval(
                id=31,
                venue_id=5,
                title="День",
                start_time=time(10, 0),
                end_time=time(18, 0),
                is_active=True,
            )
            shift = Shift(
                id=41,
                venue_id=5,
                date=date(2026, 8, 12),
                interval_id=31,
                shift_slot="DAY",
                is_active=True,
            )
            assignment = ShiftAssignment(
                id=51,
                shift_id=41,
                member_user_id=2,
                venue_position_id=first_position.id,
            )
            db.add_all([interval, shift, assignment])
            db.commit()

            with (
                patch.object(venue_shifts, "_require_schedule_editor"),
                patch.object(venue_shifts, "_recalculate_payroll_for_dates") as recalculate,
            ):
                result = venue_shifts.add_shift_assignment(
                    5,
                    41,
                    ShiftAssignmentAddIn(venue_position_id=second_position.id),
                    db,
                    owner,
                )

            db.refresh(assignment)
            self.assertEqual(result["mode"], "position_updated")
            self.assertEqual(assignment.venue_position_id, second_position.id)
            recalculate.assert_called_once()

    def test_removing_last_assigned_position_keeps_empty_role_template(self):
        with Session(self.engine) as db:
            owner, _employee, first_position, _second_position = self._seed_people_and_positions(db)

            with (
                patch.object(venue_positions, "_require_active_member_or_admin"),
                patch.object(venue_positions, "_is_owner_or_super_admin", return_value=True),
            ):
                result = venue_positions.delete_position(5, first_position.id, db, owner)

            db.refresh(first_position)
            kept_position = db.execute(
                venue_positions.select(VenuePosition).where(
                    VenuePosition.venue_id == 5,
                    VenuePosition.title == "Бармен",
                    VenuePosition.member_user_id.is_(None),
                    VenuePosition.is_active.is_(True),
                )
            ).scalar_one()
            self.assertEqual(result["mode"], "member_detached_position_kept")
            self.assertFalse(first_position.is_active)
            self.assertEqual(kept_position.pay_profile_id, first_position.pay_profile_id)
            self.assertEqual(kept_position.permission_codes, first_position.permission_codes)

    def test_payroll_metrics_are_split_by_selected_position_profile(self):
        with Session(self.engine) as db:
            owner, employee, first_position, second_position = self._seed_people_and_positions(db)
            legacy_profile = PayProfile(id=23, venue_id=5, title="Устаревший профиль", is_active=True)
            db.add(legacy_profile)
            first_position.is_active = False
            interval = ShiftInterval(
                id=31,
                venue_id=5,
                title="День",
                start_time=time(10, 0),
                end_time=time(18, 0),
                is_active=True,
            )
            first_shift = Shift(
                id=41,
                venue_id=5,
                date=date(2026, 8, 12),
                interval_id=31,
                shift_slot="DAY",
                is_active=True,
            )
            second_shift = Shift(
                id=42,
                venue_id=5,
                date=date(2026, 8, 13),
                interval_id=31,
                shift_slot="DAY",
                is_active=True,
            )
            db.add_all([interval, first_shift, second_shift])
            db.add_all(
                [
                    ShiftAssignment(
                        shift_id=41,
                        member_user_id=2,
                        venue_position_id=first_position.id,
                    ),
                    ShiftAssignment(
                        shift_id=42,
                        member_user_id=2,
                        venue_position_id=second_position.id,
                    ),
                    DailyReport(
                        venue_id=5,
                        date=date(2026, 8, 12),
                        shift_slot="DAY",
                        status="CLOSED",
                        created_by_user_id=owner.id,
                    ),
                    DailyReport(
                        venue_id=5,
                        date=date(2026, 8, 13),
                        shift_slot="DAY",
                        status="CLOSED",
                        created_by_user_id=owner.id,
                    ),
                ]
            )
            db.commit()

            contexts = load_position_payroll_contexts(
                db,
                venue_id=5,
                month_start=date(2026, 8, 1),
                month_end_excl=date(2026, 9, 1),
                fallback_assignments=[
                    (SimpleNamespace(member_user_id=employee.id), legacy_profile, employee),
                ],
            )

            by_profile = {int(context.profile.id): context for context in contexts}
            self.assertEqual(set(by_profile), {21, 22})
            self.assertEqual(by_profile[21].metrics.shifts_count, 1)
            self.assertEqual(by_profile[22].metrics.shifts_count, 1)
            self.assertEqual(by_profile[21].position_titles, {"Бармен"})
            self.assertEqual(by_profile[22].position_titles, {"Официант"})

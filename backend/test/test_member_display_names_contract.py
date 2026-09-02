from __future__ import annotations

from unittest import TestCase

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import User, VenueMember
from app.services.venue_member_names import (
    load_member_display_names,
    load_owner_notes,
)


class MemberDisplayNamesContractTests(TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")

        with self.engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE venues ("
                "id INTEGER PRIMARY KEY, "
                "name VARCHAR(200), "
                "is_archived BOOLEAN NOT NULL DEFAULT 0"
                ")"
            )
            connection.exec_driver_sql("INSERT INTO venues (id, name, is_archived) VALUES (5, 'Test venue', 0)")

        User.__table__.create(self.engine)
        VenueMember.__table__.create(self.engine)

    def test_owner_note_stays_private_but_display_label_is_available(self):
        with Session(self.engine) as db:
            owner = User(id=1, short_name="Owner")
            employee = User(id=2, short_name="Real name")

            db.add_all([owner, employee])
            db.add_all(
                [
                    VenueMember(
                        venue_id=5,
                        user_id=1,
                        venue_role="OWNER",
                        is_active=True,
                    ),
                    VenueMember(
                        venue_id=5,
                        user_id=2,
                        venue_role="STAFF",
                        owner_note="Бармен из филиала",
                        is_active=True,
                    ),
                ]
            )
            db.commit()

            owner_notes = load_owner_notes(
                db,
                venue_id=5,
                viewer=owner,
                member_user_ids=[employee.id],
            )
            employee_notes = load_owner_notes(
                db,
                venue_id=5,
                viewer=employee,
                member_user_ids=[employee.id],
            )
            display_names = load_member_display_names(
                db,
                venue_id=5,
                member_user_ids=[employee.id],
            )

            self.assertEqual(owner_notes, {2: "Бармен из филиала"})
            self.assertEqual(employee_notes, {})
            self.assertEqual(display_names, {2: "Бармен из филиала"})

from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.account_merge import merge_user_accounts
from app.core.db import Base
from app.models import (
    AuthIdentity,
    Expense,
    ExpenseAttachment,
    ExpenseCategory,
    QuickRestoConnection,
    QuickRestoSyncRun,
    ShiftScheduleTemplate,
    User,
    Venue,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class AccountMergeForeignKeyTests(unittest.TestCase):
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

    def test_user_owned_records_move_to_surviving_user(self):
        with Session(self.engine) as db:
            target = User(id=1, tg_user_id=1001, tg_username="target", short_name="Target")
            source = User(id=2, short_name="Source")
            venue = Venue(id=5, name="Merge test")
            db.add_all([target, source, venue])
            db.flush()
            category = ExpenseCategory(venue_id=venue.id, code="OTHER", title="Other")
            db.add(category)
            db.flush()
            expense = Expense(
                venue_id=venue.id,
                category_id=category.id,
                amount_minor=100,
                expense_date=date(2026, 8, 25),
                created_by_user_id=source.id,
            )
            connection = QuickRestoConnection(
                venue_id=venue.id,
                cloud="merge-test",
                api_login_encrypted="encrypted-login",
                api_password_encrypted="encrypted-password",
                created_by_user_id=source.id,
                updated_by_user_id=source.id,
            )
            template = ShiftScheduleTemplate(
                venue_id=venue.id,
                title="Source template",
                created_by_user_id=source.id,
            )
            db.add_all([expense, connection, template])
            db.flush()
            db.add_all(
                [
                    AuthIdentity(
                        user_id=target.id,
                        provider="TELEGRAM",
                        provider_user_id=str(target.tg_user_id),
                        is_verified=True,
                    ),
                    AuthIdentity(
                        user_id=source.id,
                        provider="PHONE",
                        phone_e164="+79990000002",
                        is_verified=True,
                    ),
                    ExpenseAttachment(
                        venue_id=venue.id,
                        expense_id=expense.id,
                        file_name="receipt.pdf",
                        content_type="application/pdf",
                        file_size=10,
                        storage_path="test/receipt.pdf",
                        uploaded_by_user_id=source.id,
                    ),
                    QuickRestoSyncRun(
                        connection_id=connection.id,
                        requested_by_user_id=source.id,
                        trigger="MANUAL",
                        status="SUCCESS",
                    ),
                ]
            )
            db.commit()

            merged = merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            identities = db.execute(select(AuthIdentity).order_by(AuthIdentity.provider)).scalars().all()

            self.assertEqual(merged.id, target.id)
            self.assertIsNone(db.get(User, source.id))
            self.assertEqual(db.execute(select(ShiftScheduleTemplate.created_by_user_id)).scalar_one(), target.id)
            self.assertEqual(db.execute(select(ExpenseAttachment.uploaded_by_user_id)).scalar_one(), target.id)
            self.assertEqual(db.execute(select(QuickRestoConnection.created_by_user_id)).scalar_one(), target.id)
            self.assertEqual(db.execute(select(QuickRestoConnection.updated_by_user_id)).scalar_one(), target.id)
            self.assertEqual(db.execute(select(QuickRestoSyncRun.requested_by_user_id)).scalar_one(), target.id)
            self.assertEqual({row.provider for row in identities}, {"PHONE", "TELEGRAM"})
            self.assertTrue(all(row.user_id == target.id for row in identities))


if __name__ == "__main__":
    unittest.main()

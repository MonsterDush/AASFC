from __future__ import annotations

import unittest

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.account_merge import merge_user_accounts
from app.auth.phone_auth import link_phone_identity_to_user, link_telegram_identity_to_user
from app.core.db import Base
from app.models import AuthIdentity, User


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class AuthIdentityRelinkForeignKeyTests(unittest.TestCase):
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

    @staticmethod
    def _provider_rows(db: Session, *, user_id: int, provider: str) -> list[AuthIdentity]:
        return (
            db.execute(
                select(AuthIdentity)
                .where(AuthIdentity.user_id == user_id, AuthIdentity.provider == provider)
                .order_by(AuthIdentity.id)
            )
            .scalars()
            .all()
        )

    def test_phone_relink_reuses_the_existing_provider_identity(self):
        with Session(self.engine) as db:
            user = User(id=1, short_name="Target")
            identity = AuthIdentity(
                user_id=user.id,
                provider="PHONE",
                phone_e164="+79990000001",
                is_verified=True,
            )
            db.add_all([user, identity])
            db.commit()
            identity_id = identity.id

            linked = link_phone_identity_to_user(db, user=user, phone_e164="+79990000002")
            db.commit()
            db.expire_all()

            rows = self._provider_rows(db, user_id=user.id, provider="PHONE")
            self.assertEqual(linked.id, identity_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, identity_id)
            self.assertEqual(rows[0].phone_e164, "+79990000002")
            self.assertTrue(rows[0].is_verified)

    def test_phone_relink_after_merge_keeps_one_verified_target_identity(self):
        with Session(self.engine) as db:
            target = User(id=1, short_name="Target")
            source = User(id=2, short_name="Source")
            target_identity = AuthIdentity(
                user_id=target.id,
                provider="PHONE",
                phone_e164="+79990000001",
                is_verified=True,
            )
            source_identity = AuthIdentity(
                user_id=source.id,
                provider="PHONE",
                phone_e164="+79990000002",
                is_verified=True,
            )
            db.add_all([target, source, target_identity, source_identity])
            db.commit()
            target_identity_id = target_identity.id
            source_id = source.id

            merged = merge_user_accounts(db, target_user=target, source_user=source)
            linked = link_phone_identity_to_user(db, user=merged, phone_e164="+79990000002")
            db.commit()
            db.expire_all()

            rows = self._provider_rows(db, user_id=target.id, provider="PHONE")
            self.assertIsNone(db.get(User, source_id))
            self.assertEqual(linked.id, target_identity_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, target_identity_id)
            self.assertEqual(rows[0].phone_e164, "+79990000002")
            self.assertTrue(rows[0].is_verified)

    def test_telegram_relink_reuses_the_existing_provider_identity(self):
        with Session(self.engine) as db:
            user = User(id=1, tg_user_id=1001, tg_username="target", short_name="Target")
            identity = AuthIdentity(
                user_id=user.id,
                provider="TELEGRAM",
                provider_user_id="1001",
                is_verified=True,
            )
            db.add_all([user, identity])
            db.commit()
            identity_id = identity.id

            linked = link_telegram_identity_to_user(
                db,
                user=user,
                tg_user_id=1002,
                tg_username="replacement",
            )
            db.commit()
            db.expire_all()

            rows = self._provider_rows(db, user_id=user.id, provider="TELEGRAM")
            self.assertEqual(linked.id, identity_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, identity_id)
            self.assertEqual(rows[0].provider_user_id, "1002")
            self.assertTrue(rows[0].is_verified)
            self.assertEqual(db.get(User, user.id).tg_user_id, 1002)
            self.assertEqual(db.get(User, user.id).tg_username, "replacement")

    def test_telegram_relink_after_merge_keeps_one_verified_target_identity(self):
        with Session(self.engine) as db:
            target = User(id=1, tg_user_id=1001, tg_username="target", short_name="Target")
            source = User(id=2, tg_user_id=1002, tg_username="source", short_name="Source")
            target_identity = AuthIdentity(
                user_id=target.id,
                provider="TELEGRAM",
                provider_user_id="1001",
                is_verified=True,
            )
            source_identity = AuthIdentity(
                user_id=source.id,
                provider="TELEGRAM",
                provider_user_id="1002",
                is_verified=True,
            )
            db.add_all([target, source, target_identity, source_identity])
            db.commit()
            target_identity_id = target_identity.id
            source_id = source.id

            merged = merge_user_accounts(db, target_user=target, source_user=source)
            linked = link_telegram_identity_to_user(
                db,
                user=merged,
                tg_user_id=1002,
                tg_username="replacement",
            )
            db.commit()
            db.expire_all()

            rows = self._provider_rows(db, user_id=target.id, provider="TELEGRAM")
            self.assertIsNone(db.get(User, source_id))
            self.assertEqual(linked.id, target_identity_id)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, target_identity_id)
            self.assertEqual(rows[0].provider_user_id, "1002")
            self.assertTrue(rows[0].is_verified)
            self.assertEqual(db.get(User, target.id).tg_user_id, 1002)
            self.assertEqual(db.get(User, target.id).tg_username, "replacement")


if __name__ == "__main__":
    unittest.main()

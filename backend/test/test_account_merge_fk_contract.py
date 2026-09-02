from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.auth.account_merge import (
    _DELIBERATE_DB_USER_REF_POLICIES,
    _DIRECT_USER_REF_REASSIGNMENTS,
    _SPECIALIZED_USER_REFS,
    merge_user_accounts,
)
from app.core.db import Base
from app.models import (
    BillingPromoCode,
    BillingReconciliationIssue,
    DemoEvent,
    PositionPermissionTemplate,
    Shift,
    ShiftComment,
    ShiftCommentMention,
    ShiftInterval,
    TelegramBrowserAuthSession,
    User,
    Venue,
    VenueBillingEvent,
    VenueBillingTransaction,
    VenueSetupState,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


@compiles(ARRAY, "sqlite")
def _compile_array_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


SPECIALIZED_MERGE_USER_FKS = {
    "auth_identities.user_id",
    "daily_report_tip_allocations.user_id",
    "pay_profile_assignments.member_user_id",
    "payroll_lines.member_user_id",
    "shift_assignments.member_user_id",
    "shift_availabilities.member_user_id",
    "shift_comment_mentions.mentioned_user_id",
    "shift_swap_requests.replacement_user_id",
    "shift_swap_requests.requester_user_id",
    "venue_members.user_id",
    "venue_positions.member_user_id",
}

DIRECT_REASSIGN_USER_FKS = {
    "adjustment_dispute_comments.author_user_id",
    "adjustment_disputes.created_by_user_id",
    "adjustment_disputes.resolved_by_user_id",
    "adjustments.created_by_user_id",
    "adjustments.member_user_id",
    "adjustments.updated_by_user_id",
    "balance_adjustments.created_by_user_id",
    "billing_promo_code.created_by_user_id",
    "billing_reconciliation_issue.resolved_by_user_id",
    "bonuses.created_by_user_id",
    "bonuses.member_user_id",
    "daily_report_attachments.uploaded_by_user_id",
    "daily_report_audit.user_id",
    "daily_reports.closed_by_user_id",
    "daily_reports.created_by_user_id",
    "daily_reports.updated_by_user_id",
    "demo_events.user_id",
    "expense_attachments.uploaded_by_user_id",
    "expenses.created_by_user_id",
    "notification_delivery_logs.user_id",
    "payment_method_transfers.created_by_user_id",
    "payroll_recalculation_logs.triggered_by_user_id",
    "payroll_runs.calculated_by_user_id",
    "penalties.created_by_user_id",
    "penalties.member_user_id",
    "position_permission_templates.created_by_user_id",
    "position_permission_templates.updated_by_user_id",
    "quickresto_connections.created_by_user_id",
    "quickresto_connections.scope_confirmed_by_user_id",
    "quickresto_connections.updated_by_user_id",
    "quickresto_import_issue_audits.actor_user_id",
    "quickresto_import_issues.resolved_by_user_id",
            "quickresto_sale_place_scopes.confirmed_by_user_id",
            "quickresto_shift_imports.scope_resolved_by_user_id",
            "quickresto_scope_audits.actor_user_id",
    "quickresto_sync_runs.requested_by_user_id",
    "recurring_expense_rules.created_by_user_id",
    "shift_comments.author_user_id",
    "shift_schedule_templates.created_by_user_id",
    "shift_swap_requests.decided_by_user_id",
    "shifts.created_by_user_id",
    "venue_billing_event.created_by_user_id",
    "venue_billing_transaction.created_by_user_id",
    "venue_invites.accepted_user_id",
    "venue_invites.created_by_user_id",
    "venue_setup_state.last_seen_by_user_id",
    "writeoffs.created_by_user_id",
    "writeoffs.member_user_id",
}

DELIBERATE_DATABASE_POLICY_USER_FKS = {
    "telegram_browser_auth_sessions.user_id": "SET NULL",
}


class AccountMergeUserForeignKeyContractTests(unittest.TestCase):
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

    def test_every_user_foreign_key_has_an_explicit_merge_policy(self):
        actual_foreign_keys = {}
        for table in Base.metadata.tables.values():
            for foreign_key in table.foreign_keys:
                if foreign_key.target_fullname != "users.id":
                    continue
                key = f"{table.name}.{foreign_key.parent.name}"
                actual_foreign_keys[key] = foreign_key

        expected_classified_keys = (
            SPECIALIZED_MERGE_USER_FKS | DIRECT_REASSIGN_USER_FKS | set(DELIBERATE_DATABASE_POLICY_USER_FKS)
        )
        self.assertEqual(
            set(actual_foreign_keys),
            expected_classified_keys,
            "Every new users.id FK must declare how account merge handles it",
        )
        self.assertFalse(SPECIALIZED_MERGE_USER_FKS & DIRECT_REASSIGN_USER_FKS)
        self.assertFalse(SPECIALIZED_MERGE_USER_FKS & DELIBERATE_DATABASE_POLICY_USER_FKS.keys())
        self.assertFalse(DIRECT_REASSIGN_USER_FKS & DELIBERATE_DATABASE_POLICY_USER_FKS.keys())

        for key, expected_ondelete in DELIBERATE_DATABASE_POLICY_USER_FKS.items():
            foreign_key = actual_foreign_keys[key]
            self.assertEqual(foreign_key.ondelete, expected_ondelete)
            self.assertTrue(foreign_key.parent.nullable)

        self.assertEqual(
            DELIBERATE_DATABASE_POLICY_USER_FKS,
            {"telegram_browser_auth_sessions.user_id": "SET NULL"},
            "Only an in-flight Telegram browser auth session may deliberately lose its user reference",
        )

        implemented_direct_reassignments = {
            f"{model.__table__.name}.{column_name}" for model, column_name in _DIRECT_USER_REF_REASSIGNMENTS
        }
        implemented_specialized_refs = {
            f"{table_name}.{column_name}" for table_name, column_name in _SPECIALIZED_USER_REFS
        }
        implemented_database_policies = {
            f"{table_name}.{column_name}": policy
            for (table_name, column_name), policy in _DELIBERATE_DB_USER_REF_POLICIES.items()
        }
        self.assertEqual(implemented_direct_reassignments, DIRECT_REASSIGN_USER_FKS)
        self.assertEqual(implemented_specialized_refs, SPECIALIZED_MERGE_USER_FKS)
        self.assertEqual(implemented_database_policies, DELIBERATE_DATABASE_POLICY_USER_FKS)

    def test_shift_comment_mentions_are_preserved_and_deduplicated(self):
        with Session(self.engine) as db:
            target, source = self._add_users(db)
            venue = Venue(id=10, name="Mention merge")
            interval = ShiftInterval(
                id=20,
                venue_id=venue.id,
                title="Day",
                start_time=time(9),
                end_time=time(18),
            )
            shift = Shift(
                id=30,
                venue_id=venue.id,
                date=date(2026, 8, 30),
                interval_id=interval.id,
                created_by_user_id=target.id,
            )
            db.add_all([venue, interval, shift])
            db.flush()

            source_only_comment = ShiftComment(
                id=40,
                shift_id=shift.id,
                author_user_id=target.id,
                text="Source-only mention",
            )
            duplicate_comment = ShiftComment(
                id=41,
                shift_id=shift.id,
                author_user_id=target.id,
                text="Both users mentioned",
            )
            db.add_all([source_only_comment, duplicate_comment])
            db.flush()
            source_only_mention = ShiftCommentMention(
                comment_id=source_only_comment.id,
                mentioned_user_id=source.id,
            )
            db.add_all(
                [
                    source_only_mention,
                    ShiftCommentMention(
                        comment_id=duplicate_comment.id,
                        mentioned_user_id=target.id,
                    ),
                    ShiftCommentMention(
                        comment_id=duplicate_comment.id,
                        mentioned_user_id=source.id,
                    ),
                ]
            )
            db.commit()
            source_only_mention_id = source_only_mention.id

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            mentions = db.execute(
                select(ShiftCommentMention).order_by(ShiftCommentMention.comment_id, ShiftCommentMention.id)
            ).scalars()
            mentions_by_comment = {}
            for mention in mentions:
                mentions_by_comment.setdefault(mention.comment_id, []).append(mention)

            self.assertEqual(
                [(row.id, row.mentioned_user_id) for row in mentions_by_comment[source_only_comment.id]],
                [(source_only_mention_id, target.id)],
            )
            self.assertEqual(
                [row.mentioned_user_id for row in mentions_by_comment[duplicate_comment.id]],
                [target.id],
            )

    def test_audit_and_history_user_references_move_to_surviving_user(self):
        with Session(self.engine) as db:
            target, source = self._add_users(db)
            venue = Venue(id=10, name="History merge")
            db.add(venue)
            db.flush()

            promo = BillingPromoCode(
                code="MERGE-HISTORY",
                title="Merge history",
                kind="PERCENT",
                percent_value=10,
                created_by_user_id=source.id,
            )
            issue = BillingReconciliationIssue(
                venue_id=venue.id,
                issue_code="MERGE_HISTORY",
                severity="WARNING",
                status="RESOLVED",
                fingerprint="merge-history",
                resolved_by_user_id=source.id,
            )
            demo_event = DemoEvent(
                venue_id=venue.id,
                user_id=source.id,
                event_name="account_merge_test",
            )
            permission_template = PositionPermissionTemplate(
                code="MERGE_HISTORY",
                title="Merge history",
                created_by_user_id=source.id,
                updated_by_user_id=source.id,
            )
            billing_event = VenueBillingEvent(
                venue_id=venue.id,
                event_type="ACCOUNT_MERGE_TEST",
                created_by_user_id=source.id,
            )
            billing_transaction = VenueBillingTransaction(
                venue_id=venue.id,
                source="MANUAL",
                type="ADJUSTMENT",
                status="SUCCEEDED",
                amount_minor=100,
                created_by_user_id=source.id,
            )
            setup_state = VenueSetupState(
                venue_id=venue.id,
                last_seen_by_user_id=source.id,
            )
            db.add_all(
                [
                    promo,
                    issue,
                    demo_event,
                    permission_template,
                    billing_event,
                    billing_transaction,
                    setup_state,
                ]
            )
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            self.assertEqual(db.get(BillingPromoCode, promo.id).created_by_user_id, target.id)
            self.assertEqual(db.get(BillingReconciliationIssue, issue.id).resolved_by_user_id, target.id)
            self.assertEqual(db.get(DemoEvent, demo_event.id).user_id, target.id)
            stored_template = db.get(PositionPermissionTemplate, permission_template.id)
            self.assertEqual(stored_template.created_by_user_id, target.id)
            self.assertEqual(stored_template.updated_by_user_id, target.id)
            self.assertEqual(db.get(VenueBillingEvent, billing_event.id).created_by_user_id, target.id)
            self.assertEqual(db.get(VenueBillingTransaction, billing_transaction.id).created_by_user_id, target.id)
            self.assertEqual(db.get(VenueSetupState, setup_state.id).last_seen_by_user_id, target.id)

    def test_telegram_browser_auth_session_is_invalidated_by_database_policy(self):
        with Session(self.engine) as db:
            target, source = self._add_users(db)
            session = TelegramBrowserAuthSession(
                public_token="merge-invalidates-session",
                status="COMPLETED",
                user_id=source.id,
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
            )
            db.add(session)
            db.commit()

            merge_user_accounts(db, target_user=target, source_user=source)
            db.commit()
            db.expire_all()

            self.assertIsNone(db.get(TelegramBrowserAuthSession, session.id).user_id)

    @staticmethod
    def _add_users(db: Session) -> tuple[User, User]:
        target = User(id=1, tg_user_id=1001, tg_username="target", short_name="Target")
        source = User(id=2, short_name="Source")
        db.add_all([target, source])
        db.flush()
        return target, source


if __name__ == "__main__":
    unittest.main()

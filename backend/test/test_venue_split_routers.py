from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.routers import (
    venue_adjustments,
    venue_catalogs,
    venue_finance_summary,
    venue_ledger,
    venue_membership,
    venue_pay_profiles,
    venue_payroll,
    venue_positions,
    venue_recurring_expenses,
    venue_reports,
    venue_schedule_templates,
    venue_shift_notifications,
    venue_shifts,
)
from app.schemas.venue_core import InviteCreateIn
from app.schemas.venue_payroll import PayrollCalculateIn
from app.models import NotificationJob, Shift, ShiftComment, ShiftCommentMention, User


class VenueCatalogRouterTests(TestCase):
    def test_catalog_code_normalization_keeps_validation_contract(self):
        self.assertEqual(venue_catalogs._normalize_code(" Cash Less "), "cash_less")
        with self.assertRaises(HTTPException) as raised:
            venue_catalogs._normalize_code("касса")
        self.assertEqual(raised.exception.status_code, 400)


class VenueFinanceSummaryRouterTests(TestCase):
    def test_all_summary_routes_keep_guards_delegation_and_sanitizing(self):
        db = SimpleNamespace()
        user = SimpleNamespace(id=17)
        target_date = date(2026, 7, 18)

        with patch.object(venue_finance_summary, "_require_active_member_or_admin") as active, \
             patch.object(venue_finance_summary, "_require_revenue_viewer") as revenue, \
             patch.object(venue_finance_summary, "_require_report_viewer") as reports, \
             patch.object(venue_finance_summary, "get_monthly_finance_summary", return_value={"kind": "monthly"}), \
             patch.object(venue_finance_summary, "get_day_finance_summary", return_value={"kind": "daily"}), \
             patch.object(venue_finance_summary, "get_finance_summary", return_value={"kind": "finance"}), \
             patch.object(venue_finance_summary, "sanitize_financial_payload_for_user", side_effect=lambda current_user, payload: payload):
            monthly = venue_finance_summary.get_venue_monthly_finance_summary(
                5, "2026-07", None, None, "PAYMENTS", db, user
            )
            daily = venue_finance_summary.get_venue_day_finance_summary(
                5, target_date, "DEPARTMENTS", db, user
            )
            finance = venue_finance_summary.get_venue_finance_summary(
                5, "2026-07", None, None, db, user
            )

        self.assertEqual(monthly, {"kind": "monthly"})
        self.assertEqual(daily, {"kind": "daily"})
        self.assertEqual(finance, {"kind": "finance"})
        self.assertEqual(active.call_count, 3)
        self.assertEqual(revenue.call_count, 3)
        self.assertEqual(reports.call_count, 3)


class VenueLedgerRouterTests(TestCase):
    def test_ledger_serializers_preserve_minor_units_and_nested_catalogs(self):
        payment_method = SimpleNamespace(id=2, code="cash", title="Наличные")
        department = SimpleNamespace(id=3, code="bar", title="Бар")
        entry = SimpleNamespace(
            id=1,
            venue_id=5,
            entry_date=date(2026, 7, 18),
            amount_minor=12_345,
            direction="IN",
            kind="REVENUE",
            source_type="report",
            source_id=7,
            meta_json=None,
            created_at=None,
        )

        payload = venue_ledger._serialize_finance_entry(entry, payment_method, department)

        self.assertEqual(payload["amount_minor"], 12_345)
        self.assertEqual(payload["payment_method"]["code"], "cash")
        self.assertEqual(payload["department"]["title"], "Бар")


class VenueRecurringExpenseRouterTests(TestCase):
    def test_recurring_rule_serializer_preserves_payment_method_basis(self):
        category = SimpleNamespace(id=1, code="rent", title="Аренда")
        payment_method = SimpleNamespace(id=2, code="cash", title="Наличные")
        rule = SimpleNamespace(
            id=7,
            venue_id=5,
            title="Аренда",
            category_id=1,
            supplier_id=None,
            payment_method_id=2,
            is_active=True,
            start_date=date(2026, 1, 1),
            end_date=None,
            frequency="MONTHLY",
            day_of_month=1,
            generation_mode="FIXED",
            amount_minor=100_000,
            percent_bps=None,
            spread_months=1,
            description=None,
            created_by_user_id=17,
            created_at=None,
            updated_at=None,
        )

        payload = venue_recurring_expenses._serialize_recurring_expense_rule(
            rule,
            category,
            None,
            payment_method,
            [payment_method],
        )

        self.assertEqual(payload["amount_minor"], 100_000)
        self.assertEqual(payload["payment_method_ids"], [2])
        self.assertEqual(payload["category"]["code"], "rent")


class VenuePayrollRouterTests(TestCase):
    def test_calculate_route_keeps_guards_log_commit_and_sanitizing(self):
        class Db:
            commits = 0
            rollbacks = 0

            def commit(self):
                self.commits += 1

            def rollback(self):
                self.rollbacks += 1

        db = Db()
        user = SimpleNamespace(id=17)
        payload = PayrollCalculateIn(month="2026-07")

        with patch.object(venue_payroll, "_require_active_member_or_admin"), \
             patch.object(venue_payroll, "_require_payroll_calculate"), \
             patch.object(venue_payroll, "calculate_payroll_for_month") as calculate, \
             patch.object(venue_payroll, "_create_payroll_recalculation_log") as create_log, \
             patch.object(venue_payroll, "_load_payroll_payload", return_value={"month": "2026-07"}), \
             patch.object(venue_payroll, "sanitize_financial_payload_for_user", side_effect=lambda current_user, result: result):
            result = venue_payroll.calculate_payroll(5, payload, db, user)

        self.assertEqual(result, {"month": "2026-07"})
        self.assertEqual(db.commits, 1)
        self.assertEqual(db.rollbacks, 0)
        calculate.assert_called_once_with(db=db, venue_id=5, month="2026-07", calculated_by_user_id=17)
        create_log.assert_called_once()


class VenueReportRouterTests(TestCase):
    def test_report_totals_keep_department_and_legacy_revenue_modes(self):
        values = [
            SimpleNamespace(kind="PAYMENT", value_numeric=800),
            SimpleNamespace(kind="DEPT", value_numeric=650),
        ]
        report = SimpleNamespace(revenue_total=700)

        department_totals = venue_reports._compute_report_totals(
            report=report,
            values=values,
            has_departments=True,
        )
        legacy_totals = venue_reports._compute_report_totals(
            report=report,
            values=values,
            has_departments=False,
        )

        self.assertEqual(department_totals["discrepancy"], 150)
        self.assertEqual(legacy_totals["discrepancy"], 100)


class VenuePeopleRouterTests(TestCase):
    def test_position_presets_and_pay_profile_detail_keep_delegation(self):
        db = SimpleNamespace()
        user = SimpleNamespace(id=17)

        with patch.object(venue_positions, "_require_active_member_or_admin"), \
             patch.object(venue_positions, "_is_owner_or_super_admin", return_value=True), \
             patch.object(venue_positions, "_load_position_presets_from_setup", return_value=[{"code": "bar"}]) as load_presets:
            presets = venue_positions.list_position_presets(5, False, db, user)

        with patch.object(venue_pay_profiles, "_require_active_member_or_admin"), \
             patch.object(venue_pay_profiles, "_require_pay_profiles_view"), \
             patch.object(venue_pay_profiles, "_load_pay_profile_detail", return_value={"id": 3}) as load_profile:
            profile = venue_pay_profiles.get_pay_profile(5, 3, db, user)

        self.assertEqual(presets, {"items": [{"code": "bar"}]})
        self.assertEqual(profile, {"id": 3})
        load_presets.assert_called_once_with(db, venue_id=5, include_inactive=False)
        load_profile.assert_called_once_with(db, venue_id=5, profile_id=3)

    def test_invite_route_rejects_unknown_role_before_database_work(self):
        payload = InviteCreateIn(tg_username="staff", venue_role="UNKNOWN")
        with patch.object(venue_membership, "_require_staff_manage_or_owner_or_super_admin"), \
             patch.object(venue_membership, "_is_owner_or_super_admin", return_value=True):
            with self.assertRaises(HTTPException) as raised:
                venue_membership.create_invite(5, payload, SimpleNamespace(), SimpleNamespace(id=17))
        self.assertEqual(raised.exception.status_code, 400)


class VenueAdjustmentAndScheduleRouterTests(TestCase):
    def test_adjustments_reject_mixed_period_filters(self):
        with patch.object(venue_adjustments, "_require_active_member_or_admin"), \
             patch.object(venue_adjustments, "_require_adjustments_viewer"):
            with self.assertRaises(HTTPException) as raised:
                venue_adjustments.list_adjustments(
                    5,
                    "2026-07",
                    date(2026, 7, 1),
                    date(2026, 7, 31),
                    0,
                    None,
                    SimpleNamespace(),
                    SimpleNamespace(id=17),
                )
        self.assertEqual(raised.exception.status_code, 400)

    def test_shift_comment_mentions_are_deduplicated_and_require_visible_tokens(self):
        user = SimpleNamespace(
            id=17,
            short_name="Анна",
            full_name="Анна Иванова",
            tg_username="anna",
        )

        self.assertEqual(
            venue_shifts._normalize_shift_comment_mention_ids([17, 17, 8, 0, -1]),
            [17, 8],
        )
        self.assertTrue(venue_shifts._shift_comment_has_mention_token("Проверь, пожалуйста, @Анна", user))
        self.assertTrue(venue_shifts._shift_comment_has_mention_token("Ответ для @anna", user))
        self.assertFalse(venue_shifts._shift_comment_has_mention_token("Другой сотрудник: @Анна2", user))
        self.assertFalse(venue_shifts._shift_comment_has_mention_token("Обычный комментарий", user))

    def test_shift_comment_route_persists_mentions_reply_and_notification_job(self):
        engine = create_engine("sqlite://")
        for table in (
            User.__table__,
            Shift.__table__,
            ShiftComment.__table__,
            ShiftCommentMention.__table__,
            NotificationJob.__table__,
        ):
            table.create(engine)

        with Session(engine) as db:
            author = User(id=1, short_name="Игорь")
            mentioned = User(id=2, short_name="Анна", tg_username="anna")
            parent_author = User(id=3, short_name="Мария")
            shift = Shift(id=10, venue_id=5, date=date(2026, 7, 28), interval_id=7, is_active=True)
            db.add_all([author, mentioned, parent_author, shift])
            db.flush()
            parent = ShiftComment(shift_id=10, author_user_id=3, text="Проверьте зал")
            db.add(parent)
            db.commit()
            db.refresh(parent)

            background_tasks = BackgroundTasks()
            payload = venue_shifts.ShiftCommentIn(
                text="@Анна, ответ по залу готов",
                mentioned_user_ids=[2],
                reply_to_comment_id=int(parent.id),
            )
            with patch.object(venue_shifts, "_require_shift_comments_allowed"), \
                 patch.object(
                     venue_shifts,
                     "_load_shift_comment_mentionable_members",
                     return_value=[(mentioned, "STAFF", "Администратор")],
                 ):
                result = venue_shifts.add_shift_comment(
                    5,
                    10,
                    payload,
                    background_tasks,
                    db,
                    author,
                )

            saved = db.execute(
                select(ShiftComment).where(ShiftComment.id == int(result["id"]))
            ).scalar_one()
            mention = db.execute(
                select(ShiftCommentMention).where(ShiftCommentMention.comment_id == int(saved.id))
            ).scalar_one()
            job = db.execute(
                select(NotificationJob).where(NotificationJob.job_type == "shift_comment")
            ).scalar_one()

            self.assertEqual(saved.parent_comment_id, int(parent.id))
            self.assertEqual(mention.mentioned_user_id, 2)
            self.assertEqual(result["mentions"][0]["display_name"], "Анна")
            self.assertEqual(result["reply_to"]["author"]["display_name"], "Мария")
            self.assertEqual(job.idempotency_key, f"job:shift_comment:{int(saved.id)}")
            self.assertEqual(len(background_tasks.tasks), 1)

    def test_shift_comment_notification_targets_assignees_mentions_and_reply_author(self):
        author = SimpleNamespace(id=1, short_name="Игорь", tg_user_id=101)
        assigned = SimpleNamespace(id=2, short_name="Олег", tg_user_id=102)
        mentioned = SimpleNamespace(id=3, short_name="Анна", tg_user_id=103)
        parent_author = SimpleNamespace(id=4, short_name="Мария", tg_user_id=104)
        disabled = SimpleNamespace(
            id=5,
            short_name="Борис",
            tg_user_id=105,
            notify_enabled=True,
            notify_shift_comments=False,
        )
        comment = SimpleNamespace(
            id=12,
            shift_id=10,
            parent_comment_id=11,
            author_user_id=1,
            text="@Анна, подготовка зала завершена",
        )
        shift = SimpleNamespace(id=10, date=date(2026, 7, 28))
        interval = SimpleNamespace(start_time=time(18, 0))
        venue = SimpleNamespace(id=5, name="Axelio Lounge")
        assignment_rows = [
            (SimpleNamespace(id=21), assigned),
            (SimpleNamespace(id=22), disabled),
            (SimpleNamespace(id=23), author),
        ]
        mention_rows = [(SimpleNamespace(id=31), mentioned)]

        db = SimpleNamespace(
            execute=Mock(
                side_effect=[
                    SimpleNamespace(first=lambda: (comment, shift, interval, venue, author)),
                    SimpleNamespace(all=lambda: assignment_rows),
                    SimpleNamespace(all=lambda: mention_rows),
                    SimpleNamespace(scalar_one_or_none=lambda: parent_author),
                ]
            )
        )
        delivered: list[dict] = []

        def capture_delivery(_db, **kwargs):
            delivered.append(kwargs)
            return True, False

        with patch.object(
            venue_shift_notifications,
            "_deliver_user_notification",
            side_effect=capture_delivery,
        ), patch.object(
            venue_shift_notifications,
            "_frontend_base_url",
            return_value="https://app.example.test",
        ), patch.object(
            venue_shift_notifications,
            "_is_shift_comments_allowed",
            return_value=True,
        ):
            venue_shift_notifications._send_shift_comment_notifications(
                db,
                venue_id=5,
                comment_id=12,
            )

        by_user_id = {int(item["recipient"].id): item for item in delivered}
        self.assertEqual(set(by_user_id), {2, 3, 4})
        self.assertIn("Новый комментарий к вашей смене", by_user_id[2]["text"])
        self.assertIn("Вас упомянули в комментарии", by_user_id[3]["text"])
        self.assertIn("Вам ответили в комментариях", by_user_id[4]["text"])
        self.assertEqual(by_user_id[2]["shift_assignment_id"], 21)
        self.assertIsNone(by_user_id[3]["shift_assignment_id"])
        self.assertIn("open_shift=10&comment=12", by_user_id[4]["url"])

    def test_schedule_helpers_keep_month_bounds_slots_and_deep_link(self):
        start, end_exclusive, end = venue_schedule_templates._parse_shift_schedule_template_month("2026-07")
        path = venue_shifts._build_staff_shifts_deep_link_path(
            venue_id=5,
            view="month",
            period_start=start,
            interval_ids=[3, 4],
            staffing_state="unstaffed",
            shift_slot="NIGHT",
        )

        self.assertEqual(start, date(2026, 7, 1))
        self.assertEqual(end, date(2026, 7, 31))
        self.assertEqual(end_exclusive, date(2026, 8, 1))
        self.assertEqual(venue_schedule_templates._shift_slot_label("NIGHT"), "Ночь")
        self.assertIn("month=2026-07", path)
        self.assertIn("intervals=3%2C4", path)
        self.assertIn("unstaffed=1", path)

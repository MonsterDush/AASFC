from __future__ import annotations

import hashlib
import json
from datetime import date
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from fastapi import HTTPException

from app.routers import (
    venue_catalogs,
    venue_economics,
    venue_expenses,
    venue_finance,
    venue_finance_summary,
    venue_ledger,
    venue_recurring_expenses,
    venues,
)
from app.schemas.venue_economics import (
    DayEconomicsMonthPlanIn,
    DayEconomicsPlanIn,
    DayEconomicsPlanTemplateIn,
    DayEconomicsTemplateCopyIn,
    DepartmentPlanBulkIn,
    VenueEconomicsRulesIn,
)
from app.services.payroll.calculator import (
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN,
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN,
    BOOST_SOURCE_VENUE_DAY_PLAN,
    BOOST_SOURCE_VENUE_MONTH_PLAN,
)


EXPECTED_VENUES_ROUTE_MANIFEST_SHA256 = "cdb3ca78e0241f226ed055e16f4a1f5d1db8bc18fab47f618d77efbcad4333cc"


def _route_manifest(router) -> list[tuple[list[str], str, str]]:
    return sorted(
        (sorted(getattr(route, "methods", set())), route.path, route.name)
        for route in router.routes
    )


class VenueEconomicsRouterContractTests(TestCase):
    def test_all_venue_routes_keep_original_public_manifest(self):
        manifest = _route_manifest(venues.router)
        digest = hashlib.sha256(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

        self.assertEqual(len(manifest), 146)
        self.assertEqual(digest, EXPECTED_VENUES_ROUTE_MANIFEST_SHA256)

    def test_extracted_router_owns_all_twenty_economics_routes(self):
        extracted = _route_manifest(venue_economics.router)
        aggregated = [row for row in _route_manifest(venues.router) if "/economics/" in row[1]]

        self.assertEqual(len(extracted), 20)
        self.assertEqual(len(aggregated), 20)
        self.assertEqual(
            {(methods[0], f"/venues{path}", name) for methods, path, name in extracted},
            {(methods[0], path, name) for methods, path, name in aggregated},
        )

    def test_all_split_router_routes_are_registered_in_venues(self):
        expected_counts = [
            (venue_catalogs.router, 15),
            (venue_expenses.router, 10),
            (venue_ledger.router, 9),
            (venue_recurring_expenses.router, 5),
            (venue_finance_summary.router, 3),
            (venue_finance.router, 27),
        ]
        venues_manifest = {
            (tuple(methods), path, name)
            for methods, path, name in _route_manifest(venues.router)
        }

        for split_router, expected_count in expected_counts:
            manifest = _route_manifest(split_router)
            self.assertEqual(len(manifest), expected_count)
            for methods, path, name in manifest:
                self.assertIn((tuple(methods), f"/venues{path}", name), venues_manifest)

        finance_children = {
            (tuple(methods), path, name)
            for child in (
                venue_expenses.router,
                venue_ledger.router,
                venue_recurring_expenses.router,
                venue_finance_summary.router,
            )
            for methods, path, name in _route_manifest(child)
        }
        self.assertEqual(
            finance_children,
            {(tuple(methods), path, name) for methods, path, name in _route_manifest(venue_finance.router)},
        )


class VenueEconomicsRouterBehaviorTests(TestCase):
    def setUp(self):
        self.user = SimpleNamespace(id=17, system_role="NONE")

        class CommitDb:
            def __init__(self):
                self.commits = 0

            def commit(self):
                self.commits += 1

        self.db = CommitDb()
        self.usage_map = {
            BOOST_SOURCE_VENUE_DAY_PLAN: {"usage_component_count": 2, "usage_profile_count": 1},
            BOOST_SOURCE_VENUE_MONTH_PLAN: {"usage_component_count": 3, "usage_profile_count": 2},
            BOOST_SOURCE_DEPARTMENT_DAY_PLAN: {4: {"usage_component_count": 4, "usage_profile_count": 2}},
            BOOST_SOURCE_DEPARTMENT_MONTH_PLAN: {4: {"usage_component_count": 5, "usage_profile_count": 3}},
        }
    def test_read_route_checks_access_and_sanitizes_payload(self):
        target_date = date(2026, 7, 18)
        raw_payload = {"date": target_date, "revenue_minor": 900}
        sanitized = {"date": target_date, "revenue_minor": 0}

        with patch.object(venue_economics, "_require_economics_view") as require_view, \
             patch.object(venue_economics, "get_day_economics", return_value=raw_payload) as get_day, \
             patch.object(venue_economics, "sanitize_financial_payload_for_user", return_value=sanitized) as sanitize:
            result = venue_economics.get_venue_day_economics(
                venue_id=5,
                economics_date=target_date,
                db=self.db,
                user=self.user,
            )

        self.assertIs(result, sanitized)
        require_view.assert_called_once_with(self.db, venue_id=5, user=self.user)
        get_day.assert_called_once_with(db=self.db, venue_id=5, target_date=target_date)
        sanitize.assert_called_once_with(self.user, raw_payload)

    def test_write_route_preserves_service_arguments_commit_and_usage(self):
        target_date = date(2026, 7, 18)
        payload = DayEconomicsPlanIn(
            revenue_plan_minor=100_000,
            profit_plan_minor=25_000,
            revenue_per_assigned_plan_minor=20_000,
            assigned_user_target=5,
            day_kind="SPECIAL",
            title="Фестиваль",
            notes="Усиленная смена",
        )
        plan = {"date": target_date, "source": "DATE_OVERRIDE"}
        usage_map = {
            BOOST_SOURCE_VENUE_DAY_PLAN: {
                "usage_component_count": 2,
                "usage_profile_count": 1,
            }
        }

        with patch.object(venue_economics, "require_owner_or_super_admin") as require_owner, \
             patch.object(venue_economics, "upsert_day_economics_plan", return_value=plan) as upsert, \
             patch.object(venue_economics, "_build_percent_boost_usage_map", return_value=usage_map):
            result = venue_economics.put_venue_day_economics_plan(
                venue_id=5,
                payload=payload,
                economics_date=target_date,
                db=self.db,
                user=self.user,
            )

        require_owner.assert_called_once_with(self.db, venue_id=5, user=self.user)
        upsert.assert_called_once_with(
            db=self.db,
            venue_id=5,
            target_date=target_date,
            revenue_plan_minor=100_000,
            profit_plan_minor=25_000,
            revenue_per_assigned_plan_minor=20_000,
            assigned_user_target=5,
            day_kind="SPECIAL",
            title="Фестиваль",
            notes="Усиленная смена",
        )
        self.assertEqual(self.db.commits, 1)
        self.assertEqual(result["usage_component_count"], 2)
        self.assertEqual(result["usage_profile_count"], 1)

    def test_service_validation_error_remains_http_400(self):
        with patch.object(venue_economics, "_require_economics_view"), \
             patch.object(venue_economics, "list_department_month_plans", side_effect=ValueError("bad month")):
            with self.assertRaises(HTTPException) as raised:
                venue_economics.get_venue_department_month_plans(
                    venue_id=5,
                    month="bad",
                    db=self.db,
                    user=self.user,
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "bad month")

    def test_combined_read_guard_keeps_all_three_checks(self):
        with patch.object(venue_economics, "require_active_member_or_admin") as active, \
             patch.object(venue_economics, "require_revenue_viewer") as revenue, \
             patch.object(venue_economics, "require_report_viewer") as reports:
            venue_economics._require_economics_view(self.db, venue_id=9, user=self.user)

        active.assert_called_once_with(self.db, venue_id=9, user=self.user)
        revenue.assert_called_once_with(self.db, venue_id=9, user=self.user)
        reports.assert_called_once_with(self.db, venue_id=9, user=self.user)

    def test_usage_helpers_preserve_effective_plan_and_department_counts(self):
        usage_map = {
            BOOST_SOURCE_VENUE_DAY_PLAN: {
                "usage_component_count": 3,
                "usage_profile_count": 2,
            }
        }
        counts = venue_economics._usage_counts_for_effective_plan(
            {"source": "DATE_OVERRIDE"},
            usage_map,
        )
        day_plan = venue_economics._attach_usage_to_day_plan({"source": "DATE_OVERRIDE"}, counts)
        department_plan = venue_economics._attach_usage_to_department_plan_payload(
            {"items": [{"department_id": 4}, {"department_id": 8}]},
            {4: {"usage_component_count": 5, "usage_profile_count": 3}},
        )

        self.assertEqual(day_plan["usage_component_count"], 3)
        self.assertEqual(day_plan["usage_profile_count"], 2)
        self.assertEqual(department_plan["items"][0]["usage_component_count"], 5)
        self.assertEqual(department_plan["items"][1]["usage_component_count"], 0)
        self.assertEqual(
            venue_economics._usage_counts_for_effective_plan(
                {"source": "MONTH_TEMPLATE"},
                {BOOST_SOURCE_VENUE_MONTH_PLAN: {"usage_component_count": 7}},
            )["usage_component_count"],
            7,
        )
        self.assertEqual(
            venue_economics._usage_counts_for_effective_plan({"source": "WEEKDAY_TEMPLATE"}, {}),
            {"usage_component_count": 0, "usage_profile_count": 0},
        )

    def test_usage_map_aggregates_venue_and_department_sources(self):
        rows = [
            (BOOST_SOURCE_VENUE_MONTH_PLAN, None, 3, 2),
            (BOOST_SOURCE_VENUE_DAY_PLAN, None, 2, 1),
            (BOOST_SOURCE_DEPARTMENT_MONTH_PLAN, 4, 5, 3),
            (BOOST_SOURCE_DEPARTMENT_DAY_PLAN, 4, 4, 2),
            (BOOST_SOURCE_DEPARTMENT_DAY_PLAN, 0, 99, 99),
            ("UNKNOWN", 4, 99, 99),
        ]

        class Result:
            def all(self):
                return rows

        db = SimpleNamespace(execute=lambda statement: Result())
        usage_map = venue_economics._build_percent_boost_usage_map(db, venue_id=5)

        self.assertEqual(usage_map[BOOST_SOURCE_VENUE_MONTH_PLAN]["usage_component_count"], 3)
        self.assertEqual(usage_map[BOOST_SOURCE_VENUE_DAY_PLAN]["usage_profile_count"], 1)
        self.assertEqual(usage_map[BOOST_SOURCE_DEPARTMENT_MONTH_PLAN][4]["usage_component_count"], 5)
        self.assertEqual(usage_map[BOOST_SOURCE_DEPARTMENT_DAY_PLAN][4]["usage_profile_count"], 2)
        self.assertNotIn(0, usage_map[BOOST_SOURCE_DEPARTMENT_DAY_PLAN])

    def test_remaining_read_routes_delegate_and_preserve_usage(self):
        target_date = date(2026, 7, 18)
        with patch.object(venue_economics, "_require_economics_view"), \
             patch.object(venue_economics, "_build_percent_boost_usage_map", return_value=self.usage_map), \
             patch.object(venue_economics, "get_day_economics_plan", return_value={"source": "DATE_OVERRIDE"}), \
             patch.object(venue_economics, "get_day_economics_month_plan", return_value={"source": "MONTH_TEMPLATE"}), \
             patch.object(venue_economics, "get_day_economics_plan_override", return_value={"source": "DATE_OVERRIDE"}), \
             patch.object(venue_economics, "list_day_economics_plan_templates", return_value=[{"weekday": 1}]), \
             patch.object(venue_economics, "list_department_month_plans", return_value={"month": "2026-07", "items": [{"department_id": 4}]}), \
             patch.object(venue_economics, "list_department_day_plans", return_value={"date": "2026-07-18", "items": [{"department_id": 4}]}), \
             patch.object(venue_economics, "get_venue_economics_rules", return_value={"warn_on_draft_expenses": True}), \
             patch.object(venue_economics, "sanitize_financial_payload_for_user", side_effect=lambda user, payload: payload):
            plan = venue_economics.get_venue_day_economics_plan_route(5, target_date, self.db, self.user)
            month_plan = venue_economics.get_venue_day_economics_month_plan_route(5, "2026-07", self.db, self.user)
            override = venue_economics.get_venue_day_economics_plan_override_route(5, target_date, self.db, self.user)
            templates = venue_economics.get_venue_day_economics_plan_templates_route(5, self.db, self.user)
            department_month = venue_economics.get_venue_department_month_plans(5, "2026-07", self.db, self.user)
            department_day = venue_economics.get_venue_department_day_plans(5, target_date, self.db, self.user)
            rules = venue_economics.get_venue_day_economics_rules_route(5, self.db, self.user)

        self.assertEqual(plan["usage_component_count"], 2)
        self.assertEqual(month_plan["usage_component_count"], 3)
        self.assertEqual(override["usage_profile_count"], 1)
        self.assertEqual(templates, [{"weekday": 1}])
        self.assertEqual(department_month["items"][0]["usage_component_count"], 5)
        self.assertEqual(department_day["items"][0]["usage_component_count"], 4)
        self.assertTrue(rules["warn_on_draft_expenses"])

    def test_plan_mutation_routes_commit_and_return_service_results(self):
        month_payload = DayEconomicsMonthPlanIn(revenue_plan_minor=500_000)
        template_payload = DayEconomicsPlanTemplateIn(revenue_plan_minor=80_000)
        copy_payload = DayEconomicsTemplateCopyIn(source_weekday=1, target_weekdays=[2, 3])

        with patch.object(venue_economics, "require_owner_or_super_admin"), \
             patch.object(venue_economics, "_build_percent_boost_usage_map", return_value=self.usage_map), \
             patch.object(venue_economics, "upsert_day_economics_month_plan", return_value={"source": "MONTH_TEMPLATE"}), \
             patch.object(venue_economics, "copy_day_economics_month_plan_from_previous_month", return_value={"copied": True, "copied_from_month": "2026-06", "plan": {"source": "MONTH_TEMPLATE"}}), \
             patch.object(venue_economics, "upsert_day_economics_plan_template", return_value={"weekday": 1}) as upsert_template, \
             patch.object(venue_economics, "copy_day_economics_plan_templates", return_value={"copied_count": 2}) as copy_templates:
            month_plan = venue_economics.put_venue_day_economics_month_plan(5, month_payload, "2026-07", self.db, self.user)
            copied_month = venue_economics.post_venue_day_economics_month_plan_copy_previous(5, "2026-07", True, self.db, self.user)
            template = venue_economics.put_venue_day_economics_plan_template(5, 1, template_payload, self.db, self.user)
            copied_templates = venue_economics.post_venue_day_economics_plan_templates_copy(5, copy_payload, self.db, self.user)

        self.assertEqual(month_plan["month"], "2026-07")
        self.assertEqual(month_plan["usage_component_count"], 3)
        self.assertEqual(copied_month["copied_from_month"], "2026-06")
        self.assertEqual(template, {"weekday": 1})
        self.assertEqual(copied_templates, {"copied_count": 2})
        self.assertEqual(self.db.commits, 4)
        upsert_template.assert_called_once()
        copy_templates.assert_called_once()

    def test_department_mutation_routes_commit_and_attach_usage(self):
        target_date = date(2026, 7, 18)
        bulk = DepartmentPlanBulkIn(items=[{"department_id": 4, "revenue_plan_minor": 100_000}])
        month_result = {"month": "2026-07", "items": [{"department_id": 4}]}
        day_result = {"date": "2026-07-18", "items": [{"department_id": 4}]}

        with patch.object(venue_economics, "require_owner_or_super_admin"), \
             patch.object(venue_economics, "_build_percent_boost_usage_map", return_value=self.usage_map), \
             patch.object(venue_economics, "upsert_department_month_plans", return_value=month_result), \
             patch.object(venue_economics, "autofill_department_month_plans_from_last_month", return_value={"plan": dict(month_result)}), \
             patch.object(venue_economics, "distribute_department_month_plans_from_venue_plan", return_value={"plan": dict(month_result)}), \
             patch.object(venue_economics, "upsert_department_day_plans", return_value=day_result), \
             patch.object(venue_economics, "copy_department_day_plans_from_date", return_value={"plan": dict(day_result)}), \
             patch.object(venue_economics, "autofill_department_day_plans_from_history", return_value={"plan": dict(day_result)}):
            month = venue_economics.put_venue_department_month_plans(5, bulk, "2026-07", self.db, self.user)
            autofilled_month = venue_economics.post_venue_department_month_plans_autofill(5, "2026-07", True, self.db, self.user)
            distributed_month = venue_economics.post_venue_department_month_plans_distribute(5, "2026-07", True, self.db, self.user)
            day = venue_economics.put_venue_department_day_plans(5, bulk, target_date, self.db, self.user)
            copied_day = venue_economics.post_venue_department_day_plans_copy_from_date(5, target_date, target_date, True, self.db, self.user)
            autofilled_day = venue_economics.post_venue_department_day_plans_autofill_from_history(5, target_date, "SAME_WEEKDAY_AVG", True, 4, self.db, self.user)

        self.assertEqual(month["items"][0]["usage_component_count"], 5)
        self.assertEqual(autofilled_month["plan"]["items"][0]["usage_profile_count"], 3)
        self.assertEqual(distributed_month["plan"]["items"][0]["usage_component_count"], 5)
        self.assertEqual(day["items"][0]["usage_component_count"], 4)
        self.assertEqual(copied_day["plan"]["items"][0]["usage_profile_count"], 2)
        self.assertEqual(autofilled_day["plan"]["items"][0]["usage_component_count"], 4)
        self.assertEqual(self.db.commits, 6)

    def test_rules_mutation_commits_and_returns_payload(self):
        payload = VenueEconomicsRulesIn(max_expense_ratio_bps=3500, warn_on_draft_expenses=False)
        expected = {"max_expense_ratio_bps": 3500, "warn_on_draft_expenses": False}
        with patch.object(venue_economics, "require_owner_or_super_admin"), \
             patch.object(venue_economics, "upsert_venue_economics_rules", return_value=expected) as upsert:
            result = venue_economics.put_venue_day_economics_rules(5, payload, self.db, self.user)

        self.assertIs(result, expected)
        self.assertEqual(self.db.commits, 1)
        upsert.assert_called_once_with(
            db=self.db,
            venue_id=5,
            max_expense_ratio_bps=3500,
            max_payroll_ratio_bps=None,
            min_revenue_per_assigned_minor=None,
            min_assigned_shift_coverage_bps=None,
            min_profit_minor=None,
            warn_on_draft_expenses=False,
        )

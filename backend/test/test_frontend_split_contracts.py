from __future__ import annotations

from pathlib import Path
import re
from unittest import TestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT_ROOT / "frontend"


class AppFacadeSplitContractTests(TestCase):
    def test_app_facade_keeps_public_exports_modules_and_consumers(self):
        main = (FRONTEND / "app.js").read_text(encoding="utf-8")
        exported = set(re.findall(r"^export\s+(?:async\s+)?function\s+([\w$]+)", main, re.MULTILINE))
        for block, single in re.findall(
            r"^export\s+const\s+(?:\{([^}]+)\}|([\w$]+))",
            main,
            re.MULTILINE,
        ):
            if single:
                exported.add(single)
            else:
                exported.update(name.strip() for name in block.split(",") if name.strip())

        self.assertEqual(len(exported), 112)
        self.assertTrue({
            "api",
            "ensureLogin",
            "mountNav",
            "getMe",
            "getMyVenuePermissions",
            "getDepartments",
            "getPayProfiles",
            "calculatePayroll",
            "trackDemoEvent",
        }.issubset(exported))
        self.assertLess(len(main.splitlines()), 1_800)

        modules = {
            "auth-actions.js": "createAuthActions",
            "venue-api.js": "createVenueApi",
            "navigation.js": "createNavigation",
        }
        for filename, factory in modules.items():
            source = (FRONTEND / "app" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), 500)
            self.assertIn(f'/app/{filename}?v=20260719-split1', main)
            self.assertIn(f"export function {factory}", source)

        consumer_pattern = re.compile(
            r"import\s*\{([\s\S]*?)\}\s*from\s*[\"']/app\.js\?v=20260719-split1[\"']"
        )
        consumer_count = 0
        for path in FRONTEND.rglob("*"):
            if path.suffix not in {".js", ".mjs", ".html"}:
                continue
            source = path.read_text(encoding="utf-8")
            for match in consumer_pattern.finditer(source):
                consumer_count += 1
                imported = {
                    entry.strip().split(" as ", 1)[0]
                    for entry in match.group(1).split(",")
                    if entry.strip()
                }
                self.assertTrue(imported.issubset(exported), f"{path.name}: {sorted(imported - exported)}")
        self.assertEqual(consumer_count, 51)


class OwnerSetupSplitContractTests(TestCase):
    def test_owner_setup_keeps_all_editor_modules_and_step_dispatch(self):
        main = (FRONTEND / "owner-setup.js").read_text(encoding="utf-8")
        html = (FRONTEND / "owner-setup.html").read_text(encoding="utf-8")
        controllers = {
            "catalog-editor.js": ("createCatalogSetupController", "mountCatalogEditor"),
            "pay-profile-editor.js": ("createPayProfileSetupController", "mountPayProfilesEditor"),
            "position-editor.js": ("createPositionSetupController", "mountPositionsEditor"),
            "invite-editor.js": ("createInviteSetupController", "mountInvitesEditor"),
            "shift-interval-editor.js": ("createShiftIntervalSetupController", "mountShiftIntervalsEditor"),
            "supplier-editor.js": ("createSupplierSetupController", "mountSuppliersEditor"),
            "recurring-expense-editor.js": ("createRecurringExpenseSetupController", "mountRecurringExpensesEditor"),
        }

        self.assertLess(len(main.splitlines()), 1_600)
        self.assertIn("owner-setup.js?v=20260719-split1", html)
        for filename, (factory, mount_method) in controllers.items():
            source = (FRONTEND / "owner-setup" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), 500)
            self.assertIn(f'/owner-setup/{filename}?v=20260719-split1', main)
            self.assertIn(f"export function {factory}", source)
            self.assertIn(mount_method, source)

        step_dispatch = {
            "welcome": "mountWelcomeEditor",
            "pay_profiles": "mountPayProfilesEditor",
            "positions": "mountPositionsEditor",
            "invites": "mountInvitesEditor",
            "shift_intervals": "mountShiftIntervalsEditor",
            "suppliers": "mountSuppliersEditor",
            "recurring_expenses": "mountRecurringExpensesEditor",
        }
        for step_key, mount_method in step_dispatch.items():
            step_anchor = main.index(f'currentStep.key === "{step_key}"')
            self.assertIn(mount_method, main[step_anchor:step_anchor + 220])

        pay_profile_factory = main.index("createPayProfileSetupController(editorContext)")
        shared_profiles = main.index("editorContext.loadInlinePayProfiles = loadInlinePayProfiles")
        position_factory = main.index("createPositionSetupController(editorContext)")
        self.assertLess(pay_profile_factory, shared_profiles)
        self.assertLess(shared_profiles, position_factory)


class StaffShiftsSplitContractTests(TestCase):
    def test_schedule_export_keeps_live_state_controls_and_route(self):
        main = (FRONTEND / "staff-shifts.js").read_text(encoding="utf-8")
        module = (FRONTEND / "staff-shifts" / "export-controller.js").read_text(encoding="utf-8")
        calendar = (FRONTEND / "staff-shifts" / "calendar-controller.js").read_text(encoding="utf-8")
        html = (FRONTEND / "staff-shifts.html").read_text(encoding="utf-8")

        self.assertLess(len(main.splitlines()), 1_800)
        self.assertLess(len(module.splitlines()), 900)
        self.assertLess(len(calendar.splitlines()), 850)
        self.assertIn("/staff-shifts/export-controller.js?v=20260719-split1", main)
        self.assertIn("/staff-shifts/calendar-controller.js?v=20260719-calendar1", main)
        self.assertIn("staff-shifts.js?v=20260719-calendar1", html)
        self.assertIn("/shifts/export-metadata?", module)

        mutable_fields = (
            "me",
            "calendarView",
            "curWeekStart",
            "curMonth",
            "selectedShiftSlot",
            "intervals",
            "selectedIntervalIds",
            "calendarScope",
            "showAllOnCalendar",
            "unstaffedOnly",
            "currentVenueName",
            "venueId",
            "shiftsByDate",
        )
        for field in mutable_fields:
            self.assertIn(f"get {field}() {{ return {field}; }}", main)
            self.assertIn(f"runtime.{field}", module)

        for control in ("btnExportImage", "btnExportShare", "btnExportTelegram", "btnExportDownload"):
            self.assertIn(f"el.{control}", module)

        calendar_methods = (
            "renderWeek",
            "buildIndex",
            "defaultSelectedDateForMonth",
            "selectDate",
            "monthTitle",
            "formatDateRuNoG",
            "filterForCalendar",
            "shiftIsClosed",
            "renderMonth",
        )
        for method in calendar_methods:
            self.assertIn(method, calendar)

        synchronized_fields = (
            "selectedDate",
            "shiftsByDate",
            "salaryByDate",
            "calendarScope",
            "globalShifts",
            "shifts",
            "curMonth",
            "me",
            "canEdit",
            "showAllOnCalendar",
            "nightShiftsEnabled",
            "selectedShiftSlot",
        )
        for field in synchronized_fields:
            self.assertIn(f"get {field}() {{ return {field}; }}", main)
            self.assertIn(f"set {field}(value) {{ {field} = value; }}", main)
            self.assertIn(f"runtime.{field}", calendar)


class OwnerPayProfileSplitContractTests(TestCase):
    def test_profile_page_keeps_component_and_assignment_controllers(self):
        main = (FRONTEND / "owner-pay-profile.js").read_text(encoding="utf-8")
        html = (FRONTEND / "owner-pay-profile.html").read_text(encoding="utf-8")
        modules = {
            "component-support.js": ("createPayComponentSupport", 550),
            "component-form.js": ("createPayComponentFormRenderer", 350),
            "component-controller.js": ("createPayComponentController", 650),
            "component-list.js": ("createPayComponentList", 180),
            "assignment-controller.js": ("createPayAssignmentController", 220),
        }

        self.assertLess(len(main.splitlines()), 450)
        self.assertIn("owner-pay-profile.js?v=20260719-payprofile1", html)
        for filename, (factory, line_limit) in modules.items():
            source = (FRONTEND / "owner-pay-profile" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), line_limit)
            self.assertIn(f'/owner-pay-profile/{filename}?v=20260719-payprofile1', main)
            self.assertIn(f"export function {factory}", source)

        controller_contracts = {
            "component-controller.js": ("openComponentEditor",),
            "component-list.js": ("renderComponents",),
            "assignment-controller.js": ("renderAssignments", "openAssignmentEditor"),
        }
        for filename, methods in controller_contracts.items():
            source = (FRONTEND / "owner-pay-profile" / filename).read_text(encoding="utf-8")
            for method in methods:
                self.assertIn(method, source)
                self.assertIn(method, main)

        api_ownership = {
            "component-controller.js": ("createPayComponent", "updatePayComponent"),
            "component-list.js": ("updatePayComponent", "deletePayComponent"),
            "assignment-controller.js": (
                "createPayProfileAssignment",
                "updatePayProfileAssignment",
                "deletePayProfileAssignment",
            ),
        }
        for filename, api_calls in api_ownership.items():
            source = (FRONTEND / "owner-pay-profile" / filename).read_text(encoding="utf-8")
            for api_call in api_calls:
                self.assertIn(api_call, source)


class PositionsSplitContractTests(TestCase):
    def test_positions_page_keeps_editor_list_permissions_and_invites(self):
        main = (FRONTEND / "positions.js").read_text(encoding="utf-8")
        html = (FRONTEND / "positions.html").read_text(encoding="utf-8")
        modules = {
            "permission-controller.js": ("createPositionPermissionController", 320),
            "position-domain.js": ("createPositionDomain", 240),
            "position-editor.js": ("createPositionEditor", 520),
            "position-list.js": ("createPositionList", 180),
            "invite-controller.js": ("createPositionInviteController", 150),
        }

        self.assertLess(len(main.splitlines()), 420)
        self.assertIn("positions.js?v=20260719-positions1", html)
        for filename, (factory, line_limit) in modules.items():
            source = (FRONTEND / "positions" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), line_limit)
            self.assertIn(f'/positions/{filename}?v=20260719-positions1', main)
            self.assertIn(f"export function {factory}", source)

        editor = (FRONTEND / "positions" / "position-editor.js").read_text(encoding="utf-8")
        position_list = (FRONTEND / "positions" / "position-list.js").read_text(encoding="utf-8")
        invites = (FRONTEND / "positions" / "invite-controller.js").read_text(encoding="utf-8")
        permissions = (FRONTEND / "positions" / "permission-controller.js").read_text(encoding="utf-8")

        for api_call in ("createVenuePosition", "updateVenuePosition", "deleteVenuePosition"):
            self.assertIn(api_call, editor)
        self.assertIn("deleteVenuePosition", position_list)
        self.assertIn("patchInviteDefaultPosition", invites)
        self.assertIn("/me/permissions/catalog", permissions)
        self.assertIn("/position-permission-templates", permissions)

        self.assertIn("openCreateModal", main)
        self.assertIn("renderPositions", main)
        self.assertIn("renderInvites", main)

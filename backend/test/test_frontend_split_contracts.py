from __future__ import annotations

from pathlib import Path
import re
from unittest import TestCase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = PROJECT_ROOT / "frontend"


class PageLoaderContractTests(TestCase):
    def test_all_pages_share_the_fetch_and_dom_aware_loader(self):
        loader = (FRONTEND / "page-loader.js").read_text(encoding="utf-8")
        styles_manifest = (FRONTEND / "styles.css").read_text(encoding="utf-8")
        style_cache_key = "20260723-polish1"
        core_style_files = (
            "tokens.css",
            "base-layout.css",
            "controls.css",
            "cards-lists.css",
            "calendar-core.css",
            "utilities.css",
            "calendar-reports.css",
            "finance-components.css",
            "shared-layout.css",
            "overlays-documents.css",
        )
        styles = "".join(
            (FRONTEND / "styles" / "core" / file_name).read_text(encoding="utf-8")
            for file_name in core_style_files
        )
        html_pages = sorted(FRONTEND.glob("*.html"))

        self.assertEqual(
            sorted(path.name for path in (FRONTEND / "styles" / "core").glob("*.css")),
            sorted(core_style_files),
        )
        expected_imports = [
            f'@import url("/styles/core/{file_name}?v={style_cache_key}");'
            for file_name in core_style_files
        ]
        self.assertEqual(
            re.findall(r'@import url\("[^"]+"\);', styles_manifest),
            expected_imports,
        )
        for file_name in core_style_files:
            source = (FRONTEND / "styles" / "core" / file_name).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), 500, file_name)

        self.assertEqual(len(html_pages), 50)
        for path in html_pages:
            source = path.read_text(encoding="utf-8")
            self.assertIn('/page-loader.js?v=20260720-loader1', source, path.name)
            self.assertIn(f'/styles.css?v={style_cache_key}', source, path.name)

        self.assertLess(len(loader.splitlines()), 180)
        self.assertIn("window.fetch = function", loader)
        self.assertIn("MutationObserver", loader)
        self.assertIn("HARD_TIMEOUT_MS", loader)
        self.assertIn("axelio:page-ready", loader)
        self.assertNotRegex(loader, r"(?:\sstyle\s*=|\.style\b)")
        for selector in (
            ".page-loading body>:not(.page-loader)",
            ".page-loader__panel",
            ".page-loader__spinner",
            ".page-loader__title",
            ".page-loader__hint",
        ):
            self.assertIn(f"{selector}{{", styles)

        for responsive_contract in (
            "min-height:100dvh",
            "overflow-x:clip",
            "min-height:var(--control-height)",
            ".skeleton--card{height:116px}",
            "max-height:calc(100dvh - 8px)",
            "animation-duration:.01ms !important",
        ):
            self.assertIn(responsive_contract, styles)


class PrimaryPageUiPolishContractTests(TestCase):
    def test_primary_pages_keep_shared_visual_states_and_page_styles(self):
        contracts = {
            "app-venues.html": (
                "styles/pages/app-venues.css",
                ("venue-card__layout", "venue-card__actions", "venue-list-state"),
            ),
            "app-dashboard.html": (
                "styles/pages/app-dashboard.css",
                ("dashboard-section-card", "dashboard-state", "dashboard-sections-grid--state"),
            ),
            "app-venue.html": (
                "styles/pages/app-venue.css",
                ("venue-notice--setup", "venue-billing-card", "venue-member-row__main"),
            ),
            "owner-summary.html": (
                "styles/pages/finance-pages.css",
                ("summary-metric--profit", "summary-state", "finance-stat__value is-loading"),
            ),
        }

        for html_name, (style_path, required) in contracts.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            styles = (FRONTEND / style_path).read_text(encoding="utf-8")
            self.assertIn(f'/{style_path}?v=20260723-polish2', html, html_name)
            for contract in required:
                self.assertTrue(contract in html or contract in styles, f"{html_name}: {contract}")

        summary_js = (FRONTEND / "owner-summary.js").read_text(encoding="utf-8")
        self.assertIn('classList.remove("is-loading")', summary_js)


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
            r"import\s*\{([\s\S]*?)\}\s*from\s*[\"']/app\.js\?v=20260722-dynamic1[\"']"
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


class FunctionalFrontendRegressionContractTests(TestCase):
    def test_get_requests_do_not_force_cors_preflight_headers(self):
        source = (FRONTEND / "app.js").read_text(encoding="utf-8")
        api_source = source[
            source.index("export async function api"):
            source.index("function parseDownloadFilename")
        ]

        self.assertIn('const method = String(opts.method || "GET").toUpperCase();', api_source)
        self.assertIn("const shouldSetJsonContentType = !isForm && hasBody", api_source)
        self.assertNotIn('"Cache-Control": "no-cache"', api_source)
        self.assertNotIn('Pragma: "no-cache"', api_source)

    def test_venue_member_card_uses_member_safe_endpoint(self):
        source = (FRONTEND / "app-venue.html").read_text(encoding="utf-8")

        self.assertIn("api(`/me/venues/${venueId}/members`)", source)
        self.assertNotIn("api(`/venues/${venueId}/members`)", source)

    def test_admin_position_templates_has_shared_feedback_dom(self):
        source = (FRONTEND / "admin-position-templates.html").read_text(encoding="utf-8")

        self.assertIn('id="toast"', source)
        self.assertIn('id="modal"', source)
        self.assertIn('class="modal__title"', source)
        self.assertIn('class="modal__body"', source)


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
        self.assertIn("owner-setup.js?v=20260723-functional1", html)
        self.assertIn("position-template-ui.js?v=20260722-dynamic1", main)
        self.assertNotRegex(html, r"(?:<style\b|\sstyle\s*=|\.style\b)")
        self.assertNotRegex(main, r"(?:<style\b|\sstyle\s*=|\.style\b)")
        self.assertIn('<progress class="setup-progressbar"', main)
        self.assertIn('isSetupDone(state.setup) ? "Настройка завершена"', main)
        resume_helper = main[
            main.index("function getPhaseResumeStep"):
            main.index("function renderOverview")
        ]
        self.assertNotIn('visible.find(({ ui }) => !ui.locked)', resume_helper)
        for filename, (factory, mount_method) in controllers.items():
            source = (FRONTEND / "owner-setup" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), 500)
            self.assertIn(f'/owner-setup/{filename}?v=20260720-unified10', main)
            self.assertNotRegex(source, r"(?:<style\b|\sstyle\s*=|\.style\b)")
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

        recurring = (FRONTEND / "owner-setup" / "recurring-expense-editor.js").read_text(encoding="utf-8")
        self.assertRegex(recurring, r"const \{[^}]*getPaymentMethods[^}]*\} = context;")
        self.assertRegex(main, r"const editorContext = \{[\s\S]*?getPaymentMethods,[\s\S]*?\};")


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
        self.assertIn("/staff-shifts/calendar-controller.js?v=20260720-unified6", main)
        self.assertIn("staff-shifts.js?v=20260722-dynamic1", html)
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
        self.assertIn("owner-pay-profile.js?v=20260723-functional1", html)
        for filename, (factory, line_limit) in modules.items():
            source = (FRONTEND / "owner-pay-profile" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), line_limit)
            cache_key = "20260723-functional1" if filename == "assignment-controller.js" else "20260720-unified7"
            self.assertIn(f'/owner-pay-profile/{filename}?v={cache_key}', main)
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
        self.assertIn("positions.js?v=20260723-functional1", html)
        for filename, (factory, line_limit) in modules.items():
            source = (FRONTEND / "positions" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), line_limit)
            cache_key = (
                "20260722-dynamic1"
                if filename == "permission-controller.js"
                else "20260723-functional1"
                if filename in {"position-editor.js", "position-list.js"}
                else "20260720-unified6"
            )
            self.assertIn(f'/positions/{filename}?v={cache_key}', main)
            self.assertIn(f"export function {factory}", source)

        editor = (FRONTEND / "positions" / "position-editor.js").read_text(encoding="utf-8")
        position_list = (FRONTEND / "positions" / "position-list.js").read_text(encoding="utf-8")
        invites = (FRONTEND / "positions" / "invite-controller.js").read_text(encoding="utf-8")
        permissions = (FRONTEND / "positions" / "permission-controller.js").read_text(encoding="utf-8")
        self.assertIn("position-template-ui.js?v=20260722-dynamic1", permissions)

        for api_call in ("createVenuePosition", "updateVenuePosition", "deleteVenuePosition"):
            self.assertIn(api_call, editor)
        self.assertIn("deleteVenuePosition", position_list)
        self.assertIn("patchInviteDefaultPosition", invites)
        self.assertIn("/me/permissions/catalog", permissions)
        self.assertIn("/position-permission-templates", permissions)

        self.assertIn("openCreateModal", main)
        self.assertIn("renderPositions", main)
        self.assertIn("renderInvites", main)

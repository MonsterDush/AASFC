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
        style_version = "20260825-i18nmodal2"
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
            (FRONTEND / "styles" / "core" / file_name).read_text(encoding="utf-8") for file_name in core_style_files
        )
        html_pages = sorted(FRONTEND.glob("*.html"))

        self.assertEqual(
            sorted(path.name for path in (FRONTEND / "styles" / "core").glob("*.css")),
            sorted(core_style_files),
        )
        expected_imports = [
            f'@import url("/styles/core/{file_name}?v={style_version}");' for file_name in core_style_files
        ]
        self.assertEqual(
            re.findall(r'@import url\("[^"]+"\);', styles_manifest),
            expected_imports,
        )
        for file_name in core_style_files:
            source = (FRONTEND / "styles" / "core" / file_name).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), 500, file_name)

        self.assertEqual(len(html_pages), 52)
        for path in html_pages:
            source = path.read_text(encoding="utf-8")
            self.assertIn("/page-loader.js?v=20260823-navfix1", source, path.name)
            self.assertIn("/i18n-bootstrap.js?v=20260826-i18n12", source, path.name)
            self.assertIn(f"/styles.css?v={style_version}", source, path.name)

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


class DemoMetrikaContractTests(TestCase):
    def test_metrika_is_initialized_only_after_authoritative_demo_state(self):
        metrika = (FRONTEND / "app" / "demo-metrika.js").read_text(encoding="utf-8")
        app = (FRONTEND / "app.js").read_text(encoding="utf-8")
        auth = (FRONTEND / "auth.html").read_text(encoding="utf-8")
        venues = (FRONTEND / "app-venues.html").read_text(encoding="utf-8")
        venue = (FRONTEND / "app-venue.html").read_text(encoding="utf-8")

        self.assertIn("const METRIKA_ID = 108617620", metrika)
        self.assertIn('new Set(["app.axelio.ru"])', metrika)
        self.assertIn("state?.demo_mode === true", metrika)
        self.assertIn("defer: true", metrika)
        self.assertIn("webvisor: true", metrika)
        self.assertIn('window.ym(METRIKA_ID, "hit", url', metrika)
        self.assertIn('window.ym(METRIKA_ID, "reachGoal", `demo_${normalizedEvent}`', metrika)
        self.assertIn("enableDemoMetrika(state)", app)
        self.assertNotIn("initialDemoState", app)
        for page in (auth, venues, venue):
            self.assertNotIn("/metrika.js", page)

    def test_demo_locale_is_never_persisted_to_the_shared_demo_account(self):
        venue_api = (FRONTEND / "app" / "venue-api.js").read_text(encoding="utf-8")
        settings = (FRONTEND / "settings.html").read_text(encoding="utf-8")

        demo_branch = venue_api[
            venue_api.index("if (demoState?.demo_mode)") : venue_api.index(
                "} else if", venue_api.index("if (demoState?.demo_mode)")
            )
        ]
        self.assertNotIn("/me/profile", demo_branch)
        self.assertIn("if (!demoReadonly)", settings)

    def test_i18n_observer_batches_dynamic_content_and_ignores_code(self):
        i18n = (FRONTEND / "i18n.js").read_text(encoding="utf-8")

        self.assertIn("script, style, noscript, template, [data-i18n-ignore]", i18n)
        self.assertIn("observer = new MutationObserver(() => {", i18n)
        self.assertIn("scheduleTranslation();", i18n)
        self.assertIn('"Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"', i18n)
        self.assertIn('"мин", "ч", "шт", "шт.", "ед.", "дн.", "мес.", "п.п."', i18n)
        self.assertIn("source.length >= 4 || SHORT_FRAGMENT_SOURCES.has(source)", i18n)
        self.assertIn(r"/\b(\d{1,2})-(?:го|е) числ(?:о|а)/g", i18n)
        self.assertIn("accrues on the ${englishOrdinal(day)}", i18n)
        self.assertIn('replace(/₽/g, "RUB")', i18n)
        self.assertIn('1: "st", 2: "nd", 3: "rd"', i18n)

    def test_frontend_csp_allows_metrika_session_replay(self):
        csp = (PROJECT_ROOT / "ops" / "nginx" / "axelio-security-headers.conf").read_text(encoding="utf-8")

        self.assertIn("https://yastatic.net", csp)
        self.assertIn("https://mc.webvisor.com", csp)
        self.assertIn("wss://mc.yandex.ru", csp)
        self.assertIn("child-src blob: https://mc.yandex.ru", csp)
        self.assertIn("frame-src blob: https://mc.yandex.ru", csp)
        self.assertIn("https://metrika.yandex.ru", csp)


class QuickRestoIntegrationContractTests(TestCase):
    def test_owner_only_integration_hub_and_quickresto_page_use_venue_api(self):
        venue = (FRONTEND / "app-venue.html").read_text(encoding="utf-8")
        hub_html = (FRONTEND / "owner-integrations.html").read_text(encoding="utf-8")
        hub_script = (FRONTEND / "owner-integrations.js").read_text(encoding="utf-8")
        hub_styles = (FRONTEND / "styles" / "pages" / "owner-integrations.css").read_text(encoding="utf-8")
        html = (FRONTEND / "owner-quickresto.html").read_text(encoding="utf-8")
        script = (FRONTEND / "owner-quickresto.js").read_text(encoding="utf-8")
        styles = (FRONTEND / "styles" / "pages" / "owner-quickresto.css").read_text(encoding="utf-8")

        self.assertIn('id="openIntegrations"', venue)
        self.assertIn("venue-integrations-entry hidden", venue)
        self.assertIn('hasPerm(pset, "INTEGRATIONS_VIEW")', venue)
        self.assertIn("canViewIntegrations && !demoReadonly", venue)
        self.assertIn("/owner-integrations.html?venue_id=", venue)
        self.assertIn("/styles/pages/owner-integrations.css", hub_html)
        self.assertIn("/owner-integrations.js", hub_html)
        self.assertIn("20260828-integrations2", hub_html)
        self.assertIn(".integrations-provider-tab{flex-direction:column", hub_styles)
        self.assertIn("white-space:nowrap", hub_styles)
        self.assertIn('role="tablist"', hub_html)
        self.assertIn('data-provider="quickresto"', hub_html)
        self.assertIn('data-provider="iiko"', hub_html)
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", hub_styles)
        self.assertIn("/integrations/quickresto`)", hub_script)
        self.assertIn("/owner-quickresto.html?venue_id=", hub_script)
        self.assertIn("/styles/pages/owner-quickresto.css", html)
        self.assertIn("/owner-quickresto.js", html)
        self.assertIn('name="reportImportMode"', html)
        self.assertIn('.quickresto-form input[type="date"]', styles)
        self.assertIn("padding-inline:0", styles)
        self.assertIn("::-webkit-date-and-time-value", styles)
        self.assertIn("box-sizing:border-box", styles)
        self.assertIn('class="quickresto-api-help"', html)
        self.assertIn("Предприятие → Настройки → Общие настройки", html)
        self.assertIn("https://quickresto.ru/support/rabota_s_bek_ofisom/enterprise/settings/", html)
        self.assertIn("20260831-qrissues1", html)
        self.assertIn('aria-describedby="cutoffHourHelp"', html)
        self.assertIn("Эта граница определяет дату отчёта, а не тип смены", html)
        self.assertIn("при 06:00 открытие 27 августа в 03:15", html)
        self.assertIn('id="nightShiftToggleRow" hidden', html)
        self.assertIn('id="nightShiftWindow" hidden', html)
        self.assertIn("Разделять дневные и ночные смены", html)
        self.assertIn(".quickresto-field-help", styles)
        self.assertIn(".quickresto-night-window__grid", styles)
        self.assertIn("grid-template-columns:minmax(0,1fr)", styles)
        self.assertIn("report_import_mode: selectedImportMode()", script)
        self.assertRegex(
            script,
            r"night_shift_split_enabled:\s*state\.venueNightShiftsEnabled",
        )
        self.assertIn("night_shift_start_hour:", script)
        self.assertIn("renderNightShiftSettings", script)
        self.assertIn("getPaymentMethods(venueId, { includeArchived: false })", script)
        for endpoint in (
            "/integrations/quickresto`)",
            "/integrations/quickresto/discover`",
            "/integrations/quickresto/mappings`",
            "/integrations/quickresto/sync${suffix}`",
            "/integrations/quickresto/runs?limit=10`",
        ):
            self.assertIn(endpoint, script)
        self.assertIn('el.apiPassword.value = ""', script)


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
                ("summary-metric--profit", "summary-state", "finance-stat__value is-loading", "summary-analytics-grid"),
            ),
        }

        for html_name, (style_path, required) in contracts.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            styles = (FRONTEND / style_path).read_text(encoding="utf-8")
            cache_key = {
                "owner-summary.html": "20260810-financepolish1",
                "app-venue.html": "20260828-integrations1",
            }.get(html_name, "20260723-polish2")
            self.assertIn(f"/{style_path}?v={cache_key}", html, html_name)
            for contract in required:
                self.assertTrue(contract in html or contract in styles, f"{html_name}: {contract}")

        summary_js = (FRONTEND / "owner-summary.js").read_text(encoding="utf-8")
        self.assertIn('classList.remove("is-loading")', summary_js)
        self.assertIn('primaryQuery.set("include_series", "1")', summary_js)
        self.assertIn('comparisonQuery.set("include_series", "1")', summary_js)
        self.assertIn("buildFinancePeriodComparisonGeometry", summary_js)
        self.assertIn("/owner-day-economics.html?", summary_js)
        self.assertIn("/owner-expenses.html?", summary_js)
        self.assertIn("/owner-payroll.html?", summary_js)
        self.assertIn("summary-chart-focus__values", summary_js)
        self.assertIn("(${fmtSignedMoneyMinor(delta)})", summary_js)
        self.assertIn("— сопоставление по порядковому дню", summary_js)
        self.assertNotIn("сопоставление по порядковому дню, ₽", summary_js)
        self.assertNotIn("/summary/monthly?${qs}", summary_js)

        summary_html = (FRONTEND / "owner-summary.html").read_text(encoding="utf-8")
        self.assertIn('id="summaryTrendMetricSeg"', summary_html)
        self.assertIn('data-trend-metric="revenue"', summary_html)


class WorkflowPageUiPolishContractTests(TestCase):
    def test_expense_rows_keep_status_tones_and_visual_hierarchy(self):
        html = (FRONTEND / "owner-expenses.html").read_text(encoding="utf-8")
        script = (FRONTEND / "owner-expenses.js").read_text(encoding="utf-8")
        styles = (FRONTEND / "styles/pages/finance-pages.css").read_text(encoding="utf-8")

        self.assertIn("/styles/pages/finance-pages.css?v=20260810-financepolish1", html)
        self.assertIn("/owner-expenses.js?v=20260810-financepolish1", html)
        for contract in (
            "expense-status-badge--confirmed",
            "expense-row__recognition",
            "expense-row__allocation-group",
            "expense-row__actions",
        ):
            self.assertIn(contract, script)
            self.assertIn(contract, styles)

    def test_finance_pages_expose_permission_aware_ledger_navigation(self):
        page_scripts = {
            "owner-summary.html": "owner-summary.js",
            "owner-turnover.html": "owner-turnover.js",
            "owner-expenses.html": "owner-expenses.js",
            "owner-day-economics.html": "owner-day-economics.js",
        }
        for html_name, script_name in page_scripts.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            script = (FRONTEND / script_name).read_text(encoding="utf-8")
            self.assertIn('id="openLedgerBtn"', html, html_name)
            self.assertIn("/owner-finance-ledger.html?", script, script_name)

        turnover_html = (FRONTEND / "owner-turnover.html").read_text(encoding="utf-8")
        expenses_html = (FRONTEND / "owner-expenses.html").read_text(encoding="utf-8")
        summary_html = (FRONTEND / "owner-summary.html").read_text(encoding="utf-8")
        economics_html = (FRONTEND / "owner-day-economics.html").read_text(encoding="utf-8")
        self.assertIn('class="btn ghost finance-action-btn" id="openLedgerBtn"', turnover_html)
        self.assertIn('id="expenseCatalogsWrap"', expenses_html)
        self.assertIn('class="btn subtle finance-action-btn" id="openLedgerBtn"', expenses_html)
        self.assertIn('class="btn subtle finance-action-btn hidden" id="openLedgerBtn"', summary_html)
        self.assertIn('class="btn subtle small" id="openLedgerBtn"', economics_html)
        self.assertIn('class="owner-expenses-page"', expenses_html)
        self.assertIn('class="expense-catalog-grid"', expenses_html)
        self.assertIn('class="expense-catalog-card__actions"', expenses_html)
        self.assertLess(
            expenses_html.index('id="openExpenseCategoriesBtn"'), expenses_html.index('id="addCategoryBtn"')
        )
        self.assertLess(expenses_html.index('id="openSuppliersBtn"'), expenses_html.index('id="addSupplierBtn"'))

        summary_script = (FRONTEND / "owner-summary.js").read_text(encoding="utf-8")
        self.assertIn("hasFinanceLedgerViewAccess", summary_script)
        self.assertIn("financeAccess.canViewLedger", summary_script)

        for path in sorted(FRONTEND.rglob("*")):
            if path.suffix not in {".html", ".js"} or path.name == "app-venue.html":
                continue
            source = path.read_text(encoding="utf-8")
            self.assertNotRegex(source, r'<a\s+class="[^"]*btn subtle', str(path.relative_to(FRONTEND)))
        loader = (FRONTEND / "page-loader.js").read_text(encoding="utf-8")
        self.assertIn("button[data-nav-button]", loader)
        self.assertIn('Reflect.get(button, "href")', loader)

        ledger_html = (FRONTEND / "owner-finance-ledger.html").read_text(encoding="utf-8")
        ledger_script = (FRONTEND / "owner-finance-ledger.js").read_text(encoding="utf-8")
        self.assertIn('id="ledgerFinanceShortcuts"', ledger_html)
        self.assertIn("access.canViewRevenue", ledger_script)
        self.assertIn("access.canViewExpenses", ledger_script)
        self.assertIn("syncFinanceLinks", ledger_script)
        self.assertIn("buildLedgerSourceDrilldown", ledger_script)
        self.assertIn("data-source-details", ledger_script)
        self.assertIn("focusLinkedTransfer", ledger_script)
        self.assertIn("focusLinkedAdjustment", ledger_script)
        self.assertIn('id="ledgerDirectionPick"', ledger_html)
        self.assertIn('id="ledgerSourcePick"', ledger_html)
        self.assertIn('id="ledgerDateRange"', ledger_html)
        self.assertIn('id="adjustmentList"', ledger_html)
        self.assertIn('id="exportLedgerBtn"', ledger_html)
        self.assertIn('id="ledgerReconciliation"', ledger_html)
        self.assertIn("openAdjustmentForm", ledger_script)
        self.assertIn("parseSignedMoneyToMinor", ledger_script)
        self.assertIn('query.set("direction", direction)', ledger_script)
        self.assertIn('query.set("source_type", sourceType)', ledger_script)
        self.assertIn("currentLedgerQuery", ledger_script)
        self.assertIn("renderReconciliation", ledger_script)
        self.assertIn('id="ledgerOperations"', ledger_html)
        self.assertIn('id="ledgerOperationsMore"', ledger_html)
        self.assertIn('data-compare="none"', ledger_html)
        self.assertIn("OPERATIONS_PAGE_SIZE", ledger_script)
        self.assertIn("/finance/entries/analytics?", ledger_script)
        self.assertIn("state.operationsDay = button.dataset.ledgerDay", ledger_script)
        self.assertIn("await loadOperations({ reset: true })", ledger_script)
        self.assertNotRegex(ledger_html, r'<details[^>]+id="ledgerOperations"[^>]+open')

        comparison_pages = (
            "owner-summary.html",
            "owner-expenses.html",
            "owner-turnover.html",
            "owner-day-economics.html",
            "owner-finance-ledger.html",
        )
        for html_name in comparison_pages:
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            self.assertIn("finance-comparison-disclosure", html, html_name)
            self.assertIn('data-compare="none"', html, html_name)
            self.assertNotRegex(html, r"<details[^>]+finance-comparison-disclosure[^>]+open", html_name)

        summary_html = (FRONTEND / "owner-summary.html").read_text(encoding="utf-8")
        finance_styles = (FRONTEND / "styles/pages/finance-pages.css").read_text(encoding="utf-8")
        self.assertIn("summary-primary-toolbar", summary_html)
        self.assertIn(".summary-period-segment", finance_styles)
        self.assertIn("grid-template-columns:repeat(3,minmax(0,1fr))", finance_styles)

        expense_script = (FRONTEND / "owner-expenses.js").read_text(encoding="utf-8")
        payroll_script = (FRONTEND / "owner-payroll.js").read_text(encoding="utf-8")
        report_script = (FRONTEND / "staff-report.js").read_text(encoding="utf-8")
        self.assertIn("finance-comparison-disclosure", payroll_script)
        self.assertIn('data-compare="none"', payroll_script)
        self.assertIn('params.get("expense_id")', expense_script)
        self.assertIn("focusLinkedExpense", expense_script)
        self.assertIn('params.get("payroll_line_id")', payroll_script)
        self.assertIn("focusLinkedPayrollLine", payroll_script)
        self.assertIn('params.get("report_date")', report_script)
        self.assertIn("await openDay(targetReportDate)", report_script)

    def test_setup_positions_and_invites_keep_responsive_visual_states(self):
        contracts = {
            "owner-setup.html": (
                "styles/pages/owner-setup.css",
                "20260725-polish3",
                ("setup-step__index", "setup-loading", "setup-detail-card"),
            ),
            "positions.html": (
                "styles/pages/positions.css",
                "20260725-polish3",
                ("positions-hero", "position-state", "position-member-row__actions"),
            ),
            "invites.html": (
                "styles/pages/invites.css",
                "20260725-polish4",
                ("invite-create-card", "invite-count", "invite-card__layout"),
            ),
            "invite-accept.html": (
                "styles/pages/invites.css",
                "20260725-polish4",
                ("invite-accept-card", "invite-meta-item", "invite-accept-actions"),
            ),
        }

        for html_name, (style_path, cache_key, required) in contracts.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            styles = (FRONTEND / style_path).read_text(encoding="utf-8")
            self.assertIn(f"/{style_path}?v={cache_key}", html, html_name)
            for contract in required:
                self.assertTrue(contract in html or contract in styles, f"{html_name}: {contract}")

    def test_settings_profile_and_owner_preferences_keep_responsive_visual_states(self):
        contracts = {
            "settings.html": (
                "styles/pages/settings.css",
                ("settings-content", "settings-document-link__layout", "settings-actions"),
            ),
            "profile.html": (
                "styles/pages/profile.css",
                ("profile-form", "auth-box__index", "profile-actions"),
            ),
            "owner-subscription.html": (
                "styles/pages/owner-subscription.css",
                ("subscription-status", "subscription-history-row__head", "subscription-state"),
            ),
            "owner-tip-settings.html": (
                "styles/pages/owner-tip-settings.css",
                ("tip-settings-loading", "tip-settings-state", "tip-settings-savebar"),
            ),
        }

        for html_name, (style_path, required) in contracts.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            styles = (FRONTEND / style_path).read_text(encoding="utf-8")
            self.assertIn(f"/{style_path}?v=20260725-polish5", html, html_name)
            for contract in required:
                self.assertTrue(contract in html or contract in styles, f"{html_name}: {contract}")

        tip_settings_html = (FRONTEND / "owner-tip-settings.html").read_text(encoding="utf-8")
        tip_settings_js = (FRONTEND / "owner-tip-settings.js").read_text(encoding="utf-8")
        self.assertIn("/owner-tip-settings.js?v=20260729-tips1", tip_settings_html)
        self.assertIn('id="rulesNote"', tip_settings_html)
        self.assertIn("renderRulesNote", tip_settings_js)
        self.assertIn("Promise.allSettled", tip_settings_js)
        self.assertIn("el.save.disabled = true", tip_settings_js)

    def test_staff_finance_pages_keep_responsive_visual_states_and_routes(self):
        contracts = {
            "staff-finance.html": (
                "styles/pages/staff-finance.css",
                ("staff-finance-hero", "staff-finance-action-card", "staff-finance-actions"),
            ),
            "staff-salary.html": (
                "styles/pages/staff-salary.css",
                ("salary-toolbar-card", "salary-summary-metrics", "salary-state"),
            ),
            "staff-adjustments.html": (
                "styles/pages/staff-adjustments.css",
                ("staff-adjustments-toolbar", "staff-adjustment-day", "staff-adjustments-state"),
            ),
            "staff-report.html": (
                "styles/pages/staff-report.css",
                (
                    "staff-report-toolbar",
                    "staff-report-month-button",
                    "staff-report-label-compact",
                    "staff-report-calendar",
                    "staff-report-state",
                ),
            ),
        }

        for html_name, (style_path, required) in contracts.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            styles = (FRONTEND / style_path).read_text(encoding="utf-8")
            if html_name == "staff-report.html":
                asset_version = "20260728-responsive1"
            elif html_name == "staff-salary.html":
                asset_version = "20260820-assurance1"
            else:
                asset_version = "20260726-polish6"
            self.assertIn(f"/{style_path}?v={asset_version}", html, html_name)
            for contract in required:
                self.assertTrue(contract in html or contract in styles, f"{html_name}: {contract}")

        entrypoints = {
            "staff-salary.html": "/staff-salary.js?v=20260823-kpiperunit1",
            "staff-adjustments.html": "/staff-adjustments.js?v=20260726-navmore1",
            "staff-report.html": "/staff-report.js?v=20260802-ledgerdrill1",
        }
        for html_name, entrypoint in entrypoints.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            self.assertIn(entrypoint, html)

        salary_summary = (FRONTEND / "staff-salary-summary.html").read_text(encoding="utf-8")
        self.assertIn("redirectToUnifiedSalary", salary_summary)
        self.assertIn("location.replace(`/staff-salary.html?", salary_summary)

    def test_financial_pages_keep_shared_comparison_controls_and_queries(self):
        pages = {
            "owner-turnover": (
                "revenueCompareSeg",
                "revenueCompareFrom",
                "revenueTotalDelta",
            ),
            "owner-expenses": (
                "expensesCompareSeg",
                "expensesCompareFrom",
                "expensesTotalDelta",
            ),
            "owner-payroll": (
                "payrollCompareSeg",
                "payrollCompareFrom",
                "totalAmountDelta",
            ),
            "owner-day-economics": (
                "economicsCompareSeg",
                "economicsCompareDatePick",
                "economicsRevenueDelta",
            ),
        }
        for page_name, contracts in pages.items():
            html = (FRONTEND / f"{page_name}.html").read_text(encoding="utf-8")
            script = (FRONTEND / f"{page_name}.js").read_text(encoding="utf-8")
            self.assertIn("period-comparison.js?v=20260802-financeux2", script, page_name)
            self.assertIn("compareMode", script, page_name)
            for contract in contracts:
                self.assertTrue(contract in html or contract in script, f"{page_name}: {contract}")

        expenses_script = (FRONTEND / "owner-expenses.js").read_text(encoding="utf-8")
        self.assertIn("/expenses/period-summary?", expenses_script)
        revenue_html = (FRONTEND / "owner-turnover.html").read_text(encoding="utf-8")
        revenue_script = (FRONTEND / "owner-turnover.js").read_text(encoding="utf-8")
        self.assertIn("/styles/pages/finance-pages.css?v=20260802-financeux4", revenue_html)
        self.assertIn("/owner-turnover.js?v=20260802-financeux2", revenue_html)
        self.assertIn('id="revenueTrendChart"', revenue_html)
        self.assertIn('id="revenueRowsSubtitle"', revenue_html)
        self.assertIn('primaryQuery.set("include_series", "1")', revenue_script)
        self.assertIn('comparisonQuery.set("include_series", "1")', revenue_script)
        self.assertIn("normalizeRevenueDailySeries", revenue_script)
        self.assertIn("buildRevenueStructure", revenue_script)
        self.assertIn('id="openLedgerBtn"', revenue_html)
        self.assertIn("/owner-finance-ledger.html?", revenue_script)
        comparison_helper = (FRONTEND / "app/period-comparison.js").read_text(encoding="utf-8")
        self.assertIn('if (mode === "week")', comparison_helper)

    def test_auth_adjustments_and_pay_profiles_keep_responsive_visual_states(self):
        contracts = {
            "auth.html": (
                "styles/pages/auth.css",
                ("auth-card", "auth-eyebrow", "auth-next-hint"),
            ),
            "app-adjustments.html": (
                "styles/pages/app-adjustments.css",
                ("app-adjustments-toolbar", "app-adjustments-loading", "app-adjustments-state"),
            ),
            "owner-pay-profiles.html": (
                "styles/pages/owner-pay-profile.css",
                ("pay-profile-bootstrap", "pay-profile-row__actions", "pay-profile-state"),
            ),
            "owner-pay-profile.html": (
                "styles/pages/owner-pay-profile.css",
                ("pay-profile-bootstrap", "pay-profile-detail-grid", "pay-profile-modal-actions"),
            ),
        }

        for html_name, (style_path, required) in contracts.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            styles = (FRONTEND / style_path).read_text(encoding="utf-8")
            cache_key = (
                "20260820-weekdayrates1" if style_path == "styles/pages/owner-pay-profile.css" else "20260726-polish9"
            )
            self.assertIn(f"/{style_path}?v={cache_key}", html, html_name)
            for contract in required:
                self.assertTrue(contract in html or contract in styles, f"{html_name}: {contract}")

        entrypoints = {
            "app-adjustments.html": "/app-adjustments.js?v=20260726-navmore1",
            "owner-pay-profiles.html": "/owner-pay-profiles.js?v=20260726-navmore1",
            "owner-pay-profile.html": "/owner-pay-profile.js?v=20260826-i18nvalue1",
        }
        for html_name, entrypoint in entrypoints.items():
            html = (FRONTEND / html_name).read_text(encoding="utf-8")
            self.assertIn(entrypoint, html)

        adjustments_js = (FRONTEND / "app-adjustments.js").read_text(encoding="utf-8")
        pay_profiles_js = (FRONTEND / "owner-pay-profiles.js").read_text(encoding="utf-8")
        pay_profile_js = (FRONTEND / "owner-pay-profile.js").read_text(encoding="utf-8")
        self.assertIn("async function refreshList()", adjustments_js)
        self.assertIn("await refreshList()", adjustments_js)
        self.assertIn("if (!hasManageAccess())", adjustments_js)
        self.assertIn("if (!state.can.view)", pay_profiles_js)
        self.assertIn("if (!state.can.view)", pay_profile_js)

    def test_owner_payroll_keeps_finance_visual_hierarchy_and_states(self):
        html = (FRONTEND / "owner-payroll.html").read_text(encoding="utf-8")
        script = (FRONTEND / "owner-payroll.js").read_text(encoding="utf-8")
        styles = (FRONTEND / "styles/pages/owner-payroll.css").read_text(encoding="utf-8")

        self.assertIn("/styles/pages/owner-payroll.css?v=20260802-payrollpayments1", html)
        self.assertIn("/owner-payroll.js?v=20260823-kpiperunit1", html)
        self.assertIn('class="owner-payroll-page"', html)
        self.assertIn("payroll-bootstrap", html)
        for contract in (
            "payroll-period-grid",
            "payroll-metric--per-shift",
            "payroll-leaderboard-row",
            "payroll-payment-rule",
            "payroll-person__metrics",
            "payroll-state--error",
            "@media (max-width:560px)",
        ):
            self.assertIn(contract, styles)
        for contract in (
            'id="averageAmount"',
            'id="averagePerShift"',
            'id="payrollLeaderboard"',
            'row.className = "payroll-person"',
            "buildPayrollTeamAnalytics",
            "payrollLineShiftMetrics",
            'id="payrollPaymentMethod"',
            "/payroll/payment-settings",
            "/payroll/payment-drafts/generate",
            "payroll-state--denied",
            "payroll-state--empty",
            "payroll-state--error",
            'setAttribute("aria-busy", "false")',
        ):
            self.assertIn(contract, script)

    def test_owner_catalog_pages_share_responsive_states_and_permission_first_loading(self):
        pages = {
            "owner-departments": "if (!state.can.view)",
            "owner-expense-categories": "if (!state.canView)",
            "owner-kpi": "if (!state.can.view)",
            "owner-payment-methods": "if (!state.can.view)",
            "owner-suppliers": "if (!state.canView)",
        }
        styles = (FRONTEND / "styles/pages/owner-catalogs.css").read_text(encoding="utf-8")

        for page_name, permission_guard in pages.items():
            html = (FRONTEND / f"{page_name}.html").read_text(encoding="utf-8")
            script = (FRONTEND / f"{page_name}.js").read_text(encoding="utf-8")
            self.assertIn("/styles/pages/owner-catalogs.css?v=20260726-polish10", html, page_name)
            self.assertIn(f"/{page_name}.js?v=20260726-navmore1", html, page_name)
            self.assertIn("catalog-bootstrap", html, page_name)
            self.assertIn("catalog-loading", script, page_name)
            self.assertIn("catalog-state--denied", script, page_name)
            self.assertIn("catalog-state--error", script, page_name)
            load_source = script.split("async function load()", 1)[1]
            self.assertIn(permission_guard, load_source, page_name)

        for contract in (
            "catalog-hero",
            "catalog-filter",
            "catalog-row__actions",
            "catalog-modal-actions",
            "@media (max-width:620px)",
        ):
            self.assertIn(contract, styles)

    def test_owner_economics_pages_keep_details_loading_and_permission_first_access(self):
        day_html = (FRONTEND / "owner-day-economics.html").read_text(encoding="utf-8")
        day_script = (FRONTEND / "owner-day-economics.js").read_text(encoding="utf-8")
        rules_html = (FRONTEND / "owner-economics-rules.html").read_text(encoding="utf-8")
        rules_script = (FRONTEND / "owner-economics-rules.js").read_text(encoding="utf-8")
        styles = (FRONTEND / "styles/pages/owner-economics.css").read_text(encoding="utf-8")

        for html, page_name, script_version in (
            (day_html, "owner-day-economics", "20260810-financepolish1"),
            (rules_html, "owner-economics-rules", "20260726-navmore1"),
        ):
            style_version = "20260810-financepolish1" if page_name == "owner-day-economics" else "20260726-polish11"
            self.assertIn(f"/styles/pages/owner-economics.css?v={style_version}", html, page_name)
            self.assertIn(f"/{page_name}.js?v={script_version}", html, page_name)
            self.assertIn('class="finance-page-state hidden"', html, page_name)

        for detail_id in (
            "economicsPaymentRevenueBreakdown",
            "economicsDepartmentRevenueBreakdown",
            "economicsPointExpenses",
            "economicsRecurringExpenses",
            "economicsPaymentBalances",
            "economicsKpiBreakdown",
            "economicsRulesHint",
        ):
            self.assertIn(f'id="{detail_id}"', day_html)
            self.assertIn(f'"{detail_id}"', day_script)

        day_load = day_script.split("async function loadEconomics()", 1)[1]
        self.assertLess(day_load.index("if (!access.canView)"), day_load.index("primaryPromise = api("))
        self.assertIn("setEconomicsLoading(false)", day_load)
        self.assertIn("finance-page-state--denied", styles)
        self.assertIn("Предупреждать о неподтверждённых расходах", day_script)
        self.assertIn("economics-manage-card .section-card__actions .btn", styles)
        self.assertIn("height:54px", styles)

        rules_load = rules_script.split("async function loadRules()", 1)[1]
        self.assertLess(rules_load.index("if (!state.access.canManage)"), rules_load.index("await api("))
        self.assertIn("economics-rules-loading", rules_html)
        self.assertIn("economics-rules-presets", styles)

        revenue_alias = (FRONTEND / "owner-revenue.html").read_text(encoding="utf-8")
        self.assertIn("window.location.search + window.location.hash", revenue_alias)
        self.assertIn("window.location.replace(target)", revenue_alias)


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
        self.assertTrue(
            {
                "api",
                "ensureLogin",
                "mountNav",
                "getMe",
                "getMyVenuePermissions",
                "getDepartments",
                "getPayProfiles",
                "calculatePayroll",
                "trackDemoEvent",
            }.issubset(exported)
        )
        self.assertLess(len(main.splitlines()), 1_800)

        modules = {
            "auth-actions.js": "createAuthActions",
            "venue-api.js": "createVenueApi",
            "navigation.js": "createNavigation",
            "ui-preferences.js": "createUiPreferences",
        }
        for filename, factory in modules.items():
            source = (FRONTEND / "app" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), 500)
            cache_key = {
                "navigation.js": "20260726-navmore1",
                "ui-preferences.js": "20260813-assurance2",
            }.get(filename, "20260719-split1")
            self.assertIn(f"/app/{filename}?v={cache_key}", main)
            self.assertIn(f"export function {factory}", source)

        consumer_pattern = re.compile(r"import\s*\{([\s\S]*?)\}\s*from\s*[\"']/app\.js\?v=20260820-i18nmetrika1[\"']")
        consumer_count = 0
        for path in FRONTEND.rglob("*"):
            if path.suffix not in {".js", ".mjs", ".html"}:
                continue
            source = path.read_text(encoding="utf-8")
            for match in consumer_pattern.finditer(source):
                consumer_count += 1
                imported = {entry.strip().split(" as ", 1)[0] for entry in match.group(1).split(",") if entry.strip()}
                self.assertTrue(imported.issubset(exported), f"{path.name}: {sorted(imported - exported)}")
        self.assertEqual(consumer_count, 53)


class FunctionalFrontendRegressionContractTests(TestCase):
    def test_mobile_bottom_nav_collapses_secondary_links_into_accessible_more_menu(self):
        navigation = (FRONTEND / "app" / "navigation.js").read_text(encoding="utf-8")
        styles = (FRONTEND / "styles" / "core" / "cards-lists.css").read_text(encoding="utf-8")
        preferences = (FRONTEND / "app" / "ui-preferences.js").read_text(encoding="utf-8")

        for token in (
            "const mobilePrimaryLinkCount = 3",
            "const overflowLinks = links.slice(mobilePrimaryLinkCount)",
            'button.textContent = t("more")',
            'button.setAttribute("aria-haspopup", "menu")',
            'button.setAttribute("aria-expanded", "false")',
            'if (event.key === "Escape" && !menu.hidden)',
        ):
            self.assertIn(token, navigation)

        self.assertIn('more: "Ещё"', preferences)
        self.assertIn('more: "More"', preferences)
        self.assertIn(".nav .wrap #nav > .nav-overflow-link{display:none}", styles)
        self.assertIn(".nav-more__menu[hidden]{display:none}", styles)
        self.assertIn(".nav-more__menu{", styles)
        self.assertIn("width:min(220px,calc(100vw - 24px))", styles)
        self.assertIn("min-height:38px", styles)
        self.assertIn("font-size:13px", styles)

    def test_get_requests_do_not_force_cors_preflight_headers(self):
        source = (FRONTEND / "app.js").read_text(encoding="utf-8")
        api_source = source[source.index("export async function api") : source.index("function parseDownloadFilename")]

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

    def test_admin_pages_keep_stable_loading_and_responsive_layout_contracts(self):
        contracts = {
            "admin-billing.html": ("billing-state--loading", "billing-filters"),
            "admin-venues.html": ("admin-venues-skeleton", "admin-venue-card__actions"),
            "admin-demo.html": ("demo-admin-kpi--loading", "demo-admin-section--wide"),
            "admin-demo-analytics.html": ("demo-analytics-state--loading", "demo-analytics-filter-card"),
            "admin-position-templates.html": ("tpl-state--loading", "tpl-toolbar-card"),
        }

        for filename, required_classes in contracts.items():
            source = (FRONTEND / filename).read_text(encoding="utf-8")
            for class_name in required_classes:
                self.assertIn(class_name, source, f"{filename} lost {class_name}")

    def test_shift_planning_pages_keep_stable_loading_and_responsive_layout_contracts(self):
        html_contracts = {
            "staff-shifts.html": (
                "staff-shifts-toolbar__controls",
                "staff-shifts-toolbar__row--scopes",
                "staff-shifts-toolbar__row--planning",
                "staff-shifts-toolbar__row--filters",
                "staff-shifts-tool-button",
                "shifts-calendar-loading",
            ),
            "shift-intervals.html": ("shift-tool-state--loading", "shift-tools.css?v=20260726-polish8"),
            "shift-schedule-templates.html": ("shift-tool-state--loading", "shift-tools.css?v=20260726-polish8"),
        }
        module_contracts = {
            "shift-intervals.js": ("shift-interval-row", "shift-tool-state--empty"),
            "shift-schedule-templates.js": ("shift-template-card", "shift-tool-modal-actions"),
        }

        for filename, required_tokens in html_contracts.items():
            source = (FRONTEND / filename).read_text(encoding="utf-8")
            for token in required_tokens:
                self.assertIn(token, source, f"{filename} lost {token}")
        for filename, required_tokens in module_contracts.items():
            source = (FRONTEND / filename).read_text(encoding="utf-8")
            for token in required_tokens:
                self.assertIn(token, source, f"{filename} lost {token}")

        staff_shifts = (FRONTEND / "staff-shifts.js").read_text(encoding="utf-8")
        templates = (FRONTEND / "shift-schedule-templates.js").read_text(encoding="utf-8")
        self.assertNotIn("Ночь с ${", staff_shifts)
        self.assertNotIn("Ночь с ${", templates)
        self.assertNotIn("с понедельника на вторник", templates)
        self.assertIn("календарной датой её начала", templates)
        self.assertIn("Смена с началом 30-го в 04:00 относится уже к 30-му", templates)


class OwnerSetupSplitContractTests(TestCase):
    def test_owner_setup_keeps_all_editor_modules_and_step_dispatch(self):
        main = (FRONTEND / "owner-setup.js").read_text(encoding="utf-8")
        html = (FRONTEND / "owner-setup.html").read_text(encoding="utf-8")
        controllers = {
            "catalog-editor.js": ("createCatalogSetupController", "mountCatalogEditor", "20260810-setup1"),
            "pay-profile-editor.js": ("createPayProfileSetupController", "mountPayProfilesEditor", "20260729-payroll1"),
            "position-editor.js": ("createPositionSetupController", "mountPositionsEditor", "20260720-unified10"),
            "invite-editor.js": ("createInviteSetupController", "mountInvitesEditor", "20260720-unified10"),
            "shift-interval-editor.js": (
                "createShiftIntervalSetupController",
                "mountShiftIntervalsEditor",
                "20260729-overnight1",
            ),
            "supplier-editor.js": ("createSupplierSetupController", "mountSuppliersEditor", "20260720-unified10"),
            "recurring-expense-editor.js": (
                "createRecurringExpenseSetupController",
                "mountRecurringExpensesEditor",
                "20260729-slotecon1",
            ),
        }

        self.assertLess(len(main.splitlines()), 1_600)
        self.assertIn("owner-setup.js?v=20260810-setup1", html)
        self.assertIn("position-template-ui.js?v=20260726-navmore1", main)
        self.assertNotRegex(html, r"(?:<style\b|\sstyle\s*=|\.style\b)")
        self.assertNotRegex(main, r"(?:<style\b|\sstyle\s*=|\.style\b)")
        self.assertIn('<progress class="setup-progressbar"', main)
        self.assertIn('isSetupDone(state.setup) ? "Настройка завершена"', main)
        resume_helper = main[main.index("function getPhaseResumeStep") : main.index("function renderOverview")]
        self.assertNotIn("visible.find(({ ui }) => !ui.locked)", resume_helper)
        for filename, (factory, mount_method, version) in controllers.items():
            source = (FRONTEND / "owner-setup" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), 500)
            self.assertIn(f"/owner-setup/{filename}?v={version}", main)
            self.assertNotRegex(source, r"(?:<style\b|\sstyle\s*=|\.style\b)")
            self.assertIn(f"export function {factory}", source)
            self.assertIn(mount_method, source)

        step_dispatch = {
            "pay_profiles": "mountPayProfilesEditor",
            "positions": "mountPositionsEditor",
            "invites": "mountInvitesEditor",
            "shift_intervals": "mountShiftIntervalsEditor",
            "suppliers": "mountSuppliersEditor",
            "recurring_expenses": "mountRecurringExpensesEditor",
        }
        for step_key, mount_method in step_dispatch.items():
            step_anchor = main.index(f'currentStep.key === "{step_key}"')
            self.assertIn(mount_method, main[step_anchor : step_anchor + 220])

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
        comments = (FRONTEND / "staff-shifts" / "comment-controller.js").read_text(encoding="utf-8")
        html = (FRONTEND / "staff-shifts.html").read_text(encoding="utf-8")

        self.assertLess(len(main.splitlines()), 2_100)
        self.assertLess(len(module.splitlines()), 900)
        self.assertLess(len(calendar.splitlines()), 850)
        self.assertLess(len(comments.splitlines()), 700)
        self.assertIn("/staff-shifts/export-controller.js?v=20260719-split1", main)
        self.assertIn("/staff-shifts/calendar-controller.js?v=20260729-overnight1", main)
        self.assertIn("/staff-shifts/comment-controller.js?v=20260728-comments1", main)
        self.assertIn("staff-shifts.js?v=20260811-assurance1", html)
        self.assertIn("/shifts/export-metadata?", module)
        self.assertIn("/mentionable-members", comments)
        self.assertIn("reply_to_comment_id", comments)
        self.assertIn("mentioned_user_ids", comments)
        self.assertIn("/shift-availability?", main)
        self.assertIn("/swap-candidates", main)
        self.assertIn("/swap-requests", main)

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
        self.assertIn("owner-pay-profile.js?v=20260826-i18nvalue1", html)
        for filename, (factory, line_limit) in modules.items():
            source = (FRONTEND / "owner-pay-profile" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), line_limit)
            cache_key = "20260723-functional1" if filename == "assignment-controller.js" else "20260826-i18nvalue1"
            self.assertIn(f"/owner-pay-profile/{filename}?v={cache_key}", main)
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

        component_form = (FRONTEND / "owner-pay-profile" / "component-form.js").read_text(encoding="utf-8")
        component_controller = (FRONTEND / "owner-pay-profile" / "component-controller.js").read_text(encoding="utf-8")
        component_support = (FRONTEND / "owner-pay-profile" / "component-support.js").read_text(encoding="utf-8")
        component_list = (FRONTEND / "owner-pay-profile" / "component-list.js").read_text(encoding="utf-8")
        styles = (FRONTEND / "styles/pages/owner-pay-profile.css").read_text(encoding="utf-8")
        for contract in ("f_weekday_rates_section", "data-weekday-enabled", "data-weekday-rate"):
            self.assertIn(contract, component_form)
        self.assertIn("weekday_rates: []", component_controller)
        self.assertIn("readWeekdayRates", component_controller)
        self.assertIn("localizePreservedInputValue", component_controller)
        self.assertIn("preservedInputValue", component_controller)
        self.assertIn("i18nSourceValue", component_support)
        self.assertIn("i18nDisplayValue", component_support)
        self.assertIn("weekday_rates", component_list)
        self.assertIn(".weekday-rate-row", styles)

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
        self.assertIn("positions.js?v=20260726-navmore1", html)
        for filename, (factory, line_limit) in modules.items():
            source = (FRONTEND / "positions" / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), line_limit)
            cache_key = (
                "20260726-navmore1"
                if filename == "permission-controller.js"
                else "20260725-polish4"
                if filename == "invite-controller.js"
                else "20260725-polish3"
                if filename == "position-list.js"
                else "20260723-functional1"
                if filename == "position-editor.js"
                else "20260720-unified6"
            )
            self.assertIn(f"/positions/{filename}?v={cache_key}", main)
            self.assertIn(f"export function {factory}", source)

        editor = (FRONTEND / "positions" / "position-editor.js").read_text(encoding="utf-8")
        position_list = (FRONTEND / "positions" / "position-list.js").read_text(encoding="utf-8")
        invites = (FRONTEND / "positions" / "invite-controller.js").read_text(encoding="utf-8")
        permissions = (FRONTEND / "positions" / "permission-controller.js").read_text(encoding="utf-8")
        self.assertIn("position-template-ui.js?v=20260726-navmore1", permissions)

        for api_call in ("createVenuePosition", "updateVenuePosition", "deleteVenuePosition"):
            self.assertIn(api_call, editor)
        self.assertIn("deleteVenuePosition", position_list)
        self.assertIn("patchInviteDefaultPosition", invites)
        self.assertRegex(invites, r"contact_label\s*\|\|\s*inv\?\.phone")
        self.assertIn("/me/permissions/catalog", permissions)
        self.assertIn("/position-permission-templates", permissions)

        self.assertIn("openCreateModal", main)
        self.assertIn("renderPositions", main)
        self.assertIn("renderInvites", main)

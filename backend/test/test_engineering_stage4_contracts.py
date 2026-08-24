from __future__ import annotations

from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.core import metrics


REPO_DIR = Path(__file__).resolve().parents[2]


class MetricsTests(TestCase):
    def setUp(self):
        metrics._COUNTERS.clear()
        metrics._DURATIONS.clear()

    def test_request_histogram_keeps_aggregates_instead_of_unbounded_samples(self):
        for _ in range(10_000):
            metrics.observe_request(method="get", route="/health", status_code=200, duration_seconds=0.2)

        self.assertEqual(len(metrics._DURATIONS), 1)
        histogram = next(iter(metrics._DURATIONS.values()))
        self.assertEqual(histogram.count, 10_000)
        self.assertAlmostEqual(histogram.total, 2_000.0)
        self.assertEqual(len(histogram.bucket_counts), len(metrics._HISTOGRAM_BUCKETS))

    def test_prometheus_snapshot_contains_runtime_database_and_guardrail_metrics(self):
        rows = MagicMock()
        rows.all.return_value = [("pending", 2), ("failed", 1)]
        failed_payments = MagicMock()
        failed_payments.scalar_one.return_value = 3
        reconciliation = MagicMock()
        reconciliation.scalar_one.return_value = 4
        db = MagicMock()
        failed_jobs = MagicMock()
        failed_jobs.scalar_one.return_value = 1
        db.execute.side_effect = [rows, failed_jobs, failed_payments, reconciliation]

        metrics.observe_request(method="post", route="/auth/login", status_code=401, duration_seconds=0.3)
        metrics.record_auth_failure()
        with patch.object(metrics, "_state_timestamp", return_value=123.0):
            rendered = metrics.render_prometheus(db)

        for contract in (
            f'axelio_build_info{{environment="{metrics.settings.APP_ENV}"',
            'axelio_http_requests_total{method="POST",route="/auth/login",status_class="4xx"} 1',
            "axelio_http_request_duration_seconds_bucket",
            'axelio_notification_jobs{status="failed"} 1',
            'axelio_notification_jobs{status="failed_recent_24h"} 1',
            "axelio_failed_payments_24h 3",
            "axelio_open_reconciliation_issues 4",
            "axelio_backup_last_success_timestamp_seconds 123",
        ):
            self.assertIn(contract, rendered)


class MonitoringContractTests(TestCase):
    def test_notification_runner_is_the_single_shift_reminder_scheduler(self):
        deploy = (REPO_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        rollback = (REPO_DIR / ".github/workflows/rollback.yml").read_text(encoding="utf-8")
        release = (REPO_DIR / "ops/deploy/release.sh").read_text(encoding="utf-8")
        monitor = (REPO_DIR / "ops/monitoring/health-check.sh").read_text(encoding="utf-8")
        monitor_unit = (REPO_DIR / "ops/systemd/axelio-monitor-prod.service").read_text(encoding="utf-8")
        runner = (REPO_DIR / "backend/app/scripts/process_notification_jobs.py").read_text(encoding="utf-8")

        for source in (deploy, rollback, monitor, monitor_unit):
            self.assertNotIn("SHIFT_TIMER", source)
        self.assertNotIn(': "${SHIFT_TIMER:', release)
        self.assertNotIn('restart "${SHIFT_TIMER}"', release)
        self.assertIn(': "${NOTIFY_TIMER:?Set NOTIFY_TIMER}"', release)
        self.assertIn('systemctl restart "${NOTIFY_TIMER}"', release)
        self.assertIn('disable --now "${legacy_shift_timer}"', release)
        self.assertIn("OWNS_SHIFT_REMINDERS = True", runner)
        self.assertIn("send_shift_reminders_once()", runner)

    def test_release_installs_monitor_and_records_backup_and_smoke_success(self):
        release = (REPO_DIR / "ops/deploy/release.sh").read_text(encoding="utf-8")
        backup = (REPO_DIR / "ops/backup/postgres-backup.sh").read_text(encoding="utf-8")
        readiness = (REPO_DIR / "ops/deploy/production-readiness.sh").read_text(encoding="utf-8")

        self.assertIn("axelio-monitor-prod.timer", release)
        self.assertIn("deploy-smoke-last-success.timestamp", release)
        self.assertIn("backup-last-success.timestamp", backup)
        self.assertIn("AXELIO_ALERT_TG_CHAT_IDS", readiness)
        self.assertIn("SUPER_ADMIN_TG_USER_IDS", readiness)
        self.assertIn("Environment=RCLONE_CONFIG=/etc/axelio/rclone.conf", readiness)
        self.assertIn("activate_nginx_performance", release)

        workflow = (REPO_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        self.assertIn("NGINX_ACTIVATE_DRY_RUN=true", workflow)

        backup_unit_install = release[
            release.index("install_backup_units()") : release.index("has_monitoring_sources()")
        ]
        self.assertLess(
            backup_unit_install.index("install -d -m 0755 /var/lib/axelio-monitoring"),
            backup_unit_install.index("systemctl start axelio-backup-prod.service"),
        )
        self.assertIn("journalctl -u axelio-backup-prod.service", backup_unit_install)

    def test_monitor_covers_services_readiness_backup_and_business_failures(self):
        monitor = (REPO_DIR / "ops/monitoring/health-check.sh").read_text(encoding="utf-8")
        for contract in (
            "systemctl is-active",
            "/health/ready",
            "production backup is stale",
            "failed_payments_24h",
            "open_reconciliation_high",
            "failed_notification_jobs_24h",
            "stale_notification_jobs",
            "BOT_SERVICE_URL",
            "BOT_SERVICE_SECRET",
            "notify_result",
            "production recovered",
        ):
            self.assertIn(contract, monitor)

    def test_production_observability_drill_checks_metrics_monitor_and_alert_delivery(self):
        drill = (REPO_DIR / "ops/monitoring/observability-drill.sh").read_text(encoding="utf-8")

        for contract in (
            "METRICS_TOKEN",
            "axelio_build_info",
            "axelio-monitor-prod.service",
            "journalctl -u axelio-monitor-prod.service",
            "last-alert.txt",
            "Failed notification job diagnostics",
            "payload and recipients omitted",
            "BOT_SERVICE_URL",
            "BOT_SERVICE_SECRET",
            "notify_result",
            "test alert",
            "production recovered",
            "observability-drill-last-success.timestamp",
        ):
            self.assertIn(contract, drill)

    def test_production_assurance_drill_uses_the_managed_rclone_config(self):
        drill = (REPO_DIR / "ops/production-assurance-drill.sh").read_text(encoding="utf-8")

        self.assertIn("Environment=RCLONE_CONFIG=/etc/axelio/rclone.conf", drill)


class FrontendAssuranceContractTests(TestCase):
    def test_ci_actions_use_supported_node_runtime_majors(self):
        workflow = (REPO_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

        for action in (
            "actions/checkout@v7",
            "actions/setup-python@v7",
            "actions/setup-node@v7",
            "pnpm/action-setup@v6",
        ):
            self.assertIn(action, workflow)

        for legacy_action in (
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "actions/setup-node@v4",
            "pnpm/action-setup@v4",
        ):
            self.assertNotIn(legacy_action, workflow)

    def test_ci_enforces_accessibility_and_performance_budgets(self):
        workflow = (REPO_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        browser = (REPO_DIR / "tools/browser-e2e.mjs").read_text(encoding="utf-8")
        budgets = (REPO_DIR / "tools/performance-budgets.json").read_text(encoding="utf-8")

        self.assertIn("Enforce frontend performance budgets", workflow)
        self.assertIn("axe.run", browser)
        self.assertIn('["critical", "serious"]', browser)
        self.assertIn("budgetKey.replace(/^max([A-Z])/", browser)
        for page in (
            "auth",
            "owner-venues",
            "owner-summary",
            "owner-expenses",
            "owner-payroll",
            "owner-settings",
            "owner-positions",
            "owner-day-economics",
            "staff-shifts",
            "staff-salary",
            "public-demo",
        ):
            self.assertIn(f'"{page}"', budgets)

        self.assertIn("scenarioCount: 12", browser)
        self.assertIn('{ name: "desktop", width: 1440, height: 900 }', browser)
        self.assertIn('{ name: "mobile", width: 375, height: 812 }', browser)
        for scenario in (
            "owner-auth",
            "owner-venues",
            "owner-summary",
            "owner-expenses",
            "owner-payroll",
            "owner-settings",
            "owner-positions",
            "owner-day-economics",
            "staff-auth",
            "staff-shifts",
            "staff-salary",
            "public-demo-readonly",
        ):
            self.assertIn(f'"{scenario}"', browser)

        self.assertIn("--data-file=.coverage.unit", workflow)
        self.assertIn("--data-file=.coverage.e2e", workflow)
        self.assertIn("coverage combine --keep", workflow)
        self.assertIn("--fail-under=60", workflow)

    def test_versioned_static_assets_are_immutable_and_smoke_checked(self):
        cache_map = (REPO_DIR / "ops/nginx/axelio-cache-map.conf").read_text(encoding="utf-8")
        performance = (REPO_DIR / "ops/nginx/axelio-performance.conf").read_text(encoding="utf-8")
        release = (REPO_DIR / "ops/deploy/release.sh").read_text(encoding="utf-8")
        smoke = (REPO_DIR / "ops/deploy/post-deploy-smoke.sh").read_text(encoding="utf-8")

        self.assertIn("max-age=31536000, immutable", cache_map)
        self.assertIn("$arg_v", cache_map)
        self.assertIn("$axelio_versioned_cache_control", performance)
        self.assertIn("/etc/nginx/conf.d/axelio-cache-map.conf", release)
        self.assertIn("page-loader.js?v=${EXPECTED_RELEASE}", smoke)
        self.assertIn("max-age=31536000, immutable", smoke)
        self.assertIn("runtime-config.json", smoke)
        self.assertIn("no-store", smoke)

    def test_largest_frontend_facades_delegate_to_bounded_modules(self):
        app = (REPO_DIR / "frontend/app.js").read_text(encoding="utf-8")
        shifts = (REPO_DIR / "frontend/staff-shifts.js").read_text(encoding="utf-8")
        preferences = REPO_DIR / "frontend/app/ui-preferences.js"
        helpers = REPO_DIR / "frontend/staff-shifts/helpers.js"

        self.assertIn("createUiPreferences", app)
        self.assertIn("staff-shifts/helpers.js", shifts)
        self.assertLess(len(preferences.read_text(encoding="utf-8").splitlines()), 250)
        self.assertLess(len(helpers.read_text(encoding="utf-8").splitlines()), 180)


class DocumentationContractTests(TestCase):
    def test_engineering_entrypoints_and_runbooks_are_present(self):
        for relative in (
            "README.md",
            "CONTRIBUTING.md",
            "SECURITY.md",
            "backend/docs/architecture.md",
            "backend/docs/engineering-stage3-runbook.md",
            "backend/docs/engineering-stage4-runbook.md",
            "backend/docs/engineering-assurance.md",
            "backend/docs/production-rollback-drill-2026-08-20.md",
        ):
            path = REPO_DIR / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(len(path.read_text(encoding="utf-8")), 500, relative)


if __name__ == "__main__":
    import unittest

    unittest.main()

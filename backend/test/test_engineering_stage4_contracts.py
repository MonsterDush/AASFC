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
        db.execute.side_effect = [rows, failed_payments, reconciliation]

        metrics.observe_request(method="post", route="/auth/login", status_code=401, duration_seconds=0.3)
        metrics.record_auth_failure()
        with patch.object(metrics, "_state_timestamp", return_value=123.0):
            rendered = metrics.render_prometheus(db)

        for contract in (
            f'axelio_build_info{{environment="{metrics.settings.APP_ENV}"',
            'axelio_http_requests_total{method="POST",route="/auth/login",status_class="4xx"} 1',
            "axelio_http_request_duration_seconds_bucket",
            'axelio_notification_jobs{status="failed"} 1',
            "axelio_failed_payments_24h 3",
            "axelio_open_reconciliation_issues 4",
            "axelio_backup_last_success_timestamp_seconds 123",
        ):
            self.assertIn(contract, rendered)


class MonitoringContractTests(TestCase):
    def test_release_installs_monitor_and_records_backup_and_smoke_success(self):
        release = (REPO_DIR / "ops/deploy/release.sh").read_text(encoding="utf-8")
        backup = (REPO_DIR / "ops/backup/postgres-backup.sh").read_text(encoding="utf-8")
        readiness = (REPO_DIR / "ops/deploy/production-readiness.sh").read_text(encoding="utf-8")

        self.assertIn("axelio-monitor-prod.timer", release)
        self.assertIn("deploy-smoke-last-success.timestamp", release)
        self.assertIn("backup-last-success.timestamp", backup)
        self.assertIn("AXELIO_ALERT_TG_CHAT_IDS", readiness)
        self.assertIn("SUPER_ADMIN_TG_USER_IDS", readiness)
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
            "failed_notification_jobs",
            "stale_notification_jobs",
            "sendMessage",
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
            "test alert",
            "production recovered",
            "observability-drill-last-success.timestamp",
        ):
            self.assertIn(contract, drill)


class FrontendAssuranceContractTests(TestCase):
    def test_ci_enforces_accessibility_and_performance_budgets(self):
        workflow = (REPO_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
        browser = (REPO_DIR / "tools/browser-e2e.mjs").read_text(encoding="utf-8")
        budgets = (REPO_DIR / "tools/performance-budgets.json").read_text(encoding="utf-8")

        self.assertIn("Enforce frontend performance budgets", workflow)
        self.assertIn("axe.run", browser)
        self.assertIn('["critical", "serious"]', browser)
        self.assertIn('budgetKey.replace(/^max([A-Z])/', browser)
        for page in (
            "auth",
            "owner-summary",
            "owner-expenses",
            "owner-payroll",
            "owner-settings",
            "staff-shifts",
            "public-demo",
        ):
            self.assertIn(f'"{page}"', budgets)

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
        ):
            path = REPO_DIR / relative
            self.assertTrue(path.is_file(), relative)
            self.assertGreater(len(path.read_text(encoding="utf-8")), 500, relative)


if __name__ == "__main__":
    import unittest

    unittest.main()

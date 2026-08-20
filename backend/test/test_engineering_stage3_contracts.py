from __future__ import annotations

from pathlib import Path
from unittest import TestCase


REPO_DIR = Path(__file__).resolve().parents[2]


class DeploymentContractTests(TestCase):
    def test_deploy_waits_for_quality_and_uses_managed_release_script(self):
        workflow = (REPO_DIR / ".github/workflows/deploy.yml").read_text(encoding="utf-8")

        self.assertIn("needs: quality", workflow)
        self.assertIn("group: deploy-${{ github.ref_name }}", workflow)
        self.assertIn("name: ${{ github.ref_name == 'main' && 'production' || 'development' }}", workflow)
        self.assertIn('"${DEPLOY_TOOL_DIR}/release.sh" deploy', workflow)
        self.assertIn("Encrypted PostgreSQL backup and restore drill", workflow)
        self.assertIn("production_readiness:", workflow)
        self.assertIn("Verify production observability and offsite backup", workflow)

    def test_release_requires_backup_before_production_migration_and_supports_rollback(self):
        release = (REPO_DIR / "ops/deploy/release.sh").read_text(encoding="utf-8")

        activation = release[release.index("activate_release() {") : release.index("handle_failure() {")]
        self.assertLess(activation.index("install_backup_units"), activation.index("run_migrations"))
        self.assertIn("automatic-rollback", release)
        self.assertIn("manual-rollback", release)
        self.assertIn("release.sh {deploy|rollback}", release)
        self.assertNotIn('alembic" downgrade', release)

    def test_production_readiness_requires_sentry_and_executes_offsite_backup(self):
        readiness = (REPO_DIR / "ops/deploy/production-readiness.sh").read_text(encoding="utf-8")

        self.assertIn("SENTRY_DSN", readiness)
        self.assertIn("BOT_SERVICE_URL", readiness)
        self.assertIn("BOT_SERVICE_SECRET", readiness)
        self.assertIn("BACKUP_ENCRYPTION_PASSWORD", readiness)
        self.assertIn("BACKUP_RCLONE_REMOTE", readiness)
        self.assertIn("BACKUP_REQUIRE_OFFSITE=true", readiness)
        self.assertIn('"${BACKUP_SCRIPT}"', readiness)

    def test_manual_production_rollback_uses_protected_environment(self):
        workflow = (REPO_DIR / ".github/workflows/rollback.yml").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("name: ${{ inputs.environment }}", workflow)
        self.assertIn('"${DEPLOY_TOOL_DIR}/release.sh" rollback', workflow)

    def test_rollback_metadata_survives_a_newer_database_revision_and_records_rto(self):
        release = (REPO_DIR / "ops/deploy/release.sh").read_text(encoding="utf-8")
        evidence = (REPO_DIR / "backend/docs/production-rollback-drill-2026-08-20.md").read_text(encoding="utf-8")

        self.assertIn("SELECT version_num FROM alembic_version", release)
        self.assertIn("duration_seconds", release)
        self.assertIn("32379273355", evidence)
        self.assertIn("32379473585", evidence)
        self.assertIn("approximately 11 seconds", evidence)


class BackupContractTests(TestCase):
    def test_backup_is_encrypted_verified_offsite_and_retained(self):
        backup = (REPO_DIR / "ops/backup/postgres-backup.sh").read_text(encoding="utf-8")

        self.assertIn("pg_dump", backup)
        self.assertIn("aes-256-cbc", backup)
        self.assertGreaterEqual(backup.count("pg_restore --list"), 2)
        self.assertIn("BACKUP_REQUIRE_OFFSITE", backup)
        self.assertIn("rclone copyto", backup)
        self.assertIn("rclone check", backup)
        self.assertIn('--include "/${base_name}"', backup)
        self.assertIn("-mtime +7 -delete", backup)
        self.assertIn("-mtime +28 -delete", backup)

    def test_restore_drill_uses_separate_suffixed_database_and_compares_critical_tables(self):
        restore = (REPO_DIR / "ops/backup/restore-drill.sh").read_text(encoding="utf-8")

        self.assertIn("_restore_drill", restore)
        self.assertIn("pg_restore", restore)
        self.assertIn("alembic_bin", restore)
        self.assertIn("source_count", restore)
        self.assertIn("restored_count", restore)

    def test_production_drill_restores_fresh_snapshot_and_records_rpo_rto(self):
        workflow = (REPO_DIR / ".github/workflows/production-drill.yml").read_text(encoding="utf-8")
        drill = (REPO_DIR / "ops/backup/production-restore-drill.sh").read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch", workflow)
        self.assertIn("name: production", workflow)
        self.assertIn("_restore_drill", drill)
        self.assertIn('REPO_DIR="${APP_ROOT}/repo"', drill)
        self.assertIn("actual_rpo_seconds", drill)
        self.assertIn("actual_rto_seconds", drill)
        self.assertIn("critical_table_counts=matched", drill)


if __name__ == "__main__":
    import unittest

    unittest.main()

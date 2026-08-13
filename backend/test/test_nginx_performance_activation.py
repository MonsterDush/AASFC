from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import TestCase


REPO_DIR = Path(__file__).resolve().parents[2]
ACTIVATOR = REPO_DIR / "ops/nginx/activate-performance.sh"


class NginxPerformanceActivationTests(TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.available = self.root / "sites-available"
        self.enabled = self.root / "sites-enabled"
        self.snippets = self.root / "snippets"
        self.backups = self.root / "backups"
        self.available.mkdir()
        self.enabled.mkdir()
        self.snippets.mkdir()
        self.security = self.snippets / "axelio-security-headers.conf"
        self.performance = self.snippets / "axelio-performance.conf"
        self.security.write_text("add_header X-Test enabled;\n", encoding="utf-8")
        self.performance.write_text("gzip on;\n", encoding="utf-8")
        self.config = self.available / "axelio"
        self.original = (
            "server {\n"
            "    server_name app.axelio.ru api.axelio.ru;\n"
            f"    include {self.security};\n"
            "}\n"
        )
        self.config.write_text(self.original, encoding="utf-8")
        (self.enabled / "axelio").symlink_to(self.config)

    def tearDown(self):
        self.temporary.cleanup()

    def environment(self, nginx_bin: str, *, dry_run: bool = False) -> dict[str, str]:
        environment = {
            **os.environ,
            "NGINX_SITES_ROOT": str(self.enabled),
            "NGINX_ALLOWED_ROOT": str(self.root),
            "AXELIO_SECURITY_INCLUDE": str(self.security),
            "AXELIO_PERFORMANCE_INCLUDE": str(self.performance),
            "NGINX_BACKUP_ROOT": str(self.backups),
            "NGINX_BIN": nginx_bin,
        }
        if dry_run:
            environment["NGINX_ACTIVATE_DRY_RUN"] = "true"
        return environment

    def run_activator(
        self,
        nginx_bin: str,
        *,
        check: bool = True,
        dry_run: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(ACTIVATOR)],
            check=check,
            capture_output=True,
            env=self.environment(nginx_bin, dry_run=dry_run),
            text=True,
        )

    def test_activation_is_idempotent_and_keeps_a_backup(self):
        true_bin = shutil.which("true")
        self.assertIsNotNone(true_bin)

        self.run_activator(str(true_bin))
        self.run_activator(str(true_bin))

        rendered = self.config.read_text(encoding="utf-8")
        self.assertEqual(rendered.count(f"include {self.performance};"), 1)
        manifests = list(self.backups.glob("*/manifest.txt"))
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0].read_text(encoding="utf-8").strip(), str(self.config.resolve()))

    def test_failed_nginx_validation_restores_original_config(self):
        false_bin = shutil.which("false")
        self.assertIsNotNone(false_bin)

        result = self.run_activator(str(false_bin), check=False)

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_text(encoding="utf-8"), self.original)
        self.assertIn("original configuration restored", result.stderr)

    def test_dry_run_validates_without_editing_or_creating_a_backup(self):
        true_bin = shutil.which("true")
        self.assertIsNotNone(true_bin)

        result = self.run_activator(str(true_bin), dry_run=True)

        self.assertEqual(self.config.read_text(encoding="utf-8"), self.original)
        self.assertFalse(self.backups.exists())
        self.assertIn("activation is ready for 1 config file", result.stdout)


if __name__ == "__main__":
    import unittest

    unittest.main()

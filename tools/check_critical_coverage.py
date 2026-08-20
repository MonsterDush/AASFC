#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


THRESHOLDS = {
    "app/auth/jwt_tokens.py": 95.0,
    "app/auth/passwords.py": 90.0,
    "app/core/permission_policy.py": 100.0,
    "app/services/billing/access.py": 75.0,
    "app/services/billing/state.py": 90.0,
    "app/services/finance/recognition.py": 85.0,
    "app/services/financial_privacy.py": 100.0,
    "app/services/payroll/calculator.py": 75.0,
    "app/services/security_rate_limits.py": 90.0,
    "app/services/signed_links.py": 100.0,
}


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="axelio-critical-coverage-") as tmp_dir:
        report_path = Path(tmp_dir) / "coverage.json"
        subprocess.run(
            [sys.executable, "-m", "coverage", "json", "-o", str(report_path)],
            check=True,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))

    files = report.get("files") or {}
    failures: list[str] = []
    print("Critical module coverage:")
    for filename, threshold in THRESHOLDS.items():
        summary = (files.get(filename) or {}).get("summary")
        if summary is None:
            failures.append(f"{filename}: missing from coverage data")
            continue
        covered = float(summary.get("percent_covered", 0.0))
        print(f"  {filename}: {covered:.1f}% (required {threshold:.1f}%)")
        if covered + 1e-9 < threshold:
            failures.append(f"{filename}: {covered:.1f}% < {threshold:.1f}%")

    if failures:
        print("Critical coverage gate failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

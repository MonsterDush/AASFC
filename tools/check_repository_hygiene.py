#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


SOURCE_SUFFIXES = {".css", ".html", ".js", ".mjs", ".py"}
COPY_STYLE_NAME = re.compile(r"(?: copy| \(\d+\)| \d+)(?=\.[^.]+$)", re.IGNORECASE)


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [Path(raw.decode("utf-8")) for raw in result.stdout.split(b"\0") if raw]


def main() -> int:
    offenders = [
        path
        for path in tracked_files()
        if path.exists() and path.suffix.lower() in SOURCE_SUFFIXES and COPY_STYLE_NAME.search(path.name)
    ]
    if offenders:
        print("Copy-style source filenames are forbidden:", file=sys.stderr)
        for path in offenders:
            print(f"  - {path}", file=sys.stderr)
        return 1
    print("repository hygiene: no copy-style source filenames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

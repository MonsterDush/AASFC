#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


SOURCE_SUFFIXES = {".css", ".html", ".js", ".mjs", ".py"}
COPY_STYLE_NAME = re.compile(r"(?: copy| \(\d+\)| \d+)(?=\.[^.]+$)", re.IGNORECASE)
MAX_TRACKED_FILE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_FILE_BYTES = 512 * 1024
FORBIDDEN_PARTS = {".pnpm-store", ".venv", "__pycache__", "node_modules"}


def tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        check=True,
        stdout=subprocess.PIPE,
    )
    return [Path(raw.decode("utf-8")) for raw in result.stdout.split(b"\0") if raw]


def main() -> int:
    files = tracked_files()
    copy_offenders = [
        path
        for path in files
        if path.exists() and path.suffix.lower() in SOURCE_SUFFIXES and COPY_STYLE_NAME.search(path.name)
    ]
    if copy_offenders:
        print("Copy-style source filenames are forbidden:", file=sys.stderr)
        for path in copy_offenders:
            print(f"  - {path}", file=sys.stderr)
        return 1

    generated_offenders = [path for path in files if FORBIDDEN_PARTS.intersection(path.parts)]
    if generated_offenders:
        print("Generated dependency/cache files must not be tracked:", file=sys.stderr)
        for path in generated_offenders:
            print(f"  - {path}", file=sys.stderr)
        return 1

    oversized = []
    for path in files:
        if not path.is_file():
            continue
        size = path.stat().st_size
        limit = MAX_SOURCE_FILE_BYTES if path.suffix.lower() in SOURCE_SUFFIXES else MAX_TRACKED_FILE_BYTES
        if size > limit:
            oversized.append((path, size, limit))
    if oversized:
        print("Tracked files exceed repository size limits:", file=sys.stderr)
        for path, size, limit in oversized:
            print(f"  - {path}: {size} bytes (limit {limit})", file=sys.stderr)
        print("Compress/split the file or store it outside Git before committing.", file=sys.stderr)
        return 1

    print(
        "repository hygiene: names, generated paths, and tracked file sizes are within policy "
        f"(source <= {MAX_SOURCE_FILE_BYTES} bytes; other <= {MAX_TRACKED_FILE_BYTES} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

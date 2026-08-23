from __future__ import annotations

import uuid
from pathlib import Path


def ensure_upload_root(root: str | Path) -> Path:
    resolved = Path(root).resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def new_upload_storage_path(root: str | Path) -> Path:
    resolved_root = ensure_upload_root(root)
    return resolved_root / uuid.uuid4().hex


def confined_upload_storage_path(root: str | Path, stored_path: str | Path) -> Path:
    resolved_root = Path(root).resolve()
    candidate = Path(stored_path).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("Stored upload path is outside its configured root") from exc
    return candidate

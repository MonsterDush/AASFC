from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_backend_module():
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / "backend" / "app" / "scripts" / "send_shift_reminders.py"
    if not candidate.exists():
        raise RuntimeError(f"send_shift_reminders.py not found: {candidate}")

    spec = spec_from_file_location("axelio_backend_send_shift_reminders", candidate)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load shift reminders module from {candidate}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = _load_backend_module()
    if not hasattr(module, "main"):
        raise RuntimeError("backend shift reminders module does not export main()")
    return int(module.main() or 0)

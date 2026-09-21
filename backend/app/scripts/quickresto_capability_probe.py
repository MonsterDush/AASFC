from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app.services.integrations.quickresto import QuickRestoClient, QuickRestoConfig
from app.services.integrations.quickresto_discovery import discover_quickresto_capabilities


_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _build_config_from_env(*, timeout_seconds: float) -> QuickRestoConfig:
    load_dotenv(_BACKEND_DIR / ".env", override=False)
    return QuickRestoConfig(
        cloud=os.getenv("QUICKRESTO_CLOUD", ""),
        login=os.getenv("QUICKRESTO_API_LOGIN", ""),
        password=os.getenv("QUICKRESTO_API_PASSWORD", ""),
        timeout_seconds=timeout_seconds,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only QuickResto capability discovery without retaining payload values"
    )
    parser.add_argument("--sample-limit", type=int, default=5, help="Rows sampled per API surface (1..20)")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=45.0,
        help="Per-request timeout (1..120 seconds)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Absolute JSON output path; defaults to /private/tmp",
    )
    args = parser.parse_args()

    output_path = args.output or Path(
        "/private/tmp/axelio-quickresto-capabilities-"
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    if not output_path.is_absolute():
        raise ValueError("Capability probe output path must be absolute")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    config = _build_config_from_env(timeout_seconds=float(args.timeout_seconds))
    with QuickRestoClient(config) as client:
        report = discover_quickresto_capabilities(client, sample_limit=int(args.sample_limit))
    payload = report.to_dict()
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    states: dict[str, int] = {}
    for probe in payload["capabilities"].values():
        state = str(probe["state"])
        states[state] = states.get(state, 0) + 1
    print(
        json.dumps(
            {
                "ok": True,
                "contains_payload_values": False,
                "surface_count": len(payload["surfaces"]),
                "capability_states": states,
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

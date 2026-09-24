from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
from typing import Any


_HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}

_STAGE_FOUR_IMPLEMENTED = {
    ("POST", "/api/1/access_token"),
    ("POST", "/api/v2/access_token"),
    ("POST", "/api/1/organizations"),
    ("POST", "/api/1/terminal_groups"),
    ("POST", "/api/1/terminal_groups/is_alive"),
    ("POST", "/api/1/nomenclature"),
    ("POST", "/api/1/payment_types"),
    ("POST", "/api/1/deliveries/order_types"),
    ("POST", "/api/1/discounts"),
    ("POST", "/api/1/cancel_causes"),
    ("POST", "/api/1/removal_types"),
    ("POST", "/api/1/tips_types"),
    ("POST", "/api/1/marketing_sources"),
    ("POST", "/api/1/stop_lists"),
    ("POST", "/api/1/reserve/available_restaurant_sections"),
}


def _planned_stage(tags: list[str], endpoint: str) -> str:
    joined = " ".join(tags).lower()
    if endpoint.startswith("/api/inventory/"):
        return "9"
    if endpoint.startswith("/api/nomenclature/"):
        return "4/9"
    if "employee" in joined:
        return "8"
    if any(value in joined for value in ("customer", "loyalty", "discounts and promotions")):
        return "10"
    if any(value in joined for value in ("deliver", "banquet", "reserve")):
        return "10"
    if "webhook" in joined:
        return "5"
    if any(value in joined for value in ("order", "report")):
        return "5/6/7"
    if any(value in joined for value in ("menu", "dictionary", "organization", "terminal")):
        return "4"
    return "later"


def build_matrix(spec: dict[str, Any], *, generated_on: date, source_url: str) -> str:
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        raise ValueError("OpenAPI document has no paths object")
    operations: list[tuple[str, str, list[str], str]] = []
    for endpoint, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            tags = [str(item) for item in operation.get("tags") or []]
            summary = " ".join(str(operation.get("summary") or "").split())
            operations.append((str(endpoint), method.upper(), tags, summary))
    operations.sort(key=lambda item: (item[0], item[1]))

    lines = [
        "# iikoCloud API endpoint matrix",
        "",
        f"Generated from the official OpenAPI schema on {generated_on.isoformat()}.",
        f"Source: {source_url}",
        "",
        f"Operations inventoried: **{len(operations)}** across **{len(paths)}** paths.",
        "",
        "Status semantics:",
        "",
        "- `BLOCKED`: adapter and contract test exist, but no successful live account probe has been recorded;",
        "- `NOT_IMPLEMENTED`: endpoint is classified but not implemented in the current stage;",
        "- `SUPPORTED` is intentionally absent until a successful live probe.",
        "",
        "| Method | Endpoint | Official domain | Status | Planned stage | Summary |",
        "|---|---|---|---|---|---|",
    ]
    for endpoint, method, tags, summary in operations:
        implemented = (method, endpoint) in _STAGE_FOUR_IMPLEMENTED
        status = "BLOCKED" if implemented else "NOT_IMPLEMENTED"
        stage = "4" if implemented else _planned_stage(tags, endpoint)
        domain = ", ".join(tags) or "—"
        safe_summary = summary.replace("|", "\\|") or "—"
        lines.append(f"| `{method}` | `{endpoint}` | {domain} | `{status}` | {stage} | {safe_summary} |")
    lines.extend(
        [
            "",
            "## Stage 4 live gate",
            "",
            "The Stage 4 adapter must not move an endpoint or capability to `SUPPORTED` until",
            "that exact call succeeds against the selected iiko organization and its response",
            "shape is recorded without credentials, tokens or business payload values.",
            "",
            "Regenerate after an official schema update:",
            "",
            "```bash",
            "cd backend",
            ".venv/bin/python tools/generate_iiko_api_matrix.py \\",
            "  --openapi /path/to/iiko-openapi.json \\",
            "  --output docs/integrations/iiko-api-matrix.md \\",
            f"  --generated-on {generated_on.isoformat()}",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the complete iikoCloud endpoint matrix")
    parser.add_argument("--openapi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--generated-on", type=date.fromisoformat, required=True)
    parser.add_argument(
        "--source-url",
        default="https://api-ru.iiko.services/api-docs/docs",
    )
    args = parser.parse_args()
    spec = json.loads(args.openapi.read_text(encoding="utf-8"))
    rendered = build_matrix(spec, generated_on=args.generated_on, source_url=args.source_url)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

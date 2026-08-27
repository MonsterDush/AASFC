from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from app.services.integrations.quickresto import QuickRestoClient, QuickRestoConfig


_BACKEND_DIR = Path(__file__).resolve().parents[2]

_OBJECT_TYPES: dict[str, tuple[str, str]] = {
    "payment_types": (
        "core.dictionaries.paymenttypes",
        "ru.edgex.quickresto.modules.core.dictionaries.paymenttypes.PaymentType",
    ),
    "sale_places": (
        "warehouse.nomenclature.sale_place",
        "ru.edgex.quickresto.modules.warehouse.nomenclature.sale_place.SalePlace",
    ),
    "venues": (
        "front.tablemanagement",
        "ru.edgex.quickresto.modules.front.tablemanagement.TableScheme",
    ),
    "dish_categories": (
        "warehouse.nomenclature.dish",
        "ru.edgex.quickresto.modules.warehouse.nomenclature.dish.DishCategory",
    ),
    "dishes": (
        "warehouse.nomenclature.dish",
        "ru.edgex.quickresto.modules.warehouse.nomenclature.dish.Dish",
    ),
    "shifts": (
        "front.zreport",
        "ru.edgex.quickresto.modules.front.zreport.Shift",
    ),
    "orders": (
        "front.orders",
        "ru.edgex.quickresto.modules.front.orders.OrderInfo",
    ),
}

_REDACTED_KEYS = {
    "password",
    "login",
    "email",
    "phonenumber",
    "phone",
    "firstname",
    "middlename",
    "lastname",
    "fullname",
    "shortname",
    "contactmethods",
    "payerguid",
    "customerguid",
    "customerrefid",
    "paymentuserdocid",
    "userdocid",
    "comment",
    "returncomment",
}


def _redact(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if not isinstance(value, dict):
        return value
    output: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key).replace("_", "").lower()
        output[str(key)] = "[redacted]" if normalized_key in _REDACTED_KEYS else _redact(item)
    return output


def collect_probe_snapshot(
    client: QuickRestoClient,
    *,
    limit: int,
    include_details: bool = True,
) -> dict[str, Any]:
    objects: dict[str, list[dict[str, Any]]] = {}
    for key, (module_name, class_name) in _OBJECT_TYPES.items():
        rows = client.list_objects(module_name=module_name, class_name=class_name, limit=limit)
        objects[key] = _redact(rows)

    details: dict[str, list[dict[str, Any]]] = {}
    if include_details:
        for key in ("shifts", "orders"):
            module_name, class_name = _OBJECT_TYPES[key]
            details[key] = []
            for row in objects[key]:
                object_id = int(row.get("id") or 0)
                if object_id <= 0:
                    continue
                detail = client.read_object(
                    module_name=module_name,
                    class_name=class_name,
                    object_id=object_id,
                )
                details[key].append(_redact(detail))

    counts = {key: len(rows) for key, rows in objects.items()}
    closed_shifts = [row for row in objects["shifts"] if str(row.get("status") or "").upper() == "CLOSED"]
    returned_orders = [row for row in objects["orders"] if bool(row.get("returned"))]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cloud": client.config.cloud,
        "read_only": True,
        "limit_per_object_type": int(limit),
        "counts": counts,
        "closed_shift_count": len(closed_shifts),
        "returned_order_count": len(returned_orders),
        "possibly_truncated": [key for key, count in counts.items() if count >= int(limit)],
        "objects": objects,
        "details": details,
    }


def _build_config_from_env() -> QuickRestoConfig:
    load_dotenv(_BACKEND_DIR / ".env", override=False)
    return QuickRestoConfig(
        cloud=os.getenv("QUICKRESTO_CLOUD", ""),
        login=os.getenv("QUICKRESTO_API_LOGIN", ""),
        password=os.getenv("QUICKRESTO_API_PASSWORD", ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only QuickResto API structure probe")
    parser.add_argument("--limit", type=int, default=500, help="Maximum rows per object type (1..1000)")
    parser.add_argument(
        "--skip-details",
        action="store_true",
        help="Skip per-object read calls for shifts and orders",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output JSON path; defaults to a timestamped file under /private/tmp",
    )
    args = parser.parse_args()

    config = _build_config_from_env()
    output_path = args.output or Path(
        f"/private/tmp/axelio-quickresto-probe-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    if not output_path.is_absolute():
        raise ValueError("Probe output path must be absolute")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with QuickRestoClient(config) as client:
        snapshot = collect_probe_snapshot(
            client,
            limit=int(args.limit),
            include_details=not bool(args.skip_details),
        )

    output_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "cloud": config.cloud,
                "counts": snapshot["counts"],
                "closed_shift_count": snapshot["closed_shift_count"],
                "returned_order_count": snapshot["returned_order_count"],
                "possibly_truncated": snapshot["possibly_truncated"],
                "output": str(output_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

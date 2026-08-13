from __future__ import annotations

import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import engine


_STARTED_AT = time.time()
_LOCK = threading.Lock()
_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_HISTOGRAM_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


@dataclass
class _Histogram:
    bucket_counts: list[int] = field(default_factory=lambda: [0] * len(_HISTOGRAM_BUCKETS))
    count: int = 0
    total: float = 0.0


_DURATIONS: dict[tuple[tuple[str, str], ...], _Histogram] = defaultdict(_Histogram)


def _labels(**labels: object) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(key), str(value)) for key, value in labels.items()))


def increment(name: str, amount: float = 1.0, **labels: object) -> None:
    with _LOCK:
        _COUNTERS[(name, _labels(**labels))] += float(amount)


def observe_request(*, method: str, route: str, status_code: int, duration_seconds: float) -> None:
    labels = _labels(method=method.upper(), route=route, status_class=f"{int(status_code) // 100}xx")
    duration = max(0.0, float(duration_seconds))
    with _LOCK:
        _COUNTERS[("axelio_http_requests_total", labels)] += 1.0
        histogram = _DURATIONS[labels]
        histogram.count += 1
        histogram.total += duration
        for index, bucket in enumerate(_HISTOGRAM_BUCKETS):
            if duration <= bucket:
                histogram.bucket_counts[index] += 1


def record_auth_failure(provider: str = "password") -> None:
    increment("axelio_auth_failures_total", provider=provider)


def record_rate_limit_block(scope: str) -> None:
    increment("axelio_rate_limit_blocks_total", scope=str(scope or "unknown"))


def record_database_error(operation: str = "request") -> None:
    increment("axelio_database_errors_total", operation=operation)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(f'{key}="{_escape(value)}"' for key, value in labels) + "}"


def _sample(name: str, value: float, labels: tuple[tuple[str, str], ...] = ()) -> str:
    rendered = "0" if value == 0 else f"{float(value):.12g}"
    return f"{name}{_format_labels(labels)} {rendered}"


def _state_timestamp(name: str) -> float:
    path = Path(settings.MONITORING_STATE_DIR) / name
    try:
        value = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0.0
    return value if math.isfinite(value) and value >= 0 else 0.0


def _database_gauges(db: Session) -> list[str]:
    from app.models import BillingReconciliationIssue, NotificationJob, VenueBillingTransaction

    lines = ["# HELP axelio_notification_jobs Notification jobs grouped by status."]
    lines.append("# TYPE axelio_notification_jobs gauge")
    rows = db.execute(
        select(NotificationJob.status, func.count(NotificationJob.id)).group_by(NotificationJob.status)
    ).all()
    counts = {str(status or "unknown"): int(count or 0) for status, count in rows}
    for status in sorted({"pending", "processing", "processed", "failed", *counts}):
        lines.append(_sample("axelio_notification_jobs", float(counts.get(status, 0)), _labels(status=status)))

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    failed_jobs_24h = db.execute(
        select(func.count(NotificationJob.id)).where(
            NotificationJob.status == "failed",
            NotificationJob.updated_at >= since,
        )
    ).scalar_one()
    lines.append(
        _sample(
            "axelio_notification_jobs",
            float(failed_jobs_24h or 0),
            _labels(status="failed_recent_24h"),
        )
    )

    failed_payments = db.execute(
        select(func.count(VenueBillingTransaction.id)).where(
            VenueBillingTransaction.type == "PAYMENT",
            VenueBillingTransaction.status == "FAILED",
            VenueBillingTransaction.created_at >= since,
        )
    ).scalar_one()
    open_reconciliation = db.execute(
        select(func.count(BillingReconciliationIssue.id)).where(BillingReconciliationIssue.status == "OPEN")
    ).scalar_one()
    lines.extend(
        [
            "# HELP axelio_failed_payments_24h Failed payment transactions created during the last 24 hours.",
            "# TYPE axelio_failed_payments_24h gauge",
            _sample("axelio_failed_payments_24h", float(failed_payments or 0)),
            "# HELP axelio_open_reconciliation_issues Open billing reconciliation issues.",
            "# TYPE axelio_open_reconciliation_issues gauge",
            _sample("axelio_open_reconciliation_issues", float(open_reconciliation or 0)),
        ]
    )
    return lines


def render_prometheus(db: Session) -> str:
    with _LOCK:
        counters = sorted(_COUNTERS.items())
        durations = {
            labels: (tuple(histogram.bucket_counts), histogram.count, histogram.total)
            for labels, histogram in _DURATIONS.items()
        }

    lines = [
        "# HELP axelio_build_info Axelio release and environment information.",
        "# TYPE axelio_build_info gauge",
        _sample(
            "axelio_build_info",
            1.0,
            _labels(environment=settings.APP_ENV, release=settings.release_version()),
        ),
        "# HELP axelio_process_start_time_seconds Unix timestamp when this API process started.",
        "# TYPE axelio_process_start_time_seconds gauge",
        _sample("axelio_process_start_time_seconds", _STARTED_AT),
    ]

    emitted_types: set[str] = set()
    for (name, labels), value in counters:
        if name not in emitted_types:
            lines.extend([f"# HELP {name} Axelio application counter.", f"# TYPE {name} counter"])
            emitted_types.add(name)
        lines.append(_sample(name, value, labels))

    lines.extend(
        [
            "# HELP axelio_http_request_duration_seconds API request duration by route and status class.",
            "# TYPE axelio_http_request_duration_seconds histogram",
        ]
    )
    for labels, (bucket_counts, count, total) in sorted(durations.items()):
        for bucket, bucket_count in zip(_HISTOGRAM_BUCKETS, bucket_counts, strict=True):
            lines.append(
                _sample(
                    "axelio_http_request_duration_seconds_bucket",
                    float(bucket_count),
                    labels + (("le", str(bucket)),),
                )
            )
        lines.append(
            _sample(
                "axelio_http_request_duration_seconds_bucket",
                float(count),
                labels + (("le", "+Inf"),),
            )
        )
        lines.append(_sample("axelio_http_request_duration_seconds_sum", total, labels))
        lines.append(_sample("axelio_http_request_duration_seconds_count", float(count), labels))

    pool = engine.pool
    for metric_name, getter in (
        ("axelio_db_pool_checked_out", getattr(pool, "checkedout", None)),
        ("axelio_db_pool_size", getattr(pool, "size", None)),
        ("axelio_db_pool_overflow", getattr(pool, "overflow", None)),
    ):
        if callable(getter):
            lines.extend([f"# TYPE {metric_name} gauge", _sample(metric_name, float(getter()))])

    try:
        lines.extend(_database_gauges(db))
    except Exception:
        record_database_error("metrics_snapshot")
        raise

    for metric_name, state_file in (
        ("axelio_backup_last_success_timestamp_seconds", "backup-last-success.timestamp"),
        ("axelio_deployment_smoke_last_success_timestamp_seconds", "deploy-smoke-last-success.timestamp"),
    ):
        lines.extend([f"# TYPE {metric_name} gauge", _sample(metric_name, _state_timestamp(state_file))])

    return "\n".join(lines) + "\n"

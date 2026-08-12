from __future__ import annotations

import contextvars
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import sentry_sdk
from fastapi import Request
from sentry_sdk.integrations.fastapi import FastApiIntegration
from starlette.responses import Response

from app.core.config import settings


_REQUEST_ID = contextvars.ContextVar("axelio_request_id", default="-")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_STRUCTURED_FIELDS = (
    "method",
    "route",
    "path",
    "status_code",
    "duration_ms",
    "venue_id",
)
_SENSITIVE_HEADERS = {
    "authorization",
    "cookie",
    "proxy-authorization",
    "set-cookie",
    "x-api-key",
    "x-telegram-bot-api-secret-token",
}


def normalize_request_id(value: str | None) -> str:
    candidate = str(value or "").strip()
    if candidate and _SAFE_REQUEST_ID.fullmatch(candidate):
        return candidate
    return uuid.uuid4().hex


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _REQUEST_ID.get()
        record.environment = str(settings.APP_ENV or "development")
        record.release = settings.release_version()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "environment": getattr(record, "environment", str(settings.APP_ENV or "development")),
            "release": getattr(record, "release", settings.release_version()),
        }
        for field in _STRUCTURED_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def configure_logging() -> None:
    level_name = str(settings.LOG_LEVEL or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(logging.StreamHandler(sys.stdout))

    context_filter = RequestContextFilter()
    formatter: logging.Formatter
    if settings.LOG_JSON:
        formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s "
            "environment=%(environment)s release=%(release)s %(message)s"
        )
    for handler in root.handlers:
        handler.setLevel(level)
        handler.addFilter(context_filter)
        handler.setFormatter(formatter)

    logging.getLogger("uvicorn.access").disabled = True


def _scrub_sentry_event(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    del hint
    request = event.get("request")
    if isinstance(request, dict):
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                key: value for key, value in headers.items() if str(key).lower() not in _SENSITIVE_HEADERS
            }
        elif isinstance(headers, list):
            request["headers"] = [pair for pair in headers if pair and str(pair[0]).lower() not in _SENSITIVE_HEADERS]
        request.pop("cookies", None)
        request.pop("data", None)
    event.pop("user", None)
    return event


def init_error_tracking() -> bool:
    dsn = str(settings.SENTRY_DSN or "").strip()
    if not dsn:
        return False
    sample_rate = min(max(float(settings.SENTRY_TRACES_SAMPLE_RATE or 0.0), 0.0), 1.0)
    sentry_sdk.init(
        dsn=dsn,
        environment=str(settings.APP_ENV or "development"),
        release=f"axelio@{settings.release_version()}",
        integrations=[FastApiIntegration()],
        traces_sample_rate=sample_rate,
        send_default_pii=False,
        before_send=_scrub_sentry_event,
    )
    return True


def _request_route(request: Request) -> str:
    route = request.scope.get("route")
    return str(getattr(route, "path", None) or request.url.path)


def _venue_id(request: Request) -> int | None:
    raw = request.path_params.get("venue_id")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


async def observe_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    request_id = normalize_request_id(request.headers.get("X-Request-ID"))
    token = _REQUEST_ID.set(request_id)
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = int(response.status_code)
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception:
        logging.getLogger("axelio.request").exception(
            "request_failed",
            extra={
                "method": request.method,
                "route": _request_route(request),
                "path": request.url.path,
                "status_code": status_code,
                "venue_id": _venue_id(request),
            },
        )
        raise
    finally:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        logging.getLogger("axelio.request").info(
            "request_complete",
            extra={
                "method": request.method,
                "route": _request_route(request),
                "path": request.url.path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "venue_id": _venue_id(request),
            },
        )
        _REQUEST_ID.reset(token)

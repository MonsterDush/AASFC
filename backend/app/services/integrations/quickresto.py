from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import random
import re
import time
from typing import Any, Callable, Iterable

import requests


_CLOUD_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_FILTER_OPERATIONS = {"eq", "neq", "gte", "lte", "gt", "lt", "like", "contains", "range"}
_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}
_FILTER_FALLBACK_STATUS_CODES = {400, 404, 405, 422}
_MAX_ATTEMPTS = 4
_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)
_MAX_RETRY_AFTER_SECONDS = 60.0

QUICKRESTO_OBJECT_TYPES: dict[str, tuple[str, str]] = {
    "venues": (
        "front.tablemanagement",
        "ru.edgex.quickresto.modules.front.tablemanagement.TableScheme",
    ),
    "sale_places": (
        "warehouse.nomenclature.sale_place",
        "ru.edgex.quickresto.modules.warehouse.nomenclature.sale_place.SalePlace",
    ),
    "cooking_places": (
        "warehouse.nomenclature.cooking_place",
        "ru.edgex.quickresto.modules.warehouse.nomenclature.cooking_place.CookingPlace",
    ),
    "stores": (
        "warehouse.store",
        "ru.edgex.quickresto.modules.warehouse.store.Store",
    ),
    "payment_types": (
        "core.dictionaries.paymenttypes",
        "ru.edgex.quickresto.modules.core.dictionaries.paymenttypes.PaymentType",
    ),
    "dish_categories": (
        "warehouse.nomenclature.dish",
        "ru.edgex.quickresto.modules.warehouse.nomenclature.dish.DishCategory",
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


class QuickRestoError(RuntimeError):
    """Base error for safe QuickResto API failures."""


class QuickRestoAuthenticationError(QuickRestoError):
    """Raised when QuickResto rejects API credentials."""


class QuickRestoHTTPError(QuickRestoError):
    """Raised when QuickResto returns a non-success HTTP response."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


@dataclass(frozen=True)
class QuickRestoConfig:
    cloud: str
    login: str
    password: str
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        cloud = str(self.cloud or "").strip().lower()
        login = str(self.login or "").strip()
        password = str(self.password or "")
        if not _CLOUD_RE.fullmatch(cloud):
            raise ValueError("QuickResto cloud must be a plain subdomain, for example: uk353")
        if not login:
            raise ValueError("QuickResto API login is required")
        if not password:
            raise ValueError("QuickResto API password is required")
        if not 1 <= float(self.timeout_seconds) <= 120:
            raise ValueError("QuickResto timeout must be between 1 and 120 seconds")
        object.__setattr__(self, "cloud", cloud)
        object.__setattr__(self, "login", login)

    @property
    def base_url(self) -> str:
        return f"https://{self.cloud}.quickresto.ru/platform/online"


class QuickRestoClient:
    """Read-only client for the documented QuickResto Back Office API."""

    def __init__(
        self,
        config: QuickRestoConfig,
        *,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self.config = config
        self._session = session or requests.Session()
        self._sleep = sleep
        self._jitter = jitter
        self._session.auth = (config.login, config.password)
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Connection": "keep-alive",
                "User-Agent": "Axelio-QuickResto-Probe/1.0",
            }
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> QuickRestoClient:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def list_objects(
        self,
        *,
        module_name: str,
        class_name: str,
        limit: int = 500,
        offset: int = 0,
        filters: Iterable[dict[str, Any]] | None = None,
        sort_fields: Iterable[str] | None = None,
        sort_orders: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= int(limit) <= 1000:
            raise ValueError("QuickResto list limit must be between 1 and 1000")
        if int(offset) < 0:
            raise ValueError("QuickResto list offset must be non-negative")
        json_body: dict[str, Any] = {"limit": int(limit), "offset": int(offset)}
        normalized_filters = self._normalize_filters(filters)
        normalized_sort_fields, normalized_sort_orders = self._normalize_sort(sort_fields, sort_orders)
        if normalized_filters:
            # QuickResto OpenAPI 2.92 describes filters as query parameters,
            # while real clouds consume them from the GET JSON body alongside
            # limit/offset. Unknown query parameters are silently ignored.
            json_body["filters"] = normalized_filters
        if normalized_sort_fields:
            json_body["sortFields"] = normalized_sort_fields
            json_body["sortOrders"] = normalized_sort_orders
        data = self._get_json(
            "/api/list",
            params={"moduleName": module_name, "className": class_name},
            json_body=json_body,
        )
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise QuickRestoError("QuickResto list response has an unexpected shape")
        return data

    def read_object(self, *, module_name: str, class_name: str, object_id: int) -> dict[str, Any]:
        if int(object_id) <= 0:
            raise ValueError("QuickResto object_id must be positive")
        data = self._get_json(
            "/api/read",
            params={"moduleName": module_name, "className": class_name, "objectId": int(object_id)},
            json_body=None,
        )
        if not isinstance(data, dict):
            raise QuickRestoError("QuickResto read response has an unexpected shape")
        return data

    def list_all_objects(
        self,
        *,
        module_name: str,
        class_name: str,
        page_size: int = 500,
        max_pages: int = 100,
        filters: Iterable[dict[str, Any]] | None = None,
        sort_fields: Iterable[str] | None = None,
        sort_orders: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not 1 <= int(max_pages) <= 1000:
            raise ValueError("QuickResto max_pages must be between 1 and 1000")
        rows: list[dict[str, Any]] = []
        for page in range(int(max_pages)):
            batch = self.list_objects(
                module_name=module_name,
                class_name=class_name,
                limit=int(page_size),
                offset=page * int(page_size),
                filters=filters,
                sort_fields=sort_fields,
                sort_orders=sort_orders,
            )
            rows.extend(batch)
            if len(batch) < int(page_size):
                return rows
        raise QuickRestoError("QuickResto pagination exceeded the configured safety limit")

    def list_closed_shifts(
        self,
        *,
        closed_since: datetime | None = None,
        page_size: int = 500,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        """List closed shifts, falling back to a full scan if filters are unsupported or ignored."""

        normalized_since = self._normalize_datetime(closed_since) if closed_since is not None else None
        filters: list[dict[str, Any]] = [{"field": "status", "operation": "eq", "value": "CLOSED"}]
        if normalized_since is not None:
            filters.append(
                {
                    "field": "closed",
                    "operation": "gte",
                    "value": self._format_datetime(normalized_since),
                }
            )

        try:
            rows = self.list_all_objects(
                module_name=QUICKRESTO_OBJECT_TYPES["shifts"][0],
                class_name=QUICKRESTO_OBJECT_TYPES["shifts"][1],
                page_size=page_size,
                max_pages=max_pages,
                filters=filters,
                sort_fields=("closed", "id"),
                sort_orders=("asc", "asc"),
            )
            if all(self._closed_shift_matches(row, normalized_since, unknown_matches=False) for row in rows):
                return rows
        except QuickRestoHTTPError as exc:
            if exc.status_code not in _FILTER_FALLBACK_STATUS_CODES:
                raise

        rows = self.list_all_objects(
            module_name=QUICKRESTO_OBJECT_TYPES["shifts"][0],
            class_name=QUICKRESTO_OBJECT_TYPES["shifts"][1],
            page_size=page_size,
            max_pages=max_pages,
        )
        return [row for row in rows if self._closed_shift_matches(row, normalized_since, unknown_matches=True)]

    def list_orders_for_shift_ids(
        self,
        shift_ids: Iterable[str],
        *,
        page_size: int = 500,
        max_pages: int = 100,
    ) -> list[dict[str, Any]]:
        """List order summaries for selected shifts with a one-time full-scan fallback."""

        targets = sorted({str(value or "").strip() for value in shift_ids if str(value or "").strip()})
        if not targets:
            return []
        rows: list[dict[str, Any]] = []
        try:
            for shift_id in targets:
                batch = self.list_all_objects(
                    module_name=QUICKRESTO_OBJECT_TYPES["orders"][0],
                    class_name=QUICKRESTO_OBJECT_TYPES["orders"][1],
                    page_size=page_size,
                    max_pages=max_pages,
                    filters=({"field": "shiftId", "operation": "eq", "value": shift_id},),
                    sort_fields=("id",),
                    sort_orders=("asc",),
                )
                if any(str(row.get("shiftId") or "") != shift_id for row in batch):
                    raise _QuickRestoFilterIgnored
                rows.extend(batch)
            return self._deduplicate_rows(rows)
        except _QuickRestoFilterIgnored:
            pass
        except QuickRestoHTTPError as exc:
            if exc.status_code not in _FILTER_FALLBACK_STATUS_CODES:
                raise

        rows = self.list_all_objects(
            module_name=QUICKRESTO_OBJECT_TYPES["orders"][0],
            class_name=QUICKRESTO_OBJECT_TYPES["orders"][1],
            page_size=page_size,
            max_pages=max_pages,
        )
        target_set = set(targets)
        return self._deduplicate_rows([row for row in rows if str(row.get("shiftId") or "") in target_set])

    @staticmethod
    def _normalize_filters(filters: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
        rows = list(filters or ())
        if len(rows) > 20:
            raise ValueError("QuickResto accepts at most 20 list filters")
        output: list[dict[str, Any]] = []
        for item in rows:
            if not isinstance(item, dict):
                raise ValueError("QuickResto filters must be objects")
            field = str(item.get("field") or "").strip()
            operation = str(item.get("operation") or "").strip().lower()
            if not _FIELD_RE.fullmatch(field):
                raise ValueError("QuickResto filter field is invalid")
            if operation not in _FILTER_OPERATIONS:
                raise ValueError("QuickResto filter operation is invalid")
            if "value" not in item:
                raise ValueError("QuickResto filter value is required")
            output.append({"field": field, "operation": operation, "value": item["value"]})
        return output

    @staticmethod
    def _normalize_sort(
        sort_fields: Iterable[str] | None,
        sort_orders: Iterable[str] | None,
    ) -> tuple[list[str], list[str]]:
        fields = [str(value or "").strip() for value in (sort_fields or ())]
        orders = [str(value or "").strip().lower() for value in (sort_orders or ())]
        if not fields and not orders:
            return [], []
        if not fields or len(fields) != len(orders):
            raise ValueError("QuickResto sort fields and orders must have the same length")
        if len(fields) > 5 or any(not _FIELD_RE.fullmatch(value) for value in fields):
            raise ValueError("QuickResto sort fields are invalid")
        if any(value not in {"asc", "desc"} for value in orders):
            raise ValueError("QuickResto sort order must be asc or desc")
        return fields, orders

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _format_datetime(value: datetime) -> str:
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    @classmethod
    def _closed_shift_matches(
        cls,
        row: dict[str, Any],
        closed_since: datetime | None,
        *,
        unknown_matches: bool,
    ) -> bool:
        if str(row.get("status") or "").upper() != "CLOSED":
            return False
        if closed_since is None:
            return True
        raw_closed = str(row.get("closed") or row.get("localClosedTime") or "").strip()
        if not raw_closed:
            # During verification, an unknown timestamp proves neither that
            # the server honored the filter nor that the row belongs in the
            # incremental window. During the local fallback scan we retain it
            # so malformed source data becomes a durable import issue instead
            # of disappearing silently.
            return bool(unknown_matches)
        try:
            parsed = datetime.fromisoformat(raw_closed.replace("Z", "+00:00"))
        except ValueError:
            return bool(unknown_matches)
        return cls._normalize_datetime(parsed) >= closed_since

    @staticmethod
    def _deduplicate_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            key = (str(row.get("id") or ""), str(row.get("shiftId") or ""))
            if key in seen:
                continue
            seen.add(key)
            output.append(row)
        return output

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any],
        json_body: dict[str, Any] | None,
    ) -> Any:
        if path not in {"/api/list", "/api/read"}:
            raise ValueError("Unsupported QuickResto read-only path")
        response = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                response = self._session.get(
                    f"{self.config.base_url}{path}",
                    params=params,
                    json=json_body,
                    timeout=float(self.config.timeout_seconds),
                    allow_redirects=False,
                )
            except requests.RequestException as exc:
                if attempt + 1 >= _MAX_ATTEMPTS:
                    raise QuickRestoError("QuickResto request failed before receiving a response") from exc
                self._sleep(self._backoff_delay(attempt, retry_after=None))
                continue
            if response.status_code not in _RETRYABLE_STATUS_CODES or attempt + 1 >= _MAX_ATTEMPTS:
                break
            retry_after = self._retry_after_seconds(response)
            response.close()
            self._sleep(self._backoff_delay(attempt, retry_after=retry_after))
        if response is None:
            raise QuickRestoError("QuickResto request failed before receiving a response")
        if response.status_code == 401:
            raise QuickRestoAuthenticationError("QuickResto rejected the API login or password")
        if 300 <= response.status_code < 400:
            raise QuickRestoError("QuickResto returned an unexpected redirect")
        if response.status_code == 429:
            raise QuickRestoHTTPError("QuickResto rate limit was reached", status_code=429)
        if not 200 <= response.status_code < 300:
            raise QuickRestoHTTPError(
                f"QuickResto request failed with HTTP {response.status_code}",
                status_code=response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            raise QuickRestoError("QuickResto returned invalid JSON") from exc

    def _backoff_delay(self, attempt: int, *, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(max(0.0, retry_after), _MAX_RETRY_AFTER_SECONDS)
        base = _RETRY_BACKOFF_SECONDS[min(int(attempt), len(_RETRY_BACKOFF_SECONDS) - 1)]
        return base + max(0.0, float(self._jitter(0.0, base * 0.25)))

    @staticmethod
    def _retry_after_seconds(response: requests.Response) -> float | None:
        raw = str(response.headers.get("Retry-After") or "").strip()
        if not raw:
            return None
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass
        try:
            target = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)
        return max(0.0, (target - datetime.now(timezone.utc)).total_seconds())


class _QuickRestoFilterIgnored(RuntimeError):
    """Internal sentinel used to switch to an unfiltered full scan."""

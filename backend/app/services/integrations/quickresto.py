from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import requests


_CLOUD_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

QUICKRESTO_OBJECT_TYPES: dict[str, tuple[str, str]] = {
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

    def __init__(self, config: QuickRestoConfig, *, session: requests.Session | None = None) -> None:
        self.config = config
        self._session = session or requests.Session()
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
    ) -> list[dict[str, Any]]:
        if not 1 <= int(limit) <= 1000:
            raise ValueError("QuickResto list limit must be between 1 and 1000")
        if int(offset) < 0:
            raise ValueError("QuickResto list offset must be non-negative")
        data = self._get_json(
            "/api/list",
            params={"moduleName": module_name, "className": class_name},
            json_body={"limit": int(limit), "offset": int(offset)},
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
            )
            rows.extend(batch)
            if len(batch) < int(page_size):
                return rows
        raise QuickRestoError("QuickResto pagination exceeded the configured safety limit")

    def _get_json(
        self,
        path: str,
        *,
        params: dict[str, Any],
        json_body: dict[str, Any] | None,
    ) -> Any:
        if path not in {"/api/list", "/api/read"}:
            raise ValueError("Unsupported QuickResto read-only path")
        try:
            response = self._session.get(
                f"{self.config.base_url}{path}",
                params=params,
                json=json_body,
                timeout=float(self.config.timeout_seconds),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise QuickRestoError("QuickResto request failed before receiving a response") from exc
        if response.status_code == 401:
            raise QuickRestoAuthenticationError("QuickResto rejected the API login or password")
        if 300 <= response.status_code < 400:
            raise QuickRestoError("QuickResto returned an unexpected redirect")
        if response.status_code == 429:
            raise QuickRestoError("QuickResto rate limit was reached")
        if not 200 <= response.status_code < 300:
            raise QuickRestoError(f"QuickResto request failed with HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise QuickRestoError("QuickResto returned invalid JSON") from exc

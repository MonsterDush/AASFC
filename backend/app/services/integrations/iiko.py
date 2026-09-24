from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import time
from typing import Any
from urllib.parse import urlparse

import requests


_RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class IIKOError(RuntimeError):
    """Base error for iikoCloud responses safe to expose in diagnostics."""


class IIKOAuthenticationError(IIKOError):
    """Raised when iikoCloud rejects the API login or bearer token."""


class IIKOHTTPError(IIKOError):
    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


class IIKOResponseError(IIKOError):
    """Raised when iikoCloud returns a successful response with an invalid shape."""


@dataclass(frozen=True, slots=True)
class IIKOConfig:
    api_login: str | None = None
    api_key: str | None = None
    app_id: str | None = None
    client_secret: str | None = None
    base_url: str = "https://api-ru.iiko.services"
    timeout_seconds: float = 20.0

    def __post_init__(self) -> None:
        api_login = str(self.api_login or "").strip() or None
        api_key = str(self.api_key or "").strip() or None
        app_id = str(self.app_id or "").strip() or None
        client_secret = str(self.client_secret or "").strip() or None
        base_url = str(self.base_url or "").strip().rstrip("/")
        parsed = urlparse(base_url)
        v2_values = (api_key, app_id, client_secret)
        if any(v2_values) and not all(v2_values):
            raise ValueError("iiko v2 authorization requires api_key, app_id and client_secret")
        if not all(v2_values) and not api_login:
            raise ValueError("iiko authorization requires api_login or the complete v2 credential set")
        if parsed.scheme != "https" or not parsed.netloc or parsed.params or parsed.query or parsed.fragment:
            raise ValueError("iiko base_url must be an HTTPS origin")
        if not 1 <= float(self.timeout_seconds) <= 120:
            raise ValueError("iiko timeout must be between 1 and 120 seconds")
        object.__setattr__(self, "api_login", api_login)
        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "app_id", app_id)
        object.__setattr__(self, "client_secret", client_secret)
        object.__setattr__(self, "base_url", base_url)

    @property
    def auth_version(self) -> str:
        return "v2" if self.api_key and self.app_id and self.client_secret else "v1"

    @property
    def authorization_endpoint(self) -> str:
        return "/api/v2/access_token" if self.auth_version == "v2" else "/api/1/access_token"

    def authorization_payload(self) -> dict[str, str]:
        if self.auth_version == "v2":
            return {
                "apiKey": str(self.api_key),
                "appId": str(self.app_id),
                "clientSecret": str(self.client_secret),
            }
        return {"apiLogin": str(self.api_login)}


class IIKOClient:
    """Read-only iikoCloud client for Stage 4 discovery and master data."""

    def __init__(
        self,
        config: IIKOConfig,
        *,
        session: requests.Session | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._session = session or requests.Session()
        self._monotonic = monotonic
        self._token: str | None = None
        self._token_refresh_at = 0.0
        self._session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Axelio-iikoCloud/0.4",
            }
        )

    def __enter__(self) -> IIKOClient:
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def authenticate(self, *, force: bool = False) -> str:
        if not force and self._token and self._monotonic() < self._token_refresh_at:
            return self._token
        response = self._session.post(
            f"{self.config.base_url}{self.config.authorization_endpoint}",
            json=self.config.authorization_payload(),
            timeout=float(self.config.timeout_seconds),
        )
        if response.status_code in {401, 403}:
            raise IIKOAuthenticationError("iikoCloud rejected the authorization credentials")
        if not 200 <= response.status_code < 300:
            raise IIKOHTTPError(
                f"iikoCloud authorization failed with HTTP {int(response.status_code)}",
                status_code=int(response.status_code),
            )
        payload = self._response_mapping(response, operation="authorization")
        token = str(payload.get("token") or "").strip()
        if not token:
            raise IIKOResponseError("iikoCloud authorization response has no token")
        self._token = token
        # Official v1 and v2 tokens live for one hour. Refresh five minutes early.
        self._token_refresh_at = self._monotonic() + 55 * 60
        return token

    def organizations(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        payload = self._post(
            "/api/1/organizations",
            {"returnAdditionalInfo": True, "includeDisabled": bool(include_disabled)},
        )
        return self._mapping_list(payload, "organizations")

    def terminal_groups(
        self,
        organization_ids: Sequence[str],
        *,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        payload = self._post(
            "/api/1/terminal_groups",
            {
                "organizationIds": self._identifiers(organization_ids, field="organization_ids"),
                "includeDisabled": bool(include_disabled),
            },
        )
        rows = self._unwrap_organization_items(payload, "terminalGroups")
        for row in self._unwrap_organization_items(payload, "terminalGroupsInSleep"):
            row.setdefault("isInSleep", True)
            rows.append(row)
        return rows

    def terminal_groups_alive(
        self,
        organization_ids: Sequence[str],
        terminal_group_ids: Sequence[str],
    ) -> list[dict[str, Any]]:
        payload = self._post(
            "/api/1/terminal_groups/is_alive",
            {
                "organizationIds": self._identifiers(organization_ids, field="organization_ids"),
                "terminalGroupIds": self._identifiers(terminal_group_ids, field="terminal_group_ids"),
            },
        )
        return self._mapping_list(payload, "isAliveStatus")

    def nomenclature(self, organization_id: str, *, start_revision: int = 0) -> dict[str, Any]:
        normalized_organization_id = self._identifier(organization_id, field="organization_id")
        if int(start_revision) < 0:
            raise ValueError("iiko start_revision must be non-negative")
        payload = self._post(
            "/api/1/nomenclature",
            {"organizationId": normalized_organization_id, "startRevision": int(start_revision)},
        )
        for key in ("groups", "productCategories", "products", "sizes"):
            self._mapping_list(payload, key)
        try:
            revision = int(payload["revision"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IIKOResponseError("iikoCloud nomenclature response has no valid revision") from exc
        return {**payload, "revision": revision}

    def payment_types(self, organization_ids: Sequence[str]) -> list[dict[str, Any]]:
        payload = self._post(
            "/api/1/payment_types",
            {"organizationIds": self._identifiers(organization_ids, field="organization_ids")},
        )
        return self._mapping_list(payload, "paymentTypes")

    def order_types(self, organization_ids: Sequence[str]) -> list[dict[str, Any]]:
        return self._wrapped_dictionary("/api/1/deliveries/order_types", "orderTypes", organization_ids)

    def discounts(self, organization_ids: Sequence[str]) -> list[dict[str, Any]]:
        return self._wrapped_dictionary("/api/1/discounts", "discounts", organization_ids)

    def cancel_causes(self, organization_ids: Sequence[str]) -> list[dict[str, Any]]:
        payload = self._post(
            "/api/1/cancel_causes",
            {"organizationIds": self._identifiers(organization_ids, field="organization_ids")},
        )
        return self._mapping_list(payload, "cancelCauses")

    def removal_types(self, organization_ids: Sequence[str]) -> list[dict[str, Any]]:
        payload = self._post(
            "/api/1/removal_types",
            {"organizationIds": self._identifiers(organization_ids, field="organization_ids")},
        )
        return self._mapping_list(payload, "removalTypes")

    def tips_types(self) -> list[dict[str, Any]]:
        return self._mapping_list(self._post("/api/1/tips_types", {}), "tipsTypes")

    def marketing_sources(self, organization_ids: Sequence[str]) -> list[dict[str, Any]]:
        payload = self._post(
            "/api/1/marketing_sources",
            {"organizationIds": self._identifiers(organization_ids, field="organization_ids")},
        )
        return self._mapping_list(payload, "marketingSources")

    def stop_lists(
        self,
        organization_ids: Sequence[str],
        *,
        terminal_group_ids: Sequence[str] = (),
        return_size: bool = True,
    ) -> list[dict[str, Any]]:
        request: dict[str, Any] = {
            "organizationIds": self._identifiers(organization_ids, field="organization_ids"),
            "returnSize": bool(return_size),
        }
        if terminal_group_ids:
            request["terminalGroupsIds"] = self._identifiers(
                terminal_group_ids,
                field="terminal_group_ids",
            )
        payload = self._post("/api/1/stop_lists", request)
        rows: list[dict[str, Any]] = []
        for wrapper in self._mapping_list(payload, "terminalGroupStopLists"):
            organization_id = str(wrapper.get("organizationId") or "").strip()
            for stop_list in self._mapping_list(wrapper, "items"):
                terminal_group_id = str(stop_list.get("terminalGroupId") or "").strip()
                for item in self._mapping_list(stop_list, "items"):
                    rows.append(
                        {
                            **item,
                            "organizationId": organization_id,
                            "terminalGroupId": terminal_group_id,
                        }
                    )
        return rows

    def restaurant_sections(
        self,
        terminal_group_ids: Sequence[str],
        *,
        revision: int | None = None,
        return_schema: bool = False,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "terminalGroupIds": self._identifiers(terminal_group_ids, field="terminal_group_ids"),
            "returnSchema": bool(return_schema),
        }
        if revision is not None:
            if int(revision) < 0:
                raise ValueError("iiko restaurant section revision must be non-negative")
            request["revision"] = int(revision)
        payload = self._post("/api/1/reserve/available_restaurant_sections", request)
        self._mapping_list(payload, "restaurantSections")
        try:
            response_revision = int(payload["revision"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IIKOResponseError("iikoCloud restaurant section response has no valid revision") from exc
        return {**payload, "revision": response_revision}

    def _wrapped_dictionary(
        self,
        endpoint: str,
        response_key: str,
        organization_ids: Sequence[str],
    ) -> list[dict[str, Any]]:
        payload = self._post(
            endpoint,
            {"organizationIds": self._identifiers(organization_ids, field="organization_ids")},
        )
        return self._unwrap_organization_items(payload, response_key)

    def _post(self, endpoint: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        token = self.authenticate()
        response = self._session.post(
            f"{self.config.base_url}{endpoint}",
            json=dict(payload),
            headers={"Authorization": f"Bearer {token}"},
            timeout=float(self.config.timeout_seconds),
        )
        if response.status_code == 401:
            token = self.authenticate(force=True)
            response = self._session.post(
                f"{self.config.base_url}{endpoint}",
                json=dict(payload),
                headers={"Authorization": f"Bearer {token}"},
                timeout=float(self.config.timeout_seconds),
            )
        if response.status_code in {401, 403}:
            raise IIKOAuthenticationError("iikoCloud rejected the bearer token")
        if not 200 <= response.status_code < 300:
            message = f"iikoCloud request failed with HTTP {int(response.status_code)}"
            if response.status_code in _RETRYABLE_STATUS_CODES:
                message += " (retryable)"
            raise IIKOHTTPError(message, status_code=int(response.status_code))
        return self._response_mapping(response, operation=endpoint)

    @staticmethod
    def _response_mapping(response: requests.Response, *, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except (ValueError, TypeError) as exc:
            raise IIKOResponseError(f"iikoCloud {operation} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise IIKOResponseError(f"iikoCloud {operation} returned an unexpected shape")
        return payload

    @staticmethod
    def _mapping_list(payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
        values = payload.get(key)
        if not isinstance(values, list) or any(not isinstance(item, dict) for item in values):
            raise IIKOResponseError(f"iikoCloud response field {key} must be a list of objects")
        return [dict(item) for item in values]

    @classmethod
    def _unwrap_organization_items(cls, payload: Mapping[str, Any], key: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for wrapper in cls._mapping_list(payload, key):
            organization_id = str(wrapper.get("organizationId") or "").strip()
            for item in cls._mapping_list(wrapper, "items"):
                rows.append({**item, "organizationId": organization_id})
        return rows

    @classmethod
    def _identifiers(cls, values: Sequence[str], *, field: str) -> list[str]:
        normalized = [cls._identifier(value, field=field) for value in values]
        if not normalized:
            raise ValueError(f"iiko {field} cannot be empty")
        return normalized

    @staticmethod
    def _identifier(value: str, *, field: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError(f"iiko {field} contains an empty identifier")
        return normalized

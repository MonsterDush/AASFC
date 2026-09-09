from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping
from urllib.parse import urlparse

import requests


class IikoError(RuntimeError):
    pass


class IikoAuthenticationError(IikoError):
    pass


@dataclass(frozen=True)
class IikoConfig:
    api_login: str
    base_url: str = "https://api-ru.iiko.services"
    timeout_seconds: float = 20.0
    sales_endpoint: str | None = None
    employees_endpoint: str | None = None
    extended_endpoints: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        login = str(self.api_login or "").strip()
        parsed = urlparse(str(self.base_url or ""))
        if not login:
            raise ValueError("iiko apiLogin is required")
        if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".iiko.services"):
            raise ValueError("iiko base_url must use an iiko.services HTTPS host")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("iiko base_url must not contain credentials, query, or fragment")
        if not 1 <= float(self.timeout_seconds) <= 120:
            raise ValueError("iiko timeout must be between 1 and 120 seconds")
        for field_name in ("sales_endpoint", "employees_endpoint"):
            value = getattr(self, field_name)
            if value is None:
                continue
            endpoint = str(value).strip()
            parsed_endpoint = urlparse(endpoint)
            if (
                not endpoint.startswith("/api/1/")
                or parsed_endpoint.scheme
                or parsed_endpoint.netloc
                or parsed_endpoint.query
                or parsed_endpoint.fragment
                or ".." in parsed_endpoint.path.split("/")
            ):
                raise ValueError("iiko optional endpoints must be relative /api/1 paths")
            object.__setattr__(self, field_name, endpoint)
        validated_endpoints: dict[str, str] = {}
        for raw_capability, raw_endpoint in dict(self.extended_endpoints or {}).items():
            capability = str(raw_capability or "").strip().upper()
            endpoint = str(raw_endpoint or "").strip()
            parsed_endpoint = urlparse(endpoint)
            if (
                not capability
                or not endpoint.startswith("/api/1/")
                or parsed_endpoint.scheme
                or parsed_endpoint.netloc
                or parsed_endpoint.query
                or parsed_endpoint.fragment
                or ".." in parsed_endpoint.path.split("/")
            ):
                raise ValueError("iiko extended endpoints must map capability names to relative /api/1 paths")
            validated_endpoints[capability] = endpoint
        object.__setattr__(self, "extended_endpoints", MappingProxyType(validated_endpoints))
        object.__setattr__(self, "api_login", login)
        object.__setattr__(self, "base_url", str(self.base_url).rstrip("/"))


class IikoClient:
    def __init__(self, config: IikoConfig, *, session: requests.Session | None = None) -> None:
        self.config = config
        self._session = session or requests.Session()
        self._session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
        self._token: str | None = None

    def close(self) -> None:
        self._session.close()

    def authenticate(self) -> str:
        if self._token:
            return self._token
        data = self._post("/api/1/access_token", {"apiLogin": self.config.api_login}, authenticated=False)
        token = str(data.get("token") or "") if isinstance(data, dict) else ""
        if not token:
            raise IikoAuthenticationError("iiko access token response has no token")
        self._token = token
        return token

    def organizations(self) -> dict[str, Any]:
        return self._post(
            "/api/1/organizations",
            {"organizationIds": [], "returnAdditionalInfo": True, "includeDisabled": True},
        )

    def terminal_groups(self, organization_ids: list[str]) -> dict[str, Any]:
        return self._post("/api/1/terminal_groups", {"organizationIds": organization_ids, "includeDisabled": True})

    def nomenclature(self, organization_id: str) -> dict[str, Any]:
        return self._post("/api/1/nomenclature", {"organizationId": organization_id, "startRevision": 0})

    def sales(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self.config.sales_endpoint:
            raise IikoError("iiko sales endpoint is not configured for this connection")
        return self._post(self.config.sales_endpoint, body)

    def employees(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self.config.employees_endpoint:
            raise IikoError("iiko employees endpoint is not configured for this connection")
        return self._post(self.config.employees_endpoint, body)

    def extended_export(self, capability: str, body: dict[str, Any]) -> dict[str, Any]:
        endpoint = self.config.extended_endpoints.get(str(capability or "").strip().upper())
        if not endpoint:
            raise IikoError(f"iiko {capability} endpoint is not configured for this connection")
        return self._post(endpoint, body)

    def _post(self, path: str, body: dict[str, Any], *, authenticated: bool = True) -> dict[str, Any]:
        if authenticated and not self._token:
            self.authenticate()
        headers = {"Authorization": f"Bearer {self._token}"} if authenticated else {}
        try:
            response = self._session.post(
                f"{self.config.base_url}{path}",
                json=body,
                headers=headers,
                timeout=float(self.config.timeout_seconds),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise IikoError("iiko request failed") from exc
        if response.status_code in {401, 403}:
            raise IikoAuthenticationError("iiko rejected the credentials")
        if not 200 <= response.status_code < 300:
            raise IikoError(f"iiko HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError as exc:
            raise IikoError("iiko returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise IikoError("iiko response has an unexpected shape")
        return data

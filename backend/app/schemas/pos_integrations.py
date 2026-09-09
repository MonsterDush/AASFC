from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator


class IikoConnectionUpsertIn(BaseModel):
    api_login: str | None = Field(default=None, min_length=1, max_length=500)
    organization_id: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str = Field(default="https://api-ru.iiko.services", max_length=500)
    sales_endpoint: str | None = Field(default=None, max_length=500)
    employees_endpoint: str | None = Field(default=None, max_length=500)
    extended_endpoints: dict[str, str] | None = None
    is_active: bool = True

    @field_validator("organization_id", "sales_endpoint", "employees_endpoint")
    @classmethod
    def trim_optional_text(cls, value: str | None) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @field_validator("extended_endpoints")
    @classmethod
    def validate_extended_endpoints(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        if value is None:
            return None
        allowed = {
            "RECIPES",
            "WAREHOUSES",
            "STOCK_BALANCES",
            "STOCK_MOVEMENTS",
            "SUPPLIERS",
            "PURCHASES",
            "WRITEOFFS",
            "INVENTORY",
            "EMPLOYEE_ATTENDANCE",
        }
        normalized = {str(key).strip().upper(): str(endpoint).strip() for key, endpoint in value.items()}
        unknown = sorted(set(normalized) - allowed)
        if unknown:
            raise ValueError(f"Unsupported iiko endpoint capabilities: {', '.join(unknown)}")
        if any(not endpoint for endpoint in normalized.values()):
            raise ValueError("iiko extended endpoints must not be empty")
        return normalized


class POSHistoricalSyncIn(BaseModel):
    months: int = Field(default=12, ge=1, le=24)


class QuickRestoCanonicalConfigIn(BaseModel):
    object_types: dict[str, dict[str, str]] = Field(default_factory=dict)

    @field_validator("object_types")
    @classmethod
    def validate_object_types(cls, value: dict[str, dict[str, str]]) -> dict[str, dict[str, str]]:
        allowed = {
            "RECIPES",
            "WAREHOUSES",
            "STOCK_BALANCES",
            "STOCK_MOVEMENTS",
            "SUPPLIERS",
            "PURCHASES",
            "WRITEOFFS",
            "INVENTORY",
            "EMPLOYEE_ATTENDANCE",
        }
        output: dict[str, dict[str, str]] = {}
        for raw_capability, raw_spec in value.items():
            capability = str(raw_capability or "").strip().upper()
            if capability not in allowed:
                raise ValueError(f"Unsupported QuickResto capability: {capability}")
            module_name = str((raw_spec or {}).get("module_name") or "").strip()
            class_name = str((raw_spec or {}).get("class_name") or "").strip()
            if not module_name or not class_name or len(module_name) > 255 or len(class_name) > 500:
                raise ValueError("Each QuickResto object type requires module_name and class_name")
            output[capability] = {"module_name": module_name, "class_name": class_name}
        return output


class POSEmployeeMappingConfirmIn(BaseModel):
    venue_member_id: int = Field(gt=0)


class POSReconciliationIn(BaseModel):
    period_start: date
    period_end: date
    source_revenue: Decimal
    source_refunds: Decimal = Decimal("0")
    source_counts: dict[str, int] = Field(default_factory=dict)
    coverage_start: date | None = None
    coverage_end: date | None = None
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("source_counts")
    @classmethod
    def validate_counts(cls, value: dict[str, int]) -> dict[str, int]:
        normalized = {str(key).strip(): int(count) for key, count in value.items() if str(key).strip()}
        if any(count < 0 for count in normalized.values()):
            raise ValueError("Reconciliation counts must be non-negative")
        return normalized

    @field_validator("period_end")
    @classmethod
    def validate_period(cls, value: date, info):
        start = info.data.get("period_start")
        if start is not None and value < start:
            raise ValueError("period_end must not be before period_start")
        return value


class POSQuarantineStatusIn(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        normalized = str(value or "").strip().upper()
        if normalized not in {"OPEN", "IGNORED"}:
            raise ValueError("Quarantine status must be OPEN or IGNORED")
        return normalized

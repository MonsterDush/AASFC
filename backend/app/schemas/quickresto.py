from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class QuickRestoConnectionUpsertIn(BaseModel):
    cloud: str = Field(..., min_length=1, max_length=63)
    api_login: str | None = Field(default=None, min_length=1, max_length=255)
    api_password: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool = True
    auto_sync_enabled: bool = False
    report_import_mode: Literal["DRAFT", "CLOSED"] | None = None
    business_day_cutoff_hour: int = Field(default=0, ge=0, le=23)
    night_shift_split_enabled: bool = False
    night_shift_start_hour: int = Field(default=22, ge=0, le=23)
    sync_from_date: date | None = None


class QuickRestoPaymentMappingIn(BaseModel):
    external_id: int = Field(..., gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    excluded_from_revenue: bool = False


class QuickRestoDepartmentAllocationIn(BaseModel):
    department_id: int = Field(..., gt=0)
    share_percent: int = Field(..., ge=1, le=100)


class QuickRestoDepartmentMappingIn(BaseModel):
    external_id: int = Field(..., gt=0)
    department_id: int | None = Field(default=None, gt=0)
    allocations: list[QuickRestoDepartmentAllocationIn] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_department_target(self):
        if self.department_id is not None and self.allocations:
            raise ValueError("Choose either one department or a percentage allocation")
        target_ids = [int(item.department_id) for item in self.allocations]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("QuickResto department allocation targets must be unique")
        if self.allocations and sum(int(item.share_percent) for item in self.allocations) != 100:
            raise ValueError("QuickResto department allocation must total 100 percent")
        return self


class QuickRestoKpiProductMappingIn(BaseModel):
    external_product_id: int = Field(..., gt=0)
    kpi_metric_id: int | None = Field(default=None, gt=0)
    exclude_from_percentage_base: bool = True


class QuickRestoKpiMappingsUpdateIn(BaseModel):
    products: list[QuickRestoKpiProductMappingIn] = Field(default_factory=list, max_length=10000)

    @field_validator("products")
    @classmethod
    def validate_unique_products(
        cls,
        value: list[QuickRestoKpiProductMappingIn],
    ) -> list[QuickRestoKpiProductMappingIn]:
        external_ids = [int(item.external_product_id) for item in value]
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("QuickResto KPI product mappings must be unique")
        return value


class QuickRestoMappingsUpdateIn(BaseModel):
    payments: list[QuickRestoPaymentMappingIn] = Field(default_factory=list)
    departments: list[QuickRestoDepartmentMappingIn] = Field(default_factory=list)
    kpi_products: list[QuickRestoKpiProductMappingIn] = Field(
        default_factory=list,
        max_length=10000,
    )

    @field_validator("kpi_products")
    @classmethod
    def validate_unique_kpi_products(
        cls,
        value: list[QuickRestoKpiProductMappingIn],
    ) -> list[QuickRestoKpiProductMappingIn]:
        external_ids = [int(item.external_product_id) for item in value]
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("QuickResto KPI product mappings must be unique")
        return value


class QuickRestoScopeUpdateIn(BaseModel):
    external_venue_id: int = Field(..., gt=0)
    sale_place_ids: list[int] = Field(..., min_length=1, max_length=500)
    store_ids: list[int] = Field(default_factory=list, max_length=500)

    @field_validator("sale_place_ids", "store_ids")
    @classmethod
    def validate_scope_ids(cls, value: list[int]) -> list[int]:
        normalized = sorted({int(item) for item in value})
        if any(item <= 0 for item in normalized):
            raise ValueError("QuickResto scope identifiers must be positive")
        return normalized


class QuickRestoIssueResolveIn(BaseModel):
    action: Literal["IGNORE"]
    note: str = Field(..., min_length=3, max_length=1000)

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if len(normalized) < 3:
            raise ValueError("QuickResto issue resolution note must contain at least 3 characters")
        return normalized


class QuickRestoHistoricalShiftDecisionIn(BaseModel):
    shift_import_id: int = Field(..., gt=0)
    action: Literal["KEEP_CURRENT", "EXCLUDE_CURRENT", "MOVE_TO_CONNECTED"]


class QuickRestoHistoricalScopePreviewIn(BaseModel):
    decisions: list[QuickRestoHistoricalShiftDecisionIn] = Field(..., min_length=1, max_length=5000)
    note: str = Field(..., min_length=3, max_length=1000)

    @field_validator("decisions")
    @classmethod
    def validate_unique_shift_decisions(
        cls,
        value: list[QuickRestoHistoricalShiftDecisionIn],
    ) -> list[QuickRestoHistoricalShiftDecisionIn]:
        identifiers = [int(item.shift_import_id) for item in value]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("QuickResto historical shift decisions must be unique")
        return value

    @field_validator("note")
    @classmethod
    def validate_resolution_note(cls, value: str) -> str:
        normalized = str(value or "").strip()
        if len(normalized) < 3:
            raise ValueError("QuickResto scope resolution note must contain at least 3 characters")
        return normalized


class QuickRestoHistoricalScopeConfirmIn(QuickRestoHistoricalScopePreviewIn):
    preview_token: str = Field(..., min_length=40, max_length=8192)


class QuickRestoHistoricalScopeResolveIn(QuickRestoHistoricalScopePreviewIn):
    """Backward-compatible request shape for callers that only need decision validation."""

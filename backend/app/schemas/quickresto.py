from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator


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


class QuickRestoDepartmentMappingIn(BaseModel):
    external_id: int = Field(..., gt=0)
    department_id: int | None = Field(default=None, gt=0)


class QuickRestoMappingsUpdateIn(BaseModel):
    payments: list[QuickRestoPaymentMappingIn] = Field(default_factory=list)
    departments: list[QuickRestoDepartmentMappingIn] = Field(default_factory=list)


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
    action: Literal["KEEP_CURRENT", "EXCLUDE_CURRENT"]


class QuickRestoHistoricalScopeResolveIn(BaseModel):
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

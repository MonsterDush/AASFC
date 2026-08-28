from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


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

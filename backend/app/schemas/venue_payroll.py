from __future__ import annotations

from datetime import date
from pydantic import BaseModel, Field


class PositionCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    member_user_id: int = Field(..., gt=0)
    rate: int = Field(0, ge=0)
    percent: int = Field(0, ge=0, le=100)
    pay_profile_id: int | None = Field(default=None, gt=0)
    is_active: bool = True
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None


class PositionUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    member_user_id: int | None = Field(default=None, gt=0)
    rate: int | None = Field(default=None, ge=0)
    percent: int | None = Field(default=None, ge=0, le=100)
    pay_profile_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None


class PositionPresetOut(BaseModel):
    id: str
    title: str
    rate: int = 0
    percent: int = 0
    pay_profile_id: int | None = None
    pay_profile_title: str | None = None
    template_id: str | None = None
    template_title: str | None = None
    permission_codes: list[str] = []
    is_active: bool = True


class PositionPresetsOut(BaseModel):
    items: list[PositionPresetOut] = []


class PayProfileCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool = True


class PayProfileUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class PayProfileAssignmentCreateIn(BaseModel):
    member_user_id: int = Field(..., gt=0)
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool = True


class PayProfileAssignmentUpdateIn(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool | None = None


class PayComponentCreateIn(BaseModel):
    component_type: str = Field(..., min_length=1, max_length=40)
    title: str = Field(..., min_length=1, max_length=120)
    amount_minor: int | None = Field(default=None, ge=0)
    rate_minor: int | None = Field(default=None, ge=0)
    percent_bps: int | None = Field(default=None, ge=0)
    department_id: int | None = Field(default=None, gt=0)
    department_ids: list[int] | None = None
    kpi_metric_id: int | None = Field(default=None, gt=0)
    threshold_value: int | None = Field(default=None, ge=0)
    steps_json: dict | list | None = None
    kpi_calculation_mode: str = Field(default="FIXED", min_length=1, max_length=16)
    salary_accrual_day: int | None = Field(default=None, ge=1, le=31)
    base_scope: str | None = Field(default=None, min_length=1, max_length=24)
    boost_enabled: bool = False
    boost_percent_bps: int | None = Field(default=None, ge=0)
    boost_source_type: str | None = Field(default=None, min_length=1, max_length=40)
    boost_recalc_mode: str | None = Field(default=None, min_length=1, max_length=24)
    boost_department_id: int | None = Field(default=None, gt=0)
    boost_department_ids: list[int] | None = None
    boost_kpi_metric_id: int | None = Field(default=None, gt=0)
    boost_threshold_value: int | None = Field(default=None, ge=0)
    minimum_guarantee_minor: int | None = Field(default=None, ge=0)
    minimum_guarantee_scope: str | None = Field(default=None, min_length=1, max_length=16)
    maximum_cap_minor: int | None = Field(default=None, ge=0)
    sort_order: int = Field(0, ge=0)
    is_active: bool = True


class PayComponentUpdateIn(BaseModel):
    component_type: str | None = Field(default=None, min_length=1, max_length=40)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    amount_minor: int | None = Field(default=None, ge=0)
    rate_minor: int | None = Field(default=None, ge=0)
    percent_bps: int | None = Field(default=None, ge=0)
    department_id: int | None = Field(default=None, gt=0)
    department_ids: list[int] | None = None
    kpi_metric_id: int | None = Field(default=None, gt=0)
    threshold_value: int | None = Field(default=None, ge=0)
    steps_json: dict | list | None = None
    kpi_calculation_mode: str | None = Field(default=None, min_length=1, max_length=16)
    salary_accrual_day: int | None = Field(default=None, ge=1, le=31)
    base_scope: str | None = Field(default=None, min_length=1, max_length=24)
    boost_enabled: bool | None = None
    boost_percent_bps: int | None = Field(default=None, ge=0)
    boost_source_type: str | None = Field(default=None, min_length=1, max_length=40)
    boost_recalc_mode: str | None = Field(default=None, min_length=1, max_length=24)
    boost_department_id: int | None = Field(default=None, gt=0)
    boost_department_ids: list[int] | None = None
    boost_kpi_metric_id: int | None = Field(default=None, gt=0)
    boost_threshold_value: int | None = Field(default=None, ge=0)
    minimum_guarantee_minor: int | None = Field(default=None, ge=0)
    minimum_guarantee_scope: str | None = Field(default=None, min_length=1, max_length=16)
    maximum_cap_minor: int | None = Field(default=None, ge=0)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class PayrollCalculateIn(BaseModel):
    month: str = Field(..., min_length=7, max_length=7, description="YYYY-MM")


class PayrollPaymentMonthlyRuleIn(BaseModel):
    payment_day: int = Field(..., ge=1, le=31)
    period_start_day: int = Field(..., ge=1, le=31)
    period_end_day: int = Field(..., ge=1, le=31)
    period_month_offset: int = Field(0, ge=-1, le=0)


class PayrollPaymentSettingsIn(BaseModel):
    payment_method_id: int = Field(..., gt=0)
    cadence: str = Field("MONTHLY", pattern="^(DAILY|WEEKLY|MONTHLY)$")
    weekly_payment_weekday: int | None = Field(default=None, ge=0, le=6)
    monthly_rules: list[PayrollPaymentMonthlyRuleIn] = Field(default_factory=list, max_length=31)
    is_active: bool = True


class PayrollPaymentDraftGenerateIn(BaseModel):
    month: str = Field(..., min_length=7, max_length=7, description="Месяц дат выплаты, YYYY-MM")

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.finance import DailyFinanceSummaryOut, MonthlyFinanceBreakdownRowOut


class DepartmentPlanItemIn(BaseModel):
    department_id: int = Field(..., gt=0)
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class DepartmentPlanBulkIn(BaseModel):
    items: list[DepartmentPlanItemIn] = Field(default_factory=list)


class DepartmentPlanItemOut(BaseModel):
    department_id: int
    department_title: str
    department_code: str | None = None
    month: str | None = None
    date: str | None = None
    revenue_plan_minor: int | None = None
    notes: str | None = None
    actual_current_minor: int = 0
    actual_previous_minor: int | None = None
    usage_component_count: int = 0
    usage_profile_count: int = 0


class DepartmentPlanMonthOut(BaseModel):
    financial_values_hidden: bool = False
    can_view_financial_values: bool = True
    financial_values_hidden_reason: str | None = None
    month: str
    items: list[DepartmentPlanItemOut] = Field(default_factory=list)
    department_count: int = 0
    saved_count: int | None = None
    deleted_count: int | None = None


class DepartmentPlanDayOut(BaseModel):
    financial_values_hidden: bool = False
    can_view_financial_values: bool = True
    financial_values_hidden_reason: str | None = None
    date: str
    items: list[DepartmentPlanItemOut] = Field(default_factory=list)
    department_count: int = 0
    saved_count: int | None = None
    deleted_count: int | None = None


class DepartmentPlanCopyOut(BaseModel):
    copied: int = 0
    skipped: int = 0
    copied_from_date: str | None = None
    plan: DepartmentPlanDayOut


class DepartmentPlanAutofillOut(BaseModel):
    copied: int = 0
    skipped: int = 0
    copied_from_month: str | None = None
    distributed_total_minor: int | None = None
    mode: str | None = None
    lookback_weeks: int | None = None
    used_source_dates: list[str] = Field(default_factory=list)
    used_points: int | None = None
    plan: dict


class DayEconomicsReportOut(BaseModel):
    exists: bool
    report_id: int | None = None
    status: str
    closed_at: datetime | None = None
    closed_by_user_id: int | None = None
    comment: str | None = None
    revenue_total_minor: int = 0
    tips_total_minor: int = 0


class DayEconomicsTeamOut(BaseModel):
    total_shift_count: int = 0
    assignment_count: int = 0
    assigned_user_count: int = 0
    assigned_shift_count: int = 0
    unassigned_shift_count: int = 0


class DayEconomicsMetricsOut(BaseModel):
    result_status: str
    revenue_per_assigned_minor: int | None = None
    tips_per_assigned_minor: int | None = None
    profit_per_assigned_minor: int | None = None
    revenue_per_shift_minor: int | None = None
    profit_per_shift_minor: int | None = None
    assignments_per_shift: float | None = None
    assigned_shift_coverage_bps: int | None = None
    expense_ratio_bps: int | None = None
    point_expense_ratio_bps: int | None = None
    recurring_expense_ratio_bps: int | None = None
    payroll_ratio_bps: int | None = None
    top_department_title: str | None = None
    top_department_share_bps: int | None = None
    kpi_metric_count: int = 0
    nonzero_kpi_metric_count: int = 0
    kpi_total_value_numeric: int = 0


class DepartmentShareRowOut(MonthlyFinanceBreakdownRowOut):
    share_bps: int | None = None


class KpiFactRowOut(BaseModel):
    metric_id: int
    title: str
    code: str | None = None
    unit: str
    value_numeric: int


class KpiSummaryOut(BaseModel):
    metric_count: int = 0
    nonzero_metric_count: int = 0
    total_value_numeric: int = 0


class DayEconomicsPlanOut(BaseModel):
    date: date
    source: str = "NONE"
    template_weekday: int | None = None
    template_weekday_title: str | None = None
    template_month: str | None = None
    template_month_title: str | None = None
    revenue_plan_minor: int | None = None
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    assigned_user_target: int | None = None
    day_kind: str | None = None
    day_kind_title: str | None = None
    title: str | None = None
    notes: str | None = None
    usage_component_count: int = 0
    usage_profile_count: int = 0


class DayEconomicsPlanIn(BaseModel):
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = Field(default=None, ge=0)
    assigned_user_target: int | None = Field(default=None, ge=0)
    day_kind: str | None = Field(default=None, min_length=0, max_length=16)
    title: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=1000)


class DayEconomicsPlanTemplateOut(BaseModel):
    weekday: int
    weekday_title: str
    date: date
    source: str = "WEEKDAY_TEMPLATE"
    template_weekday: int | None = None
    template_weekday_title: str | None = None
    revenue_plan_minor: int | None = None
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    assigned_user_target: int | None = None
    notes: str | None = None


class DayEconomicsPlanTemplateIn(BaseModel):
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = Field(default=None, ge=0)
    assigned_user_target: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class DayEconomicsMonthPlanOut(BaseModel):
    month: str
    source: str = "MONTH_TEMPLATE"
    template_month: str | None = None
    template_month_title: str | None = None
    revenue_plan_minor: int | None = None
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    assigned_user_target: int | None = None
    notes: str | None = None
    usage_component_count: int = 0
    usage_profile_count: int = 0


class DayEconomicsMonthPlanIn(BaseModel):
    revenue_plan_minor: int | None = Field(default=None, ge=0)
    profit_plan_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = Field(default=None, ge=0)
    assigned_user_target: int | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class DayEconomicsMonthPlanCopyOut(BaseModel):
    copied: bool
    copied_from_month: str
    plan: DayEconomicsMonthPlanOut


class DayEconomicsTemplateCopyIn(BaseModel):
    source_weekday: int = Field(..., ge=0, le=6)
    target_weekdays: list[int] = Field(default_factory=list)
    overwrite: bool = True


class DayEconomicsTemplateCopyOut(BaseModel):
    source_weekday: int
    source_weekday_title: str
    copied_count: int
    copied: list[DayEconomicsPlanTemplateOut]
    skipped_count: int
    skipped: list[dict]


class VenueEconomicsRulesOut(BaseModel):
    max_expense_ratio_bps: int | None = None
    max_payroll_ratio_bps: int | None = None
    min_revenue_per_assigned_minor: int | None = None
    min_assigned_shift_coverage_bps: int | None = None
    min_profit_minor: int | None = None
    warn_on_draft_expenses: bool = True


class VenueEconomicsRulesIn(BaseModel):
    max_expense_ratio_bps: int | None = Field(default=None, ge=0)
    max_payroll_ratio_bps: int | None = Field(default=None, ge=0)
    min_revenue_per_assigned_minor: int | None = Field(default=None, ge=0)
    min_assigned_shift_coverage_bps: int | None = Field(default=None, ge=0, le=10000)
    min_profit_minor: int | None = None
    warn_on_draft_expenses: bool = True


class DayEconomicsPlanFactOut(BaseModel):
    revenue_fact_minor: int
    revenue_plan_minor: int | None = None
    revenue_delta_minor: int | None = None
    revenue_progress_bps: int | None = None
    profit_fact_minor: int
    profit_plan_minor: int | None = None
    profit_delta_minor: int | None = None
    revenue_per_assigned_fact_minor: int | None = None
    revenue_per_assigned_plan_minor: int | None = None
    revenue_per_assigned_delta_minor: int | None = None
    assigned_user_fact: int = 0
    assigned_user_target: int | None = None
    assigned_user_delta: int | None = None


class DayEconomicsAlertOut(BaseModel):
    severity: str
    code: str
    title: str
    detail: str


class DayEconomicsRollupDayOut(BaseModel):
    date: date
    profit_minor: int
    revenue_minor: int


class DayEconomicsRollupOut(BaseModel):
    month: str
    days_in_period: int
    evaluated_day_count: int
    closed_day_count: int
    profit_total_minor: int
    avg_profit_minor: int | None = None
    avg_revenue_per_assigned_minor: int | None = None
    profitable_day_count: int = 0
    loss_day_count: int = 0
    best_day: DayEconomicsRollupDayOut | None = None
    worst_day: DayEconomicsRollupDayOut | None = None


class DayEconomicsOut(BaseModel):
    financial_values_hidden: bool = False
    can_view_financial_values: bool = True
    financial_values_hidden_reason: str | None = None
    date: date
    report: DayEconomicsReportOut
    team: DayEconomicsTeamOut
    metrics: DayEconomicsMetricsOut
    summary: DailyFinanceSummaryOut
    payment_revenue_breakdown: list[MonthlyFinanceBreakdownRowOut]
    department_revenue_breakdown: list[MonthlyFinanceBreakdownRowOut]
    department_share_breakdown: list[DepartmentShareRowOut]
    kpi_breakdown: list[KpiFactRowOut]
    kpi_summary: KpiSummaryOut
    plan: DayEconomicsPlanOut
    rules: VenueEconomicsRulesOut
    plan_fact: DayEconomicsPlanFactOut
    alerts: list[DayEconomicsAlertOut]
    rollup: DayEconomicsRollupOut

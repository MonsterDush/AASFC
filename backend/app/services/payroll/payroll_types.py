from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.models import PayrollLine, PayrollRun


PAY_COMPONENT_TYPES = {
    "SALARY_FIXED_MONTH",
    "SALARY_HOURLY",
    "SALARY_PER_SHIFT",
    "PERCENT_TOTAL_REVENUE",
    "PERCENT_DEPARTMENT_REVENUE",
    "KPI_BONUS",
    "MINIMUM_PAYOUT",
}

BASE_SCOPE_FULL_PERIOD = "FULL_PERIOD"
BASE_SCOPE_WORKED_DATES = "WORKED_DATES"

BOOST_SOURCE_NONE = "NONE"
BOOST_SOURCE_VENUE_MONTH_PLAN = "VENUE_MONTH_PLAN"
BOOST_SOURCE_VENUE_DAY_PLAN = "VENUE_DAY_PLAN"
BOOST_SOURCE_DEPARTMENT_MONTH_PLAN = "DEPARTMENT_MONTH_PLAN"
BOOST_SOURCE_DEPARTMENT_DAY_PLAN = "DEPARTMENT_DAY_PLAN"
BOOST_SOURCE_KPI_METRIC = "KPI_METRIC"

BOOST_RECALC_REPLACE_ALL = "REPLACE_ALL"
BOOST_RECALC_EXCESS_ONLY = "EXCESS_ONLY"

MINIMUM_GUARANTEE_MONTH = "MONTH"
MINIMUM_GUARANTEE_DAY = "DAY"
MINIMUM_GUARANTEE_SHIFT = "SHIFT"

KPI_CALCULATION_FIXED = "FIXED"
KPI_CALCULATION_PERCENT = "PERCENT"

BASE_SCOPE_TITLES = {
    BASE_SCOPE_FULL_PERIOD: "по всему периоду",
    BASE_SCOPE_WORKED_DATES: "по отработанным дням",
}
BOOST_SOURCE_TITLES = {
    BOOST_SOURCE_NONE: "без условия",
    BOOST_SOURCE_VENUE_MONTH_PLAN: "месячный план заведения",
    BOOST_SOURCE_VENUE_DAY_PLAN: "суточный план заведения",
    BOOST_SOURCE_DEPARTMENT_MONTH_PLAN: "месячный план департамента",
    BOOST_SOURCE_DEPARTMENT_DAY_PLAN: "суточный план департамента",
    BOOST_SOURCE_KPI_METRIC: "KPI",
}
BOOST_RECALC_TITLES = {
    BOOST_RECALC_REPLACE_ALL: "весь объём",
    BOOST_RECALC_EXCESS_ONLY: "только превышение",
}


@dataclass(frozen=True)
class PayrollWorkedShift:
    shift_id: int
    shift_date: date
    shift_slot: str
    minutes: int


@dataclass
class PayrollMemberMetrics:
    minutes_total: int = 0
    shifts_count: int = 0
    worked_dates: set[date] = field(default_factory=set)
    worked_shifts: list[PayrollWorkedShift] = field(default_factory=list)


@dataclass
class PayrollRevenueMetrics:
    total_revenue_minor: int = 0
    total_revenue_by_date_minor: dict[date, int] = field(default_factory=dict)
    department_revenue_minor: dict[int, int] = field(default_factory=dict)
    department_revenue_by_date_minor: dict[int, dict[date, int]] = field(default_factory=dict)


@dataclass
class PayrollKpiMetrics:
    totals_by_metric_id: dict[int, int] = field(default_factory=dict)
    values_by_metric_date_slot: dict[int, dict[tuple[date, str], int]] = field(default_factory=dict)


@dataclass
class PayrollCalculationResult:
    run: PayrollRun
    lines: list[PayrollLine]


@dataclass
class PayrollKpiBonusDecision:
    amount_minor: int
    metric_value: int
    threshold_value: int | None = None
    matched_step: dict | None = None
    steps: list[dict] = field(default_factory=list)
    calculation_mode: str = KPI_CALCULATION_FIXED
    percent_bps: int | None = None
    base_amount_minor: int | None = None


@dataclass
class PayrollVenuePlanMetrics:
    month_revenue_target_minor: int | None = None
    day_revenue_target_by_date_minor: dict[date, int | None] = field(default_factory=dict)
    department_month_revenue_target_minor: dict[int, int | None] = field(default_factory=dict)
    department_day_revenue_target_by_date_minor: dict[int, dict[date, int | None]] = field(default_factory=dict)


@dataclass
class PayrollPercentDecision:
    amount_minor: int
    base_amount_minor: int
    base_scope: str
    regular_percent_bps: int
    applied_percent_bps: int
    regular_amount_minor: int
    boost_enabled: bool
    boost_applied: bool
    boost_source_type: str
    boost_source_title: str
    boost_recalc_mode: str
    boost_recalc_mode_effective: str
    boost_recalc_mode_title: str
    boost_percent_bps: int | None = None
    boost_target_minor: int | None = None
    boost_actual_minor: int | None = None
    boost_target_value: int | None = None
    boost_actual_value: int | None = None
    boost_kpi_metric_id: int | None = None
    department_ids: list[int] = field(default_factory=list)
    department_titles: list[str] = field(default_factory=list)
    boost_department_ids: list[int] = field(default_factory=list)
    boost_department_titles: list[str] = field(default_factory=list)
    minimum_guarantee_minor: int | None = None
    minimum_guarantee_scope: str = MINIMUM_GUARANTEE_MONTH
    maximum_cap_minor: int | None = None
    minimum_applied: bool = False
    maximum_applied: bool = False
    day_rows: list[dict] = field(default_factory=list)

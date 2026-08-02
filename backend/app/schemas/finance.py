from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ExpenseCreateIn(BaseModel):
    category_id: int = Field(..., gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    amount_minor: int = Field(..., ge=0)
    expense_date: date
    shift_slot: str = Field("TOTAL", pattern="^(TOTAL|DAY|NIGHT)$")
    spread_months: int = Field(1, ge=1, le=120)
    status: str = Field("DRAFT", min_length=5, max_length=16)
    comment: str | None = Field(default=None, max_length=1000)


class ExpenseUpdateIn(BaseModel):
    category_id: int | None = Field(default=None, gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    clear_supplier: bool = False
    clear_payment_method: bool = False
    amount_minor: int | None = Field(default=None, ge=0)
    expense_date: date | None = None
    shift_slot: str | None = Field(default=None, pattern="^(TOTAL|DAY|NIGHT)$")
    spread_months: int | None = Field(default=None, ge=1, le=120)
    status: str | None = Field(default=None, min_length=5, max_length=16)
    comment: str | None = Field(default=None, max_length=1000)


class BalanceAdjustmentCreateIn(BaseModel):
    payment_method_id: int = Field(..., gt=0)
    adjustment_date: date
    delta_minor: int
    status: str = Field("CONFIRMED", min_length=5, max_length=16)
    reason: str | None = Field(default=None, max_length=255)
    comment: str | None = Field(default=None, max_length=1000)


class BalanceAdjustmentUpdateIn(BaseModel):
    payment_method_id: int | None = Field(default=None, gt=0)
    adjustment_date: date | None = None
    delta_minor: int | None = None
    status: str | None = Field(default=None, min_length=5, max_length=16)
    reason: str | None = Field(default=None, max_length=255)
    comment: str | None = Field(default=None, max_length=1000)


class PaymentMethodTransferCreateIn(BaseModel):
    from_payment_method_id: int = Field(..., gt=0)
    to_payment_method_id: int = Field(..., gt=0)
    transfer_date: date
    amount_minor: int = Field(..., gt=0)
    status: str = Field("CONFIRMED", min_length=5, max_length=16)
    comment: str | None = Field(default=None, max_length=1000)


class PaymentMethodTransferUpdateIn(BaseModel):
    from_payment_method_id: int | None = Field(default=None, gt=0)
    to_payment_method_id: int | None = Field(default=None, gt=0)
    transfer_date: date | None = None
    amount_minor: int | None = Field(default=None, gt=0)
    status: str | None = Field(default=None, min_length=5, max_length=16)
    comment: str | None = Field(default=None, max_length=1000)


class RecurringExpenseRuleCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=160)
    shift_slot: str = Field("TOTAL", pattern="^(TOTAL|DAY|NIGHT)$")
    category_id: int = Field(..., gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    is_active: bool = True
    start_date: date
    end_date: date | None = None
    frequency: str = Field("MONTHLY", min_length=7, max_length=16)
    day_of_month: int = Field(1, ge=1, le=31)
    generation_mode: str = Field("FIXED", min_length=4, max_length=16)
    amount_minor: int | None = Field(default=None, ge=0)
    percent_bps: int | None = Field(default=None, ge=0)
    spread_months: int = Field(1, ge=1, le=120)
    description: str | None = Field(default=None, max_length=1000)
    payment_method_ids: list[int] = Field(default_factory=list)


class RecurringExpenseRuleUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    shift_slot: str | None = Field(default=None, pattern="^(TOTAL|DAY|NIGHT)$")
    category_id: int | None = Field(default=None, gt=0)
    supplier_id: int | None = Field(default=None, gt=0)
    payment_method_id: int | None = Field(default=None, gt=0)
    clear_supplier: bool = False
    clear_payment_method: bool = False
    is_active: bool | None = None
    start_date: date | None = None
    end_date: date | None = None
    clear_end_date: bool = False
    frequency: str | None = Field(default=None, min_length=7, max_length=16)
    day_of_month: int | None = Field(default=None, ge=1, le=31)
    generation_mode: str | None = Field(default=None, min_length=4, max_length=16)
    amount_minor: int | None = Field(default=None, ge=0)
    percent_bps: int | None = Field(default=None, ge=0)
    spread_months: int | None = Field(default=None, ge=1, le=120)
    description: str | None = Field(default=None, max_length=1000)
    payment_method_ids: list[int] | None = None


class FinanceDailyPointOut(BaseModel):
    date: date
    revenue_minor: int
    expense_minor: int
    payroll_minor: int
    total_cost_minor: int
    adjustments_minor: int
    refunds_minor: int
    profit_minor: int


class FinanceCostStructureRowOut(BaseModel):
    key: str
    title: str
    amount_minor: int


class FinanceSummaryOut(BaseModel):
    financial_values_hidden: bool = False
    can_view_financial_values: bool = True
    financial_values_hidden_reason: str | None = None
    month: str | None = None
    period_start: date
    period_end: date
    revenue_minor: int
    expense_minor: int
    expense_without_payroll_minor: int | None = None
    payroll_minor: int
    payroll_expense_minor: int | None = None
    total_cost_minor: int | None = None
    adjustments_minor: int
    refunds_minor: int
    profit_minor: int
    margin_bps: int | None = None
    expense_ratio_bps: int | None = None
    payroll_ratio_bps: int | None = None
    total_cost_ratio_bps: int | None = None
    daily_series: list[FinanceDailyPointOut] = Field(default_factory=list)
    cost_structure: list[FinanceCostStructureRowOut] = Field(default_factory=list)


class MonthlyFinanceBreakdownRowOut(BaseModel):
    title: str
    code: str | None = None
    subtitle: str | None = None
    amount_minor: int


class PaymentMethodBalanceRowOut(BaseModel):
    payment_method_id: int
    title: str
    code: str | None = None
    inflow_minor: int
    outflow_minor: int
    balance_minor: int


class MonthlyFinanceSummaryOut(FinanceSummaryOut):
    income_mode: str
    revenue_breakdown: list[MonthlyFinanceBreakdownRowOut]
    expense_categories: list[MonthlyFinanceBreakdownRowOut]
    payment_method_balances: list[PaymentMethodBalanceRowOut]
    draft_expense_count: int = 0
    draft_expense_total_minor: int = 0


class DailyFinanceSummaryOut(FinanceSummaryOut):
    date: date
    income_mode: str
    shift_slot: str = "TOTAL"
    slot_costs_available: bool = True
    slot_profit_available: bool = True
    revenue_breakdown: list[MonthlyFinanceBreakdownRowOut]
    point_expenses: list[MonthlyFinanceBreakdownRowOut]
    point_expense_minor: int
    recurring_expenses: list[MonthlyFinanceBreakdownRowOut]
    recurring_expense_minor: int
    payment_method_balances: list[PaymentMethodBalanceRowOut]
    draft_expense_count: int = 0
    draft_expense_total_minor: int = 0

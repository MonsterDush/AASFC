from __future__ import annotations

from datetime import date
from pydantic import BaseModel, Field


class ReportValueIn(BaseModel):
    ref_id: int = Field(..., ge=1)
    value: int = Field(0, ge=0)


class DailyReportUpsertIn(BaseModel):
    date: date

    # legacy fields (kept for backwards compatibility)
    cash: int = Field(0, ge=0)
    cashless: int = Field(0, ge=0)
    revenue_total: int = Field(0, ge=0)
    tips_total: int = Field(0, ge=0)

    # dynamic values (A2)
    payments: list[ReportValueIn] | None = None
    departments: list[ReportValueIn] | None = None
    kpis: list[ReportValueIn] | None = None

    # optional comment (stored on report)
    comment: str | None = None


class DailyReportCloseIn(BaseModel):
    comment: str | None = None





class AdjustmentCreateIn(BaseModel):
    type: str = Field(..., description="penalty|writeoff|bonus")
    date: date
    amount: int = Field(0, ge=0)
    reason: str | None = Field(default=None, max_length=500)
    member_user_id: int | None = Field(default=None, gt=0)


class DisputeCreateIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)

class DisputeCommentIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)

class DisputeStatusIn(BaseModel):
    status: str = Field(..., min_length=4, max_length=20)  # OPEN | CLOSED

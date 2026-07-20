from __future__ import annotations

from datetime import datetime, timezone, date, time, timedelta
from typing import Optional, List
from pydantic import BaseModel, Field


class ShiftIntervalCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    start_time: time
    end_time: time
    is_active: bool = True


class ShiftIntervalUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=100)
    start_time: time | None = None
    end_time: time | None = None
    is_active: bool | None = None


class ShiftCreateIn(BaseModel):
    date: date
    interval_id: int = Field(..., gt=0)
    is_active: bool = True
    shift_slot: str | None = Field(default="DAY", max_length=16)


class ShiftUpdateIn(BaseModel):
    date: date | Optional[date] = None
    interval_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    shift_slot: str | None = Field(default=None, max_length=16)


class ShiftScheduleTemplateItemIn(BaseModel):
    weekday: int = Field(..., ge=0, le=6, description="0=Monday ... 6=Sunday")
    interval_id: int = Field(..., gt=0)
    shift_slot: str | None = Field(default="DAY", max_length=16)


class ShiftScheduleTemplateCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool = True
    items: list[ShiftScheduleTemplateItemIn] = Field(default_factory=list)


class ShiftScheduleTemplateUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None
    items: list[ShiftScheduleTemplateItemIn] | None = None


class ShiftScheduleTemplateApplyIn(BaseModel):
    month: str = Field(..., min_length=7, max_length=7, description="YYYY-MM")
    mode: str = Field(..., min_length=4, max_length=32)


class ShiftAssignmentAddIn(BaseModel):
    venue_position_id: int = Field(..., gt=0)

from __future__ import annotations

from pydantic import BaseModel, Field


class CatalogItemCreateIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)
    is_active: bool = True
    sort_order: int = Field(0, ge=0)


class CatalogItemUpdateIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class KpiMetricCreateIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)
    unit: str = Field("QTY", min_length=1, max_length=24)
    is_active: bool = True
    sort_order: int = Field(0, ge=0)


class KpiMetricUpdateIn(BaseModel):
    code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=120)
    unit: str | None = Field(default=None, min_length=1, max_length=24)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)


class SupplierCreateIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=255)
    is_active: bool = True
    sort_order: int = Field(0, ge=0)


class SupplierUpdateIn(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    contact: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0)

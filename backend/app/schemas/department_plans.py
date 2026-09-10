from datetime import date

from pydantic import BaseModel, Field, model_validator


class DepartmentPlanValueIn(BaseModel):
    revenue_plan_minor: int | None = Field(default=None, gt=0)


class DepartmentWeekdayPlanIn(DepartmentPlanValueIn):
    weekday: int = Field(ge=0, le=6)


class DepartmentDaysBulkIn(BaseModel):
    department_id: int = Field(gt=0)
    date_from: date
    date_to: date
    weekdays: list[DepartmentWeekdayPlanIn] = Field(min_length=1, max_length=7)
    overwrite_existing: bool = False
    clear_existing: bool = False
    dry_run: bool = False
    preview_token: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_range(self):
        if not 0 <= (self.date_to - self.date_from).days <= 365:
            raise ValueError("Диапазон должен содержать от 1 до 366 дней")
        if len({row.weekday for row in self.weekdays}) != len(self.weekdays):
            raise ValueError("Дни недели не должны повторяться")
        has_values = any(row.revenue_plan_minor is not None for row in self.weekdays)
        if not has_values and not self.clear_existing:
            raise ValueError("Укажите план хотя бы для одного дня недели")
        if has_values and self.clear_existing:
            raise ValueError("Для удаления планов оставьте все выбранные дни недели пустыми")
        return self

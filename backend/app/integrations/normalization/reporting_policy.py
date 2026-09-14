from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta


@dataclass(frozen=True, slots=True)
class VenueReportingPolicy:
    business_day_cutoff_hour: int = 0
    night_shift_split_enabled: bool = False
    night_shift_start_hour: int = 22
    version: int = 1

    def __post_init__(self) -> None:
        cutoff = int(self.business_day_cutoff_hour)
        night_start = int(self.night_shift_start_hour)
        if not 0 <= cutoff <= 23:
            raise ValueError("business day cutoff hour must be between 0 and 23")
        if not 0 <= night_start <= 23:
            raise ValueError("night shift start hour must be between 0 and 23")
        if self.night_shift_split_enabled and night_start <= cutoff:
            raise ValueError("night shift start hour must be greater than business day cutoff hour")
        if int(self.version) < 1:
            raise ValueError("reporting policy version must be positive")

    def business_date(self, local_started_at: datetime) -> date:
        target = local_started_at.date()
        if local_started_at.hour < int(self.business_day_cutoff_hour):
            target -= timedelta(days=1)
        return target

    def shift_slot(self, local_started_at: datetime) -> str:
        if not self.night_shift_split_enabled:
            return "DAY"
        hour = int(local_started_at.hour)
        return (
            "NIGHT" if hour >= int(self.night_shift_start_hour) or hour < int(self.business_day_cutoff_hour) else "DAY"
        )

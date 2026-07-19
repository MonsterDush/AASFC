from __future__ import annotations

from typing import Optional, List
from pydantic import BaseModel, Field


class VenueSelfServiceCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)



# ---------- Schemas ----------

class VenueCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    owner_usernames: Optional[List[str]] = None  # legacy fallback ["owner1", "@owner2"]
    owner_user_id: int | None = None
    owner_tg_username: str | None = None
    owner_phone: str | None = None


class VenueUpdateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class InviteCreateIn(BaseModel):
    invite_channel: str = "TELEGRAM"  # TELEGRAM | PHONE
    tg_username: str | None = None
    phone: str | None = None
    contact_label: str | None = None
    venue_role: str = "STAFF"  # OWNER | STAFF



class InviteDefaultPositionIn(BaseModel):
    # preset position data to apply after invite is accepted
    title: str = Field(..., min_length=1, max_length=100)
    rate: int = Field(0, ge=0)
    percent: int = Field(0, ge=0, le=100)
    pay_profile_id: int | None = Field(default=None, gt=0)
    pay_profile_title: str | None = Field(default=None, max_length=120)
    # Fine-grained permissions (only source of truth)
    permission_codes: list[str] | None = None



class InviteDefaultPositionPatchIn(BaseModel):
    default_position: InviteDefaultPositionIn | None = None


class VenueSettingsOut(BaseModel):
    tips_enabled: bool = False
    night_shifts_enabled: bool = False
    tips_split_mode: str = "EQUAL"
    tips_weights: dict | None = None


class VenueSettingsPatchIn(BaseModel):
    tips_enabled: bool | None = None
    night_shifts_enabled: bool | None = None
    tips_split_mode: str | None = None
    tips_weights: dict | None = None


from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))

    # NEW: archive flags
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    archived_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # NEW: tips settings (B2+)
    tips_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tips_split_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="EQUAL")  # EQUAL | WEIGHTED_BY_POSITION (stub)
    tips_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # stub for future weighted split

    members = relationship("VenueMember", back_populates="venue")

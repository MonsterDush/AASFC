from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class VenuePosition(Base):
    """Job position (role) of a specific member within a specific venue.

    Notes (MVP):
    - We keep a single row per (venue_id, member_user_id) and update it in place.
    - is_active allows temporarily disabling a position without removing the row.
    """

    __tablename__ = "venue_positions"
    __table_args__ = (
        UniqueConstraint("venue_id", "member_user_id", name="uq_venue_position_member"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    member_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    title: Mapped[str] = mapped_column(String(100), nullable=False)

    # MVP: integers (e.g., rate=3000, percent=10). We can migrate to Numeric later.
    rate: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    percent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Reports / schedule
    can_make_reports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_view_reports: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_view_revenue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_edit_schedule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Adjustments (penalties/writeoffs/bonuses)
    can_view_adjustments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_manage_adjustments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_resolve_disputes: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    member_user = relationship("User")

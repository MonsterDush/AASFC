from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
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

    # Fine-grained permissions for this member within this venue (JSON list of permission codes).
    # Stored as TEXT for compatibility with SQLite and Postgres.
    permission_codes: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    venue = relationship("Venue")
    member_user = relationship("User")

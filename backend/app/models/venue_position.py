from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class VenuePosition(Base):
    """Job position assignment within a venue.

    A row may be empty (``member_user_id`` is NULL), which keeps a position
    available after its last employee is detached. Multiple active rows may
    point to the same member so one employee can hold several positions.
    """

    __tablename__ = "venue_positions"
    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    member_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True, nullable=True)
    pay_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("pay_profiles.id", ondelete="SET NULL"), index=True, nullable=True
    )

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
    pay_profile = relationship("PayProfile")

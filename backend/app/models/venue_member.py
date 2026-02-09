from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class VenueMember(Base):
    __tablename__ = "venue_members"
    __table_args__ = (
        UniqueConstraint("venue_id", "user_id", name="uq_venue_member"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    venue_id: Mapped[int] = mapped_column(ForeignKey("venues.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    venue_role: Mapped[str] = mapped_column(String(32), nullable=False)  # OWNER/STAFF
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    venue = relationship("Venue", back_populates="members")
    user = relationship("User")

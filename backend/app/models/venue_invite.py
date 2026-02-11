from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import relationship

from app.core.db import Base


class VenueInvite(Base):
    __tablename__ = "venue_invites"

    id = Column(Integer, primary_key=True)

    venue_id = Column(Integer, ForeignKey("venues.id", ondelete="CASCADE"), nullable=False)
    invited_tg_username = Column(String(64), nullable=False)  # lower, no @
    venue_role = Column(String(32), nullable=False)  # OWNER/STAFF

    is_active = Column(Boolean, nullable=False, default=True)

    accepted_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    venue = relationship("Venue")
    accepted_user = relationship("User")

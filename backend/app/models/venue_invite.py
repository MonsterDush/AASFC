from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship

from app.core.db import Base


class VenueInvite(Base):
    __tablename__ = "venue_invites"

    id = Column(Integer, primary_key=True)

    venue_id = Column(Integer, ForeignKey("venues.id", ondelete="CASCADE"), nullable=False)
    invited_tg_username = Column(String(64), nullable=True)  # lower, no @
    invited_phone_e164 = Column(String(32), nullable=True)
    invited_contact_label = Column(String(255), nullable=True)
    invite_channel = Column(String(16), nullable=False, default="TELEGRAM")  # TELEGRAM | PHONE
    invite_token = Column(String(64), nullable=False, unique=True, index=True)
    venue_role = Column(String(32), nullable=False)  # OWNER/STAFF

    is_active = Column(Boolean, nullable=False, default=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    accepted_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    accepted_via = Column(String(16), nullable=True)

    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Optional preset position for invited user (applied on accept)
    default_position_json = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    venue = relationship("Venue")
    accepted_user = relationship("User", foreign_keys=[accepted_user_id])
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])

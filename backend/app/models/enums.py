import enum


class SystemRole(str, enum.Enum):
    SUPER_ADMIN = "SUPER_ADMIN"
    MODERATOR = "MODERATOR"
    NONE = "NONE"


class VenueRole(str, enum.Enum):
    OWNER = "OWNER"
    STAFF = "STAFF"


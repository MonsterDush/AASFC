# Роли, которые отображаются/используются в матрице "по умолчанию"
DEFAULT_ROLES = ["MODERATOR", "VENUE_OWNER", "VENUE_MANAGER", "STAFF"]

# Маппинг "роль участника в заведении" -> "роль в матрице дефолтных прав"
VENUE_ROLE_TO_DEFAULT_ROLE = {
    "OWNER": "VENUE_OWNER",
    "MANAGER": "VENUE_MANAGER",
    "STAFF": "STAFF",
}

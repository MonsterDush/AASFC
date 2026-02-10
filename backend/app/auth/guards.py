from __future__ import annotations

from fastapi import Depends, HTTPException, status

from app.auth.deps import get_current_user
from app.models.user import User


def require_super_admin(user: User = Depends(get_current_user)) -> User:
    if user.system_role != "SUPER_ADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="SUPER_ADMIN required",
        )
    return user

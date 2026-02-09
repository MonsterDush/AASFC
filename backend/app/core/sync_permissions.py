from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.permissions_registry import PERMISSIONS
from app.core.roles_registry import DEFAULT_ROLES
from app.models.permission import Permission
from app.models.role_permission_default import RolePermissionDefault


def sync_permissions() -> None:
    with SessionLocal() as db:  
        '''type:session'''
        # --- permissions ---
        existing_perms = {p.code: p for p in db.scalars(select(Permission)).all()}

        created = 0
        updated = 0

        for perm in PERMISSIONS:
            row = existing_perms.get(perm.code)
            if row is None:
                db.add(
                    Permission(
                        code=perm.code,
                        group=perm.group,
                        title=perm.title,
                        description=perm.description,
                        is_active=True,
                    )
                )
                created += 1
            else:
                changed = False
                if row.group != perm.group:
                    row.group = perm.group
                    changed = True
                if row.title != perm.title:
                    row.title = perm.title
                    changed = True
                if row.description != perm.description:
                    row.description = perm.description
                    changed = True
                if changed:
                    updated += 1

        db.flush()  # чтобы новые permissions были видны далее в этой транзакции

        # --- defaults matrix rows ---
        # создаём отсутствующие строки (role, permission_code) со значением false
        existing_defaults = set(
            db.execute(
                select(RolePermissionDefault.role, RolePermissionDefault.permission_code)
            ).all()
        )

        defaults_created = 0
        for role in DEFAULT_ROLES:
            for perm in PERMISSIONS:
                key = (role, perm.code)
                if key not in existing_defaults:
                    db.add(
                        RolePermissionDefault(
                            role=role,
                            permission_code=perm.code,
                            is_granted_by_default=False,
                        )
                    )
                    defaults_created += 1

        db.commit()

        print(
            f"Permissions sync done. permissions_created={created}, permissions_updated={updated}, defaults_created={defaults_created}"
        )


if __name__ == "__main__":
    sync_permissions()

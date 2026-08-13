from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.permission_policy import role_has_built_in_default
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
        defaults_created = 0
        defaults_updated = 0
        existing_default_rows = {
            (row.role, row.permission_code): row
            for row in db.scalars(select(RolePermissionDefault)).all()
        }
        for role in DEFAULT_ROLES:
            for perm in PERMISSIONS:
                key = (role, perm.code)
                should_grant = role_has_built_in_default(role, perm.code)
                row = existing_default_rows.get(key)
                if row is None:
                    db.add(
                        RolePermissionDefault(
                            role=role,
                            permission_code=perm.code,
                            is_granted_by_default=should_grant,
                        )
                    )
                    defaults_created += 1
                    continue
                if bool(row.is_granted_by_default) != bool(should_grant):
                    row.is_granted_by_default = bool(should_grant)
                    defaults_updated += 1

        db.commit()

        print(
            f"Permissions sync done. permissions_created={created}, permissions_updated={updated}, defaults_created={defaults_created}, defaults_updated={defaults_updated}"
        )


if __name__ == "__main__":
    sync_permissions()

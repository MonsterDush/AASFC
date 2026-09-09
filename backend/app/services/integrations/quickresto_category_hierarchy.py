from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.quickresto_dish_category_path import QuickRestoDishCategoryPath
from app.services.integrations.quickresto import (
    QUICKRESTO_OBJECT_TYPES,
    QuickRestoClient,
    QuickRestoHTTPError,
)
from app.services.integrations.quickresto_normalize import QuickRestoDataError


_MAX_CATEGORY_DEPTH = 32


@dataclass(frozen=True)
class QuickRestoCategoryRefreshResult:
    requested_ids: tuple[int, ...]
    refreshed_ids: tuple[int, ...]
    unresolved_ids: tuple[int, ...]

    def as_summary(self) -> dict[str, Any]:
        return {
            "dish_category_ids_seen": len(self.requested_ids),
            "dish_category_paths_refreshed": len(self.refreshed_ids),
            "unresolved_dish_category_ids": list(self.unresolved_ids),
        }


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def referenced_dish_category_ids(sources: Iterable[Mapping[str, Any]]) -> set[int]:
    """Return direct DishCategory ids actually referenced by non-returned orders."""

    output: set[int] = set()
    for source in sources:
        orders = source.get("orders") if isinstance(source, Mapping) else None
        for order in orders if isinstance(orders, list) else ():
            if not isinstance(order, Mapping) or bool(order.get("returned")):
                continue
            items = order.get("orderItemList")
            for item in items if isinstance(items, list) else ():
                if not isinstance(item, Mapping):
                    continue
                product = item.get("product")
                if not isinstance(product, Mapping):
                    continue
                external_id = int(product.get("parentId") or 0)
                if external_id > 0:
                    output.add(external_id)
    return output


def load_dish_category_root_index(
    db: Session,
    *,
    connection_id: int,
    external_ids: Iterable[int] | None = None,
) -> dict[int, int]:
    query = select(QuickRestoDishCategoryPath).where(QuickRestoDishCategoryPath.connection_id == int(connection_id))
    normalized_ids = sorted({int(value) for value in (external_ids or ()) if int(value) > 0})
    if external_ids is not None:
        if not normalized_ids:
            return {}
        query = query.where(QuickRestoDishCategoryPath.external_id.in_(normalized_ids))
    return {int(row.external_id): int(row.root_external_id) for row in db.execute(query).scalars()}


def _upsert_path_rows(
    db: Session,
    *,
    connection_id: int,
    rows_by_id: dict[int, tuple[int | None, int]],
) -> None:
    if not rows_by_id:
        return
    existing = {
        int(row.external_id): row
        for row in db.execute(
            select(QuickRestoDishCategoryPath).where(
                QuickRestoDishCategoryPath.connection_id == int(connection_id),
                QuickRestoDishCategoryPath.external_id.in_(sorted(rows_by_id)),
            )
        ).scalars()
    }
    now = _utcnow()
    for external_id, (parent_external_id, root_external_id) in rows_by_id.items():
        row = existing.get(int(external_id))
        if row is None:
            row = QuickRestoDishCategoryPath(
                connection_id=int(connection_id),
                external_id=int(external_id),
            )
            db.add(row)
        row.parent_external_id = int(parent_external_id) if parent_external_id is not None else None
        row.root_external_id = int(root_external_id)
        row.updated_at = now
    db.flush()


def _resolve_remote_path(
    client: QuickRestoClient,
    *,
    external_id: int,
    cached_roots: dict[int, int],
) -> tuple[int, dict[int, int | None]]:
    module_name, class_name = QUICKRESTO_OBJECT_TYPES["dish_categories"]
    current_id = int(external_id)
    embedded: Mapping[str, Any] | None = None
    seen: set[int] = set()
    parents: dict[int, int | None] = {}

    for _depth in range(_MAX_CATEGORY_DEPTH):
        if current_id in seen:
            raise QuickRestoDataError(f"QuickResto dish category hierarchy contains a cycle (category={current_id})")
        seen.add(current_id)
        cached_root = cached_roots.get(current_id)
        if cached_root is not None:
            return int(cached_root), parents

        node = embedded
        if node is None or int(node.get("id") or 0) != current_id or "parentItem" not in node:
            node = client.read_object(
                module_name=module_name,
                class_name=class_name,
                object_id=current_id,
            )
        node_id = int(node.get("id") or 0)
        if node_id != current_id:
            raise QuickRestoDataError(
                f"QuickResto dish category detail does not match requested id (category={current_id})"
            )

        parent = node.get("parentItem")
        if parent is None:
            parents[current_id] = None
            return current_id, parents
        if not isinstance(parent, Mapping):
            raise QuickRestoDataError(f"QuickResto dish category parent has an invalid shape (category={current_id})")
        parent_id = int(parent.get("id") or 0)
        if parent_id <= 0:
            raise QuickRestoDataError(f"QuickResto dish category parent has no id (category={current_id})")
        parents[current_id] = parent_id
        current_id = parent_id
        embedded = parent

    raise QuickRestoDataError(
        f"QuickResto dish category hierarchy exceeds {_MAX_CATEGORY_DEPTH} levels (category={external_id})"
    )


def refresh_dish_category_paths(
    db: Session,
    *,
    connection_id: int,
    client: QuickRestoClient,
    external_ids: Iterable[int],
    direct_mapping_ids: Iterable[int] = (),
) -> QuickRestoCategoryRefreshResult:
    requested = tuple(sorted({int(value) for value in external_ids if int(value) > 0}))
    direct = {int(value) for value in direct_mapping_ids if int(value) > 0}
    pending = [external_id for external_id in requested if external_id not in direct]
    cached_roots = load_dish_category_root_index(db, connection_id=int(connection_id)) if pending else {}
    cached_roots.update({external_id: external_id for external_id in direct})
    refreshed: set[int] = set()
    unresolved: set[int] = set()

    for external_id in pending:
        if external_id in cached_roots:
            continue
        try:
            root_external_id, parents = _resolve_remote_path(
                client,
                external_id=external_id,
                cached_roots=cached_roots,
            )
        except QuickRestoHTTPError as exc:
            if exc.status_code not in {400, 404}:
                raise
            unresolved.add(external_id)
            continue
        except QuickRestoDataError:
            unresolved.add(external_id)
            continue
        path_rows = {node_id: (parent_id, root_external_id) for node_id, parent_id in parents.items()}
        path_rows.setdefault(root_external_id, (None, root_external_id))
        _upsert_path_rows(
            db,
            connection_id=int(connection_id),
            rows_by_id=path_rows,
        )
        for node_id in path_rows:
            cached_roots[int(node_id)] = int(root_external_id)
        refreshed.add(external_id)

    return QuickRestoCategoryRefreshResult(
        requested_ids=requested,
        refreshed_ids=tuple(sorted(refreshed)),
        unresolved_ids=tuple(sorted(unresolved)),
    )


def copy_dish_category_paths(
    db: Session,
    *,
    source_connection_id: int,
    target_connection_id: int,
) -> int:
    if int(source_connection_id) == int(target_connection_id):
        return 0
    source_rows = list(
        db.execute(
            select(QuickRestoDishCategoryPath).where(
                QuickRestoDishCategoryPath.connection_id == int(source_connection_id)
            )
        ).scalars()
    )
    _upsert_path_rows(
        db,
        connection_id=int(target_connection_id),
        rows_by_id={
            int(row.external_id): (
                int(row.parent_external_id) if row.parent_external_id is not None else None,
                int(row.root_external_id),
            )
            for row in source_rows
        },
    )
    return len(source_rows)

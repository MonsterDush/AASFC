from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import QuickRestoDepartmentMapping
from app.models.quickresto_dish_category_path import QuickRestoDishCategoryPath
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.services.integrations.quickresto import QuickRestoHTTPError
from app.services.integrations.quickresto_category_hierarchy import (
    copy_dish_category_paths,
    referenced_dish_category_ids,
    refresh_dish_category_paths,
)
from app.services.integrations.quickresto_sync import _mapped_aggregate, _refresh_snapshot_category_paths


class CategoryDetailClient:
    def __init__(self, details: dict[int, dict]):
        self.details = details
        self.calls: list[int] = []

    def read_object(self, *, module_name, class_name, object_id):
        self.assert_module_name = module_name
        self.assert_class_name = class_name
        self.calls.append(int(object_id))
        return self.details[int(object_id)]

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return None


class QuickRestoCategoryHierarchyTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                QuickRestoConnection.__table__,
                QuickRestoDepartmentMapping.__table__,
                QuickRestoDishCategoryPath.__table__,
                QuickRestoPaymentMapping.__table__,
            ],
        )

    def tearDown(self):
        self.engine.dispose()

    def test_nested_category_resolves_to_root_and_is_cached(self):
        client = CategoryDetailClient(
            {
                608: {"id": 608, "parentItem": {"id": 5}},
                5: {"id": 5, "parentItem": {"id": 1231, "parentItem": None}},
            }
        )
        with Session(self.engine) as db:
            first = refresh_dish_category_paths(
                db,
                connection_id=2,
                client=client,
                external_ids={608},
                direct_mapping_ids={1101, 1230, 1231},
            )
            db.commit()

            self.assertEqual(first.refreshed_ids, (608,))
            self.assertEqual(first.unresolved_ids, ())
            self.assertEqual(client.calls, [608, 5])
            paths = {int(row.external_id): row for row in db.execute(select(QuickRestoDishCategoryPath)).scalars()}
            self.assertEqual(paths[608].parent_external_id, 5)
            self.assertEqual(paths[608].root_external_id, 1231)
            self.assertEqual(paths[5].parent_external_id, 1231)
            self.assertEqual(paths[5].root_external_id, 1231)
            self.assertIsNone(paths[1231].parent_external_id)
            self.assertEqual(paths[1231].root_external_id, 1231)

            second = refresh_dish_category_paths(
                db,
                connection_id=2,
                client=client,
                external_ids={608},
                direct_mapping_ids={1101, 1230, 1231},
            )
            self.assertEqual(second.refreshed_ids, ())
            self.assertEqual(client.calls, [608, 5])

    def test_cycle_stays_unresolved_without_persisting_partial_path(self):
        client = CategoryDetailClient(
            {
                10: {"id": 10, "parentItem": {"id": 11}},
                11: {"id": 11, "parentItem": {"id": 10}},
            }
        )
        with Session(self.engine) as db:
            result = refresh_dish_category_paths(
                db,
                connection_id=3,
                client=client,
                external_ids={10},
            )
            self.assertEqual(result.unresolved_ids, (10,))
            self.assertEqual(db.execute(select(QuickRestoDishCategoryPath)).scalars().all(), [])

    def test_nearest_mapped_ancestor_is_used_as_resolution_boundary(self):
        client = CategoryDetailClient({608: {"id": 608, "parentItem": {"id": 5}}})
        with Session(self.engine) as db:
            result = refresh_dish_category_paths(
                db,
                connection_id=3,
                client=client,
                external_ids={608},
                direct_mapping_ids={5},
            )

            self.assertEqual(result.refreshed_ids, (608,))
            self.assertEqual(client.calls, [608])
            path = db.execute(
                select(QuickRestoDishCategoryPath).where(
                    QuickRestoDishCategoryPath.connection_id == 3,
                    QuickRestoDishCategoryPath.external_id == 608,
                )
            ).scalar_one()
            self.assertEqual(path.root_external_id, 5)

    def test_deleted_historical_category_stays_actionable(self):
        client = CategoryDetailClient({})
        with Session(self.engine) as db:
            with patch.object(
                client,
                "read_object",
                side_effect=QuickRestoHTTPError("missing category", status_code=400),
            ):
                result = refresh_dish_category_paths(
                    db,
                    connection_id=3,
                    client=client,
                    external_ids={608},
                )
            self.assertEqual(result.unresolved_ids, (608,))
            self.assertEqual(db.execute(select(QuickRestoDishCategoryPath)).scalars().all(), [])

    def test_paths_copy_between_connections_for_confirmed_venue_move(self):
        client = CategoryDetailClient({608: {"id": 608, "parentItem": {"id": 1231, "parentItem": None}}})
        with Session(self.engine) as db:
            refresh_dish_category_paths(
                db,
                connection_id=4,
                client=client,
                external_ids={608},
            )
            copied = copy_dish_category_paths(
                db,
                source_connection_id=4,
                target_connection_id=5,
            )
            db.commit()

            self.assertEqual(copied, 2)
            target = {
                int(row.external_id): int(row.root_external_id)
                for row in db.execute(
                    select(QuickRestoDishCategoryPath).where(QuickRestoDishCategoryPath.connection_id == 5)
                ).scalars()
            }
            self.assertEqual(target, {608: 1231, 1231: 1231})

    def test_referenced_ids_ignore_returned_orders(self):
        source = {
            "orders": [
                {"returned": False, "orderItemList": [{"product": {"parentId": 608}}]},
                {"returned": True, "orderItemList": [{"product": {"parentId": 999}}]},
            ]
        }
        self.assertEqual(referenced_dish_category_ids([source]), {608})

    def test_legacy_snapshot_retry_fetches_only_missing_category_path(self):
        client = CategoryDetailClient({608: {"id": 608, "parentItem": {"id": 1231, "parentItem": None}}})
        source = {
            "orders": [
                {"returned": False, "orderItemList": [{"product": {"parentId": 608}}]},
            ]
        }
        connection = SimpleNamespace(
            id=7,
            cloud="fixture",
            api_login_encrypted="unused",
            api_password_encrypted="unused",
        )
        with Session(self.engine) as db:
            db.add(
                QuickRestoDepartmentMapping(
                    connection_id=7,
                    external_id=1231,
                    external_name="Паровые позиции",
                    department_id=None,
                )
            )
            db.add(
                QuickRestoDepartmentMapping(
                    connection_id=7,
                    external_id=608,
                    external_name="Вложенная категория",
                    department_id=None,
                )
            )
            db.commit()
            with (
                patch(
                    "app.services.integrations.quickresto_sync.open_source_snapshot",
                    return_value=source,
                ),
                patch(
                    "app.services.integrations.quickresto_sync.build_quickresto_client",
                    return_value=client,
                ) as build_client,
            ):
                result = _refresh_snapshot_category_paths(
                    db,
                    connection=connection,
                    snapshots=[SimpleNamespace()],
                    client=None,
                )
            db.commit()

            build_client.assert_called_once_with(connection)
            self.assertEqual(client.calls, [608])
            self.assertEqual(result.refreshed_ids, (608,))
            path = db.execute(
                select(QuickRestoDishCategoryPath).where(
                    QuickRestoDishCategoryPath.connection_id == 7,
                    QuickRestoDishCategoryPath.external_id == 608,
                )
            ).scalar_one()
            self.assertEqual(path.root_external_id, 1231)

    def test_unmapped_nested_category_uses_mapped_root(self):
        with Session(self.engine) as db:
            db.add_all(
                [
                    QuickRestoDepartmentMapping(
                        connection_id=7,
                        external_id=608,
                        external_name="Вложенная категория",
                        department_id=None,
                    ),
                    QuickRestoDepartmentMapping(
                        connection_id=7,
                        external_id=1231,
                        external_name="Паровые позиции",
                        department_id=42,
                    ),
                    QuickRestoDishCategoryPath(
                        connection_id=7,
                        external_id=608,
                        parent_external_id=1231,
                        root_external_id=1231,
                    ),
                    QuickRestoPaymentMapping(
                        connection_id=7,
                        external_id=1,
                        external_name="Наличные",
                        operation_type="payment",
                        payment_method_id=44,
                        excluded_from_revenue=False,
                        is_applicable=True,
                        is_available=True,
                        allowed_sale_place_ids_json=[],
                    ),
                ]
            )
            db.flush()

            result = _mapped_aggregate(
                db,
                connection=SimpleNamespace(id=7, scope_status="READY", external_venue_id=501),
                aggregate={
                    "payments_external": {1: 100},
                    "departments_external": {608: 100},
                    "revenue_total": 100,
                },
            )

            self.assertEqual(result["payments_internal"], {44: 100})
            self.assertEqual(result["departments_internal"], {42: 100})


if __name__ == "__main__":
    unittest.main()

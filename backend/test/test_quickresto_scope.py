from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import unittest

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.daily_report import DailyReport
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_external_venue import QuickRestoExternalVenue
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_sale_place_scope import QuickRestoSalePlaceScope
from app.models.quickresto_shift_import import QuickRestoShiftImport
from app.models.quickresto_store_scope import QuickRestoStoreScope
from app.models.user import User
from app.models.venue import Venue
from app.services.integrations.quickresto_scope import (
    QuickRestoScopeConflictError,
    QuickRestoScopeIndex,
    apply_quickresto_scope,
    evaluate_quickresto_shift_scope,
    refresh_quickresto_catalog,
    serialize_quickresto_catalog,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class CatalogQuickRestoClient:
    def __init__(self) -> None:
        self.rows = {
            "TableScheme": [
                {"id": 101, "name": "Центр", "address": {"fullAddress": "Москва, Центр"}},
                {"id": 102, "name": "Север", "address": {"fullAddress": "Москва, Север"}},
            ],
            "SalePlace": [
                {
                    "id": 201,
                    "title": "Центр — касса",
                    "tableScheme": {"id": 101},
                    "defaultCookingPlace": {"id": 301},
                },
                {
                    "id": 202,
                    "title": "Центр — доставка",
                    "tableScheme": {"id": 101},
                    "defaultCookingPlace": {"id": 302},
                },
                {
                    "id": 203,
                    "title": "Север — касса",
                    "tableScheme": {"id": 102},
                    "defaultCookingPlace": {"id": 303},
                },
            ],
            "CookingPlace": [
                {"id": 301, "title": "Бар", "store": {"id": 401}},
                {"id": 302, "title": "Кухня", "store": {"id": 402}},
                {"id": 303, "title": "Север", "store": {"id": 403}},
            ],
            "Store": [
                {"id": 401, "title": "Склад бара"},
                {"id": 402, "title": "Склад кухни"},
                {"id": 403, "title": "Склад Севера"},
            ],
            "PaymentType": [
                {
                    "id": 501,
                    "name": "Наличные",
                    "operationType": "payment",
                    "allowedSalePlacesWeb": [],
                },
                {
                    "id": 502,
                    "name": "Только центр",
                    "operationType": "payment",
                    "allowedSalePlacesWeb": [{"id": 201}],
                },
                {
                    "id": 503,
                    "name": "Только север",
                    "operationType": "payment",
                    "allowedSalePlacesWeb": [{"id": 203}],
                },
            ],
        }

    def list_all_objects(self, *, module_name, class_name):
        del module_name
        key = class_name.rsplit(".", 1)[-1]
        return deepcopy(self.rows[key])

    def read_object(self, *, module_name, class_name, object_id):
        del module_name
        key = class_name.rsplit(".", 1)[-1]
        return deepcopy(next(row for row in self.rows[key] if int(row["id"]) == int(object_id)))


class QuickRestoScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                Venue.__table__,
                PaymentMethod.__table__,
                DailyReport.__table__,
                QuickRestoConnection.__table__,
                QuickRestoExternalVenue.__table__,
                QuickRestoSalePlaceScope.__table__,
                QuickRestoStoreScope.__table__,
                QuickRestoPaymentMapping.__table__,
                QuickRestoShiftImport.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.db.add(User(id=1, system_role="NONE"))
        self.db.add(Venue(id=1, name="Axelio Центр"))
        self.connection = QuickRestoConnection(
            venue_id=1,
            cloud="multi",
            api_login_encrypted="v1:unused",
            api_password_encrypted="v1:unused",
            created_by_user_id=1,
        )
        self.db.add(self.connection)
        self.db.commit()
        self.db.refresh(self.connection)
        self.client = CatalogQuickRestoClient()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_catalog_and_scope_filter_locations_stores_and_payments(self):
        summary = refresh_quickresto_catalog(
            self.db,
            connection=self.connection,
            client=self.client,
        )
        self.assertEqual(summary["venues_seen"], 2)
        self.assertEqual(summary["sale_places_seen"], 3)
        self.assertEqual(summary["stores_seen"], 3)

        result = apply_quickresto_scope(
            self.db,
            connection=self.connection,
            external_venue_id=101,
            sale_place_ids=[201],
            store_ids=[401],
        )
        self.assertTrue(result["changed"])
        self.assertEqual(result["scope_status"], "READY")

        catalog = serialize_quickresto_catalog(self.db, connection=self.connection)
        selected_places = [item["external_id"] for item in catalog["sale_places"] if item["is_selected"]]
        selected_stores = [item["external_id"] for item in catalog["stores"] if item["is_selected"]]
        applicable_payments = [item["external_id"] for item in catalog["payment_types"] if item["is_applicable"]]
        self.assertEqual(selected_places, [201])
        self.assertEqual(selected_stores, [401])
        self.assertEqual(applicable_payments, [501, 502])

    def test_same_cloud_venue_cannot_be_linked_twice(self):
        refresh_quickresto_catalog(self.db, connection=self.connection, client=self.client)
        apply_quickresto_scope(
            self.db,
            connection=self.connection,
            external_venue_id=101,
            sale_place_ids=[201],
            store_ids=[401],
        )
        self.db.add(Venue(id=2, name="Axelio Дубль"))
        duplicate = QuickRestoConnection(
            venue_id=2,
            cloud="multi",
            api_login_encrypted="v1:unused",
            api_password_encrypted="v1:unused",
            created_by_user_id=1,
        )
        self.db.add(duplicate)
        self.db.flush()
        refresh_quickresto_catalog(self.db, connection=duplicate, client=self.client)

        with self.assertRaisesRegex(QuickRestoScopeConflictError, "уже подключено"):
            apply_quickresto_scope(
                self.db,
                connection=duplicate,
                external_venue_id=101,
                sale_place_ids=[201],
                store_ids=[401],
            )

    def test_external_venue_cannot_change_after_a_shift_was_imported(self):
        refresh_quickresto_catalog(self.db, connection=self.connection, client=self.client)
        apply_quickresto_scope(
            self.db,
            connection=self.connection,
            external_venue_id=101,
            sale_place_ids=[201],
            store_ids=[401],
        )
        self.db.add(
            QuickRestoShiftImport(
                connection_id=self.connection.id,
                external_shift_id="shift-1",
                external_shift_pk=1,
                source_version=1,
                business_date=date(2030, 1, 15),
                shift_slot="DAY",
                payload_hash="a" * 64,
                normalized_json={},
            )
        )
        self.db.flush()

        with self.assertRaisesRegex(QuickRestoScopeConflictError, "Нельзя сменить"):
            apply_quickresto_scope(
                self.db,
                connection=self.connection,
                external_venue_id=102,
                sale_place_ids=[203],
                store_ids=[403],
            )

    def test_shift_scope_decisions_are_explicit_and_safe(self):
        now = datetime.now(timezone.utc)
        scope = QuickRestoScopeIndex(
            external_venue_id=101,
            sale_places={
                201: QuickRestoSalePlaceScope(
                    connection_id=1,
                    external_id=201,
                    external_name="Выбрано",
                    external_venue_id=101,
                    is_selected=True,
                    is_confirmed=True,
                    is_available=True,
                    last_seen_at=now,
                ),
                202: QuickRestoSalePlaceScope(
                    connection_id=1,
                    external_id=202,
                    external_name="Исключено",
                    external_venue_id=101,
                    is_selected=False,
                    is_confirmed=True,
                    is_available=True,
                    last_seen_at=now,
                ),
                203: QuickRestoSalePlaceScope(
                    connection_id=1,
                    external_id=203,
                    external_name="Другое заведение",
                    external_venue_id=102,
                    is_selected=False,
                    is_confirmed=True,
                    is_available=True,
                    last_seen_at=now,
                ),
            },
        )

        imported = evaluate_quickresto_shift_scope(
            {"tableScheme": {"id": 101}, "salePlace": {"id": 201}},
            scope=scope,
        )
        excluded = evaluate_quickresto_shift_scope(
            {"tableScheme": {"id": 101}, "salePlace": {"id": 202}},
            scope=scope,
        )
        other = evaluate_quickresto_shift_scope(
            {"tableScheme": {"id": 102}, "salePlace": {"id": 203}},
            scope=scope,
        )
        unresolved = evaluate_quickresto_shift_scope({"id": 1}, scope=scope)
        conflict = evaluate_quickresto_shift_scope(
            {
                "tableScheme": {"id": 101},
                "salePlace": {"id": 201},
                "createTerminalSalePlace": {"id": 202},
            },
            scope=scope,
        )

        self.assertEqual(imported.action, "IMPORT")
        self.assertEqual(excluded.action, "SKIP_UNSELECTED_SALE_PLACE")
        self.assertEqual(other.action, "SKIP_OTHER_VENUE")
        self.assertEqual(unresolved.error.error_code, "LOCATION_UNRESOLVED")
        self.assertEqual(conflict.error.error_code, "LOCATION_SCOPE_CONFLICT")


if __name__ == "__main__":
    unittest.main()

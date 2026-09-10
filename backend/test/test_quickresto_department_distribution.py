from __future__ import annotations

from datetime import date, datetime, timezone
import unittest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.department import Department
from app.models.payment_method import PaymentMethod
from app.models.quickresto_connection import QuickRestoConnection
from app.models.quickresto_department_mapping import (
    QuickRestoDepartmentAllocation,
    QuickRestoDepartmentMapping,
)
from app.models.quickresto_import_issue import QuickRestoImportIssue
from app.models.quickresto_payment_mapping import QuickRestoPaymentMapping
from app.models.quickresto_sync_run import QuickRestoSyncRun
from app.models.user import User
from app.models.venue import Venue
from app.routers.venue_quickresto import _mapping_readiness, _serialize_mappings, put_quickresto_mappings
from app.schemas.quickresto import QuickRestoDepartmentMappingIn, QuickRestoMappingsUpdateIn
from app.services.integrations.quickresto_department_distribution import allocate_integer_total
from app.services.integrations.quickresto_sync import _mapped_aggregate


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class QuickRestoDepartmentDistributionTests(unittest.TestCase):
    def test_integer_allocation_preserves_positive_and_negative_totals(self):
        distribution = {21: 60, 22: 40}

        self.assertEqual(allocate_integer_total(101, distribution), {21: 61, 22: 40})
        self.assertEqual(allocate_integer_total(-101, distribution), {21: -61, 22: -40})

    def test_schema_requires_unique_targets_and_exactly_one_hundred_percent(self):
        valid = QuickRestoDepartmentMappingIn.model_validate(
            {
                "external_id": 1106,
                "allocations": [
                    {"department_id": 21, "share_percent": 60},
                    {"department_id": 22, "share_percent": 40},
                ],
            }
        )
        self.assertEqual(sum(item.share_percent for item in valid.allocations), 100)

        for payload in (
            {
                "external_id": 1106,
                "department_id": 21,
                "allocations": [{"department_id": 22, "share_percent": 100}],
            },
            {
                "external_id": 1106,
                "allocations": [
                    {"department_id": 21, "share_percent": 50},
                    {"department_id": 21, "share_percent": 50},
                ],
            },
            {
                "external_id": 1106,
                "allocations": [
                    {"department_id": 21, "share_percent": 60},
                    {"department_id": 22, "share_percent": 30},
                ],
            },
        ):
            with self.assertRaises(ValidationError):
                QuickRestoDepartmentMappingIn.model_validate(payload)

    def test_active_issue_candidate_can_be_mapped_once_and_reused_for_aggregate(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            engine,
            tables=[
                User.__table__,
                Venue.__table__,
                PaymentMethod.__table__,
                Department.__table__,
                QuickRestoConnection.__table__,
                QuickRestoPaymentMapping.__table__,
                QuickRestoDepartmentMapping.__table__,
                QuickRestoDepartmentAllocation.__table__,
                QuickRestoSyncRun.__table__,
                QuickRestoImportIssue.__table__,
            ],
        )
        with Session(engine) as db:
            user = User(id=1, system_role="SUPER_ADMIN")
            venue = Venue(id=21, name="Composite QuickResto")
            bar = Department(id=21, venue_id=21, code="bar", title="Бар", sort_order=1)
            hookah = Department(id=22, venue_id=21, code="hookah", title="Кальян", sort_order=2)
            card = PaymentMethod(id=31, venue_id=21, code="card", title="Карта", sort_order=1)
            db.add_all([user, venue, bar, hookah, card])
            connection = QuickRestoConnection(
                venue_id=21,
                cloud="ua357",
                api_login_encrypted="v1:test",
                api_password_encrypted="v1:test",
                external_venue_id=3,
                external_venue_name="Мытищи",
                scope_status="READY",
                is_active=True,
                report_import_mode="CLOSED",
                business_day_cutoff_hour=8,
                sync_from_date=date(2026, 7, 31),
                created_by_user_id=1,
            )
            db.add(connection)
            db.flush()
            db.add(
                QuickRestoPaymentMapping(
                    connection_id=connection.id,
                    external_id=901,
                    external_name="Карта",
                    operation_type="payment",
                    payment_method_id=31,
                    excluded_from_revenue=False,
                    is_applicable=True,
                    is_available=True,
                    allowed_sale_place_ids_json=[],
                )
            )
            db.add(
                QuickRestoImportIssue(
                    connection_id=connection.id,
                    group_key="REPORT:2026-09-03:DAY",
                    business_date=date(2026, 9, 3),
                    shift_slot="DAY",
                    status="OPEN",
                    error_code="MAPPING_INCOMPLETE",
                    error_category="MAPPING",
                    user_summary="Нужно сопоставление",
                    technical_summary="QuickResto mappings are incomplete (payments=[], departments=[1106])",
                    details_json={"missing_department_ids": [1106]},
                    failure_fingerprint="f" * 64,
                    correlation_id="c" * 32,
                    attempt_count=1,
                    first_failed_at=datetime.now(timezone.utc),
                    last_failed_at=datetime.now(timezone.utc),
                )
            )
            db.commit()

            serialized = _serialize_mappings(db, connection)
            candidate = next(item for item in serialized["departments"] if item["external_id"] == 1106)
            self.assertTrue(candidate["is_issue_candidate"])
            self.assertEqual(_mapping_readiness(db, connection)["unmapped_department_ids"], [1106])

            result = put_quickresto_mappings(
                21,
                QuickRestoMappingsUpdateIn.model_validate(
                    {
                        "departments": [
                            {
                                "external_id": 1106,
                                "allocations": [
                                    {"department_id": 21, "share_percent": 60},
                                    {"department_id": 22, "share_percent": 40},
                                ],
                            }
                        ]
                    }
                ),
                db,
                user,
            )
            saved = next(item for item in result["mappings"]["departments"] if item["external_id"] == 1106)
            self.assertEqual(
                saved["allocations"],
                [
                    {"department_id": 21, "share_percent": 60},
                    {"department_id": 22, "share_percent": 40},
                ],
            )
            self.assertTrue(result["mapping_readiness"]["ready"])

            aggregate = _mapped_aggregate(
                db,
                connection=connection,
                aggregate={
                    "payments_external": {"901": 101},
                    "departments_external": {"1106": 101},
                    "revenue_total": 101,
                },
            )
            self.assertEqual(aggregate["departments_internal"], {21: 61, 22: 40})
            self.assertEqual(
                len(
                    db.execute(select(QuickRestoDepartmentAllocation).join(QuickRestoDepartmentMapping)).scalars().all()
                ),
                2,
            )

            with self.assertRaises(HTTPException) as context:
                put_quickresto_mappings(
                    21,
                    QuickRestoMappingsUpdateIn.model_validate(
                        {"departments": [{"external_id": 9999, "department_id": 21}]}
                    ),
                    db,
                    user,
                )
            self.assertEqual(context.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()

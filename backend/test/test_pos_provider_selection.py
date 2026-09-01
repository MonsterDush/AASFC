from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.core.db import Base
from app.models.user import User
from app.models.venue import Venue
from app.models.venue_pos_integration_selection import VenuePOSIntegrationSelection
from app.services.integrations.pos_provider_selection import (
    POSProviderSelectionError,
    acquire_pos_provider,
    active_pos_provider,
    release_pos_provider,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


class POSProviderSelectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(
            self.engine,
            tables=[
                User.__table__,
                Venue.__table__,
                VenuePOSIntegrationSelection.__table__,
            ],
        )
        self.db = Session(self.engine)
        self.db.add(User(id=1, system_role="NONE"))
        self.db.add(Venue(id=1, name="POS selection test"))
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        self.engine.dispose()

    def test_only_one_pos_provider_can_be_active_for_a_venue(self):
        acquire_pos_provider(self.db, venue_id=1, provider="QUICKRESTO")
        self.assertEqual(active_pos_provider(self.db, venue_id=1), "QUICKRESTO")

        with self.assertRaisesRegex(POSProviderSelectionError, "другая POS-интеграция"):
            acquire_pos_provider(self.db, venue_id=1, provider="IIKO")

        self.assertTrue(release_pos_provider(self.db, venue_id=1, provider="QUICKRESTO"))
        acquire_pos_provider(self.db, venue_id=1, provider="IIKO")
        self.assertEqual(active_pos_provider(self.db, venue_id=1), "IIKO")

    def test_disabling_another_provider_does_not_release_current_selection(self):
        acquire_pos_provider(self.db, venue_id=1, provider="QUICKRESTO")

        self.assertFalse(release_pos_provider(self.db, venue_id=1, provider="IIKO"))
        self.assertEqual(active_pos_provider(self.db, venue_id=1), "QUICKRESTO")


if __name__ == "__main__":
    unittest.main()

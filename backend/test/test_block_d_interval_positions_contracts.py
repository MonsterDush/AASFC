from __future__ import annotations

from pathlib import Path
from unittest import TestCase


REPO_DIR = Path(__file__).resolve().parents[2]


def read(rel: str) -> str:
    return (REPO_DIR / rel).read_text(encoding="utf-8")


class BlockDIntervalPositionContractTests(TestCase):
    def test_shift_interval_has_nullable_position_fk_and_migration(self):
        model = read("backend/app/models/shift_interval.py")
        migration = read("backend/alembic/versions/f6b4d2a8c1e0_shift_interval_positions.py")

        self.assertIn("position_id: Mapped[int | None]", model)
        self.assertIn('ForeignKey("venue_positions.id", ondelete="SET NULL")', model)
        self.assertIn('down_revision: Union[str, Sequence[str], None] = "a7d3e5f1c9b2"', migration)
        self.assertIn('batch_op.add_column(sa.Column("position_id", sa.Integer(), nullable=True))', migration)

    def test_shift_interval_api_contract_accepts_and_returns_position(self):
        schemas = read("backend/app/schemas/venue_shifts.py")
        router = read("backend/app/routers/venue_shift_intervals.py")

        self.assertGreaterEqual(schemas.count("position_id: int | None = Field(default=None, gt=0)"), 2)
        self.assertIn("position_id: int | None = Query(default=None, gt=0)", router)
        self.assertIn('"position_title"', router)
        self.assertIn("ShiftInterval.position_id.is_(None)", router)

    def test_catalog_position_is_not_consumed_by_employee_assignment(self):
        positions = read("backend/app/routers/venue_positions.py")
        invites = read("backend/app/services/invites.py")

        self.assertIn("A catalog row (member_user_id=NULL) is stable", positions)
        self.assertIn('"created_catalog"', positions)
        self.assertIn("catalog_position = None", invites)
        self.assertIn("member_user_id=user_id", invites)
        self.assertIn("member_user_id=None", invites)

    def test_schedule_rejects_wrong_position_and_frontend_filters_candidates(self):
        backend = read("backend/app/routers/venue_shifts.py")
        frontend = read("frontend/staff-shifts.js")

        self.assertIn("Должность не подходит для интервала этой смены", backend)
        self.assertIn("_require_shift_position_match(", backend)
        self.assertIn("Нет сотрудников с подходящей должностью", frontend)
        self.assertIn("positionTitleKey(position?.title) === positionTitleKey(requiredPositionTitle)", frontend)

    def test_setup_presets_materialize_real_catalog_positions(self):
        setup = read("frontend/owner-setup.js")
        invite_editor = read("frontend/owner-setup/invite-editor.js")
        position_domain = read("frontend/positions/position-domain.js")
        preset_schema = read("backend/app/schemas/venue_payroll.py")

        self.assertIn("venue_position_id:", setup)
        self.assertIn('method: "POST"', setup)
        self.assertIn("/positions", setup)
        self.assertIn("venue_position_id: selectedPreset.venue_position_id || null", invite_editor)
        self.assertIn("const venue_position_id = Number(", position_domain)
        self.assertIn("venue_position_id,", position_domain)
        self.assertIn("venue_position_id: int | None = None", preset_schema)

    def test_interval_editors_and_localization_include_position(self):
        standalone = read("frontend/shift-intervals.js")
        setup_editor = read("frontend/owner-setup/shift-interval-editor.js")
        locale = read("frontend/locales/en.json")

        self.assertIn('id="f_position"', standalone)
        self.assertIn('id="intervalPosition"', setup_editor)
        self.assertIn('"Все должности": "All roles"', locale)
        self.assertIn(
            '"Нет сотрудников с подходящей должностью": "No employees with a matching role"',
            locale,
        )


if __name__ == "__main__":
    import unittest

    unittest.main()

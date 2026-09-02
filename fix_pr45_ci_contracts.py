#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import re
import sys

ROOT = Path.cwd()

FRONTEND_TEST = ROOT / "backend/test/test_frontend_split_contracts.py"
SCOPE_TEST = ROOT / "backend/test/test_quickresto_scope.py"
ROUTER_TEST = ROOT / "backend/test/test_venue_economics_router.py"


def load(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"Файл не найден: {path}")
    return path.read_text(encoding="utf-8")


def save(path: Path, before: str, after: str) -> None:
    if before == after:
        print(f"= {path}: изменений не требуется")
        return
    path.write_text(after, encoding="utf-8")
    print(f"+ {path}: обновлён")


def fix_frontend_contract() -> None:
    path = FRONTEND_TEST
    before = load(path)
    text = before

    text = text.replace(
        '        self.assertIn("20260902-scopereconcile1", issues_html)\n',
        '        self.assertIn("20260902-scopegeneration1", issues_html)\n'
        '        self.assertIn("20260902-scopepreview1", issues_html)\n',
    )

    if 'self.assertIn("20260902-scopegeneration1", issues_html)' not in text:
        anchor = '        self.assertIn("/owner-integration-issues.js", issues_html)\n'
        if anchor not in text:
            raise SystemExit(
                "Не удалось найти anchor owner-integration-issues.js "
                "в backend/test/test_frontend_split_contracts.py"
            )
        text = text.replace(
            anchor,
            anchor + '        self.assertIn("20260902-scopegeneration1", issues_html)\n',
            1,
        )

    if 'self.assertIn("20260902-scopepreview1", issues_html)' not in text:
        anchor = '        self.assertIn("20260902-scopegeneration1", issues_html)\n'
        if anchor not in text:
            raise SystemExit("Не удалось добавить scopepreview1 в frontend contract")
        text = text.replace(
            anchor,
            anchor + '        self.assertIn("20260902-scopepreview1", issues_html)\n',
            1,
        )

    text = text.replace(
        '        self.assertIn("20260902-scopereconcile1", issues_html)\n',
        "",
    )

    save(path, before, text)


EXTERNAL_VENUE_TEST = """    def test_external_venue_change_after_import_is_staged_for_reconciliation(self):
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

        result = apply_quickresto_scope(
            self.db,
            connection=self.connection,
            external_venue_id=102,
            sale_place_ids=[203],
            store_ids=[403],
        )

        self.assertTrue(result["pending"])
        self.assertTrue(result["historical_reconciliation_required"])
        self.assertEqual(result["scope_status"], "PENDING_RECONCILIATION")
        self.assertEqual(result["scope_generation"], 2)
        self.assertEqual(result["active_scope_generation"], 1)

        self.assertEqual(self.connection.external_venue_id, 101)
        self.assertEqual(self.connection.scope_generation, 1)
        self.assertEqual(self.connection.pending_external_venue_id, 102)
        self.assertEqual(self.connection.pending_sale_place_ids_json, [203])
        self.assertEqual(self.connection.pending_store_ids_json, [403])
        self.assertEqual(self.connection.pending_scope_generation, 2)

        active_sale_places = set(
            self.db.execute(
                select(QuickRestoSalePlaceScope.external_id).where(
                    QuickRestoSalePlaceScope.connection_id == self.connection.id,
                    QuickRestoSalePlaceScope.is_selected.is_(True),
                )
            ).scalars()
        )
        self.assertEqual(active_sale_places, {201})

"""

SALE_PLACE_TEST = """    def test_sale_place_scope_change_after_import_is_staged_for_reconciliation(self):
        refresh_quickresto_catalog(self.db, connection=self.connection, client=self.client)
        apply_quickresto_scope(
            self.db,
            connection=self.connection,
            external_venue_id=101,
            sale_place_ids=[201, 202],
            store_ids=[401, 402],
        )
        self.db.add(
            QuickRestoShiftImport(
                connection_id=self.connection.id,
                external_shift_id="shift-sale-place-scope",
                external_shift_pk=2,
                source_version=1,
                business_date=date(2030, 1, 16),
                shift_slot="DAY",
                payload_hash="b" * 64,
                normalized_json={},
            )
        )
        self.db.flush()

        result = apply_quickresto_scope(
            self.db,
            connection=self.connection,
            external_venue_id=101,
            sale_place_ids=[201],
            store_ids=[401],
        )

        self.assertTrue(result["pending"])
        self.assertTrue(result["historical_reconciliation_required"])
        self.assertEqual(result["scope_status"], "PENDING_RECONCILIATION")
        self.assertEqual(result["scope_generation"], 2)
        self.assertEqual(result["active_scope_generation"], 1)

        self.assertEqual(self.connection.external_venue_id, 101)
        self.assertEqual(self.connection.scope_generation, 1)
        self.assertEqual(self.connection.pending_external_venue_id, 101)
        self.assertEqual(self.connection.pending_sale_place_ids_json, [201])
        self.assertEqual(self.connection.pending_store_ids_json, [401])
        self.assertEqual(self.connection.pending_scope_generation, 2)

        active_sale_places = set(
            self.db.execute(
                select(QuickRestoSalePlaceScope.external_id).where(
                    QuickRestoSalePlaceScope.connection_id == self.connection.id,
                    QuickRestoSalePlaceScope.is_selected.is_(True),
                )
            ).scalars()
        )
        active_stores = set(
            self.db.execute(
                select(QuickRestoStoreScope.external_id).where(
                    QuickRestoStoreScope.connection_id == self.connection.id,
                    QuickRestoStoreScope.is_selected.is_(True),
                )
            ).scalars()
        )
        self.assertEqual(active_sale_places, {201, 202})
        self.assertEqual(active_stores, {401, 402})

"""


def replace_test_method(text: str, old_names: tuple[str, ...], replacement: str) -> str:
    for name in old_names:
        pattern = re.compile(
            rf"(?ms)^    def {re.escape(name)}\(self\):\n.*?(?=^    def test_|\Z)"
        )
        match = pattern.search(text)
        if match:
            return text[: match.start()] + replacement + text[match.end() :]
    return text


def fix_scope_contracts() -> None:
    path = SCOPE_TEST
    before = load(path)
    text = before

    text = replace_test_method(
        text,
        (
            "test_external_venue_cannot_change_after_a_shift_was_imported",
            "test_external_venue_change_after_import_is_staged_for_reconciliation",
        ),
        EXTERNAL_VENUE_TEST,
    )
    if "def test_external_venue_change_after_import_is_staged_for_reconciliation" not in text:
        raise SystemExit("Не удалось найти/переписать тест смены external venue")

    text = replace_test_method(
        text,
        (
            "test_sale_place_scope_cannot_change_after_a_shift_was_imported",
            "test_sale_place_scope_change_after_import_is_staged_for_reconciliation",
        ),
        SALE_PLACE_TEST,
    )
    if "def test_sale_place_scope_change_after_import_is_staged_for_reconciliation" not in text:
        raise SystemExit("Не удалось найти/переписать тест изменения sale place scope")

    save(path, before, text)


def add_route_name(text: str, route_name: str) -> str:
    new_route_names_block = re.search(
        r'(?ms)        new_route_names = \{\n.*?^        \}\n',
        text,
    )
    if not new_route_names_block:
        raise SystemExit("Не найден блок new_route_names")

    block = new_route_names_block.group(0)
    if f'"{route_name}",' in block:
        return text

    marker = '            "put_quickresto_scope",\n'
    if marker not in block:
        raise SystemExit(f"Не найден put_quickresto_scope для {route_name}")

    new_block = block.replace(
        marker,
        marker + f'            "{route_name}",\n',
        1,
    )
    return text[: new_route_names_block.start()] + new_block + text[new_route_names_block.end() :]


def add_expected_route(text: str, route_name: str, path: str) -> str:
    expected_block = re.search(
        r'(?ms)        expected_new_routes = \{\n.*?^        \}\n',
        text,
    )
    if not expected_block:
        raise SystemExit("Не найден блок expected_new_routes")

    block = expected_block.group(0)
    expected_fragment = f'                "{path}",\n                "{route_name}",\n'
    if expected_fragment in block:
        return text

    marker = """            (
                ("PUT",),
                "/venues/{venue_id}/integrations/quickresto/scope",
                "put_quickresto_scope",
            ),
"""
    if marker not in block:
        raise SystemExit(f"Не найден expected route anchor для {route_name}")

    addition = f"""            (
                ("POST",),
                "{path}",
                "{route_name}",
            ),
"""
    new_block = block.replace(marker, marker + addition, 1)
    return text[: expected_block.start()] + new_block + text[expected_block.end() :]


def fix_router_contracts() -> None:
    path = ROUTER_TEST
    before = load(path)
    text = before

    text = add_route_name(text, "post_quickresto_historical_scope_preview")
    text = add_route_name(text, "post_quickresto_historical_scope_reconcile")

    text = add_expected_route(
        text,
        "post_quickresto_historical_scope_preview",
        "/venues/{venue_id}/integrations/quickresto/issues/{issue_id}/reconcile-scope/preview",
    )
    text = add_expected_route(
        text,
        "post_quickresto_historical_scope_reconcile",
        "/venues/{venue_id}/integrations/quickresto/issues/{issue_id}/reconcile-scope",
    )

    text = re.sub(
        r"self\.assertEqual\(len\(manifest\),\s*178\)",
        "self.assertEqual(len(manifest), 180)",
        text,
        count=1,
    )
    if "self.assertEqual(len(manifest), 180)" not in text:
        raise SystemExit("Не удалось обновить общий manifest count до 180")

    text = re.sub(
        r"\(venue_quickresto\.router,\s*(?:13|14)\)",
        "(venue_quickresto.router, 15)",
        text,
        count=1,
    )
    if "(venue_quickresto.router, 15)" not in text:
        raise SystemExit("Не удалось обновить QuickResto router count до 15")

    text = re.sub(
        r"self\.assertEqual\(len\(native_manifest\),\s*111\)",
        "self.assertEqual(len(native_manifest), 112)",
        text,
        count=1,
    )
    if "self.assertEqual(len(native_manifest), 112)" not in text:
        raise SystemExit("Не удалось обновить native manifest count до 112")

    save(path, before, text)


def main() -> None:
    missing = [
        str(path)
        for path in (FRONTEND_TEST, SCOPE_TEST, ROUTER_TEST)
        if not path.exists()
    ]
    if missing:
        print("Запусти этот файл из корня репозитория AASFC.", file=sys.stderr)
        for path in missing:
            print(f"- не найден {path}", file=sys.stderr)
        raise SystemExit(2)

    fix_frontend_contract()
    fix_scope_contracts()
    fix_router_contracts()

    print("\nГотово.")
    print("Проверь:")
    print("  git diff --check")
    print(
        "  git diff -- backend/test/test_frontend_split_contracts.py "
        "backend/test/test_quickresto_scope.py "
        "backend/test/test_venue_economics_router.py"
    )


if __name__ == "__main__":
    main()

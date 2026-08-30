from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from app.services.integrations import credentials
from app.services.integrations.quickresto import (
    QuickRestoAuthenticationError,
    QuickRestoClient,
    QuickRestoConfig,
    QuickRestoError,
)
from app.services.integrations.quickresto_normalize import (
    QuickRestoDataError,
    aggregate_normalized_shifts,
    business_date_for_shift,
    normalize_closed_shift,
    shift_slot_for_shift,
    stable_payload_hash,
)


class QuickRestoCredentialTests(unittest.TestCase):
    def test_credentials_round_trip_without_storing_plaintext(self):
        with (
            patch.object(credentials.settings, "INTEGRATION_ENCRYPTION_KEY", "k" * 48),
            patch.object(credentials.settings, "JWT_SECRET", "j" * 48),
        ):
            encrypted = credentials.encrypt_credential("qr-secret-value")

            self.assertTrue(encrypted.startswith("v1:"))
            self.assertNotIn("qr-secret-value", encrypted)
            self.assertEqual(credentials.decrypt_credential(encrypted), "qr-secret-value")

    def test_credentials_cannot_be_decrypted_with_another_key(self):
        with patch.object(credentials.settings, "INTEGRATION_ENCRYPTION_KEY", "a" * 48):
            encrypted = credentials.encrypt_credential("qr-secret-value")

        with (
            patch.object(credentials.settings, "INTEGRATION_ENCRYPTION_KEY", "b" * 48),
            self.assertRaises(credentials.IntegrationCredentialError),
        ):
            credentials.decrypt_credential(encrypted)


class QuickRestoClientTests(unittest.TestCase):
    def test_config_accepts_plain_cloud_and_rejects_urls(self):
        config = QuickRestoConfig(cloud="UK353", login="api-user", password="secret")
        self.assertEqual(config.cloud, "uk353")
        self.assertEqual(config.base_url, "https://uk353.quickresto.ru/platform/online")

        for invalid in ("", "https://uk353.quickresto.ru", "uk353.quickresto.ru", "../uk353", "uk353/path"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                QuickRestoConfig(cloud=invalid, login="api-user", password="secret")

    def test_list_uses_only_get_without_redirects(self):
        response = Mock(status_code=200)
        response.json.return_value = [{"id": 7, "status": "CLOSED"}]
        session = Mock()
        session.headers = {}
        session.get.return_value = response
        client = QuickRestoClient(QuickRestoConfig(cloud="uk353", login="api-user", password="secret"), session=session)

        result = client.list_objects(module_name="front.zreport", class_name="example.Shift", limit=25)

        self.assertEqual(result, [{"id": 7, "status": "CLOSED"}])
        session.get.assert_called_once_with(
            "https://uk353.quickresto.ru/platform/online/api/list",
            params={"moduleName": "front.zreport", "className": "example.Shift"},
            json={"limit": 25, "offset": 0},
            timeout=20.0,
            allow_redirects=False,
        )
        self.assertEqual(session.auth, ("api-user", "secret"))

    def test_auth_redirect_and_invalid_json_fail_safely(self):
        cases = [
            (401, QuickRestoAuthenticationError),
            (302, QuickRestoError),
            (429, QuickRestoError),
            (500, QuickRestoError),
        ]
        for status_code, expected_error in cases:
            with self.subTest(status_code=status_code):
                response = Mock(status_code=status_code)
                session = Mock()
                session.headers = {}
                session.get.return_value = response
                client = QuickRestoClient(
                    QuickRestoConfig(cloud="uk353", login="api-user", password="secret"), session=session
                )
                with self.assertRaises(expected_error):
                    client.list_objects(module_name="front.zreport", class_name="example.Shift")

        response = Mock(status_code=200)
        response.json.side_effect = ValueError("bad json")
        session = Mock()
        session.headers = {}
        session.get.return_value = response
        client = QuickRestoClient(QuickRestoConfig(cloud="uk353", login="api-user", password="secret"), session=session)
        with self.assertRaisesRegex(QuickRestoError, "invalid JSON"):
            client.list_objects(module_name="front.zreport", class_name="example.Shift")

    def test_unexpected_list_shape_is_rejected(self):
        response = Mock(status_code=200)
        response.json.return_value = {"items": []}
        session = Mock()
        session.headers = {}
        session.get.return_value = response
        client = QuickRestoClient(QuickRestoConfig(cloud="uk353", login="api-user", password="secret"), session=session)

        with self.assertRaisesRegex(QuickRestoError, "unexpected shape"):
            client.list_objects(module_name="front.zreport", class_name="example.Shift")

    def test_network_error_is_wrapped_without_request_details(self):
        session = Mock()
        session.headers = {}
        session.get.side_effect = __import__("requests").ConnectionError("sensitive request context")
        client = QuickRestoClient(QuickRestoConfig(cloud="uk353", login="api-user", password="secret"), session=session)

        with self.assertRaisesRegex(QuickRestoError, "before receiving a response") as raised:
            client.list_objects(module_name="front.zreport", class_name="example.Shift")
        self.assertNotIn("sensitive", str(raised.exception))

    def test_list_all_paginates_until_short_page(self):
        response_one = Mock(status_code=200)
        response_one.json.return_value = [{"id": 1}, {"id": 2}]
        response_two = Mock(status_code=200)
        response_two.json.return_value = [{"id": 3}]
        session = Mock()
        session.headers = {}
        session.get.side_effect = [response_one, response_two]
        client = QuickRestoClient(QuickRestoConfig(cloud="uk353", login="api-user", password="secret"), session=session)

        result = client.list_all_objects(
            module_name="front.orders",
            class_name="example.OrderInfo",
            page_size=2,
        )

        self.assertEqual(result, [{"id": 1}, {"id": 2}, {"id": 3}])
        self.assertEqual(session.get.call_count, 2)
        self.assertEqual(session.get.call_args_list[0].kwargs["json"], {"limit": 2, "offset": 0})
        self.assertEqual(session.get.call_args_list[1].kwargs["json"], {"limit": 2, "offset": 2})


class QuickRestoFixtureContractTests(unittest.TestCase):
    def test_closed_shift_fixture_reconciles_payments_and_departments(self):
        fixture_path = Path(__file__).parent / "fixtures" / "quickresto" / "basic_closed_shift.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        shift = fixture["shift"]
        orders = fixture["orders"]

        self.assertEqual(shift["status"], "CLOSED")
        self.assertEqual(len(orders), shift["ordersCount"])
        self.assertTrue(all(order["shiftId"] == shift["frontId"] for order in orders))

        shift_total = shift["totalCash"] + shift["totalCard"] + shift["totalBonuses"]
        order_total = sum(order["frontTotalPrice"] for order in orders)
        payment_total = sum(payment["amount"] for order in orders for payment in order["payments"])
        self.assertEqual(order_total, shift_total)
        self.assertEqual(payment_total, shift_total)

        department_totals: dict[int, float] = {}
        for order in orders:
            for item in order["orderItemList"]:
                department_id = int(item["product"]["parentId"])
                department_totals[department_id] = department_totals.get(department_id, 0.0) + float(item["totalPrice"])
        self.assertEqual(department_totals, {6: 6000.0, 7: 900.0})
        self.assertEqual(sum(department_totals.values()), shift_total)

    def test_same_day_shifts_reconcile_mixed_payments_bonus_and_discount(self):
        fixture_path = Path(__file__).parent / "fixtures" / "quickresto" / "complex_same_day_shifts.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        shifts = fixture["shifts"]
        orders = fixture["orders"]

        self.assertEqual({shift["status"] for shift in shifts}, {"CLOSED"})
        self.assertEqual(
            {shift["localClosedTime"][:10] for shift in shifts},
            {fixture["report_date"]},
        )
        self.assertEqual(sum(shift["ordersCount"] for shift in shifts), len(orders))

        orders_by_shift: dict[str, list[dict]] = {}
        for order in orders:
            orders_by_shift.setdefault(order["shiftId"], []).append(order)
        for shift in shifts:
            shift_orders = orders_by_shift[shift["frontId"]]
            shift_revenue_payment_total = sum(
                payment["amount"]
                for order in shift_orders
                for payment in order["payments"]
                if payment["paymentType"]["operationType"] != "writeoff"
            )
            shift_writeoff_total = sum(
                payment["amount"]
                for order in shift_orders
                for payment in order["payments"]
                if payment["paymentType"]["operationType"] == "writeoff"
            )
            shift_sales_total = sum(
                shift[key]
                for key in (
                    "totalCash",
                    "totalCard",
                    "totalBonuses",
                    "nonFiscalTotalCash",
                    "nonFiscalTotalCard",
                    "nonFiscalTotalBonuses",
                )
            )
            shift_return_total = sum(
                shift[key]
                for key in (
                    "totalReturnCash",
                    "totalReturnCard",
                    "totalReturnBonuses",
                    "nonFiscalTotalReturnCash",
                    "nonFiscalTotalReturnCard",
                    "nonFiscalTotalReturnBonuses",
                )
            )
            self.assertEqual(len(shift_orders), shift["ordersCount"])
            self.assertEqual(shift_revenue_payment_total, shift_sales_total - shift_return_total)
            self.assertEqual(
                shift_writeoff_total,
                shift["writeOffTotalCash"] + shift["writeOffTotalCard"] + shift["writeOffTotalBonuses"],
            )

        payment_totals: dict[int, float] = {}
        department_totals: dict[int, float] = {}
        for order in orders:
            self.assertFalse(order["returned"])
            self.assertEqual(sum(payment["amount"] for payment in order["payments"]), order["frontTotalPrice"])

            is_writeoff = all(payment["paymentType"]["operationType"] == "writeoff" for payment in order["payments"])
            line_net_total = 0.0
            for item in order["orderItemList"]:
                line_net = item["totalPrice"] - item["totalAbsoluteDiscount"] + item["totalAbsoluteCharge"]
                line_net_total += line_net
                if not is_writeoff:
                    department_id = int(item["product"]["parentId"])
                    department_totals[department_id] = department_totals.get(department_id, 0.0) + line_net
            self.assertEqual(line_net_total, order["frontTotalPrice"])

            for payment in order["payments"]:
                if payment["paymentType"]["operationType"] == "writeoff":
                    continue
                payment_type_id = int(payment["paymentType"]["id"])
                payment_totals[payment_type_id] = payment_totals.get(payment_type_id, 0.0) + float(payment["amount"])

        self.assertEqual(
            sum(
                order["frontTotalPrice"]
                for order in orders
                if all(payment["paymentType"]["operationType"] != "writeoff" for payment in order["payments"])
            ),
            23900.0,
        )
        self.assertEqual(sum(order["frontTotalAbsoluteDiscount"] for order in orders), 600.0)
        self.assertEqual(payment_totals, {1: 6600.0, 2: 16300.0, 3: 1000.0})
        self.assertEqual(department_totals, {6: 19400.0, 7: 4500.0})
        self.assertEqual(sum(payment_totals.values()), sum(department_totals.values()))
        self.assertEqual(sum(len(order["payments"]) > 1 for order in orders), 2)
        self.assertEqual(
            sum(
                shift["writeOffTotalCash"] + shift["writeOffTotalCard"] + shift["writeOffTotalBonuses"]
                for shift in shifts
            ),
            4600.0,
        )

    def test_normalizer_builds_axelio_day_and_excludes_writeoff(self):
        fixture_path = Path(__file__).parent / "fixtures" / "quickresto" / "complex_same_day_shifts.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        orders_by_shift: dict[str, list[dict]] = {}
        for order in fixture["orders"]:
            orders_by_shift.setdefault(order["shiftId"], []).append(order)

        normalized = [
            normalize_closed_shift(
                shift,
                orders_by_shift.get(shift["frontId"], []),
                cutoff_hour=0,
            )
            for shift in fixture["shifts"]
        ]
        aggregate = aggregate_normalized_shifts(normalized)

        self.assertEqual(aggregate["business_date"], "2026-08-27")
        self.assertEqual(aggregate["shift_slot"], "DAY")
        normalized_hash_basis = dict(normalized[0])
        normalized_hash = normalized_hash_basis.pop("payload_hash")
        normalized_hash_basis.pop("shift_slot")
        self.assertEqual(normalized_hash, stable_payload_hash(normalized_hash_basis))
        aggregate_hash_basis = dict(aggregate)
        aggregate_hash = aggregate_hash_basis.pop("aggregate_hash")
        aggregate_hash_basis.pop("shift_slot")
        self.assertEqual(aggregate_hash, stable_payload_hash(aggregate_hash_basis))
        self.assertEqual(aggregate["shift_count"], 3)
        self.assertEqual(aggregate["payments_external"], {"1": 6600, "2": 16300, "3": 1000})
        self.assertEqual(aggregate["departments_external"], {"6": 19400, "7": 4500})
        self.assertEqual(aggregate["revenue_total"], 23900)
        self.assertEqual(aggregate["writeoff_total"], 4600)
        self.assertEqual(aggregate["writeoff_departments_external"], {"6": 4000, "7": 600})
        self.assertEqual(aggregate["discount_total"], 600)

    def test_normalizer_uses_shift_net_counters_without_double_subtracting_return_order(self):
        shift_id = "shift-with-return"
        shift = {
            "id": 4,
            "version": 9,
            "frontId": shift_id,
            "status": "CLOSED",
            "localOpenedTime": "2026-08-28T14:00:00.000Z",
            "localClosedTime": "2026-08-28T15:42:13.000Z",
            "totalCash": 21_200.0,
            "totalCard": 5_200.0,
            "totalBonuses": 0.0,
            "totalReturnCash": 5_200.0,
            "totalReturnCard": 0.0,
            "totalReturnBonuses": 0.0,
            "nonFiscalTotalCash": 0.0,
            "nonFiscalTotalCard": 0.0,
            "nonFiscalTotalBonuses": 0.0,
            "nonFiscalTotalReturnCash": 0.0,
            "nonFiscalTotalReturnCard": 0.0,
            "nonFiscalTotalReturnBonuses": 0.0,
            "writeOffTotalCash": 0.0,
            "writeOffTotalCard": 0.0,
            "writeOffTotalBonuses": 0.0,
            "writeOffTotalReturnCash": 0.0,
            "writeOffTotalReturnCard": 0.0,
            "writeOffTotalReturnBonuses": 0.0,
        }

        def order(
            order_id: int,
            *,
            total: int,
            payment_type_id: int,
            departments: list[tuple[int, int]],
            returned: bool = False,
        ) -> dict:
            return {
                "id": order_id,
                "shiftId": shift_id,
                "returned": returned,
                "frontTotalPrice": float(total),
                "frontTotalAbsoluteDiscount": 0.0,
                "payments": [
                    {
                        "amount": float(total),
                        "paymentType": {"id": payment_type_id, "operationType": "fiscal"},
                    }
                ],
                "orderItemList": [
                    {
                        "totalPrice": float(value),
                        "totalAbsoluteDiscount": 0.0,
                        "totalAbsoluteCharge": 0.0,
                        "product": {"parentId": department_id},
                    }
                    for department_id, value in departments
                ],
            }

        orders = [
            order(11, total=16_000, payment_type_id=1, departments=[(6, 16_000)]),
            order(10, total=5_200, payment_type_id=2, departments=[(6, 4_000), (7, 1_200)]),
            order(
                9,
                total=5_200,
                payment_type_id=1,
                departments=[(6, 4_000), (7, 1_200)],
                returned=True,
            ),
        ]

        normalized = normalize_closed_shift(shift, orders, cutoff_hour=0)

        self.assertEqual(normalized["revenue_total"], 21_200)
        self.assertEqual(normalized["payments_external"], {"1": 16_000, "2": 5_200})
        self.assertEqual(normalized["departments_external"], {"6": 20_000, "7": 1_200})
        self.assertEqual(normalized["orders_count"], 2)
        self.assertEqual(normalized["returned_orders_count"], 1)

    def test_business_day_uses_opening_time_when_shift_closes_next_day(self):
        shift = {
            "status": "CLOSED",
            "localOpenedTime": "2026-08-26T20:00:00.000Z",
            "localClosedTime": "2026-08-27T03:15:00.000Z",
        }

        self.assertEqual(business_date_for_shift(shift, cutoff_hour=0).isoformat(), "2026-08-26")

    def test_business_day_cutoff_keeps_reopened_night_shift_on_original_day(self):
        shift = {
            "status": "CLOSED",
            "localOpenedTime": "2026-08-27T03:15:00.000Z",
            "localClosedTime": "2026-08-27T11:00:00.000Z",
        }

        self.assertEqual(business_date_for_shift(shift, cutoff_hour=0).isoformat(), "2026-08-27")
        self.assertEqual(business_date_for_shift(shift, cutoff_hour=6).isoformat(), "2026-08-26")

    def test_shift_slot_defaults_to_day_when_split_is_disabled(self):
        for opened_at in (
            "2026-08-27T00:00:00.000Z",
            "2026-08-27T03:15:00.000Z",
            "2026-08-27T23:59:00.000Z",
        ):
            with self.subTest(opened_at=opened_at):
                self.assertEqual(
                    shift_slot_for_shift(
                        {"localOpenedTime": opened_at},
                        cutoff_hour=6,
                        night_shift_split_enabled=False,
                        night_shift_start_hour=22,
                    ),
                    "DAY",
                )

    def test_shift_slot_uses_configured_opening_windows(self):
        cases = (
            ("2026-08-27T05:59:00.000Z", "NIGHT", "2026-08-26"),
            ("2026-08-27T06:00:00.000Z", "DAY", "2026-08-27"),
            ("2026-08-27T21:59:00.000Z", "DAY", "2026-08-27"),
            ("2026-08-27T22:00:00.000Z", "NIGHT", "2026-08-27"),
        )
        for opened_at, expected_slot, expected_date in cases:
            shift = {"localOpenedTime": opened_at}
            with self.subTest(opened_at=opened_at):
                self.assertEqual(
                    shift_slot_for_shift(
                        shift,
                        cutoff_hour=6,
                        night_shift_split_enabled=True,
                        night_shift_start_hour=22,
                    ),
                    expected_slot,
                )
                self.assertEqual(business_date_for_shift(shift, cutoff_hour=6).isoformat(), expected_date)

    def test_aggregate_rejects_day_and_night_rows_together(self):
        base = {
            "business_date": "2026-08-27",
            "external_shift_id": "day",
            "shift_slot": "DAY",
        }
        night = {**base, "external_shift_id": "night", "shift_slot": "NIGHT"}

        with self.assertRaisesRegex(QuickRestoDataError, "day and night"):
            aggregate_normalized_shifts([base, night])


if __name__ == "__main__":
    unittest.main()

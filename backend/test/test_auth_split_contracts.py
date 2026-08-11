from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException

from app import main
from app.routers import auth, auth_common, auth_demo, auth_phone, auth_schemas, auth_telegram


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ROUTERS_DIR = PROJECT_ROOT / "backend" / "app" / "routers"
EXPECTED_AUTH_ROUTE_MANIFEST_SHA256 = "b83f1dfa02554a396c3dd1fa6b9f019da82bca47c3efacf3528dcfefbebfe4ab"
EXPECTED_AUTH_OPENAPI_SHA256 = "43f936ede98ad94d22560f1871cc8345c36a1c551253404fb484c2e5d1e7b39d"


def _effective_routes(router):
    for route in router.routes:
        effective_contexts = getattr(route, "effective_route_contexts", None)
        if callable(effective_contexts):
            yield from effective_contexts()
        else:
            yield route


def _route_manifest(router) -> list[dict]:
    return [
        {
            "methods": sorted(route.methods),
            "path": route.path,
            "name": route.name,
            "status": route.status_code,
            "response_model": getattr(getattr(route, "response_model", None), "__name__", None),
        }
        for route in _effective_routes(router)
    ]


class AuthRouterSplitContractTests(TestCase):
    def test_facade_preserves_original_route_manifest(self):
        manifest = _route_manifest(auth.router)
        digest = hashlib.sha256(
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(len(manifest), 31)
        self.assertEqual(digest, EXPECTED_AUTH_ROUTE_MANIFEST_SHA256)

    def test_facade_preserves_auth_openapi_contract(self):
        app = FastAPI()
        app.include_router(auth.router)
        schema = app.openapi()
        digest = hashlib.sha256(
            json.dumps(
                schema,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

        self.assertEqual(len(schema["paths"]), 31)
        self.assertEqual(len(schema["components"]["schemas"]), 19)
        self.assertEqual(digest, EXPECTED_AUTH_OPENAPI_SHA256)

    def test_domain_routers_partition_facade_in_original_order(self):
        child_routers = [
            (auth_telegram.router, 8),
            (auth_phone.router, 12),
            (auth_demo.router, 4),
            (auth_phone.link_router, 3),
            (auth_telegram.link_router, 4),
        ]
        aggregated = []
        for child_router, expected_count in child_routers:
            child_manifest = _route_manifest(child_router)
            self.assertEqual(len(child_manifest), expected_count)
            for route in child_manifest:
                aggregated.append({**route, "path": f"/auth{route['path']}"})

        self.assertEqual(aggregated, _route_manifest(auth.router))

    def test_facade_reexports_schemas_handlers_and_legacy_processor(self):
        self.assertIs(auth.AuthStateOut, auth_schemas.AuthStateOut)
        self.assertIs(auth.password_login, auth_phone.password_login)
        self.assertIs(auth.start_demo_session, auth_demo.start_demo_session)
        self.assertIs(auth.auth_telegram, auth_telegram.auth_telegram)
        self.assertIs(
            auth.process_telegram_browser_webhook_request,
            auth_telegram.process_telegram_browser_webhook_request,
        )

    def test_modules_remain_bounded(self):
        limits = {
            "auth.py": 150,
            "auth_schemas.py": 180,
            "auth_common.py": 320,
            "auth_phone.py": 500,
            "auth_demo.py": 200,
            "auth_telegram.py": 750,
        }
        for filename, line_limit in limits.items():
            source = (ROUTERS_DIR / filename).read_text(encoding="utf-8")
            self.assertLess(len(source.splitlines()), line_limit)

    def test_canonical_and_legacy_webhook_routes_are_registered(self):
        routes = {
            (method, route.path, route.name)
            for route in _effective_routes(main.app.router)
            for method in getattr(route, "methods", set())
        }
        self.assertIn(("POST", "/auth/telegram/browser/webhook", "telegram_browser_webhook"), routes)
        self.assertIn(("POST", "/telegram/webhook", "telegram_browser_webhook_legacy_alias"), routes)
        self.assertIn(("POST", "/webhook", "telegram_browser_webhook_legacy_alias"), routes)

    def test_shared_path_normalization_keeps_redirect_safety_rules(self):
        self.assertIsNone(auth_common._normalize_next_path("https://example.com/escape"))
        self.assertIsNone(auth_common._normalize_next_path("http://example.com/escape"))
        self.assertEqual(auth_common._normalize_next_path("venues/7"), "/venues/7")
        self.assertEqual(auth_common._normalize_next_path("/auth.html?next=/venues"), "/")


class TelegramWebhookProcessorTests(IsolatedAsyncioTestCase):
    async def test_rejects_invalid_secret_before_reading_payload(self):
        request = SimpleNamespace(json=AsyncMock())

        with patch.object(auth_telegram.settings, "TG_WEBHOOK_SECRET_TOKEN", "expected"):
            with self.assertRaises(HTTPException) as raised:
                await auth_telegram.process_telegram_browser_webhook_request(
                    request,
                    x_telegram_bot_api_secret_token="wrong",
                    db=object(),
                )

        self.assertEqual(raised.exception.status_code, 401)
        request.json.assert_not_awaited()

    async def test_dispatches_message_and_callback_updates(self):
        db = object()
        telegram_user = {"id": 17, "username": "axelio_user"}
        message_request = SimpleNamespace(
            json=AsyncMock(
                return_value={
                    "message": {
                        "text": "/start browser_login_token",
                        "from": telegram_user,
                    }
                }
            )
        )
        callback = {"data": "browser_login:token", "from": telegram_user}
        callback_request = SimpleNamespace(json=AsyncMock(return_value={"callback_query": callback}))

        with patch.object(auth_telegram.settings, "TG_WEBHOOK_SECRET_TOKEN", ""), \
             patch.object(auth_telegram, "_handle_browser_login_start_message") as handle_message, \
             patch.object(auth_telegram, "_handle_browser_login_callback") as handle_callback:
            await auth_telegram.process_telegram_browser_webhook_request(
                message_request,
                x_telegram_bot_api_secret_token=None,
                db=db,
            )
            await auth_telegram.process_telegram_browser_webhook_request(
                callback_request,
                x_telegram_bot_api_secret_token=None,
                db=db,
            )

        handle_message.assert_called_once_with(
            db,
            text="/start browser_login_token",
            from_user=telegram_user,
        )
        handle_callback.assert_called_once_with(db, callback_query=callback)

    async def test_canonical_and_legacy_handlers_delegate_to_shared_processor(self):
        request = object()
        db = object()

        with patch.object(
            auth_telegram,
            "process_telegram_browser_webhook_request",
            new_callable=AsyncMock,
        ) as canonical_processor:
            result = await auth_telegram.telegram_browser_webhook(
                request,
                x_telegram_bot_api_secret_token="secret",
                db=db,
            )

        self.assertIsNone(result)
        canonical_processor.assert_awaited_once_with(
            request,
            x_telegram_bot_api_secret_token="secret",
            db=db,
        )

        with patch.object(
            auth,
            "process_telegram_browser_webhook_request",
            new_callable=AsyncMock,
        ) as legacy_processor:
            result = await main.telegram_browser_webhook_legacy_alias(
                request,
                x_telegram_bot_api_secret_token="secret",
                db=db,
            )

        self.assertIsNone(result)
        legacy_processor.assert_awaited_once_with(
            request,
            x_telegram_bot_api_secret_token="secret",
            db=db,
        )

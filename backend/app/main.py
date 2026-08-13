from fastapi import Depends, FastAPI, Header, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text

from app.auth.jwt_tokens import JwtConfig, decode_access_token
from app.core.config import settings
from app.core.db import get_db
from app.core.observability import configure_logging, init_error_tracking, observe_request
from app.core.metrics import render_prometheus
from app.core.request_ip import resolve_client_ip
from app.core.security_headers import apply_security_headers
from app.services.demo import build_demo_readonly_error_payload, is_demo_session_payload, should_block_demo_request
from sqlalchemy.orm import Session


def _jwt_config() -> JwtConfig:
    return JwtConfig(
        secret=settings.JWT_SECRET,
        issuer=settings.JWT_ISS,
        audience=settings.JWT_AUD,
        ttl_seconds=settings.ACCESS_TOKEN_TTL_SECONDS,
    )


def _has_demo_session_cookie(request: Request) -> bool:
    access_token = request.cookies.get("access_token")
    if not access_token:
        return False
    try:
        payload = decode_access_token(_jwt_config(), access_token)
    except Exception:
        return False
    return is_demo_session_payload(payload)


def _fastapi_options() -> dict[str, str | None]:
    if settings.is_production():
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}


configure_logging()
init_error_tracking()

app = FastAPI(title="Axelio API", **_fastapi_options())
from app.routers.venues import router as venues_router
from app.routers.public_invites import router as public_invites_router
from app.routers.public_leads import router as public_leads_router
from app.routers.billing import router as billing_router, public_router as billing_public_router
from app.routers.admin_billing import router as admin_billing_router
from app.routers.admin_demo import router as admin_demo_router
from app.routers.demo_telemetry import router as demo_telemetry_router
from app.routers.setup import router as setup_router
from app.routers.position_permission_templates import (
    router as position_permission_templates_router,
    public_router as position_permission_templates_public_router,
)
from app.routers import auth, me


@app.middleware("http")
async def demo_readonly_guard(request: Request, call_next):
    if should_block_demo_request(
        method=request.method,
        path=request.url.path,
        is_demo_session=_has_demo_session_cookie(request),
    ):
        return JSONResponse(status_code=403, content=build_demo_readonly_error_payload())
    return await call_next(request)


@app.middleware("http")
async def request_observability(request: Request, call_next):
    return await observe_request(request, call_next)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    return apply_security_headers(response, production=settings.is_production())


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-ID"],
)


app.include_router(auth.router)
app.include_router(me.router)
app.include_router(venues_router)
app.include_router(public_invites_router)
app.include_router(public_leads_router)
app.include_router(setup_router)
app.include_router(position_permission_templates_public_router)
app.include_router(position_permission_templates_router)
app.include_router(billing_router)
app.include_router(billing_public_router)
app.include_router(admin_billing_router)
app.include_router(admin_demo_router)
app.include_router(demo_telemetry_router)


@app.post("/telegram/webhook", status_code=status.HTTP_204_NO_CONTENT)
@app.post("/webhook", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_browser_webhook_legacy_alias(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    """Legacy Telegram webhook aliases for browser auth.

    Older deploy notes used /telegram/webhook, while the current canonical
    endpoint is /auth/telegram/browser/webhook. Keep both so Telegram browser
    login works even if the webhook URL was configured by the old runbook.
    """
    await auth.process_telegram_browser_webhook_request(
        request,
        x_telegram_bot_api_secret_token=x_telegram_bot_api_secret_token,
        db=db,
    )
    return None


@app.get("/health")
def health():
    return {
        "status": "ok",
        "environment": str(settings.APP_ENV or "development"),
        "release": settings.release_version(),
    }


@app.get("/health/ready")
def readiness(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "database": "ok",
        "environment": str(settings.APP_ENV or "development"),
        "release": settings.release_version(),
    }


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request, db: Session = Depends(get_db)):
    client_ip = resolve_client_ip(request)
    configured_token = str(settings.METRICS_TOKEN or "").strip()
    supplied_token = str(request.headers.get("X-Metrics-Token") or "").strip()
    authorization = str(request.headers.get("Authorization") or "").strip()
    bearer_token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    is_loopback = client_ip in {"127.0.0.1", "::1"}
    if not is_loopback and (not configured_token or configured_token not in {supplied_token, bearer_token}):
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return PlainTextResponse(render_prometheus(db), media_type="text/plain; version=0.0.4")


@app.get("/version")
def version():
    return {
        "environment": str(settings.APP_ENV or "development"),
        "release": settings.release_version(),
    }

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.auth.jwt_tokens import JwtConfig, decode_access_token
from app.core.config import settings
from app.services.demo import build_demo_readonly_error_payload, is_demo_session_payload, should_block_demo_request


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

app = FastAPI(title="Axelio API")
from app.routers.venues import router as venues_router
from app.routers.public_invites import router as public_invites_router
from app.routers.public_leads import router as public_leads_router
from app.routers.billing import router as billing_router, public_router as billing_public_router
from app.routers.admin_billing import router as admin_billing_router
from app.routers import auth, me

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allow_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)


@app.middleware("http")
async def demo_readonly_guard(request: Request, call_next):
    if should_block_demo_request(
        method=request.method,
        path=request.url.path,
        is_demo_session=_has_demo_session_cookie(request),
    ):
        return JSONResponse(status_code=403, content=build_demo_readonly_error_payload())
    return await call_next(request)


app.include_router(auth.router)
app.include_router(me.router)
app.include_router(venues_router)
app.include_router(public_invites_router)
app.include_router(public_leads_router)
app.include_router(billing_router)
app.include_router(billing_public_router)
app.include_router(admin_billing_router)

@app.get("/health")
def health():
    return {"status": "ok"}

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings

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

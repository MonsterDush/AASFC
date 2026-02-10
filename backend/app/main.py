from fastapi import FastAPI

app = FastAPI(title="Axelio API")

from fastapi.middleware.cors import CORSMiddleware
from app.routers.venues import router as venues_router
from app.routers import auth, me

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app-dev.axelio.ru",
        "https://web.telegram.org",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(me.router)
app.include_router(venues_router)

@app.get("/health")
def health():
    return {"status": "ok"}


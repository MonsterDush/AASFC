from fastapi import FastAPI

app = FastAPI(title="Axelio API")

from fastapi.middleware.cors import CORSMiddleware

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
from app.routers import auth, me

app.include_router(auth.router)
app.include_router(me.router)

@app.get("/health")
def health():
    return {"status": "ok"}


from fastapi import FastAPI

app = FastAPI(title="Axelio API")

@app.get("/health")
def health():
    return {"status": "ok"}


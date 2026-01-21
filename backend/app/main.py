from fastapi import FastAPI
from .api.routes_identify import router as identify_router

app = FastAPI(title="AI Shopping API", version="0.1.0")

app.include_router(identify_router)

@app.get("/health")
def health():
    return {"ok": True}

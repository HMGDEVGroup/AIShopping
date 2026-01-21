from fastapi import FastAPI
from app.api.routes_identify import router as identify_router
from app.api.routes_offers import router as offers_router

app = FastAPI(title="AI Shopping API", version="0.1.0")

app.include_router(identify_router)
app.include_router(offers_router)

@app.get("/health")
def health():
    return {"ok": True}

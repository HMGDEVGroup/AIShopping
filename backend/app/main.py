"""
AI Shopping API - FastAPI Main Entry

✅ LOCAL (MacBook):
    cd /Users/hmg/Desktop/AIShopping/backend
    source .venv/bin/activate
    python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

✅ TEST FROM THIS MACBOOK:
    curl -i http://127.0.0.1:8000/
    curl -i http://127.0.0.1:8000/docs
    curl -i http://127.0.0.1:8000/health
    curl -i http://127.0.0.1:8000/version

✅ TEST FROM IPHONE (same WiFi):
    Find Mac IP:
        ipconfig getifaddr en0

    Then on iPhone Safari:
        http://<MAC_IP>:8000/
        http://<MAC_IP>:8000/docs
        http://<MAC_IP>:8000/health
        http://<MAC_IP>:8000/version

✅ PRODUCTION (Render):
    Build Command:
        pip install -r requirements.txt

    Start Command:
        python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT

✅ Render URL Example:
    https://aishopping-1.onrender.com

✅ Production Tests:
    https://aishopping-1.onrender.com/
    https://aishopping-1.onrender.com/docs
    https://aishopping-1.onrender.com/health
    https://aishopping-1.onrender.com/version
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ✅ Routers
from app.api.routes_identify import router as identify_router
from app.api.routes_offers import router as offers_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI Shopping API",
        version="0.1.0",
        description="Backend API for AI Shopping iOS App (Identify + Offers)",
    )

    # ✅ CORS
    # NOTE:
    # - iPhone app does NOT require CORS
    # - BUT Safari / browser / Swagger docs can require it depending on tests
    # - This keeps dev + production smooth
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # You can lock this down later for production security
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ✅ Root (GET /)
    @app.get("/")
    def root():
        return {
            "name": "AI Shopping API",
            "status": "ok",
            "docs": "/docs",
            "health": "/health",
            "version": "/version",
        }

    # ✅ Health Check (GET /health)
    @app.get("/health")
    def health():
        return {"ok": True}

    # ✅ Version endpoint (GET /version)
    @app.get("/version")
    def version():
        return {"version": "0.1.0", "build": "costco-v1"}

    # ✅ Mount routers
    app.include_router(identify_router)
    app.include_router(offers_router)

    return app


app = create_app()

import httpx
from app.core.config import settings

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

async def shopping_search(query: str) -> dict:
    if not settings.SERPAPI_API_KEY:
        raise ValueError("SERPAPI_API_KEY is not set")

    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": settings.SERPAPI_API_KEY,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(SERPAPI_ENDPOINT, params=params)
        r.raise_for_status()
        return r.json()

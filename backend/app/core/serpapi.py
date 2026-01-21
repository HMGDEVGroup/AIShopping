import httpx
from app.core.config import settings

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"

async def google_shopping_search(query: str, num: int = 10, gl: str = "us", hl: str = "en") -> dict:
    if not settings.SERPAPI_API_KEY:
        raise ValueError("SERPAPI_API_KEY is not set")

    params = {
        "engine": "google_shopping",
        "q": query,
        "api_key": settings.SERPAPI_API_KEY,
        "num": num,
        "gl": gl,
        "hl": hl,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(SERPAPI_ENDPOINT, params=params)
        r.raise_for_status()
        return r.json()

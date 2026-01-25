# /Users/hmg/Desktop/AIShopping/backend/app/core/serpapi.py

from __future__ import annotations

from typing import Any, Dict, Optional
import httpx

from app.core.config import settings


SERPAPI_ENDPOINT = "https://serpapi.com/search.json"


async def shopping_search(q: str, num: int = 20) -> Dict[str, Any]:
    """
    Google Shopping via SerpAPI.
    Returns the full SerpAPI JSON response as a dict.
    """
    api_key = (settings.SERPAPI_API_KEY or "").strip()
    if not api_key:
        # Keep response shape consistent so callers don't crash
        return {"error": "SERPAPI_API_KEY is missing"}

    params = {
        "engine": "google_shopping",
        "q": q,
        "api_key": api_key,
        "num": int(num),
        "hl": "en",
        "gl": "us",
    }

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(SERPAPI_ENDPOINT, params=params)
        r.raise_for_status()
        data = r.json()

    # If SerpAPI returns an error field, pass it through for debugging
    if isinstance(data, dict) and data.get("error"):
        return data

    # Guarantee dict
    return data if isinstance(data, dict) else {"error": "Invalid SerpAPI response type"}


async def google_search(q: str, num: int = 10) -> Dict[str, Any]:
    """
    Optional: regular Google results via SerpAPI.
    Returns full SerpAPI JSON response as dict.
    """
    api_key = (settings.SERPAPI_API_KEY or "").strip()
    if not api_key:
        return {"error": "SERPAPI_API_KEY is missing"}

    params = {
        "engine": "google",
        "q": q,
        "api_key": api_key,
        "num": int(num),
        "hl": "en",
        "gl": "us",
    }

    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.get(SERPAPI_ENDPOINT, params=params)
        r.raise_for_status()
        data = r.json()

    return data if isinstance(data, dict) else {"error": "Invalid SerpAPI response type"}

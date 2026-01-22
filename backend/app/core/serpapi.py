import os
from typing import Any, Dict

import httpx

from app.core.config import settings

SERPAPI_BASE = "https://serpapi.com/search.json"


def _get_serpapi_key() -> str:
    key = (getattr(settings, "SERPAPI_API_KEY", "") or "").strip()
    if not key:
        key = (os.environ.get("SERPAPI_API_KEY", "") or "").strip()
    if not key:
        raise ValueError("SERPAPI_API_KEY is not set")
    return key


async def shopping_search(
    q: str,
    gl: str = "us",
    hl: str = "en",
    num: int = 20,
    no_cache: bool = True,
) -> Dict[str, Any]:
    """
    SerpAPI Google Shopping search.
    """
    api_key = _get_serpapi_key()

    try:
        n = max(1, min(int(num), 100))
    except Exception:
        n = 20

    params: Dict[str, Any] = {
        "engine": "google_shopping",
        "q": q,
        "api_key": api_key,
        "gl": gl,
        "hl": hl,
        "num": n,
    }

    if no_cache:
        params["no_cache"] = "true"

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(SERPAPI_BASE, params=params)
        try:
            r.raise_for_status()
        except Exception:
            raise ValueError(f"SerpAPI request failed: {r.status_code}\nBODY:\n{r.text}")

        data = r.json()

    if isinstance(data, dict) and data.get("error"):
        raise ValueError(f"SerpAPI error: {data.get('error')}")

    return data


async def google_search(
    q: str,
    gl: str = "us",
    hl: str = "en",
    num: int = 10,
    no_cache: bool = True,
) -> Dict[str, Any]:
    """
    SerpAPI Google (web) search (used for Costco fallback).
    """
    api_key = _get_serpapi_key()

    try:
        n = max(1, min(int(num), 100))
    except Exception:
        n = 10

    params: Dict[str, Any] = {
        "engine": "google",
        "q": q,
        "api_key": api_key,
        "gl": gl,
        "hl": hl,
        "num": n,
    }

    if no_cache:
        params["no_cache"] = "true"

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(SERPAPI_BASE, params=params)
        try:
            r.raise_for_status()
        except Exception:
            raise ValueError(f"SerpAPI request failed: {r.status_code}\nBODY:\n{r.text}")

        data = r.json()

    if isinstance(data, dict) and data.get("error"):
        raise ValueError(f"SerpAPI error: {data.get('error')}")

    return data

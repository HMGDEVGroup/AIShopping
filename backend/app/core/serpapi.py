import httpx
from typing import Any, Dict, Optional

from app.core.config import settings

SERPAPI_BASE = "https://serpapi.com/search.json"


def _bool_param(v: bool) -> str:
    return "true" if v else "false"


async def _serpapi_request(params: Dict[str, Any]) -> Dict[str, Any]:
    api_key = (getattr(settings, "SERPAPI_API_KEY", "") or "").strip()
    if not api_key:
        raise ValueError("SERPAPI_API_KEY is not set")

    params = dict(params)
    params["api_key"] = api_key

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(SERPAPI_BASE, params=params)
        try:
            r.raise_for_status()
        except Exception:
            raise ValueError(f"SerpApi request failed: {r.status_code}\nBODY:\n{r.text}")

        return r.json()


async def shopping_search(
    q: str,
    gl: str = "us",
    hl: str = "en",
    num: int = 10,
    no_cache: bool = False,
) -> Dict[str, Any]:
    """
    Google Shopping results via SerpApi.
    Returns payload containing 'shopping_results' when available.
    """
    params: Dict[str, Any] = {
        "engine": "google_shopping",
        "q": q,
        "gl": gl,
        "hl": hl,
        "num": max(1, min(int(num), 100)),
    }
    if no_cache:
        params["no_cache"] = _bool_param(True)

    return await _serpapi_request(params)


async def google_search(
    q: str,
    gl: str = "us",
    hl: str = "en",
    num: int = 10,
    no_cache: bool = False,
) -> Dict[str, Any]:
    """
    Standard Google web results via SerpApi.
    Returns payload containing 'organic_results' when available.
    """
    params: Dict[str, Any] = {
        "engine": "google",
        "q": q,
        "gl": gl,
        "hl": hl,
        "num": max(1, min(int(num), 100)),
    }
    if no_cache:
        params["no_cache"] = _bool_param(True)

    return await _serpapi_request(params)

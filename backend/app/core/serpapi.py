import os
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

SERPAPI_BASE = "https://serpapi.com/search.json"


def _get_serpapi_key() -> str:
    # Prefer pydantic settings, fallback to env
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
    include_membership: bool = True,
    num: int = 10,
) -> Dict[str, Any]:
    """
    Calls SerpAPI Google Shopping and returns the raw JSON response.

    Notes:
    - SerpAPI does not have a universal “include_membership” toggle; that concept is store-specific.
      We keep the parameter so the API stays stable and you can add membership filtering later.
    """
    api_key = _get_serpapi_key()

    # SerpAPI Google Shopping engine
    params: Dict[str, Any] = {
        "engine": "google_shopping",
        "q": q,
        "api_key": api_key,
        "gl": gl,
        "hl": hl,
    }

    # Best-effort: request more results so backend can sort/filter
    # SerpAPI uses "num" for some engines; if ignored, it won't break.
    try:
        params["num"] = max(1, min(int(num), 100))
    except Exception:
        params["num"] = 10

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.get(SERPAPI_BASE, params=params)
        try:
            r.raise_for_status()
        except Exception:
            raise ValueError(f"SerpAPI request failed: {r.status_code}\nBODY:\n{r.text}")

        data = r.json()

    # Normalize: if the engine returns an error payload, surface it clearly
    if isinstance(data, dict) and data.get("error"):
        raise ValueError(f"SerpAPI error: {data.get('error')}")

    return data

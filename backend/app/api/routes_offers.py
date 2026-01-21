from fastapi import APIRouter, HTTPException, Query
from app.core.serpapi import shopping_search
from app.schemas.offers import OffersResponse, OfferItem

router = APIRouter(prefix="/v1", tags=["offers"])

# Terms that usually indicate irrelevant medical/chiropractic tables for this app
NEGATIVE_HINTS = [
    "chiropractic",
    "chiropractor",
    "traction",
    "clinic",
    "medical",
    "armedica",
    "mettler",
    "flexion",
    "distraction",
]

def is_irrelevant(title: str, q: str) -> bool:
    t = (title or "").lower()
    # For now: drop obvious medical table results
    return any(h in t for h in NEGATIVE_HINTS)

@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str = Query(..., min_length=2),
    num: int = Query(10, ge=1, le=20),
    gl: str = Query("us"),
    hl: str = Query("en"),
):
    """
    Pulls Google Shopping offers via SerpAPI.
    Adds basic filtering and link normalization.
    """
    try:
        raw = await shopping_search(q, num=num, gl=gl, hl=hl)

        results = raw.get("shopping_results", []) or []

        offers = []
        for r in results:
            title = r.get("title", "Unknown")

            # Prefer product_link (common) then link (fallback)
            link = r.get("product_link") or r.get("link")

            # Basic relevance filtering (removes obvious medical/chiropractic tables)
            if is_irrelevant(title, q):
                continue

            offers.append(
                OfferItem(
                    title=title,
                    price=r.get("price"),
                    source=r.get("source") or r.get("seller"),
                    link=link,
                    thumbnail=r.get("thumbnail"),
                    delivery=r.get("delivery"),
                    rating=r.get("rating"),
                    reviews=r.get("reviews"),
                )
            )

        return OffersResponse(query=q, offers=offers, raw=None)

    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

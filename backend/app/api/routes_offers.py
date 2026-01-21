from fastapi import APIRouter, HTTPException, Query
from app.core.serpapi import shopping_search
from app.schemas.offers import OffersResponse, OfferItem

router = APIRouter(prefix="/v1", tags=["offers"])

NEGATIVE_HINTS = [
    "chiropractic",
    "chiropractor",
    "traction",
    "clinic",
    "medical",
    "treatment",
    "therapy",
    "adjusting",
    "bolster",
    "armedica",
    "mettler",
    "flexion",
    "distraction",
    "graham field",
]

def normalize(s: str) -> str:
    return (s or "").strip().lower()

def is_irrelevant(title: str, q: str) -> bool:
    t = normalize(title)

    # Drop obvious medical/treatment results
    if any(h in t for h in NEGATIVE_HINTS):
        return True

    # Require brand match for Chirp queries (tighten relevance)
    qn = normalize(q)
    if "chirp" in qn:
        # title must contain chirp OR contain "contour decompression"
        if ("chirp" not in t) and ("contour" not in t or "decompression" not in t):
            return True

    return False

@router.get("/offers", response_model=OffersResponse)
async def offers(
    q: str = Query(..., min_length=2),
    num: int = Query(10, ge=1, le=20),
    gl: str = Query("us"),
    hl: str = Query("en"),
):
    try:
        raw = await shopping_search(q, num=num, gl=gl, hl=hl)
        results = raw.get("shopping_results", []) or []

        offers = []
        for r in results:
            title = r.get("title", "Unknown")

            # SerpAPI tends to use product_link; link may exist on some results too
            link = r.get("product_link") or r.get("link")

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

from fastapi import APIRouter, HTTPException
from app.core.serpapi import shopping_search
from app.schemas.offers import OffersResponse, OfferItem

router = APIRouter(prefix="/v1", tags=["offers"])

@router.get("/offers", response_model=OffersResponse)
async def offers(q: str):
    try:
        raw = await shopping_search(q)

        results = raw.get("shopping_results", []) or []

        offers = []
        for r in results:
            offers.append(
                OfferItem(
                    title=r.get("title", "Unknown"),
                    price=r.get("price"),
                    source=r.get("source"),
                    link=r.get("link"),
                    thumbnail=r.get("thumbnail"),
                    delivery=r.get("delivery"),
                    rating=r.get("rating"),
                    reviews=r.get("reviews"),
                )
            )

        return OffersResponse(query=q, offers=offers, raw=None)

    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))
